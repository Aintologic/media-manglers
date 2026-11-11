"""Source and packaged runtime resource discovery for the Workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys

from .tool_sources import bundled_tools_dir, find_tool, found_by_text


RUNTIME_ROOT_OVERRIDE = "MEDIA_MANGLERS_WORKBENCH_ROOT"


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    status: str
    path: str = ""
    detail: str = ""
    required: bool = True
    key: str = ""
    purpose: str = ""
    version: str = ""
    action_label: str = ""
    action_kind: str = ""
    last_checked: str = ""
    # Where the tool came from, in plain words: "Bundled with Media Manglers", "Downloaded by Media
    # Manglers", "Your chosen path", "Already on this PC" or "Part of Windows" (installer plan, Stage 1).
    found_by: str = ""
    # For a model row: the Whisper model it is about (Stage 3).
    model: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def display_status(self) -> str:
        return {
            "ready": "Ready",
            "not_checked": "Not checked yet",
            "checking": "Checking…",
            "needs_setup": "Needs setup",
            "update_recommended": "Update recommended",
            "unavailable": "Unavailable",
            "optional": "Optional",
            "missing": "Needs setup",
            "info": "Not checked yet",
        }.get(self.status, self.status.replace("_", " ").title())


@dataclass(slots=True)
class RuntimeResources:
    app_root: Path
    script_path: Path | None
    backend_source_root: Path | None
    icon_path: Path | None
    powershell_exe: str
    python_exe: str
    ffmpeg_exe: str
    ffprobe_exe: str
    packaged: bool
    ytdlp_exe: str = ""
    dependencies: list[DependencyStatus] = field(default_factory=list)
    preflight_complete: bool = False
    last_dependency_check: str = ""
    python_candidates: list[str] = field(default_factory=list)
    # Media Manglers' own tools folder (``<app folder>\runtime``) when it holds any of them; "" otherwise.
    bundled_dir: str = ""

    @property
    def backend_ready(self) -> bool:
        return all(item.ready for item in self.dependencies if item.required)


def is_packaged_app() -> bool:
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path.absolute()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def candidate_app_roots() -> list[Path]:
    override = os.environ.get(RUNTIME_ROOT_OVERRIDE, "").strip()
    module_root = Path(__file__).resolve().parents[2]
    executable_root = Path(sys.executable).resolve().parent
    roots = [Path(override)] if override else []
    roots.extend([executable_root, module_root, Path.cwd()])
    return _unique_paths(roots)


def _first_existing(roots: list[Path], relatives: tuple[str, ...], *, directory: bool = False) -> Path | None:
    for root in roots:
        for relative in relatives:
            candidate = root / relative
            if candidate.is_dir() if directory else candidate.is_file():
                return candidate
    return None


def discover_runtime_resources(configured_paths: dict[str, object] | None = None) -> RuntimeResources:
    configured_paths = configured_paths or {}
    roots = candidate_app_roots()
    script_path = _first_existing(roots, ("Video Mangler.ps1", "backend/Video Mangler.ps1"))
    backend_source_root = _first_existing(
        roots,
        ("python-core/src", "src"),
        directory=True,
    )
    if backend_source_root and not (backend_source_root / "media_manglers" / "__main__.py").is_file():
        backend_source_root = None
    icon_path = _first_existing(
        roots,
        ("Video Mangler.ico", "assets/Video Mangler.ico", "resources/Video Mangler.ico"),
    )
    # 188 and installer plan Stage 1: the path the user chose, then (FFprobe) beside the FFmpeg in use,
    # then Media Manglers' own copy, then PATH, then the tool's own install folders. A chosen Python is
    # kept even when it is missing, so the check says so rather than using another one.
    bundled = bundled_tools_dir()
    bundled_dir = str(bundled) if bundled.is_dir() else ""
    chosen_python = str(configured_paths.get("dependency_python_path") or "").strip()
    chosen_ffmpeg = str(configured_paths.get("dependency_ffmpeg_path") or "")
    chosen_ffprobe = str(configured_paths.get("dependency_ffprobe_path") or "")
    powershell_exe = find_tool("powershell").path
    python_exe = chosen_python or find_tool("python", bundled_dir=bundled_dir or None).path
    ffmpeg = find_tool("ffmpeg", chosen_ffmpeg, bundled_dir=bundled_dir or None)
    ffprobe = find_tool("ffprobe", chosen_ffprobe, beside=ffmpeg.path, bundled_dir=bundled_dir or None)
    ytdlp = find_tool("ytdlp", str(configured_paths.get("dependency_ytdlp_path") or ""))
    ffmpeg_exe, ffprobe_exe, ytdlp_exe = ffmpeg.path, ffprobe.path, ytdlp.path
    app_root = script_path.parent if script_path else roots[0]

    def where(path: str, chosen: str = "") -> str:
        return found_by_text(path, chosen=chosen, bundled_dir=bundled_dir or None)

    dependencies = [
        DependencyStatus(
            "Media Manglers helpers",
            "ready" if script_path and backend_source_root else "needs_setup",
            str(script_path or ""),
            (
                "PowerShell wrapper and Python helper source were found."
                if script_path and backend_source_root
                else "Video Mangler.ps1 or python-core/src/media_manglers is missing from the application folder."
            ),
            key="backend_sidecar",
            purpose="Provides the evidence, transcript, and archive operations used by the Workbench.",
            action_label="Repair" if not (script_path and backend_source_root) else "",
            action_kind="repair_app" if not (script_path and backend_source_root) else "",
        ),
        DependencyStatus(
            "Windows PowerShell",
            "ready" if powershell_exe else "needs_setup",
            powershell_exe,
            "Used to run the proven Video Mangler workflow.",
            key="powershell",
            purpose="Runs the proven Video Mangler workflow wrapper.",
            action_label="Install guide" if not powershell_exe else "",
            action_kind="install_guide" if not powershell_exe else "",
            found_by=where(powershell_exe),
        ),
        DependencyStatus(
            "Python helper runtime",
            "not_checked" if python_exe else "needs_setup",
            python_exe,
            "Required by the PowerShell workflow for evidence, transcript, and archive helpers.",
            key="python",
            purpose="Runs the Media Manglers helper package and Local Whisper.",
            action_label="Check" if python_exe else "Choose path",
            action_kind="check" if python_exe else "choose_python",
            found_by=where(python_exe, chosen_python),
        ),
        DependencyStatus(
            "FFmpeg",
            "not_checked" if ffmpeg_exe else "needs_setup",
            ffmpeg_exe,
            "Required for media probing, audio extraction, frames, and clips.",
            key="ffmpeg",
            purpose="Extracts audio, frames, and clips without changing source media.",
            action_label="Check" if ffmpeg_exe else "Choose path",
            action_kind="check" if ffmpeg_exe else "choose_ffmpeg",
            found_by=where(ffmpeg_exe, chosen_ffmpeg),
        ),
        DependencyStatus(
            "FFprobe",
            "not_checked" if ffprobe_exe else "needs_setup",
            ffprobe_exe,
            "Required for source metadata and stream discovery.",
            key="ffprobe",
            purpose="Reads source duration, tracks, and stream metadata.",
            action_label="Check" if ffprobe_exe else "Choose path",
            action_kind="check" if ffprobe_exe else "choose_ffprobe",
            found_by=where(ffprobe_exe, chosen_ffprobe),
        ),
        DependencyStatus(
            "yt-dlp",
            "not_checked" if ytdlp_exe else "needs_setup",
            ytdlp_exe,
            "Required only when Full Review downloads web videos.",
            required=False,
            key="ytdlp",
            purpose="Downloads supported web-video URLs before local review.",
            action_label="Check" if ytdlp_exe else "Choose path",
            action_kind="check" if ytdlp_exe else "choose_ytdlp",
            found_by=where(ytdlp_exe, str(configured_paths.get("dependency_ytdlp_path") or "")),
        ),
        DependencyStatus(
            "Local Whisper, model, Torch, CUDA, and CPU fallback",
            "not_checked",
            "",
            "Run Check readiness to validate the selected runtime and model without processing media.",
            required=False,
            key="whisper",
            purpose="Provides local transcription and reports whether GPU or CPU execution is available.",
            action_label="Check",
            action_kind="check",
        ),
    ]
    return RuntimeResources(
        app_root=app_root,
        script_path=script_path,
        backend_source_root=backend_source_root,
        icon_path=icon_path,
        powershell_exe=powershell_exe,
        python_exe=python_exe,
        ffmpeg_exe=ffmpeg_exe,
        ffprobe_exe=ffprobe_exe,
        packaged=is_packaged_app(),
        ytdlp_exe=ytdlp_exe,
        dependencies=dependencies,
        bundled_dir=bundled_dir,
    )
