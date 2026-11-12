"""226: Whisper's helper can say how far it has got, but only when asked (progress_work_units).

Features 1 and 2 hand it a progress file and show what it says on Queue / Progress. Asked, the file
reports the stretches of speech decoded so far of all of them, as work units, while Whisper decodes;
not asked, the file says exactly what the 9e065e4 helper wrote, write for write.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import sparse_narration as sn  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from tests.test_short_reactions import (  # noqa: E402
    ANCHOR_TEXT,
    GUESS,
    PROBLEM,
    REAL,
    ScriptedModel,
    line,
    load_baseline,
    narration,
    transcribe,
    unload_baseline,
)
from tests.whisper_test_models import checked_whisper  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def record_writes(module):
    """Patches ``module._write_progress`` to note each write (without its clock fields) and still write."""

    writes: list[dict] = []
    real = module._write_progress

    def write(progress_file, *, stage, message, started_at, extra=None):
        writes.append({"stage": stage, "message": message, **(extra or {})})
        real(progress_file, stage=stage, message=message, started_at=started_at, extra=extra)

    return mock.patch.object(module, "_write_progress", side_effect=write), writes


class _GpuTorch:
    __version__ = "0.0.0+cu"
    version = SimpleNamespace(cuda="12.0")
    cuda = SimpleNamespace(is_available=lambda: True, device_count=lambda: 1, get_device_name=lambda index: "Test GPU")


class _FailingOnGpuModel(ScriptedModel):
    """Fails on the graphics card at the third stretch, as a GPU that runs out of memory does."""

    def __init__(self, device: str) -> None:
        self.device = device

    def transcribe(self, audio_path: str, **kwargs: object) -> dict:
        if self.device == "cuda" and Path(audio_path).stem == "chunk-0003":
            raise RuntimeError("simulated CUDA failure")
        return super().transcribe(audio_path, **kwargs)


class _GpuWhisper:
    @staticmethod
    def load_model(model_name: str, device: str) -> _FailingOnGpuModel:
        return _FailingOnGpuModel(device)


def _script(intervals) -> dict:
    return {1: [line(intervals, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)], 2: [line(intervals, 2, 8.0, 9.0, "Oh wow.", GUESS)],
            3: [line(intervals, 3, 12.0, 14.0, "and into the pit lane now", REAL)]}


BURSTS = [(2.0, 4.0, -25.0), (8.0, 9.0, -30.0), (12.0, 14.0, -25.0)]


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class WorkUnitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wav = narration(self.root / "narration.wav", BURSTS)
        self.intervals, _audit = sn.detect_speech_intervals(self.wav)
        self.assertEqual(len(self.intervals), 3)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_asked_for_the_file_counts_the_stretches_decoded(self) -> None:
        patch, writes = record_writes(whisper_local)
        with patch:
            transcribe(whisper_local, self.wav, self.root / "out", _script(self.intervals),
                       progress_file=str(self.root / "progress.json"), progress_work_units=True)
        units = [(item["completed"], item["total"]) for item in writes if item.get("progress_kind") == "work_units"]
        self.assertEqual(units, [(0, 3), (1, 3), (2, 3), (3, 3)])
        self.assertTrue(all(item["stage"] == "transcribing" for item in writes if "progress_kind" in item))
        # Once decoding is over the file no longer counts stretches.
        self.assertEqual(writes[-1]["stage"], "complete")
        self.assertNotIn("progress_kind", writes[-1])
        self.assertNotIn("completed", (self.root / "progress.json").read_text(encoding="utf-8"))

    def test_a_fall_back_to_the_cpu_starts_counting_again(self) -> None:
        patch, writes = record_writes(whisper_local)
        ScriptedModel.script, ScriptedModel.calls = _script(self.intervals), []
        request = {"audio_path": str(self.wav), "output_dir": str(self.root / "gpu"), "model_name": "medium",
                   "language_code": "en", "prefer_gpu": True, "narration_speech_mode": "Sparse",
                   "heartbeat_interval_seconds": 60, "progress_file": str(self.root / "progress.json"),
                   "progress_work_units": True}
        with patch, mock.patch.dict(sys.modules, {"whisper": checked_whisper(_GpuWhisper()), "torch": _GpuTorch()}, clear=False):
            result = whisper_local.transcribe_from_request(request)
        self.assertEqual(result["device"], "cpu")
        seen = [(item["stage"], item.get("device"), (item.get("completed"), item.get("total"))) for item in writes
                if item["stage"] in ("transcribing", "fallback_to_cpu")]
        # The CPU's first word is not the graphics card's last count.
        self.assertEqual(seen, [
            ("transcribing", "cuda", (None, None)),
            ("transcribing", "cuda", (0, 3)), ("transcribing", "cuda", (1, 3)), ("transcribing", "cuda", (2, 3)),
            ("fallback_to_cpu", "cpu", (None, None)),
            ("transcribing", "cpu", (None, None)),
            ("transcribing", "cpu", (0, 3)), ("transcribing", "cpu", (1, 3)), ("transcribing", "cpu", (2, 3)),
            ("transcribing", "cpu", (3, 3)),
        ])

    @unittest.skipIf(bool(PROBLEM), PROBLEM)
    def test_not_asked_the_file_is_written_exactly_as_before(self) -> None:
        baseline = self.root / "baseline"
        old = load_baseline(baseline)
        try:
            for name, payload in (("absent", {}), ("off", {"progress_work_units": False})):
                with self.subTest(name):
                    old_patch, old_writes = record_writes(old.whisper_local)
                    new_patch, new_writes = record_writes(whisper_local)
                    with old_patch:
                        transcribe(old.whisper_local, self.wav, self.root / name / "old", _script(self.intervals),
                                   progress_file=str(self.root / name / "old.json"))
                    with new_patch:
                        transcribe(whisper_local, self.wav, self.root / name / "new", _script(self.intervals),
                                   progress_file=str(self.root / name / "new.json"), **payload)
                    for item in old_writes + new_writes:
                        item.pop("audio_path")
                    self.assertGreater(len(old_writes), 5)
                    self.assertEqual(new_writes, old_writes)
        finally:
            unload_baseline(baseline)


if __name__ == "__main__":
    unittest.main()
