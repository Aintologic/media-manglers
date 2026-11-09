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

from .play_targets import find_vlc
from .resources import DependencyStatus, RuntimeResources
from .tool_sources import TOOL_SOURCES, standard_locations


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
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

model_name = sys.argv[1]
result = {
    "python_path": sys.executable,
    "python_version": sys.version.split()[0],
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
    result["torch_version"] = str(getattr(torch, "__version__", "") or "")
    result["cuda_version"] = str(getattr(torch.version, "cuda", "") or "")
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_device_count"] = int(torch.cuda.device_count()) if result["cuda_available"] else 0
except Exception as exc:
    result["error"] += (" | " if result["error"] else "") + "Torch import failed: " + str(exc)
print(json.dumps(result), flush=True)
"""


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
) -> DependencyPreflightResult:
    """Check the runtime path without opening or processing any source media."""

    timestamp = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
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
        )
    )

    candidates = python_candidates
    if candidates is None:
        candidates = discover_python_candidates(
            resources,
            configured_python=configured_python,
            runner=runner,
        )
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
    selected_path = ""
    selected_probe: dict[str, object] = {}
    if candidate_results:
        selected_path, selected_probe = max(
            candidate_results,
            key=lambda item: _candidate_score(item[1]),
        )
        selected_path = str(selected_probe.get("python_path") or selected_path)
    python_ready = bool(selected_path and selected_probe.get("python_version"))
    python_detail = (
        f"Validated {len(candidate_results)} usable Python installation(s); selected the healthiest runtime."
        if python_ready and len(candidates) > 1
        else "The selected Python interpreter started successfully."
        if python_ready
        else "Only a Windows Store alias was found; choose an installed Python executable."
        if alias_candidates and not candidate_results
        else "No usable Python interpreter was found."
    )
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
        )
    )
    model_cached = bool(selected_probe.get("model_cached"))
    model_known = bool(selected_probe.get("model_known"))
    estimate = MODEL_DOWNLOAD_ESTIMATES.get(selected_model, "an unknown download size")
    model_detail = (
        "The selected model is already present in the standard Whisper cache."
        if model_cached
        else f"The selected model is not cached. First use may download {estimate}; approval is required before launch."
        if model_known
        else "The selected model name was not recognized by this Whisper installation."
    )
    dependencies.append(
        _dependency(
            "whisper_model",
            f"Whisper model: {selected_model}",
            "Controls transcription accuracy, runtime, and local model storage.",
            "ready" if model_cached else "needs_setup",
            path=str(selected_probe.get("model_cache_path") or ""),
            detail=model_detail,
            required=False,
            action_label="Approve download" if model_known and not model_cached else "Install guide" if not model_cached else "",
            action_kind="approve_model_download" if model_known and not model_cached else "install_guide" if not model_cached else "",
            checked_at=timestamp,
        )
    )

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
