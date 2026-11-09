from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from media_manglers.core import review_preparation


def _tool(name: str) -> str | None:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidate = (
            Path(local_app_data)
            / "Microsoft"
            / "WinGet"
            / "Links"
            / f"{name}.exe"
        )
        if candidate.is_file():
            return str(candidate)
    return None


FFMPEG = _tool("ffmpeg")
FFPROBE = _tool("ffprobe")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class FrameIntegrityFfmpegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def generate(self, name: str, arguments: list[str]) -> Path:
        target = self.root / name
        run = subprocess.run(
            [
                FFMPEG or "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *arguments,
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(target.is_file())
        return target

    def fixtures(self) -> dict[str, Path]:
        return {
            "normal": self.generate(
                "normal.mkv",
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=10:duration=2",
                    "-c:v",
                    "ffv1",
                ],
            ),
            "short_mismatch": self.generate(
                "short-mismatch.mkv",
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=20:duration=0.08",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=mono",
                    "-t",
                    "0.09",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                ],
            ),
            "subsecond": self.generate(
                "subsecond.mkv",
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=10:duration=0.4",
                    "-c:v",
                    "ffv1",
                ],
            ),
            "variable_rate": self.generate(
                "variable-rate.mkv",
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=30:duration=1",
                    "-vf",
                    r"select=eq(n\,0)+eq(n\,1)+eq(n\,5)+eq(n\,12)+eq(n\,29)",
                    "-fps_mode",
                    "vfr",
                    "-c:v",
                    "ffv1",
                ],
            ),
            "one_frame": self.generate(
                "one-frame.mkv",
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=navy:size=160x90:rate=1:duration=0.1",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "ffv1",
                ],
            ),
        }

    def render_package(self, source: Path, name: str) -> tuple[Path, dict, dict]:
        media = review_preparation.probe_media(FFPROBE or "ffprobe", source)
        package = self.root / "packages" / name
        visuals = review_preparation._render_visuals(
            FFMPEG or "ffmpeg",
            source,
            media,
            package / "visuals",
            include_panel_crops=False,
            ffprobe_exe=FFPROBE or "ffprobe",
        )
        manifest_media = dict(media)
        frame_times = list(manifest_media.pop("video_frame_timestamps"))
        manifest_media["video_timeline_basis"] = {
            "decodable_frame_count": len(frame_times),
            "first_decodable_timestamp_seconds": frame_times[0] if frame_times else None,
            "last_decodable_timestamp_seconds": frame_times[-1] if frame_times else None,
        }
        manifest = {
            "schema_version": 1,
            "source_id": 1,
            "media_metadata": manifest_media,
            "visuals": visuals,
        }
        review_preparation._complete_source_package(package, manifest)
        return package, media, visuals

    def test_generated_normal_short_subsecond_vfr_and_one_frame_packages(self) -> None:
        fixtures = self.fixtures()
        results: dict[str, tuple[Path, dict, dict]] = {}
        for name, source in fixtures.items():
            with self.subTest(name=name):
                package, media, visuals = self.render_package(source, name)
                results[name] = (package, media, visuals)
                validation_count = review_preparation._validate_source_package(package)
                manifest = json.loads(
                    (package / "source-manifest.json").read_text(encoding="utf-8")
                )
                integrity = json.loads(
                    (package / "integrity.json").read_text(encoding="utf-8")
                )
                actual = {
                    str(path.relative_to(package)).replace("\\", "/")
                    for path in package.rglob("*")
                    if path.is_file()
                }
                inventory = {item["path"] for item in integrity["files"]}
                declared = {
                    item["path"] for item in manifest["artifact_inventory"]
                }
                self.assertEqual(actual, inventory | {"integrity.json"})
                self.assertEqual(
                    declared,
                    actual - {"source-manifest.json", "integrity.json"},
                )
                self.assertEqual(validation_count, len(inventory))
                self.assertTrue(integrity["complete"])
                self.assertEqual(
                    [item["ordinal"] for item in visuals["frames"]],
                    list(range(1, visuals["frame_count"] + 1)),
                )
                self.assertEqual(
                    [item["actual_timestamp_seconds"] for item in visuals["frames"]],
                    sorted(
                        item["actual_timestamp_seconds"]
                        for item in visuals["frames"]
                    ),
                )
                for frame in visuals["frames"]:
                    self.assertGreater(frame["size_bytes"], 0)
                    self.assertEqual(len(frame["sha256"]), 64)
                    self.assertEqual((frame["width"], frame["height"]), (160, 90))

        self.assertEqual(results["normal"][2]["frame_count"], 6)
        self.assertEqual(results["short_mismatch"][2]["frame_count"], 2)
        self.assertEqual(results["subsecond"][2]["frame_count"], 4)
        self.assertEqual(results["variable_rate"][2]["frame_count"], 5)
        self.assertEqual(results["one_frame"][2]["frame_count"], 1)

        mismatch_media = results["short_mismatch"][1]
        mismatch_times = mismatch_media["video_frame_timestamps"]
        self.assertGreater(
            float(mismatch_media["duration_seconds"]),
            float(mismatch_times[-1]),
        )
        self.assertEqual(
            review_preparation.timeline_timestamps(
                float(mismatch_media["duration_seconds"]),
                list(mismatch_times),
            ),
            list(mismatch_times),
        )

        variable_times = results["variable_rate"][1]["video_frame_timestamps"]
        spacings = {
            round(variable_times[index] - variable_times[index - 1], 6)
            for index in range(1, len(variable_times))
        }
        self.assertGreater(len(spacings), 1)

    def test_generated_source_forced_partial_render_never_completes(self) -> None:
        source = self.generate(
            "forced-partial.mkv",
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=10:duration=1",
                "-c:v",
                "ffv1",
            ],
        )
        media = review_preparation.probe_media(FFPROBE or "ffprobe", source)
        output = self.root / "forced-partial"
        original_run = review_preparation._run
        render_count = 0

        def force_second_frame_missing(
            command: list[str],
            *,
            timeout: int = 300,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal render_count
            if "showinfo" in command:
                render_count += 1
                if render_count == 2:
                    requested = command[command.index("-ss") + 1]
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="",
                        stderr=f"showinfo pts_time:{requested}",
                    )
            return original_run(command, timeout=timeout)

        with (
            mock.patch.object(
                review_preparation,
                "_run",
                side_effect=force_second_frame_missing,
            ),
            self.assertRaisesRegex(RuntimeError, "did not create a regular image"),
        ):
            review_preparation._render_visuals(
                FFMPEG or "ffmpeg",
                source,
                media,
                output,
                include_panel_crops=False,
                ffprobe_exe=FFPROBE or "ffprobe",
            )
        self.assertTrue((output / "frames" / "frame-001.jpg").is_file())
        self.assertFalse((output / "frames" / "frame-002.jpg").exists())
        self.assertFalse((output / "timeline-index.json").exists())
        self.assertFalse((output.parent / "source-manifest.json").exists())
        self.assertFalse((output.parent / "integrity.json").exists())


if __name__ == "__main__":
    unittest.main()
