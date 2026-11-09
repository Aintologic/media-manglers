from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers_workbench.settings import (  # noqa: E402
    ALWAYS_LOCAL_RUNTIME_KEYS,
    MACHINE_LOCAL_FIELD_SPECS,
    SETTINGS_BUNDLE_SCHEMA_VERSION,
    SETTINGS_BUNDLE_TYPE,
    MachineLocalFieldSpec,
    PathValidationResult,
    ProfileManager,
    build_default_settings,
    export_settings_bundle,
    import_settings_bundle,
)


class WorkbenchSettingsPortabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo_root = self.root / "target-app"
        self.repo_root.mkdir()
        (self.repo_root / "Video Mangler.ps1").write_text("param()", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _manager(self, name: str) -> ProfileManager:
        manager = ProfileManager(self.root / name, repo_root=str(self.repo_root))
        manager.ensure_starter_profiles()
        return manager

    def _write_bundle(self, payload: dict[str, object], name: str = "bundle.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _bundle(self, settings: dict[str, object], **extra: object) -> dict[str, object]:
        return {
            "bundleType": SETTINGS_BUNDLE_TYPE,
            "schemaVersion": SETTINGS_BUNDLE_SCHEMA_VERSION,
            "settings": settings,
            "customProfiles": [],
            **extra,
        }

    def test_default_export_is_portable_and_audited(self) -> None:
        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=r"C:\Users\ExampleUser\source-repo")
        machine_values = {
            "default_input_folder": r"Q:\Captured Sessions",
            "output_folder": r"\\review-server\exports",
            "repo_root": r"C:\Users\ExampleUser\source-repo",
            "script_path": r"C:\Tools\Video Mangler.ps1",
            "log_folder": r"C:\Users\ExampleUser\AppData\Local\MediaManglers\logs",
            "temp_folder": r"%TEMP%\MediaManglers",
            "evidence_transcription_glossary_path": r"D:\Machine\glossary.json",
            "review_source_folders": "D:\\Recorder One;\\\\recorder-server\\Recorder Two",
            "unexpected_local_value": r"C:\MachineOnly\tool.exe",
        }
        settings.update(machine_values)
        settings.update(
            {
                "debug_mode": False,
                "evidence_transcription_glossary_entries": "Synthetic Term=Synthetic Alias",
                "api_token": "synthetic-secret-value",
                "voice_enrollment": "synthetic-voice-vector",
                "recent_runs": [{"source": r"C:\Private\recording.mkv"}],
            }
        )
        manager.save("Portable Custom", settings, workflow="3")

        bundle_path = export_settings_bundle(
            self.root / "portable.json",
            settings,
            manager,
            repo_root=str(self.repo_root),
        )
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle_text = bundle_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schemaVersion"], 2)
        self.assertEqual(payload["exportMode"], "portable")
        self.assertFalse(payload["portability"]["machineLocalValuesIncluded"])
        self.assertNotIn("machineLocalSettings", payload)
        self.assertFalse(set(machine_values) & set(payload["settings"]))
        self.assertFalse(set(machine_values) & set(payload["customProfiles"][0]["settings"]))
        self.assertFalse(payload["settings"]["debug_mode"])
        self.assertEqual(
            payload["settings"]["evidence_transcription_glossary_entries"],
            "Synthetic Term=Synthetic Alias",
        )
        self.assertIn("output_folder", payload["exportAudit"]["machineLocalFieldsOmitted"])
        self.assertGreaterEqual(payload["exportAudit"]["sensitiveFieldsExcludedCount"], 2)
        self.assertIn("recent_runs", payload["exportAudit"]["runtimeFieldsExcluded"])
        for private_value in (*machine_values.values(), "synthetic-secret-value", "synthetic-voice-vector"):
            self.assertNotIn(private_value, bundle_text)

    def test_advanced_export_separates_this_pc_paths(self) -> None:
        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=str(self.repo_root))
        settings["output_folder"] = str(self.root / "exports")
        manager.save("Machine Custom", settings, workflow="3")

        path = export_settings_bundle(
            self.root / "this-pc.json",
            settings,
            manager,
            repo_root=str(self.repo_root),
            include_machine_paths=True,
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["exportMode"], "this-pc-paths")
        self.assertTrue(payload["portability"]["machineLocalValuesIncluded"])
        self.assertEqual(payload["machineLocalSettings"]["output_folder"], str(self.root / "exports"))
        self.assertIn("machineLocalSettings", payload["customProfiles"][0])
        self.assertIn("output_folder", payload["exportAudit"]["machineLocalFieldsIncluded"])

    def test_portable_export_imports_on_another_machine_without_path_checks(self) -> None:
        source_manager = self._manager("source-profiles")
        source = build_default_settings(repo_root=r"R:\SourceMachine\repo")
        source.update(
            {
                "output_folder": r"R:\SourceMachine\exports",
                "debug_mode": False,
                "frame_interval_seconds": 2.5,
            }
        )
        source_manager.save("Cross Machine", source, workflow="1")
        bundle = export_settings_bundle(
            self.root / "portable-cross-machine.json",
            source,
            source_manager,
            repo_root=r"R:\SourceMachine\repo",
        )

        target_manager = self._manager("target-profiles")
        target = build_default_settings(repo_root=str(self.repo_root))
        target_output = self.root / "target-exports"
        target_output.mkdir()
        target["output_folder"] = str(target_output)

        def no_path_checks(*_args: object) -> PathValidationResult:
            raise AssertionError("A portable bundle should not invoke machine-path validation")

        result = import_settings_bundle(
            bundle,
            target,
            target_manager,
            repo_root=str(self.repo_root),
            path_validator=no_path_checks,
        )

        self.assertFalse(result.settings["debug_mode"])
        self.assertEqual(result.settings["frame_interval_seconds"], 2.5)
        self.assertEqual(result.settings["output_folder"], str(target_output))
        imported = target_manager.load("Cross Machine")
        target_profile_default = build_default_settings(repo_root=str(self.repo_root))["output_folder"]
        self.assertEqual(imported["output_folder"], target_profile_default)
        self.assertNotEqual(imported["output_folder"], r"R:\SourceMachine\exports")

    def test_valid_same_machine_paths_are_applied(self) -> None:
        output = self.root / "valid-output"
        output.mkdir()
        script = self.repo_root / "Video Mangler.ps1"
        bundle = self._write_bundle(
            self._bundle(
                {"debug_mode": False},
                machineLocalSettings={
                    "output_folder": str(output),
                    "script_path": str(script),
                },
            )
        )
        manager = self._manager("target-profiles")

        result = import_settings_bundle(
            bundle,
            build_default_settings(repo_root=str(self.repo_root)),
            manager,
            repo_root=str(self.repo_root),
        )

        self.assertEqual(result.settings["output_folder"], str(output))
        self.assertEqual(result.settings["script_path"], str(script))
        self.assertEqual(result.counts()["unresolved"], 0)
        self.assertGreaterEqual(result.counts()["applied"], 3)

    def test_missing_path_is_unresolved_and_preserves_current_value(self) -> None:
        current_output = self.root / "current-output"
        current_output.mkdir()
        missing = self.root / "missing-output"
        current = build_default_settings(repo_root=str(self.repo_root))
        current["output_folder"] = str(current_output)
        bundle = self._write_bundle(
            self._bundle({}, machineLocalSettings={"output_folder": str(missing)})
        )

        result = import_settings_bundle(
            bundle,
            current,
            self._manager("target-profiles"),
            repo_root=str(self.repo_root),
        )

        self.assertEqual(result.settings["output_folder"], str(current_output))
        self.assertEqual(result.counts()["unresolved"], 1)
        self.assertIn("missing", result.details_text().lower())
        self.assertIn(str(missing), result.details_text())

    def test_inaccessible_path_is_unresolved(self) -> None:
        current_output = self.root / "current-output"
        imported_output = self.root / "imported-output"
        current_output.mkdir()
        imported_output.mkdir()
        current = build_default_settings(repo_root=str(self.repo_root))
        current["output_folder"] = str(current_output)
        bundle = self._write_bundle(
            self._bundle({}, machineLocalSettings={"output_folder": str(imported_output)})
        )

        with patch("media_manglers_workbench.settings.os.access", return_value=False):
            result = import_settings_bundle(
                bundle,
                current,
                self._manager("target-profiles"),
                repo_root=str(self.repo_root),
            )

        self.assertEqual(result.settings["output_folder"], str(current_output))
        self.assertEqual(result.counts()["unresolved"], 1)
        self.assertIn("inaccessible", result.details_text().lower())

    def test_wrong_file_directory_type_is_incompatible(self) -> None:
        current_output = self.root / "current-output"
        current_output.mkdir()
        wrong_type = self.root / "not-a-folder.txt"
        wrong_type.write_text("synthetic", encoding="utf-8")
        current = build_default_settings(repo_root=str(self.repo_root))
        current["output_folder"] = str(current_output)
        bundle = self._write_bundle(
            self._bundle({}, machineLocalSettings={"output_folder": str(wrong_type)})
        )

        result = import_settings_bundle(
            bundle,
            current,
            self._manager("target-profiles"),
            repo_root=str(self.repo_root),
        )

        self.assertEqual(result.settings["output_folder"], str(current_output))
        self.assertEqual(result.counts()["incompatible"], 1)
        self.assertIn("expected a directory", result.details_text().lower())

    def test_legacy_bundle_paths_are_migrated_without_rewriting_source(self) -> None:
        current_output = self.root / "current-output"
        current_output.mkdir()
        legacy_payload = {
            "bundleType": SETTINGS_BUNDLE_TYPE,
            "schemaVersion": 1,
            "settings": {
                "debug_mode": False,
                "output_folder": r"Z:\LegacyMachine\exports",
                "api_token": "legacy-secret",
            },
            "customProfiles": [
                {
                    "name": "Legacy Profile",
                    "workflow": "3",
                    "settings": {
                        "evidence_max_items": 7,
                        "review_source_folders": r"\\legacy-server\recordings",
                    },
                }
            ],
        }
        bundle = self._write_bundle(legacy_payload, "legacy.json")
        original_bytes = bundle.read_bytes()
        current = build_default_settings(repo_root=str(self.repo_root))
        current["output_folder"] = str(current_output)

        def legacy_validator(value: str, *_args: object) -> PathValidationResult:
            return PathValidationResult("missing", value, "Synthetic different-machine path.")

        manager = self._manager("target-profiles")
        result = import_settings_bundle(
            bundle,
            current,
            manager,
            repo_root=str(self.repo_root),
            path_validator=legacy_validator,
        )

        self.assertFalse(result.settings["debug_mode"])
        self.assertEqual(result.settings["output_folder"], str(current_output))
        self.assertEqual(result.source_schema_version, 1)
        self.assertIn("source file was unchanged", result.summary_text())
        self.assertEqual(bundle.read_bytes(), original_bytes)
        self.assertEqual(manager.load("Legacy Profile")["evidence_max_items"], 7)
        self.assertNotEqual(manager.load("Legacy Profile")["review_source_folders"], r"\\legacy-server\recordings")
        self.assertGreaterEqual(result.counts()["ignored_for_safety"], 1)

    def test_import_summary_has_all_required_categories(self) -> None:
        wrong_type = self.root / "wrong-script-directory"
        wrong_type.mkdir()
        bundle = self._write_bundle(
            self._bundle(
                {"debug_mode": False, "api_token": "never-apply"},
                machineLocalSettings={
                    "output_folder": "",
                    "default_input_folder": str(self.root / "missing-input"),
                    "script_path": str(wrong_type),
                },
            )
        )
        result = import_settings_bundle(
            bundle,
            build_default_settings(repo_root=str(self.repo_root)),
            self._manager("target-profiles"),
            repo_root=str(self.repo_root),
        )

        self.assertEqual(
            result.counts(),
            {
                "applied": 1,
                "skipped": 1,
                "unresolved": 1,
                "incompatible": 1,
                "ignored_for_safety": 1,
            },
        )
        summary = result.summary_text()
        for label in ("Applied", "Skipped", "Unresolved", "Incompatible", "Ignored for safety"):
            self.assertIn(label + ":", summary)

    def test_nested_secrets_signed_urls_and_private_runtime_fields_never_export(self) -> None:
        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=str(self.repo_root))
        settings.update(
            {
                "custom_auth": {"token": "nested-secret"},
                "upload_url": "https://example.invalid/object?X-Amz-Signature=synthetic-signature",
                "transcript_content": "synthetic private transcript",
                "recording_fingerprint": "synthetic-recording-hash",
                "narration_layouts": {"layout": "synthetic"},
            }
        )

        path = export_settings_bundle(
            self.root / "sensitive.json",
            settings,
            manager,
            repo_root=str(self.repo_root),
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")

        for key in (
            "custom_auth",
            "upload_url",
            "transcript_content",
            "recording_fingerprint",
            "narration_layouts",
        ):
            self.assertNotIn(key, payload["settings"])
        self.assertGreaterEqual(payload["exportAudit"]["sensitiveFieldsExcludedCount"], 5)
        for value in (
            "nested-secret",
            "synthetic-signature",
            "synthetic private transcript",
            "synthetic-recording-hash",
        ):
            self.assertNotIn(value, text)

    def test_bug_report_recording_lists_never_leave_this_pc(self) -> None:
        """The never-use list and the already-done map hold recording paths (114)."""

        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=str(self.repo_root))
        settings["bug_report_excluded_recordings"] = [r"Q:\Captured Sessions\synthetic-never-use.mkv"]
        # The already-done map keeps the recording path as the KEY, so a check
        # that only looks at values sees nothing but a date.
        settings["bug_report_processed_recordings"] = {
            r"q:\captured sessions\synthetic-already-done.mkv": "2026-01-02"
        }
        manager.save("Lists Custom", settings, workflow="3")

        for include_machine_paths in (False, True):
            with self.subTest(include_machine_paths=include_machine_paths):
                path = export_settings_bundle(
                    self.root / f"lists-{include_machine_paths}.json",
                    settings,
                    manager,
                    repo_root=str(self.repo_root),
                    include_machine_paths=include_machine_paths,
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = path.read_text(encoding="utf-8")
                profile = payload["customProfiles"][0]
                for key in ("bug_report_excluded_recordings", "bug_report_processed_recordings"):
                    self.assertNotIn(key, payload["settings"])
                    self.assertNotIn(key, payload.get("machineLocalSettings", {}))
                    self.assertNotIn(key, profile["settings"])
                    self.assertNotIn(key, profile.get("machineLocalSettings", {}))
                    self.assertIn(key, payload["exportAudit"]["runtimeFieldsExcluded"])
                self.assertNotIn("synthetic-never-use", text)
                self.assertNotIn("synthetic-already-done", text)

    def test_a_map_keyed_by_local_paths_is_machine_local(self) -> None:
        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=str(self.repo_root))
        settings["synthetic_future_map"] = {r"C:\MachineOnly\synthetic-keyed.mkv": "2026-01-02"}

        path = export_settings_bundle(
            self.root / "keyed.json",
            settings,
            manager,
            repo_root=str(self.repo_root),
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("synthetic_future_map", payload["settings"])
        self.assertIn("synthetic_future_map", payload["exportAudit"]["machineLocalFieldsOmitted"])
        self.assertNotIn("synthetic-keyed", path.read_text(encoding="utf-8"))

    def test_saved_profile_does_not_copy_the_bug_report_recording_lists(self) -> None:
        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=str(self.repo_root))
        settings["bug_report_excluded_recordings"] = [r"Q:\Captured Sessions\synthetic-never-use.mkv"]
        settings["bug_report_processed_recordings"] = {
            r"q:\captured sessions\synthetic-already-done.mkv": "2026-01-02"
        }

        saved = manager.save("Lists Custom", settings, workflow="3")
        text = saved.read_text(encoding="utf-8")

        self.assertNotIn("synthetic-never-use", text)
        self.assertNotIn("synthetic-already-done", text)
        # The caller's own settings are left alone: the lists still work here.
        self.assertEqual(len(settings["bug_report_excluded_recordings"]), 1)
        self.assertEqual(len(settings["bug_report_processed_recordings"]), 1)

    def test_imported_bundle_cannot_replace_the_bug_report_recording_lists(self) -> None:
        manager = self._manager("target-profiles")
        current = build_default_settings(repo_root=str(self.repo_root))
        current["bug_report_excluded_recordings"] = [r"Q:\Captured Sessions\synthetic-mine.mkv"]
        bundle = self._write_bundle(
            self._bundle(
                {
                    "debug_mode": False,
                    "bug_report_excluded_recordings": [r"Z:\Elsewhere\synthetic-theirs.mkv"],
                    "bug_report_processed_recordings": {r"z:\elsewhere\synthetic-theirs.mkv": "2026-01-02"},
                }
            )
        )

        result = import_settings_bundle(bundle, current, manager, repo_root=str(self.repo_root))

        self.assertEqual(
            result.settings["bug_report_excluded_recordings"],
            [r"Q:\Captured Sessions\synthetic-mine.mkv"],
        )
        # 244: no list is a setting any more, so none comes in with a bundle.
        self.assertFalse(result.settings.get("bug_report_processed_recordings"))

    def test_applying_a_profile_cannot_replace_the_bug_report_recording_lists(self) -> None:
        # Applying a profile restores every transient key afterwards, so being
        # transient is what stops an old profile overwriting today's lists.
        from media_manglers_workbench.app import TRANSIENT_PROFILE_KEYS
        from media_manglers_workbench.settings import (
            ALWAYS_LOCAL_RUNTIME_KEYS,
            BUG_REPORT_RECORDING_LIST_KEYS,
        )

        self.assertEqual(
            set(BUG_REPORT_RECORDING_LIST_KEYS),
            {"bug_report_excluded_recordings", "bug_report_processed_recordings"},
        )
        for key in BUG_REPORT_RECORDING_LIST_KEYS:
            self.assertIn(key, TRANSIENT_PROFILE_KEYS)
            self.assertIn(key, ALWAYS_LOCAL_RUNTIME_KEYS)

    def test_the_vlc_path_and_the_player_window_stay_on_this_pc(self) -> None:
        """Where VLC lives and where the player window sat describe this PC only (125)."""

        manager = self._manager("source-profiles")
        settings = build_default_settings(repo_root=str(self.repo_root))
        settings.update(
            {
                "video_player": "vlc",
                "video_autoplay": False,
                "video_player_vlc_path": r"Q:\Synthetic Apps\VLC\vlc.exe",
                "review_player_geometry": "synthetic-player-window-rectangle",
                "review_player_volume": 0.35,
            }
        )
        manager.save("Player Custom", settings, workflow="3")

        for include_machine_paths in (False, True):
            with self.subTest(include_machine_paths=include_machine_paths):
                path = export_settings_bundle(
                    self.root / f"player-{include_machine_paths}.json",
                    settings,
                    manager,
                    repo_root=str(self.repo_root),
                    include_machine_paths=include_machine_paths,
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = path.read_text(encoding="utf-8")
                profile = payload["customProfiles"][0]

                # The window rectangle never leaves, whichever export was asked for.
                for scope in (payload, profile):
                    self.assertNotIn("review_player_geometry", scope["settings"])
                    self.assertNotIn("review_player_geometry", scope.get("machineLocalSettings", {}))
                    self.assertNotIn("video_player_vlc_path", scope["settings"])
                self.assertIn("review_player_geometry", payload["exportAudit"]["runtimeFieldsExcluded"])
                self.assertNotIn("synthetic-player-window-rectangle", text)
                # The VLC path goes only when this PC's paths were asked for.
                if include_machine_paths:
                    self.assertEqual(
                        payload["machineLocalSettings"]["video_player_vlc_path"],
                        r"Q:\Synthetic Apps\VLC\vlc.exe",
                    )
                    self.assertIn("video_player_vlc_path", payload["exportAudit"]["machineLocalFieldsIncluded"])
                else:
                    self.assertNotIn("video_player_vlc_path", payload.get("machineLocalSettings", {}))
                    self.assertNotIn("video_player_vlc_path", profile.get("machineLocalSettings", {}))
                    self.assertIn("video_player_vlc_path", payload["exportAudit"]["machineLocalFieldsOmitted"])
                    self.assertNotIn("Synthetic Apps", text)
                # Which player, autoplay and the volume are plain choices: they travel.
                self.assertEqual(payload["settings"]["video_player"], "vlc")
                self.assertIs(payload["settings"]["video_autoplay"], False)
                self.assertEqual(payload["settings"]["review_player_volume"], 0.35)

    def test_imported_bundle_cannot_replace_the_player_window_geometry(self) -> None:
        self.assertIn("review_player_geometry", ALWAYS_LOCAL_RUNTIME_KEYS)
        manager = self._manager("target-profiles")
        current = build_default_settings(repo_root=str(self.repo_root))
        current["review_player_geometry"] = "synthetic-my-window-rectangle"
        theirs = "synthetic-their-window-rectangle"
        bundles = {
            "settings": self._bundle({"video_player": "system", "review_player_geometry": theirs}),
            "machineLocalSettings": self._bundle(
                {"video_player": "system"},
                machineLocalSettings={"review_player_geometry": theirs},
            ),
        }

        for placement, payload in bundles.items():
            with self.subTest(placement=placement):
                bundle = self._write_bundle(payload, f"geometry-{placement}.json")

                result = import_settings_bundle(bundle, dict(current), manager, repo_root=str(self.repo_root))

                self.assertEqual(result.settings["review_player_geometry"], "synthetic-my-window-rectangle")
                # The rest of the bundle still lands.
                self.assertEqual(result.settings["video_player"], "system")
                self.assertEqual(
                    [entry.key for entry in result.entries if entry.status == "ignored_for_safety"],
                    ["review_player_geometry"],
                )

    def test_an_imported_vlc_path_is_checked_as_a_file_on_this_pc(self) -> None:
        self.assertEqual(MACHINE_LOCAL_FIELD_SPECS["video_player_vlc_path"], MachineLocalFieldSpec("file"))
        mine = self.root / "my-player" / "vlc.exe"
        theirs = self.root / "their-player" / "vlc.exe"
        for path in (mine, theirs):
            path.parent.mkdir()
            path.write_text("synthetic", encoding="utf-8")
        a_folder = self.root / "their-player-folder"
        a_folder.mkdir()
        manager = self._manager("target-profiles")
        current = build_default_settings(repo_root=str(self.repo_root))
        current["video_player_vlc_path"] = str(mine)
        cases = {
            "valid": (str(theirs), str(theirs), "applied"),
            "missing": (str(self.root / "nowhere" / "vlc.exe"), str(mine), "unresolved"),
            "folder": (str(a_folder), str(mine), "incompatible"),
            # A PC without VLC must not blank the path this PC already found.
            "blank": ("", str(mine), "skipped"),
        }

        for name, (imported, expected, status) in cases.items():
            with self.subTest(case=name):
                bundle = self._write_bundle(
                    self._bundle({"video_player_vlc_path": imported}),
                    f"vlc-{name}.json",
                )

                result = import_settings_bundle(bundle, dict(current), manager, repo_root=str(self.repo_root))

                self.assertEqual(result.settings["video_player_vlc_path"], expected)
                self.assertEqual(
                    [entry.status for entry in result.entries if entry.key == "video_player_vlc_path"],
                    [status],
                )

    def test_profile_collision_preserves_existing_profile(self) -> None:
        source_manager = self._manager("source-profiles")
        source = build_default_settings(repo_root=str(self.repo_root))
        source["evidence_max_items"] = 7
        source_manager.save("Existing Custom", source, workflow="3")
        bundle = export_settings_bundle(
            self.root / "profiles.json",
            source,
            source_manager,
            repo_root=str(self.repo_root),
        )

        target_manager = self._manager("target-profiles")
        target = build_default_settings(repo_root=str(self.repo_root))
        target["evidence_max_items"] = 99
        target_manager.save("Existing Custom", target, workflow="3")
        result = import_settings_bundle(
            bundle,
            target,
            target_manager,
            repo_root=str(self.repo_root),
        )

        self.assertEqual(target_manager.load("Existing Custom")["evidence_max_items"], 99)
        self.assertEqual(result.imported_profile_names, ["Existing Custom (imported 2)"])
        self.assertEqual(target_manager.load("Existing Custom (imported 2)")["evidence_max_items"], 7)

    def test_future_schema_rejection_does_not_change_settings_or_profiles(self) -> None:
        manager = self._manager("target-profiles")
        before_names = manager.list_names()
        current = build_default_settings(repo_root=str(self.repo_root))
        bundle = self._write_bundle(
            {
                "bundleType": SETTINGS_BUNDLE_TYPE,
                "schemaVersion": SETTINGS_BUNDLE_SCHEMA_VERSION + 1,
                "settings": {"debug_mode": False},
                "customProfiles": [],
            }
        )

        with self.assertRaisesRegex(ValueError, "Unsupported settings bundle schemaVersion"):
            import_settings_bundle(
                bundle,
                current,
                manager,
                repo_root=str(self.repo_root),
            )

        self.assertTrue(current["debug_mode"])
        self.assertEqual(manager.list_names(), before_names)


if __name__ == "__main__":
    unittest.main()
