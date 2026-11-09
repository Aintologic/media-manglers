"""Drawing the privacy masks for the operator's cameras (150 Phase 3).

A mask marks the parts of a camera that are always blurred: before any AI editor sees a picture,
and in every frame that is rendered. The operator paints over a still of the camera; white is
private. The painted mask is kept as drawn, so it can be changed later, and saved feathered (soft
edges, so the blur blends in) into the operator's per-user mask store, never the repository.

The still is shown only here, on this PC. It is never handed to an AI editor.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core.race_video.library import panel_still
from media_manglers.core.race_video.privacy import default_store, load_masks, save_mask
from media_manglers.core.race_video.timeline import DEFAULT_LAYOUT
from media_manglers.core.scratch import scratch_root

from .runner import hidden_subprocess_creation_flags
from .ui_parts import warn
from .widgets import WheelSafeComboBox

CAMERAS = (("left", "Left camera"), ("right", "Right camera"))
SOFTNESS_SIGMA = 12  # matches the soft edge of the masks drawn by hand during Phase 0


def drawn_path(store: Path, panel: str) -> Path:
    """The mask as painted, kept beside the feathered one so it can be edited again."""

    return store / f"{panel}.drawn.png"


class MaskCanvas(QWidget):
    """The camera still with the mask painted over it in red. Left button paints, or erases."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.still = QImage()
        self.mask = QImage()
        self.brush = 80          # in camera pixels
        self.erasing = False
        self._last: QPointF | None = None
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(False)

    def set_images(self, still: QImage, mask: QImage | None) -> None:
        self.still = still
        blank = QImage(still.size(), QImage.Format.Format_RGB32)
        blank.fill(QColor("black"))
        if mask is not None and not mask.isNull():
            blank = mask.convertToFormat(QImage.Format.Format_RGB32).scaled(
                still.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.mask = blank
        self.update()

    def clear(self) -> None:
        if not self.mask.isNull():
            self.mask.fill(QColor("black"))
            self.update()

    def _frame(self) -> tuple[float, float, float]:
        """Scale and offset that fit the still in the widget."""

        if self.still.isNull():
            return 1.0, 0.0, 0.0
        scale = min(self.width() / self.still.width(), self.height() / self.still.height())
        x = (self.width() - self.still.width() * scale) / 2
        y = (self.height() - self.still.height() * scale) / 2
        return scale, x, y

    def to_image(self, point: QPointF) -> QPointF:
        scale, x, y = self._frame()
        return QPointF((point.x() - x) / scale, (point.y() - y) / scale)

    def paint_at(self, start: QPointF, end: QPointF) -> None:
        if self.mask.isNull():
            return
        painter = QPainter(self.mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("black" if self.erasing else "white")
        pen = painter.pen()
        pen.setColor(color)
        pen.setWidthF(self.brush)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(start, end)
        painter.end()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._last = self.to_image(event.position())
            self.paint_at(self._last, self._last)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._last is not None:
            point = self.to_image(event.position())
            self.paint_at(self._last, point)
            self._last = point

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802
        self._last = None

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111"))
        if self.still.isNull():
            painter.setPen(QColor("#bbb"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Choose a camera and a moment, then press Show.")
            return
        scale, x, y = self._frame()
        target = self.still.size() * scale
        painter.drawImage(QPoint(int(x), int(y)), self.still.scaled(target, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                                     Qt.TransformationMode.SmoothTransformation))
        overlay = QImage(self.mask.size(), QImage.Format.Format_ARGB32_Premultiplied)
        overlay.fill(QColor(230, 40, 40))
        overlay.setAlphaChannel(self.mask.convertToFormat(QImage.Format.Format_Grayscale8))
        painter.setOpacity(0.55)
        painter.drawImage(QPoint(int(x), int(y)), overlay.scaled(target, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                                  Qt.TransformationMode.SmoothTransformation))


class PrivacyMaskDialog(QDialog):
    def __init__(self, source: Path, *, ffmpeg: str = "ffmpeg", store: Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Privacy masks")
        self.source = source
        self.ffmpeg = ffmpeg
        self.store = store or default_store()
        # 226: the unblurred camera still is written only to the app's temporary folder, never into a
        # project folder the AI editor reads; it goes when the dialog closes.
        self._temp = tempfile.TemporaryDirectory(prefix="media_manglers_mask_editor_", dir=str(scratch_root()))
        self.saved: list[str] = []

        layout = QVBoxLayout(self)
        intro = QLabel("Paint over everything on this camera that must always be blurred: a phone, a keypad, "
                       "the room behind you. Red is blurred. The blur is applied before any AI sees a picture "
                       "and in every video made from your recordings. This picture stays on this PC.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        self.camera_combo = WheelSafeComboBox()
        for value, text in CAMERAS:
            self.camera_combo.addItem(text, value)
        controls.addWidget(self.camera_combo)
        controls.addWidget(QLabel("at"))
        self.moment = QDoubleSpinBox()
        self.moment.setRange(0, 24 * 3600)
        self.moment.setDecimals(0)
        self.moment.setSuffix(" s")
        self.moment.setValue(60)
        self.moment.setToolTip("Seconds into the recording: pick a moment where you are in the picture.")
        controls.addWidget(self.moment)
        self.show_button = QPushButton("Show")
        self.show_button.clicked.connect(self.load_camera)
        controls.addWidget(self.show_button)
        controls.addSpacing(16)
        self.paint_radio = QRadioButton("Paint")
        self.paint_radio.setChecked(True)
        self.erase_radio = QRadioButton("Erase")
        self.erase_radio.toggled.connect(lambda on: setattr(self.canvas, "erasing", on))
        controls.addWidget(self.paint_radio)
        controls.addWidget(self.erase_radio)
        controls.addWidget(QLabel("Brush"))
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(10, 300)
        self.brush_slider.setValue(80)
        self.brush_slider.valueChanged.connect(lambda value: setattr(self.canvas, "brush", value))
        controls.addWidget(self.brush_slider)
        self.clear_button = QPushButton("Clear")
        controls.addWidget(self.clear_button)
        layout.addLayout(controls)

        self.canvas = MaskCanvas()
        self.clear_button.clicked.connect(self.canvas.clear)
        layout.addWidget(self.canvas, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setEnabled(False)
        layout.addWidget(buttons)
        self.resize(1100, 760)

    @property
    def panel(self) -> str:
        return str(self.camera_combo.currentData())

    def load_camera(self) -> bool:
        out = Path(self._temp.name) / f"{self.panel}.png"
        try:
            panel_still(self.ffmpeg, self.source, DEFAULT_LAYOUT, self.panel, self.moment.value(), out)
        except (OSError, RuntimeError, ValueError) as exc:
            self.status.setText(f"That moment could not be shown: {exc}")
            return False
        still = QImage(str(out))
        drawn = drawn_path(self.store, self.panel)
        existing = load_masks(self.store).get(self.panel)
        mask = QImage(str(drawn)) if drawn.exists() else QImage(str(existing)) if existing else None
        self.canvas.set_images(still, mask)
        self.save_button.setEnabled(True)
        self.status.setText("Your saved mask is shown in red; change it, then Save." if mask is not None
                            else "No mask for this camera yet. Paint the private parts, then Save.")
        return True

    def save(self) -> None:
        if self.canvas.mask.isNull():
            return
        self.store.mkdir(parents=True, exist_ok=True)
        hard = self.canvas.mask.convertToFormat(QImage.Format.Format_Grayscale8)
        drawn = drawn_path(self.store, self.panel)
        if not hard.save(str(drawn)):
            warn(self, "Not saved", f"The mask could not be written to {drawn}.")
            return
        soft = Path(self._temp.name) / f"{self.panel}-soft.png"
        result = subprocess.run([self.ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", str(drawn),
                                 "-vf", f"format=gray,gblur=sigma={SOFTNESS_SIGMA}", str(soft)],
                                capture_output=True, text=True, creationflags=hidden_subprocess_creation_flags())
        if result.returncode != 0 or not soft.exists():
            warn(self, "Not saved", f"The soft edge could not be made: {result.stderr.strip()[-300:]}")
            return
        save_mask(self.panel, soft, self.store)
        self.saved.append(self.panel)
        self.status.setText(f"Saved. The {self.camera_combo.currentText().lower()} is blurred from the next "
                            "preparation or render on. Videos already made keep their old blur until rendered again.")

    def done(self, result: int) -> None:  # noqa: D401
        super().done(result)
        self._temp.cleanup()
