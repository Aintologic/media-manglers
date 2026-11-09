"""199: a line of narration that another track carries at the same moment (music played out loud,
the game, a spotter, voice chat) is not the operator's. Only Whisper is stood in for; the
recording, FFmpeg and the transcript files are real."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import cross_track_check  # noqa: E402
from media_manglers.core.transcripts import write_transcript_files  # noqa: E402

from tests.script_functions import function_text  # noqa: E402
from tests.test_track_roles_backend import _bursty, _recording  # noqa: E402

LYRIC = "la la la, an invented chorus line, sung loudly over the music track"
NARRATION = "the limiter light should stay on when I press the pit button"
NAMES = ("T1 - Full Mix", "T2 - Narration", "T3 - Game / Simulator", "T6 - Music")


def _detection(silent: tuple[int, ...] = ()) -> dict:
    roles = {"1": "full_mix", "2": "narration", "3": "never", "4": "never"}
    return {
        "status": "selected",
        "selected_ordinal": 1,
        "track_roles": roles,
        "tracks": [
            {"ordinal": ordinal, "track_number": ordinal + 1, "title": NAMES[ordinal], "silent": ordinal in silent}
            for ordinal in range(4)
        ],
    }


def _hearing(words_by_ordinal: dict[int, str]):
    """Whisper stood in for: a window cut from Track N answers with that track's words."""

    def transcriber(path: Path) -> list[dict[str, object]]:
        ordinal = int(Path(path).stem.split("-")[-1])
        text = words_by_ordinal.get(ordinal, "")
        return [{"text": text}] if text else []

    return transcriber


class TrackChoiceTests(unittest.TestCase):
    def test_only_tracks_that_are_never_narration_and_have_sound_are_compared(self) -> None:
        tracks = cross_track_check.tracks_to_compare(_detection(silent=(2,)))
        # Not the full mix (it carries the operator's voice too), not the narration track,
        # not the silent game track: only the music track.
        self.assertEqual([(item["track_number"], item["title"]) for item in tracks], [(4, "T6 - Music")])
        self.assertEqual(cross_track_check.tracks_to_compare(None), [])

    def test_the_line_needs_most_of_its_words_on_the_other_track(self) -> None:
        line = cross_track_check.distinctive_words(NARRATION)
        # Music with a couple of the same words is chance, not the same line.
        self.assertFalse(cross_track_check.heard_elsewhere(
            line, cross_track_check.distinctive_words("la la la, the light will stay on all night")))
        self.assertTrue(cross_track_check.heard_elsewhere(
            cross_track_check.distinctive_words(LYRIC), cross_track_check.distinctive_words(LYRIC + " oh yeah")))


class LevelRuleTests(unittest.TestCase):
    def test_a_line_from_faint_sound_while_another_track_is_loud_is_bleed(self) -> None:
        # Levels measured on a sample recording: lines spoken into the microphone peak at -20 to -32 dBFS;
        # lines written down from music bleeding into the microphone at -53 to -60 dBFS.
        self.assertTrue(cross_track_check.bled_from(-57.7, -19.3))
        self.assertFalse(cross_track_check.bled_from(-21.4, -23.2))   # a spoken request, over the game
        self.assertFalse(cross_track_check.bled_from(-45.4, -18.3))   # quiet, but louder than the cut-off
        self.assertFalse(cross_track_check.bled_from(-60.0, -50.0))   # quiet, but nothing loud elsewhere


class CrossCheckRunTests(unittest.TestCase):
    def test_a_lyric_heard_on_the_music_track_is_dropped_and_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Track 2: the operator speaks at 1-3 s; at 5-7 s only faint music reaches the microphone
            # (-60 dBFS, a level measured on a sample recording) while Track 4, the music, plays loud.
            narration = ("sine=frequency=300:sample_rate=48000:duration=20,"
                         "volume='if(between(t,1,3),1,if(between(t,5,7),0.001,0))':eval=frame")
            recording = _recording(root / "synthetic-session.mkv", [
                (_bursty(200, 0.0, 3.5), NAMES[0]), (narration, NAMES[1]),
                (_bursty(500, 0.0, 0.5), NAMES[2]), (_bursty(700, 0.0, 3.5), NAMES[3]),
            ])
            folder = root / "transcript" / "sources"
            write_transcript_files(folder, "s.transcript.json", "s.transcript.srt", "s.transcript.txt", {
                "language": "en",
                "segments": [
                    {"id": 0, "start": 1.0, "end": 3.0, "text": NARRATION},
                    {"id": 1, "start": 5.0, "end": 7.0, "text": LYRIC},
                    # Too few words to compare, but faint while the music plays: bleed too.
                    {"id": 2, "start": 5.5, "end": 6.5, "text": "la la la"},
                    # A short word while the operator is audibly speaking is the operator's.
                    {"id": 3, "start": 2.4, "end": 2.8, "text": "okay"},
                ],
            })
            (folder / "s.transcript.raw.json").write_text(json.dumps({"filtered_segments": []}), encoding="utf-8")
            (folder / "s.transcript.quality.json").write_text(json.dumps({"filtered_segment_count": 0}), encoding="utf-8")
            # The music track's words do not even match: Whisper hears music differently each time.
            with mock.patch.object(cross_track_check.voice_track, "whisper_transcriber",
                                   return_value=_hearing({3: "drums and guitar only", 2: "engine noise box box"})):
                result = cross_track_check.check_from_request({
                    "source_path": str(recording),
                    "ffmpeg_exe": shutil.which("ffmpeg"),
                    "transcript_json_path": str(folder / "s.transcript.json"),
                    "detection": _detection(),
                })
            delivered = json.loads((folder / "s.transcript.json").read_text(encoding="utf-8"))
            text = (folder / "s.transcript.txt").read_text(encoding="utf-8")
            srt = (folder / "s.transcript.srt").read_text(encoding="utf-8")
            raw = json.loads((folder / "s.transcript.raw.json").read_text(encoding="utf-8"))
            quality = json.loads((folder / "s.transcript.quality.json").read_text(encoding="utf-8"))
            leftovers = list(root.rglob("*-*.wav"))
        self.assertEqual(result["compared_tracks"], [3, 4])
        self.assertEqual([item["text"] for item in delivered["segments"]], [NARRATION, "okay"])
        self.assertEqual([item["id"] for item in delivered["segments"]], [0, 1])
        self.assertNotIn("invented chorus", text + srt)
        self.assertEqual(
            [(item["reason"], item["track_number"], item["track_title"], item["found_by"], item["segment"]["text"])
             for item in raw["filtered_segments"]],
            [("heard_on_another_track", 4, "T6 - Music", "level", LYRIC),
             ("heard_on_another_track", 4, "T6 - Music", "level", "la la la")],
        )
        self.assertEqual((quality["filtered_segment_count"], quality["heard_on_another_track_count"]), (2, 2))
        self.assertEqual(result["dropped"][0]["track_number"], 4)
        self.assertEqual([path.name for path in leftovers], [])

    def test_without_a_track_to_compare_nothing_is_changed_or_listened_to(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_transcript_files(folder, "s.transcript.json", "s.transcript.srt", "s.transcript.txt",
                                   {"segments": [{"id": 0, "start": 1.0, "end": 3.0, "text": LYRIC}]})
            before = (folder / "s.transcript.json").read_text(encoding="utf-8")
            with mock.patch.object(cross_track_check.voice_track, "whisper_transcriber") as loader:
                result = cross_track_check.check_from_request({
                    "source_path": str(folder / "missing.mkv"),
                    "transcript_json_path": str(folder / "s.transcript.json"),
                    "detection": {"track_roles": {"1": "auto", "2": "auto"}, "tracks": []},
                })
            self.assertEqual((folder / "s.transcript.json").read_text(encoding="utf-8"), before)
        loader.assert_not_called()
        self.assertEqual(result["dropped"], [])


class NearSilentNarrationTests(unittest.TestCase):
    """203: a line said where the narration track itself was near silent is not the operator's."""

    def test_the_cut_off_sits_between_invented_lines_and_quiet_real_speech(self) -> None:
        # Levels measured on a sample recording, on its narration track.
        for invented in (-48.2, -48.7, -49.0, -49.2, -60.0):
            self.assertTrue(cross_track_check.near_silent(invented), invented)
        for real in (-20.4, -28.7, -32.2, -45.4):   # -45.4: a short line said quietly
            self.assertFalse(cross_track_check.near_silent(real), real)

    def test_a_line_over_a_near_silent_narration_track_is_dropped_without_other_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Track 2 speaks at 1-3 s and is silent after; Track 1, the full mix, is never compared.
            narration = ("sine=frequency=300:sample_rate=48000:duration=20,"
                         "volume='if(between(t,1,3),1,0)':eval=frame")
            recording = _recording(root / "synthetic-session.mkv", [
                (_bursty(200, 0.0, 3.5), NAMES[0]), (narration, NAMES[1]),
            ])
            folder = root / "transcript" / "sources"
            write_transcript_files(folder, "s.transcript.json", "s.transcript.srt", "s.transcript.txt", {
                "language": "en",
                "segments": [
                    {"id": 0, "start": 1.0, "end": 3.0, "text": NARRATION},
                    {"id": 1, "start": 10.0, "end": 12.0, "text": "I hope you enjoyed it."},
                ],
            })
            (folder / "s.transcript.raw.json").write_text(json.dumps({"filtered_segments": []}), encoding="utf-8")
            (folder / "s.transcript.quality.json").write_text(json.dumps({"filtered_segment_count": 0}), encoding="utf-8")
            detection = {"status": "selected", "selected_ordinal": 1, "track_roles": {"1": "full_mix", "2": "narration"},
                         "tracks": [{"ordinal": 0, "track_number": 1, "title": NAMES[0]},
                                    {"ordinal": 1, "track_number": 2, "title": NAMES[1]}]}
            with mock.patch.object(cross_track_check.voice_track, "whisper_transcriber") as loader:
                result = cross_track_check.check_from_request({
                    "source_path": str(recording), "ffmpeg_exe": shutil.which("ffmpeg"),
                    "transcript_json_path": str(folder / "s.transcript.json"), "detection": detection,
                })
            delivered = json.loads((folder / "s.transcript.json").read_text(encoding="utf-8"))
            raw = json.loads((folder / "s.transcript.raw.json").read_text(encoding="utf-8"))
            quality = json.loads((folder / "s.transcript.quality.json").read_text(encoding="utf-8"))
        loader.assert_not_called()
        self.assertEqual([item["text"] for item in delivered["segments"]], [NARRATION])
        self.assertEqual([(item["reason"], item["track_number"], item["segment"]["text"]) for item in raw["filtered_segments"]],
                         [("narration_track_near_silent", 2, "I hope you enjoyed it.")])
        self.assertEqual((quality["filtered_segment_count"], quality["narration_near_silent_count"]), (1, 1))
        self.assertEqual(result["dropped"][0]["reason"], "narration_track_near_silent")


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
class WavSliceExtractorTests(unittest.TestCase):
    """226: the check can cut its lines from tracks already decoded in the one read, instead of
    seeking into the recording for every line and track."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        narration = ("sine=frequency=300:sample_rate=48000:duration=20,"
                     "volume='if(between(t,1,3),1,if(between(t,5,7),0.001,0))':eval=frame")
        self.recording = _recording(self.root / "synthetic-session.mkv", [
            (_bursty(200, 0.0, 3.5), NAMES[0]), (narration, NAMES[1]),
            (_bursty(500, 0.0, 0.5), NAMES[2]), (_bursty(700, 0.0, 3.5), NAMES[3]),
        ])
        from media_manglers.core.voice_track import extract_all_tracks

        self.wavs = extract_all_tracks(shutil.which("ffmpeg"), self.recording, 4, self.root / "decoded")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_slice_matches_the_recordings_own_read(self) -> None:
        import wave

        sliced = cross_track_check.wav_slice_extractor(self.wavs)
        seeked = cross_track_check._ffmpeg_extractor(shutil.which("ffmpeg"), self.recording)
        for ordinal, start, seconds in ((1, 1.0, 2.0), (1, 5.0, 2.0), (1, 9.7, 0.3), (3, 4.5, 3.0), (2, 0.0, 1.25),
                                        (0, 18.5, 1.5)):
            with self.subTest(ordinal=ordinal, start=start):
                a = sliced(ordinal, start, seconds, self.root / "cut" / f"slice-{ordinal}-{start}.wav")
                b = seeked(ordinal, start, seconds, self.root / "cut" / f"seek-{ordinal}-{start}.wav")
                with wave.open(str(a), "rb") as first, wave.open(str(b), "rb") as second:
                    self.assertEqual((first.getframerate(), first.getnchannels(), first.getsampwidth()), (16000, 1, 2))
                    self.assertEqual(first.getparams()[:3], second.getparams()[:3])
                    self.assertEqual(first.getnframes(), second.getnframes())
                self.assertLessEqual(abs(cross_track_check.peak_dbfs(a) - cross_track_check.peak_dbfs(b)), 0.5)

    def test_the_check_gives_the_same_result_from_decoded_tracks(self) -> None:
        segments = [
            {"id": 0, "start": 1.0, "end": 3.0, "text": NARRATION},
            {"id": 1, "start": 5.0, "end": 7.0, "text": LYRIC},
            {"id": 2, "start": 5.5, "end": 6.5, "text": "la la la"},
            # Every track is quiet here: the line was not said into the microphone.
            {"id": 3, "start": 3.6, "end": 3.95, "text": "I hope you enjoyed it."},
        ]
        tracks = cross_track_check.tracks_to_compare(_detection())
        hearing = _hearing({3: "drums and guitar only", 2: "engine noise box box"})
        results = []
        for name, extract in (("seek", cross_track_check._ffmpeg_extractor(shutil.which("ffmpeg"), self.recording)),
                              ("slice", cross_track_check.wav_slice_extractor(self.wavs))):
            work = self.root / name
            work.mkdir()
            kept, dropped = cross_track_check.cross_check_segments(segments, tracks, extract, hearing, work,
                                                                   narration_ordinal=1)
            results.append(([item["text"] for item in kept],
                            [(item["reason"], item["track_number"], item["found_by"], item["segment"]["text"])
                             for item in dropped]))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1][0], [NARRATION])
        self.assertEqual([item[0] for item in results[1][1]],
                         ["heard_on_another_track", "heard_on_another_track", "narration_track_near_silent"])

    def test_the_editor_hands_the_check_its_own_tracks_and_its_decoded_audio(self) -> None:
        # 226: the AI Video Editor's Prepare names the tracks to compare, cuts the lines from the
        # tracks its one read decoded, and hears how far the check has got. The result is the same.
        segments = [
            {"id": 0, "start": 1.0, "end": 3.0, "text": NARRATION},
            {"id": 1, "start": 5.0, "end": 7.0, "text": LYRIC},
            {"id": 2, "start": 5.5, "end": 6.5, "text": "la la la"},
            {"id": 3, "start": 3.6, "end": 3.95, "text": "I hope you enjoyed it."},
        ]
        heard: list[tuple[int, int]] = []
        editor = {"compare_tracks": [{"ordinal": 3, "track_number": 4, "title": NAMES[3]},
                                     {"ordinal": 2, "track_number": 3, "title": NAMES[2]}],
                  "extractor": cross_track_check.wav_slice_extractor(self.wavs),
                  "on_progress": lambda done, total: heard.append((done, total))}
        outcomes = []
        for label, options in (("default", {}), ("editor", editor)):
            folder = self.root / label
            write_transcript_files(folder, "s.transcript.json", "s.transcript.srt", "s.transcript.txt",
                                   {"language": "en", "segments": [dict(item) for item in segments]})
            (folder / "s.transcript.raw.json").write_text(json.dumps({"filtered_segments": []}), encoding="utf-8")
            (folder / "s.transcript.quality.json").write_text(json.dumps({"filtered_segment_count": 0}), encoding="utf-8")
            with mock.patch.object(cross_track_check.voice_track, "whisper_transcriber",
                                   return_value=_hearing({3: "drums and guitar only", 2: "engine noise box box"})):
                result = cross_track_check.check_from_request({
                    "source_path": str(self.recording), "ffmpeg_exe": shutil.which("ffmpeg"),
                    "transcript_json_path": str(folder / "s.transcript.json"), "detection": _detection(),
                }, **options)
            outcomes.append((result, json.loads((folder / "s.transcript.json").read_text(encoding="utf-8"))["segments"],
                             [(item["reason"], item["found_by"]) for item in
                              json.loads((folder / "s.transcript.raw.json").read_text(encoding="utf-8"))["filtered_segments"]]))
        self.assertEqual(outcomes[1], outcomes[0])
        self.assertEqual([item["text"] for item in outcomes[1][1]], [NARRATION])
        self.assertEqual(heard, [(1, 4), (2, 4), (3, 4), (4, 4)])

    def test_a_track_that_was_not_decoded_is_refused(self) -> None:
        extract = cross_track_check.wav_slice_extractor({1: self.wavs[1]})
        with self.assertRaises(RuntimeError) as caught:
            extract(3, 1.0, 1.0, self.root / "missing.wav")
        self.assertIn("Track 4", str(caught.exception))
        # A window past the end of the track is an empty cut, as FFmpeg makes it.
        past = extract(1, 30.0, 1.0, self.root / "past.wav")
        self.assertEqual(cross_track_check.peak_dbfs(past), -120.0)


class BackendWiringTests(unittest.TestCase):
    """The backend runs the check right after each transcript it writes, with this recording's own
    voice-track result."""

    def test_the_check_gets_the_transcript_and_this_recordings_tracks(self) -> None:
        from tests.test_track_roles_backend import _run

        import tests.test_track_roles_backend as backend

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            backend, "FUNCTIONS", ("Invoke-MMNarrationCrossCheck",)
        ):
            result = _run(
                """
                $script:payloads = @()
                function Invoke-MediaManglersPythonCli { param($PythonCommand, $Command, $StepName, $HeartbeatSeconds, $TimeoutSeconds, $Payload)
                    $script:payloads += [pscustomobject]@{ command = $Command; payload = $Payload }
                    return [pscustomobject]@{ Result = [pscustomobject]@{ ok = $true; data = [pscustomobject]@{ dropped = @() } } }
                }
                $detection = [pscustomobject]@{ selected_ordinal = 1; track_roles = [pscustomobject]@{ '4' = 'never' }; tracks = @() }
                $null = Invoke-MMNarrationCrossCheck -PythonCommand 'py' -FFmpegExe 'ffmpeg' -VideoPath 'x.mkv' -TranscriptJsonPath 'x.transcript.json' -Detection $detection
                $null = Invoke-MMNarrationCrossCheck -PythonCommand 'py' -FFmpegExe 'ffmpeg' -VideoPath 'y.mkv' -TranscriptJsonPath 'y.transcript.json' -Detection $null
                $sent = $script:payloads[0]
                [ordered]@{ count = @($script:payloads).Count; command = $sent.command; json = $sent.payload.transcript_json_path;
                            model = $sent.payload.model_name; video = $sent.payload.source_path } | ConvertTo-Json -Compress
                """,
                Path(temp),
            )
        self.assertEqual(result, {"count": 1, "command": "narration-cross-check", "json": "x.transcript.json",
                                  "model": "base.en", "video": "x.mkv"})

    def test_the_evidence_run_checks_each_new_transcript_with_its_own_result(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        body = function_text(script, "Invoke-CodexEvidencePackageBatch")
        written = body.index("Set-MMTranscribedTrack -JsonPath $jsonPath")
        checked = body.index("Invoke-MMNarrationCrossCheck", written)
        self.assertLess(checked - written, 400)
        self.assertIn("-TranscriptJsonPath $jsonPath -Detection $voiceDetection", body)
        reset = body.index("$voiceDetection = $null")
        self.assertLess(reset, body.index("Read-MMSavedVoiceDetection -Path $voiceCachePath"))


if __name__ == "__main__":
    unittest.main()
