"""Responsive, no-media dependency preflight for the Workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Callable

from media_manglers.core.user_folders import addons_root

from .play_targets import find_vlc
from .resources import DependencyStatus, RuntimeResources
from .tool_sources import FOUND_BUNDLED, FOUND_DOWNLOADED, FOUND_ON_PC, TOOL_SOURCES, bundled_tool, found_by_text, standard_locations


CommandRunner = Callable[[list[str], int, dict[str, str] | None], subprocess.CompletedProcess[str]]

MODEL_DOWNLOAD_ESTIMATES = {
    "tiny": "about 75 MB",
    "tiny.en": "about 75 MB",
    "base": "about 142 MB",
    "base.en": "about 142 MB",
    "small": "about 466 MB",
    "small.en": "about 466 MB",
    "medium": "about 1.5 GB",
    "medium.en": "about 1.5 GB",
    "large": "about 2.9 GB",
    "large-v1": "about 2.9 GB",
    "large-v2": "about 2.9 GB",
    "large-v3": "about 2.9 GB",
    "turbo": "about 1.6 GB",
}


@dataclass(slots=True)
class DependencyPreflightResult:
    dependencies: list[DependencyStatus]
    python_exe: str
    ffmpeg_exe: str
    ffprobe_exe: str
    python_candidates: list[str]
    checked_at: str
    ytdlp_exe: str = ""


class DependencyCheckStopped(Exception):
    """The readiness check was stopped (193). Nothing it found is kept; it runs again next time."""


def _end_process_tree(process: subprocess.Popen[str]) -> None:
    # A probe can start its own children (the py launcher, a yt-dlp bootloader), and a child left
    # running holds the probe's output open, so the whole tree is ended, not just the probe.
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if process.poll() is None:
        process.kill()


class StoppableRunner:
    """Runs each readiness probe so that it can be stopped at once, with everything it started.

    No wait is without a limit: a probe that runs past its time, or that is stopped, has its
    whole process tree ended, and its output is waited for two seconds at most (159, 193).
    """

    def __init__(self) -> None:
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def stop(self) -> None:
        self._stopped.set()
        with self._lock:
            process = self._process
        if process is not None:
            _end_process_tree(process)

    def __call__(
        self, argv: list[str], timeout: int, env: dict[str, str] | None
    ) -> subprocess.CompletedProcess[str]:
        if self.stopped:
            raise DependencyCheckStopped()
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._process = process
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if not self.stopped and time.monotonic() < deadline:
                        continue
                    _end_process_tree(process)
                    try:
                        process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass   # its reader threads are daemons; nothing waits for them
                    if self.stopped:
                        raise DependencyCheckStopped() from None
                    raise subprocess.TimeoutExpired(argv, timeout) from None
        finally:
            with self._lock:
                self._process = None
        if self.stopped:
            raise DependencyCheckStopped()
        return subprocess.CompletedProcess(argv, process.returncode, stdout or "", stderr or "")


def _default_runner(
    argv: list[str], timeout: int, env: dict[str, str] | None
) -> subprocess.CompletedProcess[str]:
    return StoppableRunner()(argv, timeout, env)


def _unique_existing(values: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip().strip('"')
        if not text:
            continue
        path = Path(text)
        if not path.is_file():
            continue
        resolved = str(path.resolve())
        key = resolved.casefold()
        if key not in seen:
            seen.add(key)
            found.append(resolved)
    return found


def _is_windows_store_alias(path: str) -> bool:
    normalized = path.replace("/", "\\").casefold()
    return "\\microsoft\\windowsapps\\" in normalized or "\\windowsapps\\python" in normalized


def discover_python_candidates(
    resources: RuntimeResources,
    *,
    configured_python: str = "",
    runner: CommandRunner = _default_runner,
) -> list[str]:
    if configured_python:
        return _unique_existing([configured_python])
    candidates: list[str] = []
    primary = str(resources.python_exe or "").strip()
    if primary:
        primary_path = Path(primary)
        if primary_path.name.casefold() in {"py", "py.exe"}:
            try:
                result = runner(
                    [primary, "-3", "-c", "import sys; print(sys.executable)"],
                    30,
                    None,
                )
                if result.returncode == 0:
                    candidates.extend(result.stdout.splitlines())
            except (OSError, subprocess.SubprocessError):
                pass
        else:
            candidates.append(primary)
    direct = shutil.which("python.exe") or shutil.which("python")
    if direct:
        candidates.append(direct)
    where = shutil.which("where.exe")
    if where:
        try:
            result = runner([where, "python"], 15, None)
            if result.returncode == 0:
                candidates.extend(result.stdout.splitlines())
        except (OSError, subprocess.SubprocessError):
            pass
    found = _unique_existing(candidates)
    if not any(not _is_windows_store_alias(item) for item in found):
        # 188: nothing usable on PATH; look where the Python installers put it.
        found = _unique_existing(found + standard_locations(TOOL_SOURCES["python"]))
    return found


def _chosen_or_found(configured: str, found: str) -> tuple[str, str]:
    """188: a chosen FFmpeg, FFprobe or yt-dlp that is gone gives way to the one the lookup found."""

    configured = str(configured or "").strip().strip('"')
    if configured and not Path(configured).is_file() and found and found != configured and Path(found).is_file():
        return found, f"Your chosen path is missing ({configured}); using {found}. "
    return configured or found, ""


_PYTHON_PROBE = r"""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

private_python = False
try:
    # Installer plan, Stage 1: our own Python gets our downloaded speech libraries first, as every helper
    # run does (media_manglers.cli.main); any other Python is left exactly as it is.
    from media_manglers.core.private_runtime import is_private_python, use_addons
    use_addons()
    private_python = bool(is_private_python())
except Exception:
    pass

model_name = sys.argv[1]
result = {
    "python_path": sys.executable,
    "python_version": sys.version.split()[0],
    "private_python": private_python,
    "argos_available": importlib.util.find_spec("argostranslate") is not None,
    "torch_path": "",
    "helper_import_ok": False,
    "whisper_import_ok": False,
    "whisper_version": "",
    "torch_import_ok": False,
    "torch_version": "",
    "cuda_version": "",
    "cuda_available": False,
    "cuda_device_count": 0,
    "model_known": False,
    "model_cached": False,
    "model_cache_path": "",
    "error": "",
}
try:
    import media_manglers
    result["helper_import_ok"] = True
except Exception as exc:
    result["error"] = "Media Manglers helper import failed: " + str(exc)
try:
    import whisper
    result["whisper_import_ok"] = True
    try:
        result["whisper_version"] = importlib.metadata.version("openai-whisper")
    except Exception:
        result["whisper_version"] = str(getattr(whisper, "__version__", "") or "")
    models = getattr(whisper, "_MODELS", {})
    if model_name in models:
        result["model_known"] = True
        filename = os.path.basename(urlparse(models[model_name]).path)
        cache_path = Path.home() / ".cache" / "whisper" / filename
        result["model_cache_path"] = str(cache_path)
        result["model_cached"] = cache_path.is_file()
except Exception as exc:
    result["error"] += (" | " if result["error"] else "") + "Whisper import failed: " + str(exc)
try:
    import torch
    result["torch_import_ok"] = True
    result["torch_path"] = str(getattr(torch, "__file__", "") or "")
    result["torch_version"] = str(getattr(torch, "__version__", "") or "")
    result["cuda_version"] = str(getattr(torch.version, "cuda", "") or "")
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_device_count"] = int(torch.cuda.device_count()) if result["cuda_available"] else 0
except Exception as exc:
    result["error"] += (" | " if result["error"] else "") + "Torch import failed: " + str(exc)
print(json.dumps(result), flush=True)
"""


# Installer plan, Stage 3: whether each model a workflow will load is on this PC and is the file Whisper published.
# It runs once, in the Python that will run Whisper, through the same check every feature's load goes through
# (whisper_models), reading Whisper's model table without importing PyTorch. It never downloads anything.
_MODEL_PROBE = r"""
import json
import sys
try:
    from media_manglers.core.private_runtime import use_addons
    use_addons()
except Exception:
    pass
from media_manglers.core.whisper_models import model_state, model_table
table = model_table()
print(json.dumps({name: model_state(name, table=table).to_dict() for name in sys.argv[1:]}), flush=True)
"""

# The models a workflow will load: the selected model; base.en, which every review's voice detection uses; and the
# AI Video Editor's quick-pass model. (row key, what it is for)
MODEL_ROWS = (
    ("whisper_model", "Transcripts with the selected model."),
    ("whisper_model_voice", "Finds which track is your voice, in every review and scan."),
    ("whisper_model_quick", "The AI Video Editor's quick passes over a whole race."),
)
VOICE_MODEL = "base.en"


def required_models(selected_model: str, quick_model: str = "") -> list[tuple[str, str, str]]:
    """(row key, model, purpose) for each model a workflow will load, each model once."""

    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for (key, purpose), model in zip(MODEL_ROWS, (selected_model, VOICE_MODEL, quick_model)):
        model = str(model or "").strip()
        if model and model.casefold() not in seen:
            seen.add(model.casefold())
            rows.append((key, model, purpose))
    return rows


def _model_states(python: str, names: list[str], backend_source_root: Path | None,
                  runner: CommandRunner) -> dict[str, dict[str, object]]:
    if not python or not names:
        return {}
    env = dict(os.environ)
    if backend_source_root:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(backend_source_root) + (os.pathsep + existing if existing else "")
    try:
        # Checking a model reads the whole file once, so a large one takes a while on a slow disk.
        result = runner([python, "-c", _MODEL_PROBE, *names], 600, env)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    line = next((item.strip() for item in reversed(result.stdout.splitlines())
                 if item.strip().startswith("{") and item.strip().endswith("}")), "")
    try:
        payload = json.loads(line) if line else {}
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(name): value for name, value in payload.items() if isinstance(value, dict) and value.get("state")}


def _model_row(key: str, model: str, purpose: str, state: dict[str, object], *, checked_at: str) -> DependencyStatus:
    found = str(state.get("state") or "")
    path = str(state.get("path") or "")
    estimate = MODEL_DOWNLOAD_ESTIMATES.get(model, "an unknown download size")
    approve = {"action_label": "Approve download", "action_kind": "approve_model_download"}
    if found == "valid":
        status, detail, actions = "ready", (
            "Already on this PC and matches the file Whisper published, so it is used as it is, with no download."), {}
    elif found == "damaged":
        status, detail, actions = "needs_setup", (
            "The copy on this PC does not match the file Whisper published, so it is not used, and it is never "
            f"replaced without your approval. Approve its download ({estimate}) to replace it."), approve
    elif found == "missing":
        status, detail, actions = "needs_setup", (
            f"Not on this PC yet. Approve its download ({estimate}) to use it; nothing downloads without your "
            "approval."), approve
    elif found == "unknown":
        status, detail, actions = "needs_setup", (
            "This Whisper does not know a model by that name. Choose another Whisper model in Settings."), {
            "action_label": "Install guide", "action_kind": "install_guide"}
    else:
        status, detail, actions = "needs_setup", (
            "Not checked: the Python that runs Whisper could not check its models. Fix the rows above, then "
            "Refresh readiness."), {}
    return _dependency(
        key,
        f"Whisper model: {model}",
        purpose,
        status,
        path=path,
        detail=detail,
        required=False,
        checked_at=checked_at,
        found_by=FOUND_ON_PC if found == "valid" else "",
        model=model,
        **actions,
    )


def _probe_python_candidate(
    candidate: str,
    model_name: str,
    backend_source_root: Path | None,
    runner: CommandRunner,
) -> dict[str, object]:
    env = dict(os.environ)
    if backend_source_root:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(backend_source_root) + (os.pathsep + existing if existing else "")
    result = runner([candidate, "-c", _PYTHON_PROBE, model_name], 120, env)
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout or "Python probe failed").strip())
    json_line = next(
        (
            line.strip()
            for line in reversed(result.stdout.splitlines())
            if line.strip().startswith("{") and line.strip().endswith("}")
        ),
        "",
    )
    if not json_line:
        raise ValueError("Python probe did not return structured readiness data.")
    payload = json.loads(json_line)
    if not isinstance(payload, dict):
        raise ValueError("Python probe returned an unexpected result.")
    return payload


def _candidate_score(payload: dict[str, object]) -> int:
    score = 0
    if payload.get("whisper_import_ok"):
        score += 20
    if payload.get("torch_import_ok"):
        score += 20
        score += 10
    if payload.get("cuda_available"):
        score += 100
    if payload.get("helper_import_ok"):
        score += 5
    return score


# Installer plan, Stage 1 (decision D7): the only two reasons a Python already on the PC is used instead of ours.
KEPT_FOR_GRAPHICS_CARD = "Kept your Python because it can use your graphics card."
KEPT_FOR_ARGOS = "Kept your Python because it has Argos Translate."


def _same_file(first: str, second: str) -> bool:
    if not first or not second:
        return False
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def select_python(
    candidate_results: list[tuple[str, dict[str, object]]],
    private_python: str = "",
    *,
    translation_needs_argos: bool = False,
) -> tuple[str, dict[str, object], str]:
    """The Python the Workbench uses, with the note its row shows: (path, probe, note).

    Our private Python, when it is there and starts with the helper, unless one of the two kept exceptions
    applies to a Python already on the PC:
    1. it imports Whisper, the helper and PyTorch with working CUDA, while ours has no graphics-card support;
    2. translation runs locally (Local or Hybrid), ours lacks Argos Translate, and it has Argos with Whisper
       and the helper.
    Without our private Python (a run from the source, or a damaged copy) the healthiest Python found is used,
    as before. A chosen Python never reaches here: it is the only candidate.
    """

    if not candidate_results:
        return "", {}, ""
    ours = next(((path, probe) for path, probe in candidate_results if _same_file(path, private_python)), None)
    if ours is not None and ours[1].get("python_version") and ours[1].get("helper_import_ok"):
        others = [(path, probe) for path, probe in candidate_results if not _same_file(path, private_python)]
        if not ours[1].get("cuda_available"):
            for path, probe in others:
                if (probe.get("whisper_import_ok") and probe.get("helper_import_ok") and probe.get("torch_import_ok")
                        and probe.get("cuda_available")):
                    return path, probe, KEPT_FOR_GRAPHICS_CARD
        if translation_needs_argos and not ours[1].get("argos_available"):
            for path, probe in others:
                if probe.get("argos_available") and probe.get("whisper_import_ok") and probe.get("helper_import_ok"):
                    return path, probe, KEPT_FOR_ARGOS
        return ours[0], ours[1], ""
    path, probe = max(candidate_results, key=lambda item: _candidate_score(item[1]))
    return path, probe, ""


def translation_needs_argos(settings: dict[str, object]) -> bool:
    """Whether translation runs locally with Argos: a target language is set and the mode is Local or Hybrid."""

    targets = str(settings.get("translate_to") or "").strip()
    mode = str(settings.get("processing_mode") or "Local").strip().casefold()
    return bool(targets) and mode in {"local", "hybrid"}


def _tool_version(
    executable: str,
    args: list[str],
    runner: CommandRunner,
) -> tuple[bool, str, str]:
    if not executable or not Path(executable).is_file():
        return False, "", "The configured executable was not found or is inaccessible."
    try:
        result = runner([executable, *args], 30, None)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", str(exc)
    output = (result.stdout or result.stderr or "").strip()
    first_line = output.splitlines()[0].strip() if output else ""
    return result.returncode == 0, first_line, (result.stderr or "").strip()


def _dependency(
    key: str,
    name: str,
    purpose: str,
    status: str,
    *,
    path: str = "",
    version: str = "",
    detail: str = "",
    required: bool = True,
    action_label: str = "",
    action_kind: str = "",
    checked_at: str = "",
    found_by: str = "",
    model: str = "",
) -> DependencyStatus:
    return DependencyStatus(
        name=name,
        status=status,
        path=path,
        detail=detail,
        required=required,
        key=key,
        purpose=purpose,
        version=version,
        action_label=action_label,
        action_kind=action_kind,
        last_checked=checked_at,
        found_by=found_by,
        model=model,
    )


def run_dependency_preflight(
    resources: RuntimeResources,
    *,
    selected_model: str,
    configured_python: str = "",
    configured_ffmpeg: str = "",
    configured_ffprobe: str = "",
    configured_ytdlp: str = "",
    python_candidates: list[str] | None = None,
    runner: CommandRunner = _default_runner,
    checked_at: str | None = None,
    configured_vlc: str = "",
    vlc_finder: Callable[[str], str] = find_vlc,
    translation_needs_argos: bool = False,
    quick_model: str = "",
) -> DependencyPreflightResult:
    """Check the runtime path without opening or processing any source media."""

    timestamp = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundled_dir = str(getattr(resources, "bundled_dir", "") or "")
    private_python = bundled_tool("python", bundled_dir) if bundled_dir else ""

    def where(path: str, chosen: str = "") -> str:
        return found_by_text(path, chosen=chosen, bundled_dir=bundled_dir or None)
    dependencies: list[DependencyStatus] = []
    sidecar_ready = bool(
        resources.script_path
        and resources.script_path.is_file()
        and resources.backend_source_root
        and (resources.backend_source_root / "media_manglers" / "__main__.py").is_file()
    )
    dependencies.append(
        _dependency(
            "backend_sidecar",
            "Media Manglers helpers",
            "Provides the evidence, transcript, and archive operations used by the Workbench.",
            "ready" if sidecar_ready else "needs_setup",
            path=str(resources.backend_source_root or resources.script_path or ""),
            detail=(
                "The tracked PowerShell wrapper and Python helper sidecar are present."
                if sidecar_ready
                else "The application folder is missing Video Mangler.ps1 or python-core/src/media_manglers."
            ),
            action_label="Repair" if not sidecar_ready else "",
            action_kind="repair_app" if not sidecar_ready else "",
            checked_at=timestamp,
        )
    )

    ytdlp, ytdlp_note = _chosen_or_found(configured_ytdlp, resources.ytdlp_exe)
    ytdlp_ok, ytdlp_version, ytdlp_error = _tool_version(ytdlp, ["--version"], runner)
    ytdlp_status = "ready" if ytdlp_ok else "needs_setup"
    ytdlp_detail = ytdlp_error or "yt-dlp started successfully and can be used for web-video reviews."
    if ytdlp_ok:
        match = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})", ytdlp_version)
        if match:
            release_date = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
            checked_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if checked_date.tzinfo is None:
                checked_date = checked_date.replace(tzinfo=timezone.utc)
            age_days = max(0, (checked_date - release_date).days)
            if age_days > 90:
                ytdlp_status = "update_recommended"
                ytdlp_detail = (
                    f"This yt-dlp build is {age_days} days old. Web providers change frequently; "
                    "update yt-dlp before starting a URL review."
                )
    dependencies.append(
        _dependency(
            "ytdlp",
            "yt-dlp",
            "Downloads supported web-video URLs before local review.",
            ytdlp_status,
            path=ytdlp,
            version=ytdlp_version,
            detail=ytdlp_note + ytdlp_detail,
            required=False,
            action_label="Choose path" if ytdlp_status == "needs_setup" else "Update guide" if ytdlp_status == "update_recommended" else "",
            action_kind="choose_ytdlp" if ytdlp_status == "needs_setup" else "install_guide" if ytdlp_status == "update_recommended" else "",
            checked_at=timestamp,
            found_by=where(ytdlp, configured_ytdlp) if ytdlp_ok else "",
        )
    )

    powershell_ok, powershell_version, powershell_error = _tool_version(
        resources.powershell_exe, ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"], runner
    )
    dependencies.append(
        _dependency(
            "powershell",
            "Windows PowerShell",
            "Runs the proven Video Mangler workflow wrapper.",
            "ready" if powershell_ok else "needs_setup",
            path=resources.powershell_exe,
            version=powershell_version,
            detail=powershell_error or "PowerShell started successfully.",
            action_label="Install guide" if not powershell_ok else "",
            action_kind="install_guide" if not powershell_ok else "",
            checked_at=timestamp,
            found_by=where(resources.powershell_exe) if powershell_ok else "",
        )
    )

    candidates = python_candidates
    if candidates is None:
        candidates = discover_python_candidates(
            resources,
            configured_python=configured_python,
            runner=runner,
        )
    if private_python and not configured_python and Path(private_python).is_file():
        # Installer plan, Stage 1: our own Python is always one of the candidates, and is looked at first.
        candidates = [private_python, *candidates]
    candidates = _unique_existing(candidates)
    candidate_results: list[tuple[str, dict[str, object]]] = []
    alias_candidates = [item for item in candidates if _is_windows_store_alias(item)]
    for candidate in candidates:
        if _is_windows_store_alias(candidate):
            continue
        try:
            candidate_results.append(
                (
                    candidate,
                    _probe_python_candidate(
                        candidate,
                        selected_model,
                        resources.backend_source_root,
                        runner,
                    ),
                )
            )
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            continue
    selected_path, selected_probe, kept_note = select_python(
        candidate_results, private_python, translation_needs_argos=translation_needs_argos
    )
    uses_ours = bool(selected_path) and _same_file(selected_path, private_python)
    if selected_path and not uses_ours:
        selected_path = str(selected_probe.get("python_path") or selected_path)
    python_ready = bool(selected_path and selected_probe.get("python_version"))
    python_detail = (
        kept_note
        if python_ready and kept_note
        else "Media Manglers' own Python started successfully."
        if python_ready and uses_ours
        else f"Validated {len(candidate_results)} usable Python installation(s); selected the healthiest runtime."
        if python_ready and len(candidates) > 1
        else "The selected Python interpreter started successfully."
        if python_ready
        else "Only a Windows Store alias was found; choose an installed Python executable."
        if alias_candidates and not candidate_results
        else "No usable Python interpreter was found."
    )
    python_found_by = where(selected_path, configured_python) if python_ready else ""
    dependencies.append(
        _dependency(
            "python",
            "Python runtime",
            "Runs the Media Manglers helper package and Local Whisper.",
            "ready" if python_ready else "needs_setup",
            path=selected_path or (alias_candidates[0] if alias_candidates else configured_python),
            version=str(selected_probe.get("python_version") or ""),
            detail=python_detail,
            action_label="Choose path" if not python_ready else "Choose path",
            action_kind="choose_python",
            checked_at=timestamp,
            found_by=python_found_by,
        )
    )

    helper_ready = bool(selected_probe.get("helper_import_ok"))
    dependencies.append(
        _dependency(
            "python_helper",
            "Media Manglers Python package",
            "Connects the Workbench to the tracked local helper code.",
            "ready" if helper_ready else "needs_setup",
            path=str(resources.backend_source_root or ""),
            detail=(
                "The selected Python runtime imported the tracked helper package."
                if helper_ready
                else "The selected Python runtime could not import the tracked helper package."
            ),
            action_label="Repair" if not helper_ready else "",
            action_kind="repair_app" if not helper_ready else "",
            checked_at=timestamp,
        )
    )

    ffmpeg, ffmpeg_note = _chosen_or_found(configured_ffmpeg, resources.ffmpeg_exe)
    ffmpeg_ok, ffmpeg_version, ffmpeg_error = _tool_version(ffmpeg, ["-version"], runner)
    dependencies.append(
        _dependency(
            "ffmpeg",
            "FFmpeg",
            "Extracts audio, frames, and clips without changing source media.",
            "ready" if ffmpeg_ok else "needs_setup",
            path=ffmpeg,
            version=ffmpeg_version,
            detail=ffmpeg_note + (ffmpeg_error or "FFmpeg version check completed successfully."),
            action_label="Choose path",
            action_kind="choose_ffmpeg",
            checked_at=timestamp,
            found_by=where(ffmpeg, configured_ffmpeg) if ffmpeg_ok else "",
        )
    )
    ffprobe, ffprobe_note = _chosen_or_found(configured_ffprobe, resources.ffprobe_exe)
    ffprobe_ok, ffprobe_version, ffprobe_error = _tool_version(ffprobe, ["-version"], runner)
    dependencies.append(
        _dependency(
            "ffprobe",
            "FFprobe",
            "Reads source duration, tracks, and stream metadata.",
            "ready" if ffprobe_ok else "needs_setup",
            path=ffprobe,
            version=ffprobe_version,
            detail=ffprobe_note + (ffprobe_error or "FFprobe version check completed successfully."),
            action_label="Choose path",
            action_kind="choose_ffprobe",
            checked_at=timestamp,
            found_by=where(ffprobe, configured_ffprobe) if ffprobe_ok else "",
        )
    )

    whisper_ready = bool(selected_probe.get("whisper_import_ok"))
    dependencies.append(
        _dependency(
            "whisper",
            "Local Whisper",
            "Creates local transcripts used by review and evidence workflows.",
            "ready" if whisper_ready else "needs_setup",
            path=selected_path,
            version=str(selected_probe.get("whisper_version") or ""),
            detail=(
                "Whisper imported in the same Python runtime the Workbench will pass to the backend."
                if whisper_ready
                else str(selected_probe.get("error") or "Whisper is not installed in the selected runtime.")
            ),
            required=False,
            action_label="Install guide" if not whisper_ready else "",
            action_kind="install_guide" if not whisper_ready else "",
            checked_at=timestamp,
            found_by=(FOUND_BUNDLED if uses_ours else FOUND_ON_PC) if whisper_ready else "",
        )
    )
    # Installer plan, Stage 3: one row per model a workflow will load, each checked against the file Whisper
    # published, in the Python that runs Whisper (ours, or one of yours kept under an exception). A valid model
    # already in the cache is reused; a missing or damaged one offers Approve download, and nothing downloads
    # until you approve it.
    models = required_models(selected_model, quick_model)
    states = (_model_states(selected_path, [model for _key, model, _purpose in models], resources.backend_source_root,
                            runner)
              if selected_path and selected_probe.get("helper_import_ok") else {})
    for key, model, purpose in models:
        state = states.get(model) or {}
        if not state and model == selected_model and selected_probe.get("model_known") is not None:
            # The checksum probe did not answer: the main probe's own look at the cache is the best there is.
            if not selected_probe.get("model_known"):
                state = {"state": "unknown"}
            else:
                state = {"state": "valid" if selected_probe.get("model_cached") else "missing",
                         "path": selected_probe.get("model_cache_path") or ""}
        dependencies.append(_model_row(key, model, purpose, state, checked_at=timestamp))

    torch_ready = bool(selected_probe.get("torch_import_ok"))
    dependencies.append(
        _dependency(
            "torch",
            "PyTorch",
            "Runs Local Whisper on CPU or CUDA.",
            "ready" if torch_ready else "needs_setup",
            path=selected_path,
            version=str(selected_probe.get("torch_version") or ""),
            detail=str(selected_probe.get("error") or "PyTorch imported successfully."),
            required=False,
            action_label="Install guide" if not torch_ready else "",
            action_kind="install_guide" if not torch_ready else "",
            checked_at=timestamp,
            found_by=(
                found_by_text(str(selected_probe.get("torch_path") or ""), bundled_dir=bundled_dir or None,
                              downloaded_dir=addons_root())
                if uses_ours else FOUND_ON_PC
            ) if torch_ready else "",
        )
    )
    cuda_ready = bool(selected_probe.get("cuda_available"))
    dependencies.append(
        _dependency(
            "cuda",
            "CUDA acceleration",
            "Speeds up Local Whisper when a compatible GPU runtime is available.",
            "ready" if cuda_ready else "optional",
            path=selected_path,
            version=str(selected_probe.get("cuda_version") or ""),
            detail=(
                f"CUDA is available with {int(selected_probe.get('cuda_device_count') or 0)} detected device(s)."
                if cuda_ready
                else "CUDA is not available in the selected Python runtime. CPU fallback is checked separately."
            ),
            required=False,
            action_label="Learn more" if not cuda_ready else "",
            action_kind="learn_more" if not cuda_ready else "",
            checked_at=timestamp,
        )
    )
    cpu_ready = whisper_ready and torch_ready
    dependencies.append(
        _dependency(
            "cpu_fallback",
            "CPU fallback",
            "Allows Local Whisper to run without CUDA, usually more slowly.",
            "ready" if cpu_ready else "unavailable",
            path=selected_path,
            detail=(
                "Whisper and PyTorch can run on CPU. Long recordings may take substantially longer."
                if cpu_ready
                else "CPU fallback needs both Whisper and PyTorch in the selected runtime."
            ),
            required=False,
            action_label="Repair" if not cpu_ready else "",
            action_kind="repair_runtime" if not cpu_ready else "",
            checked_at=timestamp,
        )
    )
    # 188: VLC is optional (the built-in player needs nothing). It is only looked for, the same
    # way Settings > Video player looks for it, and never started.
    vlc = vlc_finder(configured_vlc)
    dependencies.append(
        _dependency(
            "vlc",
            "VLC media player",
            "Plays recordings in VLC when Settings > Video player is set to VLC.",
            "ready" if vlc else "optional",
            path=vlc,
            detail=(
                "VLC was found. Settings > Video player decides whether recordings open in it."
                if vlc
                else "VLC was not found. It is needed only if Settings > Video player is set to VLC; "
                "after installing it, choose Check readiness, or point to it in Settings > Video player."
            ),
            required=False,
            checked_at=timestamp,
        )
    )
    return DependencyPreflightResult(
        dependencies=dependencies,
        python_exe=selected_path,
        ffmpeg_exe=ffmpeg if ffmpeg_ok else "",
        ffprobe_exe=ffprobe if ffprobe_ok else "",
        python_candidates=candidates,
        checked_at=timestamp,
        ytdlp_exe=ytdlp if ytdlp_ok else "",
    )
