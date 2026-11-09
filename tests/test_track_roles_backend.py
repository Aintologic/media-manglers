"""196 track roles, the backend's side: the per-track setting reaches the detector, a saved
voice-track result is reused only with the same setting, and the log line the Workbench reads
says what decided the track.

The PowerShell functions are parsed out of "Video Mangler.ps1" and run on their own, as in
test_voice_verdict_backend.py. Everything is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests.script_functions import function_text

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FUNCTIONS = (
    "ConvertTo-MMTrackRoles",
    "Get-MMTrackRolesKey",
    "Read-MMSavedVoiceDetection",
    "Save-MMVoiceDetection",
    "Invoke-VoiceTrackDetection",
    "Ensure-Directory",
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
        $folder = '{folder}'
        {body}
        """
    ).strip()
    harness = folder / "harness.ps1"
    harness.write_text(source, encoding="utf-8")
    process = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                             capture_output=True, text=True, timeout=120)
    if process.returncode != 0:
        raise AssertionError(process.stderr)
    return json.loads(process.stdout.strip().splitlines()[-1])


class TrackRoleBackendTests(unittest.TestCase):
    def test_the_setting_is_read_and_kept_in_one_fixed_form(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = _run(
                """
                $roles = ConvertTo-MMTrackRoles -Text ' 6=never; 2=Narration,3=never,1=auto,x=never,4=bogus,0=never,5 = NEVER'
                [ordered]@{
                    key = Get-MMTrackRolesKey -Roles $roles
                    blank = Get-MMTrackRolesKey -Roles (ConvertTo-MMTrackRoles -Text '')
                } | ConvertTo-Json -Compress
                """,
                Path(temp),
            )
        self.assertEqual(result, {"key": "2=narration,3=never,5=never,6=never", "blank": ""})

    def test_a_saved_result_is_reused_only_with_the_same_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            recording = folder / "synthetic-session.mkv"
            recording.write_bytes(b"not really video")
            sys.path.insert(0, str(REPO_ROOT / "src"))
            from media_manglers.core import voice_track

            version = voice_track.VOICE_RULE_VERSION
            result = _run(
                f"""
                $video = '{recording}'
                $detection = [pscustomobject]@{{ status = 'selected'; selected_ordinal = 1; rule_version = {version}; explanation = 'From your setting: Track 2.' }}
                $path = Join-Path $folder 'a.voice.json'
                Save-MMVoiceDetection -Path $path -VideoPath $video -Detection $detection -PreferredOrdinals @() -TrackRolesKey '2=narration'
                function Heard($key) {{
                    $found = Read-MMSavedVoiceDetection -Path $path -VideoPath $video -PreferredOrdinals @() -TrackRolesKey $key
                    if ($null -eq $found) {{ 'listen again' }} else {{ 'reused' }}
                }}
                [ordered]@{{
                    same = Heard '2=narration'
                    changed = Heard '2=narration,5=never'
                    allAuto = Heard ''
                }} | ConvertTo-Json -Compress
                """,
                folder,
            )
        self.assertEqual(result, {"same": "reused", "changed": "listen again", "allAuto": "listen again"})

    def test_the_detector_is_given_the_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = _run(
                """
                function Remove-MMOrphanedScratch { }
                function Get-MMScratchPath { param($Prefix, $Extension) return (Join-Path $folder ($Prefix + $Extension)) }
                function Remove-MMScratchPath { param($Path) }
                $script:payload = $null
                function Invoke-MediaManglersPythonCli { param($PythonCommand, $Command, $StepName, $HeartbeatSeconds, $TimeoutSeconds, $StallTimeoutSeconds, $ProgressStateFilePath, $Payload)
                    $script:payload = $Payload
                    return [pscustomobject]@{ Result = [pscustomobject]@{ ok = $true; data = [pscustomobject]@{ status = 'selected'; tracks = @() } } }
                }
                $null = Invoke-VoiceTrackDetection -PythonCommand 'py' -VideoPath 'x.mkv' -TrackRoles (ConvertTo-MMTrackRoles -Text '2=narration,3=never')
                [ordered]@{ roles = $script:payload.track_roles } | ConvertTo-Json -Compress -Depth 4
                """,
                Path(temp),
            )
        self.assertEqual(result, {"roles": {"2": "narration", "3": "never"}})

    def test_the_evidence_run_threads_the_setting_and_names_what_decided(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn('[string]$EvidenceTrackRoles = ""', text)
        self.assertEqual(text.count("-TrackRoles $EvidenceTrackRoles `"), 2, "both evidence entry points pass the setting")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        for piece in ("-PreferredOrdinals $preferredOrdinals -TrackRolesKey $trackRolesKey",
                      "-TrackRoles $trackRoleSetting `",
                      'Write-Host ("  Voice found on Track {0} ({1})." -f ($detectedOrdinal + 1), $decidedByText)'):
            self.assertIn(piece, body)
        self.assertEqual(body.count("-TrackRolesKey $trackRolesKey"), 3, "read and both saves use the same key (264: what the library knew is saved too)")

    def test_the_setting_claims_only_the_workflows_that_read_it(self) -> None:
        # Privacy review 4: the setting claims exactly the workflows that read it. 214: Review Media
        # Inbox now chooses its track with voice detection, so it reads the setting too.
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from media_manglers_workbench.metadata import (
            METADATA_BY_KEY,
            WORKFLOW_CODEX_EVIDENCE,
            WORKFLOW_REVIEW_NEW_VIDEOS,
        )

        workflows = METADATA_BY_KEY["evidence_track_roles"].workflows
        self.assertIn(WORKFLOW_CODEX_EVIDENCE, workflows)
        self.assertIn(WORKFLOW_REVIEW_NEW_VIDEOS, workflows)
        script = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8")
        payload = script[script.index("$reviewProcessPayload = @{"):]
        self.assertIn("track_roles = (ConvertTo-MMTrackRoles -Text ([string]$EvidenceTrackRoles))", payload[: payload.index("\n        }")])


MARKERS = {"full_mix": "quokka", "teammate": "zebrafish", "spotter": "pangolin"}


def _bursty(freq: int, start: float, length: float, period: float = 4.0) -> str:
    return (f"sine=frequency={freq}:sample_rate=48000:duration=20,"
            f"volume='if(between(mod(t,{period}),{start},{start + length}),1,0)':eval=frame")


BUSY_NOISE = "anoisesrc=d=20:r=48000:a=0.3,volume='if(lt(mod(t,1),0.8),1,0.01)':eval=frame"


def _recording(path: Path, tracks: list[tuple[str, str]]) -> Path:
    """A 20 s MKV: a tiny video track and one FLAC audio track per (lavfi source, track name)."""

    import shutil

    command = [shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
               "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5:duration=20"]
    for source, _title in tracks:
        command += ["-f", "lavfi", "-i", source]
    command += ["-map", "0:v"]
    for index in range(len(tracks)):
        command += ["-map", f"{index + 1}:a"]
    for index, (_source, title) in enumerate(tracks):
        if title:
            command += [f"-metadata:s:a:{index}", f"title={title}"]
    command += ["-t", "20", "-c:v", "ffv1", "-c:a", "flac", "-ac", "2", "-ar", "48000", str(path)]
    subprocess.run(command, check=True)
    return path


class TrackRolePrivacyRunTests(unittest.TestCase):
    """Privacy review 4 (196), through the real Invoke-CodexEvidencePackageBatch on synthetic
    recordings: a track that is never narration is never transcribed, and nothing heard on a
    track that is not the narration is saved in the package."""

    def setUp(self) -> None:
        import tests.test_voice_verdict_backend as backend

        self.backend = backend.EvidenceRunVoiceAudioTests
        self.words: dict[str, str] = {}

    # The real backend harness of tests/test_voice_verdict_backend.py, with the words each track
    # "says" chosen per test.
    @property
    def SHIM(self) -> str:  # noqa: N802 - the harness reads it by this name
        return self.backend.SHIM

    @property
    def FFMPEG(self) -> str:  # noqa: N802
        return self.backend.FFMPEG

    def _launcher(self, root: Path, name: str, code: str, **values: object) -> Path:
        if name == "python" and self.words:
            values["WORDS"] = dict(self.words)
        return self.backend._launcher(self, root, name, code, **values)

    def _run_batch(self, root: Path, source: Path, **options: object) -> dict:
        return self.backend._run_batch(self, root, source, **options)

    def _teammate_and_operator(self) -> None:
        from tests.test_voice_track import NARRATION_WORDS

        self.words = {
            "0": NARRATION_WORDS,
            "1": " ".join(["another", "driver", "talks", "about", "tyre", "pressures", "and", "fuel"] * 11),
            "2": f"{MARKERS['spotter']} car left car left clear",
        }

    def test_nothing_heard_on_any_track_is_saved_in_the_package(self) -> None:
        # Found by privacy review 4 (pre-existing on main): the saved voice-track result kept up to
        # 240 characters of what was heard on every track, the full mix and a teammate's voice chat
        # included, inside the package and so inside the portable ZIP.
        from tests.test_voice_track import NARRATION_WORDS

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _recording(root / "synthetic-session.mkv", [
                (BUSY_NOISE, "Full mix"), (_bursty(300, 0.0, 1.0), "Mic/Aux"), (_bursty(500, 2.0, 0.5), "Discord"),
            ])
            self.words = {
                "0": " ".join([MARKERS["full_mix"], "the", "crowd", "noise"] * 5),
                "1": NARRATION_WORDS,
                "2": f"hey {MARKERS['teammate']} meet me after the race tonight",
            }
            result = self._run_batch(root, recording)
            saved = (root / "out" / "codex-evidence-package" / "transcript" / "sources")
            texts = [path.read_text(encoding="utf-8-sig") for path in saved.glob("*.voice.json")]
        self.assertIsNotNone(result["atPackage"], result["failure"] or result["log"][-3000:])
        detection = result["voice"][0]["detection"]
        self.assertEqual((detection["status"], detection["selected_ordinal"]), ("selected", 1))
        self.assertEqual(len(texts), 1)
        for marker in MARKERS.values():
            self.assertNotIn(marker, texts[0])
        self.assertNotIn("delta bar", texts[0])
        self.assertTrue(all("sample_text" not in track for track in detection["tracks"]), detection["tracks"])

    def _remembered_track_3(self, root: Path, recording: Path) -> str:
        selections = json.dumps({str(recording): {"audioOrdinal": 2, "humanTrackNumber": 3, "ffmpegMap": "0:a:2",
                                                  "confirmationSource": "exact saved-layout match"}})
        return f"-AudioStreamSelectionsJson '{selections}'"

    def test_a_remembered_track_set_to_never_narration_is_not_transcribed(self) -> None:
        # Found by privacy review 4: two different voices on Tracks 1 and 2 left detection unsure,
        # and the backend fell back to the remembered Track 3, which the setting says is never
        # narration. It must ask instead.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _recording(root / "synthetic-session.mkv", [
                (_bursty(300, 0.0, 1.0), ""), (_bursty(500, 2.0, 1.0), ""), (_bursty(700, 1.2, 0.6), ""),
            ])
            self._teammate_and_operator()
            result = self._run_batch(root, recording,
                                     arguments="-TrackRoles '3=never' " + self._remembered_track_3(root, recording))
        detection = result["voice"][0]["detection"]
        self.assertEqual(detection["status"], "uncertain")
        self.assertNotIn("using the remembered narration Track 3", result["log"])
        self.assertEqual(result["heard"], [])
        self.assertIn("Multiple audio tracks", result["log"])

    def test_a_remembered_track_named_spotter_is_not_transcribed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _recording(root / "synthetic-session.mkv", [
                (_bursty(300, 0.0, 1.0), "Mic"), (_bursty(500, 2.0, 1.0), "Aux"),
                (_bursty(700, 1.2, 0.6), "Spotter"),
            ])
            self._teammate_and_operator()
            result = self._run_batch(root, recording, arguments=self._remembered_track_3(root, recording))
        self.assertEqual(result["voice"][0]["detection"]["status"], "uncertain")
        self.assertNotIn("using the remembered narration Track 3", result["log"])
        self.assertEqual(result["heard"], [])

    def test_the_only_track_that_is_never_narration_is_not_transcribed(self) -> None:
        # Found by privacy review 4: a one-track recording was transcribed without looking at its
        # track name or the setting.
        from tests.test_voice_track import NARRATION_WORDS

        for title, arguments in (("Game audio", ""), ("", "-TrackRoles '1=never'")):
            with self.subTest(title=title, arguments=arguments), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                recording = _recording(root / "synthetic-session.mkv", [(_bursty(300, 0.0, 1.0), title)])
                self.words = {"0": NARRATION_WORDS}
                result = self._run_batch(root, recording, arguments=arguments)
                self.assertEqual(result["heard"], [], result["log"][-2000:])
                # Its only recording has no narration, so no package is built, and the run says why.
                self.assertIsNone(result["atPackage"])
                self.assertIn("synthetic-session.mkv: no narration found", result["failure"])
                self.assertIn("the only audio track is never narration", result["failure"])

    def test_a_one_track_recording_without_a_role_is_transcribed_as_before(self) -> None:
        from tests.test_voice_track import NARRATION_WORDS

        for title in ("", "Track1"):
            with self.subTest(title=title), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                recording = _recording(root / "synthetic-session.mkv", [(_bursty(300, 0.0, 1.0), title)])
                self.words = {"0": NARRATION_WORDS}
                result = self._run_batch(root, recording, arguments="-TrackRoles '2=narration'")
                # 214: the narration WAV goes through the helper too; only a detection request counts.
                detection = [item for item in result["payloads"] if "output_path" not in item]
                self.assertEqual(detection, [], "no detection for a plain one-track recording")
                self.assertEqual(len(result["heard"]), 1)
                self.assertEqual(result["atPackage"]["statuses"], ["synthetic-session.mkv=completed"])


if __name__ == "__main__":
    unittest.main()
