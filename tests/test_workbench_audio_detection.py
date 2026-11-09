from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers_workbench.audio_detection import (  # noqa: E402
    AudioSampleFeatures,
    AudioStreamInfo,
    AUDIBLE_PEAK_DBFS,
    AUDIBILITY_CONTRACT_VERSION,
    LayoutConfirmationStore,
    NOISE_FLOOR_PEAK_DBFS,
    SAFE_CONFIDENCE_THRESHOLD,
    SourceAudioInspection,
    VoiceEnrollmentStore,
    activity_scan_starts,
    aggregate_region_features,
    analyze_wav,
    apply_selection_precedence,
    cleanup_preview_files,
    decode_full_stream_audibility,
    extract_sample,
    inspect_source,
    layout_fingerprint,
    rank_streams,
)
from media_manglers_workbench.settings import (  # noqa: E402
    ProfileManager,
    build_default_settings,
    export_settings_bundle,
)


def _six_tracks() -> list[AudioStreamInfo]:
    return [
        AudioStreamInfo(
            ordinal=index,
            stream_index=index + 1,
            title=f"Track{index + 1}",
            codec="aac",
            channels=2,
            channel_layout="stereo",
            sample_rate=44100,
        )
        for index in range(6)
    ]


class WorkbenchAudioDetectionTests(unittest.TestCase):
    @staticmethod
    def _write_pcm_wav(path: Path, samples: list[int]) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    def test_exact_zero_quiet_signal_noise_floor_and_inconclusive_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = {
                "zero": ([0] * 16000, "digital_silence"),
                "codec-noise": (
                    [1 if index % 2 else -1 for index in range(16000)],
                    "below_noise_floor",
                ),
                "boundary": (
                    [
                        (6 if (index // 100) % 2 else -6)
                        if index % 100 == 0
                        else 0
                        for index in range(16000)
                    ],
                    "inconclusive",
                ),
                "quiet-signal": (
                    [
                        int(12 * math.sin(2 * math.pi * 220 * index / 16000))
                        for index in range(16000)
                    ],
                    "audible_signal",
                ),
            }
            observed = {}
            for name, (samples, expected) in cases.items():
                path = root / f"{name}.wav"
                self._write_pcm_wav(path, samples)
                features = analyze_wav(path)
                observed[name] = features
                self.assertEqual(features.audibility_state, expected, name)
                self.assertEqual(features.sample_count, 16000)
            self.assertEqual(observed["zero"].nonzero_sample_count, 0)
            self.assertGreater(
                observed["quiet-signal"].peak_dbfs,
                AUDIBLE_PEAK_DBFS,
            )
            self.assertLessEqual(
                observed["codec-noise"].peak_dbfs,
                NOISE_FLOOR_PEAK_DBFS,
            )

    def test_vlc_labels_are_one_based_while_ffmpeg_ordinals_are_zero_based(self) -> None:
        stream = AudioStreamInfo(1, 2, title="Track2", codec="aac", channels=2)
        self.assertEqual(stream.human_label, "Track 2")
        self.assertEqual(stream.human_track_number, 2)
        self.assertEqual(stream.ordinal, 1)
        self.assertEqual(stream.ffmpeg_map, "0:a:1")

    def test_stable_six_track_layout_fingerprint_and_saved_mapping_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            streams = _six_tracks()
            fingerprint = layout_fingerprint(streams, "OBS Studio")
            self.assertEqual(fingerprint, layout_fingerprint(_six_tracks(), "OBS Studio"))
            inspection = SourceAudioInspection(
                Path("synthetic.mkv"), streams, [], fingerprint, "OBS Studio", 60.0
            )
            store = LayoutConfirmationStore(Path(temporary) / "narration-layouts.json")
            store.confirm(inspection, 1, profile_name="Custom recording profile")
            saved = store.match(fingerprint)
            self.assertEqual(saved["humanTrackNumber"], 2)
            self.assertEqual(saved["audioOrdinal"], 1)
            self.assertEqual(saved["ffmpegMap"], "0:a:1")
            self.assertEqual(saved["streamCount"], 6)

    def test_changed_layout_invalidates_saved_fingerprint(self) -> None:
        original = _six_tracks()
        changed = _six_tracks()[:-1]
        self.assertNotEqual(
            layout_fingerprint(original, "OBS Studio"),
            layout_fingerprint(changed, "OBS Studio"),
        )

    def test_layout_store_rejects_a_silent_track_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stream = AudioStreamInfo(0, 1, title="Silent")
            inspection = SourceAudioInspection(
                source=Path("silent.mkv"),
                streams=[stream],
                ranked=[],
                layout_fingerprint=layout_fingerprint([stream], "Recorder"),
                recorder_profile="Recorder",
                duration_seconds=30.0,
                audibility_state="no_audible_narration",
                stream_audibility={
                    0: {
                        "audio_ordinal": 0,
                        "final_state": "digital_silence",
                    }
                },
            )
            store = LayoutConfirmationStore(
                Path(temporary) / "layouts.json"
            )
            with self.assertRaisesRegex(
                ValueError,
                "no confirmed audible signal",
            ):
                store.confirm(inspection, 0)
            self.assertFalse(store.path.exists())

    def test_saved_layout_precedes_profile_preference_and_changed_layout_does_not_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            streams = _six_tracks()
            recommendation = rank_streams(
                streams,
                {stream.ordinal: AudioSampleFeatures() for stream in streams},
            )
            inspection = SourceAudioInspection(
                Path("current.mkv"),
                streams,
                recommendation,
                layout_fingerprint(streams, "Recorder A"),
                "Recorder A",
                60.0,
            )
            store = LayoutConfirmationStore(Path(temporary) / "layouts.json")
            store.confirm(inspection, 1, profile_name="Synthetic profile")
            apply_selection_precedence(
                inspection,
                saved_layout=store.match(inspection.layout_fingerprint),
                preferred_track_number=4,
            )
            self.assertEqual(inspection.selected_ordinal, 1)
            self.assertEqual(inspection.selection_reason, "exact saved-layout match")
            self.assertTrue(inspection.resolved)

            changed_streams = streams[:-1]
            changed = SourceAudioInspection(
                Path("changed.mkv"),
                changed_streams,
                recommendation[: len(changed_streams)],
                layout_fingerprint(changed_streams, "Recorder A"),
                "Recorder A",
                60.0,
            )
            self.assertIsNone(store.match(changed.layout_fingerprint))
            apply_selection_precedence(
                changed,
                saved_layout=store.match(changed.layout_fingerprint),
                preferred_track_number=4,
            )
            self.assertEqual(changed.selected_ordinal, 3)
            self.assertEqual(changed.selection_reason, "profile preference")
            self.assertFalse(changed.resolved)

            manager = ProfileManager(Path(temporary) / "profiles", repo_root=str(REPO_ROOT))
            manager.ensure_starter_profiles()
            profile_settings = build_default_settings(repo_root=str(REPO_ROOT))
            profile_settings["preferred_narration_track_number"] = 4
            manager.save("Synthetic preferred narration", profile_settings, workflow="3")
            loaded = manager.load("Synthetic preferred narration")
            self.assertEqual(loaded["preferred_narration_track_number"], 4)

    def test_combined_mix_and_spotter_speech_rank_below_clean_microphone(self) -> None:
        streams = [
            AudioStreamInfo(0, 1, title="Combined Mix", channels=2, channel_layout="stereo"),
            AudioStreamInfo(1, 2, title="Microphone", channels=1, channel_layout="mono"),
            AudioStreamInfo(2, 3, title="Crew Chief Voice", channels=2, channel_layout="stereo"),
        ]
        features = {
            0: AudioSampleFeatures(0.65, 0.90, 0.96, 0.80, 0.75, 7.0, 0.08, -15.0, (0.3, 0.5, 0.4, 0.6)),
            1: AudioSampleFeatures(0.88, 0.28, 0.70, 0.02, 0.03, 27.0, 0.06, -24.0, (0.0, 0.7, 0.0, 0.8)),
            2: AudioSampleFeatures(0.82, 0.20, 0.75, 0.01, 0.02, 24.0, 0.06, -28.0, (0.6, 0.0, 0.7, 0.0)),
        }
        ranked = rank_streams(streams, features)
        self.assertEqual(ranked[0].stream.human_label, "Track 2")
        self.assertGreater(ranked[0].score, next(item.score for item in ranked if item.stream.ordinal == 0))

    def test_generated_same_narration_with_continuous_mix_ranks_clean_mic_higher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample_rate = 16000
            frame_count = sample_rate * 4
            narration: list[int] = []
            mixed: list[int] = []
            for index in range(frame_count):
                seconds = index / sample_rate
                speaking = int(seconds * 4) % 2 == 0
                voice = int(11000 * math.sin(2 * math.pi * 210 * seconds)) if speaking else 0
                continuous = int(5500 * math.sin(2 * math.pi * 520 * seconds))
                narration.append(voice)
                mixed.append(max(-32768, min(32767, voice + continuous)))

            def write_wav(path: Path, samples: list[int]) -> None:
                with wave.open(str(path), "wb") as writer:
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(sample_rate)
                    writer.writeframes(struct.pack(f"<{len(samples)}h", *samples))

            clean_path = root / "clean-microphone.wav"
            mixed_path = root / "narration-plus-continuous-audio.wav"
            write_wav(clean_path, narration)
            write_wav(mixed_path, mixed)
            streams = [
                AudioStreamInfo(0, 1, title="Track1", channels=1, channel_layout="mono"),
                AudioStreamInfo(1, 2, title="Track2", channels=1, channel_layout="mono"),
            ]
            ranked = rank_streams(
                streams,
                {0: analyze_wav(clean_path), 1: analyze_wav(mixed_path)},
            )
            self.assertEqual(ranked[0].stream.ordinal, 0)
            self.assertGreater(ranked[0].score, ranked[1].score)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "FFmpeg and FFprobe are required for the real multi-stream fixture.",
    )
    def test_real_ffmpeg_six_stream_fixture_preserves_mapping_and_audibility(
        self,
    ) -> None:
        ffmpeg = str(shutil.which("ffmpeg"))
        ffprobe = str(shutil.which("ffprobe"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "six-stream-audibility.mkv"
            inputs = [
                "color=c=black:s=320x180:r=10:d=10",
                "anullsrc=r=16000:cl=mono:d=10",
                "sine=frequency=330:sample_rate=16000:duration=10",
                (
                    "aevalsrc=if(lt(mod(t\\,2)\\,0.6)\\,"
                    "0.05*sin(2*PI*220*t)\\,0):s=16000:d=10"
                ),
                "sine=frequency=880:sample_rate=16000:duration=10",
                (
                    "aevalsrc=if(lt(t\\,7)\\,0\\,"
                    "0.05*sin(2*PI*700*t)):s=16000:d=10"
                ),
                "sine=frequency=1230:sample_rate=16000:duration=10",
            ]
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
            for index, value in enumerate(inputs):
                command.extend(
                    [
                        "-f",
                        "lavfi",
                        "-i",
                        value,
                    ]
                )
            command.extend(
                [
                    "-filter:a:1",
                    "volume=0.00025",
                    "-filter:a:5",
                    "volume=0.01",
                    "-map",
                    "0:v:0",
                ]
            )
            for input_index in range(1, 7):
                command.extend(["-map", f"{input_index}:a:0"])
            command.extend(
                [
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(source),
                ]
            )
            subprocess.run(command, check=True, capture_output=True)

            inspection = inspect_source(
                ffprobe,
                ffmpeg,
                source,
                root / "inspection",
            )
            self.assertEqual(
                inspection.audibility_contract_version,
                AUDIBILITY_CONTRACT_VERSION,
            )
            self.assertEqual(inspection.audibility_state, "audible_candidates")
            self.assertEqual(
                [
                    (
                        stream.human_track_number,
                        stream.ordinal,
                        stream.stream_index,
                        stream.ffmpeg_map,
                    )
                    for stream in inspection.streams
                ],
                [
                    (1, 0, 1, "0:a:0"),
                    (2, 1, 2, "0:a:1"),
                    (3, 2, 3, "0:a:2"),
                    (4, 3, 4, "0:a:3"),
                    (5, 4, 5, "0:a:4"),
                    (6, 5, 6, "0:a:5"),
                ],
            )
            final_states = [
                inspection.stream_audibility[index]["final_state"]
                for index in range(6)
            ]
            self.assertEqual(final_states[0], "digital_silence")
            self.assertEqual(final_states[1], "below_noise_floor")
            self.assertEqual(
                final_states[2:],
                ["audible_signal"] * 4,
            )
            self.assertTrue(
                inspection.stream_audibility[0]["full_source_checked"]
            )
            self.assertTrue(
                inspection.stream_audibility[1]["full_source_checked"]
            )
            self.assertEqual(
                inspection.stream_audibility[4]["bounded_state"],
                "audible_signal",
            )

            bounded_hashes: list[str] = []
            for stream in inspection.streams:
                region = inspection.preview_regions[stream.ordinal][0]
                generated = root / "generated" / f"track-{stream.ordinal}.wav"
                independent = (
                    root / "independent" / f"track-{stream.ordinal}.wav"
                )
                extract_sample(
                    ffmpeg,
                    source,
                    stream.ordinal,
                    generated,
                    duration_seconds=region.duration_seconds,
                    source_duration_seconds=inspection.duration_seconds,
                    start_seconds=region.start_seconds,
                )
                independent.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        f"{region.start_seconds:.3f}",
                        "-t",
                        f"{region.duration_seconds:.3f}",
                        "-i",
                        str(source),
                        "-map",
                        f"0:{stream.stream_index}",
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-c:a",
                        "pcm_s16le",
                        str(independent),
                    ],
                    check=True,
                    capture_output=True,
                )
                generated_hash = hashlib.sha256(
                    generated.read_bytes()
                ).hexdigest()
                self.assertEqual(
                    generated_hash,
                    hashlib.sha256(independent.read_bytes()).hexdigest(),
                )
                bounded_hashes.append(generated_hash)
            self.assertEqual(len(set(bounded_hashes)), 6)

            late_metrics = decode_full_stream_audibility(
                ffmpeg,
                source,
                4,
            )
            self.assertEqual(late_metrics.audibility_state, "audible_signal")
            self.assertGreater(late_metrics.nonzero_sample_count, 0)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "FFmpeg and FFprobe are required for the silent multi-stream fixture.",
    )
    def test_real_ffmpeg_silent_six_stream_checks_every_complete_stream(
        self,
    ) -> None:
        ffmpeg = str(shutil.which("ffmpeg"))
        ffprobe = str(shutil.which("ffprobe"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "silent-six-stream.mkv"
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x180:r=10:d=3",
                ]
            )
            for _index in range(6):
                command.extend(
                    [
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=16000:cl=mono:d=3",
                    ]
                )
            command.extend(["-map", "0:v:0"])
            for input_index in range(1, 7):
                command.extend(["-map", f"{input_index}:a:0"])
            command.extend(
                [
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(source),
                ]
            )
            subprocess.run(command, check=True, capture_output=True)

            inspection = inspect_source(
                ffprobe,
                ffmpeg,
                source,
                root / "inspection",
            )
            self.assertEqual(
                inspection.audibility_state,
                "no_audible_narration",
            )
            self.assertEqual(
                inspection.confirmation_state,
                "no-audible-narration",
            )
            self.assertIsNone(inspection.selected_ordinal)
            self.assertEqual(
                [
                    inspection.stream_audibility[index]["final_state"]
                    for index in range(6)
                ],
                ["digital_silence"] * 6,
            )
            self.assertTrue(
                all(
                    inspection.stream_audibility[index][
                        "full_source_checked"
                    ]
                    for index in range(6)
                )
            )
            manifest = inspection.audibility_manifest()
            self.assertTrue(manifest["full_source_check_completed"])

    def test_contains_speech_is_not_treated_as_operator_certainty(self) -> None:
        streams = [AudioStreamInfo(0, 1, title="Track1"), AudioStreamInfo(1, 2, title="Track2")]
        same = AudioSampleFeatures(0.85, 0.30, 0.70, 0.0, 0.0, 24.0, 0.06, -25.0, (0.0, 0.7, 0.1, 0.8))
        ranked = rank_streams(streams, {0: same, 1: same})
        self.assertLess(ranked[0].confidence, SAFE_CONFIDENCE_THRESHOLD)

    def test_activity_scan_and_three_region_aggregation_are_deterministic(self) -> None:
        starts = activity_scan_starts(900.0)
        self.assertGreaterEqual(len(starts), 3)
        self.assertLessEqual(len(starts), 12)
        self.assertEqual(starts[0], 0.0)
        self.assertAlmostEqual(starts[-1], 896.0)
        combined = aggregate_region_features(
            [
                AudioSampleFeatures(speech_activity=0.8, active_ratio=0.2, envelope=(0.0, 0.5)),
                AudioSampleFeatures(speech_activity=0.6, active_ratio=0.4, envelope=(0.1, 0.7)),
            ]
        )
        self.assertEqual(combined.speech_activity, 0.7)
        self.assertEqual(combined.active_ratio, 0.3)
        self.assertTrue(combined.envelope)

    def test_optional_voice_enrollment_only_adjusts_ranking(self) -> None:
        operator = AudioSampleFeatures(0.90, 0.25, 0.65, 0.0, 0.0, 28.0, 0.05, -22.0, (0.0, 0.7, 0.0, 0.8))
        other_voice = AudioSampleFeatures(0.70, 0.85, 0.95, 0.2, 0.4, 5.0, 0.20, -8.0, (0.8, 0.7, 0.9, 0.8))
        streams = [AudioStreamInfo(0, 1, title="Track1"), AudioStreamInfo(1, 2, title="Track2")]
        ranked = rank_streams(
            streams,
            {0: other_voice, 1: operator},
            voice_signature=operator.voice_vector(),
        )
        self.assertEqual(ranked[0].stream.ordinal, 1)
        self.assertGreater(ranked[0].voice_match, 0.95)

    def test_voice_signature_is_local_vector_only_and_excluded_from_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voice_store = VoiceEnrollmentStore(root / "private" / "voice-enrollment.json")
            voice_store.save_features(AudioSampleFeatures(0.9, 0.3, 0.7, 0.0, 0.0, 25.0, 0.05, -20.0))
            payload = json.loads(voice_store.path.read_text(encoding="utf-8"))
            self.assertIn("voiceVector", payload)
            self.assertNotIn("source", payload)
            self.assertNotIn("path", payload)

            manager = ProfileManager(root / "profiles", repo_root=str(REPO_ROOT))
            manager.ensure_starter_profiles()
            settings = build_default_settings(repo_root=str(REPO_ROOT))
            settings["voice_signature"] = [1, 2, 3]
            settings["narration_layouts"] = {"private": True}
            bundle = export_settings_bundle(root / "bundle.json", settings, manager, repo_root=str(REPO_ROOT))
            exported_text = bundle.read_text(encoding="utf-8")
            self.assertNotIn("voice_signature", exported_text)
            self.assertNotIn("narration_layouts", exported_text)
            self.assertNotIn("voiceVector", exported_text)

    def test_mixed_layout_batch_requires_per_layout_resolution(self) -> None:
        layout_a = layout_fingerprint(_six_tracks(), "Recorder A")
        layout_b = layout_fingerprint(_six_tracks()[:-1], "Recorder A")
        self.assertEqual(len({layout_a, layout_a}), 1)
        self.assertEqual(len({layout_a, layout_b}), 2)

    def test_preview_cleanup_removes_only_the_preview_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preview = root / "workbench-temp" / "audio-previews"
            preview.mkdir(parents=True)
            (preview / "track-2.wav").write_bytes(b"temporary")
            sibling = root / "keep.txt"
            sibling.write_text("keep", encoding="utf-8")
            cleanup_preview_files(preview)
            self.assertFalse(preview.exists())
            self.assertTrue(sibling.exists())

    def test_backend_detects_voice_per_recording_never_silently_track_1_and_app_imports_detector(self) -> None:
        # 94: an unconfirmed multi-track recording is resolved by per-recording
        # voice detection; when that is uncertain the recording is refused.
        script = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        app = (REPO_ROOT / "src" / "media_manglers_workbench" / "app.py").read_text(encoding="utf-8")
        self.assertIn('-Command "voice-track-detect"', script)
        self.assertIn("The backend will not silently use Track 1", script)
        self.assertIn("EvidenceAudioStreamSelectionsJson", script)
        self.assertIn("from .audio_detection import", app)
        self.assertIn("Auto-detect and confirm", app)


if __name__ == "__main__":
    unittest.main()
