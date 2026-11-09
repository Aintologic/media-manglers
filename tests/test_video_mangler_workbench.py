from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers_workbench.command_builder import (
    CommandSpec,
    build_codex_evidence_command,
    build_workflow_command,
    validate_effective_command,
)
from media_manglers_workbench.evidence import load_evidence_package
from media_manglers_workbench.estimates import estimate_sampling
from media_manglers_workbench.job_spec import JobSpec
from media_manglers_workbench.metadata import (
    ALL_WORKFLOWS,
    METADATA_BY_KEY,
    SETTING_METADATA,
    metadata_for_workflow,
)
from media_manglers_workbench.prompts import build_codex_prompt, export_prompt_drafts
from media_manglers_workbench.runner import FakeRunner
from media_manglers_workbench.settings import (
    BUILT_IN_PROFILE_VERSION,
    PROFILE_SCHEMA_VERSION,
    SETTINGS_SCHEMA_VERSION,
    ProfileManager,
    build_default_settings,
    clean_workbench_owned_path,
    export_settings_bundle,
    import_settings_bundle,
    load_settings,
    save_settings,
    starter_profile_settings,
    _profile_fingerprint,
)


FIXTURE_PACKAGE = Path(__file__).resolve().parent / "fixtures" / "workbench" / "evidence_package"
# 125: every setting the built-in player added.
VIDEO_PLAYER_KEYS = (
    "video_player",
    "video_autoplay",
    "video_player_vlc_path",
    "review_player_geometry",
    "review_player_volume",
)


def _profile_files_snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
    return {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in sorted(root.glob("*.json"))}


def _age_profile_files(root: Path) -> None:
    # A rewrite with identical content leaves the bytes alone, so only an old
    # timestamp makes it visible.
    old_time = time.time() - 86400
    for path in root.glob("*.json"):
        os.utime(path, (old_time, old_time))


class VideoManglerWorkbenchTests(unittest.TestCase):
    def test_job_spec_serialization_round_trip(self) -> None:
        spec = JobSpec(
            input_path=r"C:\Videos\session one\lap.mkv",
            output_folder=r"C:\Reviews\Video",
            repo_root=r"C:\Repos\media-manglers",
            evidence_target_repo="owner/example-repo",
        )

        restored = JobSpec.from_json(spec.to_json())

        self.assertEqual(restored.to_dict(), spec.to_dict())
        self.assertEqual(restored.to_dict()["schemaVersion"], 1)
        self.assertEqual(restored.to_dict()["workflow"], "codex-evidence-package")
        self.assertTrue(restored.no_prompt)
        self.assertEqual(restored.language, "en")
        self.assertEqual(restored.narration_speech_mode, "Sparse")
        self.assertEqual(restored.evidence_render_density, "Compact")
        self.assertEqual(restored.evidence_profile_setup_name, "iRacing Ticket Evidence - Balanced")

    def test_command_generation_and_preview(self) -> None:
        spec = JobSpec(
            input_path=r"C:\Videos\session one\lap.mkv",
            output_folder=r"C:\Reviews\Video",
            script_path=r".\Video Mangler.ps1",
        )

        command = build_codex_evidence_command(spec)

        self.assertEqual(command.argv[0], "powershell")
        self.assertIn("-CodexEvidencePackage", command.argv)
        self.assertIn("-NoPrompt", command.argv)
        self.assertIn("-WhisperModel", command.argv)
        self.assertIn("'C:\\Videos\\session one\\lap.mkv'", command.preview)
        self.assertIn("-Language 'en'", command.preview)
        self.assertIn("-NarrationSpeechMode 'Sparse'", command.preview)
        self.assertIn("-EvidenceRenderDensity 'Compact'", command.preview)
        self.assertIn("-EvidenceFrameCadenceSeconds '15'", command.preview)
        self.assertIn("-EvidenceMaxFramesPerCandidate '24'", command.preview)
        self.assertIn("-EvidenceProfileSetupName 'iRacing Ticket Evidence - Balanced'", command.preview)

    def test_command_preview_safe_quoting_for_windows_paths(self) -> None:
        spec = JobSpec(
            input_path=r"C:\Videos\Bob's [test]\clip one.mp4",
            output_folder=r"C:\Reviews\Apostrophe's [case]",
            script_path=r".\Video Mangler.ps1",
        )

        command = build_codex_evidence_command(spec)

        self.assertIn(r"C:\Videos\Bob's [test]\clip one.mp4", command.argv)
        self.assertIn(r"'C:\Videos\Bob''s [test]\clip one.mp4'", command.preview)
        self.assertIn(r"'C:\Reviews\Apostrophe''s [case]'", command.preview)

    def test_settings_defaults_use_user_videos_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "USERPROFILE": str(temp_root / "User"),
                    "MEDIA_MANGLERS_VIDEOS_FOLDER": str(temp_root / "User" / "Videos"),
                    "APPDATA": str(temp_root / "Roaming"),
                    "LOCALAPPDATA": str(temp_root / "Local"),
                },
                clear=False,
            ):
                settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")

        self.assertEqual(settings["default_workflow"], "1")
        self.assertEqual(settings["default_profile"], "")
        self.assertEqual(Path(settings["default_input_folder"]), temp_root / "User" / "Videos")
        self.assertEqual(Path(settings["output_folder"]), temp_root / "User" / "Videos" / "Media Mangler")
        self.assertIn("MediaManglers", settings["log_folder"])
        self.assertEqual(settings["repo_root"], r"C:\Repos\media-manglers")

    def test_settings_save_load_default_workflow_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
            settings["default_workflow"] = "3"
            settings["output_folder"] = r"C:\Users\Example\Videos\Media Mangler Custom"

            save_settings(settings, path, repo_root=r"C:\Repos\media-manglers")
            restored = load_settings(path, repo_root=r"C:\Repos\media-manglers")

        self.assertEqual(restored["default_workflow"], "3")
        self.assertEqual(restored["output_folder"], r"C:\Users\Example\Videos\Media Mangler Custom")

    def test_settings_v1_migration_preserves_known_and_custom_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "settings": {
                            "default_workflow": "2",
                            "output_folder": r"C:\Reviews\Existing",
                            "operator_custom_value": "preserve-me",
                            "evidence_frame_cadence_seconds": 0.5,
                        },
                    }
                ),
                encoding="utf-8",
            )
            restored = load_settings(path, repo_root=r"C:\Repos\media-manglers")
            save_settings(restored, path, repo_root=r"C:\Repos\media-manglers")
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(restored["default_workflow"], "1")
        self.assertEqual(restored["default_profile"], "")
        self.assertEqual(restored["output_folder"], r"C:\Reviews\Existing")
        self.assertEqual(restored["operator_custom_value"], "preserve-me")
        self.assertEqual(restored["evidence_frame_cadence_seconds"], 0.5)
        self.assertEqual(saved["schemaVersion"], SETTINGS_SCHEMA_VERSION)

    def test_video_player_defaults_are_present_with_the_right_types(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")

        self.assertEqual(set(VIDEO_PLAYER_KEYS) - set(settings), set())
        self.assertEqual(settings["video_player"], "internal")
        self.assertIs(settings["video_autoplay"], True)
        self.assertEqual(settings["video_player_vlc_path"], "")
        self.assertEqual(settings["review_player_geometry"], "")
        self.assertEqual(settings["review_player_volume"], 0.8)
        self.assertIsInstance(settings["review_player_volume"], float)
        for key in ("video_player", "video_player_vlc_path", "review_player_geometry"):
            self.assertIsInstance(settings[key], str, key)

    def test_settings_saved_before_the_video_player_pick_up_its_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            # Same schema version, no 125 keys: what every install has today.
            path.write_text(
                json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {"theme": "Light"}}),
                encoding="utf-8",
            )
            restored = load_settings(path, repo_root=r"C:\Repos\media-manglers")
            defaults = build_default_settings(repo_root=r"C:\Repos\media-manglers")
            picked_up = {key: restored[key] for key in VIDEO_PLAYER_KEYS}

            restored.update({"video_player": "vlc", "video_autoplay": False, "review_player_volume": 0.35})
            save_settings(restored, path, repo_root=r"C:\Repos\media-manglers")
            reloaded = load_settings(path, repo_root=r"C:\Repos\media-manglers")

        self.assertEqual(picked_up, {key: defaults[key] for key in VIDEO_PLAYER_KEYS})
        self.assertEqual(restored["theme"], "Light")
        self.assertEqual(reloaded["video_player"], "vlc")
        self.assertIs(reloaded["video_autoplay"], False)
        self.assertEqual(reloaded["review_player_volume"], 0.35)

    def test_profile_save_load_delete_and_starters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ProfileManager(Path(temp_dir) / "profiles", repo_root=r"C:\Repos\media-manglers")
            manager.ensure_starter_profiles()
            starter_names = manager.list_names()
            self.assertIn("Ticket Evidence Run", starter_names)
            self.assertIn("Full Review + Evidence", starter_names)
            self.assertIn("iRacing Ticket Evidence - Balanced", starter_names)
            self.assertIn("iRacing Telemetry Detail", starter_names)
            self.assertIn("iRacing Long Explanation", starter_names)

            settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
            settings["default_workflow"] = "2"
            settings["transcript_search_terms"] = "brake; apex"
            manager.save("Custom Transcript", settings)
            restored = manager.load("Custom Transcript")
            deleted = manager.delete("Custom Transcript")

        self.assertEqual(restored["default_workflow"], "2")
        self.assertEqual(restored["transcript_search_terms"], "brake; apex")
        self.assertTrue(deleted)

    def test_iracing_builtin_profiles_match_required_values(self) -> None:
        profiles = starter_profile_settings(repo_root=r"C:\Repos\media-manglers")
        balanced = profiles["iRacing Ticket Evidence - Balanced"]
        telemetry = profiles["iRacing Telemetry Detail"]
        long_explanation = profiles["iRacing Long Explanation"]

        self.assertEqual(
            (
                balanced["pre_context_seconds"],
                balanced["post_context_seconds"],
                balanced["narration_context_pre_seconds"],
                balanced["narration_context_post_seconds"],
                balanced["evidence_frame_cadence_seconds"],
                balanced["evidence_max_frames_per_candidate"],
                balanced["evidence_max_items"],
            ),
            (90, 120, 120, 600, 15.0, 24, 20),
        )
        self.assertEqual(telemetry["evidence_frame_cadence_seconds"], 15.0)
        self.assertEqual(telemetry["evidence_max_frames_per_candidate"], 24)
        self.assertEqual(telemetry["evidence_max_items"], 10)
        self.assertEqual(long_explanation["narration_context_post_seconds"], 900)
        self.assertEqual(long_explanation["evidence_frame_cadence_seconds"], 15.0)
        self.assertEqual(long_explanation["evidence_max_frames_per_candidate"], 24)
        for profile in (balanced, telemetry, long_explanation):
            self.assertEqual(profile["language"], "en")
            self.assertEqual(profile["narration_speech_mode"], "Sparse")
            self.assertEqual(profile["evidence_render_density"], "Compact")

    def test_existing_custom_profile_survives_builtin_profile_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_dir = Path(temp_dir) / "profiles"
            profiles_dir.mkdir()
            custom_path = profiles_dir / "My Custom.json"
            custom_payload = {
                "schemaVersion": 1,
                "profileName": "My Custom",
                "settings": {
                    "default_workflow": "3",
                    "evidence_frame_cadence_seconds": 0.5,
                    "operator_custom_value": "do-not-overwrite",
                },
            }
            custom_path.write_text(json.dumps(custom_payload, indent=2) + "\n", encoding="utf-8")
            before = custom_path.read_bytes()
            manager = ProfileManager(profiles_dir, repo_root=r"C:\Repos\media-manglers")
            manager.ensure_starter_profiles()
            after = custom_path.read_bytes()
            loaded = manager.load_with_metadata("My Custom")

        self.assertEqual(before, after)
        self.assertEqual(loaded.schema_version, 1)
        self.assertEqual(loaded.workflow, "3")
        self.assertEqual(loaded.settings["operator_custom_value"], "do-not-overwrite")
        self.assertEqual(loaded.settings["evidence_frame_cadence_seconds"], 0.5)
        self.assertIn("Migrated legacy profile", loaded.source_description)
        self.assertEqual(PROFILE_SCHEMA_VERSION, 2)

    def test_v092_untouched_builtin_is_migrated_before_defaults_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_dir = Path(temp_dir) / "profiles"
            profiles_dir.mkdir()
            name = "iRacing Ticket Evidence - Balanced"
            raw_settings = {
                "default_workflow": "3",
                "language": "",
                "evidence_frame_cadence_seconds": 1.0,
                "evidence_max_frames_per_candidate": 220,
            }
            payload = {
                "schemaVersion": 2,
                "profileName": name,
                "profileType": "built-in",
                "workflow": "3",
                "builtInVersion": 1,
                "builtInDefaultsHash": _profile_fingerprint(raw_settings, "3"),
                "settings": raw_settings,
            }
            (profiles_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
            manager = ProfileManager(profiles_dir, repo_root=r"C:\Repos\media-manglers")

            manager.ensure_starter_profiles()
            loaded = manager.load_with_metadata(name)

        self.assertEqual(loaded.built_in_version, BUILT_IN_PROFILE_VERSION)
        self.assertEqual(loaded.migration_status, "migrated-built-in")
        self.assertEqual(loaded.migrated_from_built_in_version, 1)
        self.assertEqual(loaded.settings["language"], "en")
        self.assertEqual(loaded.settings["narration_speech_mode"], "Sparse")
        self.assertEqual(loaded.settings["evidence_render_density"], "Compact")
        self.assertEqual(loaded.settings["evidence_frame_cadence_seconds"], 15.0)
        self.assertEqual(loaded.settings["evidence_max_frames_per_candidate"], 24)

    def test_modified_legacy_builtin_is_preserved_as_custom_then_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_dir = Path(temp_dir) / "profiles"
            profiles_dir.mkdir()
            name = "iRacing Ticket Evidence - Balanced"
            original = {"default_workflow": "3", "language": "", "operator_value": "before"}
            modified = {**original, "operator_value": "explicit-edit"}
            payload = {
                "schemaVersion": 2,
                "profileName": name,
                "profileType": "built-in",
                "workflow": "3",
                "builtInVersion": 1,
                "builtInDefaultsHash": _profile_fingerprint(original, "3"),
                "settings": modified,
            }
            (profiles_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
            manager = ProfileManager(profiles_dir, repo_root=r"C:\Repos\media-manglers")

            manager.ensure_starter_profiles()
            preserved_name = next(item for item in manager.list_names() if "preserved legacy" in item)
            preserved = manager.load_with_metadata(preserved_name)
            refreshed = manager.load_with_metadata(name)

        self.assertEqual(preserved.profile_type, "custom")
        self.assertEqual(preserved.settings["operator_value"], "explicit-edit")
        self.assertEqual(preserved.migration_status, "preserved-custom")
        self.assertEqual(refreshed.settings["language"], "en")
        self.assertEqual(refreshed.settings["narration_speech_mode"], "Sparse")

    def test_video_player_defaults_do_not_rewrite_starter_profiles(self) -> None:
        # 125 changed no built-in profile VALUE, so the version stays put: a
        # bump would rewrite every operator's starter profiles for nothing.
        self.assertEqual(BUILT_IN_PROFILE_VERSION, 7)
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ProfileManager(Path(temp_dir) / "profiles", repo_root=r"C:\Repos\media-manglers")
            manager.ensure_starter_profiles()
            _age_profile_files(manager.root)
            before = _profile_files_snapshot(manager.root)

            manager.ensure_starter_profiles()
            after = _profile_files_snapshot(manager.root)

        self.assertEqual(len(before), len(starter_profile_settings()))
        self.assertEqual(before, after)

    def test_starter_profiles_written_before_the_video_player_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ProfileManager(Path(temp_dir) / "profiles", repo_root=r"C:\Repos\media-manglers")
            manager.ensure_starter_profiles()
            for path in manager.root.glob("*.json"):
                # What the previous release left on disk: the same profile
                # without the 125 keys, hashed over exactly what the file holds.
                payload = json.loads(path.read_text(encoding="utf-8"))
                for key in VIDEO_PLAYER_KEYS:
                    del payload["settings"][key]
                payload["builtInDefaultsHash"] = _profile_fingerprint(payload["settings"], payload["workflow"])
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            _age_profile_files(manager.root)
            before = _profile_files_snapshot(manager.root)

            manager.ensure_starter_profiles()
            after = _profile_files_snapshot(manager.root)
            loaded = manager.load_with_metadata("iRacing Ticket Evidence - Balanced")

        # Same files, same bytes, same timestamps - and no "preserved legacy" copy.
        self.assertEqual(before, after)
        self.assertEqual(loaded.built_in_version, BUILT_IN_PROFILE_VERSION)
        self.assertEqual(loaded.migration_status, "")
        # The older file still hands the player its defaults when it is loaded.
        self.assertEqual(set(VIDEO_PLAYER_KEYS) - set(loaded.missing_default_keys), set())
        self.assertEqual(loaded.settings["video_player"], "internal")
        self.assertIs(loaded.settings["video_autoplay"], True)
        self.assertEqual(loaded.settings["review_player_volume"], 0.8)

    def test_effective_command_validation_detects_critical_mismatch(self) -> None:
        settings = starter_profile_settings(repo_root=r"C:\Repos\media-manglers")[
            "iRacing Ticket Evidence - Balanced"
        ]
        settings.update(
            {
                "input_path": r"C:\Videos\lap.mkv",
                "output_folder": r"C:\Reviews\Video",
                "script_path": r".\Video Mangler.ps1",
            }
        )
        command = build_workflow_command(settings, workflow="3")
        self.assertEqual(validate_effective_command(settings, command, workflow="3"), [])

        stale_argv = list(command.argv)
        stale_argv[stale_argv.index("-NarrationSpeechMode") + 1] = "Auto"
        errors = validate_effective_command(
            settings,
            CommandSpec(stale_argv, "synthetic mismatch"),
            workflow="3",
        )
        self.assertTrue(any("NarrationSpeechMode" in error for error in errors))

    def test_workflow_command_builder_supports_all_five_workflows(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
        settings.update(
            {
                "input_path": r"C:\Videos\session one\lap.mkv",
                "output_folder": r"C:\Users\Example\Videos\Media Mangler",
                "script_path": r".\Video Mangler.ps1",
                "input_kind": "url",
                "archive_search_terms": "Spa Ferrari GT3",
                "review_source_folders": r"C:\Videos\Recordings",
                "review_evidence_root": r"C:\Reviews\ReviewNewVideos",
            }
        )

        workflow_1 = build_workflow_command(settings, workflow="1")
        workflow_2 = build_workflow_command(settings, workflow="2")
        workflow_3 = build_workflow_command(settings, workflow="3")
        workflow_4 = build_workflow_command({**settings, "archive_action": "search"}, workflow="4")
        workflow_5 = build_workflow_command(settings, workflow="5")

        self.assertIn("-InputUrl", workflow_1.argv)
        self.assertNotIn("-CodexEvidencePackage", workflow_1.argv)
        self.assertIn("-TranscriptOnly", workflow_2.argv)
        self.assertIn("-CodexEvidencePackage", workflow_3.argv)
        self.assertIn("-ArchiveCatalogSearch", workflow_4.argv)
        self.assertIn("-ReviewMediaInbox", workflow_5.argv)
        self.assertIn("-ReviewInboxAction", workflow_5.argv)
        self.assertIn("-ReviewInboxWorkload", workflow_5.argv)
        self.assertIn("-ReviewInboxNewSourceLimit", workflow_5.argv)
        self.assertIn("-ReviewSourceFolders", workflow_5.argv)
        self.assertIn("-NoPrompt", workflow_5.argv)

    def test_workflow_five_process_contract_forwards_workload_and_continuation(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
        settings.update(
            {
                "review_source_folders": r"C:\Videos\Recordings",
                "review_evidence_root": r"C:\Reviews\ReviewNewVideos",
                "review_inbox_action": "Process",
                "review_inbox_workload_mode": "up_to_n",
                "review_inbox_new_source_limit": 10,
                "review_inbox_exact_source_paths": [
                    r"C:\Videos\Recordings\approved-one.mkv",
                    r"C:\Videos\Recordings\approved-two.mkv",
                ],
                "review_inbox_continuation": "opaque-continuation",
                "review_inbox_decision_json": '{"kind":"cleanup","choice":"keep"}',
            }
        )
        command = build_workflow_command(settings, workflow="5")
        for flag, expected in (
            ("-ReviewInboxAction", "Process"),
            ("-ReviewInboxWorkload", "up_to_n"),
            ("-ReviewInboxNewSourceLimit", "10"),
            ("-ReviewInboxContinuation", "opaque-continuation"),
            ("-ReviewInboxDecisionJson", '{"kind":"cleanup","choice":"keep"}'),
        ):
            self.assertEqual(command.argv[command.argv.index(flag) + 1], expected)
        restriction_index = command.argv.index("-ReviewInboxExactSourcePathsJson")
        self.assertEqual(
            json.loads(command.argv[restriction_index + 1]),
            [
                r"C:\Videos\Recordings\approved-one.mkv",
                r"C:\Videos\Recordings\approved-two.mkv",
            ],
        )

    def test_exact_source_json_scalar_survives_powershell_file_transport(
        self,
    ) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            probe = Path(temporary) / "probe-exact-source-json.ps1"
            probe.write_text(
                "\n".join(
                    (
                        "param([string]$ReviewInboxExactSourcePathsJson = \"\")",
                        "$parsed = $ReviewInboxExactSourcePathsJson | "
                        "ConvertFrom-Json -ErrorAction Stop",
                        "$values = @($parsed | ForEach-Object { [string]$_ })",
                        "@($values) | ConvertTo-Json -Compress",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            for count in (1, 2, 3):
                expected = [
                    rf"C:\Videos\Recordings\approved-{index}.mkv"
                    for index in range(1, count + 1)
                ]
                completed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(probe),
                        "-ReviewInboxExactSourcePathsJson",
                        json.dumps(expected, separators=(",", ":")),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                with self.subTest(count=count, stderr=completed.stderr):
                    self.assertEqual(completed.returncode, 0)
                    transported = json.loads(completed.stdout.strip())
                    if count == 1:
                        transported = [transported]
                    self.assertEqual(transported, expected)

    def test_workflow_command_forwards_preflight_validated_runtime_paths(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
        settings.update(
            {
                "input_path": r"C:\Videos\synthetic.mkv",
                "output_folder": r"C:\Reviews\Synthetic",
                "python_exe": r"C:\Runtime\python.exe",
                "ffmpeg_path": r"C:\Runtime\ffmpeg.exe",
                "ffprobe_path": r"C:\Runtime\ffprobe.exe",
            }
        )
        command = build_workflow_command(settings, workflow="3")
        for flag, expected in (
            ("-PythonExe", r"C:\Runtime\python.exe"),
            ("-FFmpegPath", r"C:\Runtime\ffmpeg.exe"),
            ("-FFprobePath", r"C:\Runtime\ffprobe.exe"),
        ):
            self.assertEqual(command.argv[command.argv.index(flag) + 1], expected)
        script = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('[string]$FFprobePath = ""', script)
        self.assertIn('Resolve-CommandOrPath -Value $FFprobePath -ToolName "FFprobe" -ToolKey "ffprobe"', script)

    def test_workflow_command_includes_narration_and_selected_render_flags_safely(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
        settings.update(
            {
                "input_path": r"C:\Videos\lap.mkv",
                "output_folder": r"C:\Reviews\Video",
                "narration_context_pre_seconds": 120,
                "narration_context_post_seconds": 600,
                "narration_pause_threshold_seconds": 30,
                "narration_stop_at_next_ticket_boundary": False,
                "fragmented_narration_mode": True,
                "evidence_render_candidate_ids": "ticket-021,ticket-024",
                "evidence_frame_cadence_seconds": 0.5,
            }
        )
        command = build_workflow_command(settings, workflow="3")

        self.assertIn("-NarrationContextPreSeconds", command.argv)
        self.assertIn("-NarrationContextPostSeconds", command.argv)
        self.assertIn("-NarrationPauseThresholdSeconds", command.argv)
        stop_index = command.argv.index("-NarrationStopAtNextTicketBoundary")
        fragmented_index = command.argv.index("-FragmentedNarrationMode")
        self.assertEqual(command.argv[stop_index + 1], "Off")
        self.assertEqual(command.argv[fragmented_index + 1], "On")
        self.assertIn("-EvidenceRenderCandidateIds", command.argv)
        self.assertIn("ticket-021,ticket-024", command.argv)
        self.assertIn("-EvidenceFrameCadenceSeconds '0.5'", command.preview)
        self.assertIn("-NarrationStopAtNextTicketBoundary 'Off'", command.preview)

    def test_workflow_command_uses_default_input_folder_when_input_is_blank(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
        settings.update(
            {
                "input_path": "",
                "default_input_folder": r"C:\Users\Example\Videos",
                "output_folder": r"C:\Users\Example\Videos\Media Mangler",
            }
        )

        workflow_3 = build_workflow_command(settings, workflow="3")
        workflow_1_url = build_workflow_command({**settings, "input_kind": "url"}, workflow="1")

        self.assertIn("-InputPath", workflow_3.argv)
        self.assertIn(r"C:\Users\Example\Videos", workflow_3.argv)
        self.assertNotIn(r"C:\Users\Example\Videos", workflow_1_url.argv)

    def test_metadata_registry_has_tooltips_and_workflow_visibility(self) -> None:
        keys = [item.key for item in SETTING_METADATA]

        self.assertEqual(len(keys), len(set(keys)))
        for item in SETTING_METADATA:
            self.assertTrue(item.display_label.strip(), item.key)
            self.assertTrue(item.tooltip.strip(), item.key)
            self.assertTrue(item.category.strip(), item.key)
            self.assertTrue(item.control_type.strip(), item.key)
            self.assertTrue(item.workflows, item.key)

        workflow_3_keys = {item.key for item in metadata_for_workflow("3", include_advanced=False)}
        workflow_4_keys = {item.key for item in metadata_for_workflow("4", include_advanced=False)}
        self.assertIn("pre_context_seconds", workflow_3_keys)
        self.assertNotIn("archive_hash_mode", workflow_3_keys)
        self.assertIn("archive_hash_mode", workflow_4_keys)
        self.assertIn("fragmented_narration_mode", workflow_3_keys)
        self.assertIn("narration_context_preset", workflow_3_keys)
        self.assertNotIn("narration_context_pre_seconds", workflow_3_keys)

    def test_effective_sampling_estimate_reports_caps_and_independent_contexts(self) -> None:
        settings = build_default_settings(repo_root=r"C:\Repos\media-manglers")
        settings.update(
            {
                "pre_context_seconds": 90,
                "post_context_seconds": 120,
                "narration_context_pre_seconds": 120,
                "narration_context_post_seconds": 600,
                "fragmented_narration_mode": True,
                "evidence_frame_offsets": "-90,0,120",
                "evidence_frame_cadence_seconds": 0.5,
                "evidence_max_frames_per_candidate": 50,
                "evidence_max_items": 20,
                "evidence_panel_crops": "Auto",
            }
        )
        estimate = estimate_sampling(settings)

        self.assertEqual(estimate.visual_audio_window_seconds, 210)
        self.assertEqual(estimate.narration_context_seconds, 720)
        self.assertEqual(estimate.fixed_offset_frame_count, 3)
        self.assertGreater(estimate.requested_cadence_frame_count, 400)
        self.assertLessEqual(estimate.estimated_saved_full_frames_per_candidate, 50)
        self.assertTrue(estimate.cadence_is_capped)
        self.assertFalse(estimate.audio_would_exceed_cap)
        self.assertTrue(estimate.narration_extends_beyond_visual_audio)
        self.assertEqual(estimate.total_image_multiplier, 4)
        self.assertTrue(estimate.large_package_warning)

    def test_metadata_cli_flags_exist_in_video_mangler_param_block(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "Video Mangler.ps1"
        script_text = script_path.read_text(encoding="utf-8-sig")
        param_block = script_text.split("$ErrorActionPreference", 1)[0]
        param_names = set(re.findall(r"\$([A-Za-z][A-Za-z0-9]*)", param_block))
        metadata_flags = {item.cli_flag for item in SETTING_METADATA if item.cli_flag}

        missing = sorted(metadata_flags - param_names)
        self.assertEqual(missing, [])

    def test_video_player_metadata_entries_match_the_contract(self) -> None:
        player = METADATA_BY_KEY["video_player"]
        autoplay = METADATA_BY_KEY["video_autoplay"]
        defaults = build_default_settings(repo_root=r"C:\Repos\media-manglers")

        self.assertEqual(
            (player.cli_flag, player.display_label, player.category, player.control_type, player.default),
            ("", "Play videos with", "Video player", "choice", "internal"),
        )
        self.assertEqual(player.allowed_values, ("internal", "vlc", "system"))
        self.assertEqual(
            (autoplay.cli_flag, autoplay.display_label, autoplay.category, autoplay.control_type),
            ("", "Start playing straight away", "Video player", "bool"),
        )
        self.assertIs(autoplay.default, True)
        for item in (player, autoplay):
            self.assertEqual(item.workflows, ALL_WORKFLOWS, item.key)
            self.assertFalse(item.advanced, item.key)
            # One default, not two that can drift apart.
            self.assertEqual(defaults[item.key], item.default, item.key)
            for workflow in ALL_WORKFLOWS:
                visible = {meta.key for meta in metadata_for_workflow(workflow, include_advanced=False)}
                self.assertIn(item.key, visible, workflow)

    def test_video_player_wording_promises_only_what_this_release_has(self) -> None:
        tooltip = METADATA_BY_KEY["video_player"].tooltip.lower()

        # 125 Part 2 (Wave 8) added the waveforms and the moments, so the wording names them too.
        for promised in ("built-in player", "transcript lines", "track", "never-use", "waveforms", "moments"):
            self.assertIn(promised, tooltip)
        # Words the operator never sees.
        for key in ("video_player", "video_autoplay"):
            words = f"{METADATA_BY_KEY[key].display_label} {METADATA_BY_KEY[key].tooltip}".lower()
            for banned in ("envelope", "backend", "libvlc", "qmediaplayer", "coalesce"):
                self.assertNotIn(banned, words, key)

    def test_cleanup_only_targets_workbench_owned_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Workbench"
            logs = root / "logs"
            outside = Path(temp_dir) / "SourceVideos"
            logs.mkdir(parents=True)
            outside.mkdir()
            old_file = logs / "old.log"
            new_file = logs / "new.log"
            outside_file = outside / "clip.mp4"
            old_file.write_text("old", encoding="utf-8")
            new_file.write_text("new", encoding="utf-8")
            outside_file.write_text("video", encoding="utf-8")
            now = time.time()
            old_time = now - (30 * 86400)
            old_file.touch()
            new_file.touch()
            outside_file.touch()
            import os

            os.utime(old_file, (old_time, old_time))
            result = clean_workbench_owned_path(logs, owned_root=root, retention_days=14, now=now)

            self.assertEqual(result.deleted_files, 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
            self.assertTrue(outside_file.exists())
            with self.assertRaises(ValueError):
                clean_workbench_owned_path(outside, owned_root=root, retention_days=0, now=now)

    def test_fake_runner_success_failure_and_cancel(self) -> None:
        success_logs: list[tuple[str, str]] = []
        success = FakeRunner(stdout=["one", "two"]).run(["fake"], lambda stream, line: success_logs.append((stream, line)))
        self.assertEqual(success.status, "succeeded")
        self.assertEqual(success.exit_code, 0)
        self.assertEqual(success_logs, [("stdout", "one"), ("stdout", "two")])

        failure = FakeRunner(exit_code=7, stderr=["bad"]).run(["fake"])
        self.assertEqual(failure.status, "failed")
        self.assertEqual(failure.exit_code, 7)
        self.assertEqual(failure.stderr_lines, ["bad"])
        self.assertEqual(failure.error, "bad")

        download_failure = FakeRunner(
            exit_code=1,
            stdout=[
                "FAIL download https://example.invalid/video: HTTP Error 403: Forbidden"
            ],
        ).run(["fake"])
        self.assertIn("HTTP Error 403", download_failure.error)

        runner = FakeRunner(stdout=["a", "b", "c", "d"], delay_seconds=0.05)
        result_holder = {}

        def run_fake() -> None:
            result_holder["result"] = runner.run(["fake"])

        thread = threading.Thread(target=run_fake)
        thread.start()
        time.sleep(0.08)
        runner.cancel()
        thread.join(timeout=2)
        self.assertEqual(result_holder["result"].status, "cancelled")

    def test_evidence_parser_fixture_loading(self) -> None:
        package = load_evidence_package(FIXTURE_PACKAGE)

        self.assertEqual(package.root, FIXTURE_PACKAGE)
        self.assertEqual(len(package.candidates), 1)
        self.assertEqual(len(package.review_needed), 1)
        self.assertIn(
            "Legacy package: no v0.9.3 artifact-integrity attestation is available; paths and counts were not revalidated.",
            package.warnings,
        )
        candidate = package.candidates[0]
        self.assertEqual(candidate.item_id, "ticket-001")
        self.assertEqual(candidate.repo_hint, "owner/example-repo")
        self.assertIn("make this a ticket", candidate.transcript_window_text)
        self.assertTrue(candidate.frame_paths)
        self.assertTrue(candidate.panel_crop_paths)
        self.assertTrue(candidate.audio_paths)

    def test_prompt_draft_output_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "evidence_package"
            shutil.copytree(FIXTURE_PACKAGE, root)
            package = load_evidence_package(root)
            candidate = package.candidates[0]

            prompt = build_codex_prompt(package, candidate)
            paths = export_prompt_drafts(package, candidate)

            self.assertIn("Search existing issues in the target repository", prompt)
            self.assertIn("owner/example-repo", prompt)
            self.assertTrue(paths.codex_path.exists())
            self.assertTrue(paths.claude_path.exists())
            self.assertTrue(paths.handoff_path.exists())
            self.assertEqual(paths.codex_path.parent.name, "operator-drafts")
            self.assertIn("Codex: review one ticket candidate", paths.codex_path.read_text(encoding="utf-8"))
            self.assertIn(
                "Claude Code: review one ticket candidate",
                paths.claude_path.read_text(encoding="utf-8"),
            )
            self.assertIn("Read the candidate's `narration_context.md`", prompt)
            self.assertIn("shared full transcript", prompt)
            self.assertIn("driving pause", prompt)

            # issue 94: the prompt must be self-contained for a pasted hand-off.
            # The package root must be an absolute path the agent can resolve,
            # never the old "`..` relative to this file" form.
            self.assertIn(str(root.resolve()), prompt)
            self.assertNotIn("`..` relative to this file", prompt)

            # issue 94: the marker scan is a hint, and the agent must not write
            # to GitHub before the operator approves.
            self.assertIn("hint, not the finding", prompt)
            self.assertIn("do not treat the candidate list as the list of issues", prompt.lower())
            self.assertIn("Produce **draft GitHub issues**", prompt)
            self.assertIn("until the operator approves the list", prompt)

            handoff = json.loads(paths.handoff_path.read_text(encoding="utf-8"))
            self.assertTrue(handoff["local_evidence_access_required"])
            self.assertIn("required_review_steps", handoff)
            self.assertEqual(handoff["schema_version"], 2)
            self.assertEqual(handoff["evidence_package_root"], str(root.resolve()))
            self.assertNotEqual(handoff["evidence_package_root"], "..")
            self.assertFalse(handoff["detection_is_authoritative"])
            self.assertTrue(handoff["agent_must_present_before_writing"])
            self.assertIn("projects", handoff)

    def test_versioned_settings_bundle_round_trip_includes_profile_glossary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_manager = ProfileManager(root / "source-profiles", repo_root=str(root))
            source_manager.ensure_starter_profiles()
            settings = build_default_settings(repo_root=str(root))
            settings["evidence_transcription_glossary_entries"] = "Project Atlas=Project At Last"
            settings["recent_runs"] = [{"source": "private-path"}]
            source_manager.save("Custom Atlas", settings, workflow="3")
            bundle_path = export_settings_bundle(
                root / "bundle.json",
                settings,
                source_manager,
                repo_root=str(root),
            )
            payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], 2)
            self.assertEqual(payload["exportMode"], "portable")
            self.assertNotIn("recent_runs", payload["settings"])

            target_manager = ProfileManager(root / "target-profiles", repo_root=str(root))
            target_manager.ensure_starter_profiles()
            result = import_settings_bundle(
                bundle_path,
                build_default_settings(repo_root=str(root)),
                target_manager,
                repo_root=str(root),
            )
            self.assertEqual(
                result.settings["evidence_transcription_glossary_entries"],
                "Project Atlas=Project At Last",
            )
            self.assertEqual(result.imported_profile_names, ["Custom Atlas"])
            imported_profile = target_manager.load("Custom Atlas")
            self.assertEqual(
                imported_profile["evidence_transcription_glossary_entries"],
                "Project Atlas=Project At Last",
            )

    def test_workflow_command_forwards_glossary_metadata_audio_confirmation_and_debug(self) -> None:
        settings = build_default_settings(repo_root=str(Path.cwd()))
        settings.update(
            {
                "script_path": str(Path.cwd() / "Video Mangler.ps1"),
                "input_path": str(Path.cwd() / "synthetic.mkv"),
                "output_folder": str(Path.cwd() / "synthetic-output"),
                "evidence_transcription_glossary_entries": "Project Atlas=Project At Last",
                "evidence_audio_stream_index": 2,
                "evidence_audio_stream_selection_confirmed": True,
                "evidence_target_project": "Synthetic Dashboard",
                "debug_mode": True,
            }
        )
        command = build_workflow_command(settings, workflow="3")
        self.assertIn("-EvidenceTranscriptionGlossaryEntries", command.argv)
        self.assertIn("-EvidenceAudioStreamSelectionConfirmed", command.argv)
        self.assertIn("-EvidenceTargetProject", command.argv)
        self.assertIn("-DebugMode", command.argv)


if __name__ == "__main__":
    unittest.main()
