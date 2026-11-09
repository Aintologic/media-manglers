"""The AI Video Editor's own parts (236, the approved "player first" layout).

The page itself is ``ai_video_editor.AiVideoEditorPage``. What it shows is built here:

- the start view's cards: "Make a video from a recording", "Continue: <last video>" and one picture
  card per video under "Your videos", with a plain status pill (``ui_parts.StatusPill``) and a
  thumbnail made by the shared frame renderer and kept in the app's cache folder (``ThumbnailMaker``);
- the story strip under the player: one block per beat of the version's timeline, each as wide as its
  name and with a pen for a note, scrolling sideways when they do not fit (``SceneStrip``);
- the video's toolbar: a labelled button per group and the small panel each opens (``ToolbarButton``,
  ``ToolPanel``), and the version's picture with its play choices on it (``PictureBox``);
- the dialogs the page opens: Choose a recording (with what the Raw bin and the Inbox already know about
  each one), See the prompt first, the story and the editor's own review as a readable page, this
  version's files, and Approve and export….

Thumbnails only ever come from what the app rendered with the privacy masks applied (a version's
preview or final) or from Prepare's own masked stills; never from the recording itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core import app_cache, frame_render, raw_bin_library, recording_records
from media_manglers.core.race_video import link
from media_manglers.core.race_video.analysis import BUDGETS, SHEET_COLUMNS, SHEET_ROWS
from media_manglers.core.race_video.library import (
    ROLE_AGENT,
    ROLE_EXPORT,
    ROLE_FINAL,
    ROLE_PREVIEW,
    ROLE_READABLE,
    ROLE_VALIDATION,
)
from media_manglers.core.race_video.project import clock_text
from media_manglers.core.race_video.prompt import APP_LABELS, STAMPS
from media_manglers.core.race_video.readable import readable
from media_manglers.core.race_video.render import PROFILES
from media_manglers.core.race_video.review import REVIEW_STILL_INTERVAL

from . import theme
from .tables import make_columns_resizable
from .ui_parts import (
    TOOL_ICON_FOLDER,
    FlowLayout,
    InlineFeedback,
    SegmentedControl,
    StatusPill,
    bind_action,
    line_icon,
    polish_views,
    set_button_kind,
)

BUDGET_LABELS = {"light": "Light", "standard": "Standard", "thorough": "Thorough"}

# Status pills of the start view (236). Their colours follow the one status rule (theme.status_kind).
STATUS_GETTING_READY = "Getting ready…"
STATUS_NOT_PREPARED = "Not prepared yet"
STATUS_WAITING = "Waiting for your AI agent"
STATUS_NEEDS_PREVIEW = "Needs a preview"
STATUS_READY = "Ready to watch"
STATUS_EXPORTED = "Exported"
STATUS_RENDERING = "Rendering a preview…"
STATUS_EXPORTING = "Exporting…"
# A pill shows "needs a look" (amber) for this status word of the one status rule (theme.status_kind).
ATTENTION = "complete_with_warnings"
_STATUS_KIND = {STATUS_GETTING_READY: "active", STATUS_RENDERING: "active", STATUS_EXPORTING: "active",
                STATUS_NOT_PREPARED: "waiting", STATUS_WAITING: ATTENTION, STATUS_NEEDS_PREVIEW: ATTENTION,
                STATUS_READY: "completed", STATUS_EXPORTED: "completed"}

FILE_WORDS = {
    ROLE_PREVIEW: "Preview: a quick, smaller render to watch",
    ROLE_FINAL: "Final: the full-quality render",
    ROLE_EXPORT: "Export: the final, in the export folder",
    ROLE_READABLE: "A readable name for the same render",
    ROLE_VALIDATION: "A test render at another size",
    ROLE_AGENT: "Made by your AI agent itself",
}
THUMB_WIDTH, THUMB_HEIGHT = 480, 270


# Words -------------------------------------------------------------------------------------------


def budget_words(budget: str) -> str:
    """What the AI budget changes (236, item 2), in plain words and only what the code does: the pictures
    Prepare takes for the AI editor, the closer looks and the review rounds it may use, and the effort the
    prompt asks for (``analysis.BUDGETS``, ``review.REVIEW_STILL_INTERVAL``, ``prompt.STAMPS``)."""

    spec = BUDGETS[budget]
    claude, codex = STAMPS[budget]
    most = int(spec["max_sheets"]) * SHEET_COLUMNS * SHEET_ROWS
    rounds = int(spec["review_rounds"])
    times = {1: "once", 2: "twice"}.get(rounds, f"{rounds} times")
    return (f"{BUDGET_LABELS[budget]}: Prepare takes a picture of the race every {spec['still_interval']} seconds for "
            f"your AI agent (further apart on a long race, so there are never more than {most}). For this video, all "
            f"its versions together, the agent may take {spec['close_look_images']} closer looks at moments the "
            f"pictures cannot settle and watch its versions {times} (a picture every {REVIEW_STILL_INTERVAL[budget]} "
            "seconds of the cut) to find what to fix; after that the app refuses more unless the agent asks you first. "
            f"The prompt asks Claude Code for its \"{claude}\" effort (Codex: \"{codex}\").")


BUDGET_INTRO = ("More pictures and more rounds let your AI agent see more of the race and fix more of its own "
                "version, but they take longer and use more of your AI plan. Prepare itself takes a little longer "
                "for more pictures; writing down what you said takes the same time on all three.")


def status_of(project: dict[str, Any], running: str = "") -> tuple[str, str]:
    """The video's plain status for its card (236): (pill words, its status word for the one status rule). ``running`` is the page's
    job for this video ("prepare", "preview", "export") or ""."""

    if running == "prepare":
        text = STATUS_GETTING_READY
    elif running == "preview":
        text = STATUS_RENDERING
    elif running == "export":
        text = STATUS_EXPORTING
    elif not project.get("analysed"):
        text = STATUS_NOT_PREPARED
    elif not project.get("versions"):
        text = STATUS_WAITING
    else:
        newest = project["versions"][0]
        if newest.get("exported"):
            text = STATUS_EXPORTED
        elif play_file(newest) is not None:
            text = STATUS_READY
        else:
            text = STATUS_NEEDS_PREVIEW
    return text, _STATUS_KIND[text]


def versions_text(project: dict[str, Any]) -> str:
    count = len(project.get("versions") or [])
    return f"{count} version{'s' if count != 1 else ''}" if count else "No versions yet"


def continue_text(project: dict[str, Any], running: str = "", percent: int | None = None) -> str:
    """The line under "Continue: <name>": where that video is, in a sentence."""

    status, _kind = status_of(project, running)
    newest = (project.get("versions") or [None])[0]
    label = f"Version {int(newest['version'])}" if newest else ""
    if status == STATUS_GETTING_READY:
        return "Getting it ready for your AI agent" + (f": {percent}%." if percent is not None else ".")
    return {
        STATUS_RENDERING: f"Rendering a preview of {label.lower()}.",
        STATUS_EXPORTING: f"Exporting {label.lower()}.",
        STATUS_NOT_PREPARED: "Not prepared yet: press Prepare for the AI editor.",
        STATUS_WAITING: "Waiting for your AI agent: copy the prompt and paste it in.",
        STATUS_NEEDS_PREVIEW: f"{label} has no preview yet.",
        STATUS_READY: f"{label} is ready to watch.",
        STATUS_EXPORTED: f"{label} is exported.",
    }[status]


def video_length(version: dict[str, Any]) -> float | None:
    """How long the version's video is, from its technical check (seconds), None when not known."""

    renders = Path(version["folder"]) / "renders"
    for name, key in (("qc-preview.json", "duration"), ("qc-final.json", "duration"),
                      ("render-preview.json", "expected_duration"), ("render-final.json", "expected_duration")):
        try:
            return float(json.loads((renders / name).read_text(encoding="utf-8"))[key])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def format_words(found: dict[str, Any]) -> str:
    """A render's picture in words: "1280×720, 30 fps"; "" when its report does not say."""

    if not found.get("width") or not found.get("height"):
        return ""
    fps = str(found.get("fps") or "").split("/")
    rate = ""
    try:
        value = float(fps[0]) / (float(fps[1]) if len(fps) > 1 else 1.0)
        rate = f", {value:.3g} fps"
    except (ValueError, ZeroDivisionError):
        rate = ""
    return f"{found['width']}×{found['height']}{rate}"


def play_file(version: dict[str, Any], prefer: str = ROLE_PREVIEW) -> dict[str, Any] | None:
    """The file the page plays for a version (236, item 6): ``prefer`` when the version has it, else its
    preview, its final, its export, then the first video the AI agent made itself; None when it has none."""

    files = list(version.get("files") or [])
    order = ((ROLE_FINAL, ROLE_EXPORT, ROLE_PREVIEW, ROLE_AGENT) if prefer in (ROLE_FINAL, ROLE_EXPORT)
             else (ROLE_PREVIEW, ROLE_FINAL, ROLE_EXPORT, ROLE_AGENT))
    for role in order:
        for row in files:
            if row.get("role") == role:
                return row
    return None


# 236 fix round: the play choices live on the picture, and pressing one plays at once.
PLAY_FINAL = APP_LABELS["play_final"]
PLAY_PREVIEW = APP_LABELS["play"]
PLAY_PREVIEW_BESIDE = f"{PLAY_PREVIEW} (quick, smaller)"
PLAY_AGENT = "Play your AI agent's video"


def play_choices(version: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """What the picture offers for a version: (the main choice, the one beside it).

    With a final or an export, the main choice is the final (full quality) and the preview, when there is
    one, goes beside it; with only a preview, the preview alone; with neither, the first video the AI agent
    made itself. (None, None) when the version has no video at all."""

    if not version:
        return None, None
    main = play_file(version, ROLE_FINAL)
    if main is None or main["role"] not in (ROLE_FINAL, ROLE_EXPORT):
        return main, None
    beside = next((row for row in version.get("files") or [] if row.get("role") == ROLE_PREVIEW), None)
    return main, beside


def play_label(row: dict[str, Any], *, beside: bool = False) -> str:
    """The words of the play button for ``row``: the final, the preview (with what it is when it sits
    beside the final), or the AI agent's own video."""

    if row["role"] in (ROLE_FINAL, ROLE_EXPORT):
        return PLAY_FINAL
    if row["role"] == ROLE_PREVIEW:
        return PLAY_PREVIEW_BESIDE if beside else PLAY_PREVIEW
    return PLAY_AGENT


def _size_words(found: dict[str, Any], profile: str) -> str:
    if found.get("width") and found.get("height"):
        return f"{found['width']}×{found['height']}"
    return f"{PROFILES[profile]['width']}×{PROFILES[profile]['height']}"


def chip_words(version: dict[str, Any]) -> str:
    """The line on the picture under its play buttons: "v002 · 4:12 · final 1920×1080 · preview 1280×720"."""

    roles = {row["role"] for row in version.get("files") or []}
    parts = [str(version["label"])]
    length = video_length(version)
    if length:
        parts.append(clock_text(length))
    if roles & {ROLE_FINAL, ROLE_EXPORT}:
        parts.append(f"final {_size_words(version.get('final_format') or {}, 'final')}")
    if ROLE_PREVIEW in roles:
        parts.append(f"preview {_size_words(version.get('preview_format') or {}, 'preview')}")
    return " · ".join(parts)


def offer_words(version: dict[str, Any]) -> str:
    """What the picture offers to play, said at the top of This version's files."""

    main, beside = play_choices(version)
    if main is None:
        return f"{version['label']} has no video yet: press {APP_LABELS['render']} to make its preview."
    if beside is not None:
        return f"On the picture: {PLAY_FINAL}, and {PLAY_PREVIEW_BESIDE} beside it."
    if main["role"] == ROLE_AGENT:
        return f"On the picture: {PLAY_AGENT}. The app has made no preview of {version['label']} yet."
    return f"On the picture: {play_label(main)}."


def playing_words(version: dict[str, Any], row: dict[str, Any] | None) -> str:
    """What is playing, said in one line under the player: which file, its size and frame rate, and what
    kind of render it is."""

    if row is None:
        return f"{version['label']} has no video yet: press {APP_LABELS['render']} on the picture."
    role = row.get("role")
    if role in (ROLE_PREVIEW, ROLE_FINAL, ROLE_EXPORT):
        final = role != ROLE_PREVIEW
        size = format_words(version.get("final_format" if final else "preview_format") or {}) or (
            _size_words({}, "final" if final else "preview"))
        what = {ROLE_PREVIEW: "the preview", ROLE_FINAL: "the final", ROLE_EXPORT: "the export"}[role]
        kind = "the full-quality file" if final else "a quick, smaller render to judge the edit"
        return f"Playing {what} of {version['label']} ({size}): {kind}."
    if role == ROLE_AGENT:
        return f"Playing {row['name']}, a video your AI agent made itself."
    return f"Playing {row.get('name') or 'a file'} of {version['label']}."


def files_summary(version: dict[str, Any]) -> str:
    """One line of what a version has: "Preview ✓ · Final ✓ · Export ✓ · 2 videos your AI agent made"."""

    roles = {row["role"] for row in version.get("files") or []}
    parts = [f"{name} {'✓' if role in roles else '—'}" for role, name in
             ((ROLE_PREVIEW, "Preview"), (ROLE_FINAL, "Final"), (ROLE_EXPORT, "Export"))]
    agent = sum(1 for row in version.get("files") or [] if row["role"] == ROLE_AGENT)
    if agent:
        parts.append(f"{agent} video{'s' if agent != 1 else ''} your AI agent made")
    return " · ".join(parts)


def render_words(version: dict[str, Any]) -> str:
    """What Render a preview will do to this version's files (236, item 6)."""

    if version.get("preview"):
        return ("Render a preview makes this version's preview again and replaces the one there (scenes rendered "
                "before are reused when they did not change, so it is quick).")
    return "Render a preview makes this version's first preview."


def export_words(version: dict[str, Any], quality: str) -> str:
    """What Approve and export… will do to this version's files (236, items 6 and 7)."""

    if version.get("exported"):
        return (f"There is already an export of {version['label']}: it will be made again at {quality} and "
                "replace the one in the export folder.")
    if version.get("final"):
        return (f"{version['label']} has a final from before: it is made again at {quality}, replacing it, "
                "then put in the export folder.")
    return f"{version['label']} has no export yet: it will be made at {quality}."


def size_words(size: int) -> str:
    for unit, step in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{size} bytes"


# What the app knows about a recording (236, item 1) ---------------------------------------------


def library_recordings() -> list[dict[str, Any]]:
    """Every recording the Raw bin library knows, read without changing anything (the database opened
    read-only), with what mined it (the Inbox, Find my bug reports, both from the library since 224); []
    when there is no library yet. Asked of the library's front door (242, 244)."""

    return recording_records.list_recordings()


def edits_of(row: dict[str, Any], projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The editor's videos made from the recording in a Raw bin row (242, Wave C2): a bound video by its content,
    so a renamed or moved recording keeps its edits; a video made before by the path it names. Newest first."""

    content = str(row.get("content_sha256") or "")
    path = os.path.normcase(os.path.abspath(str(row.get("path") or ""))) if row.get("path") else ""
    found = [project for project in projects
             if (content and project.get("content_sha256") == content)
             or (path and not project.get("content_sha256")
                 and os.path.normcase(os.path.abspath(str(project.get("source") or ""))) == path)]
    return sorted(found, key=lambda project: str(project.get("activity") or project.get("created") or ""), reverse=True)


def knowledge_words(row: dict[str, Any] | None, project: dict[str, Any] | list[dict[str, Any]] | None = None) -> str:
    """What the app already knows about one recording, in a line: the Raw bin's guess, the speech it heard
    and its idle time, the operator's decision and labels, what mined it for tickets (the Raw bin's Mined
    words, 244), and an AI Video Editor video already made from it. "" when the app knows nothing about
    it. Shown to the operator only, never to an agent. 242 (Wave C2): ``project`` may be every edit of the
    recording (``edits_of``); several are counted."""

    edits = project if isinstance(project, list) else [project] if project else []
    if len(edits) > 1:
        before = knowledge_words(row)
        newest = edits[0]
        made = f"AI Video Editor: {len(edits)} edits"
        if newest.get("story_title"):
            made += f", newest \"{newest['story_title']}\""
        return " · ".join(part for part in (before, made) if part)
    project = edits[0] if edits else None

    parts: list[str] = []
    if row:
        guess = raw_bin_library.GUESS_TEXT.get(str(row.get("guess") or ""), "")
        if guess:
            detail = []
            minutes = float(row.get("speech_seconds") or 0.0) / 60
            if minutes >= 0.1:
                detail.append(f"{minutes:.0f} min of your speech" if minutes >= 1 else "under a minute of your speech")
            if row.get("idle_share") is not None:
                detail.append(f"{round(float(row['idle_share']) * 100)}% idle")
            parts.append(f"Raw bin: {guess}" + (f" ({', '.join(detail)})" if detail else ""))
        decision = str(row.get("decision") or "")
        if decision and decision != raw_bin_library.DECISION_UNDECIDED:
            parts.append(f"you marked it {raw_bin_library.DECISION_TEXT.get(decision, decision)}")
        if row.get("labels"):
            parts.append("labels: " + ", ".join(row["labels"]))
        # 244 (operator decision Q8): the same words as the Raw bin's Mined column.
        mined = str(row.get("mined") or ("Inbox" if row.get("reviewed_by_inbox") else ""))
        if mined:
            parts.append(f"Mined: {mined}")
    if project:
        count = len(project.get("versions") or [])
        made = f"AI Video Editor: {versions_text(project).lower()}" if count else "AI Video Editor: prepared"
        if project.get("story_title"):
            made += f", \"{project['story_title']}\""
        parts.append(made)
    return " · ".join(parts)


# Thumbnails --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThumbnailSource:
    """Where a video's card picture comes from: a frame of a masked render, or one of Prepare's masked stills."""

    key: str
    path: Path
    seconds: float = 0.0
    still: bool = False


def thumbnail_source(project: dict[str, Any]) -> ThumbnailSource | None:
    """The newest version's preview (or final), a third of the way in; else Prepare's still a third of the
    way into the race; None when the video has neither. The key changes when the file does."""

    for version in project.get("versions") or []:
        row = play_file(version)
        if row is None or row["role"] == ROLE_AGENT:
            continue
        length = video_length(version) or 0.0
        return _source(Path(row["path"]), round(length / 3, 2), still=False)
    stills = sorted((Path(project["folder"]) / "analysis" / "stills").glob("s*.jpg")) if project.get("folder") else []
    if stills:
        return _source(stills[len(stills) // 3], 0.0, still=True)
    return None


def _source(path: Path, seconds: float, *, still: bool) -> ThumbnailSource | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = hashlib.sha256(f"{os.path.normcase(str(path))}|{stat.st_size}|{stat.st_mtime_ns}|{seconds}".encode()).hexdigest()
    return ThumbnailSource(key[:32], path, seconds, still)


class ThumbnailMaker(QObject):
    """Makes card pictures one at a time, off the window's thread, into the cache folder (``editor-thumbnails``),
    and reuses them while the file they came from is unchanged."""

    ready = Signal(str, str)   # key, picture

    def __init__(self, ffmpeg: Callable[[], str], cache_root: Callable[[], Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ffmpeg = ffmpeg
        self._cache_root = cache_root
        self._queue: "queue.Queue[tuple[ThumbnailSource, Path, str]]" = queue.Queue()
        self._asked: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stopped = False

    def picture(self, source: ThumbnailSource) -> Path | None:
        """The picture when it is made; otherwise it is made and ``ready`` says when."""

        target = app_cache.item_path(self._cache_root(), "editor-thumbnails", source.key, ".jpg")
        if target.is_file():
            app_cache.touch(target)
            return target
        if source.key not in self._asked and not self._stopped:
            self._asked.add(source.key)
            self._queue.put((source, target, self._ffmpeg()))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, name="ai-video-editor-thumbnails", daemon=True)
                self._thread.start()
        return None

    def stop(self, wait_ms: int = 5000) -> bool:
        """Take no more pictures and wait for the one being taken (the app is closing); True when none is."""

        self._stopped = True
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(max(0, wait_ms) / 1000)
        return thread is None or not thread.is_alive()

    def _work(self) -> None:
        while not self._stopped:
            try:
                source, target, ffmpeg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                made = self._make(source, target, ffmpeg)
            except Exception:  # noqa: BLE001 - a card without a picture is still a card
                made = False
            if made:
                try:
                    self.ready.emit(source.key, str(target))
                except RuntimeError:
                    return  # the page closed

    @staticmethod
    def _make(source: ThumbnailSource, target: Path, ffmpeg: str) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.still:
            image = QImage(str(source.path))
            if image.isNull():
                return False
            # Prepare's stills are the whole three-screen frame; the card shows the middle screen, the game.
            third = image.width() // 3 if image.width() >= image.height() * 3 else 0
            if third:
                image = image.copy(third, 0, third, image.height())
            image = image.scaled(THUMB_WIDTH, THUMB_HEIGHT, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            temp = target.with_name(f".{target.stem}.{os.getpid()}.tmp.jpg")
            if not image.save(str(temp), "JPG", 85):
                return False
            os.replace(temp, target)
            return True
        # A third of the way in; the first picture when that is past the end of a video shorter than said.
        for seconds in dict.fromkeys((source.seconds, 0.0)):
            try:
                frame_render.render_stills(ffmpeg, source.path, [seconds], target.parent,
                                           scale=[THUMB_WIDTH, THUMB_HEIGHT], name=target.name, workers=1, reuse=False)
            except RuntimeError:
                continue
            if target.is_file():
                return True
        return False


def card_pixmap(path: str | Path | None, width: int, height: int, corner_text: str = "") -> QPixmap:
    """A card's picture at its size, cropped to fill it, with the video's length in a corner; a plain
    dark picture when there is none yet."""

    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(QColor(theme.token("inner")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if path:
        image = QPixmap(str(path))
        if not image.isNull():
            scaled = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((width - scaled.width()) // 2, (height - scaled.height()) // 2, scaled)
    if corner_text:
        font = QFont(theme.FONT_FAMILY)
        font.setPointSizeF(theme.point_size("small"))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        box = QRect(0, 0, metrics.horizontalAdvance(corner_text) + theme.px(12), metrics.height() + theme.px(4))
        box.moveBottomRight(QPoint(width - theme.px(8), height - theme.px(8)))
        painter.fillRect(box, QColor(0, 0, 0, 170))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, corner_text)
    painter.end()
    return pixmap


# Cards -------------------------------------------------------------------------------------------


def _transparent(widget: QWidget) -> QWidget:
    """A part of a card that lets the click through to the card itself."""

    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return widget


class MakeVideoCard(QPushButton):
    """The start view's one big way in: "Make a video from a recording" (236)."""

    TITLE = "Make a video from a recording"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("makeVideoCard")
        self.setProperty("primary", True)
        self.setAccessibleName(self.TITLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(18), theme.px(24), theme.px(18))
        layout.setSpacing(theme.px(16))
        words = QVBoxLayout()
        words.setSpacing(theme.px(4))
        self.title = _transparent(QLabel(self.TITLE))
        self.title.setObjectName("makeVideoTitle")
        self.title.setWordWrap(True)
        self.subtitle = _transparent(QLabel("Pick a recording. The app gets it ready; your AI agent edits it."))
        self.subtitle.setWordWrap(True)
        words.addWidget(self.title)
        words.addWidget(self.subtitle)
        layout.addLayout(words, 1)
        self.plus = _transparent(QLabel("+"))
        self.plus.setObjectName("makeVideoPlus")
        self.plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.keep_scaled(self.plus, "setFixedSize", (44, 44))
        layout.addWidget(self.plus)
        theme.keep_scaled(self, "setMinimumHeight", 104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = self.layout().minimumSize()
        return QSize(min(hint.width(), theme.px(280)), hint.height())

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return max(theme.px(104), self.layout().totalHeightForWidth(width))


class VideoCard(QPushButton):
    """One video under "Your videos": its picture, its name, its story's title, a status pill and how many
    versions it has. A click opens it. ``wide`` makes the "Continue: <name>" card: picture beside the words."""

    def __init__(self, project: dict[str, Any], parent: QWidget | None = None, *, wide: bool = False) -> None:
        super().__init__(parent)
        self.project = project
        self.wide = wide
        self.setObjectName("continueCard" if wide else "videoCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._picture: str | None = None
        self._corner = ""
        self.thumb = _transparent(QLabel() if wide else _Thumb())
        self.thumb.setObjectName("videoThumb")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not wide:
            self.thumb.resized.connect(self._paint_thumb)
        self.name_label = _transparent(QLabel(""))
        self.name_label.setObjectName("videoCardName")
        self.name_label.setWordWrap(True)
        self.story_label = _transparent(QLabel(""))
        self.story_label.setProperty("muted", True)
        self.story_label.setWordWrap(True)
        self.pill = _transparent(StatusPill())
        self.count_label = _transparent(QLabel(""))
        self.count_label.setProperty("small", True)
        self.line_label = _transparent(QLabel(""))
        self.line_label.setProperty("muted", True)
        self.line_label.setWordWrap(True)
        words = QVBoxLayout()
        words.setSpacing(theme.px(6))
        words.addWidget(self.name_label)
        if wide:
            words.addWidget(self.line_label)
        else:
            words.addWidget(self.story_label)
            # The count goes under a long status rather than squeezing it.
            row = FlowLayout(spacing=8)
            row.addWidget(self.pill)
            row.addWidget(self.count_label)
            words.addLayout(row)
        if wide:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(theme.px(16), theme.px(16), theme.px(16), theme.px(16))
            layout.setSpacing(theme.px(16))
            theme.keep_scaled(self.thumb, "setFixedSize", (160, 90))
            layout.addWidget(self.thumb)
            layout.addLayout(words, 1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        else:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, theme.px(12))
            layout.setSpacing(theme.px(10))
            layout.addWidget(self.thumb)
            inner = QVBoxLayout()
            inner.setContentsMargins(theme.px(14), 0, theme.px(14), 0)
            inner.addLayout(words)
            layout.addLayout(inner)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_project(project)

    def set_project(self, project: dict[str, Any], running: str = "", percent: int | None = None) -> None:
        self.project = project
        status, kind = status_of(project, running)
        shown = f"{status} {percent}%" if status == STATUS_GETTING_READY and percent is not None else status
        self.pill.set_status(kind, shown)
        self.count_label.setText(versions_text(project))
        name = project["name"]
        self.name_label.setText(f"Continue: {name}" if self.wide else name)
        self.story_label.setText(str(project.get("story_title") or ""))
        self.story_label.setVisible(bool(project.get("story_title")) and not self.wide)
        self.line_label.setText(continue_text(project, running, percent))
        newest = (project.get("versions") or [None])[0]
        length = video_length(newest) if newest else None
        self._corner = clock_text(length) if length else ""
        self.setAccessibleName(f"{'Continue: ' if self.wide else ''}{name}, {shown}, {versions_text(project)}")
        self._paint_thumb()

    def set_picture(self, path: str | None) -> None:
        self._picture = path
        self._paint_thumb()

    def _paint_thumb(self) -> None:
        size = self.thumb.size() if self.thumb.width() > 1 else QSize(theme.px(160), theme.px(90))
        self.thumb.setPixmap(card_pixmap(self._picture, size.width(), size.height(), "" if self.wide else self._corner))

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.layout().minimumSize()


class _Thumb(QLabel):
    """A card's picture: as wide as the card, 16:9, so the card's height follows its width and the grid
    measures each card at the width it really has."""

    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return max(1, width * 9 // 16)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(theme.px(240), theme.px(135))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(theme.px(120), theme.px(68))

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit()


class ResponsiveGrid(QWidget):
    """Cards in as many equal columns as fit (236: "repeat(auto-fill, minmax(230px, 1fr))" of the mockup)."""

    def __init__(self, minimum: int, parent: QWidget | None = None, *, most: int = 0) -> None:
        super().__init__(parent)
        self.minimum = minimum
        # At most this many columns (0: as many as fit): the start view's two big cards share the row.
        self.most = most
        self.cards: list[QWidget] = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        theme.keep_scaled(self.grid, "setHorizontalSpacing", 18)
        theme.keep_scaled(self.grid, "setVerticalSpacing", 18)
        self._columns = 0

    def set_cards(self, cards: list[QWidget]) -> None:
        for card in self.cards:
            self.grid.removeWidget(card)
            if card not in cards:
                card.setParent(None)
                card.deleteLater()
        self.cards = list(cards)
        self._columns = 0
        self._arrange(self.width())

    def _arrange(self, width: int) -> None:
        gap = self.grid.horizontalSpacing()
        columns = max(1, (max(width, 1) + gap) // (theme.px(self.minimum) + gap))
        if self.most:
            columns = min(columns, self.most)
        if columns != self._columns:
            self._columns = columns
            for card in self.cards:
                self.grid.removeWidget(card)
            for index, card in enumerate(self.cards):
                # Each card fills its cell's width and keeps its own height, at the top of the row.
                self.grid.addWidget(card, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
            # Every column of the row shares the width, even one no card is in yet.
            for column in range(max(columns, self.grid.columnCount())):
                self.grid.setColumnStretch(column, 1 if column < columns else 0)
                self.grid.setColumnMinimumWidth(column, 0)
            # Qt ignores a new layout asked for while it is laying out, so it is laid out again straight after.
            QTimer.singleShot(0, self._relayout)

    def _relayout(self) -> None:
        try:
            widget: QWidget | None = self
            while widget is not None:
                if widget.layout() is not None:
                    widget.layout().invalidate()
                widget.updateGeometry()
                if widget.isWindow():
                    break
                widget = widget.parentWidget()
        except RuntimeError:  # deleted with its page
            pass

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange(event.size().width())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), theme.px(self.minimum)), hint.height())


# The story strip ---------------------------------------------------------------------------------


class _IconRefresh:
    """A button whose line icon is drawn again when the theme or the text size changes (both restyle the
    whole window), so its colour and size always match the words beside it."""

    _icon_drawn = False

    def _draw_icon(self) -> None:  # pragma: no cover - each class draws its own
        raise NotImplementedError

    def changeEvent(self, event: Any) -> None:  # noqa: N802
        super().changeEvent(event)  # type: ignore[misc]
        if event.type() == QEvent.Type.StyleChange and self._icon_drawn:
            self._draw_icon()


class ScenePen(_IconRefresh, QToolButton):
    """The pen on a scene of the story strip: it writes a note about that scene (236 fix round)."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scenePen")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Write a note about {name}")
        self.setToolTip(f"Write a note about {name} for the next version.")
        self._draw_icon()

    def _draw_icon(self) -> None:
        size = theme.px(16)
        self.setIcon(line_icon("pen", theme.token("link"), theme.token("link_hover"), size, TOOL_ICON_FOLDER))
        self.setIconSize(QSize(size, size))
        self._icon_drawn = True


class SceneBlock(QPushButton):
    """One beat of the story under the player: its name and length, as wide as its words (236 fix
    round: a name is never cut off; the strip scrolls sideways instead), and a pen that writes a note
    about it. A right-click offers the same."""

    note_requested = Signal(object)

    def __init__(self, block: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.block = block
        self.setObjectName("sceneBlock")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        length = clock_text(block["length"])
        self.setAccessibleName(f"Scene {block['name']}, {length}, starts at {clock_text(block['start'])}")
        self.setToolTip(f"{block['name']}: {length}, from {clock_text(block['start'])}. Click to jump there; "
                        "the pen, or a right-click, writes a note about it.")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.pen = ScenePen(str(block["name"]), self)
        self.pen.clicked.connect(lambda: self.note_requested.emit(self.block))

    def _menu(self, point: QPoint) -> None:
        self.menu = QMenu(self)
        self.menu.addAction("Jump here").triggered.connect(self.click)
        self.menu.addAction("Write a note about this scene").triggered.connect(
            lambda: self.note_requested.emit(self.block))
        self.menu.popup(self.mapToGlobal(point))

    def _fonts(self) -> tuple[QFont, QFont]:
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        return bold, self.font()

    def sizeHint(self) -> QSize:  # noqa: N802
        bold, plain = self._fonts()
        words = max(QFontMetrics(bold).horizontalAdvance(str(self.block["name"])),
                    QFontMetrics(plain).horizontalAdvance(clock_text(self.block["length"])))
        pen = self.pen.sizeHint()
        width = theme.px(10) + words + theme.px(8) + pen.width() + theme.px(4)
        height = max(self.fontMetrics().height() * 2 + theme.px(14), pen.height() + theme.px(8))
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        pen = self.pen.sizeHint()
        self.pen.resize(pen)
        self.pen.move(self.width() - pen.width() - theme.px(4), (self.height() - pen.height()) // 2)

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        room = self.rect().adjusted(theme.px(10), theme.px(5), -(self.pen.width() + theme.px(10)), -theme.px(5))
        metrics = self.fontMetrics()
        line = QRect(room.left(), room.top(), room.width(), metrics.height())
        bold, plain = self._fonts()
        for font, colour, text in ((bold, "text_strong", str(self.block["name"])),
                                   (plain, "muted", clock_text(self.block["length"]))):
            painter.setFont(font)
            painter.setPen(QColor(theme.token(colour)))
            painter.drawText(line, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            line.translate(0, metrics.height())


class _StripScroll(QScrollArea):
    """The strip's scenes in a row that scrolls sideways when they do not fit; the mouse wheel scrolls it
    too, and passes on to the page at either end."""

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        bar = self.horizontalScrollBar()
        step = event.angleDelta().y() or event.angleDelta().x()
        at_end = (step > 0 and bar.value() <= bar.minimum()) or (step < 0 and bar.value() >= bar.maximum())
        if bar.maximum() <= 0 or not step or at_end:
            event.ignore()
            return
        bar.setValue(bar.value() - step)
        event.accept()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        strip = self.parentWidget()
        if isinstance(strip, SceneStrip):
            strip.fit_height()


class SceneStrip(QFrame):
    """The version's story as a strip of scenes (236): a click jumps the player there; the pen on a
    scene (or a right-click) puts that scene in the notes. 236 fix round: each scene is as wide as its
    words, and the strip scrolls sideways when they do not all fit, so a name is never cut off."""

    jump_requested = Signal(object)
    note_requested = Signal(object)

    HINT = ("The story, scene by scene. Click a scene to jump there. Right-click, or the pen on a scene, to write "
            "a note about it.")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sceneStrip")
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(12), theme.px(8), theme.px(12), theme.px(10))
        layout.setSpacing(theme.px(6))
        self.hint = QLabel(self.HINT)
        self.hint.setProperty("small", True)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.scroll = _StripScroll(self)
        self.scroll.setObjectName("sceneStripScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.inner = QWidget()
        self.inner.setObjectName("sceneStripInner")
        self.row = QHBoxLayout(self.inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(theme.px(4))
        # The scenes start at the left; the room after the last one is the strip's, not an empty scene.
        self.row.addStretch(1)
        self.scroll.setWidget(self.inner)
        layout.addWidget(self.scroll)
        # The scenes take their real size only once styled, a moment after they are made (the 150% walk saw
        # them cut off at the bottom): the strip measures itself again whenever its row changes size.
        self.inner.installEventFilter(self)
        self.blocks: list[SceneBlock] = []
        self.chosen: dict[str, Any] | None = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.inner and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            QTimer.singleShot(0, self._fit_later)
        return False

    def _fit_later(self) -> None:
        try:
            self.fit_height()
        except RuntimeError:  # deleted with its page
            pass

    def set_blocks(self, blocks: list[dict[str, Any]]) -> None:
        if [block.block for block in self.blocks] == list(blocks):
            # The same scenes (a refresh): the scene chosen stays chosen.
            self.setVisible(bool(blocks))
            return
        for block in self.blocks:
            self.row.removeWidget(block)
            block.deleteLater()
        self.blocks = []
        self.chosen = None
        for data in blocks:
            block = SceneBlock(data)
            block.clicked.connect(lambda _checked=False, b=block: self._clicked(b))
            block.note_requested.connect(self.note_requested.emit)
            self.row.insertWidget(self.row.count() - 1, block)
            self.blocks.append(block)
        self.setVisible(bool(blocks))
        self.scroll.horizontalScrollBar().setValue(0)
        self.fit_height()

    def fit_height(self) -> None:
        """As tall as the scenes, and the sideways scroll bar's height more only when it is needed."""

        tallest = max((block.sizeHint().height() for block in self.blocks), default=0)
        wide = self.inner.minimumSizeHint().width() > self.scroll.viewport().width()
        bar = self.scroll.horizontalScrollBar().sizeHint().height() if wide else 0
        height = tallest + bar
        if self.scroll.height() != height or self.scroll.minimumHeight() != height:
            self.scroll.setFixedHeight(height)

    def _clicked(self, block: SceneBlock) -> None:
        for other in self.blocks:
            other.setChecked(other is block)
        self.chosen = block.block
        self.scroll.ensureWidgetVisible(block, theme.px(16), 0)
        self.jump_requested.emit(block.block)


# The toolbar of a video ---------------------------------------------------------------------------


class ToolbarButton(_IconRefresh, QPushButton):
    """A labelled button of the video's toolbar, with its line icon (236 fix round: "Video settings",
    "Prompt", "Story & review", "Files" instead of a hidden ⋯ menu). It shows as open while its panel is."""

    def __init__(self, text: str, icon: str, parent: QWidget | None = None) -> None:
        # A single & would mark a keyboard letter and vanish ("Story & review"); doubled, it shows.
        super().__init__(text.replace("&", "&&"), parent)
        self.setObjectName("editorTool")
        self.setAccessibleName(text)
        self.icon_name = icon
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._draw_icon()

    def _draw_icon(self) -> None:
        size = theme.px(16)
        self.setIcon(line_icon(self.icon_name, theme.token("link_hover"), theme.token("link_hover"), size,
                               TOOL_ICON_FOLDER))
        self.setIconSize(QSize(size, size))
        self._icon_drawn = True

    def text(self) -> str:  # noqa: D102 - the words as shown, not as Qt keeps them
        return super().text().replace("&&", "&")

    def set_open(self, shown: bool) -> None:
        if self.property("open") != shown:
            self.setProperty("open", shown)
            self.style().unpolish(self)
            self.style().polish(self)


class ToolPanel(QFrame):
    """What a toolbar button opens (236 fix round): a small panel under it with its choices as
    full-width labelled buttons. A choice closes the panel and does its work, and the page says what it
    did beside the toolbar (UI rules section 7); a choice that only picks something (the export quality)
    keeps the panel open, so the tick can be seen moving. A choice that is not possible now stays in
    sight, greyed out, and its tooltip says why."""

    closed = Signal()

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("toolPanel")
        self.setAccessibleName(name)
        self.name = name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(8), theme.px(8), theme.px(8), theme.px(8))
        layout.setSpacing(theme.px(4))
        self.buttons: dict[str, QPushButton] = {}
        self.anchor: QWidget | None = None
        # A press outside closes it (when, and where on the screen): pressed on its own button, the click it
        # ends must not open it again.
        self.pressed_outside: tuple[float, QPoint] = (0.0, QPoint())

    def add_button(self, key: str, text: str, handler: Callable[[], Any], *, close: bool = True,
                   checkable: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("toolPanelButton")
        button.setCheckable(checkable)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        def run(_checked: bool = False) -> None:
            if close:
                self.hide()
            handler()

        button.clicked.connect(run)
        self.layout().addWidget(button)
        self.buttons[key] = button
        return button

    def add_heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("toolPanelHeading")
        label.setProperty("small", True)
        label.setWordWrap(True)
        self.layout().addWidget(label)
        return label

    def add_divider(self) -> None:
        line = QFrame()
        line.setObjectName("toolPanelDivider")
        line.setFixedHeight(1)
        self.layout().addWidget(line)

    def add_note(self) -> QLabel:
        """The line at the bottom that says, in words, why a choice is greyed out (``show_why``)."""

        self.note = QLabel("")
        self.note.setObjectName("toolPanelNote")
        self.note.setProperty("small", True)
        self.note.setProperty("muted", True)
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        self.layout().addWidget(self.note)
        return self.note

    def show_why(self, reasons: list[str]) -> None:
        """Say why the greyed-out choices cannot be used now, each reason once, so it is read, not hovered for."""

        said = list(dict.fromkeys(reason for reason in reasons if reason))
        self.note.setText(" ".join(said))
        self.note.setVisible(bool(said))

    def open_under(self, anchor: QWidget) -> None:
        """Open under ``anchor``, its left edge on the anchor's, kept inside the anchor's window and screen
        (the 150% walk saw it hang past the window's right edge)."""

        self.anchor = anchor
        self.setMinimumWidth(max(anchor.width(), theme.px(260)))
        self.adjustSize()
        # A heading that wraps needs its lines' height at the width the panel really has.
        layout = self.layout()
        if layout.hasHeightForWidth():
            self.resize(self.width(), max(self.height(), layout.totalHeightForWidth(self.width())))
        below = anchor.mapToGlobal(QPoint(0, anchor.height() + theme.px(4)))
        screen = anchor.screen()
        room = screen.availableGeometry() if screen is not None else QRect(below, self.size())
        window = anchor.window().frameGeometry()
        left, right = max(room.left(), window.left()), min(room.right(), window.right())
        x = max(left, min(below.x(), right + 1 - self.width()))
        y = below.y()
        if y + self.height() > room.bottom() + 1:
            y = max(room.top(), anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - theme.px(4))
        self.move(x, y)
        self.show()
        # Shown, its frame counts too: moved back by what still hangs over the right edge.
        over = self.frameGeometry().right() - right
        if over > 0:
            self.move(max(left, self.x() - over), self.y())
        self.raise_()
        first = next((button for button in self.buttons.values() if button.isEnabled()), None)
        if first is not None:
            first.setFocus(Qt.FocusReason.PopupFocusReason)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if not self.rect().contains(event.position().toPoint()):
            self.pressed_outside = (time.monotonic(), event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def closed_by_a_press_on(self, widget: QWidget) -> bool:
        """Whether a press on ``widget`` closed the panel a moment ago (the press reaches it after)."""

        when, where = self.pressed_outside
        self.pressed_outside = (0.0, QPoint())
        return time.monotonic() - when < 0.5 and widget.rect().contains(widget.mapFromGlobal(where))

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        super().hideEvent(event)
        self.closed.emit()


# The picture of a version --------------------------------------------------------------------------


class PictureBox(QWidget):
    """The chosen version's picture in the player's place until Play (236 fix round): as big as the room
    allows at its own shape, the box hugging the picture, with the play choices on it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aiVideoEditorPoster")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.picture = QPixmap()
        # What goes on the picture: a child laid over it, kept in its middle.
        self.overlay = QWidget(self)
        self.overlay.setObjectName("posterOverlay")
        self.overlay_layout = QVBoxLayout(self.overlay)
        self.overlay_layout.setContentsMargins(theme.px(16), theme.px(12), theme.px(16), theme.px(12))
        self.overlay_layout.setSpacing(theme.px(10))
        # The row of play choices, which the page fills; it turns into a column when it does not fit.
        self.buttons_row: QBoxLayout | None = None
        # The least height the page wants for it (the player's, so pressing Play does not move the page).
        self.least_height: Callable[[], int] | None = None
        # What is on the picture changes size (a button shown, a line of feedback): it is centred again.
        self.overlay.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.overlay and event.type() == QEvent.Type.LayoutRequest:
            QTimer.singleShot(0, self._replace)
        return False

    def _replace(self) -> None:
        try:
            self.place_overlay()
        except RuntimeError:  # deleted with its page
            pass

    def set_picture(self, path: str | None) -> None:
        self.picture = QPixmap(str(path)) if path else QPixmap()
        self.update()

    def _shown(self, layout: Any) -> list[QWidget]:
        found = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.widget() is not None and not item.widget().isHidden():
                found.append(item.widget())
            elif item.layout() is not None:
                found.extend(self._shown(item.layout()))
        return found

    def least_width(self) -> int:
        """The narrowest the picture may be: what is on it, one above the other."""

        margins = self.overlay_layout.contentsMargins()
        widest = max((widget.sizeHint().width() for widget in self._shown(self.overlay_layout)), default=0)
        return widest + margins.left() + margins.right()

    def picture_rect(self) -> QRect:
        """Where the picture goes: 16:9 (or the picture's own shape) as big as fits, in the middle; never
        narrower than what is on it (the picture is then cropped a little at the top and bottom)."""

        ratio = (self.picture.width() / self.picture.height()) if not self.picture.isNull() and self.picture.height() \
            else 16 / 9
        width, height = self.width(), self.height()
        if width > height * ratio:
            width = min(self.width(), max(int(round(height * ratio)), self.least_width()))
        else:
            height = int(round(width / ratio))
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def place_overlay(self) -> None:
        box = self.picture_rect()
        row = self.buttons_row
        if row is not None:
            # The play choices side by side when they fit on the picture, else one above the other.
            margins = self.overlay_layout.contentsMargins()
            buttons = self._shown(row)
            across = sum(button.sizeHint().width() for button in buttons) + row.spacing() * max(0, len(buttons) - 1)
            wanted = (QBoxLayout.Direction.LeftToRight if across <= box.width() - margins.left() - margins.right()
                      else QBoxLayout.Direction.TopToBottom)
            if row.direction() != wanted:
                row.setDirection(wanted)
                self.overlay_layout.activate()
        hint = self.overlay.sizeHint()
        width, height = min(max(hint.width(), self.least_width()), max(1, box.width())), min(hint.height(), self.height())
        self.overlay.setGeometry(box.x() + (box.width() - width) // 2, box.y() + (box.height() - height) // 2, width, height)
        self.overlay.raise_()
        self.update()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.place_overlay()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = self.overlay.sizeHint()
        least = self.least_height() if self.least_height is not None else 0
        return QSize(min(hint.width(), theme.px(320)), max(theme.px(180), hint.height() + theme.px(16), least))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(theme.px(640), theme.px(360))

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        box = self.picture_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(box, theme.px(14), theme.px(14))
        painter.setClipPath(path)
        painter.fillRect(box, QColor(theme.token("video")))
        if not self.picture.isNull():
            scaled = self.picture.scaled(box.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(box.x() + (box.width() - scaled.width()) // 2,
                               box.y() + (box.height() - scaled.height()) // 2, scaled)
            # A little darker, so the buttons on it read well on any picture.
            painter.fillRect(box, QColor(0, 0, 0, 70))
        painter.end()


# Dialogs -----------------------------------------------------------------------------------------


def _dialog_size(dialog: QDialog, width: int, height: int) -> None:
    screen = dialog.screen()
    room = screen.availableGeometry().size() if screen is not None else QSize(width, height)
    dialog.resize(min(theme.px(width), room.width() - 40), min(theme.px(height), room.height() - 80))


class ReaderDialog(QDialog):
    """The story or the editor's own review as a readable page (236, item 5): the short summary, the key
    changes and the concerns first; the whole text, and the technical report, one click away."""

    def __init__(self, what: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.what = what
        self.setWindowTitle(what)
        self.setObjectName("readerDialog")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(16))
        layout.setSpacing(theme.px(10))
        self.title = QLabel(what)
        self.title.setProperty("title", True)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.summary_view = QTextBrowser()
        self.summary_view.setObjectName("readerSummary")
        self.summary_view.setAccessibleName(f"{what}, in short")
        self.summary_view.setOpenExternalLinks(False)
        layout.addWidget(self.summary_view, 1)
        row = QHBoxLayout()
        self.full_button = QPushButton("Show the whole text")
        set_button_kind(self.full_button, "link")
        self.full_button.setCheckable(True)
        self.full_button.toggled.connect(self._show_full)
        row.addWidget(self.full_button)
        self.technical_button = QPushButton("Show the technical report")
        set_button_kind(self.technical_button, "link")
        self.technical_button.setCheckable(True)
        self.technical_button.toggled.connect(self._show_technical)
        row.addWidget(self.technical_button)
        row.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.full_view = QTextBrowser()
        self.full_view.setAccessibleName(what)
        self.full_view.setOpenExternalLinks(False)
        self.full_view.setVisible(False)
        layout.addWidget(self.full_view, 2)
        self.technical_view = QTextBrowser()
        self.technical_view.setAccessibleName("The technical report")
        self.technical_view.setVisible(False)
        layout.addWidget(self.technical_view, 2)
        self._text = ""
        _dialog_size(self, 760, 640)

    def show_text(self, label: str, text: str, empty: str, technical: str = "") -> None:
        """Fill it for one version: ``text`` is the file's Markdown, ``empty`` what to say without one."""

        self._text = text
        self.setWindowTitle(f"{self.what} of {label}")
        self.title.setText(f"{self.what} of {label}")
        parts = readable(text) if text.strip() else {}
        blocks = []
        if parts.get("title"):
            blocks.append(f"**{parts['title']}**")
        for heading, key in (("In short", "summary"), ("Key changes", "changes"), ("Concerns", "concerns")):
            if parts.get(key):
                blocks.append(f"### {heading}\n\n{parts[key]}")
        if not text.strip():
            blocks = [empty]
        elif len(blocks) <= (1 if parts.get("title") else 0):
            blocks.append("This file has no short summary. Press Show the whole text to read it.")
        self.summary_view.setMarkdown("\n\n".join(blocks))
        self.full_view.setMarkdown(text or empty)
        self.full_button.setVisible(bool(text.strip()))
        self.full_button.setChecked(False)
        self.technical_view.setMarkdown(technical)
        self.technical_button.setVisible(bool(technical.strip()))
        self.technical_button.setChecked(False)

    def full_text(self) -> str:
        return self._text

    def _show_full(self, on: bool) -> None:
        self.full_view.setVisible(on)
        self.full_button.setText("Hide the whole text" if on else "Show the whole text")

    def _show_technical(self, on: bool) -> None:
        self.technical_view.setVisible(on)
        self.technical_button.setText("Hide the technical report" if on else "Show the technical report")


class PromptDialog(QDialog):
    """See the prompt first (236, item 3): the prompt as it will be copied, ready to be changed, with a
    short introduction for the operator that is not part of it."""

    copied = Signal(str, str)   # tool, the text copied

    INTRO = ("This is what the app copies for your AI agent. Paste it into {name} as your first message: it says "
             "where this video's files are and tells {name} to read its instructions first. Those instructions "
             "(the brief) are kept by the app and are not shown here. You can change the words below before you "
             "copy them; your changes are used for this copy only and are not kept.")

    def __init__(self, make: Callable[[str, bool], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.make = make
        self.setWindowTitle("See the prompt first")
        self.setObjectName("promptDialog")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(16))
        layout.setSpacing(theme.px(10))
        title = QLabel("See the prompt first")
        title.setProperty("title", True)
        layout.addWidget(title)
        self.intro = QLabel("")
        self.intro.setObjectName("promptIntro")
        self.intro.setProperty("muted", True)
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        choices = QHBoxLayout()
        self.tool_choice = SegmentedControl([("claude", "Claude Code"), ("codex", "Codex")], name="For")
        self.tool_choice.set_value("claude")
        self.tool_choice.changed.connect(lambda _value: self._fill())
        choices.addWidget(QLabel("For"))
        choices.addWidget(self.tool_choice)
        self.notes_check = QCheckBox("Answer my notes")
        self.notes_check.setToolTip("The prompt for a new version that answers the notes you saved for this version.")
        self.notes_check.toggled.connect(lambda _on: self._fill())
        choices.addWidget(self.notes_check)
        choices.addStretch(1)
        layout.addLayout(choices)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("promptEditor")
        self.editor.setAccessibleName("The prompt")
        layout.addWidget(self.editor, 1)
        row = FlowLayout()
        self.copy_button = QPushButton("Copy this prompt")
        self.copy_button.setProperty("primary", True)
        row.addWidget(self.copy_button)
        self.reset_button = QPushButton("Put back the app's prompt")
        set_button_kind(self.reset_button, "link")
        self.reset_button.clicked.connect(self._fill)
        row.addWidget(self.reset_button)
        self.feedback = InlineFeedback()
        self.feedback.setObjectName("promptDialogFeedback")
        row.addWidget(self.feedback)
        layout.addLayout(row)
        bind_action(self.copy_button, self._copy, working="Copying…", done="Copied", feedback=self.feedback)
        close = QHBoxLayout()
        close.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        close.addWidget(self.close_button)
        layout.addLayout(close)
        self._made = ""
        _dialog_size(self, 820, 680)

    def open_for(self, tool: str, *, notes_label: str = "") -> None:
        self.tool_choice.set_value(tool)
        self.notes_check.setVisible(bool(notes_label))
        self.notes_check.setText(f"Answer my notes on {notes_label}" if notes_label else "Answer my notes")
        self.notes_check.blockSignals(True)
        self.notes_check.setChecked(False)
        self.notes_check.blockSignals(False)
        self._fill()
        self.feedback.clear()
        self.show()
        self.raise_()

    def tool(self) -> str:
        return str(self.tool_choice.value() or "claude")

    def edited(self) -> bool:
        return self.editor.toPlainText() != self._made

    def _fill(self) -> None:
        tool = self.tool()
        name = "Claude Code" if tool == "claude" else "Codex"
        self.intro.setText(self.INTRO.format(name=name))
        try:
            self._made = self.make(tool, self.notes_check.isChecked() and self.notes_check.isVisible())
        except (OSError, ValueError, KeyError) as exc:
            self._made = ""
            self.feedback.failed(f"The prompt could not be made: {exc}", "Close this, then try again.")
        self.editor.setPlainText(self._made)

    def _copy(self) -> Any:
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        text = self.editor.toPlainText()
        QApplication.clipboard().setText(text)
        self.copied.emit(self.tool(), text)
        name = "Claude Code" if self.tool() == "claude" else "Codex"
        from .ui_parts import Outcome  # noqa: PLC0415

        return Outcome.done(f"Copied{' with your changes' if self.edited() else ''}. Paste it into {name}.")


class ApproveExportDialog(QDialog):
    """Approve and export… (236, item 7): what it does, in a few lines, and the export quality it uses."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Approve and export")
        self.setObjectName("approveExportDialog")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(16))
        layout.setSpacing(theme.px(10))
        self.title = QLabel("Approve and export")
        self.title.setProperty("title", True)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.what = QLabel("")
        self.what.setObjectName("approveExportWhat")
        self.what.setWordWrap(True)
        self.what.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.what)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        quality_row = QHBoxLayout()
        from .widgets import WheelSafeComboBox  # noqa: PLC0415

        self.quality_combo = WheelSafeComboBox()
        self.quality_state = QLabel("")
        self.quality_state.setProperty("muted", True)
        quality_row.addWidget(self.quality_combo)
        quality_row.addWidget(self.quality_state)
        quality_row.addStretch(1)
        self.quality_label = QLabel("Export quality")
        self.quality_label.setBuddy(self.quality_combo)
        form.addRow(self.quality_label, quality_row)
        layout.addLayout(form)
        self.replaces = QLabel("")
        self.replaces.setObjectName("approveExportReplaces")
        self.replaces.setProperty("muted", True)
        self.replaces.setWordWrap(True)
        layout.addWidget(self.replaces)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.export_button = QPushButton("Export")
        self.export_button.setProperty("primary", True)
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self.accept)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)
        _dialog_size(self, 620, 420)

    def show_for(self, name: str, label: str, quality_words: str, replaces: str) -> None:
        number = label.lstrip("v").lstrip("0") or "0"
        self.title.setText(f"Approve and export {name} {label}")
        self.what.setText(
            f"This makes the finished video of version {number} on this PC:"
            "<ul style='margin-left:-20px'>"
            f"<li>renders it at full size ({PROFILES['final']['width']}×{PROFILES['final']['height']}), at the "
            "recording's own frame rate up to 60 fps, at the export quality below;</li>"
            "<li>levels the sound for upload (about −14 LUFS, as YouTube plays it);</li>"
            "<li>checks it, then puts it in the export folder.</li></ul>"
            "Nothing is uploaded. Why: the preview you watched is a quick, smaller render; the export is the "
            "full-quality file you keep or upload.")
        self.replaces.setText(replaces)
        self.export_button.setText(f"Export {label}")
        self.quality_state.setText(quality_words)


class VersionFilesDialog(QDialog):
    """This version's files (236, item 6): every video it has, what each is and who made it, what Play
    opens, and what Render a preview and Approve and export… will do to them."""

    play_requested = Signal(str)

    COLUMNS = ("File", "What it is", "Made by", "Size", "Made")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("This version's files")
        self.setObjectName("versionFilesDialog")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(16))
        layout.setSpacing(theme.px(10))
        self.title = QLabel("This version's files")
        self.title.setProperty("title", True)
        layout.addWidget(self.title)
        self.playing = QLabel("")
        self.playing.setWordWrap(True)
        layout.addWidget(self.playing)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("versionFilesTable")
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # The shared rule for tables: every column can be dragged; the file name takes the spare width.
        make_columns_resizable(self.table, stretch=0)
        self.table.doubleClicked.connect(lambda _index: self._play())
        layout.addWidget(self.table, 1)
        polish_views(self)
        self.actions_words = QLabel("")
        self.actions_words.setProperty("muted", True)
        self.actions_words.setWordWrap(True)
        layout.addWidget(self.actions_words)
        row = QHBoxLayout()
        self.play_button = QPushButton("Play the chosen file")
        self.play_button.clicked.connect(self._play)
        row.addWidget(self.play_button)
        row.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.rows: list[dict[str, Any]] = []
        _dialog_size(self, 900, 520)

    def show_for(self, title: str, playing: str, rows: list[dict[str, Any]], actions: str) -> None:
        self.title.setText(title)
        self.playing.setText(playing)
        self.rows = list(rows)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            what = FILE_WORDS.get(row["role"], row["role"])
            if row.get("same_as"):
                what += f" (the same file as the {row['same_as']})"
            made = row.get("modified", "")
            try:
                made = datetime.fromisoformat(made).astimezone().strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
            for column, text in enumerate((row["name"], what, "Your AI agent" if row["made_by"] == "agent" else "The app",
                                           size_words(int(row["size"])), made)):
                item = QTableWidgetItem(text)
                item.setToolTip(row["path"] if column == 0 else text)
                self.table.setItem(index, column, item)
        if rows:
            self.table.selectRow(0)
        for column in range(1, len(self.COLUMNS)):
            self.table.resizeColumnToContents(column)
        self.actions_words.setText(actions)
        self.play_button.setEnabled(bool(rows))
        self.show()
        self.raise_()

    def _play(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.rows):
            self.play_requested.emit(self.rows[row]["path"])


class ChooseRecordingDialog(QDialog):
    """Choose a recording (236, item 1): the recordings the Raw bin knows, newest first, with what the app
    already knows about each (its guess, your speech, idle time, your decision and labels, the Inbox's
    verdict, and a video already made from it), so they can be told apart without opening them. "Browse for
    another file…" opens the Windows file picker as before."""

    COLUMNS = ("Recording", "Length", "What the app knows")

    def __init__(self, rows: list[dict[str, Any]], projects: dict[str, dict[str, Any]] | list[dict[str, Any]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a recording")
        self.setObjectName("chooseRecordingDialog")
        self.setModal(True)
        self.chosen: Path | None = None
        self.browse_asked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(16))
        layout.setSpacing(theme.px(10))
        title = QLabel("Choose a recording")
        title.setProperty("title", True)
        layout.addWidget(title)
        intro = QLabel("The recordings the Raw bin has looked at, newest first, with what the app already knows "
                       "about each. Not in the list? Browse for another file.")
        intro.setProperty("muted", True)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search names, labels and what the app knows")
        self.search.setAccessibleName("Search recordings")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("chooseRecordingTable")
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        # The shared rule for tables: every column can be dragged; what the app knows takes the spare width.
        make_columns_resizable(self.table, stretch=2)
        self.table.doubleClicked.connect(lambda _index: self._choose())
        layout.addWidget(self.table, 1)
        polish_views(self)
        buttons = QHBoxLayout()
        self.browse_button = QPushButton("Browse for another file…")
        self.browse_button.clicked.connect(self._browse)
        buttons.addWidget(self.browse_button)
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.choose_button = QPushButton("Choose this recording")
        self.choose_button.setProperty("primary", True)
        self.choose_button.clicked.connect(self._choose)
        buttons.addWidget(self.choose_button)
        layout.addLayout(buttons)
        self.rows = sorted(rows, key=lambda row: Path(str(row.get("path") or "")).name.casefold(), reverse=True)
        # 242 (Wave C2): the page passes every video, joined to each recording by content (``edits_of``); a
        # mapping by path is what it passed before.
        self.knowledge = [knowledge_words(row, edits_of(row, projects) if isinstance(projects, list)
                                          else projects.get(os.path.normcase(str(row.get("path") or ""))))
                          for row in self.rows]
        self.table.setRowCount(len(self.rows))
        for index, (row, known) in enumerate(zip(self.rows, self.knowledge)):
            path = Path(str(row.get("path") or ""))
            minutes = float(row.get("duration_seconds") or 0.0) / 60
            for column, text in enumerate((path.name, f"{minutes:.0f} min" if minutes else "", known or "Nothing yet")):
                item = QTableWidgetItem(text)
                item.setToolTip(str(row.get("guess_reason") or "") if column == 2 else str(path))
                self.table.setItem(index, column, item)
        for column in (0, 1):
            self.table.resizeColumnToContents(column)
        self.table.resizeRowsToContents()
        if self.rows:
            self.table.selectRow(0)
        _dialog_size(self, 980, 620)

    def _filter(self, text: str) -> None:
        words = text.casefold().split()
        for index, (row, known) in enumerate(zip(self.rows, self.knowledge)):
            haystack = f"{Path(str(row.get('path') or '')).name} {known}".casefold()
            self.table.setRowHidden(index, not all(word in haystack for word in words))

    def _choose(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.rows) and not self.table.isRowHidden(row):
            self.chosen = Path(str(self.rows[row]["path"]))
            self.accept()

    def _browse(self) -> None:
        self.browse_asked = True
        self.accept()


LINK_VERDICT_WORDS = {
    link.CAN_LINK: "Its recording is where it was.",
    link.MOVED: "Its recording has moved or been renamed. It can be linked where it is now.",
    link.NO_EVIDENCE: "Nothing shows which file is its recording, so it is not offered; a file name alone is never "
                      "enough. It keeps working as it does now.",
}


class LinkRecordingsDialog(QDialog):
    """Link recordings (242, Wave C2, operator decision Q6): every video that is not linked to its recording yet,
    once, with the evidence (``race_video.link.Evidence``), and a button to link each one you confirm. Linking reads
    the recording once when the library has not, off the window's thread, and changes only the video's project file
    (a copy is kept beside it). A video you leave keeps working exactly as before."""

    linked = Signal(int, str, str)  # row, "linked" or "failed", the words to show

    def __init__(self, evidence: list[Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Link recordings")
        self.setObjectName("linkRecordingsDialog")
        self.evidence = list(evidence)
        self.changed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(16))
        layout.setSpacing(theme.px(10))
        title = QLabel("Link recordings")
        title.setProperty("title", True)
        layout.addWidget(title)
        intro = QLabel("These videos were made before the app kept which recording each one is by its content. Link "
                       "one when the evidence shows it is the right recording: its edits then follow the recording if "
                       "it is moved or renamed. A video you leave as it is keeps working as before.")
        intro.setProperty("muted", True)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(theme.px(14))
        self.buttons: list[QPushButton] = []
        self.states: list[QLabel] = []
        for index, item in enumerate(self.evidence):
            box = QFrame()
            box.setObjectName("linkRecordingsItem")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(theme.px(4))
            # The video's name with its button and what happened beside it, so the button is in sight with the name
            # (the 100% walk: under the evidence, the second video's button was out of the list's view).
            row = QHBoxLayout()
            name = QLabel(Path(item.project).name)
            name.setProperty("sectionTitle", True)
            name.setWordWrap(True)
            row.addWidget(name, 1)
            state = QLabel("")
            state.setObjectName(f"linkRecordingsState{index}")
            state.setWordWrap(True)
            row.addWidget(state)
            button = QPushButton("Link this video")
            button.setObjectName(f"linkRecordingsLink{index}")
            button.setAccessibleName(f"Link {Path(item.project).name}")
            button.setVisible(bool(item.target))
            button.clicked.connect(lambda _checked=False, number=index: self._link(number))
            row.addWidget(button)
            inner.addLayout(row)
            verdict = QLabel(LINK_VERDICT_WORDS[item.verdict])
            verdict.setWordWrap(True)
            inner.addWidget(verdict)
            facts = QLabel("\n".join(item.lines()))
            facts.setProperty("muted", True)
            facts.setWordWrap(True)
            facts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            inner.addWidget(facts)
            self.buttons.append(button)
            self.states.append(state)
            rows.addWidget(box)
        rows.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        self.linked.connect(self._on_linked)
        _dialog_size(self, 820, 720)

    def _link(self, index: int) -> None:
        item = self.evidence[index]
        self.buttons[index].setEnabled(False)
        self.states[index].setText("Confirming which recording this is…" if not item.library_has_hash else "Linking…")

        def work() -> None:
            try:
                link.link_project(Path(item.project), Path(item.target))
                state, words = "linked", "Linked."
            except Exception as exc:  # noqa: BLE001 - said in the dialog; the project file is as it was
                state, words = "failed", f"Not linked: {exc}"
            try:
                self.linked.emit(index, state, words)
            except RuntimeError:
                pass  # the dialog closed while it linked

        threading.Thread(target=work, name="ai-video-editor-link", daemon=True).start()

    def _on_linked(self, index: int, state: str, words: str) -> None:
        self.states[index].setText(words)
        if state == "linked":
            self.changed = True
            self.buttons[index].setVisible(False)
        else:
            self.buttons[index].setEnabled(True)
