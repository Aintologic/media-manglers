"""267: the AI Video Editor's project decides which recording it edits, never the AI editor's path.

Two real recordings with the same file name sit in two folders, made with FFmpeg: the project's own and
another one of the same length and tracks, so the other one would render without complaint. The AI
editor's timeline names a source path; add-version, render and export use the project's own
recording, and a path that is not it is refused unless the shared identity rule
(``recording_identity``) confirms the same content. A file name alone never decides it.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import recording_identity  # noqa: E402
from media_manglers.core.race_video.library import export_version  # noqa: E402
from media_manglers.core.race_video.project import (  # noqa: E402
    add_version,
    create_project,
    load_version,
    read_json,
    version_dir,
)
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.requests import add_version_from_request, render_from_request  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}


def make_recording(path: Path, centre: str) -> Path:
    """Twelve seconds of three camera panels with a voice track and a game track; ``centre`` is the
    FFmpeg test picture of the middle panel, so two recordings can differ in content only."""

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12",
        "-f", "lavfi", "-i", f"{centre}=s=320x180:r=30:d=12",
        "-f", "lavfi", "-i", "smptebars=s=320x180:r=30:d=12",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration=12",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


def timeline(source: Path) -> dict:
    return {
        "schema": SCHEMA,
        "source": str(source),
        "source_layout": LAYOUT,
        "tracks": {"voice": 0, "game": 1},
        "scenes": [
            {"id": "s01", "beat": "hook", "reason": "test", "in": 0.5, "out": 3.5, "view": "center",
             "audio": {"voice": 1.0, "game": 0.5}},
            {"id": "s02", "beat": "end", "reason": "test", "in": 6.0, "out": 9.0, "view": "full",
             "audio": {"voice": 0.0, "game": 1.0}, "transition_in": "dissolve", "transition_dur": 0.5},
        ],
    }


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class RecordingAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.recording = make_recording(root / "drive-a" / "race.mkv", "testsrc")
        # The same file name, another folder, another race: the same length and tracks.
        cls.other = make_recording(root / "drive-b" / "race.mkv", "rgbtestsrc")
        cls.options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, encoder="x264", hwaccel="none")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def setUp(self) -> None:
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)
        self.project = create_project(self.root / "out", self.recording, "race")

    def tearDown(self) -> None:
        self.work.cleanup()

    def _version_naming(self, source: Path) -> int:
        """A version stored for the project's own recording whose timeline was then changed to name
        ``source``: a timeline.json edited by hand, or a version stored before 267."""

        number = add_version(self.project, timeline(self.recording), source_duration=12.0, audio_streams=2)
        path = version_dir(self.project, number) / "timeline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source"] = str(source)
        path.write_text(json.dumps(data), encoding="utf-8")
        return number

    def test_the_two_recordings_really_differ_only_in_content(self) -> None:
        self.assertEqual(self.recording.name, self.other.name)
        self.assertNotEqual(recording_identity.sampled_sha256_file(self.recording),
                            recording_identity.sampled_sha256_file(self.other))

    def test_add_version_refuses_another_recording_with_the_same_name(self) -> None:
        before = (self.project / "project.json").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different recording") as caught:
            add_version(self.project, timeline(self.other), source_duration=12.0, audio_streams=2)
        self.assertIn(str(self.recording), str(caught.exception), "the refusal names the project's recording")
        self.assertEqual((self.project / "project.json").read_text(encoding="utf-8"), before)
        self.assertFalse(version_dir(self.project, 1).exists())

    def test_the_add_version_command_refuses_it_too(self) -> None:
        with self.assertRaisesRegex(ValueError, "different recording"):
            add_version_from_request({"project": str(self.project), "timeline": timeline(self.other),
                                      "ffprobe": FFPROBE})
        self.assertFalse(version_dir(self.project, 1).exists())

    def test_render_refuses_a_version_naming_another_recording(self) -> None:
        number = self._version_naming(self.other)
        with self.assertRaisesRegex(ValueError, "different recording"):
            render_version(self.project, number, "preview", self.options)
        with self.assertRaisesRegex(ValueError, "different recording"):
            render_from_request({"project": str(self.project), "version": number, "profile": "preview",
                                 "ffmpeg": FFMPEG, "ffprobe": FFPROBE, "encoder": "x264", "hwaccel": "none"})
        self.assertFalse((version_dir(self.project, number) / "renders" / "preview.mp4").exists())

    def test_export_refuses_a_version_naming_another_recording(self) -> None:
        number = self._version_naming(self.other)
        with self.assertRaisesRegex(ValueError, "different recording"):
            export_version(self.project, number, self.options)
        self.assertEqual(list((self.project / "export").iterdir()), [])
        self.assertFalse((version_dir(self.project, number) / "renders" / "final.mp4").exists())

    def test_a_copy_with_the_same_content_is_accepted_and_the_version_names_the_project_s_recording(self) -> None:
        copy = self.root / "drive-c" / "race.mkv"
        copy.parent.mkdir()
        shutil.copyfile(self.recording, copy)
        number = add_version(self.project, timeline(copy), source_duration=12.0, audio_streams=2)
        self.assertEqual(load_version(self.project, number)["source"], str(self.recording),
                         "a stored version always names the project's own recording")

    def test_another_spelling_of_the_project_s_own_path_is_the_same_recording(self) -> None:
        spelled = str(self.recording).upper().replace("\\", "/")
        number = add_version(self.project, timeline(Path(spelled)) | {"source": spelled}, source_duration=12.0,
                             audio_streams=2)
        self.assertEqual(load_version(self.project, number)["source"], str(self.recording))

    def test_a_render_reads_the_project_s_recording_and_passes_its_check(self) -> None:
        number = add_version(self.project, timeline(self.recording), source_duration=12.0, audio_streams=2)
        result = render_from_request({"project": str(self.project), "version": number, "profile": "preview",
                                      "ffmpeg": FFMPEG, "ffprobe": FFPROBE, "encoder": "x264", "hwaccel": "none"})
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])

    def test_a_file_of_the_same_name_is_not_taken_for_a_recording_that_is_gone(self) -> None:
        # The project's recording is no longer where the project says; a file of the same name elsewhere
        # cannot be checked against it, so it is refused, never taken by its name.
        moved_root = Path(tempfile.mkdtemp(dir=self.root))
        project_recording = make_recording(moved_root / "before" / "race.mkv", "testsrc")
        project = create_project(self.root / "out", project_recording, "gone")
        moved = moved_root / "after" / "race.mkv"
        moved.parent.mkdir()
        project_recording.rename(moved)
        with self.assertRaisesRegex(ValueError, "no longer there"):
            add_version(project, timeline(moved), source_duration=12.0, audio_streams=2)
        self.assertEqual(read_json(project / "project.json")["versions"], [])


class SameContentRuleTests(unittest.TestCase):
    """The shared rule applied to two files on disk: the size and sampled hash propose, the full hash confirms."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _file(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_the_same_bytes_are_the_same_content(self) -> None:
        data = bytes(range(256)) * 2048
        self.assertTrue(recording_identity.same_content(self._file("a.mkv", data), self._file("b.mkv", data)))

    def test_one_byte_outside_the_sampled_pieces_makes_another_recording(self) -> None:
        # The sampled hash cannot see this byte; only the full hash can, and it decides.
        data = bytearray(bytes(range(256)) * 4096)
        first = self._file("a.mkv", bytes(data))
        data[300_000] ^= 0xFF
        second = self._file("b.mkv", bytes(data))
        self.assertEqual(recording_identity.sampled_sha256_file(first), recording_identity.sampled_sha256_file(second))
        self.assertFalse(recording_identity.same_content(first, second))

    def test_another_size_is_another_recording(self) -> None:
        self.assertFalse(recording_identity.same_content(self._file("a.mkv", b"x" * 1000),
                                                         self._file("b.mkv", b"x" * 1001)))


if __name__ == "__main__":
    unittest.main()
