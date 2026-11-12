"""Wave 7 (226): the AI Video Editor's Prepare on the shared engine.

Real FFmpeg on small synthetic recordings made with lavfi, with titled audio tracks, through the real
race-video-prepare handler. Whisper is not in the test runtime: most runs skip the transcript, and the
runs that write one stand Whisper in through sys.modules, so the shared Whisper helper itself runs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import wave

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import frame_render, voice_track  # noqa: E402
from media_manglers.core import raw_bin_library  # noqa: E402
from media_manglers.core.race_video import analysis, game_speech, project as project_module  # noqa: E402
from media_manglers.core.race_video import requests as race_requests  # noqa: E402
from media_manglers.core.race_video.timeline import DEFAULT_LAYOUT, SCHEMA  # noqa: E402
from media_manglers.core.spelling_words import SETTING_KEY as WORDS_KEY  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from tests.whisper_test_models import checked_whisper  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
# One picture, measured whole: a recording that is not 5760x1080.
SINGLE = {"width": 320, "height": 180, "panels": {"center": [0, 0, 320, 180]}}
NAMED = [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"), ("game", "T3 - Game"), ("music", "T4 - Music")]
# Six tracks with OBS's own names, which say nothing about what each one carries (226).
OBS_SIX = [("mix", "Track1"), ("narration", "Track2"), ("game", "Track3"), ("engine", "Track4"), ("music", "Track5"),
           ("music", "Track6")]
# A Narration track setting that names the game track and sets two others as Never narration (226).
NEVER_ROLES = "1=full_mix,2=narration,3=game,5=never,6=never"
# The same with no game role, as settings made before Wave 6 were: Never narration was the game track then.
OLDER_ROLES = "1=full_mix,2=narration,5=never,6=never"
NEVER_GAME_REFUSAL = ("Track 6 is set as Never narration in your Narration track setting (it may be music), and the "
                      "setting names Track 3 as your game sound; choose Track 3, or change the setting.")
# Whisper's numbers for a plain, confident decode.
REAL = {"temperature": 0.0, "avg_logprob": -0.3, "no_speech_prob": 0.05, "compression_ratio": 1.2}
SENTENCES = ["here we go into turn one", "the rear tyres are going off now", "braking a little later for the hairpin",
             "that car behind is getting closer", "the pit window opens next lap", "holding the inside line here",
             "fuel looks fine for the finish", "one more push through the last sector"]


def _sources(seconds: int) -> dict[str, str]:
    return {
        "narration": (f"sine=frequency=300:sample_rate=48000:duration={seconds},"
                      "volume='if(lt(mod(t,4),1.2),1,0)':eval=frame"),
        # Falls quiet while the narration speaks, so it never sounds like a route of the microphone.
        "game": (f"anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={seconds},"
                 "volume='if(lt(mod(t,4),1.5),0.001,1)':eval=frame"),
        # The engine all race long, never quiet: dead time can only come from the picture.
        "engine": f"anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={seconds}",
        # A tune that comes and goes: a steady tone has no activity at all, by the shared rule.
        "music": (f"sine=frequency=700:sample_rate=48000:duration={seconds},"
                  "volume='if(lt(mod(t,3),2),1,0.02)':eval=frame"),
        "mix": f"anoisesrc=color=brown:amplitude=0.2:sample_rate=48000:duration={seconds}",
        "silent": f"anullsrc=r=48000:cl=mono:d={seconds}",
        # A microphone barely on from 2 to 5 s (about -48 dBFS: heard, but not said into it), then a
        # loud short burst from 8 to 9.5 s (about -21 dBFS): a reaction.
        "reaction": (f"sine=frequency=300:sample_rate=48000:duration={seconds},"
                     "volume='if(between(t,2,5),0.045,if(between(t,8,9.5),1,0))':eval=frame"),
    }


def editor_recording(path: Path, tracks: list[tuple[str, str]], *, seconds: int = 20,
                     frozen: tuple[int, int] | None = None) -> Path:
    """A 320x180 recording with a keyframe every 2 s and these (kind, track name) audio tracks. Kinds:
    "narration" (a tone, 1.2 s of every 4 s), "game" (pink noise, quiet while the narration speaks),
    "engine" (steady pink noise),
    "music" (a tone that comes and goes), "mix" (steady brown noise), "silent", "reaction" (a faint
    tone, then a loud short burst). With ``frozen`` (start, end) the picture stands still between those
    seconds (colour bars) and moves before and after."""

    path.parent.mkdir(parents=True, exist_ok=True)
    command = [FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=10:d={seconds}"]
    first_audio = 1
    if frozen:
        command += ["-f", "lavfi", "-i", f"smptebars=s=320x180:r=10:d={seconds}"]
        first_audio = 2
    sources = _sources(seconds)
    for kind, _title in tracks:
        command += ["-f", "lavfi", "-i", sources[kind]]
    if frozen:
        start, end = frozen
        command += ["-filter_complex", f"[1:v][0:v]overlay=enable='not(between(t,{start},{end}))',format=yuv420p[v]",
                    "-map", "[v]"]
    else:
        command += ["-map", "0:v"]
    for index in range(len(tracks)):
        command += ["-map", f"{first_audio + index}:a"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-g", "20", "-pix_fmt", "yuv420p", "-c:a", "flac"]
    for index, (_kind, title) in enumerate(tracks):
        if title:
            command += [f"-metadata:s:a:{index}", f"title={title}"]
    subprocess.run([*command, "-t", str(seconds), str(path)], check=True)
    return path


class FFmpegReads:
    """Notes every program the code starts (``subprocess.Popen``, which ``subprocess.run`` uses too)."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __enter__(self) -> "FFmpegReads":
        real = subprocess.Popen
        seen = self.commands

        class Counting(real):  # type: ignore[misc, valid-type]
            def __init__(self, args, *rest, **options) -> None:
                seen.append([str(part) for part in args] if isinstance(args, (list, tuple)) else [str(args)])
                super().__init__(args, *rest, **options)

        self._patch = mock.patch.object(subprocess, "Popen", Counting)
        self._patch.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._patch.stop()

    def of(self, source: Path) -> list[list[str]]:
        """FFmpeg runs that read ``source``."""

        return [command for command in self.commands if Path(command[0]).stem.lower() == "ffmpeg"
                and "-i" in command and str(source) in command]

    def full_reads(self, source: Path) -> int:
        """Runs that read the whole recording: those that do not seek in first (a still)."""

        return sum(1 for command in self.of(source) if "-ss" not in command[:command.index("-i")])

    def seeks(self, source: Path) -> int:
        return sum(1 for command in self.of(source) if "-ss" in command[:command.index("-i")])


class _Settings:
    """Points the saved Workbench settings at a folder of the test's own (none unless written)."""

    def __init__(self, root: Path) -> None:
        self.root = root / "appdata"
        self._patch = mock.patch.dict(os.environ, {"MEDIA_MANGLERS_WORKBENCH_APPDATA": str(self.root)})

    def write(self, **settings) -> None:
        path = self.root / "MediaManglers" / "workbench" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schemaVersion": 1, "settings": settings}), encoding="utf-8")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class PrepareTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = _Settings(self.root)
        self.settings._patch.start()

    def tearDown(self) -> None:
        self.settings._patch.stop()
        self.temp.cleanup()

    def payload(self, source: Path, **extra) -> dict:
        return {"source": str(source), "output_root": str(self.root / "out"), "budget": "light", "layout": SINGLE,
                "privacy_masks": {}, "skip_transcript": True, "track_roles": "", "ffmpeg": FFMPEG, "ffprobe": FFPROBE,
                **extra}

    def prepare(self, source: Path, **extra) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return race_requests.prepare_from_request(self.payload(source, **extra))

    def meta(self, result: dict) -> dict:
        return json.loads((Path(result["project"]) / "project.json").read_text(encoding="utf-8"))

    def analysis(self, result: dict) -> dict:
        return json.loads((Path(result["project"]) / "analysis" / "analysis.json").read_text(encoding="utf-8"))


class SpeechFactsTests(PrepareTestCase):
    """264: your answer and the stored pick reach Prepare, and its one read keeps every track's moments."""

    def test_your_answer_from_another_screen_is_the_voice_and_beats_the_track_names(self) -> None:
        from media_manglers.core import speech_facts

        source = editor_recording(self.root / "named.mkv", [("narration", "T1 - Mic"), ("narration", "T2 - Narration"), ("game", "T3 - Game")])
        speech_facts.confirm_track(source, 1, by=speech_facts.ANSWERED_ON_BUGS)
        result = self.prepare(source)
        tracks = self.meta(result)["tracks"]
        self.assertEqual((tracks["voice"], tracks["voice_decided_by"]), (0, "override"))

    def test_your_answer_on_a_track_that_can_never_be_the_voice_stops_at_the_plain_message(self) -> None:
        from media_manglers.core import speech_facts

        source = editor_recording(self.root / "named.mkv", NAMED)
        speech_facts.confirm_track(source, 3, by=speech_facts.ANSWERED_ON_BUGS)
        with self.assertRaisesRegex(ValueError, "^Choose the voice track: Track 3"):
            self.prepare(source)

    def test_the_one_read_keeps_every_tracks_moments_with_nothing_for_an_agent(self) -> None:
        from media_manglers.core import speech_facts

        source = editor_recording(self.root / "named.mkv", NAMED)
        result = self.prepare(source)
        measure = speech_facts.known_measure(source)
        self.assertEqual(measure.measured_by, "editor")
        self.assertEqual(sorted(measure.tracks), [1, 2, 3, 4])
        for path in Path(result["project"]).rglob("*.json"):
            self.assertNotIn("moments", path.read_text(encoding="utf-8"), path.name)

    def test_a_stored_pick_skips_the_listening(self) -> None:
        from media_manglers.core import speech_facts, voice_track as voice

        source = editor_recording(self.root / "plain.mkv", [("narration", ""), ("narration", ""), ("engine", ""), ("music", "")])
        speech_facts.record_measure(source, {
            "rule_version": voice.VOICE_RULE_VERSION, "status": "selected", "selected_ordinal": 1, "decided_by": "auto",
            "tracks": [], "track_activity": {"2": {"silent": False, "moments": [[1.0, 2.0]]}}},
            measured_by=speech_facts.BY_RAW_BIN, titles={0: "", 1: "", 2: "", 3: ""})
        with mock.patch.object(voice, "whisper_transcriber", side_effect=AssertionError("listened")), \
                mock.patch.object(voice, "detect_voice_track", side_effect=AssertionError("listened")):
            result = self.prepare(source, tracks={"game": 0})
        self.assertEqual(self.meta(result)["tracks"]["voice"], 1)
        self.assertEqual(self.meta(result)["tracks"]["voice_decided_by"], "auto")


class TrackChoiceTests(PrepareTestCase):
    """Decision A: the editor follows the track names and the Track roles, and refuses what can never
    be the voice or the game sound."""

    def test_the_track_names_choose_the_voice_and_the_game_sound(self) -> None:
        source = editor_recording(self.root / "named.mkv", NAMED)
        result = self.prepare(source)
        meta = self.meta(result)
        self.assertEqual(meta["tracks"], {"voice": 1, "game": 2, "voice_decided_by": "track_name",
                                          "game_decided_by": "track_name"})
        self.assertEqual(meta["layout"], SINGLE, "the request's layout is fixed at the first Prepare")
        self.assertEqual(meta["video"], {"width": 320, "height": 180, "avg_frame_rate": "10/1", "r_frame_rate": "10/1"})
        self.assertEqual([row["role"] for row in self.analysis(result)["tracks"]], ["unknown", "voice", "game", "unknown"])
        # A later Prepare keeps the project's layout, whatever the request says.
        with contextlib.redirect_stdout(io.StringIO()):
            race_requests.prepare_from_request({**self.payload(source), "layout": DEFAULT_LAYOUT})
        self.assertEqual(self.meta(result)["layout"], SINGLE)

    def test_the_track_roles_setting_chooses_them_for_unnamed_tracks(self) -> None:
        source = editor_recording(self.root / "plain.mkv", [("game", ""), ("narration", ""), ("game", "")])
        result = self.prepare(source, track_roles="2=narration,3=game")
        self.assertEqual(self.meta(result)["tracks"], {"voice": 1, "game": 2, "voice_decided_by": "setting",
                                                       "game_decided_by": "setting"})

    def test_settings_left_out_of_the_request_come_from_the_saved_settings(self) -> None:
        # An AI editor's own run sends no settings: the operator's saved Track roles are read, read only.
        source = editor_recording(self.root / "plain.mkv", [("game", ""), ("narration", ""), ("music", "")])
        self.settings.write(evidence_track_roles="1=game,2=narration")
        payload = self.payload(source)
        del payload["track_roles"]
        with contextlib.redirect_stdout(io.StringIO()):
            result = race_requests.prepare_from_request(payload)
        self.assertEqual(self.meta(result)["tracks"], {"voice": 1, "game": 0, "voice_decided_by": "setting",
                                                       "game_decided_by": "setting"})
        self.assertEqual(race_requests.engine_settings({"track_roles": "3=game"})["track_roles"], "3=game",
                         "a setting in the request wins")

    def test_a_track_that_can_never_be_used_is_refused_before_the_recording_is_read(self) -> None:
        source = editor_recording(self.root / "named.mkv", NAMED)
        cases = {
            "must be different tracks": {"voice": 2, "game": 2},
            "is never narration": {"voice": 3},
            "is the full mix, which carries every sound": {"voice": 0},
            "cannot be the game sound": {"game": 0},
            "must never reach a video as the game": {"game": 3},
            "has 4 audio tracks; there is no Track 9": {"voice": 8},
        }
        for words, tracks in cases.items():
            with self.subTest(tracks=tracks), FFmpegReads() as runs:
                with self.assertRaises(ValueError) as caught:
                    self.prepare(source, tracks=tracks)
                self.assertIn(words, str(caught.exception))
                self.assertEqual(runs.of(source), [], "nothing was read")

    def test_a_game_track_the_setting_sets_as_never_narration_is_refused_when_it_names_the_game(self) -> None:
        # 226 (decision A): a music, spotter or full-mix track can never reach a video. With the Narration
        # track setting naming the game track, a track it sets as Never narration, picked by hand as the
        # game sound, is refused before the recording is read and before a project folder is made.
        source = editor_recording(self.root / "obs.mkv", OBS_SIX, seconds=6)
        with FFmpegReads() as runs, self.assertRaises(ValueError) as caught:
            self.prepare(source, track_roles=NEVER_ROLES, tracks={"game": 5})
        self.assertEqual(str(caught.exception), NEVER_GAME_REFUSAL)
        self.assertEqual(runs.of(source), [], "nothing was read")
        self.assertFalse((self.root / "out" / "race-videos").exists(), "no project folder is left")
        # A setting with no game role keeps today's behaviour: the same pick is taken.
        older = self.prepare(source, track_roles=OLDER_ROLES, tracks={"game": 5})
        self.assertEqual(self.meta(older)["tracks"], {"voice": 1, "game": 5, "voice_decided_by": "setting",
                                                      "game_decided_by": "override"})
        # The setting's own game track, and a track it leaves on Auto, picked by hand, are taken too.
        for game in (2, 3):
            with self.subTest(game=game):
                picked = self.prepare(source, track_roles=NEVER_ROLES, tracks={"game": game})
                self.assertEqual(self.meta(picked)["tracks"]["game"], game)

    def test_without_whisper_a_voice_only_listening_can_find_is_asked_for(self) -> None:
        source = editor_recording(self.root / "plain.mkv", [("game", ""), ("narration", ""), ("music", "")])
        with self.assertRaisesRegex(ValueError, "Choose the voice track"):
            self.prepare(source)

    def test_no_game_track_stops_prepare_with_the_reason(self) -> None:
        source = editor_recording(self.root / "plain.mkv", [("game", ""), ("narration", ""), ("game", "")])
        with self.assertRaises(ValueError) as caught:
            self.prepare(source, track_roles="2=narration")
        self.assertIn("Choose the game track", str(caught.exception))
        self.assertIn("more than one track could be the game audio", str(caught.exception))

    def test_listening_finds_the_voice_when_neither_names_nor_settings_say(self) -> None:
        source = editor_recording(self.root / "plain.mkv", [("game", ""), ("narration", ""), ("silent", "")])
        loaded: list[str] = []

        def hearing(model_name, prefer_gpu, language_code, **_options):
            loaded.append(model_name)

            def transcribe(path):
                # The voice probe of Track 2 hears speech; every other track hears nothing.
                return ([{"text": "this is a spoken note about the first topic", **REAL}]
                        if Path(path).name == "probe-1.wav" else [])
            return transcribe

        # The narration's own Whisper run is stood in for here; TranscriptTests runs the real helper.
        _NoNarration.calls = []
        with mock.patch.object(voice_track, "whisper_transcriber", side_effect=hearing), \
                mock.patch.object(whisper_local, "transcribe_from_request", side_effect=_NoNarration.transcribe):
            result = self.prepare(source, skip_transcript=False, skip_game_speech=True)
        self.assertEqual(self.meta(result)["tracks"], {"voice": 1, "game": 0, "voice_decided_by": "auto",
                                                       "game_decided_by": "auto"})
        self.assertEqual(loaded, ["small"], "the quick passes' model, loaded once")
        self.assertEqual([Path(call["audio_path"]).name for call in _NoNarration.calls], ["track-1.wav"])

    def test_a_silent_voice_or_game_track_is_used_as_chosen_and_said_plainly(self) -> None:
        # 226: an older OBS layout has nothing on the track Track roles call the game sound.
        source = editor_recording(self.root / "plain.mkv", [("narration", ""), ("engine", ""), ("silent", "")], seconds=8)
        game = ("Track 3, your game sound, is silent for the whole recording; check your Narration track setting or "
                "choose the game track on the page.")
        for attempt in ("first", "again, with nothing to read"):
            with self.subTest(attempt):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    result = race_requests.prepare_from_request(self.payload(source, track_roles="1=narration,3=game"))
                self.assertEqual(self.meta(result)["tracks"]["game"], 2, "the choice stands")
                self.assertEqual(result["warnings"], [game])
                self.assertIn(f"Warning: {game}\n", out.getvalue())
                digest = (Path(result["project"]) / "analysis" / "digest.md").read_text(encoding="utf-8")
                self.assertTrue(digest.startswith(f"# Race analysis: plain.mkv\n\n**Warning:** {game}\n\n- Length:"),
                                digest[:400])
        picked = self.prepare(source, track_roles="1=narration", tracks={"game": 2})
        self.assertEqual(picked["warnings"], ["Track 3, your game sound, is silent for the whole recording; choose "
                                              "another track as your game sound on the page."])
        steady = self.prepare(source, track_roles="1=narration,2=game")
        self.assertEqual(steady["warnings"], [], "a steady engine noise is sound, not silence")
        self.assertNotIn(1, self.meta(steady)["sounding"], "though it has no speech-like activity")
        quiet = editor_recording(self.root / "quiet.mkv", [("silent", ""), ("engine", "")], seconds=8)
        self.assertEqual(self.prepare(quiet, track_roles="1=narration,2=game")["warnings"],
                         ["Track 1, your voice, is silent for the whole recording; check your Narration track setting "
                          "or choose your voice track on the page."])

    def test_the_editors_layout_is_the_shared_three_panel_geometry(self) -> None:
        self.assertEqual(project_module.editor_layout(), DEFAULT_LAYOUT)


class _NoNarration:
    """Stands in for the narration's Whisper run, writing an empty transcript."""

    calls: list[dict] = []

    @classmethod
    def transcribe(cls, payload: dict) -> dict:
        cls.calls.append(dict(payload))
        folder = Path(payload["output_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / payload["json_name"]).write_text(json.dumps({"segments": []}), encoding="utf-8")
        return {}


class FolderRuleTests(PrepareTestCase):
    """The one output-folder rule holds in core too: an AI editor's own run cannot write elsewhere."""

    def test_a_temporary_or_recordings_drive_folder_is_refused(self) -> None:
        source = editor_recording(self.root / "named.mkv", NAMED, seconds=4)
        timeline = {"schema": SCHEMA, "source": str(source), "tracks": {"voice": 1, "game": 2},
                    "scenes": [{"id": "s01", "in": 0.5, "out": 2.0}]}
        temp_root = self.root / "Temp" / "videos"
        with mock.patch.dict(os.environ, {"MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT": ""}):
            with self.assertRaisesRegex(ValueError, "is a temporary folder"):
                self.prepare(source, output_root=str(temp_root))
            with self.assertRaisesRegex(ValueError, "is a temporary folder"):
                race_requests.add_version_from_request({"timeline": timeline, "output_root": str(temp_root),
                                                        "ffprobe": FFPROBE})
        recordings = self.root / "recordings"
        recordings.mkdir()
        with mock.patch.dict(os.environ, {"MEDIA_MANGLERS_RECORDINGS_FOLDERS": str(recordings)}):
            with self.assertRaisesRegex(ValueError, "read-only to Media Manglers"):
                self.prepare(source, output_root=str(recordings / "edits"))
        self.assertFalse(temp_root.exists())
        self.assertFalse((recordings / "edits").exists())


class NoEmptyProjectTests(PrepareTestCase):
    """A refused first Prepare leaves no project folder for the page to list (226)."""

    def test_a_refused_first_prepare_leaves_no_project_folder(self) -> None:
        named = editor_recording(self.root / "named.mkv", NAMED, seconds=6)
        plain = editor_recording(self.root / "plain.mkv", [("game", ""), ("narration", ""), ("game", "")], seconds=6)
        cases = {
            "refused before the read": (named, {"tracks": {"game": 3}}, "must never reach a video as the game"),
            "refused after the read": (plain, {"track_roles": "2=narration"}, "Choose the game track"),
        }
        for case, (source, extra, words) in cases.items():
            with self.subTest(case), self.assertRaisesRegex(ValueError, words):
                self.prepare(source, **extra)
            self.assertFalse((self.root / "out" / "race-videos").exists(), "no project folder is left")
        # A project that exists is kept when a later Prepare of it is refused.
        project = Path(self.prepare(named)["project"])
        with self.assertRaisesRegex(ValueError, "must never reach a video as the game"):
            self.prepare(named, tracks={"game": 3})
        self.assertTrue((project / "analysis" / "analysis.json").exists())


class ScratchLeftoverTests(PrepareTestCase):
    """226 (196): Stop ends a run's processes at once, so a stopped Prepare cannot remove its work
    folder, which holds the decoded sound of every track. The next race-video command removes it, and
    never the folder of a run that still goes on."""

    def setUp(self) -> None:
        super().setUp()
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self._scratch_patch = mock.patch.dict(os.environ, {"MEDIA_MANGLERS_SCRATCH_ROOT": str(self.scratch)})
        self._scratch_patch.start()
        self.sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        ended = subprocess.Popen([sys.executable, "-c", "pass"])
        ended.wait()
        self.dead_pid = ended.pid

    def tearDown(self) -> None:
        self.sleeper.kill()
        self.sleeper.wait()
        self._scratch_patch.stop()
        super().tearDown()

    def plant(self, name: str) -> Path:
        folder = self.scratch / name
        (folder / "tracks").mkdir(parents=True, exist_ok=True)
        (folder / "tracks" / "track-0.wav").write_bytes(b"\0" * 1024)
        return folder

    def plant_all(self) -> dict[str, Path]:
        # The running process's folder is made after it started, as its own run would make it.
        return {
            "stopped": self.plant(f"{analysis.SCRATCH_PREFIX}{self.dead_pid}_abcdefgh"),
            "stopped game voices": self.plant(f"media_manglers_race_video_game_{self.dead_pid}_0g722it_"),
            "running": self.plant(f"{analysis.SCRATCH_PREFIX}{self.sleeper.pid}_abcdefgh"),
            "this process": self.plant(f"{analysis.SCRATCH_PREFIX}{os.getpid()}_abcdefgh"),
            "not a run's": self.plant(f"{analysis.SCRATCH_PREFIX}notarun"),
            "the raw bin's": self.plant(f"media_manglers_raw_bin_{self.dead_pid}_abcdefgh"),
        }

    def assert_swept(self, planted: dict[str, Path]) -> None:
        self.assertEqual({name: folder.exists() for name, folder in planted.items()},
                         {"stopped": False, "stopped game voices": False, "running": True, "this process": True,
                          "not a run's": True, "the raw bin's": True})

    def test_prepare_removes_a_stopped_runs_work_folder_and_keeps_a_running_ones(self) -> None:
        planted = self.plant_all()
        source = editor_recording(self.root / "named.mkv", NAMED, seconds=4)
        self.prepare(source)
        self.assert_swept(planted)
        self.assertEqual(sorted(path.name for path in self.scratch.iterdir()),
                         sorted(planted[name].name for name in ("running", "this process", "not a run's", "the raw bin's")),
                         "Prepare's own work folder is gone too")

    def test_the_analysis_transcript_and_review_kit_sweep_first(self) -> None:
        source = editor_recording(self.root / "named.mkv", NAMED, seconds=4)
        project = self.prepare(source)["project"]
        planted = self.plant_all()
        with contextlib.redirect_stdout(io.StringIO()):
            race_requests.analyze_from_request({"source": str(source), "project": project, "budget": "light",
                                                "ffmpeg": FFMPEG, "ffprobe": FFPROBE, "track_roles": ""})
        self.assert_swept(planted)
        # Each removes them before anything else, even when the request then fails.
        for handler, payload in ((race_requests.transcribe_from_request, {"project": str(self.root / "no-project")}),
                                 (race_requests.review_kit_from_request, {"project": project, "version": 9,
                                                                          "transcribe": False})):
            with self.subTest(handler=handler.__name__):
                planted = self.plant_all()
                with self.assertRaises(Exception):
                    handler({"ffmpeg": FFMPEG, "ffprobe": FFPROBE, **payload})
                self.assert_swept(planted)

    def test_a_folder_named_with_a_process_number_given_out_again_is_removed(self) -> None:
        # The running process started after the folder was made: Windows gave its number out again.
        folder = self.plant(f"{analysis.SCRATCH_PREFIX}{self.sleeper.pid}_abcdefgh")
        later = time.time() + 600
        with mock.patch.object(race_requests, "process_start_time", return_value=later):
            self.assertEqual(race_requests.remove_scratch_leftovers(), 1)
        self.assertFalse(folder.exists())


class OneReadTests(PrepareTestCase):
    """The recording is read once, sound and game picture together, and dead time is found from both."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.class_temp = tempfile.TemporaryDirectory()
        cls.source = editor_recording(Path(cls.class_temp.name) / "frozen.mkv",
                                      [("narration", "T1 - Narration"), ("engine", "T2 - Game")], seconds=100,
                                      frozen=(10, 80))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.class_temp.cleanup()

    def test_one_read_finds_a_frozen_game_picture_and_the_digest_lists_it(self) -> None:
        with FFmpegReads() as runs:
            result = self.prepare(self.source)
        data = self.analysis(result)
        self.assertEqual(runs.full_reads(self.source), 1, "one read of the whole recording")
        self.assertEqual(runs.seeks(self.source), data["stills"], "and one short seek per still")
        activity = data["activity"]
        self.assertEqual(activity["status"], "measured")
        self.assertEqual(len(activity["idle_stretches"]), 1, activity)
        start, end = activity["idle_stretches"][0]
        self.assertLessEqual(abs(start - 10), 3, activity)
        self.assertLessEqual(abs(end - 80), 3, activity)
        self.assertEqual(activity["idle_by"], [["game_picture"]])
        self.assertEqual(activity["picture_kinds"], ["still"])
        self.assertEqual(activity["region"], "whole frame")
        self.assertIn("replay", activity["cannot_tell"])
        stored = json.loads((Path(result["project"]) / "analysis" / "activity.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, activity)
        digest = (Path(result["project"]) / "analysis" / "digest.md").read_text(encoding="utf-8")
        changes, dead, sheets = (digest.index("## Sharp picture changes on the story panel"),
                                 digest.index("## Dead time (no driving found)"), digest.index("## Contact sheets"))
        self.assertLess(changes, dead)
        self.assertLess(dead, sheets)
        section = digest[dead:sheets]
        self.assertIn(f"- {analysis.clock(start)}-{analysis.clock(end)} ({(end - start) // 60} min {(end - start) % 60} s): "
                      "game picture still while the game sound goes on (often the pits, a repair or the grid)", section)
        self.assertIn("Cut dead time unless it serves the story.", section)
        self.assertIn("privacy masks applied: no masks set, so the camera panels are not blurred", digest)
        # Nothing of the read is left in the scratch folder.
        self.assertEqual(list(Path(tempfile.gettempdir()).glob(f"{analysis.SCRATCH_PREFIX}{os.getpid()}_*")), [])

    def test_when_the_combined_read_fails_the_sound_is_read_again_and_the_picture_is_not_measured(self) -> None:
        real = frame_render.picture_output

        def broken(region, frames_path, times_path, **options):
            arguments = real(region, frames_path, times_path, **options)
            arguments[arguments.index("-vf") + 1] = "no_such_filter_mm"
            return arguments

        with FFmpegReads() as runs, mock.patch.object(frame_render, "picture_output", side_effect=broken):
            result = self.prepare(self.source)
        self.assertEqual(runs.full_reads(self.source), 2, "the combined read, then the sound on its own")
        activity = self.analysis(result)["activity"]
        self.assertEqual(activity["status"], "measured", "the game sound is still measured")
        self.assertEqual(activity["signals"]["game_picture"]["status"], "unknown")
        self.assertIn("could not be read in the same pass as the sound", activity["signals"]["game_picture"]["reason"])
        digest = (Path(result["project"]) / "analysis" / "digest.md").read_text(encoding="utf-8")
        section = digest[digest.index("## Dead time"):digest.index("## Contact sheets")]
        self.assertIn("- none found", section)
        self.assertIn("Game picture not measured: the game picture could not be read in the same pass", section)

    def test_a_long_step_is_never_silent_for_long(self) -> None:
        # The page warns after 30 s without a line; every step says something at least every 10 s.
        real = voice_track.analyze_track_wav
        heard: list[float] = []
        speak = race_requests._progress

        def slow(path, ordinal):
            time.sleep(1.5)
            return real(path, ordinal)

        def noted(*args, **kwargs):
            heard.append(time.monotonic())
            return speak(*args, **kwargs)

        with mock.patch.object(race_requests, "PROGRESS_PULSE_SECONDS", 0.3), \
                mock.patch.object(voice_track, "analyze_track_wav", side_effect=slow), \
                mock.patch.object(race_requests, "_progress", side_effect=noted):
            self.prepare(self.source, progress_label="frozen.mkv")
        gaps = [later - earlier for earlier, later in zip(heard, heard[1:])]
        self.assertGreater(len(heard), 10)
        self.assertLess(max(gaps), 1.0, f"the longest silence was {max(gaps):.1f} s")


class _CpuTorch:
    __version__ = "0.0.0+cpu"
    cuda = mock.Mock(is_available=lambda: False, device_count=lambda: 0)
    version = mock.Mock(cuda="")


class _Model:
    def transcribe(self, audio, **_options) -> dict:
        name = Path(audio).name
        FakeWhisper.heard.append(name)
        if name.startswith("chunk-"):
            # The narration's stretches of speech, one line each, in the shared Whisper helper.
            number = int(Path(audio).stem.split("-")[1])
            with wave.open(str(audio), "rb") as clip:
                seconds = clip.getnframes() / clip.getframerate()
            return {"language": "en", "segments": [
                {"start": 0.0, "end": round(seconds, 2), "text": " " + SENTENCES[(number - 1) % len(SENTENCES)], **REAL}]}
        if name.startswith("piece-"):
            # A piece of the game track: a teammate on voice chat, and a grunt Whisper is unsure is speech.
            return {"language": "en", "segments": [
                {"start": 3.0, "end": 5.0, "text": " Box this lap for fresh tyres.", **REAL},
                {"start": 8.0, "end": 9.0, "text": " uh huh", **{**REAL, "no_speech_prob": 0.9}}]}
        return {"language": "en", "segments": []}


class FakeWhisper:
    loads: list[str] = []
    heard: list[str] = []

    @staticmethod
    def load_model(model_name, device=None):
        FakeWhisper.loads.append(model_name)
        return _Model()


class _GameEchoModel(_Model):
    """The game track carries the narration's first line too (a teammate on voice chat saying it): the
    cross-track check hears those words when it plays the game track (Track 2) at that line's moment."""

    def transcribe(self, audio, **options) -> dict:
        if Path(audio).name == "window-0-1.wav":
            FakeWhisper.heard.append(Path(audio).name)
            return {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": " " + SENTENCES[0], **REAL}]}
        return super().transcribe(audio, **options)


class _GameEchoWhisper:
    @staticmethod
    def load_model(model_name, device=None):
        FakeWhisper.loads.append(model_name)
        return _GameEchoModel()


class _ReactionModel:
    """The "reaction" track as Whisper hears it: a confident sentence written over the barely-on
    microphone (2-5 s), and a short exclamation over the loud burst that Whisper sampled and rates
    below its own bar (8-9.5 s), the kind the editor's short-reaction rule keeps."""

    def transcribe(self, audio, **_options) -> dict:
        name = Path(audio).name
        FakeWhisper.heard.append(name)
        if name == "chunk-0001.wav":
            return {"language": "en", "segments": [{"start": 0.4, "end": 3.0, "text": " the tyres are gone now", **REAL}]}
        if name == "chunk-0002.wav":
            return {"language": "en", "segments": [
                {"start": 0.4, "end": 1.0, "text": " Oh wow.", **{**REAL, "temperature": 0.2, "avg_logprob": -1.3}}]}
        return {"language": "en", "segments": []}


class _ReactionWhisper:
    @staticmethod
    def load_model(model_name, device=None):
        FakeWhisper.loads.append(model_name)
        return _ReactionModel()


class TranscriptTests(PrepareTestCase):
    """Decision B: the narration is written with the operator's Whisper settings and word list, checked
    against the other tracks, and written again only when what it depends on changes."""

    def run_prepare(self, source: Path, **extra) -> tuple[dict, list[dict]]:
        FakeWhisper.loads, FakeWhisper.heard = [], []
        with mock.patch.dict(sys.modules, {"whisper": checked_whisper(FakeWhisper()), "torch": _CpuTorch()}), \
                mock.patch.object(whisper_local, "transcribe_from_request",
                                  wraps=whisper_local.transcribe_from_request) as helper:
            result = self.prepare(source, skip_transcript=False, **extra)
        return result, [call.args[0] for call in helper.call_args_list]

    def test_the_transcript_is_reused_until_its_settings_change(self) -> None:
        source = editor_recording(self.root / "race.mkv", [("narration", "T1 - Narration"), ("game", "T2 - Game"),
                                                           ("music", "T3 - Music")])
        result, requests = self.run_prepare(source, **{WORDS_KEY: "Brooklands"})
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual((request["model_name"], request["language_code"], request["narration_speech_mode"]),
                         ("medium", "en", "Sparse"))
        self.assertEqual((request["initial_prompt"], request["glossary_entries"]),
                         ("Preferred terminology: Brooklands", ["Brooklands"]))
        self.assertTrue(request["keep_short_reactions"])
        self.assertTrue(request["progress_work_units"])
        self.assertEqual(Path(request["ffmpeg_dir"]), Path(FFMPEG).resolve().parent)
        self.assertEqual(Path(request["audio_path"]).name, "track-0.wav", "the decoded voice track of the one read")
        self.assertIn("medium", FakeWhisper.loads)
        self.assertIn("base.en", FakeWhisper.loads, "the cross-track check compares words with base.en")
        self.assertIn("small", FakeWhisper.loads, "the game track is heard with the quick passes' model")
        self.assertTrue(any(name.startswith("window-") and name.endswith("-2.wav") for name in FakeWhisper.heard),
                        "the music track was compared")
        folder = Path(result["project"]) / "analysis" / "transcript"
        stamp = json.loads((folder / "narration.stamp.json").read_text(encoding="utf-8"))
        self.assertEqual((stamp["voice"], stamp["compared"], stamp["model"], stamp["keep_short_reactions"]),
                         (0, [1, 2], "medium", True))
        digest = (Path(result["project"]) / "analysis" / "digest.md").read_text(encoding="utf-8")
        self.assertIn("here we go into turn one", digest)

        # Other voices on the game track, with every line left out kept apart, with its reason.
        heard = json.loads((folder / "game.speech.json").read_text(encoding="utf-8"))
        self.assertEqual(heard["segments"], [{"start": 3.0, "end": 5.0, "text": "Box this lap for fresh tyres."}])
        self.assertEqual(heard["left_out"], [{"start": 8.0, "end": 9.0, "text": "uh huh", "reason": "probably_not_speech"}])
        self.assertEqual((heard["model"], heard["track"]), ("small", 1))
        voices = digest[digest.index("## Other voices on the game track"):]
        self.assertIn("[00:03] Box this lap for fresh tyres.", voices)
        self.assertIn("Left out: 1 more line heard on the game track was not clearly another voice", voices)
        self.assertNotIn("uh huh", digest, "a left-out line is never in the digest")

        again, requests = self.run_prepare(source, **{WORDS_KEY: "Brooklands"})
        self.assertEqual(requests, [], "the same settings: the transcript is used again")
        self.assertFalse(any(name.startswith("piece-") for name in FakeWhisper.heard), "and the game track's voices")
        self.assertIn("here we go into turn one", (Path(again["project"]) / "analysis" / "digest.md").read_text(encoding="utf-8"))

        _changed, requests = self.run_prepare(source, **{WORDS_KEY: "Brooklands, Silverstone"})
        self.assertEqual(len(requests), 1, "a changed word list writes the narration again")
        self.assertEqual(requests[0]["initial_prompt"], "Preferred terminology: Brooklands, Silverstone")

    def test_a_second_prepare_with_nothing_changed_does_not_read_the_recording(self) -> None:
        source = editor_recording(self.root / "race.mkv", [("narration", "T1 - Narration"), ("game", "T2 - Game")])
        with FFmpegReads() as runs:
            first, requests = self.run_prepare(source)
        self.assertEqual((runs.full_reads(source), len(requests)), (1, 1))
        folder = Path(first["project"]) / "analysis"
        before = {name: (folder / name).read_bytes() for name in ("analysis.json", "digest.md", "transcript/game.speech.json",
                                                                  "transcript/narration.transcript.json")}
        self.assertEqual(self.meta(first)["sounding"], [0, 1], "which tracks have sound is kept for the next Prepare")

        with FFmpegReads() as runs:
            again, requests = self.run_prepare(source)
        self.assertEqual(runs.of(source), [], "the recording is not read at all: no full read and no still")
        self.assertEqual(requests, [], "the narration is used again")
        self.assertFalse(any(name.startswith("piece-") for name in FakeWhisper.heard), "and the game track's voices")
        self.assertEqual({name: (folder / name).read_bytes() for name in before}, before, "everything is as it was")
        self.assertEqual(self.meta(again)["tracks"], self.meta(first)["tracks"])

        # A change the stills depend on reads the recording once again.
        with FFmpegReads() as runs:
            self.run_prepare(source, budget="standard")
        self.assertEqual(runs.full_reads(source), 1)

    def test_a_game_track_found_by_listening_means_reading_again(self) -> None:
        # The one track left becomes the game track only after its sound is measured.
        source = editor_recording(self.root / "race.mkv", [("narration", "T1 - Narration"), ("game", "")])
        self.prepare(source)
        with FFmpegReads() as runs:
            result = self.prepare(source)
        self.assertEqual(self.meta(result)["tracks"]["game_decided_by"], "auto")
        self.assertEqual(runs.full_reads(source), 1)

    def test_race_video_transcribe_leaves_out_a_line_heard_on_the_game_track_as_prepare_does(self) -> None:
        source = editor_recording(self.root / "race.mkv", [("narration", "T1 - Narration"), ("game", "T2 - Game")],
                                  seconds=12)

        def run(handler, payload: dict) -> dict:
            FakeWhisper.loads, FakeWhisper.heard = [], []
            with mock.patch.dict(sys.modules, {"whisper": checked_whisper(_GameEchoWhisper()), "torch": _CpuTorch()}), \
                    contextlib.redirect_stdout(io.StringIO()):
                return handler(payload)

        result = run(race_requests.prepare_from_request, self.payload(source, skip_transcript=False, skip_game_speech=True))
        folder = Path(result["project"]) / "analysis" / "transcript"

        def lines() -> list[str]:
            data = json.loads((folder / "narration.transcript.json").read_text(encoding="utf-8"))
            return [str(segment["text"]).strip() for segment in data["segments"]]

        def heard_elsewhere() -> list[tuple]:
            raw = json.loads((folder / "narration.transcript.raw.json").read_text(encoding="utf-8"))
            return [(item["track_number"], item["found_by"], str(item["segment"]["text"]).strip())
                    for item in raw["filtered_segments"] if item.get("reason") == "heard_on_another_track"]

        prepared = lines()
        self.assertEqual(heard_elsewhere(), [(2, "words", SENTENCES[0])], "Prepare leaves the line out")
        self.assertNotIn(SENTENCES[0], prepared)
        self.assertIn(SENTENCES[1], prepared)
        stamp = json.loads((folder / "narration.stamp.json").read_text(encoding="utf-8"))

        with FFmpegReads() as runs:
            run(race_requests.transcribe_from_request, {"project": result["project"], "voice": 0, "ffmpeg": FFMPEG,
                                                        "ffprobe": FFPROBE, "track_roles": ""})
        self.assertEqual(lines(), prepared, "race-video-transcribe leaves out the same line")
        self.assertEqual(heard_elsewhere(), [(2, "words", SENTENCES[0])])
        self.assertIn("window-0-1.wav", FakeWhisper.heard, "the game track was heard at that line's moment")
        self.assertTrue(any("-ss" in command[:command.index("-i")] and "0:a:1" in command for command in runs.of(source)),
                        "each line's moment is read with one short seek into the recording")
        self.assertEqual(json.loads((folder / "narration.stamp.json").read_text(encoding="utf-8")), stamp,
                         "its stamp is written, the same as Prepare's")
        _again, requests = self.run_prepare(source, skip_game_speech=True)
        self.assertEqual(requests, [], "so the next Prepare uses that transcript as it is")


class ReactionRecheckTests(PrepareTestCase):
    """Decision B: a short reaction is kept only while a real line still anchors it; the cross-track and
    near-silent checks run first, so a reaction never hangs on a line they took out."""

    def test_a_reaction_whose_anchor_was_not_said_into_the_microphone_goes_too(self) -> None:
        # The real rule, through the shared Whisper helper with Whisper stood in for: Whisper writes a
        # sentence over the barely-on microphone (2-5 s, about -48 dBFS) and a short exclamation over the
        # loud burst at 8-9.5 s. The helper keeps the exclamation as a reaction, anchored by that sentence;
        # the near-silent check then takes the sentence out, and the reaction has no anchor left.
        source = editor_recording(self.root / "race.mkv", [("reaction", "T1 - Narration"), ("engine", "T2 - Game")])
        FakeWhisper.loads, FakeWhisper.heard = [], []
        with mock.patch.dict(sys.modules, {"whisper": checked_whisper(_ReactionWhisper()), "torch": _CpuTorch()}), \
                mock.patch.object(whisper_local, "transcribe_from_request",
                                  wraps=whisper_local.transcribe_from_request) as helper:
            result = self.prepare(source, skip_transcript=False, skip_game_speech=True)
        self.assertTrue(helper.call_args.args[0]["keep_short_reactions"])
        self.assertIn("chunk-0002.wav", FakeWhisper.heard, "the burst is its own stretch of speech")
        folder = Path(result["project"]) / "analysis" / "transcript"
        delivered = json.loads((folder / "narration.transcript.json").read_text(encoding="utf-8"))
        raw = json.loads((folder / "narration.transcript.raw.json").read_text(encoding="utf-8"))
        quality = json.loads((folder / "narration.transcript.quality.json").read_text(encoding="utf-8"))
        self.assertEqual([(str(item["segment"]["text"]).strip(), item["anchor_start"])
                          for item in raw["short_reactions_kept"]], [("Oh wow.", 2.05)],
                         "the shared helper kept the reaction, anchored by the sentence")
        self.assertEqual(delivered["segments"], [])
        self.assertEqual([(item["reason"], str(item["segment"]["text"]).strip()) for item in raw["filtered_segments"]],
                         [("narration_track_near_silent", "the tyres are gone now"),
                          ("short_reaction_without_anchor", "Oh wow.")])
        self.assertEqual((quality["filtered_segment_count"], quality["narration_near_silent_count"],
                          quality["short_reactions_kept_count"], quality["short_reactions_without_anchor_count"]),
                         (2, 1, 0, 1))
        self.assertTrue((folder / "narration.stamp.json").exists(), "written once every check is done")
        self.assertNotIn("Oh wow", (Path(result["project"]) / "analysis" / "digest.md").read_text(encoding="utf-8"))


class WhisperProgressTests(PrepareTestCase):
    def test_the_narrations_progress_reaches_the_page_as_work_units(self) -> None:
        # The shared Whisper helper writes how many stretches of speech it has decoded to its progress
        # file (progress_work_units); Prepare turns that into status lines while Whisper works.
        source = editor_recording(self.root / "race.mkv", [("narration", "T1 - Narration"), ("engine", "T2 - Game")],
                                  seconds=8)

        def whisper(payload: dict) -> dict:
            self.assertTrue(payload["progress_work_units"])
            progress = Path(payload["progress_file"])
            for done in range(4):
                progress.write_text(json.dumps({"stage": "transcribing", "message": "Running Whisper",
                                                "progress_kind": "work_units", "completed": done, "total": 3}),
                                    encoding="utf-8")
                time.sleep(0.5)
            folder = Path(payload["output_dir"])
            (folder / payload["json_name"]).write_text(json.dumps({"segments": []}), encoding="utf-8")
            return {}

        out = io.StringIO()
        with mock.patch.object(whisper_local, "transcribe_from_request", side_effect=whisper), \
                mock.patch.object(race_requests, "WHISPER_PROGRESS_SECONDS", 0.1), contextlib.redirect_stdout(out):
            race_requests.prepare_from_request(self.payload(source, skip_transcript=False, skip_game_speech=True,
                                                            progress_label="race.mkv"))
        lines = [json.loads(line.split(" ", 1)[1]) for line in out.getvalue().splitlines()
                 if line.startswith("MM_PROGRESS_V1 ")]
        writing = [(line["activity"], line.get("completed"), line.get("total")) for line in lines
                   if line["phase"] == "Writing down the narration" and line.get("total")]
        for done in range(4):
            self.assertIn((f"Writing down the narration: {done} of 3 stretches of speech", done, 3), writing)
        # 242 (Wave C2): a new video whose recording the library has not read starts with "Confirming which
        # recording this is", so the narration is the third step here.
        self.assertEqual([line["phase_index"] for line in lines if line["phase"] == "Writing down the narration"][0], 3)
        self.assertEqual(lines[-1]["activity"], "Ready for the AI editor")
        self.assertTrue(lines[-1]["source_terminal"])


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class GameVoicesTests(unittest.TestCase):
    """The game track is heard in five-minute pieces from the decoded audio, with the shared loader."""

    def test_pieces_are_heard_in_order_and_every_left_out_line_keeps_its_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav = root / "track-2.wav"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=650",
                            "-c:a", "pcm_s16le", str(wav)], check=True)
            narration = root / "narration.transcript.json"
            narration.write_text(json.dumps({"segments": [{"start": 600.0, "end": 603.0,
                                                           "text": "pit this lap for the soft tyres"}]}), encoding="utf-8")
            pieces: list[float] = []

            def transcriber(path):
                with wave.open(str(path), "rb") as clip:
                    pieces.append(round(clip.getnframes() / clip.getframerate(), 2))
                number = len(pieces)
                # Times are from the start of each cut: 0, 295 and 595 s (5 s of overlap before each piece).
                if number == 1:
                    return [{"start": 10.0, "end": 12.0, "text": " Car left, still there.", **REAL},
                            {"start": 20.0, "end": 21.0, "text": " Thank you for watching!", **REAL}]
                if number == 2:
                    return [{"start": 9.0, "end": 11.0, "text": " Nice move into turn three.", **{**REAL, "avg_logprob": -1.4}},
                            {"start": 35.0, "end": 36.0, "text": " Pit window open now, pit window open.",
                             **{**REAL, "compression_ratio": 3.1}}]
                return [{"start": 6.0, "end": 8.0, "text": " pit this lap for the soft tyres", **REAL}]

            heard: list[tuple[int, int]] = []
            target = game_speech.listen_to_game_track(
                wav, root / "out", narration, transcriber=transcriber, track=2, model_name="small", language="en",
                result_stamp={"rules": 1}, on_progress=lambda done, total: heard.append((done, total)))
            data = json.loads(target.read_text(encoding="utf-8"))
        # Five-minute pieces, each cut with 5 s more on either side (226).
        self.assertEqual(pieces, [305.0, 310.0, 55.0])
        self.assertEqual(heard, [(1, 3), (2, 3), (3, 3)])
        self.assertEqual(data["segments"], [{"start": 10.0, "end": 12.0, "text": "Car left, still there."}])
        self.assertEqual([(item["start"], item["reason"]) for item in data["left_out"]],
                         [(20.0, "filler_whisper_writes_over_noise"), (304.0, "whisper_unsure_of_the_words"),
                          (330.0, "repeated_words"), (601.0, "the_drivers_own_voice")])
        self.assertEqual((data["track"], data["model"], data["language"], data["stamp"]), (2, "small", "en", {"rules": 1}))

    def test_a_line_said_across_a_cut_is_heard_whole_and_listed_once(self) -> None:
        # A teammate's line from 299.2 to 301.5 s, across the first five-minute cut. The stand-in Whisper
        # writes down whatever of it each piece holds, as Whisper does with a line cut short.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav = root / "track-2.wav"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "aevalsrc='if(between(t,299.2,301.5),0.5*sin(2*PI*400*t),0)':s=16000:d=650",
                            "-c:a", "pcm_s16le", str(wav)], check=True)

            def transcriber(path):
                import numpy  # noqa: PLC0415

                with wave.open(str(path), "rb") as clip:
                    rate = clip.getframerate()
                    samples = numpy.frombuffer(clip.readframes(clip.getnframes()), dtype=numpy.int16)
                loud = numpy.flatnonzero(numpy.abs(samples) > 1000)
                if not len(loud):
                    return []
                return [{"start": float(loud[0]) / rate, "end": float(loud[-1] + 1) / rate,
                         "text": " Car left, still there.", **REAL}]

            target = game_speech.listen_to_game_track(wav, root / "out", None, transcriber=transcriber, track=2)
            data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["segments"], [{"start": 299.2, "end": 301.5, "text": "Car left, still there."}])
        self.assertEqual(data["left_out"], [])
        self.assertEqual(data["stamp"], {})

    def test_the_game_voices_have_no_decoder_or_whisper_loader_of_their_own(self) -> None:
        text = Path(game_speech.__file__).read_text(encoding="utf-8")
        for own in ("import whisper", "load_model", "import subprocess", "import torch"):
            self.assertNotIn(own, text)


class SharedPartsTests(unittest.TestCase):
    def test_one_clock_and_one_track_roles_parser(self) -> None:
        self.assertIs(analysis.clock, voice_track.clock)
        self.assertEqual(analysis.clock(3725), "1:02:05")
        self.assertIs(raw_bin_library._roles_value, voice_track.roles_from_text)
        self.assertEqual(voice_track.roles_from_text("2=Narration; 3=game,x=never"), {"2": "narration", "3": "game"})

    def test_the_quick_passes_use_small_unless_set_and_main_means_the_main_model(self) -> None:
        fields = {"model_name": "large"}
        self.assertEqual(race_requests.quick_model({}, fields), "small")
        self.assertEqual(race_requests.quick_model({"race_video_quick_whisper_model": "main"}, fields), "large")
        self.assertEqual(race_requests.quick_model({"race_video_quick_whisper_model": "medium"}, fields), "medium")

    def test_the_editors_core_never_imports_the_workbench(self) -> None:
        code = ("import sys\n"
                f"sys.path.insert(0, {str(REPO_ROOT / 'src')!r})\n"
                "class Block:\n"
                "    def find_spec(self, name, path=None, target=None):\n"
                "        if name == 'media_manglers_workbench' or name.startswith('media_manglers_workbench.'):\n"
                "            raise ImportError('the packaged backend has no Workbench')\n"
                "sys.meta_path.insert(0, Block())\n"
                "from media_manglers.core.race_video import requests, analysis, game_speech\n"
                "import media_manglers\n"
                "print(media_manglers.__file__)\n")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertEqual(Path(done.stdout.strip()), REPO_ROOT / "src" / "media_manglers" / "__init__.py", done.stderr)


if __name__ == "__main__":
    unittest.main()
