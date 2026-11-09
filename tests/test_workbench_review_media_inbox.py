from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QObject, Qt, Signal  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
)

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.audio_detection import (  # noqa: E402
    AudioStreamInfo,
    LayoutConfirmationStore,
    SourceAudioInspection,
)
from media_manglers_workbench.metadata import WORKFLOW_BY_NUMBER  # noqa: E402
from media_manglers_workbench.review_inbox_dialogs import (  # noqa: E402
    ReviewInboxAllPendingDialog,
    ReviewInboxAudioChoiceDialog,
)
from media_manglers_workbench.resources import (  # noqa: E402
    DependencyStatus,
    RuntimeResources,
)
from media_manglers_workbench.runner import FakeRunner, RunnerResult  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESS_MARKER = "MM_REVIEW_INBOX_PROCESS_RESULT_V1 "


def _ready_resources() -> RuntimeResources:
    return RuntimeResources(
        app_root=REPO_ROOT,
        script_path=REPO_ROOT / "Video Mangler.ps1",
        backend_source_root=REPO_ROOT / "src",
        icon_path=REPO_ROOT / "assets" / "Video Mangler.ico",
        powershell_exe="powershell",
        python_exe="py",
        ffmpeg_exe="ffmpeg",
        ffprobe_exe="ffprobe",
        packaged=False,
        dependencies=[DependencyStatus("synthetic backend", "ready")],
    )


def _status(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "operator_status": "Done",
        "queue_root": "",
        "queue_prompt_path": "",
        "queue_counts": {
            "ready_for_codex_review": 0,
            "waiting_on_codex": 0,
            "additional_local_evidence": 0,
            "manual_review": 0,
            "done": 0,
        },
        "run_state": {
            "active": False,
            "resumable": False,
        },
    }
    result.update(overrides)
    return result


class _FakePlayerWindow(QObject):
    """The shared player as the Inbox dialog sees it: it reports the track it really plays."""

    track_heard = Signal(str, int)


class _AcceptedAudioDialog:
    selected_result = {
        "source_path": "synthetic.mkv",
        "layout_fingerprint": "layout-1",
        "audio_ordinal": 1,
        "human_track_number": 2,
    }

    def __init__(self, *_args, **_kwargs) -> None:
        self.diagnostic = SimpleNamespace(connect=lambda _callback: None)

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted)


class _AcceptedAllPendingDialog:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted)


class _KeepCleanupDialog:
    decision = "keep_generated"

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def exec(self) -> int:
        return 1


class ReviewMediaInboxWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_root = self.root / "synthetic-sources"
        self.source_root.mkdir()
        (self.source_root / "synthetic.mp4").write_bytes(b"synthetic")
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()
        self.scratch_root = self.root / "scratch"
        self.scratch_root.mkdir()
        self.queue_root = self.evidence_root / "review-inbox"
        self.queue_root.mkdir()
        self.queue_prompt = self.queue_root / "CODEX_REVIEW_QUEUE_PROMPT.md"
        self.queue_prompt.write_text("Synthetic Codex queue prompt", encoding="utf-8")
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
            self.window.deleteLater()
        self.app.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.window = None
        self.temp.cleanup()

    def _configured_status(self, **overrides: object) -> dict[str, object]:
        return _status(
            queue_root=str(self.queue_root),
            queue_prompt_path=str(self.queue_prompt),
            **overrides,
        )

    def _window(
        self,
        *,
        reconciler=None,
        runner_factory=FakeRunner,
        resources: RuntimeResources | None = None,
        exact_source_paths: list[str] | None = None,
    ) -> WorkbenchWindow:
        self.window = WorkbenchWindow(
            settings_path=self.root / "settings.json",
            profiles_dir=self.root / "profiles",
            runner_factory=runner_factory,
            resources=resources or _ready_resources(),
            review_inbox_reconciler=reconciler
            or (lambda _payload: self._configured_status()),
            review_inbox_exact_source_paths=exact_source_paths,
        )
        self.window.app_settings["temp_folder"] = str(self.root / "temp")
        self.window.run_settings.update(
            {
                "temp_folder": str(self.root / "temp"),
                "review_source_folders": str(self.source_root),
                "review_evidence_root": str(self.evidence_root),
                "review_local_work_root": str(self.scratch_root),
                "review_inbox_folder": str(self.root),
                "review_dedupe_mode": "Fast",
                "review_no_recurse": False,
            }
        )
        self.window.set_current_workflow("5")
        self.window.navigate("Review Media Inbox")
        self.window.show()
        self.app.processEvents()
        self._wait(lambda: self.window.review_inbox_reconcile_thread is None)
        self.window._refresh_review_inbox_dashboard()
        return self.window

    def _wait(self, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(predicate())

    @staticmethod
    def _runner_for(contract: dict[str, object], *, delay: float = 0.0):
        line = PROCESS_MARKER + json.dumps(contract)
        return lambda: FakeRunner(stdout=[line], delay_seconds=delay)

    def _ready_audio_choice_dialog(
        self, name: str, *, listened: bool = True, silent_track: int | None = None,
    ) -> tuple[ReviewInboxAudioChoiceDialog, Path]:
        source = self.root / f"{name}.mkv"
        confirmation_path = self.root / f"{name}-layouts.json"
        self.opened_targets: list[object] = []
        self.player_window = _FakePlayerWindow()

        def open_in_player(target):
            self.opened_targets.append(target)
            return self.player_window

        dialog = ReviewInboxAudioChoiceDialog(
            {"source_path": str(source)},
            ffprobe_exe="ffprobe",
            ffmpeg_exe="ffmpeg",
            temp_root=self.root / "temp",
            confirmation_store=LayoutConfirmationStore(confirmation_path),
            player_opener=open_in_player,
        )
        dialog.inspection = SourceAudioInspection(
            source=source,
            streams=[
                AudioStreamInfo(
                    ordinal=0,
                    stream_index=1,
                    title="Game",
                    codec="aac",
                    channels=2,
                ),
                AudioStreamInfo(
                    ordinal=1,
                    stream_index=2,
                    title="Microphone",
                    language="eng",
                    codec="aac",
                    channels=1,
                ),
            ],
            ranked=[],
            layout_fingerprint=f"{name}-layout",
            recorder_profile="synthetic",
            duration_seconds=30.0,
            selected_ordinal=1,
            preview_regions={1: [
                SimpleNamespace(label="speech", start_seconds=12.0, duration_seconds=6.0),
                SimpleNamespace(label="speech", start_seconds=22.0, duration_seconds=5.0),
            ]},
            stream_audibility={
                ordinal: {"final_state": "digital_silence" if ordinal == silent_track else "audible_signal"}
                for ordinal in (0, 1)
            },
        )
        dialog.track_combo.blockSignals(True)
        dialog.track_combo.clear()
        dialog.track_combo.addItem("Track 1 — Game", 0)
        dialog.track_combo.addItem("Track 2 — Microphone", 1)
        dialog.track_combo.setCurrentIndex(1)
        dialog.track_combo.blockSignals(False)
        dialog._populate_regions()
        if listened:
            dialog.listened.add(1)
        dialog._refresh_buttons()
        dialog.show()
        self.app.processEvents()
        return dialog, confirmation_path

    def test_01_visible_name_and_home_route_are_review_media_inbox(self) -> None:
        self.assertEqual(WORKFLOW_BY_NUMBER["5"].title, "Review Media Inbox")
        window = self._window()
        window.start_workflow_from_home("5")
        self.assertIs(
            window.page_stack.currentWidget(),
            window.pages["Review Media Inbox"],
        )

    def test_02_primary_page_is_not_scrollable_and_exposes_only_task_controls(self) -> None:
        window = self._window()
        page = window.pages["Review Media Inbox"]
        self.assertNotIsInstance(page, QScrollArea)
        self.assertEqual(page.findChildren(QScrollArea), [])
        button_text = {
            button.text() for button in page.findChildren(QPushButton)
        }
        self.assertEqual(
            button_text,
            {
                "Inbox settings",
                "Process new media",
                "Stop after current",
                "Open Codex review queue",
                "Copy Codex prompt",
                "Technical details",
                # 237: the shared parts' own controls: the job banner's link, and Dismiss on a failure
                # line or a finished job (hidden until one is shown).
                "Open in Queue / Progress",
                "Dismiss",
            },
        )
        public_text = " ".join(
            widget.text() for widget in page.findChildren(QPushButton)
        ).casefold()
        for forbidden in (
            "scan / refresh",
            "prepare bounded",
            "json",
            "lifecycle",
            "finalize reviewed",
            "render targeted",
        ):
            self.assertNotIn(forbidden, public_text)

    def test_03_workload_defaults_and_up_to_bounds(self) -> None:
        window = self._window()
        self.assertTrue(window.review_inbox_next3_radio.isChecked())
        self.assertFalse(window.review_inbox_up_to_spin.isVisible())
        window.review_inbox_up_to_radio.setChecked(True)
        self.app.processEvents()
        self.assertTrue(window.review_inbox_up_to_spin.isVisible())
        self.assertEqual(window.review_inbox_up_to_spin.minimum(), 1)
        self.assertEqual(window.review_inbox_up_to_spin.maximum(), 9999)
        self.assertEqual(window.review_inbox_up_to_spin.value(), 10)

    def test_04_missing_configuration_is_actionable_and_process_is_disabled(self) -> None:
        window = self._window()
        window.run_settings["review_source_folders"] = ""
        window._refresh_review_inbox_dashboard()
        self.assertFalse(window.review_inbox_process_button.isEnabled())
        self.assertEqual(window.review_inbox_operator_status.text(), "Needs attention")
        self.assertIn(
            "Use Inbox settings to choose at least one local source folder",
            window.review_inbox_attention.text(),
        )
        self.assertNotIn(
            str(window.run_settings.get("default_input_folder") or "private-default"),
            window.review_inbox_attention.text(),
        )

    def test_05_launch_reconcile_is_background_only_and_updates_all_counts(self) -> None:
        calls: list[dict[str, object]] = []

        def reconcile(payload):
            calls.append(payload)
            time.sleep(0.03)
            return self._configured_status(
                operator_status="Ready for Codex review",
                queue_counts={
                    "ready_for_codex_review": 4,
                    "waiting_on_codex": 3,
                    "additional_local_evidence": 2,
                    "done": 19,
                },
            )

        window = self._window(reconciler=reconcile)
        self.assertTrue(calls)
        self.assertFalse(calls[-1]["allow_source_scan"])
        self.assertFalse(calls[-1]["allow_media_processing"])
        self.assertEqual(window.review_inbox_operator_status.text(), "Ready for Codex review")
        self.assertEqual(
            window.review_inbox_queue_count_labels["ready_for_codex_review"].text(),
            "4",
        )
        self.assertEqual(
            window.review_inbox_queue_count_labels["waiting_on_codex"].text(),
            "3",
        )
        self.assertEqual(
            window.review_inbox_queue_count_labels[
                "additional_local_evidence"
            ].text(),
            "2",
        )
        self.assertEqual(window.review_inbox_queue_count_labels["done"].text(), "19")

    def test_primary_attention_hides_diagnostics_but_technical_details_retains_them(
        self,
    ) -> None:
        window = self._window()
        private_detail = (
            r"RuntimeError: C:\private-media\operator\synthetic.mp4 could not be read"
        )
        contract = self._configured_status(
            operator_status="Needs attention",
            attention={
                "code": "preparation_error",
                "message": "Media preparation stopped safely.",
                "details": private_detail,
            },
        )

        window._apply_review_inbox_status(contract)

        self.assertEqual(
            window.review_inbox_attention.text(),
            "Media preparation stopped safely.",
        )
        self.assertEqual(window.review_inbox_attention.toolTip(), "")
        self.assertNotIn(private_detail, window.review_inbox_attention.text())
        with patch(
            "media_manglers_workbench.app.ReviewInboxTechnicalDialog"
        ) as dialog_type:
            window.open_review_inbox_technical_details()
        details = dialog_type.call_args.args[0]
        self.assertIn(json.dumps(private_detail)[1:-1], details)

    def test_retained_manual_review_is_informational_and_process_stays_enabled(
        self,
    ) -> None:
        window = self._window()

        window._apply_review_inbox_status(
            self._configured_status(
                operator_status="Manual review available",
                queue_counts={
                    "ready_for_codex_review": 0,
                    "waiting_on_codex": 0,
                    "additional_local_evidence": 0,
                    "manual_review": 1,
                    "done": 0,
                },
                manual_review=[
                    {
                        "batch_id": "retained-manual",
                        "manual_review_count": 1,
                        "batch_relative_path": "batches/retained-manual",
                    }
                ],
            )
        )

        self.assertEqual(
            window.review_inbox_operator_status.text(),
            "Manual review available",
        )
        self.assertIn(
            "1 prior item remains available for manual review",
            window.review_inbox_attention.text(),
        )
        self.assertIn(
            "New media processing can continue",
            window.review_inbox_attention.text(),
        )
        self.assertTrue(window.review_inbox_attention.isVisible())
        self.assertEqual(
            window.review_inbox_queue_count_labels["done"].text(),
            "0",
        )
        self.assertTrue(window.review_inbox_next3_radio.isChecked())
        self.assertTrue(window.review_inbox_process_button.isEnabled())

    def test_06_process_stays_on_inbox_and_consumes_distinct_contract(self) -> None:
        contract = self._configured_status(
            operator_status="Waiting on Codex",
            queue_counts={
                "ready_for_codex_review": 0,
                "waiting_on_codex": 2,
                "additional_local_evidence": 0,
                "done": 7,
            },
        )
        window = self._window(runner_factory=self._runner_for(contract))
        window.start_review_inbox_process()
        self._wait(lambda: window.runner_thread is None)
        self.assertIs(
            window.page_stack.currentWidget(),
            window.pages["Review Media Inbox"],
        )
        self.assertEqual(window.review_inbox_operator_status.text(), "Waiting on Codex")
        self.assertEqual(
            window.review_inbox_queue_count_labels["waiting_on_codex"].text(),
            "2",
        )

    def test_07_process_command_receives_workload_limit_and_safe_defaults(self) -> None:
        captured: list[list[str]] = []

        class CapturingRunner(FakeRunner):
            def run(self, command, on_log=None, **_kwargs):
                captured.append(list(command.argv))
                line = PROCESS_MARKER + json.dumps(self_contract)
                if on_log:
                    on_log("stdout", line)
                return RunnerResult("succeeded", 0, stdout_lines=[line])

        self_contract = self._configured_status()
        window = self._window(runner_factory=CapturingRunner)
        window.review_inbox_up_to_radio.setChecked(True)
        window.review_inbox_up_to_spin.setValue(10)
        window.start_review_inbox_process()
        self._wait(lambda: window.runner_thread is None)
        argv = captured[-1]
        self.assertIn("Process", argv)
        self.assertIn("up_to_n", argv)
        self.assertIn("10", argv)
        self.assertIn("-NoPrompt", argv)

    def test_restricted_qualification_is_run_scoped_and_path_free_on_page(
        self,
    ) -> None:
        captured: list[list[str]] = []
        approved = self.source_root / "synthetic.mp4"
        (self.root / "settings.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 5,
                    "settings": {
                        "review_inbox_exact_source_paths": [
                            str(self.root / "stale-private-source.mkv")
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        class CapturingRunner(FakeRunner):
            def run(self, command, on_log=None, **_kwargs):
                captured.append(list(command.argv))
                line = PROCESS_MARKER + json.dumps(self_contract)
                if on_log:
                    on_log("stdout", line)
                return RunnerResult("succeeded", 0, stdout_lines=[line])

        self_contract = self._configured_status(
            run_state={
                "active": True,
                "resumable": True,
                "status": "waiting_external_review",
                "exact_source_restriction": True,
                "exact_source_restriction_count": 1,
            }
        )
        window = self._window(
            runner_factory=CapturingRunner,
            exact_source_paths=[str(approved)],
        )

        self.assertTrue(window.review_inbox_restriction_banner.isVisible())
        self.assertIn(
            "Restricted qualification run: 1 selected source",
            window.review_inbox_restriction_banner.text(),
        )
        self.assertNotIn(str(approved), window.review_inbox_restriction_banner.text())
        self.assertFalse(window.review_inbox_all_pending_radio.isEnabled())
        self.assertNotIn(
            "review_inbox_exact_source_paths",
            window.app_settings,
        )
        window.save_app_settings()
        saved_settings = json.loads(
            window.settings_path.read_text(encoding="utf-8")
        )
        self.assertNotIn(
            "review_inbox_exact_source_paths",
            saved_settings["settings"],
        )
        with patch.object(
            QInputDialog,
            "getText",
            return_value=("restricted-copy", True),
        ):
            window.save_profile_as()
        saved_profile = json.loads(
            window.profile_manager.profile_path("restricted-copy").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn(
            "review_inbox_exact_source_paths",
            saved_profile["settings"],
        )

        window.start_review_inbox_process()
        self._wait(lambda: window.runner_thread is None)
        argv = captured[-1]
        restriction_index = argv.index("-ReviewInboxExactSourcePathsJson")
        self.assertEqual(
            json.loads(argv[restriction_index + 1]),
            [str(approved)],
        )
        self.assertNotIn(str(approved), window.pages["Review Media Inbox"].findChild(
            QLabel, "reviewInboxRestrictionBanner"
        ).text())

    def test_08_full_mode_requires_confirmation_for_each_new_run(self) -> None:
        window = self._window(
            runner_factory=self._runner_for(self._configured_status())
        )
        window.run_settings["review_dedupe_mode"] = "Full"
        with patch.object(
            QMessageBox,
            "warning",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as warning:
            window.start_review_inbox_process()
        self.assertEqual(warning.call_count, 1)
        self.assertIsNone(window.runner_thread)

    def test_09_stop_after_current_writes_cooperative_signal(self) -> None:
        window = self._window(
            runner_factory=self._runner_for(
                self._configured_status(
                    operator_status="Processing",
                    run_state={
                        "active": True,
                        "resumable": False,
                        "workload_mode": "next_3",
                    },
                ),
                delay=0.08,
            )
        )
        window.start_review_inbox_process()
        self.assertIsNotNone(window.runner_thread)
        stop_path = window.review_inbox_stop_path
        window.stop_review_inbox_after_current()
        self.assertIsNotNone(stop_path)
        self.assertTrue(stop_path.is_file())
        self.assertIn(
            "safe boundary",
            stop_path.read_text(encoding="utf-8"),
        )
        self._wait(lambda: window.runner_thread is None)

    def test_10_queue_open_and_copy_use_queue_level_paths(self) -> None:
        window = self._window()
        window._apply_review_inbox_status(
            self._configured_status(
                queue_counts={
                    "ready_for_codex_review": 1,
                    "waiting_on_codex": 0,
                    "additional_local_evidence": 0,
                    "done": 0,
                }
            )
        )
        opened: list[Path] = []
        window._open_path = lambda path: opened.append(path) or True  # type: ignore[method-assign]
        window.open_review_inbox_queue()
        window.copy_review_inbox_codex_prompt()
        self.assertEqual(opened, [self.queue_root])
        self.assertEqual(
            QApplication.clipboard().text(),
            "Synthetic Codex queue prompt",
        )

    def test_10a_copy_prompt_errors_keep_paths_out_of_primary_page(self) -> None:
        window = self._window()
        window._apply_review_inbox_status(
            self._configured_status(
                queue_counts={
                    "ready_for_codex_review": 1,
                    "waiting_on_codex": 0,
                    "additional_local_evidence": 0,
                    "done": 0,
                }
            )
        )
        private_detail = (
            r"C:\private-queue\CODEX_REVIEW_QUEUE_PROMPT.md could not be read"
        )
        window.review_inbox_attention.setToolTip("stale private diagnostic")
        with patch.object(
            Path,
            "read_text",
            side_effect=OSError(private_detail),
        ):
            window.copy_review_inbox_codex_prompt()
        self.assertEqual(
            window.review_inbox_attention.text(),
            "The Codex queue prompt could not be copied.",
        )
        self.assertEqual(window.review_inbox_attention.toolTip(), "")
        self.assertNotIn(private_detail, window.review_inbox_attention.text())
        self.assertIn(private_detail, "\n".join(window.run_log_lines))

        self.queue_prompt.unlink()
        window.review_inbox_attention.setToolTip("another stale diagnostic")
        window.copy_review_inbox_codex_prompt()
        self.assertEqual(
            window.review_inbox_attention.text(),
            "The Codex queue prompt is not ready yet.",
        )
        self.assertEqual(window.review_inbox_attention.toolTip(), "")

    def test_11_resumable_contract_locks_workload_controls(self) -> None:
        window = self._window()
        window._apply_review_inbox_status(
            self._configured_status(
                operator_status="Needs audio choice",
                run_state={
                    "active": False,
                    "resumable": True,
                    "workload_mode": "up_to_n",
                    "new_source_limit": 27,
                },
            )
        )
        self.assertTrue(window.review_inbox_up_to_radio.isChecked())
        self.assertEqual(window.review_inbox_up_to_spin.value(), 27)
        self.assertFalse(window.review_inbox_next3_radio.isEnabled())
        self.assertFalse(window.review_inbox_up_to_spin.isEnabled())

    def test_12_structured_progress_updates_primary_page(self) -> None:
        window = self._window()
        window.current_workflow = "5"
        window._apply_structured_progress(
            {
                "schema": "MM_PROGRESS_V1",
                "phase": "transcribing",
                "activity": "Transcribing current source",
                "source_name": str(self.source_root / "synthetic.mp4"),
                "source_ordinal": 2,
                "source_total": 3,
                "progress_kind": "work_units",
                "completed": 4,
                "total": 10,
            }
        )
        self.assertEqual(window.review_inbox_operator_status.text(), "Processing")
        self.assertIn("synthetic.mp4", window.review_inbox_progress_detail.text())
        self.assertEqual(window.review_inbox_progress_bar.maximum(), 10)
        self.assertEqual(window.review_inbox_progress_bar.value(), 4)
        window._apply_structured_progress(
            {
                "schema": "MM_PROGRESS_V1",
                "phase": "No audible narration",
                "source_name": str(self.source_root / "silent.mp4"),
                "source_ordinal": 1,
                "source_total": 3,
                "progress_kind": "indeterminate",
            }
        )
        self.assertIn(
            "No audible narration",
            window.review_inbox_progress_detail.text(),
        )

    def test_13_audio_choice_continues_same_run_once_without_navigation(self) -> None:
        contract = self._configured_status(
            operator_status="Needs audio choice",
            run_state={
                "active": False,
                "resumable": True,
                "workload_mode": "next_3",
            },
            audio_choice={
                "source_path": str(self.source_root / "synthetic.mp4"),
                "token": "audio-token",
            },
            continuation="continue-audio",
        )
        window = self._window()
        launches: list[dict[str, object]] = []
        window._launch_review_inbox_process = lambda **kwargs: launches.append(kwargs)  # type: ignore[method-assign]
        with patch(
            "media_manglers_workbench.app.ReviewInboxAudioChoiceDialog",
            _AcceptedAudioDialog,
        ):
            window._handle_review_inbox_process_decision(contract)
            window._handle_review_inbox_process_decision(contract)
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0]["continuation"], "continue-audio")
        self.assertEqual(
            launches[0]["decision"]["type"],  # type: ignore[index]
            "audio",
        )
        self.assertEqual(
            launches[0]["decision"]["token"],  # type: ignore[index]
            "audio-token",
        )
        self.assertTrue(
            launches[0]["decision"]["confirmed"]  # type: ignore[index]
        )
        self.assertEqual(
            launches[0]["decision"]["audio_ordinal"],  # type: ignore[index]
            1,
        )
        self.assertIs(
            window.page_stack.currentWidget(),
            window.pages["Review Media Inbox"],
        )

    def test_14_all_pending_cancel_and_accept_send_canonical_decisions(self) -> None:
        contract = self._configured_status(
            operator_status="Processing",
            all_pending_confirmation={
                "eligible_source_count": 205,
                "total_source_bytes": 12_345,
                "scratch_free_bytes": 23_456,
                "evidence_free_bytes": 34_567,
                "estimated_peak_temporary_bytes": 45_678,
                "time_estimate": {
                    "estimated_seconds": 3661,
                    "basis": "Median recent successful preparation duration",
                },
                "token": "all-token",
            },
            continuation="continue-all",
        )
        window = self._window()
        launches: list[dict[str, object]] = []
        window._launch_review_inbox_process = lambda **kwargs: launches.append(kwargs)  # type: ignore[method-assign]
        with patch(
            "media_manglers_workbench.app.ReviewInboxAllPendingDialog"
        ) as dialog_type:
            dialog_type.return_value.exec.return_value = int(
                QDialog.DialogCode.Rejected
            )
            window._handle_review_inbox_process_decision(contract)
        self.assertEqual(len(launches), 1)
        self.assertEqual(
            launches[0]["decision"],
            {
                "type": "all_pending",
                "token": "all-token",
                "confirmed": False,
            },
        )

        second_contract = dict(contract)
        second_contract["all_pending_confirmation"] = {
            **contract["all_pending_confirmation"],  # type: ignore[misc]
            "token": "all-token-2",
        }
        with patch(
            "media_manglers_workbench.app.ReviewInboxAllPendingDialog",
            _AcceptedAllPendingDialog,
        ):
            window._handle_review_inbox_process_decision(second_contract)
        self.assertEqual(len(launches), 2)
        self.assertEqual(
            launches[1]["decision"],
            {
                "type": "all_pending",
                "token": "all-token-2",
                "confirmed": True,
            },
        )

    def test_15_cleanup_keep_is_safe_and_continues_once(self) -> None:
        contract = self._configured_status(
            operator_status="Done",
            cleanup_confirmation={
                "disposable_bytes": 1024,
                "token": "plans-1",
            },
            continuation="continue-cleanup",
        )
        window = self._window()
        launches: list[dict[str, object]] = []
        window._launch_review_inbox_process = lambda **kwargs: launches.append(kwargs)  # type: ignore[method-assign]
        with patch(
            "media_manglers_workbench.app.ReviewInboxCleanupDialog",
            _KeepCleanupDialog,
        ):
            window._handle_review_inbox_process_decision(contract)
            window._handle_review_inbox_process_decision(contract)
        self.assertEqual(len(launches), 1)
        self.assertEqual(
            launches[0]["decision"],  # type: ignore[index]
            {
                "type": "cleanup",
                "token": "plans-1",
                "choice": "keep_generated",
            },
        )

    def test_16_workflow_five_is_not_in_new_review_selector(self) -> None:
        window = self._window()
        self.assertEqual(window.workflow_selector.findData("5"), -1)
        window.navigate("New Review")
        self.assertNotEqual(window.current_workflow, "5")
        self.assertIs(
            window.page_stack.currentWidget(),
            window.pages["New Review"],
        )

    def test_17_workflows_one_through_four_still_use_existing_runner(self) -> None:
        runs: list[FakeRunner] = []
        window = self._window(
            runner_factory=lambda: runs.append(FakeRunner()) or runs[-1]
        )
        for workflow in ("1", "2", "4"):
            window.current_workflow = workflow
            window.run_settings.update(
                {
                    "input_path": str(self.source_root / "synthetic.mp4"),
                    "input_kind": "local",
                    "output_folder": str(self.root / f"out-{workflow}"),
                }
            )
            window.start_job()
            self._wait(lambda: window.runner_thread is None)
        self.assertEqual(len(runs), 3)

    def test_18_process_failure_without_contract_never_claims_completion(self) -> None:
        window = self._window(
            runner_factory=lambda: FakeRunner(exit_code=1, stderr=["synthetic failure"])
        )
        window.start_review_inbox_process()
        self._wait(lambda: window.runner_thread is None)
        self.assertEqual(window.review_inbox_operator_status.text(), "Needs attention")
        self.assertIn(
            "without a complete local queue status",
            window.review_inbox_attention.text(),
        )

    def test_19_settings_dialog_saves_machine_local_values(self) -> None:
        window = self._window()
        replacement = {
            "review_source_folders": str(self.source_root),
            "review_evidence_root": str(self.evidence_root),
            "review_local_work_root": str(self.scratch_root),
            "review_inbox_folder": str(self.root / "replacement"),
            "review_no_recurse": True,
            "review_dedupe_mode": "Fast",
        }
        with patch(
            "media_manglers_workbench.app.ReviewInboxSettingsDialog"
        ) as dialog_type:
            dialog_type.return_value.exec.return_value = int(
                QDialog.DialogCode.Accepted
            )
            dialog_type.return_value.values.return_value = replacement
            window._open_review_inbox_configuration()
        self._wait(lambda: window.review_inbox_reconcile_thread is None)
        # 224 (Wave B2b, Q3): the Inbox folder; the old ledger setting is not shown or changed.
        self.assertEqual(
            window.run_settings["review_inbox_folder"],
            replacement["review_inbox_folder"],
        )
        self.assertEqual(
            window.app_settings["review_inbox_folder"],
            replacement["review_inbox_folder"],
        )
        self.assertEqual(window.app_settings.get("review_ledger_path", ""), "")
        self.assertTrue(window.settings_path.is_file())

    def test_20_process_serializes_canonical_decision_json_exactly(self) -> None:
        captured: list[list[str]] = []
        result_contract = self._configured_status()

        class CapturingRunner(FakeRunner):
            def run(self, command, on_log=None, **_kwargs):
                captured.append(list(command.argv))
                line = PROCESS_MARKER + json.dumps(result_contract)
                if on_log:
                    on_log("stdout", line)
                return RunnerResult("succeeded", 0, stdout_lines=[line])

        window = self._window(runner_factory=CapturingRunner)
        decision = {
            "type": "cleanup",
            "token": "cleanup-token",
            "choice": "keep_generated",
        }
        window._launch_review_inbox_process(
            continuation="opaque-continuation",
            decision=decision,
            full_acknowledged=True,
        )
        self._wait(lambda: window.runner_thread is None)
        argv = captured[-1]
        decision_index = argv.index("-ReviewInboxDecisionJson")
        continuation_index = argv.index("-ReviewInboxContinuation")
        self.assertEqual(
            argv[decision_index + 1],
            json.dumps(decision, ensure_ascii=False, separators=(",", ":")),
        )
        self.assertEqual(argv[continuation_index + 1], "opaque-continuation")

    def test_21_prompt_exists_but_copy_is_disabled_until_codex_work_is_ready(
        self,
    ) -> None:
        window = self._window()
        self.assertTrue(self.queue_prompt.is_file())
        self.assertFalse(window.review_inbox_copy_prompt_button.isEnabled())
        self.assertEqual(
            window.review_inbox_copy_prompt_button.toolTip(),
            "No Codex review work is ready yet.",
        )
        window.copy_review_inbox_codex_prompt()
        self.assertEqual(
            window.review_inbox_attention.text(),
            "No Codex review work is ready yet.",
        )

    def test_22_all_pending_dialog_uses_canonical_capacity_and_time_fields(
        self,
    ) -> None:
        dialog = ReviewInboxAllPendingDialog(
            {
                "eligible_source_count": 205,
                "total_source_bytes": 3 * 1024**3,
                "scratch_free_bytes": 40 * 1024**3,
                "evidence_free_bytes": 50 * 1024**3,
                "estimated_peak_temporary_bytes": 12 * 1024**3,
                "time_estimate": {
                    "estimated_seconds": 3661,
                    "basis": "Median recent successful preparation duration",
                },
            }
        )
        try:
            visible_text = "\n".join(
                label.text() for label in dialog.findChildren(QLabel)
            )
        finally:
            dialog.close()
            dialog.deleteLater()
        self.assertIn("205 source(s)", visible_text)
        self.assertIn("3.0 GiB", visible_text)
        self.assertIn("12.0 GiB", visible_text)
        self.assertIn("1 hr 1 min 1 sec", visible_text)

    def test_23_completed_or_cancelled_run_resets_workload_to_next_three(
        self,
    ) -> None:
        window = self._window()
        for status in ("complete", "cancelled"):
            with self.subTest(status=status):
                window.review_inbox_all_pending_radio.setChecked(True)
                window.review_inbox_up_to_spin.setValue(99)
                window._apply_review_inbox_status(
                    self._configured_status(
                        run_state={
                            "active": False,
                            "resumable": False,
                            "status": status,
                            "workload_mode": "all_pending",
                            "new_source_limit": None,
                        }
                    )
                )
                self.assertTrue(window.review_inbox_next3_radio.isChecked())
                self.assertEqual(window.review_inbox_up_to_spin.value(), 10)
                self.assertTrue(window.review_inbox_next3_radio.isEnabled())

    def test_264_use_this_track_is_your_answer_for_this_recording_and_the_layout_answer_is_saved_as_before(self) -> None:
        from media_manglers.core import speech_facts

        (self.root / "use-this.mkv").write_bytes(b"synthetic")
        dialog, confirmation_path = self._ready_audio_choice_dialog("use-this")
        try:
            QTest.mouseClick(dialog.use_button, Qt.MouseButton.LeftButton)
            self.assertEqual(speech_facts.confirmed_track(self.root / "use-this.mkv"), 2)
            self.assertEqual(speech_facts.answer_for(self.root / "use-this.mkv").by, "inbox_dialog")
            self.assertEqual(json.loads(confirmation_path.read_text(encoding="utf-8"))["layouts"]["use-this-layout"]["audioOrdinal"], 1)
        finally:
            dialog.close()

    def test_264_your_answer_for_a_recording_never_overwrites_the_saved_answer_for_its_layout(self) -> None:
        from media_manglers.core import speech_facts

        source = self.root / "answered.mkv"
        source.write_bytes(b"synthetic")
        speech_facts.confirm_track(source, 2, by=speech_facts.ANSWERED_ON_BUGS)
        dialog, confirmation_path = self._ready_audio_choice_dialog("answered")
        try:
            inspection = dialog.inspection
            inspection.audibility_state = "audible_candidates"
            dialog.inspection = None
            dialog._inspection_ready(inspection)
            self.assertEqual(inspection.confirmation_state, "confirmed-recording")
            self.assertEqual(dialog.selected_result["audio_ordinal"], 1)
            self.assertFalse(confirmation_path.exists(), "a saved layout answer is not made out of it")
        finally:
            dialog.close()

    def test_24_play_opens_the_shared_player_on_the_track_at_the_region(self) -> None:
        # 220: the dialog has no player of its own; Play opens the shared player on top of it,
        # on the chosen track, at the chosen region, with the track's regions as its speech stretches.
        dialog, _confirmation_path = self._ready_audio_choice_dialog("shared-player", listened=False)
        try:
            self.assertFalse(dialog.use_button.isEnabled(), "a recommendation alone confirms nothing")
            dialog.region_combo.setCurrentIndex(1)
            QTest.mouseClick(dialog.play_button, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertEqual(len(self.opened_targets), 1)
            target = self.opened_targets[0]
            self.assertEqual(target.path, dialog.source)
            self.assertEqual(target.hear_track, 2)
            self.assertEqual(target.start_seconds, 22.0)
            self.assertEqual(target.stretches, ((12.0, 18.0), (22.0, 27.0)))
            self.assertEqual(target.stretch_kind, "speech")
            self.assertFalse(dialog.use_button.isEnabled(), "a click on Play is not hearing the track")
            self.player_window.track_heard.emit(str(dialog.source), 1)
            self.assertFalse(dialog.use_button.isEnabled(), "hearing another track does not count")
            self.player_window.track_heard.emit(str(dialog.source), 2)
            self.assertTrue(dialog.use_button.isEnabled(), "once the player plays it, an audible track can be confirmed")
            self.assertFalse(hasattr(dialog, "player"), "the dialog keeps no player of its own")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_24a_audio_choice_keeps_paths_and_failures_out_of_visible_tooltips(
        self,
    ) -> None:
        private_detail = (
            r"C:\private\recordings\operator-session.mkv: ffprobe failed"
        )
        dialog = ReviewInboxAudioChoiceDialog(
            {"source_path": str(self.root / "private-source.mkv")},
            ffprobe_exe="ffprobe",
            ffmpeg_exe="ffmpeg",
            temp_root=self.root / "temp",
            confirmation_store=LayoutConfirmationStore(
                self.root / "audio-layouts.json"
            ),
        )
        diagnostics: list[str] = []
        dialog.diagnostic.connect(diagnostics.append)
        try:
            source_name = dialog.findChild(
                QLabel,
                "reviewInboxAudioSourceName",
            )
            self.assertIsNotNone(source_name)
            self.assertEqual(source_name.toolTip(), "")
            self.assertNotIn(str(self.root), source_name.text())

            dialog._inspection_failed(private_detail)
            self.assertEqual(dialog.status.toolTip(), "")
            self.assertNotIn(private_detail, dialog.status.text())
            self.assertIn(private_detail, diagnostics[-1])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_24aa_a_silent_track_is_never_confirmed_even_after_playing_it(
        self,
    ) -> None:
        dialog, _confirmation_path = self._ready_audio_choice_dialog(
            "silent-track", listened=False, silent_track=1,
        )
        try:
            QTest.mouseClick(dialog.play_button, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.player_window.track_heard.emit(str(dialog.source), 2)
            self.assertFalse(dialog.use_button.isEnabled())
            self.assertIn("no audible signal", dialog.status.text().lower())
            QTest.keyClick(dialog.track_combo, Qt.Key.Key_Return)
            self.app.processEvents()
            self.assertIsNone(dialog.selected_result)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_24aa2_a_track_the_player_cannot_load_is_never_confirmed(self) -> None:
        dialog, store = self._ready_audio_choice_dialog("cannot-load", listened=False)
        try:
            QTest.mouseClick(dialog.play_button, Qt.MouseButton.LeftButton)
            self.app.processEvents()  # the player never reports the track: it could not load it
            self.assertFalse(dialog.use_button.isEnabled())
            dialog._confirm()
            self.assertIsNone(dialog.selected_result)
            self.assertFalse(store.exists())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_24ab_a_recommendation_alone_never_confirms(self) -> None:
        dialog, store = self._ready_audio_choice_dialog("not-played", listened=False)
        try:
            dialog._confirm()
            self.assertIsNone(dialog.selected_result)
            self.assertFalse(store.exists())
            self.assertIn("play the selected track", dialog.status.text().lower())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_24b_audio_diagnostics_are_available_only_in_technical_details(
        self,
    ) -> None:
        private_detail = r"C:\private\audio\preview.wav: decode failed"
        window = self._window()

        window._record_review_inbox_diagnostic(private_detail)

        self.assertNotIn(
            private_detail,
            window.review_inbox_attention.text(),
        )
        self.assertEqual(window.review_inbox_attention.toolTip(), "")
        self.assertIn(private_detail, "\n".join(window.run_log_lines))
        window.run_log_lines = []
        with patch(
            "media_manglers_workbench.app.ReviewInboxTechnicalDialog"
        ) as dialog_type:
            window.open_review_inbox_technical_details()
        details = dialog_type.call_args.args[0]
        self.assertIn(private_detail, details)

    def test_24c_audio_choice_controls_have_stable_keyboard_tab_order(self) -> None:
        dialog, _confirmation_path = self._ready_audio_choice_dialog(
            "keyboard-order"
        )
        controls = [
            dialog.track_combo,
            dialog.region_combo,
            dialog.play_button,
            dialog.stop_button,
            dialog.use_button,
        ]
        self.assertEqual(
            [control.objectName() for control in controls],
            [
                "reviewInboxAudioTrackCombo",
                "reviewInboxAudioRegionCombo",
                "reviewInboxAudioPlayButton",
                "reviewInboxAudioStopButton",
                "reviewInboxAudioUseButton",
            ],
        )
        try:
            controls[0].setFocus(Qt.FocusReason.TabFocusReason)
            self.app.processEvents()
            self.assertTrue(controls[0].hasFocus())
            for expected in controls[1:]:
                QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
                self.app.processEvents()
                self.assertTrue(
                    expected.hasFocus(),
                    f"Tab focus stopped on {dialog.focusWidget().objectName()!r}",
                )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_24d_audio_choice_enter_confirms_and_stop_or_escape_pauses(self) -> None:
        accepted, accepted_store = self._ready_audio_choice_dialog(
            "keyboard-accept"
        )
        try:
            self.assertTrue(accepted.use_button.isDefault())
            accepted.track_combo.setFocus(Qt.FocusReason.TabFocusReason)
            self.assertTrue(accepted.track_combo.hasFocus())
            QTest.keyClick(accepted.track_combo, Qt.Key.Key_Return)
            self.app.processEvents()
            self.assertEqual(
                accepted.result(),
                int(QDialog.DialogCode.Accepted),
            )
            self.assertEqual(
                (accepted.selected_result or {}).get("audio_ordinal"),
                1,
            )
            self.assertTrue(accepted_store.is_file())
        finally:
            accepted.close()
            accepted.deleteLater()

        stopped, stopped_store = self._ready_audio_choice_dialog(
            "keyboard-stop"
        )
        try:
            stopped.stop_button.setFocus(Qt.FocusReason.TabFocusReason)
            QTest.keyClick(stopped.stop_button, Qt.Key.Key_Space)
            self.app.processEvents()
            self.assertEqual(
                stopped.result(),
                int(QDialog.DialogCode.Rejected),
            )
            self.assertIsNone(stopped.selected_result)
            self.assertFalse(stopped_store.exists())
        finally:
            stopped.close()
            stopped.deleteLater()

        escaped, escaped_store = self._ready_audio_choice_dialog(
            "keyboard-escape"
        )
        try:
            QTest.keyClick(escaped, Qt.Key.Key_Escape)
            self.app.processEvents()
            self.assertEqual(
                escaped.result(),
                int(QDialog.DialogCode.Rejected),
            )
            self.assertIsNone(escaped.selected_result)
            self.assertFalse(escaped_store.exists())
        finally:
            escaped.close()
            escaped.deleteLater()

    def test_24e_video_guide_matches_process_cli_and_legacy_scan_default(self) -> None:
        guide = (
            REPO_ROOT / "docs" / "guides" / "VIDEO_MANGLER.txt"
        ).read_text(encoding="utf-8")
        script = (REPO_ROOT / "Video Mangler.ps1").read_text(
            encoding="utf-8-sig"
        )
        for parameter in (
            "-ReviewMediaInbox",
            "-ReviewInboxAction",
            "-ReviewInboxWorkload",
            "-ReviewInboxNewSourceLimit",
            "-ReviewInboxExactSourcePathsJson",
            "-ReviewInboxContinuation",
            "-ReviewInboxDecisionJson",
            "-ReviewAudioConfirmationsPath",
            "-ReviewStopAfterCurrentFilePath",
        ):
            self.assertIn(parameter, guide)
        for workload in ("next_3", "up_to_n", "all_pending"):
            self.assertIn(workload, guide)
        self.assertRegex(
            guide,
            r"Process is the normal one-click\s+coordinator",
        )
        self.assertIn("safe legacy default of Scan", guide)
        self.assertIn("Settings files use schema version 5", guide)
        self.assertIn("Profile files use schema version 2", guide)
        self.assertNotIn("metadata-only\n  lifecycle scan", guide)
        for declaration in (
            '[Alias("ReviewMediaInbox")]',
            '[string]$ReviewInboxAction = "Scan"',
            '[string]$ReviewInboxWorkload = "next_3"',
            '[int]$ReviewInboxNewSourceLimit = 0',
            '[string]$ReviewInboxExactSourcePathsJson = ""',
            '[string]$ReviewInboxContinuation = ""',
            '[string]$ReviewInboxDecisionJson = ""',
            '[string]$ReviewAudioConfirmationsPath = ""',
            '[string]$ReviewStopAfterCurrentFilePath = ""',
        ):
            self.assertIn(declaration, script)
        self.assertIn("--review-inbox-exact-source", guide)

    def test_24b_inbox_is_ready_once_the_startup_tool_check_ends(self) -> None:
        # 220: as the start-up page, the Inbox refreshed while the tool check was still
        # running and nothing refreshed it afterwards, so it said "Done" with Process greyed
        # out until its settings were saved again.
        window = self._window()
        worker = SimpleNamespace(deleteLater=lambda: None, isRunning=lambda: False, wait=lambda *_a: True)
        window.dependency_check_thread = worker  # type: ignore[assignment]
        window._refresh_review_inbox_dashboard()
        self.assertFalse(window.review_inbox_process_button.isEnabled())
        self.assertEqual(window.review_inbox_operator_status.text(), "Checking tools")

        window._dependency_check_stopped(worker)  # type: ignore[arg-type]
        self.app.processEvents()
        self.assertTrue(window.review_inbox_process_button.isEnabled())
        self.assertNotEqual(window.review_inbox_operator_status.text(), "Checking tools")

    def test_25_first_process_click_checks_dependencies_then_continues(self) -> None:
        runs: list[list[str]] = []

        class CapturingRunner(FakeRunner):
            def run(self, command, on_log=None, **kwargs):
                kwargs.pop("cwd", None)
                runs.append(list(command.argv))
                return super().run(command, on_log=on_log, **kwargs)

        resources = _ready_resources()
        resources.dependencies = [
            DependencyStatus("synthetic backend", "not_checked")
        ]
        resources.preflight_complete = False
        window = self._window(
            resources=resources,
            runner_factory=lambda: CapturingRunner(
                stdout=[
                    PROCESS_MARKER
                    + json.dumps(self._configured_status())
                ]
            ),
        )
        window._refresh_review_inbox_dashboard()
        self.assertTrue(window.review_inbox_process_button.isEnabled())

        with patch.object(window, "start_dependency_check") as check:
            window.start_review_inbox_process()

        check.assert_called_once_with()
        self.assertTrue(window.review_inbox_process_after_dependency_check)
        self.assertFalse(window.review_inbox_process_button.isEnabled())
        self.assertEqual(window.review_inbox_operator_status.text(), "Processing")
        self.assertIn(
            "Checking configured local tools",
            window.review_inbox_progress_detail.text(),
        )

        resources.dependencies = [
            DependencyStatus("synthetic backend", "ready")
        ]
        resources.preflight_complete = True
        dependency_worker = SimpleNamespace(deleteLater=lambda: None)
        reconcile_worker = SimpleNamespace(deleteLater=lambda: None)
        window.dependency_check_thread = dependency_worker  # type: ignore[assignment]
        window.review_inbox_reconcile_thread = reconcile_worker  # type: ignore[assignment]
        window._dependency_check_stopped(  # type: ignore[arg-type]
            dependency_worker
        )
        self.app.processEvents()
        self.assertTrue(window.review_inbox_process_after_dependency_check)
        self.assertEqual(runs, [])

        window._review_inbox_reconcile_stopped(  # type: ignore[arg-type]
            reconcile_worker
        )
        self._wait(
            lambda: (
                not window.review_inbox_process_after_dependency_check
                and window.runner_thread is None
                and bool(runs)
            )
        )
        self.assertEqual(len(runs), 1)
        self.assertIn("Process", runs[0])
        self.assertFalse(window.review_inbox_process_after_dependency_check)
        self.assertEqual(window.review_inbox_operator_status.text(), "Done")

    def test_26_failed_dependency_check_stays_on_inbox_with_one_message(self) -> None:
        resources = _ready_resources()
        resources.dependencies = [
            DependencyStatus("Synthetic Python", "not_checked")
        ]
        resources.preflight_complete = False
        window = self._window(resources=resources)

        with patch.object(window, "start_dependency_check"):
            window.start_review_inbox_process()

        resources.dependencies = [
            DependencyStatus("Synthetic Python", "needs_setup")
        ]
        resources.preflight_complete = True
        reconcile_worker = SimpleNamespace(deleteLater=lambda: None)
        window.review_inbox_reconcile_thread = reconcile_worker  # type: ignore[assignment]
        window._resume_review_inbox_after_dependency_check()
        self.assertTrue(window.review_inbox_process_after_dependency_check)
        self.assertNotEqual(
            window.review_inbox_operator_status.text(),
            "Needs attention",
        )
        window._review_inbox_reconcile_stopped(  # type: ignore[arg-type]
            reconcile_worker
        )
        self._wait(
            lambda: (
                not window.review_inbox_process_after_dependency_check
                and window.review_inbox_operator_status.text()
                == "Needs attention"
            )
        )
        self.assertIsNone(window.runner_thread)
        self.assertEqual(
            window.review_inbox_operator_status.text(),
            "Needs attention",
        )
        self.assertIn(
            "Settings > Dependencies: Synthetic Python.",
            window.review_inbox_attention.text(),
        )
        self.assertIs(
            window.page_stack.currentWidget(),
            window.pages["Review Media Inbox"],
        )


if __name__ == "__main__":
    unittest.main()
