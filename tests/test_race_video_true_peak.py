"""A finished render stays under the -1 dBTP limit even when encoding raises its peaks (170).

Encoding the sound to AAC after it is levelled can push the true peak up by half a decibel or more;
in testing on a real race, two editors' first previews failed the technical check at -0.8 dBTP.
Here the levelling is allowed to put peaks right at 0 dB, so the encoded file must be measured and
its sound encoded again a little quieter.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.race_video import render  # noqa: E402
from media_manglers.core.race_video.project import add_version, create_project  # noqa: E402
from media_manglers.core.race_video.qc import check_video  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}
# A quiet hum with short, very loud clicks: levelled loudness pulls the clicks right up to the ceiling.
SPIKY = "aevalsrc='0.02*sin(2*PI*200*t)+0.98*sin(2*PI*2500*t)*lt(mod(t,0.5),0.004)':s=48000:d=20"


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class TruePeakTests(unittest.TestCase):
    def test_a_render_is_brought_under_the_peak_limit_after_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "spiky.mkv"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=20",
                            "-f", "lavfi", "-i", SPIKY, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                            "-c:a", "pcm_s16le", "-t", "20", str(source)], check=True)
            project = create_project(root / "out", source, "spiky")
            timeline = {"schema": SCHEMA, "source": str(source), "source_layout": LAYOUT,
                        "tracks": {"voice": 0, "game": 1},
                        "scenes": [{"id": "s01", "beat": "x", "reason": "test", "in": 1.0, "out": 15.0,
                                    "view": "center", "audio": {"voice": 1.0, "game": 0.0}}]}
            version = add_version(project, timeline, source_duration=20.0, audio_streams=2)
            options = render.RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, encoder="x264", hwaccel="none")
            with patch.dict(render.LOUDNESS, {"TP": 0.0}):
                report = render.render_version(project, version, "preview", options)
            qc = check_video(Path(report["output"]), "preview", expected_duration=report["expected_duration"],
                             ffmpeg=FFMPEG, ffprobe=FFPROBE)
        peak_check = next(c for c in qc["checks"] if c["check"].startswith("true peak"))
        self.assertTrue(peak_check["pass"], peak_check["detail"])
        self.assertGreater(report["loudness_measured"]["lowered_after_encoding_db"], 0,
                           "the encoded file was measured and its sound lowered")
        # 226: what the report says was lowered is what the file was encoded with, and it says how often.
        self.assertEqual(report["loudness"]["lowered_db_applied"], report["loudness_measured"]["lowered_after_encoding_db"])
        self.assertGreaterEqual(report["loudness"]["attempts"], 2)

    def test_after_the_last_try_the_report_says_only_the_lowering_that_was_applied(self) -> None:
        # 226 (161.3): every try is measured as over the ceiling here. The third try is encoded 2.6 dB
        # quieter (1.3 dB more each time); the 3.9 dB a fourth try would use is never applied, so it must
        # not be reported. The file itself shows what was applied: 2.6 dB quieter than a normal render.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "steady.mkv"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=12",
                            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=12",
                            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.2:sample_rate=48000:duration=12",
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                            "-c:a", "flac", "-t", "12", str(source)], check=True)
            project = create_project(root / "out", source, "steady")
            timeline = {"schema": SCHEMA, "source": str(source), "source_layout": LAYOUT,
                        "tracks": {"voice": 0, "game": 1},
                        "scenes": [{"id": "s01", "beat": "x", "reason": "test", "in": 1.0, "out": 9.0,
                                    "view": "center", "audio": {"voice": 0.5, "game": 1.0}}]}
            version = add_version(project, timeline, source_duration=12.0, audio_streams=2)
            options = render.RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, encoder="x264", hwaccel="none")
            normal = render.render_version(project, version, "preview", options)
            normal_loudness, _peak = render.measure_loudness(FFMPEG, Path(normal["output"]))
            real = render.measure_loudness

            def always_too_loud(ffmpeg, path):
                integrated, _peak = real(ffmpeg, path)
                return integrated, 0.0

            with patch.object(render, "measure_loudness", side_effect=always_too_loud):
                report = render.render_version(project, version, "preview", options)
            quieter, _peak = real(FFMPEG, Path(report["output"]))
        self.assertEqual(normal["loudness"]["lowered_db_applied"], 0.0, normal["loudness"])
        self.assertEqual(report["loudness"]["attempts"], 3)
        self.assertEqual(report["loudness"]["lowered_db_applied"], 2.6)
        self.assertEqual(report["loudness_measured"]["lowered_after_encoding_db"], 2.6)
        self.assertAlmostEqual(normal_loudness - quieter, 2.6, delta=0.3)


if __name__ == "__main__":
    unittest.main()
