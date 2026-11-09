from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers_workbench.build_identity import (  # noqa: E402
    BuildIdentity,
    load_packaged_build_identity,
)


FULL_COMMIT = "4ce15e3c49444bc6287aecafaf4489220723f6e0"


def _identity(*, packaged: bool, dirty: bool | None = False) -> BuildIdentity:
    return BuildIdentity(
        semantic_version="0.9.4",
        file_version="0.9.4.0",
        product_version="0.9.4.0",
        full_commit=FULL_COMMIT,
        short_commit="4ce15e3",
        build_timestamp_utc="2026-07-14T02:00:00Z",
        packaged=packaged,
        dirty=dirty,
        validation_label="Gate 4 validation build",
    )


class WorkbenchBuildIdentityTests(unittest.TestCase):
    def test_packaged_identity_formatting(self) -> None:
        self.assertEqual(
            _identity(packaged=True).display_identity,
            "v0.9.4 | PACKAGED | 4ce15e3 | CLEAN | Gate 4 validation build",
        )

    def test_source_run_identity_formatting(self) -> None:
        self.assertEqual(
            _identity(packaged=False).display_identity,
            "v0.9.4 | SOURCE | 4ce15e3 | CLEAN | Gate 4 validation build",
        )

    def test_embedded_commit_metadata_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata_path = Path(temp_dir) / "workbench-build-identity.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "semantic_version": "0.9.4",
                        "file_version": "0.9.4.0",
                        "product_version": "0.9.4.0",
                        "full_git_commit": FULL_COMMIT,
                        "short_git_commit": "wrong-value",
                        "build_timestamp_utc": "2026-07-14T02:00:00Z",
                        "dirty": False,
                        "validation_label": "Gate 4 validation build",
                    }
                ),
                encoding="utf-8",
            )
            identity = load_packaged_build_identity(metadata_path)
        self.assertEqual(identity.full_commit, FULL_COMMIT)
        self.assertEqual(identity.short_commit, "4ce15e3")
        self.assertEqual(identity.validation_label, "Gate 4 validation build")

    def test_dirty_build_labeling_is_unmistakable(self) -> None:
        identity = _identity(packaged=True, dirty=True)
        self.assertEqual(identity.worktree_state, "DIRTY")
        self.assertEqual(
            identity.display_identity,
            "v0.9.4 | PACKAGED | 4ce15e3 | DIRTY | Gate 4 validation build",
        )

    def test_fallback_when_metadata_is_unavailable(self) -> None:
        identity = load_packaged_build_identity(Path("missing-build-identity.json"))
        self.assertEqual(identity.display_identity, "v0.11.0 | PACKAGED | UNKNOWN | UNKNOWN")
        self.assertEqual(identity.worktree_state, "UNKNOWN")
        self.assertEqual(dict(identity.details())["Full Git commit SHA"], "Unavailable")
        self.assertEqual(dict(identity.details())["Build date/time"], "Unavailable")

    def test_friendly_and_diagnostic_identity_are_distinct(self) -> None:
        identity = _identity(packaged=True)
        self.assertEqual(identity.friendly_version, "v0.9.4")
        self.assertNotIn("PACKAGED", identity.friendly_version)
        self.assertIn("Full Git commit SHA: " + FULL_COMMIT, identity.diagnostic_text)
        self.assertIn("Validation label: Gate 4 validation build", identity.diagnostic_text)


if __name__ == "__main__":
    unittest.main()
