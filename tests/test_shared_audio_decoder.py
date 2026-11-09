"""214: one decoder for the narration audio every feature transcribes.

The backend made its own narration WAV (Export-TranscriptSourceWav) beside the shared decoder in
voice_track that voice detection and Review Media Inbox use. The backend now asks the shared one;
these pin that its WAV is byte-for-byte what the backend made, and how a stopped decode ends.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import voice_track  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _two_tracks(path: Path) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=700:duration=3",
                    "-map", "0:a", "-map", "1:a", "-c:a", "aac", str(path)], check=True)
    return path


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class SameAudioTests(unittest.TestCase):
    def test_the_wav_is_the_one_the_backend_made_before(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _two_tracks(root / "two.mkv")
            # The backend's own command until 214, as it was.
            old = root / "old.wav"
            subprocess.run([FFMPEG, "-y", "-i", str(source), "-map", "0:a:1", "-vn", "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le", str(old)], check=True, capture_output=True)
            named = voice_track.extract_wav(FFMPEG, source, root / "named.wav", ffmpeg_map="0:a:1")
            # The clip has no video, so its second audio track is stream 1 of the file.
            absolute = voice_track.extract_wav(FFMPEG, source, root / "absolute.wav", ffmpeg_map="0:1")
            track = voice_track.extract_track(FFMPEG, source, 1, root / "track.wav")
            self.assertEqual({_digest(named), _digest(absolute), _digest(track)}, {_digest(old)})

    def test_the_all_tracks_mix_is_the_backend_mix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _two_tracks(root / "two.mkv")
            old = root / "old-mix.wav"
            subprocess.run([FFMPEG, "-y", "-i", str(source), "-filter_complex",
                            "[0:a:0][0:a:1]amix=inputs=2:duration=longest:normalize=0[aout]", "-map", "[aout]",
                            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(old)], check=True,
                           capture_output=True)
            mix = voice_track.extract_wav(FFMPEG, source, root / "mix.wav", mix_ordinals=[0, 1])
            self.assertEqual(_digest(mix), _digest(old))

    def test_what_a_stopped_run_left_is_cleared_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _two_tracks(root / "two.mkv")
            destination = root / "out" / "voice.wav"
            stale = voice_track.decode_work_dir(destination) / "track.wav"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"left by a stopped run")
            voice_track.extract_wav(FFMPEG, source, destination, ffmpeg_map="0:a:0")
            self.assertTrue(destination.is_file())
            self.assertFalse(voice_track.decode_work_dir(destination).exists())


class RefusalTests(unittest.TestCase):
    def test_a_stream_that_is_not_one_is_refused(self) -> None:
        for value in ("[aout]", "0:a:1 -f", "", None):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):
                    voice_track.extract_wav("ffmpeg", Path(temp) / "x.mkv", Path(temp) / "x.wav", ffmpeg_map=value)


class StoppedDecodeTests(unittest.TestCase):
    STUCK = textwrap.dedent(
        """
        import json, os, sys, time
        args = sys.argv[1:]
        with open(args[-1], 'wb') as partial:
            partial.write(b'RIFF' + bytes(100000))
        with open(RECORD, 'w', encoding='utf-8') as handle:
            json.dump({'pid': os.getpid()}, handle)
        while True:
            print('out_time_us=65000000', flush=True)
            print('progress=continue', flush=True)
            time.sleep(0.2)
        """
    )

    def test_a_stalled_decode_leaves_nothing_and_stops_ffmpeg_behind_its_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = root / "pid.json"
            script = root / "ffmpeg.py"
            script.write_text(f"RECORD = {str(record)!r}\n" + self.STUCK, encoding="utf-8")
            launcher = root / "ffmpeg.cmd"
            launcher.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
            destination = root / "out" / "voice.wav"
            with self.assertRaises(RuntimeError) as raised:
                voice_track.extract_wav(str(launcher), root / "x.mkv", destination, ffmpeg_map="0:a:1", stall_seconds=1.0)
            time.sleep(1.0)
            pid = json.loads(record.read_text(encoding="utf-8"))["pid"]
            alive = str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True,
                                               text=True).stdout
        self.assertIn("01:05 into the recording", str(raised.exception))
        self.assertFalse(destination.exists())
        self.assertFalse(voice_track.decode_work_dir(destination).exists())
        self.assertFalse(alive, "FFmpeg itself is stopped, not only its launcher")


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class PackageMp3Tests(unittest.TestCase):
    """214: the package's MP3 is made by the same decoder, byte-for-byte as the backend made it."""

    def test_the_mp3_is_the_one_the_backend_made_before(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _two_tracks(root / "two.mkv")
            old = root / "old.mp3"
            subprocess.run([FFMPEG, "-y", "-i", str(source), "-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
                            str(old)], check=True, capture_output=True)
            made = voice_track.extract_wav(FFMPEG, source, root / "audio" / "audio.mp3", ffmpeg_map="0:a:0",
                                           audio_format="mp3")
            self.assertEqual(_digest(made), _digest(old))
            self.assertFalse(voice_track.decode_work_dir(made).exists())

    def test_an_unknown_format_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            voice_track.extract_wav(FFMPEG, Path(temp) / "x.mkv", Path(temp) / "x.ogg", ffmpeg_map="0:a:0",
                                    audio_format="ogg")

@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class RequestTests(unittest.TestCase):
    def test_audio_extract_reports_in_the_backend_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _two_tracks(root / "two.mkv")
            progress = root / "progress.json"
            result = voice_track.extract_from_request({
                "ffmpeg_exe": FFMPEG, "source_path": str(source), "output_path": str(root / "voice.wav"),
                "ffmpeg_map": "0:a:1", "progress_state_file_path": str(progress), "duration_seconds": 3,
            })
            state = json.loads(progress.read_text(encoding="utf-8"))
        self.assertGreater(result["bytes"], 1000)
        self.assertEqual(set(state), {"message", "elapsed_seconds", "updated_at_utc"})
        self.assertTrue(state["message"].startswith("Reading the recording's audio"), state)


if __name__ == "__main__":
    unittest.main()
