"""Focused operator dialogs for the one-click Review Media Inbox."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any, Callable

from PySide6.QtCore import QSignalBlocker, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core import speech_facts

from .main_settings import folder_state
from .audio_detection import (
    LayoutConfirmationStore,
    SourceAudioInspection,
    apply_selection_precedence,
    cleanup_preview_files,
    inspect_source,
)
from .play_targets import PlayTarget
from .ui_parts import InlineFeedback, bind_action


def _format_bytes(value: Any) -> str:
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        size = 0
    units = ("bytes", "KiB", "MiB", "GiB", "TiB")
    amount = float(size)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1024.0 or candidate == units[-1]:
            break
        amount /= 1024.0
    return f"{int(amount)} {unit}" if unit == "bytes" else f"{amount:.1f} {unit}"


def _format_duration_seconds(value: Any) -> str:
    try:
        seconds = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hr")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds or not parts:
        parts.append(f"{seconds} sec")
    return " ".join(parts)


class ReviewInboxSettingsDialog(QDialog):
    """Edits only the small machine-local settings needed by Workflow 5."""

    def __init__(
        self,
        settings: dict[str, Any],
        parent: QWidget | None = None,
        *,
        main_output_folder: str = "",
        main_temp_folder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Media Inbox settings")
        self.resize(720, 470)
        root = QVBoxLayout(self)
        guidance = QLabel(
            "Choose the recording folders to scan and separate locations for generated evidence "
            "and temporary work. Original recordings remain read-only."
        )
        guidance.setWordWrap(True)
        guidance.setProperty("muted", True)
        root.addWidget(guidance)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.source_folders = QPlainTextEdit()
        self.source_folders.setMaximumHeight(92)
        source_value = settings.get("review_source_folders")
        if isinstance(source_value, (list, tuple)):
            source_text = "\n".join(str(item) for item in source_value if str(item).strip())
        else:
            source_text = str(source_value or "").replace(";", "\n")
        self.source_folders.setPlainText(source_text)
        add_source = QPushButton("Add folder…")
        add_source.clicked.connect(self._add_source_folder)
        source_panel = QWidget()
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(self.source_folders)
        source_layout.addWidget(add_source, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addRow("Source folders", source_panel)

        self.evidence_root = self._path_row(
            form,
            "Evidence root",
            str(settings.get("review_evidence_root") or ""),
            directory=True,
        )
        self.work_root = self._path_row(
            form,
            "Scratch / work root",
            str(settings.get("review_local_work_root") or ""),
            directory=True,
        )
        # 214: a blank folder uses the main one, and each says which it is using.
        self.evidence_root_state = self._follow_main(self.evidence_root, main_output_folder, "the main output folder")
        self.work_root_state = self._follow_main(self.work_root, main_temp_folder, "the app's temporary folder")
        # 224 (Wave B2b, Q3): the Inbox's records are in the library; this is its folder (queue, batches, history
        # and the files the outside agent reads and writes). The old ledger setting is kept, unshown.
        self.inbox_folder = self._path_row(
            form,
            "Inbox folder",
            str(settings.get("review_inbox_folder") or ""),
            directory=True,
        )
        self.recurse = QCheckBox("Include subfolders")
        self.recurse.setChecked(not bool(settings.get("review_no_recurse")))
        form.addRow("", self.recurse)
        self.dedupe_mode = QComboBox()
        self.dedupe_mode.addItems(("Fast", "Full"))
        mode = str(settings.get("review_dedupe_mode") or "Fast")
        self.dedupe_mode.setCurrentText(mode if mode in {"Fast", "Full"} else "Fast")
        form.addRow("Duplicate check", self.dedupe_mode)
        root.addLayout(form, 1)

        note = QLabel(
            "Fast is the normal setting. Full reads every source and asks for confirmation before each new Process run."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        root.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _path_row(
        self,
        form: QFormLayout,
        label: str,
        value: str,
        *,
        directory: bool,
    ) -> QLineEdit:
        edit = QLineEdit(value)
        browse = QPushButton("Browse…")
        browse.clicked.connect(
            lambda checked=False, target=edit, choose_directory=directory: self._browse_path(
                target, choose_directory
            )
        )
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form.addRow(label, panel)
        return edit

    def _follow_main(self, edit: QLineEdit, main: str, name: str) -> QLabel:
        state = QLabel()
        state.setProperty("muted", True)
        edit.setPlaceholderText(f"Blank: {name}, {main}" if main else f"Blank: {name}")
        edit.parentWidget().layout().addWidget(state)

        def refresh() -> None:
            state.setText(folder_state(edit.text(), main))

        edit.textChanged.connect(refresh)
        refresh()
        return state

    def _add_source_folder(self) -> None:
        current = [line.strip() for line in self.source_folders.toPlainText().splitlines() if line.strip()]
        start = current[-1] if current else ""
        selected = QFileDialog.getExistingDirectory(self, "Add recording folder", start)
        if selected and selected not in current:
            current.append(selected)
            self.source_folders.setPlainText("\n".join(current))

    def _browse_path(self, target: QLineEdit, directory: bool) -> None:
        current = target.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Choose folder", current)
        if selected:
            target.setText(selected)

    def values(self) -> dict[str, Any]:
        folders = [line.strip() for line in self.source_folders.toPlainText().splitlines() if line.strip()]
        return {
            "review_source_folders": ";".join(folders),
            "review_evidence_root": self.evidence_root.text().strip(),
            "review_local_work_root": self.work_root.text().strip(),
            "review_inbox_folder": self.inbox_folder.text().strip(),
            "review_no_recurse": not self.recurse.isChecked(),
            "review_dedupe_mode": self.dedupe_mode.currentText() or "Fast",
        }


class ReviewInboxTechnicalDialog(QDialog):
    def __init__(
        self,
        details: str,
        *,
        open_log: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Media Inbox technical details")
        self.resize(780, 560)
        root = QVBoxLayout(self)
        explanation = QLabel(
            "Read-only diagnostics for troubleshooting. Normal processing does not require these details."
        )
        explanation.setWordWrap(True)
        explanation.setProperty("muted", True)
        root.addWidget(explanation)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details.setPlainText(details)
        root.addWidget(self.details, 1)
        actions = QHBoxLayout()
        copy = QPushButton("Copy details")
        actions.addWidget(copy)
        # 237: "Copied" or "Opened" beside these buttons.
        feedback = InlineFeedback()
        if open_log is not None:
            open_button = QPushButton("Open Workbench log")
            actions.addWidget(open_button)
            bind_action(open_button, open_log, working="Opening…", done="Opened", feedback=feedback)
        actions.addWidget(feedback)
        bind_action(copy, self._copy, working="Copying…", done="Copied", feedback=feedback)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.details.toPlainText())


class ReviewInboxCleanupDialog(QDialog):
    KEEP = 1
    REMOVE = 2

    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review complete")
        self._decision = "keep_generated"
        root = QVBoxLayout(self)
        disposable = _format_bytes(
            payload.get("disposable_bytes")
            or payload.get("temporary_bytes")
            or payload.get("bytes")
        )
        source_count = int(payload.get("source_count") or payload.get("sources") or 0)
        text = QLabel(
            f"Review is complete. Remove {disposable} of temporary generated evidence"
            + (f" for {source_count} source(s)" if source_count else "")
            + "? Original recordings will not be touched."
        )
        text.setWordWrap(True)
        root.addWidget(text)
        note = QLabel(
            "Keeping generated evidence is the safe default. Removal is limited to the already-previewed generated files."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        root.addWidget(note)
        actions = QHBoxLayout()
        keep = QPushButton("Keep generated evidence")
        keep.setDefault(True)
        keep.setAutoDefault(True)
        keep.clicked.connect(self._keep)
        remove = QPushButton("Remove temporary evidence")
        remove.clicked.connect(self._remove)
        actions.addWidget(keep)
        actions.addWidget(remove)
        root.addLayout(actions)
        keep.setFocus(Qt.FocusReason.OtherFocusReason)

    @property
    def decision(self) -> str:
        return self._decision

    def _keep(self) -> None:
        self._decision = "keep_generated"
        self.done(self.KEEP)

    def _remove(self) -> None:
        self._decision = "remove_temporary"
        self.done(self.REMOVE)

    def reject(self) -> None:
        self._keep()


class ReviewInboxAllPendingDialog(QDialog):
    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Process all pending media?")
        root = QVBoxLayout(self)
        heading = QLabel(
            f"{int(payload.get('eligible_source_count') or payload.get('eligible_count') or payload.get('source_count') or 0)} source(s) are currently eligible."
        )
        heading.setWordWrap(True)
        root.addWidget(heading)
        details = QFormLayout()
        details.addRow(
            "Source size",
            QLabel(
                _format_bytes(
                    payload.get("total_source_bytes")
                    or payload.get("source_bytes")
                    or payload.get("total_bytes")
                )
            ),
        )
        details.addRow("Scratch free", QLabel(_format_bytes(payload.get("scratch_free_bytes"))))
        details.addRow("Evidence free", QLabel(_format_bytes(payload.get("evidence_free_bytes"))))
        details.addRow(
            "Estimated peak temporary use",
            QLabel(
                _format_bytes(
                    payload.get("estimated_peak_temporary_bytes")
                    or payload.get("peak_temporary_bytes")
                    or payload.get("peak_bytes")
                )
            ),
        )
        time_estimate = payload.get("time_estimate")
        if isinstance(time_estimate, dict):
            estimate = _format_duration_seconds(
                time_estimate.get("estimated_seconds")
            )
            basis = str(time_estimate.get("basis") or "").strip()
            if estimate and basis:
                estimate = f"{estimate} ({basis})"
            elif not estimate:
                estimate = basis
        else:
            estimate = ""
        if not estimate:
            estimate = str(
                payload.get("estimated_time")
                or payload.get("estimated_duration")
                or "No reliable time estimate yet"
            )
        details.addRow("Estimated time", QLabel(estimate))
        root.addLayout(details)
        note = QLabel(
            "The eligible list is fixed for this run. New files wait for the next run, and Stop after current remains available."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        root.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Process all pending")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setDefault(True)
        cancel.setFocus(Qt.FocusReason.OtherFocusReason)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class _AudioInspectionWorker(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source: Path,
        ffprobe_exe: str,
        ffmpeg_exe: str,
        temp_root: Path,
        voice_signature: tuple[float, ...] | None,
        inspector: Callable[..., SourceAudioInspection],
    ) -> None:
        super().__init__()
        self.source = source
        self.ffprobe_exe = ffprobe_exe
        self.ffmpeg_exe = ffmpeg_exe
        self.temp_root = temp_root
        self.voice_signature = voice_signature
        self.inspector = inspector

    def run(self) -> None:
        try:
            result = self.inspector(
                self.ffprobe_exe,
                self.ffmpeg_exe,
                self.source,
                self.temp_root,
                voice_signature=self.voice_signature,
                cancel_requested=self.isInterruptionRequested,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.ready.emit(result)

    def cancel(self) -> None:
        self.requestInterruption()




class ReviewInboxAudioChoiceDialog(QDialog):
    """One-source exception dialog; recommendations never count as confirmation.

    220: the tracks are heard in the shared built-in player, opened on top of this dialog on the
    chosen track at the chosen region, with the track's speech regions as its Next / Previous speech.
    The dialog has no player of its own. A track can be confirmed only once it has been played here
    and the inspection found it audible, so a recommendation alone still never confirms anything.
    """

    diagnostic = Signal(str)

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        ffprobe_exe: str,
        ffmpeg_exe: str,
        temp_root: Path,
        confirmation_store: LayoutConfirmationStore,
        voice_signature: tuple[float, ...] | None = None,
        preferred_track_number: int = 0,
        inspector: Callable[..., SourceAudioInspection] = inspect_source,
        player_opener: Callable[[PlayTarget], Any] | None = None,
        levels_path_for: Callable[[Path], Path | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Which track contains your microphone?")
        self.resize(640, 360)
        source_value = (
            payload.get("source_path")
            or payload.get("path")
            or (payload.get("source") or {}).get("path")
            if isinstance(payload.get("source"), dict)
            else payload.get("source_path") or payload.get("path")
        )
        self.source = Path(str(source_value or ""))
        self.ffprobe_exe = ffprobe_exe
        self.ffmpeg_exe = ffmpeg_exe
        self.confirmation_store = confirmation_store
        self.voice_signature = voice_signature
        self.preferred_track_number = preferred_track_number
        self.inspector = inspector
        self.player_opener = player_opener
        self.levels_path_for = levels_path_for
        digest = hashlib.sha256(str(self.source).encode("utf-8")).hexdigest()[:12]
        self.preview_root = temp_root / "review-inbox-audio-choice" / digest
        self.inspection: SourceAudioInspection | None = None
        self.selected_result: dict[str, Any] | None = None
        self.inspection_worker: _AudioInspectionWorker | None = None
        # The tracks the player has actually played from this dialog (it says so through track_heard).
        self.listened: set[int] = set()
        self._listening_to: list[Any] = []

        root = QVBoxLayout(self)
        filename = QLabel(self.source.name or "Unknown source")
        filename.setProperty("sectionTitle", True)
        filename.setObjectName("reviewInboxAudioSourceName")
        filename.setToolTip("")
        root.addWidget(filename)
        guidance = QLabel(
            "This recording has more than one possible narration track. Play the recommendation in the "
            "player, then confirm only the track containing your microphone."
        )
        guidance.setWordWrap(True)
        root.addWidget(guidance)
        self.status = QLabel("Inspecting audio tracks locally…")
        self.status.setWordWrap(True)
        self.status.setProperty("operatorState", "active")
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)

        form = QFormLayout()
        self.track_combo = QComboBox()
        self.track_combo.setObjectName("reviewInboxAudioTrackCombo")
        self.track_combo.addItem("Inspecting tracks…", -1)
        self.track_combo.currentIndexChanged.connect(self._track_changed)
        form.addRow("Microphone track", self.track_combo)
        self.region_combo = QComboBox()
        self.region_combo.setObjectName("reviewInboxAudioRegionCombo")
        self.region_combo.addItem("Start of recording", 0)
        form.addRow("Start at", self.region_combo)
        root.addLayout(form)

        self.play_button = QPushButton("Play in the player")
        self.play_button.setObjectName("reviewInboxAudioPlayButton")
        self.play_button.setToolTip(
            "Opens the built-in player on this track at the chosen place. Close the player to come back here."
        )
        self.play_button.setAutoDefault(False)
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._play)
        play_row = QHBoxLayout()
        play_row.addWidget(self.play_button)
        play_row.addStretch(1)
        root.addLayout(play_row)
        root.addStretch(1)

        actions = QHBoxLayout()
        self.stop_button = QPushButton("Stop processing")
        self.stop_button.setObjectName("reviewInboxAudioStopButton")
        self.stop_button.setAutoDefault(False)
        self.stop_button.clicked.connect(self.reject)
        self.use_button = QPushButton("Use this track")
        self.use_button.setObjectName("reviewInboxAudioUseButton")
        self.use_button.setProperty("primary", True)
        self.use_button.setDefault(True)
        self.use_button.setAutoDefault(True)
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self._confirm)
        actions.addWidget(self.stop_button)
        actions.addStretch(1)
        actions.addWidget(self.use_button)
        root.addLayout(actions)

        for current, following in zip(
            (self.track_combo, self.region_combo, self.play_button, self.stop_button),
            (self.region_combo, self.play_button, self.stop_button, self.use_button),
        ):
            QWidget.setTabOrder(current, following)
        self._start_inspection()

    def _report_diagnostic(self, context: str, details: Any) -> None:
        diagnostic = str(details or "").strip()
        if diagnostic:
            self.diagnostic.emit(f"{context}: {diagnostic}")
        self.status.setToolTip("")

    def _start_inspection(self) -> None:
        if not self.source.is_file() or not self.ffprobe_exe or not self.ffmpeg_exe:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.status.setText("The source or local audio tools are unavailable. Stop processing and correct the setup.")
            self.status.setProperty("operatorState", "error")
            return
        worker = _AudioInspectionWorker(
            self.source,
            self.ffprobe_exe,
            self.ffmpeg_exe,
            self.preview_root / "inspection",
            self.voice_signature,
            self.inspector,
        )
        worker.ready.connect(self._inspection_ready)
        worker.failed.connect(self._inspection_failed)
        worker.finished.connect(lambda thread=worker: self._inspection_stopped(thread))
        self.inspection_worker = worker
        worker.start()

    def _inspection_ready(self, inspection: SourceAudioInspection) -> None:
        apply_selection_precedence(
            inspection,
            saved_layout=self.confirmation_store.match(inspection.layout_fingerprint),
            preferred_track_number=self.preferred_track_number,
            confirmed_track=speech_facts.confirmed_track(self.source),
        )
        self.inspection = inspection
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        ranking = {item.stream.ordinal: item for item in inspection.ranked}
        with QSignalBlocker(self.track_combo):
            self.track_combo.clear()
            for stream in inspection.streams:
                ranked = ranking.get(stream.ordinal)
                recommended = (
                    " — recommended"
                    if inspection.recommendation
                    and inspection.recommendation.stream.ordinal == stream.ordinal
                    else ""
                )
                confidence = f" ({ranked.confidence:.0%})" if ranked else ""
                details = ", ".join(
                    value
                    for value in (
                        stream.title,
                        f"{stream.channels} channel" + ("s" if stream.channels != 1 else "")
                        if stream.channels
                        else "",
                        stream.language,
                        stream.codec,
                    )
                    if value
                )
                audibility = inspection.stream_audibility.get(stream.ordinal, {})
                final_audibility = str(audibility.get("final_state") or "")
                audibility_label = (
                    " — silent"
                    if final_audibility in {"digital_silence", "below_noise_floor"}
                    else " — audibility inconclusive"
                    if final_audibility == "inconclusive"
                    else ""
                )
                self.track_combo.addItem(
                    f"{stream.human_label}{recommended}{confidence}"
                    + audibility_label
                    + (f" — {details}" if details else ""),
                    stream.ordinal,
                )
            selected = inspection.selected_ordinal
            index = self.track_combo.findData(selected)
            self.track_combo.setCurrentIndex(max(0, index))
        if not inspection.streams:
            self.status.setText("No audio tracks were detected. Stop processing and retry the source.")
            self.status.setProperty("operatorState", "error")
            return
        if inspection.audibility_state == "no_audible_narration":
            self.status.setText(
                "No audible narration was detected across the complete audio "
                "streams. Stop processing and retry Process so the source can "
                "continue with visual evidence only."
            )
            self.status.setProperty("operatorState", "ready")
            self.use_button.setEnabled(False)
            self.play_button.setEnabled(False)
            return
        if inspection.audibility_state == "inconclusive":
            self.status.setText(
                "Audio audibility could not be classified safely. Stop "
                "processing and review Technical details; no track can be "
                "confirmed."
            )
            self.status.setProperty("operatorState", "error")
            self.use_button.setEnabled(False)
            self.play_button.setEnabled(False)
            return
        if inspection.resolved:
            self.status.setText("This exact layout is already confirmed. Continuing safely…")
            ordinal = inspection.selected_ordinal
            if not self._set_selected_result(ordinal) or not isinstance(ordinal, int):
                self.status.setText(
                    "The confirmed layout did not identify a valid track. Stop processing and review the source."
                )
                self.status.setProperty("operatorState", "error")
                return
            try:
                # 264: an answer for this one recording says nothing about its layout.
                if inspection.confirmation_state != "confirmed-recording":
                    self.confirmation_store.confirm(inspection, ordinal)
            except (OSError, ValueError) as exc:
                self.status.setText(
                    "The confirmation could not be saved. Stop processing and correct the settings."
                )
                self._report_diagnostic(
                    "Review Inbox audio confirmation save failed",
                    f"{type(exc).__name__}: {exc}",
                )
                self.status.setProperty("operatorState", "error")
                return
            self.accept()
            return
        self.status.setText("Recommendation ready. Play it in the player, then confirm the microphone track.")
        self.status.setProperty("operatorState", "attention")
        self._populate_regions()
        self._refresh_buttons()

    def _inspection_failed(self, details: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status.setText(
            "Audio inspection failed safely. Stop processing, correct the source or local audio tools, and retry."
        )
        self._report_diagnostic("Review Inbox audio inspection failed", details)
        self.status.setProperty("operatorState", "error")

    def _inspection_stopped(self, worker: _AudioInspectionWorker) -> None:
        if self.inspection_worker is worker:
            self.inspection_worker = None
        worker.deleteLater()

    def _current_ordinal(self) -> int | None:
        ordinal = self.track_combo.currentData()
        return int(ordinal) if isinstance(ordinal, int) and ordinal >= 0 else None

    def _audible(self, ordinal: int) -> bool:
        inspection = self.inspection
        if inspection is None:
            return False
        return not inspection.stream_audibility or bool(inspection.stream_is_audible(ordinal))

    def _track_changed(self) -> None:
        self._populate_regions()
        if self.inspection is not None:
            ordinal = self._current_ordinal()
            self.inspection.selected_ordinal = ordinal
            if not self.inspection.resolved:
                self.inspection.confirmation_state = "unresolved"
        self._refresh_buttons()

    def _regions(self, ordinal: int | None) -> list[Any]:
        inspection = self.inspection
        if inspection is None or ordinal is None:
            return []
        return list(inspection.preview_regions.get(ordinal, []))

    def _populate_regions(self) -> None:
        regions = self._regions(self._current_ordinal())
        with QSignalBlocker(self.region_combo):
            self.region_combo.clear()
            if regions:
                for index, region in enumerate(regions):
                    self.region_combo.addItem(
                        f"{index + 1}: {region.label} · "
                        f"{region.start_seconds:.1f}s–"
                        f"{region.start_seconds + region.duration_seconds:.1f}s",
                        index,
                    )
            else:
                self.region_combo.addItem("Start of recording", 0)

    def _refresh_buttons(self) -> None:
        ordinal = self._current_ordinal()
        playable = self.inspection is not None and ordinal is not None
        self.play_button.setEnabled(playable)
        self.use_button.setEnabled(playable and self._can_confirm(ordinal))
        if playable and not self._audible(ordinal):
            self.status.setText(
                "This track contains no audible signal. Choose another track; Use this track is disabled."
            )
            self.status.setProperty("operatorState", "attention")

    def _can_confirm(self, ordinal: int | None) -> bool:
        if self.inspection is None or ordinal is None or not self._audible(ordinal):
            return False
        return self.inspection.resolved or ordinal in self.listened

    def play_target(self) -> PlayTarget | None:
        """What Play opens: the recording, on the chosen track, at the chosen place."""

        ordinal = self._current_ordinal()
        if ordinal is None:
            return None
        regions = self._regions(ordinal)
        index = max(0, int(self.region_combo.currentData() or 0))
        start = regions[min(index, len(regions) - 1)].start_seconds if regions else 0.0
        stretches = tuple(
            (float(region.start_seconds), float(region.start_seconds + region.duration_seconds))
            for region in regions
        )
        levels = self.levels_path_for(self.source) if self.levels_path_for is not None else None
        return PlayTarget(
            path=self.source,
            start_seconds=start,
            hear_track=ordinal + 1,
            stretches=stretches,
            stretch_kind="speech",
            levels_path=levels,
            label=f"Track {ordinal + 1}: is this your microphone?",
        )

    def _play(self) -> None:
        target = self.play_target()
        ordinal = self._current_ordinal()
        if target is None or ordinal is None:
            return
        if self.player_opener is None:
            self.status.setText("The built-in player is not available here.")
            self.status.setProperty("operatorState", "attention")
            return
        window = self.player_opener(target)
        # A track counts as heard only when the player says it loaded and is playing it: a click on Play
        # is not enough, and a recording the player cannot load never unlocks Use this track.
        heard = getattr(window, "track_heard", None)
        if heard is not None and window not in self._listening_to:
            heard.connect(self._on_track_heard)
            self._listening_to.append(window)
        self.status.setText(f"Opening Track {ordinal + 1} in the player…")
        self.status.setProperty("operatorState", "active")
        self._refresh_buttons()

    def _on_track_heard(self, path: str, track: int) -> None:
        if Path(str(path)) != self.source or self.inspection is None:
            return
        ordinal = int(track) - 1
        self.listened.add(ordinal)
        if self._audible(ordinal):
            self.status.setText(
                f"Playing Track {ordinal + 1} in the player. Confirm it only if it contains your microphone."
            )
            self.status.setProperty("operatorState", "ready")
        self._refresh_buttons()

    def _set_selected_result(self, ordinal: Any) -> bool:
        inspection = self.inspection
        if inspection is None or not isinstance(ordinal, int) or ordinal < 0:
            return False
        if inspection.stream_audibility and not inspection.stream_is_audible(ordinal):
            return False
        if not inspection.resolved and ordinal not in self.listened:
            return False
        stream = next((item for item in inspection.streams if item.ordinal == ordinal), None)
        if stream is None:
            return False
        self.selected_result = {
            "source_path": str(self.source),
            "layout_fingerprint": inspection.layout_fingerprint,
            "audio_ordinal": ordinal,
            "human_track_number": stream.human_track_number,
        }
        return True

    def _confirm(self) -> None:
        ordinal = self.track_combo.currentData()
        if not self._set_selected_result(ordinal) or self.inspection is None:
            self.status.setText("Play the selected track in the player before confirming it.")
            return
        self.inspection.selected_ordinal = int(ordinal)
        self.inspection.confirmation_state = "operator-confirmed"
        self.inspection.confirmation_source = "operator"
        try:
            self.confirmation_store.confirm(self.inspection, int(ordinal))
        except (OSError, ValueError) as exc:
            self.status.setText("The confirmation could not be saved. Stop processing and correct the settings.")
            self._report_diagnostic(
                "Review Inbox audio confirmation save failed",
                f"{type(exc).__name__}: {exc}",
            )
            self.status.setProperty("operatorState", "error")
            return
        # 264: Use this track is your answer for this recording too, on every screen.
        speech_facts.confirm_track(self.source, int(ordinal) + 1, by=speech_facts.ANSWERED_IN_INBOX)
        self.accept()

    def done(self, result: int) -> None:
        if self.inspection_worker is not None:
            self.inspection_worker.cancel()
        for window in self._listening_to:
            try:
                window.track_heard.disconnect(self._on_track_heard)
            except (RuntimeError, TypeError):
                pass
        self._listening_to = []
        cleanup_preview_files(self.preview_root)
        super().done(result)
