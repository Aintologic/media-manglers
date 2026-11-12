"""Installer plan, Stage 5: the FFmpeg bundled in runtime\\ffmpeg is the pinned build and does what the app needs.

The build checks the real bundled FFmpeg against ``tools/installer/ffmpeg-needs.json`` and stops when a required
entry is missing. These tests keep that list honest: every codec the shipped code names is on it, the list reader
understands FFmpeg 8.1's own output, and the pins say what the plan says (8.1 gpl-shared, no ffplay).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "installer"))

import packaged_runtime  # noqa: E402

NEEDS = json.loads((REPO_ROOT / "tools" / "installer" / "ffmpeg-needs.json").read_text(encoding="utf-8"))
LOCK = json.loads((REPO_ROOT / "tools" / "installer" / "components.lock.json").read_text(encoding="utf-8"))


def _names(kind: str, *, required: bool | None = None) -> set[str]:
    return {item["name"] for item in NEEDS.get(kind, [])
            if required is None or bool(item.get("required", True)) == required}


class NeedsListTests(unittest.TestCase):
    def test_every_codec_the_shipped_code_names_is_checked(self) -> None:
        python = re.compile(r"""["']-(?:c:[av]|codec:[av]|acodec|vcodec)["']\s*,\s*(?:f?["'])?([A-Za-z0-9_]+)""")
        script = re.compile(r"""-(?:c:[av]|acodec|vcodec)['"]?\s*,?\s*['"]?([A-Za-z0-9_]+)""")
        named: dict[str, str] = {}
        for path in (REPO_ROOT / "src").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for match in python.finditer(line):
                    named.setdefault(match.group(1), f"{path.relative_to(REPO_ROOT)}:{number}")
        backend = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8-sig").splitlines()
        for number, line in enumerate(backend, start=1):
            for match in script.finditer(line):
                named.setdefault(match.group(1), f"Video Mangler.ps1:{number}")
        named.pop("copy", None)  # a stream copy, not an encoder
        unlisted = {name: where for name, where in named.items() if name not in _names("encoders")}
        self.assertEqual(unlisted, {}, "add these to tools/installer/ffmpeg-needs.json")

    def test_the_processor_encoders_are_required_and_nvidia_ones_are_not(self) -> None:
        for name in ("libx264", "aac", "libmp3lame", "pcm_s16le"):
            self.assertIn(name, _names("encoders", required=True))
        self.assertIn("h264_nvenc", _names("encoders", required=False))
        self.assertIn("drawtext", _names("filters", required=True))
        self.assertIn("--enable-libfreetype", _names("configuration", required=True), "drawtext needs freetype")
        self.assertIn("--enable-gpl", _names("configuration", required=True), "libx264 makes it a GPL build")


class ListReaderTests(unittest.TestCase):
    def test_ffmpeg_8_1_lists_are_read(self) -> None:
        encoders = (" V..... = Video\n A..... = Audio\n ------\n V....D libx264              libx264 H.264\n"
                    " A....D aac                  AAC (Advanced Audio Coding)\n")
        self.assertEqual(packaged_runtime._names(encoders, "encoders"), {"libx264", "aac"})
        filters = ("Filters:\n  T.. = Timeline support\n  | = Source or sink filter\n"
                   " T.C drawtext          V->V       Draw text on top of video frames using libfreetype library.\n"
                   " ... color             |->V       Provide an uniformly colored input.\n")
        self.assertEqual(packaged_runtime._names(filters, "filters"), {"drawtext", "color"})
        demuxers = (" D.. = Demuxing supported\n ---\n D   mov,mp4,m4a,3gp,3g2,mj2 QuickTime / MOV\n"
                    " D   matroska,webm   Matroska / WebM\n")
        self.assertEqual(packaged_runtime._names(demuxers, "demuxers"),
                         {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm"})
        devices = "Devices:\n D. = Demuxing supported\n ---\n D  lavfi           Libavfilter virtual input device\n"
        self.assertEqual(packaged_runtime._names(devices, "devices"), {"lavfi"})


class PinTests(unittest.TestCase):
    def test_the_pinned_ffmpeg_is_the_8_1_gpl_shared_month_end_build(self) -> None:
        ffmpeg = LOCK["components"]["ffmpeg"]
        self.assertTrue(ffmpeg["file"].endswith("-win64-gpl-shared-8.1.zip"))
        self.assertRegex(ffmpeg["release"], r"^autobuild-\d{4}-\d{2}-(28|29|30|31)-\d{2}-\d{2}$",
                         "a month-end build")
        self.assertTrue(ffmpeg["url"].startswith("https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/"))
        self.assertEqual(ffmpeg["left_out"], ["ffplay.exe"])
        self.assertTrue({"ffmpeg.exe", "ffprobe.exe", "avcodec-62.dll"} <= set(ffmpeg["bin_sha256"]),
                        "every shipped file is pinned, the libraries too")
        self.assertNotIn("ffplay.exe", ffmpeg["bin_sha256"])
        self.assertTrue(ffmpeg["licence"].startswith("GPL-3.0"))

    def test_every_component_is_pinned_by_sha256_over_https(self) -> None:
        for key, part in LOCK["components"].items():
            if key == "vc_runtime":
                for name, digest in part["files"].items():
                    self.assertRegex(digest, r"^[0-9a-f]{64}$", name)
                continue
            self.assertRegex(part["sha256"], r"^[0-9a-f]{64}$", key)
            self.assertTrue(part["url"].startswith("https://"), key)
            self.assertTrue(part["url"].endswith("/" + part["file"]), key)
            self.assertGreater(int(part["size"]), 0, key)
            self.assertTrue(part["licence"], key)

    def test_an_unused_module_is_left_out_of_the_standard_library_zip_and_nothing_else_changes(self) -> None:
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "python312.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for name in ("abc.pyc", "cgitb.pyc", "zipfile/__init__.pyc"):
                    archive.writestr(name, name.encode())
            self.assertEqual(packaged_runtime.stdlib_leave_out(path, ["cgitb.pyc"]), ["cgitb.pyc"])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ["abc.pyc", "zipfile/__init__.pyc"])
                self.assertEqual(archive.read("abc.pyc"), b"abc.pyc")
        self.assertEqual(LOCK["components"]["python"]["stdlib_left_out"], ["cgitb.pyc"])

    def test_no_pip_is_shipped_or_used_by_the_build(self) -> None:
        self.assertNotIn("pip", LOCK["components"])
        build = (REPO_ROOT / "tools" / "installer" / "Build-PackagedRuntime.ps1").read_text(encoding="utf-8")
        self.assertNotRegex(build, r"(?i)\bpip(\.pyz)?\s+install|-m\s+pip")


class SourceBundleTests(unittest.TestCase):
    """The Corresponding Source bundle's pins and packing (the real bundle is built on the operator's PC)."""

    def setUp(self) -> None:
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        import ffmpeg_source_bundle

        self.bundle = ffmpeg_source_bundle
        self.pins = json.loads((REPO_ROOT / "tools" / "installer" / "ffmpeg-source-pins.json").read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_the_pins_name_every_source_by_its_exact_revision(self) -> None:
        self.assertRegex(self.pins["ffmpeg"]["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(self.pins["builds"]["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(self.pins["binary"]["sha256"], LOCK["components"]["ffmpeg"]["sha256"],
                         "the source is for the very file the build ships")
        self.assertTrue(self.pins["ffmpeg"]["describe"] in LOCK["components"]["ffmpeg"]["version"])
        stages = [item for item in self.pins["dependencies"] if item["kind"] != "meta"]
        self.assertGreater(len(stages), 90)
        for item in stages:
            if item["kind"] == "svn":
                self.assertIsInstance(item["revision"], int, item["stage"])
            else:
                self.assertRegex(item["commit"], r"^[0-9a-f]{40}$", item["stage"])
            self.assertTrue(item["licence"], item["stage"])
        for name in ("50-x264.sh", "50-libmp3lame.sh", "fonts/50-freetype.sh", "50-librsvg/99-librsvg.sh"):
            self.assertTrue(any(item["stage"].endswith(name) for item in stages), name)
        self.assertTrue(any("zvbi" in line for line in self.pins["known_problems"]),
                        "the known licence conflict is written down, not hidden")

    def test_without_the_builds_own_cache_no_bundle_is_called_complete(self) -> None:
        from unittest import mock

        with mock.patch.object(self.bundle, "git_archive", side_effect=lambda *a, **k: self._fake_archive(a[2])):
            with self.assertRaises(SystemExit) as caught:
                self.bundle.build_bundle(self.root / "out", ci_cache=None)
        self.assertIn("CI download cache", str(caught.exception))

    def _fake_archive(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"archive")
        return target

    def test_a_work_folder_with_gits_read_only_files_is_removed(self) -> None:
        import os
        import stat

        pack = self.root / "work" / "git-1" / ".git" / "objects" / "pack" / "pack-1.idx"
        pack.parent.mkdir(parents=True)
        pack.write_bytes(b"index")
        os.chmod(pack, stat.S_IREAD)  # git keeps its pack files read-only
        self.bundle.remove_tree(self.root / "work")
        self.assertFalse((self.root / "work").exists())

    def test_the_lock_marks_the_pinned_build_not_for_release(self) -> None:
        blockers = LOCK["components"]["ffmpeg"].get("publish_blockers") or []
        self.assertTrue(any("zvbi" in item for item in blockers))
        build = (REPO_ROOT / "tools" / "installer" / "Build-PackagedRuntime.ps1").read_text(encoding="utf-8")
        self.assertIn("publish_blockers", build, "the build says so on every run")
        self.assertIn("privacy_check.py", build, "and scans what it put in runtime\\")

    def test_parts_stay_under_the_release_file_limit(self) -> None:
        source = self.root / "source"
        for index in range(7):
            path = source / "dependencies" / f"stage{index}.tar.xz"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes([index]) * 400)
        (source / "README-SOURCE.txt").write_text("readme", encoding="utf-8")
        from unittest import mock

        with mock.patch.object(self.bundle, "PART_LIMIT", 1000):
            parts = self.bundle.pack_parts(source, self.root / "parts", "ffmpeg-source")
        self.assertGreater(len(parts), 1)
        import zipfile

        names = []
        for part in parts:
            self.assertLessEqual(sum(info.file_size for info in zipfile.ZipFile(part).infolist()), 1000)
            names += zipfile.ZipFile(part).namelist()
        self.assertEqual(len(names), 8, "every file is in exactly one part")
        sums = (self.root / "parts" / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(sums), len(parts))

    def test_the_ci_cache_gives_each_used_stage_the_archive_the_build_used(self) -> None:
        import hashlib
        import io
        import tarfile
        import zipfile

        def add(tar: tarfile.TarFile, name: str, data: bytes = b"", link: str = "") -> None:
            info = tarfile.TarInfo(f".cache/downloads/{name}")
            if link:
                info.type, info.linkname = tarfile.SYMTYPE, link
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

        inner = io.BytesIO()
        with tarfile.open(fileobj=inner, mode="w:gz") as tar:
            add(tar, "50-x264.tar.xz", link="50-x264_new.tar.xz")
            add(tar, "50-x264_old.tar.xz", b"old")
            add(tar, "50-x264_new.tar.xz", b"new")
            add(tar, "10-xcbproto_aaa.tar.xz", b"linux only")
        cache = self.root / "download-cache.zip"
        with zipfile.ZipFile(cache, "w") as archive:
            archive.writestr("cache.tar.gz", inner.getvalue())
        pins = {"ci_download_cache": {"run": 1, "artifact": 2, "name": "download-cache",
                                      "sha256": hashlib.sha256(cache.read_bytes()).hexdigest()},
                "dependencies": [{"stage": "scripts.d/50-x264.sh", "kind": "git", "repo": "https://x264.invalid",
                                  "commit": "a" * 40, "licence": "GPL-2.0-or-later"},
                                 {"stage": "scripts.d/50-zimg.sh", "kind": "git", "repo": "https://zimg.invalid",
                                  "commit": "b" * 40, "licence": "WTFPL"}]}
        manifest: list = []
        source = self.root / "source"
        found = self.bundle._unpack_ci_cache(cache, pins, source / "dependencies", manifest, source)
        self.assertEqual(sorted(path.name for path in (source / "dependencies").iterdir()), ["50-x264_new.tar.xz"])
        self.assertEqual(found, {"from_cache": 1, "missing_from_cache": ["50-zimg"], "left_out": ["10-xcbproto"]})
        self.assertEqual(manifest[0]["revision"], "a" * 40)
        pins["ci_download_cache"]["sha256"] = "0" * 64
        with self.assertRaises(SystemExit):
            self.bundle._unpack_ci_cache(cache, pins, self.root / "again", [], self.root)


if __name__ == "__main__":
    unittest.main()
