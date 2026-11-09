"""The AI Video Editor page (150 Phase 3; 236: the approved "player first" layout).

One page for the whole loop: choose a race recording, prepare it for the AI editor, copy the prompt for
Claude Code or Codex, then watch each version the editor makes on the page, write notes for the next
version, and export the one you approve.

236: the page has two views. The start view: one big "Make a video from a recording" card (it opens
Choose a recording…), "Continue: <last video>", and "Your videos" as picture cards with a plain status
(Ready to watch, Waiting for your AI agent, Exported, Getting ready…) and how many versions each has. The
one-video view: "← Your videos", the video's name and "Approve and export…" top right; under them its
versions as tabs (newest chosen) and a toolbar of labelled buttons, "Video settings", "Prompt", "Story &
review" and "Files", each opening a small panel of labelled choices (236 fix round: nothing is only in a
hidden menu). The chosen version's picture fills the player's place with the play choices on it, "Play
the final (full quality)" with "Play the preview (quick, smaller)" beside it, or "Play the preview" alone;
pressing one plays it at once on the page, in the app's one built-in player (docked into the page, never
a second player). Its story is a strip of scenes under the player, each as wide as its words, scrolling
sideways when they do not fit (click to jump there; the pen on a scene, or a right-click, puts it in the
notes); the notes box is at the bottom. Before the first version exists, the player's place says so and
offers the one next step: Prepare for the AI editor, or Copy prompt for Claude Code. The page notices
new versions by itself.

The Workbench never calls an AI service. The long jobs (preparing a recording, rendering a preview,
exporting) run as the race-video commands of the Python core through the Workbench's shared runner, so
they show on Queue / Progress, write the run log and land in History like every other run. They never
become the last evidence package (150 Risk 1). Everything the page shows is read from the project
folders, so it always matches what is on disk.

226: the voice and game-sound boxes start on Auto, which follows the track names and the Narration
track setting (Track roles) by the same rules Prepare uses, and say what Auto picks; a track picked by
hand overrides it for that recording only. The recording's tracks are read off the window's thread.
When a recording that was prepared before is chosen again, the tracks picked by hand then are picked
again, and the page warns, on the page, before a Prepare would change the tracks of a video that
already has versions. Prepare sends the engine settings the page shows (Track roles, Whisper, words to
spell right, the quick passes) with the run. Each video can keep its own export quality, in its
project's ``editor-settings.json``.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core import app_cache, recording_records, speech_facts, voice_track
from media_manglers.core.recording_records import Records
from media_manglers.core.race_video import link
from media_manglers.core.race_video.library import (
    ROLE_EXPORT,
    ROLE_FINAL,
    ROLE_PREVIEW,
    ROLE_READABLE,
    list_projects,
    reconcile,
    start_fresh_edit,
)
from media_manglers.core.race_video.project import (
    editor_settings,
    notes_with_scenes,
    picked_tracks,
    prepared_tracks,
    project_folder,
    project_recording,
    save_feedback,
    scene_note_line,
    set_editor_settings,
    split_scene_notes,
    usage_report,
)
from media_manglers.core.race_video.prompt import APP_LABELS, build_prompt
from media_manglers.core.race_video.render import DEFAULT_QUALITY, EXPORT_QUALITY_KEY, QUALITIES
from media_manglers.core.race_video.requests import (
    ENGINE_SETTING_KEYS,
    QUICK_MODEL_DEFAULT,
    QUICK_MODEL_KEY,
    QUICK_MODEL_MAIN,
    TRACK_ROLES_SETTING_KEY,
    setting_game_refusal,
)
from media_manglers.core.race_video.timeline import story_blocks
from media_manglers.core.user_folders import temporary_folder_problem

from . import run_status
from .ai_video_editor_parts import (
    BUDGET_INTRO,
    PLAY_FINAL,
    PLAY_PREVIEW_BESIDE,
    ApproveExportDialog,
    ChooseRecordingDialog,
    LinkRecordingsDialog,
    MakeVideoCard,
    PictureBox,
    PromptDialog,
    ReaderDialog,
    ResponsiveGrid,
    SceneStrip,
    ThumbnailMaker,
    ToolbarButton,
    ToolPanel,
    VersionFilesDialog,
    VideoCard,
    budget_words,
    chip_words,
    export_words,
    files_summary,
    knowledge_words,
    library_recordings,
    offer_words,
    play_choices,
    play_label,
    playing_words,
    render_words,
    thumbnail_source,
)
from .command_builder import CommandSpec
from .main_settings import USING_MAIN_SETTING, project_choice_state, quick_passes_state, track_choice_state
from .metadata import METADATA_BY_KEY
from .play_targets import PlayTarget
from .runner import RunnerResult
from . import theme
from .theme import status_kind
from .ui_parts import (
    TOOL_ICON_FOLDER,
    FlowLayout,
    InlineFeedback,
    Outcome,
    StepBar,
    bind_action,
    line_icon,
    set_button_kind,
)
from .widgets import WheelSafeComboBox

if TYPE_CHECKING:  # pragma: no cover
    from .app import WorkbenchWindow

PAGE_NAME = APP_LABELS["page"]
# The rail fits about nine characters at the smallest window; the page and its card use the full name.
NAV_LABEL = "AI Editor"
HOME_CARD_KEY = "video-editor"
HOME_CARD_PURPOSE = "Turn a long narrated race recording into a short, story-driven video. Your AI agent edits; you watch and approve."
PAGE_PURPOSE = "Turn a long race recording into a short video that tells the story."
BUDGETS = (("light", "Light"), ("standard", "Standard"), ("thorough", "Thorough"))
RUN_TITLES = {
    "prepare": "AI Video Editor: analysis",
    "preview": "AI Video Editor: preview",
    "export": "AI Video Editor: export",
}
# 237: what the page's job banner says is running.
BANNER_TITLES = {
    "prepare": "Preparing {label} for the AI editor",
    "preview": "Rendering a preview of {label}",
    "export": "Exporting {label}",
}
VIDEO_FILTER = "Video recordings (*.mkv *.mp4 *.mov *.avi *.m4v *.webm)"
# 226 (decision A): the first item of each track box. Its data is None: the run decides the track.
AUTO = "Auto"
# 226: the Settings field the Track roles live in, by the name the operator sees on Settings > General / Startup.
TRACK_ROLES_FIELD = "Narration track setting"
TRACK_TOOLTIPS = {
    "voice": (f"Auto uses the track your track names or your {TRACK_ROLES_FIELD} (Settings > General / Startup) "
              "call narration; when they do not say, Prepare finds your voice by listening. Pick a track to "
              "override it for this recording only."),
    "game": (f"Auto uses the track your track names or your {TRACK_ROLES_FIELD} call Game audio; when they do "
             "not say, Prepare takes the one track left with sound. Pick a track to override it for this "
             "recording only."),
}
_ROLE_WORDS = {"voice": "narration", "game": "game sound"}
_DECIDED_WORDS = {voice_track.DECIDED_BY_NAME: "from the track name",
                  voice_track.DECIDED_BY_SETTING: f"from your {TRACK_ROLES_FIELD}"}
_TRACK_WORDS = {"voice": "your voice", "game": "the game sound"}
DECIDED_DURING_PREPARE = "Auto: decided during Prepare"
NO_MASKS_WARNING = ("No privacy masks are drawn, so the camera panels in this video's pictures are not blurred. "
                    f"Draw them with Privacy masks… under {APP_LABELS['settings_tool']}, then prepare the recording "
                    "again.")
QUICK_PASS_CHOICES = ((QUICK_MODEL_DEFAULT, "Whisper small (faster)"), (QUICK_MODEL_MAIN, "Use main setting"))
# 236: the steps of a video, as the step bar before the first version shows them.
STEPS = ("Prepare for the AI editor", "Copy the prompt for your AI agent", "Watch and say what to change",
         "Approve and export")
NOTES_TITLE = f"{APP_LABELS['notes']} (plain words, for the next version)"
NEXT_STEPS = (
    "Your AI agent first tells you, in plain words, the story it plans to tell, and whether it will wait for your "
    "changes before it cuts.",
    "It makes version 1, watches it as a viewer would and fixes what it can. On a long race this takes a while.",
    f"Version 1 appears here by itself, as a tab at the top. If it does not, press {APP_LABELS['files_tool']}, then "
    f"{APP_LABELS['refresh']}.",
    f"Press {APP_LABELS['play']} on the picture, then write what should change, or press {APP_LABELS['approve']}",
)
# 236 fix round: the player's place before the first version, by where the video is.
NO_VERSION_TITLE = "Your AI agent hasn't made a version yet"
NO_VERSION_PREPARE = "Prepare for the AI editor…"
NO_VERSION_WORDS = {
    "prepare": ("The app writes down what you said and watches the race on this PC, then gives you the prompt for "
                "your AI agent."),
    "copy": ("Paste it into Claude Code as your first message: your AI agent tells you the story it plans, makes "
             "version 1 and reviews it, and version 1 then appears here by itself."),
    "preparing": "On a long race this takes a while; the bar at the top shows how far it has got.",
}
PREPARING_TITLE = "Getting this recording ready for your AI agent"
# 236: the page looks for new versions and renders this often while it is shown.
WATCH_SECONDS = 4.0
# 236 fix round: the video's toolbar instead of a ⋯ menu, in its order: (key, the button's words, its icon).
TOOLS = (
    ("settings", APP_LABELS["settings_tool"], "video-settings"),
    ("prompt", APP_LABELS["prompt_tool"], "prompt"),
    ("story", APP_LABELS["story_tool"], "story"),
    ("files", APP_LABELS["files_tool"], "files"),
)
# What each toolbar button's panel holds, in its order: (key, words). A None is a divider; "quality" is the
# export quality's choices. The play choices show in Files only for a version that has a final and a preview,
# so the other one is a click away while one plays.
TOOL_PANELS: dict[str, tuple[tuple[str, str] | None, ...]] = {
    "settings": (("voice", "Your voice"), ("game", "Game sound"), ("budget", "AI budget"), None,
                 ("masks", "Privacy masks…")),
    "prompt": (("copy_claude", "Copy prompt for Claude Code"), ("copy_codex", "Copy prompt for Codex"),
               ("see_prompt", "See the prompt first"), None, ("fresh", APP_LABELS["fresh"])),
    "story": (("story", "The story"), ("review", "The editor's own review")),
    "files": (("play_final", PLAY_FINAL), ("play_preview", PLAY_PREVIEW_BESIDE), None,
              ("files", "This version's files"), ("render", APP_LABELS["render"]), None, ("quality", "Export quality"),
              None, ("open_project", "Open project folder"), ("open_export", "Open export folder"), None,
              ("refresh", APP_LABELS["refresh"])),
}
# 236 fix round: the least height of a version's picture while it plays, and of its picture before Play
# with room for the player's rows below it, so pressing Play never makes it small and the page below does not
# jump (a short window scrolls a little instead). Pixels of picture, so it does not grow with the text size.
PLAYING_PICTURE_LEAST = 260
PLAYER_ROWS_GUESS = 170
# Why a choice of a panel is greyed out, said in its tooltip.
NOT_PREPARED_WHY = "Prepare the recording for the AI editor first."
NO_VERSION_WHY = "Your AI agent has not made a version of this video yet."
BUSY_WHY = "Wait for the job that is running to finish."


def editor_output_root(settings: dict[str, Any]) -> Path:
    """The folder whose race-videos folder holds the projects: the editor's own, else the output folder."""

    chosen = str(settings.get("race_video_output_folder") or "").strip()
    return Path(chosen or str(settings.get("output_folder") or "")).expanduser()


def cli_command(resources: Any, command: str, request: Path, result: Path) -> CommandSpec:
    """A race-video command of the Python core, run with the Python that has Whisper.

    The runner cannot set PYTHONPATH, so the core's folder is put on the path by the command itself.
    """

    root = str(resources.backend_source_root or "")
    bootstrap = (f"import sys; sys.path.insert(0, {root!r}); "
                 "from media_manglers.cli import main; raise SystemExit(main(sys.argv[1:]))")
    argv = [str(resources.python_exe or "python"), "-c", bootstrap, command,
            "--request-file", str(request), "--result-file", str(result)]
    return CommandSpec(argv=argv, preview=f"media_manglers {command} --request-file {request}")


def audio_tracks(ffprobe: str, source: Path) -> list[str]:
    """Each audio track's name as the recording stores it ("" when it has none), Track 1 first.

    226: read by the shared probe (``voice_track.probe_audio_streams``), and run off the window's
    thread: on a slow drive it can take a while. [] when the recording cannot be read.
    """

    try:
        streams, _duration = voice_track.probe_audio_streams(ffprobe or "ffprobe", source)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return []
    return [str((stream.get("tags") or {}).get("title") or "").strip() for stream in streams]


def auto_tracks(titles: list[str], track_roles: Any, voice: int | None = None) -> dict[str, tuple[int | None, str]]:
    """What Auto picks before the recording is read (226, decision A), by the rules Prepare uses: the
    track names first, then the Track roles setting ("2=narration,3=game").

    ``voice`` is a voice track picked on the page (0-based), which the game rule leaves out. Each value
    is (track, what decided it), or (None, "") when only Prepare can tell: by listening for the voice,
    or by finding the one track left with sound for the game.
    """

    named = dict(enumerate(titles))
    roles_value = voice_track.roles_from_text(track_roles)
    source, roles = voice_track.track_roles(named, voice_track.parse_track_roles(roles_value))
    narration = [ordinal for ordinal in sorted(roles) if roles[ordinal] == voice_track.ROLE_NARRATION]
    auto_voice: tuple[int | None, str] = (narration[0], source) if len(narration) == 1 else (None, "")
    game, decided = voice_track.game_audio_track(named, setting_value=roles_value,
                                                 narration_ordinal=voice if voice is not None else auto_voice[0])
    auto_game: tuple[int | None, str] = (
        (game, decided) if game is not None and decided in _DECIDED_WORDS else (None, ""))
    return {"voice": auto_voice, "game": auto_game}


def auto_text(name: str, pick: tuple[int | None, str]) -> str:
    """How a track box says what Auto picks: "Auto: Track 2, narration, from your Narration track setting"."""

    ordinal, decided = pick
    if ordinal is None:
        return DECIDED_DURING_PREPARE
    return f"Auto: Track {ordinal + 1}, {_ROLE_WORDS[name]}, {_DECIDED_WORDS.get(decided, decided)}"


def main_export_quality(settings: dict[str, Any]) -> str:
    """The main export quality (Settings > AI Video Editor), YouTube when it is not set."""

    value = str(settings.get(EXPORT_QUALITY_KEY) or "").strip().casefold()
    return value if value in QUALITIES else DEFAULT_QUALITY


def project_export_quality(project: Path) -> str:
    """The export quality this video keeps for itself, "" when it follows the main setting (226)."""

    value = str(editor_settings(project).get("export_quality") or "").strip().casefold()
    return value if value in QUALITIES else ""


def set_project_export_quality(project: Path, quality: str) -> None:
    """Keep ``quality`` as this video's own export quality, or "" to follow the main setting again.

    226: ``<project>/editor-settings.json`` (``EDITOR_SETTINGS_NAME``) is written whole and at once,
    keeping what else it holds (the tracks Prepare keeps there); the export reads it. The file goes
    when nothing is left in it.
    """

    set_editor_settings(project, export_quality=quality or None)


def earlier_prepare(output_root: Path, source: Path) -> dict[str, Any]:
    """What an earlier Prepare of ``source`` left in its video's project (226): ``folder``, the
    ``prepared`` voice and game tracks, the tracks ``picked`` by hand then (0-based; from the project's
    ``editor-settings.json``, else, for a project prepared before it kept them, the "override" tracks of
    its ``project.json``) and how many ``versions`` it has. {} when the recording has no project there
    (or the folder of its name belongs to another recording, which Prepare refuses itself)."""

    try:
        project = project_folder(output_root, source, read=False)
        meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(meta, dict):
        return {}
    kept = editor_settings(project).get("tracks")
    if isinstance(kept, dict):
        picked = {name: int(kept[name]) for name in ("voice", "game") if isinstance(kept.get(name), int)}
    else:
        picked = picked_tracks(meta.get("tracks"))
    return {"folder": project, "prepared": prepared_tracks(project), "picked": picked,
            "versions": len(meta.get("versions") or [])}


def tracks_change_text(earlier: dict[str, Any], voice: int | None, game: int | None) -> str:
    """The page's warning before a Prepare would change the tracks of a video that has versions (226),
    or "": ``voice`` and ``game`` are the tracks the boxes give (0-based; None when only Prepare can tell)."""

    count = int(earlier.get("versions") or 0)
    prepared = earlier.get("prepared") or {}
    if not count or not prepared:
        return ""
    now = {"voice": voice, "game": game}
    changed = [name for name in ("voice", "game") if name in prepared and now[name] is not None
               and now[name] != prepared[name]]
    unknown = [name for name in ("voice", "game") if name in prepared and now[name] is None]
    if not changed and not unknown:
        return ""
    versions = f"{count} version{'s use' if count != 1 else ' uses'}"
    uses = " and ".join(f"Track {prepared[name] + 1} as {_TRACK_WORDS[name]}" for name in ("voice", "game")
                        if name in prepared)
    lost = f"{'they' if count != 1 else 'it'} can no longer be rendered or exported"
    if changed:
        return (f"These are not the tracks this video was prepared with: its {versions} {uses}, and after a "
                f"Prepare with other tracks {lost}.")
    which = " and ".join(_TRACK_WORDS[name] for name in unknown)
    return (f"Prepare decides {which} again: this video's {versions} {uses}, and if Prepare picks another "
            f"track {lost}.")


def _text(path: str) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _section(text: str) -> QLabel:
    label = QLabel(text)
    # 237: a heading wraps rather than being cut off at a large text size.
    label.setWordWrap(True)
    label.setProperty("sectionTitle", True)
    return label


def _show_kind(label: QLabel, kind: str) -> None:
    """Colour a status sentence by the app's one status rule (213): the theme's statusKind.

    ``kind`` is a status word (see theme.status_kind) or "" for a plain instruction, which keeps the
    label's own look. A coloured sentence drops the cyan accent so only the rule decides its colour.
    """

    kind = status_kind(kind) if kind else ""
    label.setProperty("statusKind", kind)
    if label.property("plainAccent"):
        label.setProperty("accent", not kind)
    # A stylesheet only looks at a property again when the widget is re-polished.
    label.style().unpolish(label)
    label.style().polish(label)


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("muted", True)
    return label



def _link(text: str) -> QPushButton:
    button = QPushButton(text)
    set_button_kind(button, "link")
    return button


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
    layout.setSpacing(theme.px(8))
    return frame, layout


class _VersionTab(QPushButton):
    """A version's tab: a click chooses it, a double-click plays it."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()


class _PlayButton(QPushButton):
    """A play choice on the picture (236 fix round): the main one filled in the accent colour, the one
    beside it see-through, each with a play mark."""

    def __init__(self, text: str, *, primary: bool, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.primary = primary
        self.setObjectName("posterPlay" if primary else "posterPlaySecondary")
        # The player's place has one primary button at a time (UI rules section 5): this one.
        self.setProperty("primary", primary)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._draw_icon()

    def _draw_icon(self) -> None:
        size = theme.px(18)
        colour = theme.token("on_accent") if self.primary else "#FFFFFF"
        self.setIcon(line_icon("play", colour, colour, size, TOOL_ICON_FOLDER))
        self.setIconSize(QSize(size, size))

    def changeEvent(self, event: Any) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange:
            # The theme or the text size changed: the mark follows.
            self._draw_icon()


class _PlayerBox(QFrame):
    """The player's place on the page (236 fix round): the docked player is kept as wide as its picture
    needs at 16:9 and centred, so the box hugs the video instead of leaving wide empty bars, but never so
    narrow that its buttons wrap onto another line (that would take the picture's height). It is placed by
    hand rather than by a layout, so the room beside it never counts towards the page's width. The box is
    never so short that the picture is small: a short window scrolls a little instead."""

    def player(self) -> QWidget | None:
        for child in self.children():
            if isinstance(child, QWidget) and hasattr(child, "video_stack"):
                return child
        return None

    @staticmethod
    def rows(player: QWidget) -> int:
        """The height of the player's own rows (timeline, buttons, its name): all of it but the picture."""

        return max(0, player.minimumSizeHint().height() - player.video_stack.minimumSizeHint().height())

    @staticmethod
    def sides(player: QWidget) -> int:
        """The room the player keeps at its left and right edges: its own margins and its layout's."""

        own, inner = player.contentsMargins(), player.layout().contentsMargins()
        return own.left() + own.right() + inner.left() + inner.right()

    @classmethod
    def controls_width(cls, player: QWidget) -> int:
        """The width the player's buttons and its time need on one line."""

        layout = player.layout()
        widest = max((layout.itemAt(index).layout().sizeHint().width() for index in range(layout.count())
                      if isinstance(layout.itemAt(index).layout(), FlowLayout)), default=0)
        return widest + cls.sides(player)

    def childEvent(self, event: Any) -> None:  # noqa: N802
        super().childEvent(event)
        if event.type() in (QEvent.Type.ChildAdded, QEvent.Type.ChildRemoved):
            self.updateGeometry()
            QTimer.singleShot(0, self._fit_later)

    def _fit_later(self) -> None:
        try:
            self.fit()
        except RuntimeError:  # deleted with its page
            pass

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fit()

    def fit(self) -> None:
        player = self.player()
        if player is None:
            return
        # The player's own rows keep their height; the rest is picture, at 16:9.
        wanted = int(max(0, self.height() - self.rows(player)) * 16 / 9) + self.sides(player)
        width = min(self.width(), max(player.minimumSizeHint().width(), self.controls_width(player), wanted))
        player.setGeometry((self.width() - width) // 2, 0, width, self.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        player = self.player()
        return player.sizeHint() if player is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        player = self.player()
        if player is None:
            return super().minimumSizeHint()
        least = player.minimumSizeHint()
        return QSize(least.width(), max(least.height(), PLAYING_PICTURE_LEAST + self.rows(player)))


class _CurrentOnlyStack(QStackedWidget):
    """A stack as tall as the view it shows, so a short view never scrolls for a tall one (236).

    A stack asks for the height of its tallest page; this one asks only for its shown page's. A page in
    ``fill`` (the player and its poster) asks for no more than its minimum and takes the room the page
    has left, so the video grows with the window and never pushes the story strip and the notes off it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fill: set[int] = set()
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def _filling(self, page: QWidget | None) -> bool:
        return page is not None and id(page) in self.fill

    def sizeHint(self) -> QSize:  # noqa: N802
        current = self.currentWidget()
        if current is None:
            return super().sizeHint()
        hint = current.sizeHint()
        if self._filling(current):
            hint.setHeight(current.minimumSizeHint().height())
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        current = self.currentWidget()
        return current is not None and not self._filling(current) and current.hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        current = self.currentWidget()
        return current.heightForWidth(width) if self.hasHeightForWidth() else -1


class AiVideoEditorPage(QWidget):
    """Your videos -> one video: prepare -> copy the prompt -> watch on the page, note, export."""

    # 226: a recording's track names, read on a thread of their own: (which read it is, the names).
    tracks_read = Signal(int, object)
    # 242 (Wave C2): the evidence for Link recordings…, looked up off the window's thread.
    links_found = Signal(object)

    def __init__(self, host: "WorkbenchWindow") -> None:
        super().__init__()
        self.host = host
        self.running = False
        self.run_kind = ""
        self.run_folder: Path | None = None
        self.run_project = ""
        # 236: what the run started from: the version and whether its preview and export were there before.
        self.run_before: dict[str, Any] = {}
        self.recording: Path | None = None
        # The chosen recording's track names; None until they are read.
        self.track_titles: list[str] | None = None
        self.probing = False
        self._probe_number = 0
        self._track_rows: dict[str, QWidget] = {}
        # 226: what an earlier Prepare of the chosen recording left (``earlier_prepare``), {} for none.
        self.earlier: dict[str, Any] = {}
        self.projects: list[dict[str, Any]] = []
        self.last_message = ""
        # 236: the video shown in the one-video view (its project folder; "" for a recording not prepared
        # yet), the version chosen there, and whether the step view was asked for over the player.
        self.view = "start"
        self.project_folder = ""
        self.version_number: int | None = None
        self.steps_asked = False
        # Whether Prepare's boxes show (open) or only what Prepare used (once a video is prepared).
        self._form_open = False
        # 236 fix round: the file playing on the page, None while the picture shows.
        self._playing_path: Path | None = None
        self._shown_notes: tuple[str, int] | None = None
        # 236: what was typed in the notes and the scenes put in them, kept for each version while another is
        # shown, so a refresh, another version or another video never loses them.
        self._drafts: dict[tuple[str, int], tuple[str, list[dict[str, Any]]]] = {}
        # The version playing on the page, (video, version), and Prepare's warnings for each video.
        self._playing_key: tuple[str, int | None] | None = None
        self.prepare_notes: dict[str, dict[str, Any]] = {}
        self.run_recording: Path | None = None
        self.scene_notes: list[dict[str, Any]] = []
        self._signature: tuple[Any, ...] = ()
        self._cards: dict[str, VideoCard] = {}
        # How far "Your videos" was scrolled when a video was opened from it.
        self._start_scroll = 0
        self.tracks_read.connect(self._on_tracks_read)
        self.links_found.connect(self._show_link_dialog)
        changed = getattr(host, "run_availability_changed", None)
        if changed is not None:
            changed.connect(self._on_run_availability_changed)
        job_changed = getattr(host, "job_changed", None)
        if job_changed is not None:
            job_changed.connect(self._on_job_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        # 237: Prepare, Render a preview and Approve and export, while they run: what, how far, time left,
        # and Open in Queue / Progress for that job. Above both views, so it stays in sight in either.
        maker = getattr(host, "make_job_banner", None)
        self.job_banner = maker(PAGE_NAME) if callable(maker) else None
        if self.job_banner is not None:
            layout.addWidget(self.job_banner)
        self.views = _CurrentOnlyStack()
        self.views.setObjectName("aiVideoEditorViews")
        self.start_view = self._build_start_view()
        self.video_view = self._build_video_view()
        self.views.addWidget(self.start_view)
        self.views.addWidget(self.video_view)
        layout.addWidget(self.views, 1)

        self.thumbnails = ThumbnailMaker(
            lambda: str(getattr(self.host.resources, "ffmpeg_exe", "") or "ffmpeg"),
            lambda: app_cache.cache_root(str(self.host.app_settings.get("cache_folder") or "")), self)
        self.thumbnails.ready.connect(self._on_thumbnail)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(int(WATCH_SECONDS * 1000))
        self.watch_timer.timeout.connect(self._watch_disk)
        self._build_dialogs()
        self.refresh()

    # Start view -------------------------------------------------------------

    def _build_start_view(self) -> QWidget:
        view = QWidget()
        view.setObjectName("aiVideoEditorStartView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(16))
        header = QHBoxLayout()
        words = QVBoxLayout()
        title = QLabel(PAGE_NAME)
        title.setProperty("title", True)
        words.addWidget(title)
        words.addWidget(_muted(PAGE_PURPOSE))
        header.addLayout(words, 1)
        self.editor_settings_button = _link("Editor settings")
        self.editor_settings_button.setObjectName("aiVideoEditorSettingsLink")
        self.editor_settings_button.setToolTip("Settings > AI Video Editor: the folder for edited videos, the AI budget "
                                               "for a new video, the model names, export quality and quick passes.")
        self.editor_settings_button.clicked.connect(self.open_editor_settings)
        header.addWidget(self.editor_settings_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.make_video_button = MakeVideoCard()
        self.make_video_button.setToolTip("Choose a recording: the app gets it ready for your AI agent.")
        self.make_video_button.clicked.connect(self.browse_recording)
        self.continue_card: VideoCard | None = None
        self.top_cards = ResponsiveGrid(320, most=2)
        layout.addWidget(self.top_cards)

        videos_header = QHBoxLayout()
        self.videos_title = _section(APP_LABELS["videos"])
        videos_header.addWidget(self.videos_title, 1)
        self.newest_first = QLabel("Newest first")
        self.newest_first.setProperty("small", True)
        videos_header.addWidget(self.newest_first)
        self.refresh_button = _link(APP_LABELS["refresh"])
        self.refresh_button.setToolTip("The page also looks for new versions by itself every few seconds.")
        videos_header.addWidget(self.refresh_button)
        layout.addLayout(videos_header)
        self.refresh_feedback = InlineFeedback()
        self.refresh_feedback.setObjectName("aiVideoEditorRefreshFeedback")
        layout.addWidget(self.refresh_feedback)
        bind_action(self.refresh_button, self._refresh_action, working="Refreshing…", done="Up to date",
                    feedback=self.refresh_feedback)
        # 242 (Wave C2, Q6): videos not linked to their recording yet, and the one dialog that links them.
        link_row = QHBoxLayout()
        self.link_line = _muted("")
        self.link_line.setObjectName("aiVideoEditorLinkLine")
        link_row.addWidget(self.link_line, 1)
        self.link_button = _link("Link recordings…")
        self.link_button.setObjectName("aiVideoEditorLinkRecordings")
        self.link_button.setToolTip("Shows each video not linked to its recording yet, with the evidence; you link the "
                                    "ones you confirm.")
        self.link_button.clicked.connect(self.offer_links)
        link_row.addWidget(self.link_button)
        layout.addLayout(link_row)
        self.link_line.setVisible(False)
        self.link_button.setVisible(False)
        self.link_dialog: LinkRecordingsDialog | None = None
        self.video_cards = ResponsiveGrid(230)
        self.video_cards.setObjectName("aiVideoEditorProjects")
        self.video_cards.setAccessibleName(APP_LABELS["videos"])
        layout.addWidget(self.video_cards)
        self.no_videos = _muted("No videos yet. Make a video from a recording to start.")
        self.no_videos.setObjectName("aiVideoEditorNoVideos")
        layout.addWidget(self.no_videos)
        layout.addStretch(1)
        return view

    # One-video view ---------------------------------------------------------

    def _build_video_view(self) -> QWidget:
        view = QWidget()
        view.setObjectName("aiVideoEditorVideoView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(10))
        header = QHBoxLayout()
        header.setSpacing(theme.px(12))
        self.back_button = _link("← Your videos")
        self.back_button.setObjectName("aiVideoEditorBack")
        self.back_button.clicked.connect(self.show_start)
        header.addWidget(self.back_button)
        self.project_title = QLabel("")
        self.project_title.setObjectName("aiVideoEditorTitle")
        self.project_title.setProperty("sectionTitle", True)
        self.project_title.setWordWrap(True)
        self.project_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self.project_title, 1)
        self.export_button = QPushButton(APP_LABELS["approve"])
        self.export_button.setProperty("primary", True)
        self.export_button.setToolTip("Makes the finished, full-quality video on this PC. Nothing is uploaded.")
        header.addWidget(self.export_button)
        layout.addLayout(header)

        # 236 fix round: the versions as tabs, a divider, then a labelled button for each group of what else
        # there is for the video, each opening a small panel. The row wraps when it does not fit.
        self.toolbar = QWidget()
        self.toolbar.setObjectName("aiVideoEditorToolbar")
        self.toolbar_row = FlowLayout(self.toolbar, spacing=10)
        self.tabs_frame = QFrame()
        self.tabs_frame.setObjectName("versionTabs")
        self.tabs_frame.setAccessibleName("Versions")
        self.tabs_layout = FlowLayout(self.tabs_frame, spacing=3)
        theme.keep_scaled(self.tabs_layout, "setContentsMargins", (3, 3, 3, 3))
        self.tabs_group = QButtonGroup(self)
        self.tabs_group.setExclusive(True)
        self.version_tabs: list[QPushButton] = []
        self.toolbar_row.addWidget(self.tabs_frame)
        self.tabs_divider = QFrame()
        self.tabs_divider.setObjectName("toolbarDivider")
        theme.keep_scaled(self.tabs_divider, "setFixedSize", (1, 38))
        self.toolbar_row.addWidget(self.tabs_divider)
        self.tool_buttons: dict[str, ToolbarButton] = {}
        for key, words, icon in TOOLS:
            button = ToolbarButton(words, icon)
            button.clicked.connect(lambda _checked=False, k=key: self.open_tool(k))
            self.toolbar_row.addWidget(button)
            self.tool_buttons[key] = button
        # What a panel's choice did, said beside the toolbar (UI rules section 7).
        self.actions_feedback = InlineFeedback()
        self.actions_feedback.setObjectName("aiVideoEditorActionsFeedback")
        self.toolbar_row.addWidget(self.actions_feedback)
        layout.addWidget(self.toolbar)
        self.project_details = _muted("")
        self.project_details.setObjectName("aiVideoEditorDetails")
        self.project_details.setProperty("small", True)
        layout.addWidget(self.project_details)

        self.status_sentence = QLabel("")
        self.status_sentence.setObjectName("aiVideoEditorStatus")
        self.status_sentence.setProperty("accent", True)
        # An instruction keeps the accent; a state (working, done, needs a look, failed) uses the rule.
        self.status_sentence.setProperty("plainAccent", True)
        self.status_sentence.setWordWrap(True)
        layout.addWidget(self.status_sentence)

        self.stage = _CurrentOnlyStack()
        self.stage.setObjectName("aiVideoEditorStage")
        # It holds the keyboard focus for a moment while its page changes (``_show_stage``).
        self.stage.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.stage.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.step_page = self._build_step_page()
        self.empty_page = self._build_empty_page()
        self.poster_page = self._build_poster_page()
        self.player_page = _PlayerBox()
        self.player_page.setObjectName("aiVideoEditorPlayer")
        for page in (self.step_page, self.empty_page, self.poster_page, self.player_page):
            self.stage.addWidget(page)
        self.stage.fill = {id(self.empty_page), id(self.poster_page), id(self.player_page)}
        layout.addWidget(self.stage, 1)
        under = layout.indexOf(self.status_sentence)
        layout.insertWidget(under + 1, self.mask_warning)
        layout.insertWidget(under + 2, self.sound_warning)

        # 236 (item 6), fix round: one line under the player: what is playing (its kind, size and frame
        # rate), and what the version has.
        self.files_row = QWidget()
        files = QHBoxLayout(self.files_row)
        files.setContentsMargins(0, 0, 0, 0)
        files.setSpacing(theme.px(12))
        self.playing_label = QLabel("")
        self.playing_label.setObjectName("aiVideoEditorPlaying")
        self.playing_label.setWordWrap(True)
        files.addWidget(self.playing_label, 1)
        self.files_summary = QLabel("")
        self.files_summary.setObjectName("aiVideoEditorFilesSummary")
        self.files_summary.setProperty("small", True)
        # One line: what is playing beside it wraps first.
        self.files_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        files.addWidget(self.files_summary)
        layout.addWidget(self.files_row)
        self.version_note = _muted("")
        self.version_note.setObjectName("aiVideoEditorVersionNote")
        layout.addWidget(self.version_note)

        self.scene_strip = SceneStrip()
        self.scene_strip.jump_requested.connect(self.jump_to_scene)
        self.scene_strip.note_requested.connect(self.add_scene_note)
        layout.addWidget(self.scene_strip)
        layout.addWidget(self._build_notes_box())
        self.usage_label = _muted("")
        self.usage_label.setObjectName("aiVideoEditorUsage")
        self.usage_label.setProperty("small", True)
        layout.addWidget(self.usage_label)
        bind_action(self.export_button, self.start_export, working="Opening…", done="Started",
                    feedback=self.actions_feedback)
        self._build_tool_panels()
        return view

    def _build_step_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("aiVideoEditorSteps")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(12))
        self.step_bar = StepBar(list(STEPS))
        layout.addWidget(self.step_bar)
        self.back_to_player_button = _link("← Back to the player")
        self.back_to_player_button.setObjectName("aiVideoEditorBackToPlayer")
        self.back_to_player_button.clicked.connect(self.back_to_player)
        layout.addWidget(self.back_to_player_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._build_prepare_card())
        layout.addWidget(self._build_prompt_card())
        layout.addStretch(1)
        return page

    def _build_prepare_card(self) -> QFrame:
        card, layout = _card()
        self.prepare_card = card
        card.setObjectName("aiVideoEditorPrepareCard")
        layout.addWidget(_section(f"1  {STEPS[0]}"))
        layout.addWidget(_muted("The app writes down what you said and watches the race on this PC, so your AI agent "
                                "can read it. Nothing is uploaded."))
        self.prepared_label = QLabel("")
        self.prepared_label.setObjectName("aiVideoEditorPrepared")
        self.prepared_label.setWordWrap(True)
        layout.addWidget(self.prepared_label)
        self.prepare_again_button = _link("Change the tracks or the AI budget…")
        self.prepare_again_button.setObjectName("aiVideoEditorPrepareAgain")
        self.prepare_again_button.clicked.connect(lambda: self.show_steps(open_form=True))
        layout.addWidget(self.prepare_again_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.prepare_form = QWidget()
        self.prepare_form.setObjectName("aiVideoEditorPrepareForm")
        form_layout = QVBoxLayout(self.prepare_form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(theme.px(8))
        # 236 (item 1): what the Raw bin, the Inbox and the editor already know about the recording.
        self.knowledge_label = _muted("")
        self.knowledge_label.setObjectName("aiVideoEditorKnowledge")
        self.knowledge_label.setVisible(False)
        form_layout.addWidget(self.knowledge_label)
        recording_row = QHBoxLayout()
        self.recording_label = _muted("No recording chosen.")
        recording_row.addWidget(self.recording_label, 1)
        self.choose_button = QPushButton("Choose a recording…")
        self.choose_button.clicked.connect(self.browse_recording)
        recording_row.addWidget(self.choose_button)
        form_layout.addLayout(recording_row)
        form = QFormLayout()
        # The boxes keep a sensible width instead of running across the whole card.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.voice_combo, self.voice_reset_button, self.voice_state = self._track_box("voice", "Your voice", form)
        self.game_combo, self.game_reset_button, self.game_state = self._track_box("game", "Game sound", form)
        self.budget_combo = WheelSafeComboBox()
        for value, text in BUDGETS:
            self.budget_combo.addItem(text, value)
        self.budget_combo.setCurrentIndex(max(0, self.budget_combo.findData(
            str(self.host.app_settings.get("race_video_budget") or "standard"))))
        self.budget_combo.setToolTip(METADATA_BY_KEY["race_video_budget"].tooltip)
        self.budget_combo.setAccessibleName("AI budget")
        theme.keep_scaled(self.budget_combo, "setMinimumWidth", 240)
        self.budget_combo.currentIndexChanged.connect(self._show_budget_words)
        form.addRow("AI budget", self.budget_combo)
        form_layout.addLayout(form)
        # 236 (item 2): what the budget changes, in plain words, from what the code does.
        self.budget_words = _muted("")
        self.budget_words.setObjectName("aiVideoEditorBudgetWords")
        form_layout.addWidget(self.budget_words)
        self.budget_intro = _muted(BUDGET_INTRO)
        self.budget_intro.setProperty("small", True)
        form_layout.addWidget(self.budget_intro)
        # 226: said on the page, never in a pop-up, before a Prepare would change the tracks of a video
        # that already has versions.
        self.tracks_warning = _muted("")
        self.tracks_warning.setObjectName("aiVideoEditorTracksWarning")
        self.tracks_warning.setVisible(False)
        form_layout.addWidget(self.tracks_warning)
        # Masks first: the AI agent must only ever see blurred cameras.
        masks_row = QHBoxLayout()
        masks_row.setSpacing(theme.px(12))
        self.masks_button = QPushButton("Privacy masks…")
        self.masks_button.setToolTip("Draw the parts of your cameras that are always blurred, before any AI sees a picture.")
        self.masks_button.clicked.connect(self.open_mask_editor)
        masks_row.addWidget(self.masks_button, 0, Qt.AlignmentFlag.AlignTop)
        masks_row.addWidget(_muted("Draw them before you prepare: your AI agent only ever sees blurred cameras."), 1)
        form_layout.addLayout(masks_row)
        prepare_row = FlowLayout()
        self.prepare_button = QPushButton("Prepare for the AI editor")
        self.prepare_button.setProperty("primary", True)
        self.prepare_button.setToolTip("Writes down what you said and watches the race on this PC. "
                                       "It shows on Queue / Progress while it runs.")
        prepare_row.addWidget(self.prepare_button)
        self.prepare_feedback = InlineFeedback()
        self.prepare_feedback.setObjectName("aiVideoEditorPrepareFeedback")
        prepare_row.addWidget(self.prepare_feedback)
        form_layout.addLayout(prepare_row)
        # 237: what Prepare did, said beside it; while it runs, the job banner shows how far it has got.
        bind_action(self.prepare_button, self.start_prepare, working="Starting…", done="Started",
                    feedback=self.prepare_feedback)
        layout.addWidget(self.prepare_form)

        # 226 (decision F): said on the page, never in a pop-up, when Prepare found no masks to apply.
        # 236: under the video's status sentence (``_build_video_view``), so it is in sight over the player
        # as well as over the steps, and only on the video it is about.
        self.mask_warning = _muted("")
        self.mask_warning.setObjectName("aiVideoEditorMaskWarning")
        self.mask_warning.setVisible(False)
        # 226: said on the page after a Prepare, never in a pop-up, when the voice or game track it used
        # is silent for the whole recording.
        self.sound_warning = _muted("")
        self.sound_warning.setObjectName("aiVideoEditorSoundWarning")
        self.sound_warning.setVisible(False)
        self._show_budget_words()
        return card

    def _build_prompt_card(self) -> QFrame:
        card, layout = _card()
        self.prompt_card = card
        card.setObjectName("aiVideoEditorPromptCard")
        layout.addWidget(_section(f"2  {STEPS[1]}"))
        layout.addWidget(_muted("Copy the prompt and paste it into Claude Code or Codex as your first message. Your AI "
                                "agent makes the first version and reviews it itself."))
        prompts = FlowLayout()
        self.copy_claude_button = QPushButton("Copy prompt for Claude Code")
        self.copy_claude_button.setProperty("primary", True)
        self.copy_codex_button = QPushButton("Copy prompt for Codex")
        self.see_prompt_button = _link("See the prompt first")
        self.see_prompt_button.setObjectName("aiVideoEditorSeePrompt")
        for button in (self.copy_claude_button, self.copy_codex_button, self.see_prompt_button):
            prompts.addWidget(button)
        self.prompts_feedback = InlineFeedback()
        self.prompts_feedback.setObjectName("aiVideoEditorPromptsFeedback")
        prompts.addWidget(self.prompts_feedback)
        layout.addLayout(prompts)
        for button, tool in ((self.copy_claude_button, "claude"), (self.copy_codex_button, "codex")):
            bind_action(button, lambda t=tool: self.copy_prompt(t), working="Copying…", done="Copied",
                        feedback=self.prompts_feedback)
        self.see_prompt_button.clicked.connect(lambda: self.see_prompt("claude"))
        heading = QLabel("What happens next")
        heading.setProperty("small", True)
        layout.addWidget(heading)
        self.next_steps = QLabel("<ol style='margin-left:-24px'>" + "".join(f"<li>{step}</li>" for step in NEXT_STEPS)
                                 + "</ol>")
        self.next_steps.setObjectName("aiVideoEditorNextSteps")
        self.next_steps.setTextFormat(Qt.TextFormat.RichText)
        self.next_steps.setWordWrap(True)
        layout.addWidget(self.next_steps)
        return card

    def _build_poster_page(self) -> QWidget:
        """236 fix round: the version's picture as big as the room allows, with the play choices on it."""

        page = PictureBox()
        self.poster = page
        page.least_height = lambda: PLAYING_PICTURE_LEAST + theme.px(PLAYER_ROWS_GUESS)
        layout = page.overlay_layout
        row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        row.setSpacing(theme.px(12))
        page.buttons_row = row
        row.addStretch(1)
        self.play_button = _PlayButton(PLAY_FINAL, primary=True)
        self.play_button.setToolTip("Plays it here, on the page, at once.")
        row.addWidget(self.play_button)
        self.play_preview_button = _PlayButton(PLAY_PREVIEW_BESIDE, primary=False)
        self.play_preview_button.setToolTip("Plays the preview here at once: a quick, smaller render to judge the edit.")
        row.addWidget(self.play_preview_button)
        # A version with no video yet: said on the picture, with the button that makes one.
        self.no_video_label = QLabel("")
        self.no_video_label.setObjectName("posterMessage")
        self.no_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_video_label.setWordWrap(True)
        self.poster_render_button = QPushButton(APP_LABELS["render"])
        self.poster_render_button.setProperty("primary", True)
        self.poster_render_button.setToolTip("Makes this version's preview, to watch it here.")
        row.addWidget(self.poster_render_button)
        row.addStretch(1)
        layout.addWidget(self.no_video_label)
        layout.addLayout(row)
        self.poster_chip = QLabel("")
        self.poster_chip.setObjectName("posterChip")
        layout.addWidget(self.poster_chip, 0, Qt.AlignmentFlag.AlignHCenter)
        self.play_feedback = InlineFeedback()
        self.play_feedback.setObjectName("aiVideoEditorPlayFeedback")
        layout.addWidget(self.play_feedback, 0, Qt.AlignmentFlag.AlignHCenter)
        for button, which in ((self.play_button, "main"), (self.play_preview_button, "beside")):
            bind_action(button, lambda w=which: self.play_choice(w), working="Opening…", done="Playing",
                        feedback=self.play_feedback)
        bind_action(self.poster_render_button, self.start_preview, working="Starting…", done="Started",
                    feedback=self.play_feedback)
        return page

    def _build_empty_page(self) -> QWidget:
        """236 fix round: the player's place before the first version: what is missing and the one next step."""

        page = QFrame()
        page.setObjectName("aiVideoEditorEmpty")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.px(24), theme.px(24), theme.px(24), theme.px(24))
        layout.setSpacing(theme.px(12))
        layout.addStretch(1)
        self.empty_title = QLabel(NO_VERSION_TITLE)
        self.empty_title.setObjectName("aiVideoEditorEmptyTitle")
        self.empty_title.setProperty("sectionTitle", True)
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setWordWrap(True)
        layout.addWidget(self.empty_title)
        row = QHBoxLayout()
        row.addStretch(1)
        self.empty_prepare_button = QPushButton(NO_VERSION_PREPARE)
        self.empty_prepare_button.setProperty("primary", True)
        self.empty_prepare_button.setToolTip("Opens the first step: check the tracks, then prepare.")
        row.addWidget(self.empty_prepare_button)
        self.empty_copy_button = QPushButton("Copy prompt for Claude Code")
        self.empty_copy_button.setProperty("primary", True)
        self.empty_copy_button.setToolTip("Copies the prompt; Prompt, in the row of buttons above, has Codex's.")
        row.addWidget(self.empty_copy_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.empty_feedback = InlineFeedback()
        self.empty_feedback.setObjectName("aiVideoEditorEmptyFeedback")
        self.empty_feedback.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_feedback, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_words = _muted("")
        self.empty_words.setObjectName("aiVideoEditorEmptyWords")
        self.empty_words.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_words)
        layout.addStretch(1)
        bind_action(self.empty_prepare_button, self._open_prepare_step, working="Opening…", done="Opened",
                    feedback=self.empty_feedback)
        bind_action(self.empty_copy_button, lambda: self.copy_prompt("claude"), working="Copying…", done="Copied",
                    feedback=self.empty_feedback)
        return page

    def _build_notes_box(self) -> QFrame:
        box = QFrame()
        box.setObjectName("notesBox")
        self.notes_box = box
        layout = QHBoxLayout(box)
        layout.setContentsMargins(theme.px(16), theme.px(10), theme.px(10), theme.px(10))
        layout.setSpacing(theme.px(10))
        words = QVBoxLayout()
        words.setSpacing(theme.px(6))
        self.notes_title = QLabel(NOTES_TITLE)
        self.notes_title.setProperty("small", True)
        self.notes_title.setWordWrap(True)
        words.addWidget(self.notes_title)
        self.feedback_edit = QPlainTextEdit()
        self.feedback_edit.setObjectName("aiVideoEditorFeedback")
        self.feedback_edit.setAccessibleName(APP_LABELS["notes"])
        self.feedback_edit.setPlaceholderText('For example: "The opening is too slow. Show more of the battle before the crash."')
        theme.keep_scaled(self.feedback_edit, "setMinimumHeight", 56)
        theme.keep_scaled(self.feedback_edit, "setMaximumHeight", 96)
        words.addWidget(self.feedback_edit)
        self.chips_row = FlowLayout(spacing=6)
        self.chips: list[QPushButton] = []
        words.addLayout(self.chips_row)
        layout.addLayout(words, 1)
        buttons = QVBoxLayout()
        buttons.setSpacing(theme.px(6))
        self.save_notes_button = QPushButton(APP_LABELS["save_notes_claude"])
        self.save_notes_button.setProperty("primary", True)
        self.save_notes_codex_button = _link(APP_LABELS["save_notes_codex"])
        buttons.addWidget(self.save_notes_button)
        buttons.addWidget(self.save_notes_codex_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.notes_feedback = InlineFeedback()
        self.notes_feedback.setObjectName("aiVideoEditorNotesFeedback")
        buttons.addWidget(self.notes_feedback)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        for button, tool in ((self.save_notes_button, "claude"), (self.save_notes_codex_button, "codex")):
            bind_action(button, lambda t=tool: self.save_notes(t), working="Saving…", done="Saved and copied",
                        feedback=self.notes_feedback)
        return box

    def _build_tool_panels(self) -> None:
        """236 fix round: each toolbar button's panel, its choices as full-width labelled buttons."""

        handlers: dict[str, Callable[[], Any]] = {
            "voice": lambda: self.show_steps(open_form=True, focus=self.voice_combo),
            "game": lambda: self.show_steps(open_form=True, focus=self.game_combo),
            "budget": lambda: self.show_steps(open_form=True, focus=self.budget_combo),
            "masks": self.open_mask_editor,
            "copy_claude": lambda: self._tool_run(lambda: self.copy_prompt("claude"), "Copying…"),
            "copy_codex": lambda: self._tool_run(lambda: self.copy_prompt("codex"), "Copying…"),
            "see_prompt": lambda: self.see_prompt("claude"),
            "fresh": lambda: self._tool_run(self.start_fresh_edit, "Making it…"),
            "story": lambda: self.show_reader("story"),
            "review": lambda: self.show_reader("review"),
            "play_final": lambda: self._tool_run(lambda: self.play_choice("main"), "Opening…"),
            "play_preview": lambda: self._tool_run(lambda: self.play_choice("beside"), "Opening…"),
            "files": self.show_files,
            "render": lambda: self._tool_run(self.start_preview, "Starting…"),
            "open_project": lambda: self._tool_run(self.open_project_folder, "Opening…"),
            "open_export": lambda: self._tool_run(self.open_export_folder, "Opening…"),
            "refresh": lambda: self._tool_run(self._refresh_action, "Refreshing…"),
        }
        self.tool_panels: dict[str, ToolPanel] = {}
        # Every choice of every panel by its key, as the page enables it and the tests click it.
        self.tool_actions: dict[str, QPushButton] = {}
        self.quality_buttons: dict[str, QPushButton] = {}
        for tool, words, _icon in TOOLS:
            panel = ToolPanel(words, self)
            panel.closed.connect(lambda t=tool: self.tool_buttons[t].set_open(False))
            for entry in TOOL_PANELS[tool]:
                if entry is None:
                    panel.add_divider()
                    continue
                key, text = entry
                if key == "quality":
                    self.quality_heading = panel.add_heading(text)
                    for value, spec in QUALITIES.items():
                        button = panel.add_button(f"quality:{value}", str(spec["label"]),
                                                  lambda v=value: self._quality_chosen(v), close=False, checkable=True)
                        button.setToolTip(f"This video exports at {spec['label']}. Choosing the main setting's "
                                          "quality again follows Settings > AI Video Editor again.")
                        self.quality_buttons[value] = button
                    continue
                self.tool_actions[key] = panel.add_button(key, text, handlers[key])
            panel.add_note()
            self.tool_panels[tool] = panel
        self.tool_actions["render"].setToolTip("Makes this version's preview, to watch it here.")

    def _open_prepare_step(self) -> Outcome:
        """The no-version box's "Prepare for the AI editor…": the first step, its tracks and its Prepare button."""

        self.show_steps(open_form=True, focus=self.prepare_button)
        return Outcome.quiet()

    def _build_dialogs(self) -> None:
        self.export_dialog = ApproveExportDialog(self)
        self.export_quality_combo = self.export_dialog.quality_combo
        self.export_quality_combo.setObjectName("aiVideoEditorExportQuality")
        self.export_quality_combo.setAccessibleName("Export quality for this video")
        for value, spec in QUALITIES.items():
            self.export_quality_combo.addItem(str(spec["label"]), value)
        self.export_quality_combo.setToolTip(
            "How this video's export is compressed. It follows Settings > AI Video Editor until you choose "
            "another here; choosing the main setting's quality again follows it again.")
        self.export_quality_combo.currentIndexChanged.connect(self._on_export_quality_changed)
        self.export_quality_state = self.export_dialog.quality_state
        self.export_quality_state.setObjectName("aiVideoEditorExportQualityState")
        self.export_quality_label = self.export_dialog.quality_label
        self.export_dialog.accepted.connect(self._export_approved)
        self.story_reader = ReaderDialog("The story", self)
        self.review_reader = ReaderDialog("The editor's own review", self)
        self.story_view = self.story_reader.full_view
        self.review_view = self.review_reader.full_view
        self.prompt_dialog = PromptDialog(self._prompt_for_dialog, self)
        self.prompt_dialog.copied.connect(self._prompt_copied)
        self.files_dialog = VersionFilesDialog(self)
        self.files_dialog.play_requested.connect(lambda path: self.play_path(Path(path)))

    def _track_box(self, name: str, text: str, form: QFormLayout) -> tuple[WheelSafeComboBox, QPushButton, QLabel]:
        """One track box (226): Auto or a track, a reset back to Auto, and what Auto picks."""

        combo = WheelSafeComboBox()
        combo.setObjectName(f"aiVideoEditor{name.title()}Track")
        combo.setAccessibleName(text)
        combo.setToolTip(TRACK_TOOLTIPS[name])
        combo.addItem(AUTO, None)
        theme.keep_scaled(combo, "setMinimumWidth", 240)
        combo.currentIndexChanged.connect(self._on_track_choice_changed)
        if name == "voice":
            # 264 (Q4): your pick here is your answer for this recording, on every screen; Auto clears it.
            combo.currentIndexChanged.connect(self._on_voice_choice_changed)
        reset = QPushButton("Reset to Auto")
        reset.setObjectName(f"aiVideoEditor{name.title()}Reset")
        reset.setToolTip(f"Go back to Auto: the track your track names or your {TRACK_ROLES_FIELD} give.")
        reset.setVisible(False)
        reset.clicked.connect(lambda: combo.setCurrentIndex(0))
        form.addRow(text, combo)
        state = _muted("")
        state.setObjectName(f"aiVideoEditor{name.title()}State")
        # What Auto picks, on a line of its own across the card, then the reset under it (226: beside it,
        # the words were squeezed to a few letters a line); shown once a recording's tracks are known, so
        # an empty line takes no room before that.
        state.setVisible(False)
        self._track_rows[name] = state
        form.addRow(state)
        form.addRow(reset)
        return combo, reset, state

    # State ------------------------------------------------------------------

    @property
    def output_root(self) -> Path:
        return editor_output_root(self.host.app_settings)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        # Settings may have changed while the page was hidden: the Track roles Auto follows, and the
        # main export quality a video without its own follows.
        self._show_track_states()
        self._show_export_quality()
        # 236: the page looks for what the AI editor made while it is shown.
        self.watch_timer.start()
        if not self._watch_disk():
            # 242 (Wave C2, design 2.8): the library's index is repaired whenever the page is shown, and a recording
            # renamed or moved while the page was hidden is offered for linking at once.
            self._index_projects()
            self._show_link_line()
        if self.view == "video" and self.stage.currentWidget() is self.player_page and not self._player_here():
            self._show_stage(self.poster_page)

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        super().hideEvent(event)
        self.watch_timer.stop()
        self._close_tool_panels()
        # 236: the player goes back to being its own window when the page is left.
        self._undock_player()

    def refresh(self) -> None:
        """Read every project from disk and show it, keeping the video and version chosen where they still exist."""

        try:
            self.projects = list_projects(self.output_root) if str(self.output_root) else []
        except OSError:
            self.projects = []
        self._signature = self._disk_signature()
        # 242 (Wave C2, design 2.8): Refresh, a change on disk and the end of a run all come here.
        self._index_projects()
        self._show_link_line()
        self._show_cards()
        if self.view == "video":
            self._show_video()
        if self.recording is not None and self.track_titles is not None:
            # A Prepare or the AI editor may have changed the chosen recording's video since it was chosen.
            self.earlier = self._read_earlier(self.recording)
            self._show_tracks_warning()
        self._refresh_state()

    def _disk_signature(self) -> tuple[Any, ...]:
        """What changes on disk when the AI editor or a run adds a version, a render or an export: the
        times of each project's files and folders that hold them (cheap: no file is read)."""

        root = self.output_root / "race-videos" if str(self.output_root) else None
        found: list[Any] = []
        if root is None or not root.is_dir():
            return ()
        try:
            projects = sorted(item for item in root.iterdir() if item.is_dir() and not item.name.startswith("."))
        except OSError:
            return ()
        for project in projects:
            for path in (project / "project.json", project / "export", project / "feedback"):
                try:
                    stat = path.stat()
                    found.append((str(path), stat.st_mtime_ns, stat.st_size))
                except OSError:
                    found.append((str(path), None))
            versions = project / "versions"
            try:
                for version in sorted(versions.iterdir()):
                    for path in (version, version / "renders"):
                        try:
                            found.append((str(path), path.stat().st_mtime_ns))
                        except OSError:
                            pass
            except OSError:
                pass
        return tuple(found)

    def _watch_disk(self) -> bool:
        """Refresh when the projects changed on disk; True when it did."""

        if not self.isVisible():
            return False
        signature = self._disk_signature()
        if signature != self._signature:
            self.refresh()
            return True
        return False

    def _index_projects(self) -> None:
        """242 (Wave C2, audit M2): make the library's index of the projects match their files. It never writes to a
        project, and a library that cannot be written changes nothing on the page."""

        records = getattr(self.host, "records", None)
        if not isinstance(records, Records) or not str(self.output_root):
            return
        try:
            reconcile(records, self.output_root, projects=self.projects)
        except (OSError, sqlite3.Error, ValueError, KeyError):
            pass

    def _needing_link(self) -> list[dict[str, Any]]:
        return [project for project in self.projects
                if not project.get("content_sha256") or not Path(str(project.get("source") or "")).is_file()]

    def _show_link_line(self) -> None:
        count = len(self._needing_link())
        self.link_line.setText(
            f"{count} video{'s are' if count != 1 else ' is'} not linked to {'their recordings' if count != 1 else 'its recording'} "
            "yet. Linking lets their edits follow a recording that is moved or renamed." if count else "")
        self.link_line.setVisible(bool(count))
        self.link_button.setVisible(bool(count))

    def offer_links(self) -> None:
        """Link recordings… (242, Wave C2, Q6): one dialog listing each video not linked yet, with its evidence. The
        library is only read here and no recording is read; linking one reads it when the library has not."""

        cache = app_cache.cache_root(str(self.host.app_settings.get("cache_folder") or ""))
        folders = [Path(project["folder"]) for project in self._needing_link()]
        self.link_button.setEnabled(False)
        self.link_line.setText("Looking at the evidence for each video…")

        def look() -> None:
            # Off the window's thread: it looks at each recording's folder, which can be a sleeping drive.
            connection = None
            evidence: list[Any] = []
            try:
                connection = recording_records.connect_read_only()
                evidence = [link.evidence_for(folder, connection=connection, cache=cache) for folder in folders]
            except Exception:  # noqa: BLE001 - without the library the evidence is looked at without it
                evidence = [link.evidence_for(folder, cache=cache) for folder in folders]
            finally:
                if connection is not None:
                    connection.close()
            try:
                self.links_found.emit(evidence)
            except RuntimeError:
                pass  # the window closed meanwhile

        threading.Thread(target=look, name="ai-video-editor-link-evidence", daemon=True).start()

    def _show_link_dialog(self, evidence: list[Any]) -> None:
        self.link_button.setEnabled(True)
        self._show_link_line()
        if self.link_dialog is not None:
            self.link_dialog.close()
        self.link_dialog = LinkRecordingsDialog(evidence, self)
        self.link_dialog.finished.connect(lambda _code: self.refresh())
        self.link_dialog.show()
        self.link_dialog.raise_()

    def project_by_folder(self, folder: str) -> dict[str, Any] | None:
        for project in self.projects:
            if project["folder"] == folder:
                return project
        return None

    def current_project(self) -> dict[str, Any] | None:
        return self.project_by_folder(self.project_folder) if self.project_folder else None

    def current_version(self) -> dict[str, Any] | None:
        project = self.current_project()
        if not project or self.version_number is None:
            return None
        for version in project["versions"]:
            if int(version["version"]) == self.version_number:
                return version
        return None

    def _running_for(self, project: dict[str, Any]) -> str:
        """The page's job running for this video, or ""."""

        if not self.running:
            return ""
        if self.run_kind == "prepare":
            return "prepare" if self.run_project and self.run_project == project["folder"] else ""
        return self.run_kind if self.run_project == project["folder"] else ""

    def _job_percent(self) -> int | None:
        snapshot = getattr(self.host, "job_snapshot", None)
        info = snapshot() if callable(snapshot) else None
        return info.percent if info is not None and info.origin == PAGE_NAME and info.running else None

    def _last_project(self) -> dict[str, Any] | None:
        return max(self.projects, key=lambda project: str(project.get("activity") or project.get("created") or ""),
                   default=None)

    def _show_cards(self) -> None:
        """The start view: Make a video, Continue: <the video worked on last>, and a card per video."""

        last = self._last_project()
        percent = self._job_percent()
        if last is not None:
            if self.continue_card is None:
                self.continue_card = VideoCard(last, wide=True)
                self.continue_card.clicked.connect(lambda: self.open_video(self.continue_card.project["folder"]))
            self.continue_card.set_project(last, self._running_for(last), percent)
            self._ask_picture(self.continue_card)
            self.top_cards.set_cards([self.make_video_button, self.continue_card])
        else:
            # set_cards deletes a card it no longer holds.
            self.top_cards.set_cards([self.make_video_button])
            self.continue_card = None
        cards: list[QWidget] = []
        kept: dict[str, VideoCard] = {}
        for project in self.projects:
            card = self._cards.get(project["folder"])
            if card is None:
                card = VideoCard(project)
                card.clicked.connect(lambda _checked=False, folder=project["folder"]: self.open_video(folder))
            card.set_project(project, self._running_for(project), percent)
            self._ask_picture(card)
            kept[project["folder"]] = card
            cards.append(card)
        self._cards = kept
        self.video_cards.set_cards(cards)
        self.video_cards.setVisible(bool(cards))
        self.no_videos.setVisible(not cards)
        self.newest_first.setVisible(bool(cards))

    def _ask_picture(self, card: VideoCard) -> None:
        source = thumbnail_source(card.project)
        card.setProperty("thumbKey", source.key if source else "")
        if source is None:
            card.set_picture(None)
            return
        picture = self.thumbnails.picture(source)
        card.set_picture(str(picture) if picture else None)

    def _on_thumbnail(self, key: str, path: str) -> None:
        for card in [*self._cards.values(), *([self.continue_card] if self.continue_card else [])]:
            if card.property("thumbKey") == key:
                card.set_picture(path)
        if self.view == "video":
            self._show_poster()

    def _on_job_changed(self) -> None:
        # The Getting ready… percent of the video being prepared, on its card only.
        if not self.running:
            return
        percent = self._job_percent()
        for card in [*self._cards.values(), *([self.continue_card] if self.continue_card else [])]:
            running = self._running_for(card.project)
            if running:
                card.set_project(card.project, running, percent)

    # Moving between the views ---------------------------------------------------

    def show_start(self) -> None:
        """Back to "Your videos"."""

        self._undock_player()
        # The dialogs of the video shown (its prompt, its story and review, its files) go with it.
        self._close_video_dialogs()
        self.view = "start"
        self.steps_asked = False
        self.views.setCurrentWidget(self.start_view)
        self.refresh()
        # Back where the list was left (the 150% walk: a long list is scrolled to reach a card).
        self._scroll_page_to(self._start_scroll)

    def open_video(self, folder: str) -> None:
        """Open one video: its newest version chosen, ready to play."""

        if folder != self.project_folder:
            # What the page said, and the dialogs it opened, were about the video shown before.
            if not self.running:
                self._say("")
            self._close_video_dialogs()
        # Opened from its card, a video shows its newest version (what was typed for another one waits).
        self.version_number = None
        self.project_folder = folder
        project = self.project_by_folder(folder)
        source = Path(project["source"]) if project and project.get("source") else None
        if self.recording is not None and source != self.recording:
            # Another video's recording was chosen before; this video's own is the one its steps use.
            self._forget_recording()
        self.steps_asked = False
        self._form_open = False
        if self.view == "start":
            self._start_scroll = self._page_scroll()
        self.view = "video"
        self.views.setCurrentWidget(self.video_view)
        # The video opens at its top, its name and toolbar in sight, wherever the list was scrolled to.
        self._scroll_page_to(0)
        self._show_video()
        self._refresh_state()
        if project and not project.get("analysed") and source is not None and self.recording is None:
            self.set_recording(source, keep_project=True)

    def _page_bar(self) -> Any:
        stack = getattr(self.host, "page_stack", None)
        scroll_for = getattr(stack, "scroll_for", None)
        area = scroll_for(self) if callable(scroll_for) else None
        return area.verticalScrollBar() if area is not None else None

    def _page_scroll(self) -> int:
        bar = self._page_bar()
        return bar.value() if bar is not None else 0

    def _scroll_page_to(self, value: int) -> None:
        """Scroll the page's own scroll area, now and again once the view shown has been laid out."""

        bar = self._page_bar()
        if bar is None:
            return
        bar.setValue(value)
        QTimer.singleShot(0, lambda: bar.setValue(value))

    def _forget_recording(self) -> None:
        """No recording chosen: its tracks, its warnings and what the app knew about it go with it."""

        self.recording = None
        self.track_titles = None
        self.earlier = {}
        self.probing = False
        self._probe_number += 1
        self.recording_label.setText("No recording chosen.")
        self._fill_track_boxes([])
        self._show_knowledge()

    def _close_video_dialogs(self) -> None:
        for dialog in (self.prompt_dialog, self.story_reader, self.review_reader, self.files_dialog):
            dialog.hide()
        self._close_tool_panels()

    def _close_tool_panels(self) -> None:
        for panel in getattr(self, "tool_panels", {}).values():
            panel.hide()

    def show_steps(self, *, open_form: bool = False, focus: QWidget | None = None) -> None:
        """The steps of this video in the player's place (236): Video settings > Your voice, Game sound or
        AI budget, and the no-version box's Prepare for the AI editor…."""

        project = self.current_project()
        if project is not None and project.get("source") and self.recording is None:
            self.set_recording(Path(project["source"]), keep_project=True)
        self.steps_asked = True
        self._form_open = open_form or not (project and project.get("analysed"))
        self._undock_player()
        if not self.probing:
            self._show_budget_choice()
        self._show_video()
        if focus is not None:
            focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def back_to_player(self) -> None:
        self.steps_asked = False
        self._show_video()

    def _show_stage(self, page: QWidget) -> None:
        """Show ``page`` in the player's place. The keyboard focus on what goes out of sight moves to the place
        itself first: otherwise Qt hands it to the next control and the page scrolls there (the walk on the real
        screen saw Play scroll the title and the toolbar out of sight at 150%)."""

        current, focus = self.stage.currentWidget(), QApplication.focusWidget()
        if current is not None and current is not page and focus is not None and current.isAncestorOf(focus):
            self.stage.setFocus(Qt.FocusReason.OtherFocusReason)
        self.stage.setCurrentWidget(page)

    def _player_here(self) -> bool:
        opener = getattr(self.host, "video_opener", None)
        docked = getattr(opener, "docked_in", None)
        return callable(docked) and docked() is self.player_page

    def _undock_player(self) -> None:
        opener = getattr(self.host, "video_opener", None)
        undock = getattr(opener, "undock", None)
        if callable(undock) and self._player_here():
            undock(self.player_page)
        self._playing_path = None
        if self.view == "video" and self.stage.currentWidget() is self.player_page:
            self._show_stage(self.poster_page)
        self._show_playing_line()

    def _let_go_of_video(self) -> None:
        """Before a render or an export replaces a video file: the player gives it back (236)."""

        self._undock_player()
        opener = getattr(self.host, "video_opener", None)
        release = getattr(opener, "release_media", None)
        if callable(release):
            release()
        self._playing_key = None
        self._playing_path = None

    # The one-video view ---------------------------------------------------------

    def _show_video(self) -> None:
        project = self.current_project()
        versions = project["versions"] if project else []
        numbers = [int(version["version"]) for version in versions]
        if self.version_number not in numbers:
            self.version_number = numbers[0] if numbers else None
        name = project["name"] if project else (self.recording.stem if self.recording else "New video")
        self.project_title.setText(name)
        details = []
        if project:
            details.append(f"From {Path(str(project['source'])).name}")
            budget = dict(BUDGETS).get(project["budget"], "")
            if budget:
                details.append(f"{budget} AI budget")
            if project.get("edit_of"):
                details.append(f"a separate edit of {project['edit_of']}")
        elif self.recording is not None:
            details.append(f"From {self.recording.name}")
        version = self.current_version()
        if version and version.get("editor_label"):
            # What the version answers can be a paragraph: it is in the version tab's tooltip.
            details.append(f"{version['label']} by {version['editor_label']}")
        self.project_details.setText(" · ".join(details))
        self._show_tabs(versions)
        has_versions = bool(versions)
        analysed = bool(project and project.get("analysed"))
        # A recording with no video yet shows its steps; a video with no version, the box that says so.
        show_steps = self.steps_asked or project is None
        if show_steps:
            # Nothing keeps playing out of sight behind the steps.
            self._undock_player()
            self._show_step_page(project, analysed, has_versions)
            self._show_stage(self.step_page)
        elif not has_versions:
            self._undock_player()
            self._show_empty_page(project, analysed)
            self._show_stage(self.empty_page)
        elif self.stage.currentWidget() in (self.step_page, self.empty_page) or not self._player_here():
            self._show_stage(self.poster_page)
        if not show_steps and self._player_here() and self._playing_key != (self.project_folder, self.version_number):
            # Another version or video was chosen while one played: it waits on the picture for its own Play.
            self._undock_player()
        self.toolbar.setVisible(project is not None)
        self.files_row.setVisible(not show_steps and has_versions)
        self.scene_strip.setVisible(not show_steps and has_versions)
        self.notes_box.setVisible(not show_steps and has_versions)
        self._show_version_details(version, show_steps)
        self._show_prepare_notes()
        self.usage_label.setText(self._usage_text(Path(project["folder"])) if project else "")
        self.usage_label.setVisible(bool(self.usage_label.text()))
        self._show_export_quality()
        self._refresh_state()

    def _show_tabs(self, versions: list[dict[str, Any]]) -> None:
        wanted = [(int(version["version"]), version["label"] + (" · newest" if index == 0 else ""),
                   version) for index, version in enumerate(versions)]
        if [button.property("version") for button in self.version_tabs] != [number for number, _text, _v in wanted] \
                or [button.text() for button in self.version_tabs] != [text for _n, text, _v in wanted]:
            for button in self.version_tabs:
                self.tabs_group.removeButton(button)
                self.tabs_layout.removeWidget(button)
                button.deleteLater()
            self.version_tabs = []
            # Oldest on the left, as the mockup reads: v001, v002 · newest.
            for number, text, version in reversed(wanted):
                button = _VersionTab(text)
                button.setObjectName("versionTab")
                button.setCheckable(True)
                button.setProperty("version", number)
                tip = [f"{version['label']}"]
                if version.get("editor_label"):
                    tip.append(f"made by {version['editor_label']}")
                if version.get("answers"):
                    tip.append(str(version["answers"]))
                button.setToolTip(" · ".join(tip + ["Double-click to play it."]))
                button.setAccessibleName(f"Version {number}")
                button.clicked.connect(lambda _checked=False, n=number: self.choose_version(n))
                # Double-click plays, as it did on the versions list (UI rules section 8).
                button.double_clicked.connect(lambda n=number: self._play_version(n))
                self.tabs_group.addButton(button)
                self.tabs_layout.addWidget(button)
                self.version_tabs.append(button)
        for button in self.version_tabs:
            button.setChecked(button.property("version") == self.version_number)
        self.tabs_frame.setVisible(bool(self.version_tabs))
        self.tabs_divider.setVisible(bool(self.version_tabs))

    def _play_version(self, number: int) -> None:
        self.choose_version(number)
        # Through the picture's main play choice, so it says what it did beside it.
        if self.play_button.isVisible() or self.play_button.isVisibleTo(self.poster_page):
            self.play_button.click()

    def choose_version(self, number: int) -> None:
        if number == self.version_number:
            return
        self.version_number = number
        self._show_video()

    def _show_step_page(self, project: dict[str, Any] | None, analysed: bool, has_versions: bool) -> None:
        current = 0 if not analysed else (1 if not has_versions else 2)
        self.step_bar.set_current(current)
        form_open = getattr(self, "_form_open", False) or not analysed
        self.prepare_form.setVisible(form_open)
        self.prepare_again_button.setVisible(analysed and not form_open)
        self.prompt_card.setVisible(analysed)
        # Back to the player's place: the picture, or the box that says no version is made yet.
        self.back_to_player_button.setVisible(project is not None)
        if analysed and project:
            tracks = prepared_tracks(Path(project["folder"]))
            said = [f"Track {tracks[name] + 1} is {_TRACK_WORDS[name]}" for name in ("voice", "game") if name in tracks]
            budget = dict(BUDGETS).get(project["budget"], project["budget"] or "")
            self.prepared_label.setText("Prepared. " + (", ".join(said) + ". " if said else "")
                                        + (f"AI budget: {budget}." if budget else ""))
            _show_kind(self.prepared_label, run_status.COMPLETED)
        else:
            self.prepared_label.setText("")
        self.prepared_label.setVisible(bool(self.prepared_label.text()))
        self._show_knowledge()

    def _show_empty_page(self, project: dict[str, Any], analysed: bool) -> None:
        """236 fix round: a video with no version yet. The player's place says so, offers the one next step
        and says in a sentence what happens after."""

        preparing = self._running_for(project) == "prepare"
        self.empty_title.setText(PREPARING_TITLE if preparing else NO_VERSION_TITLE)
        self.empty_prepare_button.setVisible(not preparing and not analysed)
        self.empty_copy_button.setVisible(not preparing and analysed)
        self.empty_words.setText(NO_VERSION_WORDS["preparing" if preparing else "copy" if analysed else "prepare"])

    def _show_version_details(self, version: dict[str, Any] | None, show_steps: bool) -> None:
        if version is None or show_steps:
            self.playing_label.setText("")
            self.files_summary.setText("")
            self.version_note.setText("")
            self.version_note.setVisible(False)
            self.scene_strip.set_blocks([])
            self._show_poster()
            self._show_notes(None)
            return
        self.files_summary.setText(f"{version['label']} has: {files_summary(version)}")
        self._show_playing_line()
        main, _beside = play_choices(version)
        roles = {item["role"] for item in version["files"]}
        note, kind = "", ""
        if version["preview_passed"] is False:
            note, kind = "This preview failed the technical check; ask the AI editor to look at it.", "attention"
        elif main is not None and not roles & {ROLE_PREVIEW, ROLE_FINAL, ROLE_EXPORT}:
            note = (f"The app has made no preview of {version['label']} yet: press {APP_LABELS['files_tool']}, then "
                    f"{APP_LABELS['render']}.")
        if version["final_passed"] is False:
            note, kind = "The full-quality render failed the technical check, so it was not exported.", "attention"
        self.version_note.setText(note)
        _show_kind(self.version_note, kind)
        self.version_note.setVisible(bool(note))
        blocks: list[dict[str, Any]] = []
        if version.get("timeline"):
            try:
                blocks = story_blocks(json.loads(Path(version["timeline"]).read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                blocks = []
        self.scene_strip.set_blocks(blocks)
        self._show_poster()
        self._show_notes(version)

    def _show_poster(self) -> None:
        """The chosen version's picture with its play choices on it (236 fix round)."""

        project, version = self.current_project(), self.current_version()
        picture = None
        if project and version:
            source = thumbnail_source({**project, "versions": [version]})
            picture = self.thumbnails.picture(source) if source else None
        self.poster.set_picture(str(picture) if picture else None)
        main, beside = play_choices(version)
        if main is not None and self.play_button.property("busy") is not True:
            self.play_button.setText(play_label(main))
        self.play_button.setVisible(main is not None)
        self.play_preview_button.setVisible(beside is not None)
        self.no_video_label.setText(f"{version['label']} has no video yet." if version and main is None else "")
        self.no_video_label.setVisible(bool(version) and main is None)
        self.poster_render_button.setVisible(bool(version) and main is None)
        self.poster_chip.setText(chip_words(version) if version else "")
        self.poster_chip.setVisible(bool(version) and main is not None)
        self.poster.place_overlay()

    def _show_playing_line(self) -> None:
        """The one line under the player: what is playing, its kind, size and frame rate (236 fix round)."""

        if not hasattr(self, "playing_label"):
            return
        version = self.current_version()
        if version is None:
            self.playing_label.setText("")
            return
        if self._playing_path is not None and self._player_here():
            row = next((item for item in version["files"] if Path(item["path"]) == self._playing_path), None)
            self.playing_label.setText(playing_words(version, row or {"name": self._playing_path.name, "role": ""}))
        elif play_choices(version)[0] is None:
            self.playing_label.setText(playing_words(version, None))
        else:
            self.playing_label.setText(f"Press Play on the picture to watch {version['label']} here.")

    def _show_notes(self, version: dict[str, Any] | None) -> None:
        """The notes box shows the version's saved notes when another version is chosen; what is being
        typed is never replaced by a refresh (236: the page looks for new versions by itself)."""

        if version is None:
            # Hidden with the steps; what was typed waits for the way back.
            return
        key = (self.project_folder, int(version["version"]))
        if key == self._shown_notes:
            return
        if self._shown_notes is not None:
            self._drafts[self._shown_notes] = (self.feedback_edit.toPlainText(), [dict(b) for b in self.scene_notes])
        self._shown_notes = key
        self._clear_scene_notes()
        if key in self._drafts:
            words, chosen = self._drafts[key]
            self.feedback_edit.setPlainText(words)
            for block in chosen:
                self._add_chip(block)
            return
        words, scenes = split_scene_notes(_text(version["feedback"]))
        self.feedback_edit.setPlainText(words)
        # The scenes the saved notes name come back as their chips, so saving again keeps them.
        for block in self.scene_strip.blocks:
            if scene_note_line(block.block) in scenes:
                self._add_chip(block.block)

    def _usage_text(self, project: Path) -> str:
        try:
            totals = usage_report(project)["totals"]
        except (OSError, ValueError, KeyError):
            return ""
        if not totals:
            return ""
        return "Handed to the AI editor so far: " + ", ".join(f"{count} {kind}" for kind, count in totals.items()) + "."

    def _show_knowledge(self) -> None:
        """236 (item 1): what the app already knows about the chosen recording, under Prepare's steps."""

        if self.recording is None:
            self.knowledge_label.setVisible(False)
            return
        row = None
        key = os.path.normcase(os.path.abspath(str(self.recording)))
        for item in self._library_rows():
            # 268: a Missing recording that had this path is not the one there now.
            if not item.get("missing") and os.path.normcase(os.path.abspath(str(item.get("path") or ""))) == key:
                row = item
                break
        project = self.current_project()
        words = knowledge_words(row, project if project and project.get("analysed") else None)
        # 264: a calm line when your answer differs from what the app heard; no extra detection runs to compare.
        chose = speech_facts.narration_answer(self.recording).you_chose
        if chose:
            words = f"{words}. {chose}" if words else chose
        self.knowledge_label.setText(f"What the app knows about it: {words}" if words else "")
        self.knowledge_label.setVisible(bool(words))

    def _library_rows(self) -> list[dict[str, Any]]:
        return library_recordings()

    def _on_run_availability_changed(self) -> None:
        # 220: another feature's run started or ended; Prepare follows it.
        if hasattr(self, "prepare_button"):
            self._refresh_state()

    def _refresh_state(self) -> None:
        project = self.current_project()
        version = self.current_version()
        busy = self.running or getattr(self.host, "runner_thread", None) is not None
        analysed = bool(project and project["analysed"])
        self.prepare_button.setEnabled(not busy and self.recording is not None and not self.probing)
        for combo in (self.voice_combo, self.game_combo):
            combo.setEnabled(bool(self.track_titles) and not self.running)
        for button in (self.copy_claude_button, self.copy_codex_button, self.see_prompt_button):
            button.setEnabled(analysed)
        # Fix round: nothing to approve before the first version, so the button waits until there is one.
        self.export_button.setVisible(bool(project and project["versions"]))
        self.export_button.setEnabled(bool(version and version["preview"]) and not busy)
        self.export_button.setToolTip(
            "Makes the finished, full-quality video on this PC. Nothing is uploaded." if version and version["preview"]
            else "Watch a preview of a version first: Approve and export… needs one.")
        self.export_quality_combo.setEnabled(project is not None and not self.running)
        for button in (self.save_notes_button, self.save_notes_codex_button):
            button.setEnabled(bool(version) and analysed)
        self.masks_button.setEnabled(project is not None or self.recording is not None)
        self.empty_copy_button.setEnabled(analysed)
        self.poster_render_button.setEnabled(bool(version) and not busy)
        # 236 fix round: every choice of the toolbar's panels stays in sight; one not possible now is greyed
        # out and its tooltip says why.
        no_version = NO_VERSION_WHY if not version else ""
        why = {
            "voice": "", "game": "", "budget": "",
            "masks": "" if project is not None or self.recording is not None else "Choose a recording first.",
            "copy_claude": "" if analysed else NOT_PREPARED_WHY,
            "copy_codex": "" if analysed else NOT_PREPARED_WHY,
            "see_prompt": "" if analysed else NOT_PREPARED_WHY,
            "fresh": NOT_PREPARED_WHY if not analysed else BUSY_WHY if busy else "",
            "story": no_version, "review": no_version, "files": no_version,
            "render": no_version or (BUSY_WHY if busy else ""),
            "play_final": no_version, "play_preview": no_version,
            "open_project": "" if project is not None else "This video has no project folder yet.",
            "open_export": "" if project and project["exports"] else
                           f"Nothing is exported yet: {APP_LABELS['approve']} makes the export.",
            "refresh": "",
        }
        tips = {"voice": "Shows the tracks this video was prepared with; change them and prepare again.",
                "game": "Shows the tracks this video was prepared with; change them and prepare again.",
                "budget": "Shows the AI budget; a new budget needs the recording prepared again.",
                "masks": "Draw the parts of your cameras that are always blurred, before any AI sees a picture.",
                "copy_claude": "Copies the prompt; paste it into Claude Code.",
                "copy_codex": "Copies the prompt; paste it into Codex.",
                "see_prompt": "Shows the prompt, ready to change before you copy it.",
                "fresh": "A separate edit of the same recording, with no versions and a fresh AI budget.",
                "story": "The story this version tells, as the AI editor wrote it.",
                "review": "What the AI editor found when it watched this version, and its technical report.",
                "files": "Every file of this version, what each one is, and which one plays.",
                "render": render_words(version) if version else "",
                "play_final": "Plays the final here at once.", "play_preview": "Plays the preview here at once.",
                "open_project": "Opens this video's folder in File Explorer.",
                "open_export": "Opens the folder with the exported video in File Explorer.",
                "refresh": "Looks for new versions now (the page also looks by itself every few seconds)."}
        for key, button in self.tool_actions.items():
            button.setEnabled(not why[key])
            button.setToolTip(why[key] or tips[key])
        for button in self.quality_buttons.values():
            button.setEnabled(project is not None and not self.running)
        _main, beside = play_choices(version)
        # The play choices are in Files for a version with a final and a preview, so the other is one click away.
        for key in ("play_final", "play_preview"):
            self.tool_actions[key].setVisible(beside is not None)
        for tool, panel in self.tool_panels.items():
            panel.show_why([why[key] for key, button in panel.buttons.items()
                            if key in why and not button.isHidden() and not button.isEnabled()])
        # 237: while its job runs, the button that started it says what it is doing.
        here = bool(project) and self.run_project == project["folder"]
        for kind, button, idle, busy_text in (("prepare", self.prepare_button, "Prepare for the AI editor", "Preparing…"),
                                              ("export", self.export_button, APP_LABELS["approve"], "Exporting…")):
            button.setText(busy_text if self.running and self.run_kind == kind and (kind == "prepare" or here) else idle)
        self.tool_actions["render"].setText("Rendering a preview…" if self.running and self.run_kind == "preview" and here
                                            else APP_LABELS["render"])

    def _say(self, text: str, state: str = "") -> None:
        """Show the page's status sentence; ``state`` colours it by the one status rule."""

        self.status_sentence.setText(text)
        _show_kind(self.status_sentence, state)
        self.status_sentence.setVisible(bool(text))

    # The toolbar ----------------------------------------------------------------------

    def open_tool(self, key: str) -> None:
        """A toolbar button: its panel opens under it; pressed again, it closes (236 fix round)."""

        panel = self.tool_panels[key]
        if panel.isVisible():
            panel.hide()
            return
        if panel.closed_by_a_press_on(self.tool_buttons[key]):
            # The press on this button closed the panel a moment ago; the click it ends does not open it again.
            return
        self._close_tool_panels()
        self._refresh_state()
        self._show_export_quality()
        self.tool_buttons[key].set_open(True)
        panel.open_under(self.tool_buttons[key])

    def _tool_run(self, handler: Callable[[], Any], working: str) -> None:
        """A panel's choice that does something: its feedback is said beside the toolbar (UI rules 7)."""

        self.actions_feedback.working(working)
        QApplication.processEvents()
        try:
            outcome = handler()
        except Exception as exc:  # noqa: BLE001 - every failure is said beside the button
            self.actions_feedback.failed(f"That did not work: {exc}")
            return
        if isinstance(outcome, Outcome) and outcome.kind == "failed":
            self.actions_feedback.failed(outcome.text, outcome.next_step)
        elif isinstance(outcome, Outcome) and outcome.kind == "quiet":
            self.actions_feedback.clear()
        else:
            self.actions_feedback.done(outcome.text if isinstance(outcome, Outcome) and outcome.text else "Done")

    def open_editor_settings(self) -> None:
        """"Editor settings": Settings > AI Video Editor."""

        navigate = getattr(self.host, "navigate", None)
        if callable(navigate):
            navigate("Settings")
        tabs = getattr(self.host, "settings_tabs", None)
        panel = getattr(self.host, "ai_video_editor_settings", None)
        if tabs is not None and panel is not None:
            tabs.setCurrentWidget(panel)

    def show_reader(self, which: str) -> None:
        """The story or the editor's own review as a readable page (236, item 5)."""

        version = self.current_version()
        if version is None:
            return
        reader = self.story_reader if which == "story" else self.review_reader
        empty = ("The AI editor has not written a story for this version." if which == "story"
                 else "The AI editor has not reviewed this version yet.")
        technical = _text(version.get("technical") or "") if which == "review" else ""
        reader.show_text(version["label"], _text(version["story" if which == "story" else "review"]), empty, technical)
        reader.show()
        reader.raise_()

    def show_files(self) -> None:
        """This version's files (236, item 6)."""

        project, version = self.current_project(), self.current_version()
        if not project or not version:
            return
        quality = QUALITIES[self._export_quality(project)]["label"]
        self.files_dialog.show_for(f"{project['name']} {version['label']}: its files", offer_words(version),
                                   version["files"], f"{render_words(version)} {export_words(version, quality)}")

    # New video -------------------------------------------------------------

    def browse_recording(self) -> None:
        """Choose a recording…: the Raw bin's recordings with what the app knows about each (236, item 1),
        or the Windows file picker when the Raw bin has none (or for another file)."""

        rows = [row for row in self._library_rows() if not row.get("missing") and row.get("path")
                and Path(str(row["path"])).suffix.lower() in (".mkv", ".mp4", ".mov", ".avi", ".m4v", ".webm")]
        path: Path | None = None
        if rows:
            # 242 (Wave C2): each recording's edits, joined by content, so several edits and a renamed or moved
            # recording's edits all show.
            dialog = ChooseRecordingDialog(rows, list(self.projects), self)
            self.choose_dialog = dialog
            if dialog.exec() != ChooseRecordingDialog.DialogCode.Accepted:
                return
            if dialog.chosen is not None:
                path = dialog.chosen
            elif not dialog.browse_asked:
                return
        if path is None:
            start = str(self.host.app_settings.get("default_input_folder") or "")
            chosen, _filter = QFileDialog.getOpenFileName(self, "Choose a race recording", start, VIDEO_FILTER)
            if not chosen:
                return
            path = Path(chosen)
        self.set_recording(path)

    def _editor_root(self) -> Path | None:
        """The folder whose race-videos folder holds the projects, None when no folder is set."""

        settings = self.host.app_settings
        chosen = (str(settings.get("race_video_output_folder") or "").strip()
                  or str(settings.get("output_folder") or "").strip())
        return Path(chosen).expanduser() if chosen else None

    def _read_earlier(self, path: Path, root: Path | None = None) -> dict[str, Any]:
        root = root if root is not None else self._editor_root()
        return earlier_prepare(root, path) if root is not None else {}

    def set_recording(self, path: Path, *, keep_project: bool = False) -> None:
        """Choose the recording; its audio tracks are read off the window's thread (226), and both
        boxes start on Auto, or on the tracks picked by hand at the recording's last Prepare. 236: the
        one-video view opens on its first step, for the video this recording already has or a new one;
        ``keep_project`` is for the video already open, whose own recording this is."""

        self.recording = path
        self.track_titles = None
        self.earlier = {}
        self.probing = True
        self._probe_number += 1
        number = self._probe_number
        self._fill_track_boxes([])
        # 236: Prepare's warnings are kept with their video and shown with it (``_show_prepare_notes``).
        self.recording_label.setText(f"{path.name}  (reading its audio tracks…)")
        self._say("Reading the recording's audio tracks…")
        # Looked up here, on the window's thread, so the function used is the one in place now.
        probe = audio_tracks
        ffprobe = str(getattr(self.host.resources, "ffprobe_exe", "") or "ffprobe")
        root = self._editor_root()
        if not keep_project:
            # The video this recording already has, if any; else a new one, on its first step.
            folder = ""
            try:
                folder = str(project_folder(root, path, read=False)) if root is not None else ""
            except (OSError, ValueError):
                folder = ""
            if (folder if self.project_by_folder(folder) else "") != self.project_folder:
                self.version_number = None
                self._close_video_dialogs()
            self.project_folder = folder if self.project_by_folder(folder) else ""
            self._undock_player()
            self.view = "video"
            self.steps_asked = True
            self._form_open = True
            self.views.setCurrentWidget(self.video_view)
            self._show_video()

        def read() -> None:
            try:
                titles = list(probe(ffprobe, path))
            except Exception:  # noqa: BLE001 - a recording that cannot be read has no tracks
                titles = []
            try:
                earlier = self._read_earlier(path, root)
            except Exception:  # noqa: BLE001 - a project that cannot be read is treated as none
                earlier = {}
            # 264: your answer for this recording, from any screen, wins over this page's older pick; an answer
            # you cleared means Auto, here too. With neither, the pick at the last Prepare stands.
            answer = speech_facts.answer_for(path)
            if answer.state != "none":
                picked = dict(earlier.get("picked") or {})
                picked.pop("voice", None)
                if answer.state == "confirmed" and answer.track:
                    picked["voice"] = int(answer.track) - 1
                earlier = {**earlier, "picked": picked}
            try:
                self.tracks_read.emit(number, (titles, earlier))
            except RuntimeError:
                pass  # the window closed while the tracks were read
        threading.Thread(target=read, name="ai-video-editor-tracks", daemon=True).start()
        self._show_knowledge()
        self._refresh_state()

    def _on_tracks_read(self, number: int, found: tuple[list[str], dict[str, Any]]) -> None:
        if number != self._probe_number or self.recording is None:
            return
        titles, earlier = found
        self.probing = False
        self.track_titles = list(titles)
        self.earlier = dict(earlier)
        if earlier.get("folder") and not self.project_folder and self.project_by_folder(str(earlier["folder"])):
            self.project_folder = str(earlier["folder"])
            self._show_video()
        name = self.recording.name
        count = len(titles)
        self.recording_label.setText(f"{name}  ({count} audio track{'s' if count != 1 else ''})" if count
                                     else f"{name}  (no audio tracks found)")
        self._fill_track_boxes(titles, picked=self.earlier.get("picked") or {})
        self._show_budget_choice()
        voice, game = self._effective_tracks()
        if not titles:
            self._say("No audio tracks were found in that recording, so it cannot be prepared.", "attention")
        elif count < 2:
            self._say("That recording has one audio track; the AI Video Editor needs your voice and the game sound "
                      "on separate tracks.", "attention")
        elif voice is not None and voice == game:
            self._say(self._same_track_text(), "attention")
        elif self._game_setting_refusal():
            self._say(self._game_setting_refusal(), "attention")
        else:
            self._say("Check the tracks, then press Prepare for the AI editor.")
        self._refresh_state()

    def _fill_track_boxes(self, titles: list[str], picked: dict[str, int] | None = None) -> None:
        """Offer Auto and each track. ``picked`` is the tracks picked by hand at the recording's last
        Prepare (0-based, 226): those boxes start on them, so they show Overridden again."""

        for name, combo in (("voice", self.voice_combo), ("game", self.game_combo)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(AUTO, None)
            for number, title in enumerate(titles, start=1):
                combo.addItem(f"Track {number}", number)
                combo.setItemData(number, f"Track {number}" + (f"  ({title})" if title else ""),
                                  Qt.ItemDataRole.ToolTipRole)
            ordinal = (picked or {}).get(name)
            combo.setCurrentIndex(ordinal + 1 if isinstance(ordinal, int) and 0 <= ordinal < len(titles) else 0)
            combo.blockSignals(False)
        self._show_track_states()

    @staticmethod
    def _picked(combo: WheelSafeComboBox) -> int | None:
        """The track picked in a box (0-based), or None on Auto."""

        number = combo.currentData()
        return int(number) - 1 if number is not None else None

    def _auto(self) -> dict[str, tuple[int | None, str]]:
        return auto_tracks(self.track_titles or [], self.host.app_settings.get(TRACK_ROLES_SETTING_KEY),
                           voice=self._picked(self.voice_combo))

    def _effective_tracks(self) -> tuple[int | None, int | None]:
        """The voice and game tracks the run will use, as far as the page can tell (0-based)."""

        auto = self._auto()
        voice, game = self._picked(self.voice_combo), self._picked(self.game_combo)
        return (voice if voice is not None else auto["voice"][0]), (game if game is not None else auto["game"][0])

    def _show_track_states(self) -> None:
        """Beside each box: what Auto picks, and Using main setting, or Overridden with a reset (226)."""

        known = self.track_titles is not None
        auto = self._auto() if known else {}
        for name, combo, reset, label in (("voice", self.voice_combo, self.voice_reset_button, self.voice_state),
                                          ("game", self.game_combo, self.game_reset_button, self.game_state)):
            picked = self._picked(combo)
            reset.setVisible(picked is not None)
            self._track_rows[name].setVisible(known)
            if not known:
                label.setText("")
                continue
            state = track_choice_state(AUTO, 0 if picked is None else picked + 1)
            text = auto_text(name, auto[name])
            label.setText(f"{text} · {state}" if state == USING_MAIN_SETTING else f"{state} · {text}")
        self._show_tracks_warning()

    def _show_budget_choice(self) -> None:
        """The AI budget box: the budget a prepared video was prepared with (236: its steps show what it
        has), else the main setting for a new video."""

        project = self.current_project()
        chosen = str((project or {}).get("budget") or "") if project and project.get("analysed") else ""
        value = chosen or str(self.host.app_settings.get("race_video_budget") or "standard")
        self.budget_combo.setCurrentIndex(max(0, self.budget_combo.findData(value)))

    def _show_budget_words(self, *_args: Any) -> None:
        value = str(self.budget_combo.currentData() or "standard")
        self.budget_words.setText(budget_words(value))

    def _tracks_change_text(self) -> str:
        if self.recording is None or not self.track_titles:
            return ""
        return tracks_change_text(self.earlier, *self._effective_tracks())

    def _show_tracks_warning(self, text: str | None = None) -> None:
        """226: before a Prepare would change the tracks of a video that has versions, say so beside the
        boxes, coloured as a warning; no pop-up."""

        if not hasattr(self, "tracks_warning"):
            return
        text = self._tracks_change_text() if text is None else text
        self.tracks_warning.setText(text)
        _show_kind(self.tracks_warning, run_status.COMPLETED_WITH_WARNINGS if text else "")
        self.tracks_warning.setVisible(bool(text))

    def _on_voice_choice_changed(self, _index: int) -> None:
        if self.recording is None:
            return
        track = self._picked(self.voice_combo)
        if track is None:
            speech_facts.clear_track(self.recording, by=speech_facts.ANSWERED_ON_EDITOR)
        else:
            speech_facts.confirm_track(self.recording, track + 1, by=speech_facts.ANSWERED_ON_EDITOR)
        self._show_knowledge()

    def _on_track_choice_changed(self, _index: int) -> None:
        self._show_track_states()
        if not self.track_titles or self.running:
            return
        voice, game = self._effective_tracks()
        refusal = self._game_setting_refusal()
        if voice is not None and voice == game:
            self._say(self._same_track_text(), "attention")
        elif refusal:
            self._say(refusal, "attention")
        elif self.status_sentence.text() == self._same_track_text() or self._is_game_setting_refusal(
                self.status_sentence.text()):
            self._say("Check the tracks, then press Prepare for the AI editor.")

    @staticmethod
    def _same_track_text() -> str:
        return "Your voice and the game sound are on the same track here; choose the right tracks before you prepare."

    def _game_setting_refusal(self) -> str:
        """226 (decision A): why the game track picked by hand cannot be the game sound by the Narration
        track setting, as Prepare would refuse it, or "" (``setting_game_refusal``)."""

        return setting_game_refusal(dict(enumerate(self.track_titles or [])),
                                    self.host.app_settings.get(TRACK_ROLES_SETTING_KEY), self._picked(self.game_combo))

    @staticmethod
    def _is_game_setting_refusal(text: str) -> bool:
        return " is set as Never narration in your Narration track setting " in text

    def _engine_settings(self) -> dict[str, Any]:
        """The settings Prepare uses, as the page shows them now, even before Settings are saved (226):
        the Track roles, the Whisper model, device, language and speech mode, the words to spell right,
        and the quick passes' model."""

        settings = self.host.app_settings
        return {key: settings.get(saved, "") for key, saved in ENGINE_SETTING_KEYS.items()}

    def start_prepare(self) -> Outcome:
        # 237: a refusal keeps its dialog, so the line beside the button stays quiet for it.
        if self.recording is None or self.probing:
            return Outcome.quiet()
        titles = self.track_titles or []
        if not titles:
            QMessageBox.information(self, "No audio tracks", "That recording has no audio tracks to work with.")
            return Outcome.quiet()
        if len(titles) < 2:
            QMessageBox.information(self, "One audio track",
                                    "The AI Video Editor needs your voice and the game sound on separate tracks.")
            return Outcome.quiet()
        voice, game = self._effective_tracks()
        if voice is not None and voice == game:
            QMessageBox.information(self, "Same track twice",
                                    "Your voice and the game sound must be different tracks.")
            return Outcome.quiet()
        refusal = self._game_setting_refusal()
        if refusal:
            QMessageBox.information(self, "Not the game sound", refusal)
            return Outcome.quiet()
        problem = temporary_folder_problem(self.output_root, "folder for edited videos")
        if problem:
            QMessageBox.information(self, "Choose a folder you keep",
                                    problem + " Change it in Settings > AI Video Editor.")
            return Outcome.quiet()
        # 226: a Prepare never changes the tracks of a video that has versions without the page saying
        # so first. Read again now: the AI editor may have added a version since the recording was chosen.
        self.earlier = self._read_earlier(self.recording)
        warning = self._tracks_change_text()
        if warning and not (self.tracks_warning.isVisible() and self.tracks_warning.text() == warning):
            self._show_tracks_warning(warning)
            self._say("Read the warning under the tracks; press Prepare again to prepare with these tracks.",
                      "attention")
            return Outcome.failed("Not started yet: this would change the tracks of a video that has versions.",
                                  "Read the warning above, then press Prepare again to go ahead.")
        settings = self.host.app_settings
        prepared = self.current_project()
        if not (prepared and prepared.get("analysed")):
            # The main setting is the budget for a new video; a video prepared again keeps its own choice.
            settings["race_video_budget"] = str(self.budget_combo.currentData())
        payload: dict[str, Any] = {
            "source": str(self.recording),
            "output_root": str(self.output_root),
            "budget": str(self.budget_combo.currentData()),
            "ffmpeg": str(getattr(self.host.resources, "ffmpeg_exe", "") or "ffmpeg"),
            "ffprobe": str(getattr(self.host.resources, "ffprobe_exe", "") or "ffprobe"),
            **self._engine_settings(),
        }
        # 226: only a box with a track picked by hand sends it (0-based); Auto is the run's to decide.
        picked = {name: track for name, track in (("voice", self._picked(self.voice_combo)),
                                                  ("game", self._picked(self.game_combo))) if track is not None}
        if picked:
            payload["tracks"] = picked
        try:
            target = str(project_folder(self.output_root, self.recording, read=False))
        except (OSError, ValueError):
            target = ""
        return self._run("prepare", "race-video-prepare", payload, self.recording.name, project=target)

    # Versions ---------------------------------------------------------------

    def start_preview(self) -> Outcome:
        project, version = self.current_project(), self.current_version()
        if not project or not version:
            return Outcome.quiet()
        self._let_go_of_video()
        return self._run("preview", "race-video-render", self._render_payload(project, version, profile="preview"),
                         f"{project['name']} {version['label']}", project=project["folder"])

    def _export_quality(self, project: dict[str, Any]) -> str:
        """The quality this video exports at: its own, else the main setting."""

        return project_export_quality(Path(project["folder"])) or main_export_quality(self.host.app_settings)

    def _show_export_quality(self) -> None:
        """The export-quality box and menu for the chosen video: its own quality (Overridden), else the main
        setting's (Using main setting)."""

        if not hasattr(self, "export_quality_combo"):
            return
        project = self.current_project()
        own = project_export_quality(Path(project["folder"])) if project else ""
        chosen = own or main_export_quality(self.host.app_settings)
        combo = self.export_quality_combo
        combo.blockSignals(True)
        combo.setCurrentIndex(max(0, combo.findData(chosen)))
        combo.blockSignals(False)
        state = project_choice_state(own) if project else ""
        self.export_quality_state.setText(state)
        if hasattr(self, "quality_buttons"):
            for value, button in self.quality_buttons.items():
                button.setChecked(value == chosen)
            self.quality_heading.setText(f"Export quality: {QUALITIES[chosen]['label']} · {state or USING_MAIN_SETTING}")

    def _on_export_quality_changed(self, _index: int) -> None:
        self._choose_export_quality(str(self.export_quality_combo.currentData() or DEFAULT_QUALITY))

    def _quality_chosen(self, chosen: str) -> None:
        """Files > Export quality: the panel stays open, so the tick is seen moving; said beside the toolbar too."""

        self._choose_export_quality(chosen)
        self.actions_feedback.done(f"This video exports at {QUALITIES[chosen]['label']}.")

    def _choose_export_quality(self, chosen: str) -> None:
        """226: a quality other than the main setting's becomes this video's own; the main setting's
        quality again removes it, so the video follows the main setting."""

        project = self.current_project()
        if not project:
            return
        own = "" if chosen == main_export_quality(self.host.app_settings) else chosen
        try:
            set_project_export_quality(Path(project["folder"]), own)
        except OSError as exc:
            self._say(f"The export quality could not be kept: {exc}", run_status.FAILED)
        self._show_export_quality()
        if self.export_dialog.isVisible():
            self._fill_export_dialog()

    def _fill_export_dialog(self) -> None:
        project, version = self.current_project(), self.current_version()
        if not project or not version:
            return
        quality = QUALITIES[self._export_quality(project)]["label"]
        self.export_dialog.show_for(project["name"], version["label"], self.export_quality_state.text(),
                                    export_words(version, quality))

    def start_export(self) -> Outcome:
        """Approve and export…: the dialog says what it does and with which quality (236, item 7)."""

        project, version = self.current_project(), self.current_version()
        if not project or not version:
            return Outcome.quiet()
        self._show_export_quality()
        self._fill_export_dialog()
        self.export_dialog.open()
        return Outcome.quiet()

    def _export_approved(self) -> None:
        project, version = self.current_project(), self.current_version()
        if not project or not version:
            return
        # The core reads this video's own export quality itself (editor-settings.json).
        self._let_go_of_video()
        outcome = self._run("export", "race-video-export", self._render_payload(project, version),
                            f"{project['name']} {version['label']}", project=project["folder"])
        if outcome.kind == "done":
            self.actions_feedback.done("Started")

    def _render_payload(self, project: dict[str, Any], version: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "project": project["folder"],
            "version": int(version["version"]),
            "ffmpeg": str(getattr(self.host.resources, "ffmpeg_exe", "") or "ffmpeg"),
            "ffprobe": str(getattr(self.host.resources, "ffprobe_exe", "") or "ffprobe"),
            **extra,
        }

    def play_choice(self, which: str) -> Outcome:
        """A play choice on the picture (236 fix round): "main" (the final, else the preview, else the AI
        agent's own video) or "beside" (the preview beside the final). It plays at once, on the page, in the
        app's one player."""

        main, beside = play_choices(self.current_version())
        row = main if which == "main" else beside
        if row is None:
            return Outcome.quiet()
        return self.play_path(Path(row["path"]))

    def play_path(self, path: Path, *, at: float | None = None) -> Outcome:
        opener = getattr(self.host, "video_opener", None)
        project, version = self.current_project(), self.current_version()
        if opener is None or not project or not version:
            return Outcome.quiet()
        window = opener.dock(self.player_page)
        self._playing_key = (self.project_folder, self.version_number)
        self._playing_path = Path(path)
        self._show_stage(self.player_page)
        self.player_page.fit()
        self._show_playing_line()
        target = PlayTarget(path=path, label=f"{project['name']} {version['label']}",
                            start_seconds=float(at or 0.0))
        if window.open_path() == path:
            if at is not None:
                window.seek_seconds(at, play=True)
            else:
                window.open_target(target, autoplay=True)
        else:
            window.open_target(target, autoplay=True)
            if at is not None and at <= 0:
                window.seek_seconds(0, play=True)
        return Outcome.done("Playing")

    def jump_to_scene(self, block: dict[str, Any]) -> None:
        """A scene of the story strip: the player goes there (and plays), in the render playing (the edit's
        times are the same in its preview and its final), else in the picture's main choice."""

        version = self.current_version()
        if version is None:
            return
        renders = {Path(item["path"]) for item in version["files"]
                   if item["role"] in (ROLE_PREVIEW, ROLE_FINAL, ROLE_EXPORT, ROLE_READABLE)}
        path = self._playing_path if self._player_here() and self._playing_path in renders else None
        if path is None:
            main, _beside = play_choices(version)
            if main is None:
                return
            path = Path(main["path"])
        self.play_path(path, at=float(block["start"]))

    # Prompts and notes ------------------------------------------------------

    def _prompt(self, tool: str, feedback_version: int | None = None, scenes: list[str] | None = None,
                folder: str = "") -> str:
        project = self.project_by_folder(folder) if folder else self.current_project()
        if project is None:
            raise ValueError("the video is no longer there")
        resources = self.host.resources
        model = str(self.host.app_settings.get(f"race_video_{tool}_model") or "")
        return build_prompt(Path(project["folder"]), tool=tool, python=str(resources.python_exe or "python"), model=model,
                            src_root=Path(str(resources.backend_source_root or "")), feedback_version=feedback_version,
                            scenes=scenes)

    def copy_prompt(self, tool: str) -> Outcome:
        if not self.current_project():
            return Outcome.quiet()
        try:
            text = self._prompt(tool)
        except (OSError, ValueError, KeyError) as exc:
            self._say(f"The prompt could not be made: {exc}", run_status.FAILED)
            return Outcome.failed(f"The prompt could not be made: {exc}",
                                  f"Press {APP_LABELS['files_tool']}, then {APP_LABELS['refresh']}, and try again.")
        QApplication.clipboard().setText(text)
        name = "Claude Code" if tool == "claude" else "Codex"
        self._say(f"Prompt for {name} copied. Paste it into {name}; it makes the first version and reviews it itself.",
                  run_status.COMPLETED)
        return Outcome.done(f"Copied. Paste it into {name}.")

    def see_prompt(self, tool: str) -> None:
        """See the prompt first (236, item 3)."""

        if not self.current_project():
            return
        version = self.current_version()
        self._prompt_for = (self.project_folder, version)
        self.prompt_dialog.open_for(tool, notes_label=version["label"] if version and version["feedback"] else "")

    def _prompt_for_dialog(self, tool: str, answer_notes: bool) -> str:
        folder, version = getattr(self, "_prompt_for", (self.project_folder, self.current_version()))
        if answer_notes and version and version["feedback"]:
            _words, scenes = split_scene_notes(_text(version["feedback"]))
            return self._prompt(tool, feedback_version=int(version["version"]), scenes=scenes, folder=folder)
        return self._prompt(tool, folder=folder)

    def _prompt_copied(self, tool: str, _text_copied: str) -> None:
        name = "Claude Code" if tool == "claude" else "Codex"
        self._say(f"Prompt for {name} copied. Paste it into {name}.", run_status.COMPLETED)

    def add_scene_note(self, block: dict[str, Any]) -> None:
        """Put a scene of the strip in the notes: a chip "Note on: <scene>", and the scene's name at the
        start of a new line, ready for the words (236)."""

        if any(chosen["name"] == block["name"] and chosen["start"] == block["start"] for chosen in self.scene_notes):
            # Already in the notes: the words go on at the end of its line (the 150% walk saw them go in front).
            text = self.feedback_edit.toPlainText()
            start = text.find(f"{block['name']}: ")
            end = text.find("\n", start) if start >= 0 else -1
            cursor = self.feedback_edit.textCursor()
            cursor.setPosition(len(text) if start < 0 or end < 0 else end)
            self.feedback_edit.setTextCursor(cursor)
            self.feedback_edit.setFocus()
            return
        self._add_chip(block)
        text = self.feedback_edit.toPlainText().rstrip()
        self.feedback_edit.setPlainText((text + "\n" if text else "") + f"{block['name']}: ")
        cursor = self.feedback_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.feedback_edit.setTextCursor(cursor)
        self.feedback_edit.setFocus()

    def _add_chip(self, block: dict[str, Any]) -> None:
        self.scene_notes.append(dict(block))
        chip = QPushButton(f"Note on: {block['name']}  ✕")
        chip.setObjectName("sceneChip")
        chip.setToolTip("Takes this scene off your notes. The words you wrote stay.")
        chip.setAccessibleName(f"Note on: {block['name']}")
        chip.clicked.connect(lambda _checked=False, b=dict(block), c=chip: self._remove_scene_note(b, c))
        self.chips_row.addWidget(chip)
        self.chips.append(chip)

    def _remove_scene_note(self, block: dict[str, Any], chip: QPushButton) -> None:
        self.scene_notes = [chosen for chosen in self.scene_notes
                            if not (chosen["name"] == block["name"] and chosen["start"] == block["start"])]
        if chip in self.chips:
            self.chips.remove(chip)
        self.chips_row.removeWidget(chip)
        chip.deleteLater()

    def _clear_scene_notes(self) -> None:
        for chip in list(self.chips):
            self._remove_scene_note({"name": "", "start": None}, chip)
        self.scene_notes = []

    def save_notes(self, tool: str) -> Outcome:
        project, version = self.current_project(), self.current_version()
        text = self.feedback_edit.toPlainText().strip()
        if not project or not version:
            return Outcome.quiet()
        if not text:
            # 237: said beside the button, not in a pop-up.
            return Outcome.failed("No notes yet.", "Write what should change in the box first.")
        scenes = [scene_note_line(block) for block in self.scene_notes]
        save_feedback(Path(project["folder"]), int(version["version"]), notes_with_scenes(text, scenes))
        self._drafts.pop((project["folder"], int(version["version"])), None)
        QApplication.clipboard().setText(self._prompt(tool, feedback_version=int(version["version"]), scenes=scenes))
        name = "Claude Code" if tool == "claude" else "Codex"
        self._say(f"Notes saved for {version['label']} and the revision prompt for {name} is copied. "
                  f"Paste it into {name}; it makes a new version that answers your notes.", run_status.COMPLETED)
        self.refresh()
        return Outcome.done(f"Notes saved, prompt copied. Paste it into {name}.")

    def start_fresh_edit(self) -> Outcome:
        """171: a second, independent edit of this recording, for another AI editor or a new attempt."""

        project = self.current_project()
        if not project:
            return Outcome.quiet()
        answer = QMessageBox.question(
            self, "Start a fresh edit",
            f"Start a separate edit of {Path(project['source']).name}?\n\nIt reuses this video's analysis, starts "
            "with no versions and a fresh AI budget, and gets its own prompt. This edit and its versions stay as "
            "they are.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return Outcome.quiet()
        try:
            fresh = start_fresh_edit(Path(project["folder"]))
        except (OSError, ValueError) as exc:
            self._say(f"The fresh edit could not be made: {exc}", run_status.FAILED)
            return Outcome.failed(f"The fresh edit could not be made: {exc}", "Check the folder for edited videos.")
        self.refresh()
        self.open_video(str(fresh))
        self._say(f"Fresh edit ready: {fresh.name}. Copy its prompt for Claude Code or Codex.", run_status.COMPLETED)
        return Outcome.done("Fresh edit ready")

    # Folders ----------------------------------------------------------------

    def _refresh_action(self) -> Outcome:
        self.refresh()
        count = len(self.projects)
        return Outcome.done(f"Up to date: {count} video{'s' if count != 1 else ''}")

    @staticmethod
    def _open_folder(folder: Path, what: str) -> Outcome:
        if not folder.is_dir():
            return Outcome.failed(f"The {what} is not there.", "It may have been moved or deleted; press "
                                  f"{APP_LABELS['files_tool']}, then {APP_LABELS['refresh']}.")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            return Outcome.failed(f"Windows did not open the {what}.", f"Open it yourself: {folder}")
        return Outcome.done("Opened")

    def open_project_folder(self) -> Outcome:
        project = self.current_project()
        if not project:
            return Outcome.quiet()
        return self._open_folder(Path(project["folder"]), "project folder")

    def open_export_folder(self) -> Outcome:
        project = self.current_project()
        if not project:
            return Outcome.quiet()
        return self._open_folder(Path(project["folder"]) / "export", "export folder")

    def open_mask_editor(self) -> None:
        from .privacy_mask_editor import PrivacyMaskDialog  # noqa: PLC0415

        project = self.current_project()
        source = Path(project["source"]) if project else self.recording
        if source is None:
            return
        dialog = PrivacyMaskDialog(source, ffmpeg=str(getattr(self.host.resources, "ffmpeg_exe", "") or "ffmpeg"),
                                   parent=self)
        dialog.exec()

    # Runs -------------------------------------------------------------------

    def _run(self, kind: str, command: str, payload: dict[str, Any], label: str, *, project: str) -> Outcome:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder = self.output_root / "race-videos" / ".runs" / f"{stamp}-{kind}"
        folder.mkdir(parents=True, exist_ok=True)
        request, result = folder / "request.json", folder / "result.json"
        request.write_text(json.dumps({"payload": {**payload, "progress_label": label}}, indent=2), encoding="utf-8")
        settings = dict(self.host.app_settings)
        settings["output_folder"] = str(Path(project) if project and kind != "prepare" else self.output_root / "race-videos")
        spec = cli_command(self.host.resources, command, request, result)
        banner = {"origin": PAGE_NAME, "banner_title": BANNER_TITLES[kind].format(label=label)} if hasattr(
            self.host, "make_job_banner") else {}
        # 243: the run's recording, as the library keeps it: the one chosen for Prepare, else the project's own.
        recording = self._run_recording_path(kind, project)
        run_kinds = {"kind": f"editor_{kind}", "record_items": [recording] if recording else []} if isinstance(
            getattr(self.host, "records", None), Records) else {}
        if not self.host.start_external_run(spec, title=RUN_TITLES[kind], settings=settings, queue_items=[label],
                                            listener=self, evidence_package=False, **banner, **run_kinds):
            return Outcome.quiet()
        self.run_recording_path = recording
        version = self.current_version()
        # 236 (item 6): what was there before, so the page can say afterwards what the run changed.
        self.run_before = {"label": version["label"] if version else "", "preview": bool(version and version["preview"]),
                           "exported": bool(version and version.get("exported")),
                           "export": str(version.get("export") or "") if version else ""}
        self.running, self.run_kind, self.run_folder, self.run_project = True, kind, folder, project
        self.run_recording = self.recording if kind == "prepare" else None
        self.last_message = ""
        if kind == "prepare":
            self.prepare_notes.pop(project, None)
            self._show_prepare_notes()
        # 237: the job banner on this page shows how far it has got; the sentence only says what it is doing.
        self._say({"prepare": "Preparing the recording for the AI editor. Long races take a while.",
                   "preview": "Rendering the preview.",
                   "export": "Exporting and checking it."}[kind], "active")
        self._refresh_state()
        self._show_cards()
        return Outcome.done("Started")

    def _run_recording_path(self, kind: str, project: str) -> str:
        if kind == "prepare" and self.recording is not None:
            return str(self.recording)
        try:
            return str(project_recording(Path(project))) if project else ""
        except (OSError, ValueError):
            return ""

    def _record_outcome(self, result: RunnerResult, outcome: str, reason: str) -> None:
        """243: the run's one recording, with its outcome, in the library."""

        records = getattr(self.host, "records", None)
        run_id = str(getattr(result, "run_id", "") or "")
        recording = str(getattr(self, "run_recording_path", "") or "")
        if not isinstance(records, Records) or not run_id or not recording:
            return
        try:
            records.record_outcomes(run_id, [{"item": recording, "outcome": outcome, "reason": reason[:300]}],
                                    reported_by=PAGE_NAME)
        except (OSError, sqlite3.Error, ValueError):
            pass

    def _show_prepare_notes(self) -> None:
        """226, 236: what the last Prepare of the video shown found to warn about."""

        notes = self.prepare_notes.get(self.project_folder) if self.project_folder else None
        self._show_mask_warning(bool(notes and notes.get("no_masks")))
        self._show_sound_warnings(list((notes or {}).get("warnings") or []))

    def _show_mask_warning(self, show: bool) -> None:
        self.mask_warning.setText(NO_MASKS_WARNING if show else "")
        # A warning's colour by the one status rule ("attention" alone is not one of its words).
        _show_kind(self.mask_warning, run_status.COMPLETED_WITH_WARNINGS if show else "")
        self.mask_warning.setVisible(show)

    def _show_sound_warnings(self, warnings: list[str]) -> None:
        """226: Prepare's warnings that the voice or game track it used is silent, as the no-masks one is shown."""

        text = "\n".join(str(item) for item in warnings if str(item).strip())
        self.sound_warning.setText(text)
        _show_kind(self.sound_warning, run_status.COMPLETED_WITH_WARNINGS if text else "")
        self.sound_warning.setVisible(bool(text))

    def on_log_line(self, _stream: str, line: str) -> None:
        text = str(line).strip()
        if text and not text.startswith("MM_PROGRESS_V1"):
            self.last_message = text

    def on_finished(self, result: RunnerResult) -> None:
        kind, folder, target = self.run_kind, self.run_folder, self.run_project
        self.running, self.run_kind = False, ""
        # 236: the page goes on showing the video it shows; only when that is the one the run was for
        # (a new recording's first step included) does it take the run's result in.
        here = self.view == "video" and (self.project_folder == target or (
            kind == "prepare" and not self.project_folder and self.recording == self.run_recording))
        named = "" if here else f"{Path(target).name}: " if target else ""
        data: dict[str, Any] = {}
        error = ""
        if folder is not None and (folder / "result.json").exists():
            try:
                outcome = json.loads((folder / "result.json").read_text(encoding="utf-8"))
                data, error = dict(outcome.get("data") or {}), str(outcome.get("error") or "")
            except (OSError, ValueError):
                error = "the result could not be read"
        if result.status == "cancelled":
            self._say(f"{named}Stopped. Nothing was changed in your earlier versions.", "cancelled")
            self._record_outcome(result, "cancelled", "Stopped.")
        elif result.status != "succeeded" or error:
            reason = error or result.error or self.last_message or "see the run log"
            self._say(f"{named}That did not finish: {reason}", run_status.FAILED)
            self._record_outcome(result, "failed", reason)
            self.host.show_external_run_outcome(f"{RUN_TITLES.get(kind, 'AI Video Editor')} did not finish",
                                                state=run_status.FAILED)
        else:
            if kind == "prepare" and data.get("project"):
                self.run_project = target = str(data["project"])
                named = "" if here else f"{Path(target).name}: "
                if here:
                    # 226: the video just prepared is the one shown, so its details and Copy prompt are its
                    # own; its steps show what Prepare used.
                    self.project_folder = target
                    self.version_number = None
                    self.steps_asked = False
                    self._form_open = False
            if kind == "prepare" and target:
                # 226 (decision F): the pictures the AI editor sees have no blurred cameras; a voice or game
                # track with no sound, used as chosen. Kept with the video, said whenever it is shown.
                self.prepare_notes[target] = {"no_masks": data.get("privacy_masked") is False,
                                              "warnings": list(data.get("warnings") or [])}
            message = self._success_text(kind, data, self.run_before)
            # One state for the page's sentence and for Queue / Progress, so they always agree.
            state = run_status.COMPLETED if "failed" not in message else run_status.COMPLETED_WITH_PROBLEMS
            self._say(f"{named}{message}", state)
            self._record_outcome(result, state, message)
            self.host.show_external_run_outcome(message, state=state)
        self.refresh()

    @staticmethod
    def _success_text(kind: str, data: dict[str, Any], before: dict[str, Any] | None = None) -> str:
        """What a finished run did, and for a render or an export what it changed (236, item 6)."""

        before = before or {}
        if kind == "prepare":
            return "Ready for the AI editor. Copy the prompt for Claude Code or Codex and paste it in."
        check = data.get("technical_check") or {}
        report = data.get("render") or {}
        reused = report.get("scenes_reused")
        rendered = report.get("scenes_rendered")
        scenes = (f" ({rendered} scene{'s' if rendered != 1 else ''} rendered, {reused} reused)"
                  if isinstance(reused, int) and isinstance(rendered, int) else "")
        label = before.get("label") or "this version"
        if kind == "preview":
            changed = f"It replaced the earlier preview of {label}" if before.get("preview") else f"It is the first preview of {label}"
            if check.get("passed"):
                return f"Preview ready: press {APP_LABELS['play']}. {changed}{scenes}."
            return ("The preview was made but failed the technical check; the AI editor's review should explain it. "
                    f"{changed}.")
        if data.get("export"):
            name = Path(str(data["export"])).name
            changed = "replaced the earlier export" if before.get("exported") else "a new file in the export folder"
            return f"Exported and checked: {name} ({changed}). Nothing was uploaded."
        return "The full-quality render failed the technical check, so it was not exported."


class AiVideoEditorSettingsPanel(QWidget):
    """The "AI Video Editor" tab of Settings. Like the video-player tab, it owns no settings itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings: dict[str, Any] = {}
        form = QFormLayout(self)
        folder_meta = METADATA_BY_KEY["race_video_output_folder"]
        row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Your output folder")
        self.folder_edit.setToolTip(folder_meta.tooltip)
        self.folder_edit.setAccessibleName(folder_meta.display_label)
        self.browse_button = browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        form.addRow(folder_meta.display_label, row)
        self.budget_combo = WheelSafeComboBox()
        for value, text in BUDGETS:
            self.budget_combo.addItem(text, value)
        self.budget_combo.setToolTip(METADATA_BY_KEY["race_video_budget"].tooltip)
        form.addRow(METADATA_BY_KEY["race_video_budget"].display_label, self.budget_combo)
        # 174: the tools rename their models, so the names the prompt uses are kept here.
        self.model_edits: dict[str, QLineEdit] = {}
        for tool in ("claude", "codex"):
            meta = METADATA_BY_KEY[f"race_video_{tool}_model"]
            edit = QLineEdit()
            edit.setPlaceholderText(str(meta.default))
            edit.setToolTip(meta.tooltip)
            self.model_edits[tool] = edit
            form.addRow(meta.display_label, edit)
        # 226 (161.5): the export quality every video uses unless it chooses its own on the page.
        quality_meta = METADATA_BY_KEY[EXPORT_QUALITY_KEY]
        self.quality_combo = WheelSafeComboBox()
        self.quality_combo.setObjectName("aiVideoEditorSettingsExportQuality")
        for value, spec in QUALITIES.items():
            self.quality_combo.addItem(str(spec["label"]), value)
        self.quality_combo.setToolTip(quality_meta.tooltip)
        form.addRow(quality_meta.display_label, self.quality_combo)
        # 226 (decision C): the quick passes stay on Whisper small unless set to the main model.
        quick_meta = METADATA_BY_KEY[QUICK_MODEL_KEY]
        self.quick_combo = WheelSafeComboBox()
        self.quick_combo.setObjectName("aiVideoEditorSettingsQuickPasses")
        for value, text in QUICK_PASS_CHOICES:
            self.quick_combo.addItem(text, value)
        self.quick_combo.setToolTip(quick_meta.tooltip)
        self.quick_combo.currentIndexChanged.connect(self._show_quick_state)
        self.quick_state = _muted("")
        self.quick_state.setObjectName("aiVideoEditorSettingsQuickPassesState")
        quick_row = QHBoxLayout()
        quick_row.addWidget(self.quick_combo, 1)
        quick_row.addWidget(self.quick_state)
        form.addRow(quick_meta.display_label, quick_row)
        self.note = _muted(f"Your voice and game-sound tracks follow the track names and your {TRACK_ROLES_FIELD} "
                           "(Settings > General / Startup): on the AI Video Editor page both boxes start on Auto, and "
                           "picking a track there overrides it for that recording only. Privacy masks are drawn from "
                           "the AI Video Editor page.")
        form.addRow(self.note)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder for edited videos", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        # The main Whisper model can change on a workflow's settings while this tab is hidden.
        self._show_quick_state()

    def _show_quick_state(self, *_args: Any) -> None:
        self.quick_state.setText(quick_passes_state(self.quick_combo.currentData(), self._settings.get("whisper_model")))

    def load(self, settings: dict[str, Any]) -> None:
        # Kept to show the quick passes against the main Whisper model as it is now.
        self._settings = settings
        self.folder_edit.setText(str(settings.get("race_video_output_folder") or ""))
        self.budget_combo.setCurrentIndex(max(0, self.budget_combo.findData(str(settings.get("race_video_budget") or "standard"))))
        for tool, edit in self.model_edits.items():
            key = f"race_video_{tool}_model"
            edit.setText(str(settings.get(key) or METADATA_BY_KEY[key].default))
        self.quality_combo.setCurrentIndex(max(0, self.quality_combo.findData(main_export_quality(settings))))
        quick = str(settings.get(QUICK_MODEL_KEY) or "").strip() or QUICK_MODEL_DEFAULT
        if self.quick_combo.findData(quick) < 0:
            # A model typed into the settings file by hand is kept, never replaced on the next save.
            self.quick_combo.addItem(f"Whisper {quick}", quick)
        self.quick_combo.setCurrentIndex(self.quick_combo.findData(quick))
        self._show_quick_state()

    def values(self) -> dict[str, Any]:
        return {
            "race_video_output_folder": self.folder_edit.text().strip(),
            "race_video_budget": str(self.budget_combo.currentData() or "standard"),
            **{f"race_video_{tool}_model": edit.text().strip() or str(METADATA_BY_KEY[f"race_video_{tool}_model"].default)
               for tool, edit in self.model_edits.items()},
            EXPORT_QUALITY_KEY: str(self.quality_combo.currentData() or DEFAULT_QUALITY),
            QUICK_MODEL_KEY: str(self.quick_combo.currentData() or QUICK_MODEL_DEFAULT),
        }


def home_card_frame(on_start: Any) -> tuple[QFrame, QPushButton]:
    """The Home card under "Other tasks". Start opens the page; it is not a workflow."""

    frame = QFrame()
    frame.setProperty("card", True)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    heading = QLabel("AI Video Editor")
    heading.setProperty("sectionTitle", True)
    layout.addWidget(heading)
    layout.addWidget(_muted(HOME_CARD_PURPOSE))
    layout.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    start = QPushButton("Start")
    start.clicked.connect(on_start)
    row.addWidget(start)
    layout.addLayout(row)
    return frame, start
