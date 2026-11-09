"""206: Full Review's Auto finds the narration track the shared way, and never says "no narration".

Full Review is for any video. A chosen track, a preferred track and a one-track video are used as
before, with no detection. On Auto with several tracks, the narration track is found by track
names, the per-track setting and voice detection; when there is none, a track named or set as the
full mix is used, and failing that every track, as Auto always did.

The backend's own functions run on synthetic recordings, with the real voice detection; only
Whisper's ear is stood in for.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from tests.test_skipped_recording_privacy import SHIM, SRC, _launcher
from tests.test_track_roles_backend import BUSY_NOISE, _bursty, _recording
from tests.test_voice_track import NARRATION_WORDS, _three_track_recording

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _choose(root: Path, video: Path, *, words: dict[str, str] | None = None, mode: str = "Auto",
            track: int = 0, roles: str = "", stub_detection: bool = False) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    control = root / "run-control.json"
    control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")
    python = _launcher(root, "python", SHIM, SRC=str(SRC), WORDS=words or {}, CONTROL=str(control),
                       B_PATH="", SKIP_ON="")
    stub = ("function Invoke-VoiceTrackDetection { $script:detectionCalls += 1; return $null }"
            if stub_detection else "")
    source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Parent -is [System.Management.Automation.Language.NamedBlockAst] }}, $false)) {{
            Invoke-Expression $node.Extent.Text
        }}
        function Write-MMProgressV1 {{ }}
        $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{SRC}'; EntryPoint = '' }}
        $script:detectionCalls = 0
        {stub}
        $streams = @(Get-VideoAudioStreams -FFprobeExe '{FFPROBE}' -VideoPath '{video}')
        $number = Get-MMFullReviewAutoTrackNumber -AudioStreams $streams -Mode '{mode}' -TrackOrdinal {track} `
            -PythonCommand '{python}' -FFmpegExe '{FFMPEG}' -FFprobeExe '{FFPROBE}' -VideoPath '{video}' -PreferGpu $false `
            -TrackRolesText '{roles}' -HeartbeatSeconds 1
        $selection = Resolve-TranscriptAudioSelection -AudioStreams $streams -Mode '{mode}' -StreamSpecifier '' `
            -TrackOrdinal $(if ($number -gt 0) {{ $number }} else {{ {track} }}) -PreferredTrackOrdinal 0 -InteractiveMode:$false
        [Console]::Out.WriteLine((@{{
            number = $number
            narration = ($null -ne $script:MMFullReviewNarration)
            every_track = [bool]$selection.IsAllTracks
            transcribed = @(@($selection.SelectedStreams) | ForEach-Object {{ [int]$_.ordinal + 1 }})
            detection_calls = $script:detectionCalls
        }} | ConvertTo-Json -Compress))
        """
    ).strip()
    harness = root / "harness.ps1"
    harness.write_text(source, encoding="utf-8")
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(result.stderr[-4000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class FullReviewTrackChoiceTests(unittest.TestCase):
    def test_a_single_track_video_is_transcribed_without_looking_for_a_narration_track(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = _recording(root / "one-track.mkv", [(_bursty(300, 0.0, 3.0), "")])
            result = _choose(root / "run", video, stub_detection=True)
        self.assertEqual(result["detection_calls"], 0)
        self.assertEqual((result["number"], result["every_track"], result["transcribed"]), (0, True, [1]))

    def test_the_narration_track_is_found_and_only_it_is_transcribed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = _three_track_recording(root / "three-tracks.mkv")
            result = _choose(root / "run", video, words={"1": NARRATION_WORDS})
        self.assertEqual((result["number"], result["narration"], result["every_track"], result["transcribed"]),
                         (2, True, False, [2]))

    def test_264_a_known_recording_is_answered_by_the_library_with_nothing_listened_to(self) -> None:
        from media_manglers.core import speech_facts

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = _three_track_recording(root / "three-tracks.mkv")
            first = _choose(root / "run", video, words={"1": NARRATION_WORDS})
            self.assertEqual(first["number"], 2)
            self.assertEqual(speech_facts.known_measure(video).measured_by, "full_review")
            second = _choose(root / "again", video, stub_detection=True)
            self.assertEqual((second["number"], second["narration"], second["detection_calls"]), (2, True, 0))
            # Your answer wins, here too, with nothing listened to.
            speech_facts.confirm_track(video, 3, by=speech_facts.ANSWERED_ON_BUGS)
            third = _choose(root / "yours", video, stub_detection=True)
            self.assertEqual((third["number"], third["narration"], third["detection_calls"]), (3, True, 0))

    def test_with_no_narration_a_track_named_full_mix_is_transcribed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = _recording(root / "named.mkv", [
                (BUSY_NOISE, "T1 - Full Mix"),
                ("anullsrc=r=48000:cl=stereo", "T2 - Narration"),
                (_bursty(500, 0.0, 3.0), "T3 - Game / Simulator"),
            ])
            result = _choose(root / "run", video)
        self.assertEqual((result["number"], result["narration"], result["every_track"], result["transcribed"]),
                         (1, False, False, [1]))

    def test_with_no_narration_and_no_full_mix_every_track_is_transcribed_as_before(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = _three_track_recording(root / "three-tracks.mkv")
            result = _choose(root / "run", video)
        self.assertEqual((result["number"], result["narration"], result["every_track"], result["transcribed"]),
                         (0, False, True, [1, 2, 3]))

    def test_a_chosen_track_is_used_as_before_without_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = _three_track_recording(root / "three-tracks.mkv")
            chosen = _choose(root / "track", video, mode="Track", track=3, stub_detection=True)
            mixed = _choose(root / "mixed", video, mode="Mixed", stub_detection=True)
            every = _choose(root / "all", video, mode="All", stub_detection=True)
        self.assertEqual((chosen["detection_calls"], chosen["transcribed"]), (0, [3]))
        self.assertEqual((mixed["detection_calls"], mixed["transcribed"]), (0, [1]))
        self.assertEqual((every["detection_calls"], every["transcribed"]), (0, [1, 2, 3]))


class FullReviewWiringTests(unittest.TestCase):
    def test_full_review_uses_the_words_and_the_narration_filter(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        start = text.index("function Process-Video {")
        body = text[start: text.index("\nfunction ", start + 10)]
        self.assertIn("$autoTrackOrdinal = Get-MMFullReviewAutoTrackNumber", body)
        # Every Whisper call of Full Review gets the words to spell right.
        import re

        passed = len(re.findall(r"^\s*-GlossaryEntries \(Get-MMSpellingWords\) `", body, flags=re.MULTILINE))
        self.assertEqual(body.count("Invoke-PythonWhisperTranscript `"), passed)
        self.assertIn("-NarrationSpeechMode $(if ($null -ne $script:MMFullReviewNarration)", body)
        self.assertIn("-TranscriptJsonPath $transcriptJson -Detection $script:MMFullReviewNarration", body)


if __name__ == "__main__":
    unittest.main()
