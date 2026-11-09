"""The backend's side of an honest voice-track verdict (142).

The PowerShell functions are parsed out of "Video Mangler.ps1" and run on
their own, as in test_run_control.py. Everything is synthetic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
import wave

from tests.script_functions import function_text
from tests.test_voice_track import NARRATION_WORDS, _three_track_recording, _transcriber_hearing

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FUNCTIONS = (
    "Read-MMSavedVoiceDetection",
    "Get-MMTranscriptSidePath",
    "Get-MMTranscribedTrack",
    "Set-MMTranscribedTrack",
    "Test-MMTranscribedTriple",
    "Remove-MMTranscriptFiles",
    "Get-CodexEvidenceProblemReason",
    # The narration WAV for Find my bug reports (196), with the real extraction it falls back to.
    "Export-MMNarrationWav",
    "Test-MMTranscriptWavFormat",
    "Export-TranscriptSourceWav",
    "Invoke-ExternalCapture",
    # 214: the WAV is made by the shared decoder, through the Python helper.
    "Invoke-MediaManglersPythonCli",
    "Get-MediaManglersPythonCliInfo",
    "Get-MediaManglersPythonCliUnavailableMessage",
    "Invoke-ExternalStreaming",
    "Read-ProgressStateFile",
    "Get-ProgressStateSignature",
    "Get-ProgressDeviceValue",
    "Get-ProgressDeviceTag",
    "Get-ProgressStateSummary",
    "Format-DurationHuman",
    "Test-ConsoleDebugMode",
    "Test-MMSkipException",
    "Stop-MMProcessTree",
    "Get-MMProcessTreeIds",
    "Remove-MMScratchPath",
    "Get-MMScratchPath",
    "Quote-Argument",
    "Ensure-Directory",
    "Get-ExternalFailureSummary",
    "Add-LogContentWithRetry",
    "Save-MMVoiceDetection",
)


def _run(body: str, folder: Path) -> dict:
    names = ",".join(f"'{name}'" for name in FUNCTIONS)
    source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        $wanted = @({names})
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
            Invoke-Expression $node.Extent.Text
        }}
        function Write-Log {{ }}
        function Invoke-MMRunControlCheck {{ return 0 }}
        function Write-MMProgressV1 {{ }}
        $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{REPO_ROOT / "src"}'; EntryPoint = '' }}
        $script:MMLastResumeAt = $null
        $script:MMProgressPhase = 'Test'
        $script:CurrentLogFile = $null
        $folder = '{folder}'
        {body}
        """
    ).strip()
    harness = folder / "harness.ps1"
    harness.write_text(source, encoding="utf-8")
    process = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr)
    return json.loads(process.stdout.strip().splitlines()[-1])


def _rule_version() -> int:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from media_manglers.core import voice_track

    return voice_track.VOICE_RULE_VERSION


class SavedVoiceVerdictTests(unittest.TestCase):
    # 196 changed this test on purpose: it used to reuse a v1 "selected"
    # verdict. A track chosen under another selection rule is not this rule's
    # answer, so every older verdict, a chosen track included, is heard again.
    def test_an_older_saved_verdict_of_any_kind_is_listened_to_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            recording = folder / "synthetic-session.mkv"
            recording.write_bytes(b"not really video")

            def saved(name: str, schema: str, status: str, *, size: int | None = None, **extra: object) -> None:
                stat = recording.stat()
                payload = {
                    "schema": schema,
                    "source_size": stat.st_size if size is None else size,
                    "source_modified_utc": "",
                    **extra,
                    "detection": {"status": status, "selected_ordinal": 1 if status == "selected" else None},
                }
                (folder / f"{name}.voice.json").write_text(json.dumps(payload), encoding="utf-8")

            saved("v1-selected", "mm-voice-detection-v1", "selected")
            saved("v1-none", "mm-voice-detection-v1", "no_narration_found")
            saved("v1-asked", "mm-voice-detection-v1", "uncertain")
            # v2 was written only by unreleased builds of this change, whose
            # verdict was then corrected again.
            saved("v2-none", "mm-voice-detection-v2", "no_narration_found")
            saved("v3-none", "mm-voice-detection-v3", "no_narration_found")
            saved("v3-selected", "mm-voice-detection-v3", "selected")
            saved("v3-moved", "mm-voice-detection-v3", "selected", size=1)
            saved("v4-none", "mm-voice-detection-v4", "no_narration_found", rule_version=_rule_version(), preferred_ordinals=[])
            saved("v4-other-rule", "mm-voice-detection-v4", "selected", rule_version=_rule_version() - 1, preferred_ordinals=[])
            names = ("v1-selected", "v1-none", "v1-asked", "v2-none", "v3-none", "v3-selected", "v3-moved", "v4-none", "v4-other-rule")
            result = _run(
                f"""
                $video = '{recording}'
                $modified = (Get-Item -LiteralPath $video).LastWriteTimeUtc.ToString('o')
                foreach ($file in Get-ChildItem -LiteralPath $folder -Filter '*.voice.json') {{
                    $json = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
                    $json.source_modified_utc = $modified
                    $json | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $file.FullName -Encoding UTF8
                }}
                $out = [ordered]@{{}}
                foreach ($name in {", ".join(f"'{name}'" for name in names)}) {{
                    $detection = Read-MMSavedVoiceDetection -Path (Join-Path $folder "$name.voice.json") -VideoPath $video
                    $out[$name] = if ($null -eq $detection) {{ 'listen again' }} else {{ [string]$detection.status }}
                }}
                $out | ConvertTo-Json -Compress
                """,
                folder,
            )
        self.assertEqual(
            result,
            {
                "v1-selected": "listen again",
                "v1-none": "listen again",
                "v1-asked": "listen again",
                "v2-none": "listen again",
                "v3-none": "listen again",
                "v3-selected": "listen again",
                "v3-moved": "listen again",
                "v4-none": "no_narration_found",
                "v4-other-rule": "listen again",
            },
        )

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_a_saved_verdict_is_reused_only_from_this_selection_rule(self) -> None:
        # Real detector results, saved by the real Save-MMVoiceDetection and
        # read back by the real Read-MMSavedVoiceDetection: no JSON is written
        # by hand. The older files are the saved ones with one field changed.
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            recording = _three_track_recording(folder / "synthetic-session.mkv")
            for name, words in (("chosen", {1: NARRATION_WORDS}), ("nothing", {})):
                detection = voice_track.detect_voice_track(recording, ffmpeg_exe=shutil.which("ffmpeg"),
                                                           ffprobe_exe=shutil.which("ffprobe"),
                                                           keep_wavs_dir=folder / "voice-work",
                                                           transcriber=_transcriber_hearing(words))
                (folder / f"{name}.detection.json").write_text(json.dumps(detection), encoding="utf-8")
            result = _run(
                f"""
                $video = '{recording}'
                function Load($name) {{ Get-Content -LiteralPath (Join-Path $folder "$name.detection.json") -Raw | ConvertFrom-Json }}
                function Heard($name, [int[]]$preferred) {{
                    $detection = Read-MMSavedVoiceDetection -Path (Join-Path $folder "$name.voice.json") -VideoPath $video -PreferredOrdinals $preferred
                    if ($null -eq $detection) {{ 'listen again' }} else {{ '{{0}} {{1}}' -f [string]$detection.status, [string]$detection.selected_ordinal }}
                }}
                function Older($from, $name, $field, $value) {{
                    $json = Get-Content -LiteralPath (Join-Path $folder "$from.voice.json") -Raw | ConvertFrom-Json
                    $json.$field = $value
                    [System.IO.File]::WriteAllText((Join-Path $folder "$name.voice.json"), ($json | ConvertTo-Json -Depth 12))
                }}
                Save-MMVoiceDetection -Path (Join-Path $folder 'chosen.voice.json') -VideoPath $video -Detection (Load 'chosen') -PreferredOrdinals @(1)
                Save-MMVoiceDetection -Path (Join-Path $folder 'nothing.voice.json') -VideoPath $video -Detection (Load 'nothing') -PreferredOrdinals @()
                Older 'chosen' 'v3-chosen' 'schema' 'mm-voice-detection-v3'
                Older 'chosen' 'v1-chosen' 'schema' 'mm-voice-detection-v1'
                Older 'chosen' 'old-rule' 'rule_version' ([int]((Load 'chosen').rule_version) - 1)
                $saved = Get-Content -LiteralPath (Join-Path $folder 'chosen.voice.json') -Raw | ConvertFrom-Json
                [ordered]@{{
                    schema = [string]$saved.schema
                    ruleVersion = $saved.rule_version
                    keptWavsSaved = ($null -ne $saved.detection.PSObject.Properties['kept_track_wavs'])
                    sameUsualTrack = Heard 'chosen' @(1)
                    noUsualTrack = Heard 'chosen' @()
                    otherUsualTrack = Heard 'chosen' @(0)
                    nothingSameUsualTrack = Heard 'nothing' @()
                    nothingWithAUsualTrack = Heard 'nothing' @(1)
                    v3Chosen = Heard 'v3-chosen' @(1)
                    v1Chosen = Heard 'v1-chosen' @(1)
                    oldRule = Heard 'old-rule' @(1)
                }} | ConvertTo-Json -Compress
                """,
                folder,
            )
        self.assertEqual(
            result,
            {
                "schema": "mm-voice-detection-v4",
                "ruleVersion": voice_track.VOICE_RULE_VERSION,
                "keptWavsSaved": False,
                "sameUsualTrack": "selected 1",
                # The usual track breaks ties, so a verdict reached with
                # another one is not this decision.
                "noUsualTrack": "listen again",
                "otherUsualTrack": "listen again",
                "nothingSameUsualTrack": "no_narration_found ",
                "nothingWithAUsualTrack": "listen again",
                # Before 196 both of these were reused.
                "v3Chosen": "listen again",
                "v1Chosen": "listen again",
                "oldRule": "listen again",
            },
        )

    # 196 renamed this from test_the_backend_saves_new_verdicts_as_v3 on purpose.
    def test_the_backend_saves_new_verdicts_as_v4(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertTrue('schema = "mm-voice-detection-v4"' in text, "no v4 schema is written")
        for old in ("v1", "v2", "v3"):
            self.assertFalse(f'schema = "mm-voice-detection-{old}"' in text, old)
        # Both places the saved verdict is handled know the usual track it was reached with.
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        for call in ("Read-MMSavedVoiceDetection -Path $voiceCachePath -VideoPath $video.FullName -PreferredOrdinals $preferredOrdinals",
                     "Save-MMVoiceDetection -Path $voiceCachePath -VideoPath $video.FullName -Detection $voiceDetection -PreferredOrdinals $preferredOrdinals"):
            self.assertTrue(call in body, call)

    def test_the_backend_and_the_detector_agree_on_the_selection_rule(self) -> None:
        # When the track rule changes, both numbers must move together, or a
        # verdict from the old rule would be trusted under the new one.
        import re

        text = SCRIPT.read_text(encoding="utf-8-sig")
        start = text.index("function Read-MMSavedVoiceDetection {")
        reader = text[start : text.index("\nfunction ", start + 10)]
        found = re.findall(r"\$voiceRuleVersion = (\d+)", reader)
        self.assertEqual(len(found), 1, reader)
        self.assertEqual(int(found[0]), _rule_version())

    def test_the_operators_own_answer_is_never_replaced_by_a_saved_verdict(self) -> None:
        # The track the operator picked arrives as confirmationSource "operator" and skips
        # detection, saved verdicts included: no saved file of any version can
        # stand in for the operator's answer.
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        self.assertTrue(
            '$operatorConfirmedThisFile = $videoAudioSelectionConfirmed -and ($videoAudioConfirmationSource -in @("operator", "explicit parameter"))'
            in body
        )
        self.assertEqual(text.count("Read-MMSavedVoiceDetection -Path"), 1)
        with tempfile.TemporaryDirectory() as temp:
            result = _run(
                f"""
                $tokens = $null; $parseErrors = $null
                $scriptAst = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                $batch = $scriptAst.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-CodexEvidencePackageBatch' }}, $true)
                $read = $batch.Find({{ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Read-MMSavedVoiceDetection' }}, $true)
                $guards = @()
                $node = $read.Parent
                while ($null -ne $node -and $node -ne $batch) {{
                    if ($node -is [System.Management.Automation.Language.IfStatementAst]) {{
                        foreach ($clause in $node.Clauses) {{
                            if ($clause.Item2.Extent.StartOffset -le $read.Extent.StartOffset -and $read.Extent.EndOffset -le $clause.Item2.Extent.EndOffset) {{
                                $guards += $clause.Item1.Extent.Text
                            }}
                        }}
                    }}
                    $node = $node.Parent
                }}
                @{{ guards = @($guards) }} | ConvertTo-Json -Compress
                """,
                Path(temp),
            )
        guards = result["guards"] if isinstance(result["guards"], list) else [result["guards"]]
        self.assertTrue(any("-not $operatorConfirmedThisFile" in guard for guard in guards), result)

    def test_a_question_is_not_answered_with_a_remembered_track_that_had_no_speech(self) -> None:
        # A saved layout confirms Track 2, but detection heard speech only on
        # busy tracks and none on Track 2: using Track 2 anyway would be a
        # guess against what was just heard.
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        remembered = body.index("using the remembered narration Track")
        guard = body.rindex('[string]$voiceDetection.uncertain_reason -eq "speech_on_busy_tracks"', 0, remembered)
        self.assertLess(body.rindex("elseif ($videoAudioSelectionConfirmed -and -not (", 0, remembered), guard)
        self.assertIn("-contains [int]$videoAudioStreamIndex", body[guard:remembered])


class TranscriptReuseTests(unittest.TestCase):
    def test_an_empty_placeholder_is_not_a_finished_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for stem in ("placeholder", "transcribed"):
                (folder / f"{stem}.transcript.json").write_text('{"segments": []}', encoding="utf-8")
                (folder / f"{stem}.transcript.srt").write_text("", encoding="utf-8")
                (folder / f"{stem}.transcript.txt").write_text("", encoding="utf-8")
            # Whisper always writes this beside what it transcribed.
            (folder / "transcribed.transcript.quality.json").write_text("{}", encoding="utf-8")
            result = _run(
                """
                $out = [ordered]@{}
                foreach ($stem in 'placeholder', 'transcribed', 'missing') {
                    $out[$stem] = Test-MMTranscribedTriple -JsonPath (Join-Path $folder "$stem.transcript.json") -SrtPath (Join-Path $folder "$stem.transcript.srt") -TxtPath (Join-Path $folder "$stem.transcript.txt")
                }
                $out | ConvertTo-Json -Compress
                """,
                folder,
            )
        self.assertEqual(result, {"placeholder": False, "transcribed": True, "missing": False})

    def test_a_transcript_is_reused_only_for_the_track_it_was_made_from(self) -> None:
        # The operator answered "which track is you" with Track 1, it had no
        # words, and the operator chose Track 2 on the next Continue: Track 2 must be
        # heard, not Track 1's transcript reused under Track 2's name.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for stem in ("track-one", "older"):
                (folder / f"{stem}.transcript.json").write_text('{"segments": []}', encoding="utf-8")
                (folder / f"{stem}.transcript.srt").write_text("", encoding="utf-8")
                (folder / f"{stem}.transcript.txt").write_text("", encoding="utf-8")
                (folder / f"{stem}.transcript.quality.json").write_text("{}", encoding="utf-8")
            result = _run(
                """
                $json = Join-Path $folder 'track-one.transcript.json'
                $srt = Join-Path $folder 'track-one.transcript.srt'
                $txt = Join-Path $folder 'track-one.transcript.txt'
                Set-MMTranscribedTrack -JsonPath $json -AudioOrdinal 0
                $old = Join-Path $folder 'older.transcript.json'
                $out = [ordered]@{
                    recorded = Get-MMTranscribedTrack -JsonPath $json
                    sameTrack = Test-MMTranscribedTriple -JsonPath $json -SrtPath $srt -TxtPath $txt -AudioOrdinal 0
                    otherTrack = Test-MMTranscribedTriple -JsonPath $json -SrtPath $srt -TxtPath $txt -AudioOrdinal 1
                    madeBeforeTracksWereRecorded = Test-MMTranscribedTriple -JsonPath $old -SrtPath ($old -replace 'json$', 'srt') -TxtPath ($old -replace 'json$', 'txt') -AudioOrdinal 1
                    operatorNamedTheTrack = Test-MMTranscribedTriple -JsonPath $old -SrtPath ($old -replace 'json$', 'srt') -TxtPath ($old -replace 'json$', 'txt') -AudioOrdinal 1 -RequireTrackRecord
                }
                $out | ConvertTo-Json -Compress
                """,
                folder,
            )
        self.assertEqual(
            result,
            {
                "recorded": 0,
                "sameTrack": True,
                "otherTrack": False,
                # Detection chose the track: an older transcript is trusted as before.
                "madeBeforeTracksWereRecorded": True,
                # The operator named the track: one that may be another's is redone.
                "operatorNamedTheTrack": False,
            },
        )

    def test_clearing_a_transcript_leaves_nothing_that_marks_finished_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            names = [
                "x.transcript.json", "x.transcript.srt", "x.transcript.txt", "x.transcript.quality.json",
                "x.transcript.raw.json", "x.transcript.vad.json", "x.transcript.track.json", "x.audio.flac",
                "x.audio.wav", "x.voice.json",
            ]
            for name in names:
                (folder / name).write_text("{}", encoding="utf-8")
            result = _run(
                """
                $json = Join-Path $folder 'x.transcript.json'
                Remove-MMTranscriptFiles -JsonPath $json -SrtPath (Join-Path $folder 'x.transcript.srt') -TxtPath (Join-Path $folder 'x.transcript.txt') -AudioPaths @((Join-Path $folder 'x.audio.wav'), (Join-Path $folder 'x.audio.flac'))
                @{ left = @(Get-ChildItem -LiteralPath $folder -Filter 'x.*' | ForEach-Object Name) } | ConvertTo-Json -Compress
                """,
                folder,
            )
        # The voice verdict is about the recording, not about a transcript.
        left = result["left"]
        self.assertEqual(left if isinstance(left, list) else [left], ["x.voice.json"])

    def test_the_evidence_run_uses_those_checks_and_the_transcript_only_run_is_left_alone(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        self.assertIn(
            "Test-MMTranscribedTriple -JsonPath $jsonPath -SrtPath $srtPath -TxtPath $txtPath -AudioOrdinal ([int]$videoAudioStreamIndex)"
            ' -RequireTrackRecord:($videoAudioConfirmationSource -eq "operator")',
            body,
        )
        # A fresh transcription starts clean, audio included: an interrupted
        # run can leave another track's extracted audio behind.
        fresh = body[body.index("$madeFromTrack = Get-MMTranscribedTrack -JsonPath $jsonPath") :]
        self.assertLess(
            fresh.index("Remove-MMTranscriptFiles -JsonPath $jsonPath -SrtPath $srtPath -TxtPath $txtPath -AudioPaths @($workingAudioWavPath, $audioPath)"),
            fresh.index("Export-MMNarrationWav"),
        )
        # Recorded as soon as Whisper has written the triple, for every way
        # of transcribing (the legacy helper writes no quality file).
        written = body.index("Set-MMTranscribedTrack -JsonPath $jsonPath -AudioOrdinal ([int]$videoAudioStreamIndex)")
        self.assertLess(body.index("the expected transcript JSON/SRT/TXT triple was not found"), written)
        # A reused transcript that was blocked as invented stays blocked.
        reuse = body[body.index("if ($transcriptTripleExists -and -not $OverwriteTranscripts) {") :]
        self.assertLess(reuse.index('$status = "quality_blocked"'), reuse.index("Skipping existing Codex evidence transcript triple"))
        # Overwriting, or a different track, clears the side files too.
        self.assertIn("Remove-MMTranscriptFiles -JsonPath $jsonPath", body)
        start = text.index("function Invoke-TranscriptOnlyBatch {")
        transcript_only = text[start : text.index("\nfunction ", start + 10)]
        self.assertNotIn("Test-MMTranscribedTriple", transcript_only)


def _chunk_at(data: bytes, chunk_id: bytes) -> int:
    """Where a RIFF chunk starts in a WAV file's bytes."""

    position = 12
    while position + 8 <= len(data):
        if data[position : position + 4] == chunk_id:
            return position
        size = int.from_bytes(data[position + 4 : position + 8], "little")
        position += 8 + size + (size % 2)
    raise ValueError(f"no {chunk_id!r} chunk")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class NarrationWavReuseTests(unittest.TestCase):
    """196: the narration WAV is the audio voice detection already decoded, when it is sound.

    The kept WAVs and their list come from the real detector on a synthetic recording (only
    Whisper is stood in for), passed through JSON as the backend receives them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.recording = _three_track_recording(Path(cls._temp.name) / "synthetic-session.mkv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def _detect(self, folder: Path, words: dict[int, str], **kwargs: object) -> dict:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from media_manglers.core import voice_track

        result = voice_track.detect_voice_track(self.recording, ffmpeg_exe=shutil.which("ffmpeg"),
                                                ffprobe_exe=shutil.which("ffprobe"), work_dir=folder / "work",
                                                keep_wavs_dir=folder / "voice-work",
                                                transcriber=_transcriber_hearing(words), **kwargs)
        (folder / "detection.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    def _narration(self, folder: Path, *, ordinal: int, kept: str = "$detection.kept_track_wavs",
                   video: str | None = None) -> dict:
        return _run(
            f"""
            $script:logged = New-Object System.Collections.Generic.List[string]
            function Write-Log {{ param([string]$Message, [string]$Level = 'INFO') $script:logged.Add($Message) }}
            $detection = Get-Content -LiteralPath (Join-Path $folder 'detection.json') -Raw | ConvertFrom-Json
            $output = Join-Path $folder 'audio\\narration.audio.wav'
            $status = Export-MMNarrationWav -FFmpegExe '{shutil.which("ffmpeg")}' -InputVideo '{video or self.recording}' -OutputWav $output -AudioOrdinal {ordinal} -KeptWavs {kept} -PythonCommand '{sys.executable}'
            @{{ status = $status; output = $output; log = @($script:logged) }} | ConvertTo-Json -Compress
            """,
            folder,
        )

    def test_the_chosen_tracks_audio_is_reused_and_the_recording_is_not_read_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            detection = self._detect(folder, {1: NARRATION_WORDS})
            self.assertEqual(detection["selected_ordinal"], 1, detection)
            kept = Path(detection["kept_track_wavs"][0]["path"])
            kept_bytes = kept.read_bytes()
            # A recording that does not exist: had FFmpeg been asked to read it, this would fail.
            result = self._narration(folder, ordinal=1, video=str(folder / "no-such-recording.mkv"))
            self.assertEqual(result["status"], "REUSED_VOICE_DETECTION", result)
            self.assertEqual(Path(result["output"]).read_bytes(), kept_bytes)
            self.assertFalse(kept.exists())
        self.assertTrue(any("reused the decoded audio from voice detection; the recording was not read again" in line
                            for line in result["log"]), result["log"])

    def test_another_tracks_audio_or_none_falls_back_to_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            # Detection asked, and kept only the usual Track 1; the operator then chose Track 2.
            detection = self._detect(folder, {0: NARRATION_WORDS}, preferred_ordinals=[0])
            self.assertEqual([item["ordinal"] for item in detection["kept_track_wavs"]], [0])
            other_track = self._narration(folder, ordinal=1)
            with wave.open(other_track["output"], "rb") as audio:
                other_seconds = audio.getnframes() / audio.getframerate()
            Path(other_track["output"]).unlink()
            # A saved verdict or a Continue: nothing was kept at all.
            nothing_kept = self._narration(folder, ordinal=1, kept="$null")
            self.assertTrue(Path(nothing_kept["output"]).is_file())
        self.assertEqual(other_track["status"], "CREATED", other_track)
        self.assertAlmostEqual(other_seconds, 20.0, delta=0.1)
        self.assertEqual(nothing_kept["status"], "CREATED", nothing_kept)

    def test_a_damaged_kept_wav_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            detection = self._detect(folder, {1: NARRATION_WORDS})
            kept = Path(detection["kept_track_wavs"][0]["path"])
            good = kept.read_bytes()
            data_at = _chunk_at(good, b"data")
            header_only = bytearray(good[: data_at + 8])
            header_only[data_at + 4 : data_at + 8] = (0).to_bytes(4, "little")
            header_only[4:8] = (len(header_only) - 8).to_bytes(4, "little")
            wrong_rate = bytearray(good)
            rate_at = _chunk_at(good, b"fmt ") + 12
            wrong_rate[rate_at : rate_at + 4] = (8000).to_bytes(4, "little")
            outcomes = {}
            for name, damaged in (("no audio in it", header_only), ("wrong sample rate", wrong_rate)):
                kept.write_bytes(bytes(damaged))
                result = self._narration(folder, ordinal=1)
                outcomes[name] = (result["status"], kept.exists())
                Path(result["output"]).unlink()
        self.assertEqual(outcomes, {"no audio in it": ("CREATED", False), "wrong sample rate": ("CREATED", False)})

    def test_a_saved_verdict_never_keeps_a_wav_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            detection = self._detect(folder, {1: NARRATION_WORDS})
            self.assertTrue(detection["kept_track_wavs"])
            _run(
                f"""
                $detection = Get-Content -LiteralPath (Join-Path $folder 'detection.json') -Raw | ConvertFrom-Json
                Save-MMVoiceDetection -Path (Join-Path $folder 'x.voice.json') -VideoPath '{self.recording}' -Detection $detection
                @{{ kept = @($detection.kept_track_wavs).Count }} | ConvertTo-Json -Compress
                """,
                folder,
            )
            saved = json.loads((folder / "x.voice.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["detection"]["status"], "selected")
        self.assertEqual(saved["detection"]["selected_ordinal"], 1)
        self.assertNotIn("kept_track_wavs", saved["detection"])

    def test_the_evidence_run_reuses_detection_audio_only_after_clearing_old_files(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        fresh = body[body.index("$madeFromTrack = Get-MMTranscribedTrack -JsonPath $jsonPath") :]
        fresh = fresh[: fresh.index("Invoke-PythonWhisperTranscript")]
        self.assertLess(fresh.index("Remove-MMTranscriptFiles -JsonPath $jsonPath"), fresh.index("Export-MMNarrationWav"))
        self.assertNotIn("Export-TranscriptSourceWav", fresh)
        self.assertIn("-KeepWavDir $keepVoiceWavDir", body)
        self.assertIn('$keepVoiceWavDir = if ($canReuseFullReviewTranscript) { "" } else { $voiceWavFolder }', body)
        # The kept audio is removed whatever happens to the recording, before the package is written.
        per_video = body[body.index("foreach ($video in $videos) {") : body.index("[void]$manifestEntries.Add(")]
        self.assertIn("Remove-MMScratchPath -Path $voiceWavFolder", per_video[per_video.rindex("finally {") :])
        after_loop = body[body.index("[void]$manifestEntries.Add(") : body.index("Invoke-CodexEvidenceDetectHelper")]
        self.assertIn("Remove-MMScratchPath -Path $voiceWavFolder", after_loop)
        # Its fallback extraction is stopped only when FFmpeg stops moving (145), like the call it replaced.
        start = text.index("function Export-MMNarrationWav {")
        wrapper = text[start : text.index("\nfunction ", start + 10)]
        self.assertIn("-StallTimeoutSeconds 180", wrapper)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class EvidenceRunVoiceAudioTests(unittest.TestCase):
    """196, through the real Find my bug reports backend on a synthetic recording.

    Every function in the script is the real one, including the Python helper call and the
    detector behind it. Only Whisper (in detection and in transcription), run control, the
    Workbench progress lines and the package writer are stood in for. The backend's FFmpeg is a
    launcher that notes each call and runs the real FFmpeg.
    """

    SHIM = textwrap.dedent(
        """
        import json, sys, tempfile, time
        from unittest import mock
        sys.path.insert(0, SRC)
        from media_manglers import cli
        from media_manglers.core import voice_track

        def transcriber(path):
            if globals().get('TEMPS'):
                # Where the helper's own temporary files go, and the files the backend handed it.
                with open(TEMPS, 'a', encoding='utf-8') as handle:
                    handle.write(json.dumps({'tempdir': tempfile.gettempdir(),
                                             'request': args[args.index('--request-file') + 1],
                                             'result': args[args.index('--result-file') + 1]}) + '\\n')
            if globals().get('HANG'):
                # Listening stops: nothing new is reported while this sleeps.
                time.sleep(HANG)
            text = WORDS.get(path.stem.split('-')[-1], '')
            return [{'text': text, 'no_speech_prob': 0.05, 'avg_logprob': -0.3}] if text else []

        args = sys.argv[1:]
        # What the backend asked the detector for, as it asked it.
        with open(args[args.index('--request-file') + 1], encoding='utf-8-sig') as handle:
            payload = json.load(handle).get('payload', {})
        with open(PAYLOADS, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(payload) + '\\n')
        real_run = voice_track.run_while_progressing

        def run_while_progressing(command, **options):
            # A shorter stall limit, so a decode that stops moving is stopped in seconds.
            if globals().get('STALL'):
                options['stall_seconds'] = STALL
            return real_run(command, **options)

        with mock.patch.object(voice_track, 'whisper_transcriber', return_value=transcriber), \\
                mock.patch.object(voice_track, 'run_while_progressing', run_while_progressing):
            raise SystemExit(cli.main(args[args.index('media_manglers') + 1 :]))
        """
    )

    FFMPEG = textwrap.dedent(
        """
        import json, subprocess, sys
        with open(RECORD, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(sys.argv[1:]) + '\\n')
        raise SystemExit(subprocess.run([REAL] + sys.argv[1:]).returncode)
        """
    )

    # The recording's drive goes to sleep while voice detection reads it:
    # FFmpeg reports one position, then the same one again and again.
    STALLING_FFMPEG = textwrap.dedent(
        """
        import subprocess, sys, time
        args = sys.argv[1:]
        if 'pipe:1' in args:
            try:
                for _ in range(100):
                    print('out_time_us=1000000', flush=True)
                    print('progress=continue', flush=True)
                    time.sleep(0.2)
            except OSError:
                pass
            raise SystemExit(1)
        raise SystemExit(subprocess.run([REAL] + args).returncode)
        """
    )

    def _launcher(self, root: Path, name: str, code: str, **values: object) -> Path:
        script = root / f"{name}.py"
        script.write_text("".join(f"{key} = {value!r}\n" for key, value in values.items()) + code, encoding="utf-8")
        launcher = root / f"{name}.cmd"
        launcher.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        return launcher

    def _run_batch(self, root: Path, source: Path, *, whisper: str = "", ffmpeg_code: str | None = None,
                   arguments: str = "", env: dict[str, str] | None = None, after: str = "",
                   **shim: object) -> dict:
        """Run the real Invoke-CodexEvidencePackageBatch up to the package step.

        ``whisper`` is PowerShell run by the stand-in transcription after it notes the WAV it was
        given. The result holds what was in the package's audio folder when the package writer was
        called (``None`` when it never was), the error the run stopped with, the run log, every
        request the detector received and every FFmpeg command. ``env`` is added to the backend's
        environment; ``after`` is PowerShell run in the same process once the batch has stopped,
        and what it returns is ``after``. ``pid`` is the backend's process id.
        """
        calls = root / "ffmpeg-calls.txt"
        payloads = root / "payloads.txt"
        python = self._launcher(root, "python", self.SHIM, SRC=str(REPO_ROOT / "src"), WORDS={"1": NARRATION_WORDS},
                                PAYLOADS=str(payloads), **shim)
        ffmpeg = self._launcher(root, "ffmpeg", ffmpeg_code or self.FFMPEG, RECORD=str(calls), REAL=shutil.which("ffmpeg"))
        package = root / "out" / "codex-evidence-package"
        script = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
            foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }}, $false)) {{
                Invoke-Expression $node.Extent.Text
            }}
            $script:MMSkipMessagePrefix = "MM_SKIP_REQUESTED"
            $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{REPO_ROOT / "src"}'; EntryPoint = '' }}
            function Invoke-MMRunControlCheck {{ return 0 }}
            function Write-MMProgressV1 {{ }}
            $script:heard = @()
            function Invoke-PythonWhisperTranscript {{
                param([string]$PythonCommand, [string]$AudioPath, [string]$TranscriptFolder, [string]$ModelName, [string]$LanguageCode,
                    [string]$FFmpegExe, [bool]$PreferGpu, [string]$Task, [string]$JsonName, [string]$SrtName, [string]$TextName,
                    [string]$InitialPrompt, [string]$NarrationSpeechMode, [double]$SourceDurationSeconds, [int]$HeartbeatSeconds,
                    [int]$WhisperTimeoutSeconds, [switch]$InteractiveMode, [switch]$AllowInteractiveLongRunPrompt)
                $script:heard += [pscustomobject]@{{ path = $AudioPath; bytes = (Get-Item -LiteralPath $AudioPath).Length }}
                {whisper}
                Set-Content -LiteralPath (Join-Path $TranscriptFolder $JsonName) -Value '{{"segments": []}}'
                Set-Content -LiteralPath (Join-Path $TranscriptFolder $SrtName) -Value ''
                Set-Content -LiteralPath (Join-Path $TranscriptFolder $TextName) -Value ''
            }}
            $script:atPackage = $null
            function Invoke-CodexEvidenceDetectHelper {{
                param($Sources)
                $audio = '{package / "audio"}'
                $script:atPackage = [pscustomobject]@{{
                    confirmation_sources = @($Sources | ForEach-Object {{ [string]$_.audio_stream_confirmation_source }})
                    voice_work_exists = (Test-Path -LiteralPath (Join-Path $audio 'voice-work'))
                    files = @(Get-ChildItem -LiteralPath $audio -Recurse -File | ForEach-Object Name)
                    statuses = @($Sources | ForEach-Object {{ '{{0}}={{1}}' -f $_.source_filename, $_.status }})
                }}
                throw 'package step reached'
            }}
            $failure = ''
            try {{
                Invoke-CodexEvidencePackageBatch -InputPath '{source}' -OutputFolder '{root / "out"}' -PythonCommand '{python}' -FFmpegExe '{ffmpeg}' -FFprobeExe '{shutil.which("ffprobe")}' -ModelName 'base.en' -LanguageCode 'en' -CanUseWhisperGpu $false {arguments} | Out-Null
            }}
            catch {{
                if ($_.Exception.Message -ne 'package step reached') {{ $failure = $_.Exception.Message }}
            }}
            $ffmpegLauncher = '{ffmpeg}'
            $pythonLauncher = '{python}'
            $afterResult = & {{ {after} }}
            @{{ atPackage = $script:atPackage; heard = @($script:heard); failure = $failure; pid = $PID; after = $afterResult }} | ConvertTo-Json -Compress -Depth 6
            """
        ).strip()
        harness = root / "harness.ps1"
        harness.write_text(script, encoding="utf-8")
        process = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
            capture_output=True, text=True, timeout=600, env=dict(os.environ, **(env or {})),
        )
        self.assertEqual(process.returncode, 0, process.stderr[-4000:])
        result = json.loads(process.stdout.strip().splitlines()[-1])
        result["stdout"] = process.stdout
        if result["atPackage"] is not None:
            for key in ("files", "statuses"):
                value = result["atPackage"][key]
                result["atPackage"][key] = [value] if isinstance(value, str) else list(value or [])
        result["log"] = (package / "codex_evidence_run.log").read_text(encoding="utf-8-sig")
        # 264: every request but the quick question asked first, which ``lookups`` holds.
        requests = [json.loads(line) for line in payloads.read_text(encoding="utf-8").splitlines()] \
            if payloads.exists() else []
        result["lookups"] = [item for item in requests if "use_saved_layouts" in item]
        result["payloads"] = [item for item in requests if "use_saved_layouts" not in item]
        result["reads"] = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] \
            if calls.exists() else []
        result["voice"] = [json.loads(path.read_text(encoding="utf-8-sig"))
                           for path in (package / "transcript" / "sources").glob("*.voice.json")]
        return result

    def test_264_a_second_package_of_a_known_recording_listens_to_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            (root / "first").mkdir()
            (root / "second").mkdir()
            first = self._run_batch(root / "first", recording)
            self.assertIsNotNone(first["atPackage"], first["failure"] or first["log"][-3000:])
            self.assertEqual(len([item for item in first["payloads"] if item.get("measured_by")]), 1, "the first one listened")
            self.assertIn("Listening", self._listened_line(first))
            second = self._run_batch(root / "second", recording)
        self.assertIsNotNone(second["atPackage"], second["failure"] or second["log"][-3000:])
        self.assertEqual([item for item in second["payloads"] if item.get("measured_by")], [], "nothing was listened to")
        self.assertIn("The library already knows the voice track", second["log"])
        self.assertIn("(selected, auto", second["log"])
        self.assertEqual(self._listened_line(second), "")
        self.assertEqual([item["track_number"] for item in second["voice"][0]["detection"]["tracks"] if item["ordinal"] == 1], [2])
        for result in (first, second):
            saved = json.dumps(result["voice"])
            for private in ("moments", "track_activity", "track_probes", "track_levels", "sample_text"):
                self.assertNotIn(private, saved)
        self.assertEqual(second["voice"][0]["detection"]["selected_ordinal"], first["voice"][0]["detection"]["selected_ordinal"])

    @staticmethod
    def _listened_line(result: dict) -> str:
        return result["stdout"] if "Listening to every audio track" in result["stdout"] else ""

    def test_264_your_answer_comes_before_what_an_earlier_run_of_this_package_heard(self) -> None:
        from media_manglers.core import speech_facts

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            (root / "out").mkdir()
            first = self._run_batch(root, recording)
            self.assertEqual(first["voice"][0]["detection"]["selected_ordinal"], 1)
            speech_facts.confirm_track(recording, 3, by=speech_facts.ANSWERED_ON_BUGS)
            (root / "payloads.txt").unlink()
            second = self._run_batch(root, recording)
        self.assertEqual([item for item in second["payloads"] if item.get("measured_by")], [])
        self.assertEqual(second["voice"][0]["detection"]["decided_by"], "auto", "your answer is not put in the package's saved result")
        self.assertNotIn("You chose", json.dumps(second["voice"]))
        self.assertIn("The library already knows the voice track", second["log"])
        self.assertIn("(selected, confirmed)", second["log"])
        self.assertEqual(second["atPackage"]["confirmation_sources"], ["operator"], "the package says who chose it, as for any forced track")
        self.assertIn("Voice found on Track 3 (you chose)", second["stdout"])

    def test_264_an_old_raw_bin_row_is_used_through_the_backend_with_a_game_audio_setting(self) -> None:
        # The setting as the operator saved it reaches the check: the row was scanned with "3=game".
        import sqlite3

        from media_manglers.core import recording_records

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            stat = recording.stat()
            connection = recording_records.connect(backup=False)
            try:
                with connection:
                    recording_id = int(connection.execute(
                        "INSERT INTO recordings(first_seen_utc, content_sha256, size_bytes, narration_track, rules_roles, "
                        "track_titles_json) VALUES ('x', ?, ?, 2, '3=game', '{}')", ("a" * 64, stat.st_size)).lastrowid)
                    connection.execute(
                        "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, missing, "
                        "first_seen_utc, last_seen_utc) VALUES (?, ?, ?, '', ?, ?, 1, 0, 'x', 'x')",
                        (recording_id, str(recording), recording_records.path_key(recording), stat.st_size, stat.st_mtime_ns))
            finally:
                connection.close()
            self.assertIsInstance(sqlite3.sqlite_version, str)
            result = self._run_batch(root, recording, arguments="-TrackRoles '3=game'")
        self.assertEqual([item for item in result["payloads"] if item.get("measured_by")], [], "nothing was listened to")
        self.assertEqual(result["voice"][0]["detection"]["selected_ordinal"], 1)

    def test_264_the_detection_is_given_this_recordings_own_remembered_pick(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording)
        self.assertEqual(result["lookups"][0]["use_saved_layouts"], True, "asked before anything is heard")
        self.assertEqual(result["lookups"][0]["preferred_ordinals"], [])
        self.assertEqual([item.get("preferred_ordinals") for item in result["payloads"] if item.get("measured_by")], [[]],
                         "no saved answer for this layout: no remembered pick")

    def test_264_a_library_that_cannot_be_asked_only_means_the_run_listens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording, env={"MEDIA_MANGLERS_LIBRARY_ROOT": str(recording)})
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        self.assertEqual(len([item for item in result["payloads"] if item.get("measured_by")]), 1)

    def test_the_kept_audio_is_used_and_gone_before_the_package_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording, arguments="-AudioStreamIndex 2")
        # 201: the small review copy reads the recording too, now while Whisper works rather
        # than after the package is written. It is the review copy's own read, made once.
        review_copy = [args for args in result["reads"] if str(recording) in args
                       and any("review_video_" in str(arg) for arg in args)]
        recording_reads = [args for args in result["reads"] if str(recording) in args and args not in review_copy]
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        self.assertLessEqual(len(review_copy), 1, review_copy)
        # Read once, by voice detection; the narration was the audio it kept.
        self.assertEqual(len(recording_reads), 1, recording_reads)
        self.assertIn("reused the decoded audio from voice detection; the recording was not read again", result["log"])
        self.assertEqual(len(result["heard"]), 1)
        self.assertGreater(result["heard"][0]["bytes"], 600000)
        self.assertTrue(result["heard"][0]["path"].endswith(".audio.wav"))
        # The remembered Track 3 was kept too and not used: none of it may reach the package.
        self.assertFalse(result["atPackage"]["voice_work_exists"], result["atPackage"])
        self.assertEqual([name for name in result["atPackage"]["files"] if name.endswith(".wav")], [])
        self.assertEqual(len(result["voice"]), 1)
        self.assertNotIn("kept_track_wavs", result["voice"][0]["detection"])

    def test_a_recording_that_fails_or_is_skipped_leaves_no_audio_for_the_package(self) -> None:
        # The narration WAV (the audio voice detection kept, moved in) of a
        # recording whose transcription failed, or that the operator skipped,
        # is not used, and the package ZIP takes .wav files.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recordings = root / "recordings"
            recordings.mkdir()
            first = _three_track_recording(recordings / "a-session.mkv")
            shutil.copy(first, recordings / "b-session.mkv")
            shutil.copy(first, recordings / "c-session.mkv")
            result = self._run_batch(
                root, recordings, arguments="-AudioStreamIndex 2",
                whisper="if ($JsonName -like 'b-*') { throw 'Whisper stopped reporting progress' } "
                        "if ($JsonName -like 'c-*') { throw ($script:MMSkipMessagePrefix + ': skipped by you (c-session.mkv).') }",
            )
        at_package = result["atPackage"]
        self.assertIsNotNone(at_package, result["failure"] or result["log"][-3000:])
        self.assertEqual(sorted(at_package["statuses"]),
                         ["a-session.mkv=completed", "b-session.mkv=failed", "c-session.mkv=operator_skipped"])
        # Each recording's narration WAV was there when transcription started.
        self.assertEqual(len(result["heard"]), 3)
        self.assertTrue(all(item["bytes"] > 600000 for item in result["heard"]), result["heard"])
        self.assertEqual([name for name in at_package["files"] if name.lower().endswith(".wav")], [])

    def test_a_recording_that_stopped_being_read_is_reported_as_that(self) -> None:
        # 145: the drive went to sleep while voice detection read the
        # recording. Choosing a track would not help, so the operator reads
        # where reading stopped and what to check.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording, ffmpeg_code=self.STALLING_FFMPEG, STALL=2.0)
        self.assertIsNone(result["atPackage"])
        self.assertIn("No usable narration transcript was produced", result["failure"])
        reason = next(line for line in result["failure"].splitlines() if "synthetic-session.mkv:" in line)
        self.assertIn("00:01", reason)
        self.assertIn("the drive may have gone to sleep or been disconnected", reason)
        self.assertNotIn("choose the track with your voice", reason)

    def test_the_full_review_add_on_keeps_no_audio_it_will_not_use(self) -> None:
        # The add-on reuses Full Review's transcript, so voice detection keeps
        # no audio for it: whole tracks moved into the package only to be
        # deleted are work Full Review never did before 196.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            review = root / "full-review"
            review.mkdir()
            for name, text in (("t.json", '{"segments": []}'), ("t.srt", ""), ("t.txt", "")):
                (review / name).write_text(text, encoding="utf-8")
            result = self._run_batch(
                root, recording,
                arguments=f"-AudioStreamIndex 2 -InvocationMode 'full-review-addon' -ExistingTranscriptJsonPath '{review / 't.json'}' "
                          f"-ExistingTranscriptSrtPath '{review / 't.srt'}' -ExistingTranscriptTextPath '{review / 't.txt'}'",
            )
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        self.assertIn("Reusing Full Review transcript", result["log"])
        self.assertEqual(len(result["payloads"]), 1, "voice detection still ran")
        self.assertEqual(result["payloads"][0].get("keep_wavs_dir"), "")
        self.assertEqual(result["heard"], [])

    def test_no_wav_is_left_in_the_audio_folder_when_the_package_is_written(self) -> None:
        # The package ZIP takes every file under audio\, and a .wav of a whole
        # track is the operator's microphone for the whole race. Whatever left
        # one there, none is handed to the package writer.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(
                root, recording, arguments="-AudioStreamIndex 2",
                whisper="$audioDir = Split-Path -Parent $AudioPath; "
                        "$tracksDir = Join-Path $audioDir 'tracks'; "
                        "New-Item -ItemType Directory -Force -Path $tracksDir | Out-Null; "
                        "Set-Content -LiteralPath (Join-Path $audioDir 'stray.wav') -Value 'x'; "
                        "Set-Content -LiteralPath (Join-Path $tracksDir 'track_02.wav') -Value 'x'",
            )
        at_package = result["atPackage"]
        self.assertIsNotNone(at_package, result["failure"] or result["log"][-3000:])
        self.assertEqual([name for name in at_package["files"] if name.lower().endswith(".wav")], [], at_package)
        self.assertTrue(any(name.endswith(".audio.flac") for name in at_package["files"]), at_package)
        self.assertIn("Removed 2 .wav file(s) from the package's audio folder before the package was written.", result["log"])

    def test_work_files_left_by_a_stopped_run_are_removed_and_nothing_else(self) -> None:
        # Stop in the Workbench ends the backend at once, so its clean-up never
        # runs. The next voice detection removes what a run that is no longer
        # running left, and only that.
        def guid() -> str:
            return str(uuid.uuid4())

        ended = subprocess.Popen([sys.executable, "-c", "pass"])
        ended.wait()
        dead, alive = ended.pid, os.getpid()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scratch = root / "scratch"
            scratch.mkdir()
            removed = [
                scratch / f"media_manglers_voice_work_{dead}_{guid()}",
                scratch / f"media_manglers_voice_progress_{dead}_{guid()}.json",
                scratch / f"media_manglers_voice_progress_{dead}_{guid()}.json.tmp",
                scratch / f"media_manglers_ffmpeg_progress_{dead}_{guid()}.txt",
                scratch / f"media_manglers_audio_progress_{dead}_{guid()}.json",
                # 201: and every other work file a stopped run can leave.
                scratch / f"media_manglers_request_{dead}_{guid()}.json",
                scratch / f"media_manglers_result_{dead}_{guid()}.json",
                scratch / f"media_manglers_whisper_progress_{dead}_{guid()}.json",
                scratch / f"media_manglers_whisper_probe_{dead}_{guid()}.py",
                scratch / f"media_manglers_whisper_transcribe_{dead}_{guid()}.py",
                scratch / f"media_manglers_whisper_calibration_{dead}_{guid()}",
                scratch / f"media_manglers_evidence_frames_{dead}_{guid()}",
                scratch / f"media_manglers_evidence_audio_{dead}_{guid()}",
                scratch / f"media_manglers_cross_check_{dead}_k2x9_q7a",
                scratch / f"media_manglers_voice_helper_{dead}_ab12cd34",
            ]
            kept = [
                scratch / f"media_manglers_request_{alive}_{guid()}.json",
                scratch / f"media_manglers_evidence_frames_{alive}_{guid()}",
                scratch / f"media_manglers_cross_check_{alive}_k2x9_q7a",
                # Another run that is still going may own these.
                scratch / f"media_manglers_voice_work_{alive}_{guid()}",
                scratch / f"media_manglers_voice_progress_{alive}_{guid()}.json",
                scratch / f"media_manglers_ffmpeg_progress_{alive}_{guid()}.txt",
                scratch / f"media_manglers_audio_progress_{alive}_{guid()}.json",
                # Names from before process ids were in them.
                scratch / f"media_manglers_voice_work_{guid()}",
                scratch / f"media_manglers_voice_progress_{guid()}.json",
                scratch / f"media_manglers_ffmpeg_progress_{guid()}.txt",
                # Not exactly one of the app's names.
                scratch / f"media_manglers_voice_work_{dead}_not-a-guid",
                scratch / f"media_manglers_voice_progress_{dead}_{guid()}.json.bak",
                scratch / f"some_other_tool_{dead}_{guid()}",
            ]
            for path in removed + kept:
                if path.suffix not in {".json", ".txt", ".tmp", ".bak", ".py"}:
                    path.mkdir()
                    (path / "track-0.wav").write_bytes(b"0" * 4096)
                else:
                    path.write_text("{}", encoding="utf-8")
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording, arguments="-AudioStreamIndex 2",
                                     env={"MEDIA_MANGLERS_SCRATCH_ROOT": str(scratch)})
            left_removed = [path.name for path in removed if path.exists()]
            left_kept = [path.name for path in kept if path.exists()]
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        self.assertEqual(left_removed, [], "work files of a run that is no longer running are removed")
        self.assertEqual(left_kept, [path.name for path in kept], "nothing else is touched")
        self.assertIn("Removed 15 work file(s) left behind by an earlier run that was stopped.", result["log"])

    def test_scratch_goes_under_the_scratch_root_when_one_is_set(self) -> None:
        # MEDIA_MANGLERS_SCRATCH_ROOT moves voice detection's decoded audio,
        # the progress files and the Python helper's own temporary files.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            override = root / "scratch-override"
            temps = root / "temps.txt"
            recording = _three_track_recording(root / "synthetic-session.mkv")
            extract = root / "extract.wav"
            result = self._run_batch(
                root, recording, arguments="-AudioStreamIndex 2", TEMPS=str(temps),
                env={"MEDIA_MANGLERS_SCRATCH_ROOT": str(override)},
                # The narration extraction's progress file, by the real function and the shared decoder.
                after=f"Export-TranscriptSourceWav -PythonCommand $pythonLauncher -FFmpegExe $ffmpegLauncher -InputVideo '{recording}' "
                      f"-OutputWav '{extract}' -FfmpegMap '0:a:0' -StallTimeoutSeconds 30 -HeartbeatSeconds 1 | Out-Null",
            )
            helper = [json.loads(line) for line in temps.read_text(encoding="utf-8").splitlines()] if temps.exists() else []
            extracted = extract.is_file()
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        pid = result["pid"]
        guid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        payload = result["payloads"][0]
        work, progress = Path(payload["work_dir"]), Path(payload["progress_state_file_path"])
        self.assertEqual(os.path.normcase(str(work.parent)), os.path.normcase(str(override)), work)
        self.assertRegex(work.name, rf"^media_manglers_voice_work_{pid}_{guid}$")
        self.assertEqual(os.path.normcase(str(progress.parent)), os.path.normcase(str(override)), progress)
        self.assertRegex(progress.name, rf"^media_manglers_voice_progress_{pid}_{guid}\.json$")
        self.assertTrue(extracted)
        # 214: every decode is the shared decoder's, reporting on pipe:1; the extraction's own
        # progress file for the backend is under the scratch root too.
        for args in result["reads"]:
            if "-progress" in args:
                self.assertEqual(args[args.index("-progress") + 1], "pipe:1", args)
        extraction = next(item for item in result["payloads"] if item.get("output_path"))
        audio_progress = Path(extraction["progress_state_file_path"])
        self.assertEqual(os.path.normcase(str(audio_progress.parent)), os.path.normcase(str(override)), audio_progress)
        self.assertRegex(audio_progress.name, rf"^media_manglers_audio_progress_{pid}_{guid}\.json$")
        self.assertTrue(helper, "the stand-in speech model was never asked")
        for record in helper:
            self.assertEqual(os.path.normcase(record["tempdir"]), os.path.normcase(str(override)), record)

    def test_a_voice_detection_run_from_the_tests_leaves_nothing_in_the_system_temp_folder(self) -> None:
        area51_temp = REPO_ROOT / "AREA51" / "TEMP"
        if not area51_temp.is_dir():
            self.skipTest("the test suite uses the normal temp folder when AREA51 is absent")
        scratch = area51_temp / "pytest-scratch"
        system_temp = os.environ.get("MEDIA_MANGLERS_TESTS_SYSTEM_TEMP", "")
        self.assertTrue(system_temp, "conftest.py notes the system temp folder before it moves temp files")
        for name in ("TEMP", "TMP", "TMPDIR", "MEDIA_MANGLERS_SCRATCH_ROOT"):
            self.assertEqual(os.path.normcase(os.environ.get(name, "")), os.path.normcase(str(scratch)), name)
        self.assertEqual(os.path.normcase(tempfile.gettempdir()), os.path.normcase(str(scratch)))

        def inside(path: str, folder: Path) -> bool:
            return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(str(folder)) + os.sep)

        before = set(os.listdir(system_temp))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            temps = root / "temps.txt"
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording, arguments="-AudioStreamIndex 2", TEMPS=str(temps),
                                     after="[System.IO.Path]::GetTempPath()")
            helper = [json.loads(line) for line in temps.read_text(encoding="utf-8").splitlines()]
        new = sorted(set(os.listdir(system_temp)) - before)
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        payload = result["payloads"][0]
        used = [payload["work_dir"], payload["progress_state_file_path"], str(root), os.path.join(result["after"], "x")]
        for record in helper:
            used += [record["request"], record["result"], os.path.join(record["tempdir"], "x")]
        for path in used:
            self.assertTrue(inside(path, scratch), path)
        self.assertEqual([name for name in new if str(result["pid"]) in name or name.startswith("mm-")], [])

    def test_voice_detection_that_stops_making_progress_is_reported_as_that(self) -> None:
        # 145: the helper's watchdog stops voice detection when nothing new
        # arrives (here listening hangs). Choosing another track would not
        # help, so the operator reads what stopped and what to check.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            result = self._run_batch(root, recording, arguments="-VoiceDetectionStallTimeoutSeconds 4", HANG=120)
        self.assertIsNone(result["atPackage"])
        self.assertIn("Voice track detection stopped reporting progress", result["log"])
        self.assertIn("No usable narration transcript was produced", result["failure"])
        reason = next((line for line in result["failure"].splitlines() if "synthetic-session.mkv:" in line), "")
        self.assertIn("stopped making progress", reason, result["failure"])
        self.assertIn("make sure it is awake and connected", reason)
        self.assertNotIn("choose the track with your voice", reason)
        self.assertNotIn("voice detection could not run", reason)


class ProblemWordingTests(unittest.TestCase):
    def _reasons(self, entries: dict[str, dict[str, str]]) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "entries.json").write_text(json.dumps(entries), encoding="utf-8")
            return _run(
                """
                $entries = Get-Content -LiteralPath (Join-Path $folder 'entries.json') -Raw | ConvertFrom-Json
                $out = [ordered]@{}
                foreach ($property in $entries.PSObject.Properties) {
                    $out[$property.Name] = Get-CodexEvidenceProblemReason -Entry $property.Value
                }
                $out | ConvertTo-Json -Compress
                """,
                folder,
            )

    def test_what_the_operator_reads_about_each_recording_is_what_was_found(self) -> None:
        reasons = self._reasons(
            {
                "quiet microphone": {
                    "status": "no_narration",
                    "error_message": "Your usual microphone track, Track 2, has sound but no clear speech.",
                },
                "no words anywhere": {"status": "no_narration", "error_message": ""},
                "cannot tell": {
                    "status": "failed",
                    "error_message": "Multiple audio tracks: the app could not tell which track is your microphone "
                    "in 'synthetic-session.mkv'. Track 2 (394 clear words) and Track 1 (266) carry speech ...",
                },
                "detection broke": {
                    "status": "failed",
                    "error_message": "Multiple audio tracks were detected for 'synthetic-session.mkv' and automatic "
                    "voice detection failed (error). Choose the microphone track for this recording in the Workbench.",
                },
            }
        )
        self.assertEqual(
            reasons["quiet microphone"],
            "no narration found - Your usual microphone track, Track 2, has sound but no clear speech.",
        )
        self.assertEqual(reasons["no words anywhere"], "no narration found - no audio track has clear speech in this recording")
        self.assertIn("could not tell which track is your microphone", reasons["cannot tell"])
        self.assertIn("press Fix and continue", reasons["cannot tell"])
        # A detector that failed to run is not a recording whose track is unknown.
        self.assertIn("voice detection could not run", reasons["detection broke"])
        for reason in reasons.values():
            self.assertNotIn("silent", reason)

    def test_the_question_is_worded_for_every_reason_the_app_can_have_for_asking(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertNotIn("more than one track carries isolated speech", text)
        self.assertIn('throw ("Multiple audio tracks: the app could not tell which track is your microphone', text)
        self.assertNotIn("your microphone was silent in this recording, or it was not recorded", text)


if __name__ == "__main__":
    unittest.main()
