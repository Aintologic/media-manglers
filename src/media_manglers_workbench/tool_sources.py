"""Where each tool comes from, and where the Workbench looks for it (188; installer plan, Stage 1).

One table for every tool the Workbench and the scripts use: its official page, its Windows Package
Manager package when there is one, the folders its own installer puts it in, and, for FFmpeg, FFprobe
and Python, where Media Manglers' own copy sits in the packaged application folder's ``runtime``
folder. The lookup order is the same everywhere: the path the user chose, then (for FFprobe) the file
beside the FFmpeg in use, then Media Manglers' own copy, then PATH, then those folders. There are no
folders from one machine. Nothing here downloads, installs or changes anything.

The scripts carry the same table and order in PowerShell (`Get-ToolSource` and
`Resolve-ExecutablePath` in `Video Mangler.ps1`); `tests/test_tool_sources.py` keeps them equal.
"""

from __future__ import annotations

from dataclasses import dataclass
import glob
import os
from pathlib import Path
import re
import shutil
from typing import Callable, Mapping


@dataclass(frozen=True, slots=True)
class ToolSource:
    key: str
    name: str
    page: str
    winget_id: str = ""
    # Executable names looked for on PATH, in order.
    commands: tuple[str, ...] = ()
    # The tool's own install folders, as patterns under an environment folder. Each is
    # (environment variable, pattern below it); a pattern may hold * wildcards.
    standard: tuple[tuple[str, str], ...] = ()
    # Where Media Manglers' own copy sits, below the packaged application folder's runtime folder;
    # "" for a tool it does not ship.
    bundled: str = ""

    @property
    def winget_command(self) -> str:
        return f"winget install --id {self.winget_id} -e" if self.winget_id else ""


_WINGET_LINKS = ("LOCALAPPDATA", r"Microsoft\WinGet\Links")
_WINGET_PACKAGES = ("LOCALAPPDATA", r"Microsoft\WinGet\Packages")
_WINGET_MACHINE_LINKS = ("ProgramFiles", r"WinGet\Links")


def _links(exe: str) -> tuple[tuple[str, str], ...]:
    return (
        (_WINGET_LINKS[0], rf"{_WINGET_LINKS[1]}\{exe}"),
        (_WINGET_MACHINE_LINKS[0], rf"{_WINGET_MACHINE_LINKS[1]}\{exe}"),
    )


TOOL_SOURCES: dict[str, ToolSource] = {
    source.key: source
    for source in (
        ToolSource(
            "ffmpeg",
            "FFmpeg",
            "https://ffmpeg.org/download.html",
            "Gyan.FFmpeg",
            ("ffmpeg.exe", "ffmpeg"),
            _links("ffmpeg.exe")
            + ((_WINGET_PACKAGES[0], rf"{_WINGET_PACKAGES[1]}\Gyan.FFmpeg_*\ffmpeg-*\bin\ffmpeg.exe"),),
            bundled=r"ffmpeg\bin\ffmpeg.exe",
        ),
        ToolSource(
            "ffprobe",
            "FFprobe",
            "https://ffmpeg.org/download.html",
            "Gyan.FFmpeg",
            ("ffprobe.exe", "ffprobe"),
            _links("ffprobe.exe")
            + ((_WINGET_PACKAGES[0], rf"{_WINGET_PACKAGES[1]}\Gyan.FFmpeg_*\ffmpeg-*\bin\ffprobe.exe"),),
            bundled=r"ffmpeg\bin\ffprobe.exe",
        ),
        ToolSource(
            "ytdlp",
            "yt-dlp",
            "https://github.com/yt-dlp/yt-dlp#installation",
            "yt-dlp.yt-dlp",
            ("yt-dlp.exe", "yt-dlp"),
            _links("yt-dlp.exe")
            + ((_WINGET_PACKAGES[0], rf"{_WINGET_PACKAGES[1]}\yt-dlp.yt-dlp_*\yt-dlp.exe"),),
        ),
        ToolSource(
            "python",
            "Python",
            "https://www.python.org/downloads/windows/",
            "Python.Python.3.12",
            ("python.exe", "python", "py.exe", "py"),
            (
                ("LOCALAPPDATA", r"Programs\Python\Python3*\python.exe"),
                ("LOCALAPPDATA", r"Python\pythoncore-3*\python.exe"),
                ("ProgramFiles", r"Python3*\python.exe"),
            ),
            bundled=r"python\python.exe",
        ),
        ToolSource(
            "powershell",
            "PowerShell",
            "https://learn.microsoft.com/powershell/scripting/install/install-powershell-on-windows",
            "Microsoft.PowerShell",
            ("powershell.exe", "powershell", "pwsh.exe", "pwsh"),
            (
                ("SystemRoot", r"System32\WindowsPowerShell\v1.0\powershell.exe"),
                ("ProgramFiles", r"PowerShell\7\pwsh.exe"),
            ),
        ),
        ToolSource("whisper", "Local Whisper", "https://github.com/openai/whisper#setup"),
        ToolSource("torch", "PyTorch", "https://pytorch.org/get-started/locally/"),
        ToolSource(
            "vlc",
            "VLC media player",
            "https://www.videolan.org/vlc/",
            "VideoLAN.VLC",
            ("vlc.exe", "vlc"),
            (
                ("ProgramFiles", r"VideoLAN\VLC\vlc.exe"),
                ("ProgramFiles(x86)", r"VideoLAN\VLC\vlc.exe"),
            ),
        ),
    )
}


def tool_source(key: str) -> ToolSource | None:
    return TOOL_SOURCES.get(key)


# A row that offers Download: its tool is missing, needs an update, or (VLC) was not found.
DOWNLOAD_STATES = frozenset({"needs_setup", "missing", "update_recommended", "optional"})


def needs_download(dependency: object) -> bool:
    # Installer plan, Stage 4: a row whose way out is Media Manglers' own Set up never also sends the operator to a
    # tool's install page (pip instructions for another Python).
    return (
        str(getattr(dependency, "key", "") or "") in TOOL_SOURCES
        and str(getattr(dependency, "status", "") or "") in DOWNLOAD_STATES
        and str(getattr(dependency, "action_kind", "") or "") != "speech_setup"
    )


def bundled_tools_dir(executable: str | None = None) -> Path:
    """Media Manglers' own tools folder, ``<app folder>\\runtime``, anchored on the program's own folder: never
    on the current folder or the ``MEDIA_MANGLERS_WORKBENCH_ROOT`` override. A source run has none."""

    from media_manglers.core.private_runtime import runtime_folder  # noqa: PLC0415

    return runtime_folder(executable)


def bundled_tool(key: str, bundled_dir: str | os.PathLike[str] | None) -> str:
    """Where Media Manglers' own copy of ``key`` would sit in ``bundled_dir``; "" for a tool it does not ship."""

    source = TOOL_SOURCES.get(key)
    if not bundled_dir or source is None or not source.bundled:
        return ""
    return str(Path(bundled_dir) / source.bundled)


# What each row says about where a tool came from (installer plan, Stage 1).
FOUND_BUNDLED = "Bundled with Media Manglers"
FOUND_DOWNLOADED = "Downloaded by Media Manglers"
FOUND_CHOSEN = "Your chosen path"
FOUND_ON_PC = "Already on this PC"
FOUND_WINDOWS = "Part of Windows"


def _inside(path: str, folder: str | os.PathLike[str] | None) -> bool:
    if not path or not folder:
        return False
    item = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(str(folder))).rstrip("\\/")
    return item.startswith(root + os.sep)


def found_by_text(path: str, *, chosen: str = "", bundled_dir: str | os.PathLike[str] | None = None,
                  downloaded_dir: str | os.PathLike[str] | None = None,
                  environ: Mapping[str, str] | None = None) -> str:
    """Where the tool at ``path`` came from, in the words a readiness row shows; "" when nothing was found."""

    path = str(path or "").strip().strip('"')
    if not path:
        return ""
    environ = os.environ if environ is None else environ
    chosen = str(chosen or "").strip().strip('"')
    if chosen and os.path.normcase(os.path.abspath(chosen)) == os.path.normcase(os.path.abspath(path)):
        return FOUND_CHOSEN
    if _inside(path, bundled_dir):
        return FOUND_BUNDLED
    if _inside(path, downloaded_dir):
        return FOUND_DOWNLOADED
    if _inside(path, environ.get("SystemRoot") or ""):
        return FOUND_WINDOWS
    return FOUND_ON_PC


@dataclass(frozen=True, slots=True)
class ToolLookup:
    """Where a tool was found: "chosen", "beside FFmpeg", "bundled", "PATH", "standard", or "" for not found."""

    path: str = ""
    found_by: str = ""
    # A chosen path that does not exist; the lookup went on to the others (188).
    chosen_missing: str = ""

    @property
    def note(self) -> str:
        if self.chosen_missing and self.path:
            return f"Your chosen path is missing ({self.chosen_missing}); using {self.path}."
        if self.chosen_missing:
            return f"Your chosen path is missing ({self.chosen_missing})."
        return ""


def standard_locations(
    source: ToolSource,
    *,
    environ: Mapping[str, str] | None = None,
    expand: Callable[[str], list[str]] = glob.glob,
) -> list[str]:
    """Every existing file in the tool's own install folders, newest version folder first."""

    environ = os.environ if environ is None else environ
    found: list[str] = []
    for variable, pattern in source.standard:
        base = str(environ.get(variable) or "").strip()
        if not base:
            continue
        full = str(Path(base) / pattern)
        matches = expand(full) if "*" in pattern else [full]
        found.extend(sorted(matches, key=_version_order, reverse=True))
    return found


def _version_order(path: str) -> list[tuple[int, object]]:
    # Numbers compare as numbers, so Python312 comes before Python39 and ffmpeg-10 before ffmpeg-9.
    return [
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", path)
    ]


def find_tool(
    key: str,
    chosen: str = "",
    *,
    beside: str = "",
    bundled_dir: str | os.PathLike[str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
    environ: Mapping[str, str] | None = None,
    expand: Callable[[str], list[str]] = glob.glob,
) -> ToolLookup:
    """The chosen path, then (for FFprobe) beside the FFmpeg in use, then Media Manglers' own copy in
    ``bundled_dir`` (``bundled_tools_dir()``), then PATH, then the standard folders."""

    source = TOOL_SOURCES[key]
    chosen = str(chosen or "").strip().strip('"')
    chosen_missing = ""
    if chosen:
        if is_file(chosen):
            return ToolLookup(chosen, "chosen")
        chosen_missing = chosen
    bundled = bundled_tool(key, bundled_dir)
    if beside and Path(beside).is_absolute():
        # FFprobe ships in the same folder as FFmpeg, as the scripts and the helpers expect. Beside our own
        # FFmpeg that is our own FFprobe.
        sibling = Path(beside).parent / ("ffprobe.exe" if beside.lower().endswith(".exe") else "ffprobe")
        if is_file(str(sibling)):
            same = bool(bundled) and os.path.normcase(str(sibling)) == os.path.normcase(bundled)
            return ToolLookup(str(sibling), "bundled" if same else "beside FFmpeg", chosen_missing)
    if bundled and is_file(bundled):
        return ToolLookup(bundled, "bundled", chosen_missing)
    for command in source.commands:
        resolved = which(command)
        if resolved:
            return ToolLookup(resolved, "PATH", chosen_missing)
    for candidate in standard_locations(source, environ=environ, expand=expand):
        if is_file(candidate):
            return ToolLookup(candidate, "standard", chosen_missing)
    return ToolLookup("", "", chosen_missing)
