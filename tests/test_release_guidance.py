from __future__ import annotations

from pathlib import Path
import re
import unittest


class ReleaseGuidanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        revoked_video_id = "".join(["APOq", "EiXEC4g"])
        self.revoked_french = f"https://www.youtube.com/watch?v={revoked_video_id}"
        self.approved_french_id = "XRka52Y3kyA"

    def _read_text(self, relative_path: str) -> str:
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_revoked_french_source_is_removed_and_approved_example_stays_focused(self) -> None:
        tracked_guidance = [
            "README.md",
            "docs/guides/README.txt",
            "docs/guides/VIDEO_MANGLER.txt",
            "tools/smoke/Run-AudioSmokeTest.ps1",
        ]

        for relative_path in tracked_guidance:
            with self.subTest(path=relative_path):
                text = self._read_text(relative_path)
                self.assertNotIn(self.revoked_french, text)

        focused_guidance = [
            "docs/guides/VIDEO_MANGLER.txt",
            "tools/smoke/Run-AudioSmokeTest.ps1",
        ]
        for relative_path in focused_guidance:
            with self.subTest(path=relative_path):
                text = self._read_text(relative_path)
                self.assertIn(self.approved_french_id, text)

        for relative_path in ("README.md", "docs/guides/README.txt"):
            with self.subTest(path=relative_path):
                self.assertNotIn(self.approved_french_id, self._read_text(relative_path))

    def test_current_version_has_matching_release_notes_and_readme_link(self) -> None:
        version = (self.repo_root / "VERSION").read_text(encoding="utf-8").strip()

        self.assertEqual(version, "0.11.0")
        self.assertTrue(
            (self.repo_root / "docs" / "release-notes" / f"RELEASE_NOTES_v{version}.txt").exists()
        )
        self.assertIn(
            f"[v{version} release notes](docs/release-notes/RELEASE_NOTES_v{version}.txt)",
            self._read_text("README.md"),
        )

    def test_readme_release_badge_is_static_and_shows_the_current_version(self) -> None:
        # The badge names the version itself rather than looking a release up on GitHub, so it has
        # to move with VERSION.
        version = (self.repo_root / "VERSION").read_text(encoding="utf-8").strip()
        readme = self._read_text("README.md")
        self.assertIn(f"https://img.shields.io/badge/version-v{version}%20", readme)
        self.assertNotIn("img.shields.io/github/", readme)

    def test_readme_badge_and_download_point_to_the_release(self) -> None:
        # The version badge opens that version's release, and Download opens the Releases page.
        version = (self.repo_root / "VERSION").read_text(encoding="utf-8").strip()
        readme = self._read_text("README.md")
        releases = "https://github.com/Aintologic/media-manglers/releases"
        badge = re.compile(
            rf"\[!\[Version v{re.escape(version)}[^\]]*\]"
            rf"\(https://img\.shields\.io/badge/version-v{re.escape(version)}%20[^)]*\)\]"
            rf"\({re.escape(releases)}/tag/v{re.escape(version)}\)"
        )
        self.assertRegex(readme, badge)
        self.assertIn(f"**[Download]({releases})**", readme)

    def test_no_guide_still_says_the_first_release_is_coming(self) -> None:
        for relative_path in (
            "README.md",
            "docs/README.md",
            "docs/guides/README.txt",
            "docs/workbench/GETTING_STARTED.md",
            "docs/release-notes/RELEASE_NOTES_v0.11.0.txt",
        ):
            with self.subTest(path=relative_path):
                text = " ".join(self._read_text(relative_path).split()).lower()
                self.assertNotIn("coming soon", text)

    def test_packaged_validation_watchdog_scripts_are_tracked(self) -> None:
        self.assertTrue((self.repo_root / "tools" / "validation" / "PackagedRunWatchdog.ps1").exists())
        self.assertTrue(
            (self.repo_root / "tools" / "validation" / "Run-PackagedVideoRemoteValidation.ps1").exists()
        )


if __name__ == "__main__":
    unittest.main()
