"""Whisper never starts FFmpeg itself: every feature hands it the sound the app has already read (H2 of the Wave
I-A review).

Given a file name, Whisper decodes the sound by starting the bare command ``ffmpeg`` (openai-whisper 20250625,
``whisper/audio.py``: "Requires the ffmpeg CLI in PATH"), which Windows looks up on PATH. On a PC that has only the
FFmpeg Media Manglers ships, or one chosen in Settings that is not on PATH, voice-track detection, the narration
cross-check, the raw bin scan, the Deep scan and the AI Video Editor's quick passes then failed; on a PC with another
FFmpeg on PATH, Whisper quietly used that one. Now the app reads the 16 kHz mono WAV it wrote itself, sample for
sample what Whisper's own decode gives, and any other sound through the FFmpeg the app resolved. These tests run
on a PATH with no FFmpeg at all, with a Whisper stand-in that decodes a file name exactly as Whisper does.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from media_manglers.core import voice_track  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from tests.whisper_test_models import checked_whisper  # noqa: E402

# An FFmpeg on this PC before PATH is emptied, to prove the app's own reading matches Whisper's decode exactly.
REAL_FFMPEG = shutil.which("ffmpeg") or ""
WINDOWS = os.environ.get("SystemRoot", r"C:\Windows")
NO_FFMPEG_PATH = os.pathsep.join([str(Path(WINDOWS) / "System32"), WINDOWS])


def whisper_load_audio(file: str, sr: int = 16000) -> np.ndarray:
    """Whisper's own decode of a file name (openai-whisper 20250625, ``whisper.audio.load_audio``): it starts the
    bare command ``ffmpeg``, found on PATH."""

    cmd = ["ffmpeg", "-nostdin", "-threads", "0", "-i", file, "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le",
           "-ar", str(sr), "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


class _Model:
    received: list[object] = []

    def transcribe(self, audio: object, **_kwargs: object) -> dict[str, object]:
        _Model.received.append(audio)
        if isinstance(audio, str):
            audio = whisper_load_audio(audio)
        seconds = len(audio) / 16000.0  # type: ignore[arg-type]
        return {"language": "en", "text": " the brake bias is too far forward",
                "segments": [{"id": 0, "start": 0.0, "end": round(seconds, 2),
                              "text": " the brake bias is too far forward", "no_speech_prob": 0.01,
                              "avg_logprob": -0.2, "compression_ratio": 1.1}]}


class _Whisper:
    @staticmethod
    def load_model(_name: str, device: str = "cpu", **_kwargs: object) -> _Model:
        return _Model()


def write_wav(path: Path, seconds: float = 3.0, rate: int = 16000, channels: int = 1) -> Path:
    """A burst of sound in the middle second, quiet around it, as speech between pauses."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        frames = bytearray()
        for index in range(int(seconds * rate)):
            loud = 1.0 <= index / rate < 2.0
            value = int((12000 if loud else 20) * math.sin(2 * math.pi * 440 * index / rate))
            frames += struct.pack("<h", value) * channels
        writer.writeframes(bytes(frames))
    return path


class WhisperNeverStartsFfmpegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wav = write_wav(self.root / "work" / "narration.wav")
        _Model.received = []
        self.patches = [mock.patch.dict(os.environ, {"PATH": NO_FFMPEG_PATH}),
                        mock.patch.dict(sys.modules, {"whisper": checked_whisper(_Whisper())})]
        for patch in self.patches:
            patch.start()
        self.assertIsNone(shutil.which("ffmpeg"), "this PATH has no FFmpeg")

    def tearDown(self) -> None:
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def test_voice_track_detection_listens_with_no_ffmpeg_on_path(self) -> None:
        # Voice-track detection, the cross-check, the raw bin scan and the editor's quick passes all listen this way.
        transcribe = voice_track.whisper_transcriber("base.en", False, "en")
        segments = transcribe(self.wav)
        self.assertEqual([item["text"] for item in segments], [" the brake bias is too far forward"])
        self.assertTrue(all(isinstance(item, np.ndarray) for item in _Model.received), "Whisper got the sound")
        self.assertEqual(len(_Model.received[0]), 3 * 16000)

    def test_the_deep_scan_request_transcribes_with_no_ffmpeg_on_path(self) -> None:
        # The raw bin's Deep scan sends no FFmpeg folder at all; both speech modes.
        for mode in ("Sparse", "Continuous"):
            with self.subTest(mode=mode):
                _Model.received = []
                output = self.root / f"out-{mode}"
                result = whisper_local.transcribe_from_request(
                    {"audio_path": str(self.wav), "output_dir": str(output), "model_name": "base.en",
                     "language_code": "en", "prefer_gpu": False, "narration_speech_mode": mode})
                self.assertTrue(Path(str(result["json_path"])).is_file(), result)
                self.assertTrue(_Model.received)
                self.assertTrue(all(isinstance(item, np.ndarray) for item in _Model.received))
                written = json.loads(Path(str(result["json_path"])).read_text(encoding="utf-8"))
                self.assertIn("brake bias", written["text"])

    @unittest.skipUnless(REAL_FFMPEG, "needs an FFmpeg on this PC to compare with Whisper's own decode")
    def test_the_sound_is_sample_for_sample_what_whispers_own_decode_gives(self) -> None:
        mine = whisper_local.whisper_audio(self.wav)
        with mock.patch.dict(os.environ, {"PATH": str(Path(REAL_FFMPEG).parent) + os.pathsep + NO_FFMPEG_PATH}):
            theirs = whisper_load_audio(str(self.wav))
        self.assertEqual(mine.dtype, theirs.dtype)
        self.assertTrue(np.array_equal(mine, theirs), "the transcript cannot change")

    @unittest.skipUnless(REAL_FFMPEG, "needs an FFmpeg on this PC")
    def test_other_sound_is_decoded_by_the_ffmpeg_the_app_resolved_never_one_from_path(self) -> None:
        stereo = write_wav(self.root / "work" / "stereo-44k.wav", rate=44100, channels=2)
        sound = whisper_local.whisper_audio(stereo, REAL_FFMPEG)
        self.assertEqual(len(sound), 3 * 16000)
        with self.assertRaises(FileNotFoundError):
            whisper_local.whisper_audio(stereo, "")  # nothing resolved and none on PATH: never a guess


if __name__ == "__main__":
    unittest.main()
