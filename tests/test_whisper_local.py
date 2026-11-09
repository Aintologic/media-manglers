from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.providers import whisper_local


class _FakeCuda:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def device_count() -> int:
        return 2

    @staticmethod
    def get_device_name(index: int) -> str:
        return f"Fake RTX {index}"


class _FakeTorchModule:
    __version__ = "9.9.9+cu999"
    version = SimpleNamespace(cuda="99.9")
    cuda = _FakeCuda()


class _FakeCpuCuda:
    @staticmethod
    def is_available() -> bool:
        return False

    @staticmethod
    def device_count() -> int:
        return 0


class _FakeCpuTorchModule:
    __version__ = "2.11.0+cpu"
    version = SimpleNamespace(cuda="")
    cuda = _FakeCpuCuda()


class _FakeModel:
    last_initial_prompt: str | None = None

    def __init__(self, device_name: str) -> None:
        self._device_name = device_name

    def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None,
        task: str,
        verbose: bool,
        fp16: bool,
        initial_prompt: str | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        _FakeModel.last_initial_prompt = initial_prompt
        if self._device_name == "cuda":
            raise RuntimeError("simulated CUDA failure")
        return {
            "language": language or "en",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello world"},
            ],
        }


class _FakeWhisperModule:
    @staticmethod
    def load_model(model_name: str, device: str) -> _FakeModel:
        return _FakeModel(device)


class WhisperLocalProviderTests(unittest.TestCase):
    def test_probe_environment_reports_gpu_capable_runtime_details(self) -> None:
        with mock.patch.dict(
            sys.modules,
            {
                "whisper": _FakeWhisperModule(),
                "torch": _FakeTorchModule(),
            },
            clear=False,
        ):
            result = whisper_local.probe_environment(emit_logs=False)

        self.assertTrue(result["whisper_import_ok"])
        self.assertTrue(result["torch_import_ok"])
        self.assertTrue(result["cuda_available"])
        self.assertEqual(result["device"], "cuda")
        self.assertEqual(result["selected_device"], "cuda")
        self.assertEqual(result["cuda_device_count"], 2)
        self.assertEqual(result["cuda_device_names"], ["Fake RTX 0", "Fake RTX 1"])
        self.assertEqual(result["selected_device_name"], "Fake RTX 0")
        self.assertEqual(result["classification_code"], "gpu_capable_for_whisper")
        self.assertTrue(result["can_run_local_whisper"])
        self.assertTrue(str(result["python_path"]).lower().endswith("python.exe") or "python" in str(result["python_path"]).lower())
        self.assertTrue(result["python_version"])

    def test_probe_environment_reports_cpu_only_runtime_details(self) -> None:
        with mock.patch.dict(
            sys.modules,
            {
                "whisper": _FakeWhisperModule(),
                "torch": _FakeCpuTorchModule(),
            },
            clear=False,
        ):
            result = whisper_local.probe_environment(emit_logs=False)

        self.assertTrue(result["whisper_import_ok"])
        self.assertTrue(result["torch_import_ok"])
        self.assertFalse(result["cuda_available"])
        self.assertEqual(result["selected_device"], "cpu")
        self.assertEqual(result["cuda_device_count"], 0)
        self.assertEqual(result["cuda_device_names"], [])
        self.assertEqual(result["classification_code"], "cpu_only_for_whisper")
        self.assertEqual(result["classification_label"], "CPU-only for Local Whisper")
        self.assertTrue(result["can_run_local_whisper"])

    def test_transcribe_from_request_records_gpu_fallback_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            audio_path = temp_root / "input.mp3"
            output_dir = temp_root / "output"
            progress_file = temp_root / "progress.json"
            audio_path.write_bytes(b"fake-audio")

            payload = {
                "audio_path": str(audio_path),
                "output_dir": str(output_dir),
                "model_name": "large",
                "language_code": "en",
                "prefer_gpu": True,
                "task_name": "transcribe",
                "progress_file": str(progress_file),
                "heartbeat_interval_seconds": 15,
            }

            with mock.patch.dict(
                sys.modules,
                {
                    "whisper": _FakeWhisperModule(),
                    "torch": _FakeTorchModule(),
                },
                clear=False,
            ):
                result = whisper_local.transcribe_from_request(payload)

            progress_state = json.loads(progress_file.read_text(encoding="utf-8"))

            self.assertEqual(result["device"], "cpu")
            self.assertEqual(result["gpu_error"], "simulated CUDA failure")
            self.assertEqual(result["requested_device"], "cuda")
            self.assertEqual(result["selected_device"], "cpu")
            self.assertEqual(result["device_switch_count"], 1)
            self.assertEqual(result["classification_code"], "gpu_capable_for_whisper")
            self.assertEqual(result["cuda_device_names"], ["Fake RTX 0", "Fake RTX 1"])
            self.assertEqual(progress_state["device"], "cpu")
            self.assertEqual(progress_state["selected_device"], "cpu")
            self.assertEqual(progress_state["requested_device"], "cuda")
            self.assertEqual(progress_state["device_switch_count"], 1)
            self.assertEqual(progress_state["gpu_error"], "simulated CUDA failure")
            self.assertEqual(progress_state["stage"], "complete")
            self.assertTrue((output_dir / "transcript.json").exists())
            self.assertTrue((output_dir / "transcript.srt").exists())
            self.assertTrue((output_dir / "transcript.txt").exists())
            self.assertTrue((output_dir / "transcript.raw.json").exists())
            self.assertTrue((output_dir / "transcript.vad.json").exists())
            self.assertTrue((output_dir / "transcript.quality.json").exists())

    def test_transcribe_from_request_forwards_initial_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            audio_path = temp_root / "input.mp3"
            output_dir = temp_root / "output"
            audio_path.write_bytes(b"fake-audio")
            _FakeModel.last_initial_prompt = None

            payload = {
                "audio_path": str(audio_path),
                "output_dir": str(output_dir),
                "model_name": "medium",
                "language_code": "de",
                "prefer_gpu": False,
                "task_name": "transcribe",
                "initial_prompt": "Brooklands",
                "heartbeat_interval_seconds": 15,
            }

            with mock.patch.dict(
                sys.modules,
                {
                    "whisper": _FakeWhisperModule(),
                    "torch": _FakeCpuTorchModule(),
                },
                clear=False,
            ):
                result = whisper_local.transcribe_from_request(payload)

            self.assertEqual(result["device"], "cpu")
            self.assertEqual(_FakeModel.last_initial_prompt, "Brooklands")
            self.assertTrue((output_dir / "transcript.json").exists())


# A short fragment the decoder was unsure about: on its own it is filtered as
# "combined_low_speech_information"; next to real narration it is rescued (119).
_UNSURE_FRAGMENT = {
    "start": 0.4,
    "end": 0.9,
    "text": "alpha bravo",
    "no_speech_prob": 0.5,
    "avg_logprob": -0.9,
    "compression_ratio": 0.5,
}
_REAL_NARRATION = {
    "start": 0.4,
    "end": 1.1,
    "text": "the limiter light should stay on",
    "no_speech_prob": 0.05,
    "avg_logprob": -0.2,
    "compression_ratio": 1.2,
}


class _ScriptedSparseModel:
    """Returns a scripted segment list per sparse chunk, in chunk order."""

    script: list[list[dict[str, object]]] = []

    def transcribe(self, audio_path: str, **_kwargs: object) -> dict[str, object]:
        name = Path(audio_path).name  # chunk-0001.wav, chunk-0002.wav, ...
        index = int(name.split("-")[1].split(".")[0]) - 1
        segments = self.script[index] if index < len(self.script) else []
        return {"language": "en", "segments": [dict(item) for item in segments]}


class _ScriptedSparseWhisper:
    @staticmethod
    def load_model(model_name: str, device: str) -> _ScriptedSparseModel:
        return _ScriptedSparseModel()


def _write_two_bursts_wav(path: Path, *, sample_rate: int = 16000) -> None:
    """Eight seconds with sound at 2.0-3.2 s and 5.0-6.0 s, so sparse mode finds two chunks."""

    import math
    import wave
    from array import array

    samples = array("h")
    for index in range(8 * sample_rate):
        seconds = index / sample_rate
        active = 2.0 <= seconds <= 3.2 or 5.0 <= seconds <= 6.0
        samples.append(int(8000 * math.sin(2 * math.pi * 220 * seconds)) if active else 0)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())


class RescuedSegmentAuditTests(unittest.TestCase):
    """133: a line kept only because it sat next to real speech must be on disk.

    These go through the real writer on purpose. 118 slipped through because its
    test built the input dictionary by hand instead of using the pipeline's own.
    """

    def _transcribe(self, temp_root: Path, script: list[list[dict[str, object]]]) -> tuple[dict, dict, dict]:
        audio_path = temp_root / "narration.wav"
        output_dir = temp_root / "output"
        _write_two_bursts_wav(audio_path)
        _ScriptedSparseModel.script = script
        payload = {
            "audio_path": str(audio_path),
            "output_dir": str(output_dir),
            "model_name": "medium",
            "language_code": "en",
            "prefer_gpu": False,
            "task_name": "transcribe",
            "narration_speech_mode": "Sparse",
            "heartbeat_interval_seconds": 15,
        }
        with mock.patch.dict(
            sys.modules,
            {"whisper": _ScriptedSparseWhisper(), "torch": _FakeCpuTorchModule()},
            clear=False,
        ):
            whisper_local.transcribe_from_request(payload)
        read = lambda name: json.loads((output_dir / name).read_text(encoding="utf-8"))  # noqa: E731
        return read("transcript.json"), read("transcript.raw.json"), read("transcript.quality.json")

    def test_fragment_next_to_real_narration_is_recorded_as_rescued(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, audit, quality = self._transcribe(
                Path(temp_dir), [[_REAL_NARRATION], [_UNSURE_FRAGMENT]]
            )

        self.assertEqual([item["text"] for item in delivered["segments"]], [_REAL_NARRATION["text"], "alpha bravo"])
        # The delivered transcript keeps its four-key shape.
        self.assertEqual(set(delivered["segments"][1]), {"id", "start", "end", "text"})
        self.assertEqual(audit["filtered_segments"], [])

        self.assertEqual(len(audit["rescued_segments"]), 1)
        rescued = audit["rescued_segments"][0]
        self.assertEqual(rescued["chunk_index"], 2)
        self.assertEqual(rescued["attempt"], 1)
        self.assertEqual(rescued["reason"], "low_information_kept_near_narration")
        self.assertEqual(rescued["segment"]["text"], "alpha bravo")
        for key in ("no_speech_prob", "avg_logprob", "compression_ratio"):
            self.assertIn(key, rescued["segment"])
        # Source-recording time: the second burst starts at 5.0 s, so the fragment
        # sits inside that chunk, not at the 0.4 s the decoder reported.
        chunk = next(item for item in audit["raw_attempts"] if item["chunk_index"] == 2)
        self.assertGreaterEqual(rescued["segment"]["start"], chunk["interval"]["start_seconds"])
        self.assertLessEqual(rescued["segment"]["start"], chunk["interval"]["end_seconds"])
        self.assertGreater(rescued["segment"]["start"], 4.0)
        self.assertEqual(rescued["segment"]["start"], delivered["segments"][1]["start"])
        self.assertEqual(quality["rescued_segment_count"], 1)

    def test_isolated_fragment_is_dropped_and_nothing_is_recorded_as_rescued(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, audit, quality = self._transcribe(Path(temp_dir), [[_UNSURE_FRAGMENT], []])

        self.assertEqual(delivered["segments"], [])
        self.assertEqual(audit["rescued_segments"], [])
        self.assertEqual([item["reason"] for item in audit["filtered_segments"]], ["combined_low_speech_information"])
        self.assertEqual(quality["rescued_segment_count"], 0)

    def test_a_recording_transcribed_without_the_sparse_filter_lists_nothing_as_rescued(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            audio_path = temp_root / "input.mp3"
            output_dir = temp_root / "output"
            audio_path.write_bytes(b"fake-audio")
            payload = {
                "audio_path": str(audio_path),
                "output_dir": str(output_dir),
                "model_name": "medium",
                "language_code": "en",
                "prefer_gpu": False,
                "task_name": "transcribe",
                "heartbeat_interval_seconds": 15,
            }
            with mock.patch.dict(
                sys.modules,
                {"whisper": _FakeWhisperModule(), "torch": _FakeCpuTorchModule()},
                clear=False,
            ):
                whisper_local.transcribe_from_request(payload)
            audit = json.loads((output_dir / "transcript.raw.json").read_text(encoding="utf-8"))
            quality = json.loads((output_dir / "transcript.quality.json").read_text(encoding="utf-8"))

        self.assertEqual(audit["rescued_segments"], [])
        self.assertEqual(quality["rescued_segment_count"], 0)



class _ScriptedContinuousModel:
    segments: list[dict[str, object]] = []

    def transcribe(self, audio_path: str, **_kwargs: object) -> dict[str, object]:
        return {"language": "en", "segments": [dict(item) for item in self.segments],
                "text": " ".join(str(item["text"]) for item in self.segments)}


class _ScriptedContinuousWhisper:
    @staticmethod
    def load_model(model_name: str, device: str) -> _ScriptedContinuousModel:
        return _ScriptedContinuousModel()


_LOOP_LINE = "So, so, um, well, a sample phrase, a sample phrase, a sample phrase"


class InventedLineFilterTests(unittest.TestCase):
    """199: Whisper's invented lines are dropped in every transcription mode, and listed."""

    def _payload(self, temp_root: Path, mode: str) -> dict[str, object]:
        audio_path = temp_root / "narration.wav"
        _write_two_bursts_wav(audio_path)
        return {
            "audio_path": str(audio_path),
            "output_dir": str(temp_root / "output"),
            "model_name": "medium",
            "language_code": "en",
            "prefer_gpu": False,
            "task_name": "transcribe",
            "narration_speech_mode": mode,
            "heartbeat_interval_seconds": 15,
        }

    def _read(self, temp_root: Path, name: str) -> dict:
        return json.loads((temp_root / "output" / name).read_text(encoding="utf-8"))

    def test_continuous_mode_drops_invented_lines_but_never_quiet_narration(self) -> None:
        _ScriptedContinuousModel.segments = [
            {"id": 0, "start": 1.0, "end": 2.0, "text": "the limiter light should stay on",
             "no_speech_prob": 0.1, "avg_logprob": -0.2, "compression_ratio": 1.1},
            {"id": 1, "start": 3.0, "end": 4.0, "text": "Thanks for watching!",
             "no_speech_prob": 0.1, "avg_logprob": -0.2, "compression_ratio": 1.1},
            {"id": 2, "start": 5.0, "end": 6.0, "text": _LOOP_LINE,
             "no_speech_prob": 0.0, "avg_logprob": -0.3, "compression_ratio": 1.9},
            # Quiet narration scores like noise; in Continuous mode numbers alone never drop it.
            {"id": 3, "start": 7.0, "end": 7.5, "text": "pit board",
             "no_speech_prob": 0.7, "avg_logprob": -0.9, "compression_ratio": 0.6},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict(sys.modules, {"whisper": _ScriptedContinuousWhisper(), "torch": _FakeCpuTorchModule()},
                                 clear=False):
                whisper_local.transcribe_from_request(self._payload(root, "Continuous"))
            delivered, audit = self._read(root, "transcript.json"), self._read(root, "transcript.raw.json")
        self.assertEqual([item["text"] for item in delivered["segments"]],
                         ["the limiter light should stay on", "pit board"])
        self.assertEqual([(item["reason"], item["segment"]["text"]) for item in audit["filtered_segments"]],
                         [("known_filler_phrase", "Thanks for watching!"), ("phrase_loop", _LOOP_LINE)])
        self.assertIn("pit board", delivered["text"])
        self.assertNotIn("sample phrase", delivered["text"])

    def test_a_loop_split_over_two_sparse_chunks_is_dropped(self) -> None:
        line = {"start": 0.2, "end": 0.9, "text": "a sample phrase, a sample phrase",
                "no_speech_prob": 0.0, "avg_logprob": -0.3, "compression_ratio": 1.4}
        _ScriptedSparseModel.script = [[_REAL_NARRATION, dict(line)], [dict(line)]]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict(sys.modules, {"whisper": _ScriptedSparseWhisper(), "torch": _FakeCpuTorchModule()},
                                 clear=False):
                whisper_local.transcribe_from_request(self._payload(root, "Sparse"))
            delivered, audit = self._read(root, "transcript.json"), self._read(root, "transcript.raw.json")
        self.assertEqual([item["text"] for item in delivered["segments"]], [_REAL_NARRATION["text"]])
        # The second chunk is thrown out for repeating the first; the first chunk's half of the
        # loop then goes too, because together they say the phrase four times.
        self.assertEqual([item["reason"] for item in audit["rejected_chunks"]], ["repetition_persisted_after_retry"])
        self.assertEqual([item["reason"] for item in audit["filtered_segments"]], ["phrase_loop"])


class WordsToSpellRightCorrectTheTranscriptTests(unittest.TestCase):
    """206: a caller that asks for it gets the operator's corrections in the transcript itself.

    Full Review, Transcript Only and Review Media Inbox write their transcripts here and nowhere
    corrected them. What Whisper wrote is kept in the audit, so nothing is lost.
    """

    def _transcribe(self, root: Path, **extra: object) -> tuple[dict, dict, dict]:
        audio_path = root / "input.mp3"
        audio_path.write_bytes(b"fake-audio")
        _ScriptedContinuousModel.segments = [
            {"id": 0, "start": 1.0, "end": 2.0, "text": " This is the first brook lands livery.",
             "no_speech_prob": 0.1, "avg_logprob": -0.2, "compression_ratio": 1.1},
            {"id": 1, "start": 3.0, "end": 4.0, "text": " The pit board is fine.",
             "no_speech_prob": 0.1, "avg_logprob": -0.2, "compression_ratio": 1.1},
        ]
        payload = {"audio_path": str(audio_path), "output_dir": str(root / "output"), "model_name": "medium",
                   "language_code": "en", "prefer_gpu": False, "task_name": "transcribe",
                   "heartbeat_interval_seconds": 15, **extra}
        with mock.patch.dict(sys.modules, {"whisper": _ScriptedContinuousWhisper(), "torch": _FakeCpuTorchModule()},
                             clear=False):
            whisper_local.transcribe_from_request(payload)
        read = lambda name: json.loads((root / "output" / name).read_text(encoding="utf-8"))  # noqa: E731
        return read("transcript.json"), read("transcript.raw.json"), read("transcript.quality.json")

    def test_the_transcript_is_corrected_and_what_whisper_wrote_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, audit, quality = self._transcribe(Path(temp_dir), glossary_entries=["Brooklands=brook lands"])
        self.assertEqual([item["text"].strip() for item in delivered["segments"]],
                         ["This is the first Brooklands livery.", "The pit board is fine."])
        self.assertIn("Brooklands", delivered["text"])
        self.assertEqual([(item["before"].strip(), item["after"].strip()) for item in audit["glossary_corrections"]],
                         [("This is the first brook lands livery.", "This is the first Brooklands livery.")])
        self.assertEqual(quality["glossary_correction_count"], 1)

    def test_without_the_words_nothing_is_corrected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, audit, _quality = self._transcribe(Path(temp_dir))
        self.assertIn("brook lands", delivered["segments"][0]["text"])
        self.assertEqual(audit.get("glossary_corrections", []), [])


class _PromptRecordingSparseModel:
    """Scripted per chunk and per attempt; records the words each call was given."""

    script: dict[int, list[list[dict[str, object]]]] = {}
    calls: list[tuple[int, object]] = []

    def transcribe(self, audio_path: str, **kwargs: object) -> dict[str, object]:
        chunk = int(Path(audio_path).name.split("-")[1].split(".")[0])
        attempt = sum(1 for index, _prompt in self.calls if index == chunk)
        self.calls.append((chunk, kwargs.get("initial_prompt")))
        answers = self.script.get(chunk) or [[]]
        segments = answers[min(attempt, len(answers) - 1)]
        return {"language": "en", "segments": [dict(item) for item in segments]}


class _PromptRecordingSparseWhisper:
    @staticmethod
    def load_model(model_name: str, device: str) -> _PromptRecordingSparseModel:
        return _PromptRecordingSparseModel()


class WordsSurviveTheRetryTests(unittest.TestCase):
    """201: the words to spell right reach Whisper on the retry too.

    The retry used to drop them, so a chunk Whisper looped on came back without
    the operator's words. The words are only left out as a last attempt, when
    the retry with them loops as well.
    """

    WORDS = "Preferred terminology: Brooklands, iRacing"
    LOOP = {"start": 0.2, "end": 0.9, "text": "a sample phrase, a sample phrase",
            "no_speech_prob": 0.0, "avg_logprob": -0.3, "compression_ratio": 1.4}
    CLEAN = {"start": 0.2, "end": 0.9, "text": "Brooklands dropped the session",
             "no_speech_prob": 0.05, "avg_logprob": -0.2, "compression_ratio": 1.1}

    def _transcribe(self, root: Path, chunk_two: list[list[dict[str, object]]]) -> tuple[dict, dict]:
        audio_path = root / "narration.wav"
        _write_two_bursts_wav(audio_path)
        _PromptRecordingSparseModel.script = {1: [[_REAL_NARRATION, dict(self.LOOP)]], 2: chunk_two}
        _PromptRecordingSparseModel.calls = []
        payload = {
            "audio_path": str(audio_path),
            "output_dir": str(root / "output"),
            "model_name": "medium",
            "language_code": "en",
            "prefer_gpu": False,
            "task_name": "transcribe",
            "narration_speech_mode": "Sparse",
            "initial_prompt": self.WORDS,
            "heartbeat_interval_seconds": 15,
        }
        with mock.patch.dict(sys.modules, {"whisper": _PromptRecordingSparseWhisper(), "torch": _FakeCpuTorchModule()},
                             clear=False):
            whisper_local.transcribe_from_request(payload)
        read = lambda name: json.loads((root / "output" / name).read_text(encoding="utf-8"))  # noqa: E731
        return read("transcript.json"), read("transcript.raw.json")

    def test_the_retry_keeps_the_words(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, _audit = self._transcribe(Path(temp_dir), [[dict(self.LOOP)], [dict(self.CLEAN)]])
        chunk_two = [prompt for chunk, prompt in _PromptRecordingSparseModel.calls if chunk == 2]
        self.assertEqual(chunk_two, [self.WORDS, self.WORDS])
        self.assertIn(self.CLEAN["text"], [item["text"] for item in delivered["segments"]])

    def test_the_words_are_left_out_only_when_the_retry_with_them_loops_too(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, audit = self._transcribe(
                Path(temp_dir), [[dict(self.LOOP)], [dict(self.LOOP)], [dict(self.CLEAN)]]
            )
        chunk_two = [prompt for chunk, prompt in _PromptRecordingSparseModel.calls if chunk == 2]
        self.assertEqual(chunk_two, [self.WORDS, self.WORDS, None])
        self.assertIn(self.CLEAN["text"], [item["text"] for item in delivered["segments"]])
        self.assertEqual(
            [item["attempt"] for item in audit["raw_attempts"] if item["chunk_index"] == 2], [1, 2, 3]
        )
        self.assertEqual(audit["rejected_chunks"], [])

    def test_a_chunk_that_loops_every_time_is_still_thrown_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivered, audit = self._transcribe(Path(temp_dir), [[dict(self.LOOP)]])
        self.assertEqual([item["text"] for item in delivered["segments"]], [_REAL_NARRATION["text"]])
        self.assertEqual([item["reason"] for item in audit["rejected_chunks"]], ["repetition_persisted_after_retry"])


if __name__ == "__main__":
    unittest.main()
