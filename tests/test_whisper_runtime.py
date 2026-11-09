from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.whisper_runtime import build_runtime_plan


class WhisperRuntimePlanTests(unittest.TestCase):
    def test_short_large_gpu_run_gets_guardrail_budget_and_calibration(self) -> None:
        plan = build_runtime_plan(
            source_duration_seconds=322.421,
            model_name="large",
            gpu_capable=True,
            heartbeat_seconds=15,
        )

        self.assertTrue(plan["calibration_recommended"])
        self.assertEqual(plan["calibration_sample_seconds"], 45)
        self.assertGreaterEqual(plan["estimated_runtime_seconds"], 480)
        self.assertGreaterEqual(plan["resolved_timeout_seconds"], 660)

    def test_short_medium_gpu_run_still_skips_calibration(self) -> None:
        plan = build_runtime_plan(
            source_duration_seconds=322.421,
            model_name="medium",
            gpu_capable=True,
            heartbeat_seconds=15,
        )

        self.assertFalse(plan["calibration_recommended"])
        self.assertEqual(plan["calibration_sample_seconds"], 0)
        self.assertEqual(
            plan["calibration_recommendation_reason"],
            "source media is short enough that a calibration pass would add unnecessary overhead",
        )

    def test_longer_media_gets_a_higher_adaptive_timeout(self) -> None:
        short_plan = build_runtime_plan(
            source_duration_seconds=15 * 60,
            model_name="large",
            gpu_capable=False,
        )
        long_plan = build_runtime_plan(
            source_duration_seconds=90 * 60,
            model_name="large",
            gpu_capable=False,
        )

        self.assertGreater(
            long_plan["resolved_timeout_seconds"],
            short_plan["resolved_timeout_seconds"],
        )

    def test_larger_model_gets_a_higher_adaptive_timeout(self) -> None:
        small_plan = build_runtime_plan(
            source_duration_seconds=60 * 60,
            model_name="small",
            gpu_capable=False,
        )
        large_plan = build_runtime_plan(
            source_duration_seconds=60 * 60,
            model_name="large",
            gpu_capable=False,
        )

        self.assertGreater(
            large_plan["resolved_timeout_seconds"],
            small_plan["resolved_timeout_seconds"],
        )

    def test_explicit_timeout_override_wins(self) -> None:
        plan = build_runtime_plan(
            source_duration_seconds=60 * 60,
            model_name="large",
            gpu_capable=False,
            explicit_timeout_seconds=7777,
        )

        self.assertEqual(plan["resolved_timeout_seconds"], 7777)
        self.assertEqual(plan["timeout_source"], "explicit_override")

    def test_all_track_effective_duration_multiplies_workload(self) -> None:
        source_duration = 17 * 60 + 6
        plan = build_runtime_plan(
            source_duration_seconds=source_duration,
            effective_duration_seconds=source_duration * 6,
            audio_track_count=6,
            transcript_audio_mode="All",
            model_name="medium",
            gpu_capable=True,
        )

        self.assertEqual(plan["source_duration_seconds"], source_duration)
        self.assertEqual(plan["effective_duration_seconds"], source_duration * 6)
        self.assertEqual(plan["audio_track_count"], 6)
        self.assertEqual(plan["transcript_audio_mode"], "All")

    def test_six_track_all_mode_budget_exceeds_single_track_budget(self) -> None:
        source_duration = 17 * 60 + 6
        single_track = build_runtime_plan(
            source_duration_seconds=source_duration,
            model_name="medium",
            gpu_capable=True,
        )
        all_tracks = build_runtime_plan(
            source_duration_seconds=source_duration,
            effective_duration_seconds=source_duration * 6,
            audio_track_count=6,
            transcript_audio_mode="All",
            model_name="medium",
            gpu_capable=True,
        )

        self.assertGreater(
            all_tracks["resolved_timeout_seconds"],
            single_track["resolved_timeout_seconds"],
        )
        self.assertGreater(
            all_tracks["estimated_runtime_seconds"],
            single_track["estimated_runtime_seconds"],
        )

    def test_stall_watchdog_is_separate_from_runtime_budget(self) -> None:
        plan = build_runtime_plan(
            source_duration_seconds=90 * 60,
            model_name="large",
            gpu_capable=False,
            heartbeat_seconds=10,
        )

        self.assertIn("stall_timeout_seconds", plan)
        self.assertIn("resolved_timeout_seconds", plan)
        self.assertLess(plan["stall_timeout_seconds"], plan["resolved_timeout_seconds"])
        self.assertGreaterEqual(plan["stall_timeout_seconds"], 30)


if __name__ == "__main__":
    unittest.main()
