from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_probe(*, restricted: bool = False) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(REPO_ROOT / "src"))

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication, QScrollArea

    from media_manglers_workbench.app import WorkbenchWindow
    from media_manglers_workbench.resources import DependencyStatus, RuntimeResources
    from media_manglers_workbench.runner import FakeRunner

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sources = root / "sources"
        evidence = root / "evidence"
        scratch = root / "scratch"
        queue = evidence / "review-inbox"
        for path in (sources, evidence, scratch, queue):
            path.mkdir(parents=True, exist_ok=True)
        (sources / "synthetic.mp4").write_bytes(b"synthetic")
        prompt = queue / "CODEX_REVIEW_QUEUE_PROMPT.md"
        prompt.write_text("Synthetic queue prompt", encoding="utf-8")
        resources = RuntimeResources(
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
        window = WorkbenchWindow(
            settings_path=root / "settings.json",
            profiles_dir=root / "profiles",
            resources=resources,
            runner_factory=FakeRunner,
            review_inbox_reconciler=lambda _payload: {
                "operator_status": "Ready for Codex review",
                "queue_root": str(queue),
                "queue_prompt_path": str(prompt),
                "queue_counts": {
                    "ready_for_codex_review": 2,
                    "waiting_on_codex": 1,
                    "additional_local_evidence": 1,
                    "done": 8,
                },
                "run_state": {"active": False, "resumable": False},
            },
            review_inbox_exact_source_paths=(
                [str(sources / "synthetic.mp4")] if restricted else None
            ),
        )
        window.run_settings.update(
            {
                "review_source_folders": str(sources),
                "review_evidence_root": str(evidence),
                "review_local_work_root": str(scratch),
                "review_inbox_folder": str(root),
                "review_dedupe_mode": "Fast",
                "review_no_recurse": False,
            }
        )
        window.set_current_workflow("5")
        window.navigate("Review Media Inbox")
        window.resize(980, 680)
        window.show()
        deadline = time.monotonic() + 3
        while (
            window.review_inbox_reconcile_thread is not None
            and time.monotonic() < deadline
        ):
            app.processEvents()
        app.processEvents()
        page = window.pages["Review Media Inbox"]
        controls = [
            window.review_inbox_settings_button,
            window.review_inbox_next3_radio,
            window.review_inbox_up_to_radio,
            window.review_inbox_all_pending_radio,
            window.review_inbox_process_button,
            window.review_inbox_stop_button,
            window.review_inbox_open_queue_button,
            window.review_inbox_copy_prompt_button,
            window.review_inbox_technical_button,
        ]
        inside: dict[str, bool] = {}
        geometries = {}
        for control in controls:
            top_left = control.mapTo(page, QPoint(0, 0))
            rectangle = control.rect().translated(top_left)
            name = control.objectName() or control.text()
            geometries[name] = rectangle
            inside[name] = page.rect().contains(rectangle)
        overlaps: list[str] = []
        for index, first in enumerate(controls):
            for second in controls[index + 1 :]:
                if geometries[first.objectName()].intersects(
                    geometries[second.objectName()]
                ):
                    overlaps.append(
                        f"{first.objectName()}|{second.objectName()}"
                    )
        minimum_sizes = {
            control.objectName(): (
                control.width() + 2 >= control.minimumSizeHint().width()
                and control.height() + 2 >= control.minimumSizeHint().height()
            )
            for control in controls
        }
        focus = {}
        for control in (
            window.review_inbox_process_button,
            window.review_inbox_stop_button,
            window.review_inbox_open_queue_button,
            window.review_inbox_copy_prompt_button,
            window.review_inbox_technical_button,
        ):
            was_enabled = control.isEnabled()
            control.setEnabled(True)
            control.setFocus(Qt.FocusReason.TabFocusReason)
            app.processEvents()
            focus[control.objectName()] = control.hasFocus()
            control.setEnabled(was_enabled)
        result = {
            "scale": os.environ.get("QT_SCALE_FACTOR"),
            "devicePixelRatio": window.devicePixelRatio(),
            "window": [window.width(), window.height()],
            "page": [page.width(), page.height()],
            "scrollAreas": len(page.findChildren(QScrollArea)),
            "inside": inside,
            "minimumSizes": minimum_sizes,
            "overlaps": overlaps,
            "focus": focus,
            "sizeHintFits": page.sizeHint().height() <= page.height() + 2,
            "restricted": restricted,
            "restrictionBannerVisible": (
                window.review_inbox_restriction_banner.isVisible()
            ),
            "allPendingEnabled": (
                window.review_inbox_all_pending_radio.isEnabled()
            ),
        }
        window._closing_after_smoke = True
        window.close()
        app.processEvents()
        print(json.dumps(result, sort_keys=True))
    return 0


class ReviewInboxScalingTests(unittest.TestCase):
    def test_100_125_and_150_percent_fit_without_primary_scroll(self) -> None:
        for scale in ("1", "1.25", "1.5"):
            for restricted in (False, True):
                env = dict(os.environ)
                env.update(
                    {
                        "QT_QPA_PLATFORM": "offscreen",
                        "QT_SCALE_FACTOR": scale,
                        "PYTHONPATH": str(REPO_ROOT / "src"),
                    }
                )
                probe_args = [sys.executable, str(Path(__file__).resolve()), "--probe"]
                if restricted:
                    probe_args.append("--restricted")
                completed = subprocess.run(
                    probe_args,
                    cwd=REPO_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                with self.subTest(
                    scale=scale,
                    restricted=restricted,
                    stderr=completed.stderr,
                ):
                    self.assertEqual(completed.returncode, 0)
                    lines = [
                        line
                        for line in completed.stdout.splitlines()
                        if line.strip().startswith("{")
                    ]
                    self.assertTrue(lines, completed.stdout)
                    result = json.loads(lines[-1])
                    self.assertEqual(result["window"], [980, 680])
                    self.assertEqual(result["scrollAreas"], 0)
                    self.assertTrue(all(result["inside"].values()), result)
                    self.assertTrue(all(result["minimumSizes"].values()), result)
                    self.assertEqual(result["overlaps"], [], result)
                    self.assertTrue(all(result["focus"].values()), result)
                    self.assertTrue(result["sizeHintFits"], result)
                    self.assertEqual(
                        result["restrictionBannerVisible"],
                        restricted,
                        result,
                    )
                    self.assertEqual(
                        result["allPendingEnabled"],
                        not restricted,
                        result,
                    )


if __name__ == "__main__":
    if "--probe" in sys.argv:
        raise SystemExit(_run_probe(restricted="--restricted" in sys.argv))
    unittest.main()
