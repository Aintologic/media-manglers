"""What to play, where to start, and which player gets it (125).

Everything here is plain data and plain functions with no Qt import, so the
rules that decide which recording comes next, where VLC is installed and how
it is started are tested in milliseconds without a window.  ``video_open``
re-exports these names for callers that already import the opener.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import ntpath
import os
from pathlib import Path
import posixpath
import re
import shutil
import sys
from typing import Any, Callable, Iterable, Mapping

try:  # Standard library, but it only exists on Windows.
    import winreg
except ImportError:  # pragma: no cover - only reached off Windows
    winreg = None  # type: ignore[assignment]

from .audio_detection import SUPPORTED_MEDIA_EXTENSIONS
from .recording_lists import path_key


PLAYER_INTERNAL = "internal"
PLAYER_VLC = "vlc"
PLAYER_SYSTEM = "system"
PLAYER_CHOICES = (PLAYER_INTERNAL, PLAYER_VLC, PLAYER_SYSTEM)

# Every evidence package lives in a folder of this name, whatever the run's
# output folder is called, so a path with it as a part is a package file.
PACKAGE_FOLDER_NAME = "codex-evidence-package"

# The second value ``next_target`` returns.
NEXT_FOUND = "next"
NEXT_NO_LIST = "no_list"
NEXT_END_OF_LIST = "end_of_list"

# The Workbench's supported-media set holds only video containers today.
# Subtracting the sound-only ones keeps "Play" off a sound file if that set
# ever grows one: the player is a video review tool and would show a black
# picture for it.
_SOUND_ONLY_SUFFIXES = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".wma"}
)
VIDEO_SUFFIXES: frozenset[str] = (
    frozenset(suffix.lower() for suffix in SUPPORTED_MEDIA_EXTENSIONS) - _SOUND_ONLY_SUFFIXES
)

# A web address, including one that has already been through ``Path()``, which
# turns "https://host/a.mp4" into "https:\host\a.mp4" on Windows.  Two or more
# characters before the colon, so a drive letter is never mistaken for one.
_URL_LIKE = re.compile(r"^[a-z][a-z0-9+.\-]+:[\\/]", re.IGNORECASE)

_VLC_REGISTRY_KEY = r"SOFTWARE\VideoLAN\VLC"
_VLC_REGISTRY_VALUE = "InstallDir"
_VLC_MAC_BUNDLE = ("Applications", "VLC.app", "Contents", "MacOS", "VLC")


def _clean_seconds(value: Any) -> float:
    """A start time as a finite float that is never below zero."""

    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return seconds if math.isfinite(seconds) and seconds > 0 else 0.0


@dataclass(frozen=True, slots=True)
class PlayTarget:
    """One thing to play: a recording and, optionally, the moment to start at."""

    path: Path
    start_seconds: float = 0.0
    package_root: Path | None = None
    label: str = ""
    voice_track: int | None = None  # 1-based Track N the app believes is the voice, when known
    # What decided ``voice_track`` (196): "from track name", "from your setting" or "auto-detected".
    voice_source: str = ""
    # Set when ``path`` is NOT one of the operator's recordings but a file
    # playing in its place, such as a package's small review copy.  Anything
    # that is about the recording itself (never-use, skip, which transcript)
    # must use ``recording_path``, or the copy's path ends up on the never-use
    # list while the real recording stays allowed.
    stands_in_for: Path | None = None
    # 220: the 1-based track the player starts on. ``voice_track`` only names the voice; this one
    # is what is heard. Left out, the player starts on the track its transcript came from (212).
    hear_track: int | None = None
    # 220: stretches to jump between with Next / Previous stretch, as (start, end) seconds:
    # speech for a recording with narration, else the active (not idle) stretches.
    stretches: tuple[tuple[float, float], ...] = ()
    stretch_kind: str = ""  # "speech" or "active", for the buttons' words
    # 264 (Q2): the stretches are coarse, and the finer speech facts replace them once the recording is measured.
    # Left off, a page's own stretches stay (the Inbox's and the wizard's answer "is this your microphone?").
    refine_stretches: bool = False
    # 220: the cached level of each track for each second, for the player's waveform lanes.
    levels_path: Path | None = None

    def __post_init__(self) -> None:
        # Targets are built from settings, manifests and item data, where a
        # path is often still a string and a moment can be None.  Normalising
        # once here means no consumer has to guard ``target.path.name`` or
        # ``target.start_seconds > 0``.
        object.__setattr__(self, "path", Path(self.path))
        root = self.package_root
        object.__setattr__(self, "package_root", Path(root) if root else None)
        original = self.stands_in_for
        object.__setattr__(self, "stands_in_for", Path(original) if original else None)
        object.__setattr__(self, "start_seconds", _clean_seconds(self.start_seconds))
        levels = self.levels_path
        object.__setattr__(self, "levels_path", Path(levels) if levels else None)
        cleaned: list[tuple[float, float]] = []
        for item in self.stretches or ():
            try:
                start, end = _clean_seconds(item[0]), _clean_seconds(item[1])
            except (TypeError, IndexError):
                continue
            if end > start:
                cleaned.append((start, end))
        object.__setattr__(self, "stretches", tuple(sorted(cleaned)))
        try:
            hear = int(self.hear_track) if self.hear_track is not None else None
        except (TypeError, ValueError):
            hear = None
        object.__setattr__(self, "hear_track", hear if hear is not None and hear >= 1 else None)

    @property
    def recording_path(self) -> Path:
        """The operator's recording this target is about."""

        return self.stands_in_for or self.path

    @property
    def is_package_file(self) -> bool:
        """True for a clip or copy that lives inside a package, not a recording.

        Such a file has no recording of its own to mark never-use or skip, and
        no transcript of its own to show.
        """

        if self.stands_in_for is not None:
            return False  # a stand-in knows its recording
        parts = tuple(part.lower() for part in self.path.parts)
        if PACKAGE_FOLDER_NAME in parts:
            return True
        # A package that was unzipped or renamed has another folder name, so
        # the name alone is not enough: anything inside the package this
        # target belongs to is a package file too.  Pure path arithmetic; the
        # disk is never asked.
        if self.package_root is None:
            return False
        root = tuple(part.lower() for part in self.package_root.parts)
        return len(parts) > len(root) and parts[: len(root)] == root


@dataclass(frozen=True, slots=True)
class PlaySequence:
    """The list a recording was opened from, frozen at that moment."""

    targets: tuple[PlayTarget, ...]
    label: str = ""  # e.g. "Find my bug reports list"
    # Where in THIS frozen tuple the opened recording sits.  It is a position
    # in the snapshot, never in the live view's rows, so it cannot go stale.
    # It matters when one recording is on several rows (History has one row
    # per run): "next" must continue from the row that was opened, not jump
    # back to the first row showing the same recording.
    opened_at: int = 0

    def __post_init__(self) -> None:
        # The views this is built from are rebuilt and re-ordered while the
        # player is open.  A list or generator handed in here must not be able
        # to change underneath the player, so it is materialised now.
        object.__setattr__(self, "targets", tuple(self.targets))
        try:
            opened_at = int(self.opened_at)
        except (TypeError, ValueError, OverflowError):  # OverflowError: int(float("inf"))
            opened_at = 0
        # Kept inside the tuple: the player calls opened_on() from a Qt slot on
        # every open, where an IndexError would surface as a crash.
        last = max(0, len(self.targets) - 1)
        object.__setattr__(self, "opened_at", min(max(0, opened_at), last))

    def opened_on(self, target: PlayTarget) -> "PlaySequence":
        """The same list, remembering that ``target`` is the one now open."""

        key = path_key(target.recording_path)
        # Search forward from the current place first, so the list only ever
        # moves down; fall back to anywhere for a target opened out of order.
        count = len(self.targets)
        start = min(self.opened_at, count)
        ordered = list(range(start, count)) + list(range(0, start))
        for index in ordered:
            if path_key(self.targets[index].recording_path) == key:
                return PlaySequence(self.targets, self.label, index)
        return self


def is_video_path(path: Path | str) -> bool:
    """True when the name looks like a video file.  Never touches the disk."""

    text = str(path or "").strip()
    # Queue rows can hold a web address that ends in ".mp4"; that is not a
    # file the player can be pointed at.
    if not text or _URL_LIKE.match(text):
        return False
    # ntpath splits on both kinds of slash, so the answer does not depend on
    # which operating system wrote the path.
    return ntpath.splitext(text)[1].lower() in VIDEO_SUFFIXES


def normalize_player_choice(value: Any) -> str:
    """The stored player choice, or the built-in player for anything unknown."""

    # A hand-edited settings file that says "VLC" is still a clear choice.
    text = value.strip().lower() if isinstance(value, str) else ""
    return text if text in PLAYER_CHOICES else PLAYER_INTERNAL


def _vlc_registry_install_dir() -> str:
    """VLC's install folder as its installer recorded it, or ``""``."""

    if winreg is None:
        return ""
    # Any surprise from the registry (no access, an odd value type, a policy
    # block) only means "not found here"; it must never stop a video opening.
    try:
        hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        # A 32-bit VLC on 64-bit Windows registers under the 32-bit view,
        # which a 64-bit process does not see unless it asks for it.
        views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
        for hive in hives:
            for view in views:
                try:
                    with winreg.OpenKey(hive, _VLC_REGISTRY_KEY, 0, winreg.KEY_READ | view) as key:
                        value, _kind = winreg.QueryValueEx(key, _VLC_REGISTRY_VALUE)
                except OSError:
                    continue
                text = str(value or "").strip()
                if text:
                    return text
    except Exception:
        return ""
    return ""


def find_vlc(
    configured: str = "",
    *,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.isfile,
    environ: Mapping[str, str] | None = None,
    registry_install_dir: Callable[[], str] | None = None,
    platform: str = sys.platform,
) -> str:
    """Full path of the VLC program, or ``""`` when it cannot be found.

    VLC is only ever looked for, never started, to answer this.
    """

    env = os.environ if environ is None else environ

    # "Copy as path" in Windows wraps the path in quotes; a pasted value that
    # still has them would otherwise look like a missing file.
    chosen = str(configured or "").strip().strip('"').strip()
    if chosen and exists(chosen):
        return chosen

    names = ("vlc.exe", "vlc") if platform == "win32" else ("vlc",)
    for name in names:
        found = which(name)
        if found:
            return str(found)

    candidates: list[str] = []
    if platform == "win32":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            base = str(env.get(variable) or "").strip()
            if base:
                candidates.append(ntpath.join(base, "VideoLAN", "VLC", "vlc.exe"))
    elif platform == "darwin":
        candidates.append(posixpath.join("/", *_VLC_MAC_BUNDLE))
        home = str(env.get("HOME") or "").strip()
        if home:
            candidates.append(posixpath.join(home, *_VLC_MAC_BUNDLE))
    for candidate in candidates:
        if exists(candidate):
            return candidate

    # Last, because it is the only step that leaves the file system: VLC
    # installed to a folder of the operator's choosing is still in the registry.
    if platform == "win32":
        lookup = _vlc_registry_install_dir if registry_install_dir is None else registry_install_dir
        install_dir = str(lookup() or "").strip().rstrip("\\/")
        if install_dir:
            candidate = install_dir + "\\vlc.exe"
            if exists(candidate):
                return candidate
    return ""


def build_vlc_command(vlc_exe: str, target: PlayTarget, *, autoplay: bool) -> list[str]:
    """The argument list that starts VLC on ``target``."""

    command = [str(vlc_exe)]
    start = _clean_seconds(target.start_seconds)
    if start > 0:
        command.append(f"--start-time={start:.3f}")
    if not autoplay:
        command.append("--start-paused")
    command.append(str(target.path))
    return command


def next_target(
    sequence: PlaySequence | None,
    current: Path | str,
    excluded: Iterable[str] | None,
) -> tuple[PlayTarget | None, str]:
    """The recording after ``current`` in the list it was opened from.

    Returns ``(target, "next")``, ``(None, "no_list")`` or
    ``(None, "end_of_list")``.
    """

    if sequence is None or len(sequence.targets) < 2:
        return None, NEXT_NO_LIST
    # The position is found by path every time.  The rows a sequence was
    # taken from are rebuilt in several places, and marking a recording
    # never-use removes its row, so a remembered index would point at the
    # wrong recording.
    current_key = path_key(current)
    keys = [path_key(target.recording_path) for target in sequence.targets]
    # Prefer the row that was actually opened when it still names this
    # recording; otherwise the first row at or after it, then anywhere.  This
    # is a position in the frozen snapshot, not in the live view.
    start = sequence.opened_at if sequence.opened_at < len(keys) else 0
    if keys[start] == current_key:
        position: int | None = start
    else:
        position = next((index for index in range(start, len(keys)) if keys[index] == current_key), None)
        if position is None:
            position = next((index for index in range(0, start) if keys[index] == current_key), None)
    if position is None:
        return None, NEXT_NO_LIST
    # path_key leaves a key unchanged, so the caller may pass keys or paths.
    skip = {path_key(item) for item in (excluded or ())}
    # One recording can sit on several rows; moving to another row of the
    # same recording would not be "next".
    skip.add(current_key)
    # No wrap-around: only what comes after is considered.
    for index in range(position + 1, len(keys)):
        if keys[index] not in skip:
            return sequence.targets[index], NEXT_FOUND
    return None, NEXT_END_OF_LIST
