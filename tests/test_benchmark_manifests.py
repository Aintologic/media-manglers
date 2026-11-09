from __future__ import annotations

import json
from pathlib import Path
import unittest


class BenchmarkManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.benchmark_root = self.repo_root / "tools" / "benchmarks" / "manifests"
        revoked_video_id = "".join(["APOq", "EiXEC4g"])
        self.revoked_french_url = f"https://www.youtube.com/watch?v={revoked_video_id}"

    def _load_json(self, relative_path: str) -> dict:
        return json.loads((self.repo_root / relative_path).read_text(encoding="utf-8"))

    def test_canonical_short_manifest_matches_current_approved_video_ids(self) -> None:
        manifest = self._load_json("tools/benchmarks/manifests/canonical-short.json")
        expected_video_ids = {
            "1aA1WGON49E",
            "hNaUbuWL8MI",
            "7_u8Qj78cA0",
            "XRka52Y3kyA",
            "WPm2N93SmTA",
            "5OspljwLkDQ",
            "Xe6AgUkZmog",
            "fJ7V53jFrVc",
        }

        self.assertEqual({item["video_id"] for item in manifest["sources"]}, expected_video_ids)
        for source in manifest["sources"]:
            with self.subTest(source=source["source_id"]):
                self.assertNotIn("playlist?", source["url"])
                self.assertNotIn("&list=", source["url"])
                self.assertNotEqual(source["url"], self.revoked_french_url)

    def test_long_and_shadow_manifests_stay_single_video_only(self) -> None:
        manifest_paths = [
            "tools/benchmarks/manifests/canonical-long.json",
            "tools/benchmarks/manifests/technical-terminology-shadow.json",
        ]

        for relative_path in manifest_paths:
            manifest = self._load_json(relative_path)
            for source in manifest["sources"]:
                with self.subTest(path=relative_path, source=source["source_id"]):
                    self.assertNotIn("playlist?", source["url"])
                    self.assertNotIn("&list=", source["url"])

    def test_readme_points_to_current_benchmark_program(self) -> None:
        # The concise README links the benchmark program only; the program
        # page links the results schema.
        readme = (self.repo_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/benchmarks/BENCHMARK_PROGRAM.md", readme)
        program = (self.repo_root / "docs" / "benchmarks" / "BENCHMARK_PROGRAM.md").read_text(encoding="utf-8")
        self.assertIn("BENCHMARK_RESULTS_SCHEMA.md", program)
        self.assertTrue((self.repo_root / "docs" / "benchmarks" / "BENCHMARK_RESULTS_SCHEMA.md").is_file())


if __name__ == "__main__":
    unittest.main()
