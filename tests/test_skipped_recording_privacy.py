"""Nothing from a recording the operator skipped reaches the package or its ZIP (196).

Find my bug reports promises that a skipped recording leaves nothing in the package. This runs
the real backend (every function of "Video Mangler.ps1": Invoke-CodexEvidencePackageBatch, run
control reading a real run-control.json, voice detection, FFmpeg, the Python detect and write
helpers, narration visuals) on three synthetic recordings, and then the real
build_portable_agent_zip on the finished package. Only Whisper (transcription and the detector's
probe) and the Workbench progress lines are stood in for.

Recording b is the one skipped, at every moment the operator can skip it. Its stand-in transcript
carries a word found nowhere else, so any of its text that reaches the package is found. It may be
named, with its status, only where the package says it was skipped.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile

from tests.test_voice_track import NARRATION_WORDS, _three_track_recording

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
SRC = REPO_ROOT / "src"
MARK = {"a": "ALPHAWORDX", "b": "BRAVOSECRETWORD", "c": "CHARLIEWORDX"}
NAME = "b-session"
TEXT_EXT = {".csv", ".json", ".jsonl", ".md", ".srt", ".txt", ".log", ".html", ".mmlist"}
# Where the package may say, by name, that b was skipped: the manifests, the quality report and
# the run log (which the ZIP leaves out).
MAY_NAME_IT = {"manifest.json", "WORKFLOW3_STAGE_MANIFEST.json", "EVIDENCE_QUALITY_REPORT.md", "codex_evidence_run.log"}

SHIM = textwrap.dedent(
    """
    import json, sys
    from unittest import mock
    sys.path.insert(0, SRC)
    from media_manglers import cli
    from media_manglers.core import voice_track
    args = sys.argv[1:]
    command = args[args.index('media_manglers') + 1]
    # The operator presses Skip on recording b in Queue / Progress while the package is built.
    if command == SKIP_ON:
        with open(CONTROL, encoding='utf-8') as handle:
            control = json.load(handle)
        control['skip'] = list(control.get('skip') or []) + [B_PATH]
        with open(CONTROL, 'w', encoding='utf-8') as handle:
            json.dump(control, handle)

    def transcriber(path):
        text = WORDS.get(path.stem.split('-')[-1], '')
        return [{'text': text, 'no_speech_prob': 0.05, 'avg_logprob': -0.3}] if text else []

    with mock.patch.object(voice_track, 'whisper_transcriber', return_value=transcriber):
        raise SystemExit(cli.main(args[args.index('media_manglers') + 1 :]))
    """
)


def _launcher(root: Path, name: str, code: str, **values: object) -> Path:
    script = root / f"{name}.py"
    script.write_text("".join(f"{key} = {value!r}\n" for key, value in values.items()) + code, encoding="utf-8")
    launcher = root / f"{name}.cmd"
    launcher.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
    return launcher


def _run_batch(root: Path, recordings: list[Path], out: Path, *, skip_at: str = "", skip_first: bool = False,
               skip_while_packaging: str = "", arguments: str = "", own_problems: bool = False,
               skip_everything: bool = False) -> str:
    """Run the real Invoke-CodexEvidencePackageBatch to the end; the error it stopped with, or "".

    skip_at is when the stand-in Whisper skips recording b: "during" (while b is transcribed; the
    real run-control check stops it), "right_after" (b's transcript is written, its lossless copy
    not yet made) or "postloop" (while c is transcribed, after b finished).

    With own_problems each recording talks about problems of its own, so b's tickets are not merged
    into a's and its screenshots, audio excerpt and clips are rendered. The batch's result is kept in
    the run folder's result.json. With skip_everything every recording is skipped before it starts.
    """

    root.mkdir(parents=True, exist_ok=True)
    b_path = str(recordings[1])
    control = root / "run-control.json"
    first_skips = [str(p) for p in recordings] if skip_everything else [b_path] if skip_first else []
    control.write_text(json.dumps({"pause": False, "skip": first_skips}), encoding="utf-8")
    python = _launcher(root, "python", SHIM, SRC=str(SRC), WORDS={"1": NARRATION_WORDS}, CONTROL=str(control),
                       B_PATH=b_path, SKIP_ON=skip_while_packaging)
    listing = root / "recordings.mmlist"
    listing.write_text("# Recordings for one bug-report package\n" + "\n".join(str(p) for p in recordings) + "\n",
                       encoding="utf-8")
    script = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }}, $false)) {{
            Invoke-Expression $node.Extent.Text
        }}
        $script:MMSkipMessagePrefix = "MM_SKIP_REQUESTED"
        $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{SRC}'; EntryPoint = '' }}
        $script:MMRunControlPath = '{control}'
        function Write-MMProgressV1 {{ }}
        function Add-TestSkip {{
            $c = Get-Content -LiteralPath '{control}' -Raw | ConvertFrom-Json
            $list = @(@($c.skip) | Where-Object {{ $_ }}) + @('{b_path}')
            [System.IO.File]::WriteAllText('{control}', (@{{ pause = $false; skip = $list }} | ConvertTo-Json -Compress))
            # Run control reads the file again at most once a second.
            Start-Sleep -Milliseconds 1200
        }}
        function Invoke-PythonWhisperTranscript {{
            param([string]$PythonCommand, [string]$AudioPath, [string]$TranscriptFolder, [string]$ModelName, [string]$LanguageCode,
                [string]$FFmpegExe, [bool]$PreferGpu, [string]$Task, [string]$JsonName, [string]$SrtName, [string]$TextName,
                [string]$InitialPrompt, [string]$NarrationSpeechMode, [double]$SourceDurationSeconds, [int]$HeartbeatSeconds,
                [int]$WhisperTimeoutSeconds, [switch]$InteractiveMode, [switch]$AllowInteractiveLongRunPrompt)
            $letter = $JsonName.Substring(0, 1)
            if ('{skip_at}' -eq 'during' -and $letter -eq 'b') {{
                Add-TestSkip
                # What the real Whisper wait loop does on every tick.
                $null = Invoke-MMRunControlCheck -StepName 'Whisper'
            }}
            $marks = @{{ a = '{MARK["a"]}'; b = '{MARK["b"]}'; c = '{MARK["c"]}' }}
            $mark = $marks[$letter]
            $first = 'export problem'; $second = 'dashboard menu'
            if ('{own_problems}' -eq 'True') {{
                $first = @{{ a = 'brake pedal calibration fault'; b = 'export problem'; c = 'lap timer overlay glitch' }}[$letter]
                $second = @{{ a = 'steering wheel binding'; b = 'dashboard menu'; c = 'replay camera' }}[$letter]
            }}
            $segments = @(
                @{{ id = 1; start = 2.0; end = 6.0; text = ("Please make this a ticket for the " + $first + ", " + $mark + " one.") }},
                @{{ id = 2; start = 10.0; end = 14.0; text = ("The " + $second + " issue is back, " + $mark + " two.") }}
            )
            [System.IO.File]::WriteAllText((Join-Path $TranscriptFolder $JsonName), (@{{ language = 'en'; segments = $segments }} | ConvertTo-Json -Depth 5))
            [System.IO.File]::WriteAllText((Join-Path $TranscriptFolder $SrtName), ("1`r`n00:00:02,000 --> 00:00:06,000`r`nPlease make this a ticket for the " + $first + ", " + $mark + " one.`r`n"))
            [System.IO.File]::WriteAllText((Join-Path $TranscriptFolder $TextName), ("Please make this a ticket for the " + $first + ", " + $mark + " one. The " + $second + " issue is back, " + $mark + " two."))
            if ('{skip_at}' -eq 'right_after' -and $letter -eq 'b') {{ Add-TestSkip }}
            if ('{skip_at}' -eq 'postloop' -and $letter -eq 'c') {{ Add-TestSkip }}
        }}
        $failure = ''
        $result = $null
        try {{
            $result = Invoke-CodexEvidencePackageBatch -InputPath '{listing}' -OutputFolder '{out}' -PythonCommand '{python}' -FFmpegExe '{shutil.which("ffmpeg")}' -FFprobeExe '{shutil.which("ffprobe")}' -ModelName 'base.en' -LanguageCode 'en' -CanUseWhisperGpu $false -AudioStreamIndex 2 -PanelCropMode Off {arguments}
        }}
        catch {{
            $failure = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage
        }}
        if ($null -ne $result) {{
            [System.IO.File]::WriteAllText('{root / "result.json"}', ($result | Select-Object -Property * -ExcludeProperty ProblemRecordings | ConvertTo-Json -Compress))
        }}
        @{{ failure = $failure }} | ConvertTo-Json -Compress
        """
    ).strip()
    harness = root / "harness.ps1"
    harness.write_text(script, encoding="utf-8")
    process = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True, text=True, timeout=900,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr[-4000:])
    return json.loads(process.stdout.strip().splitlines()[-1])["failure"]


def _findings(name: str, data: bytes, where: str = "", skipped: tuple[str, ...] = ("b",)) -> list[str]:
    """Why a file of the package is from a skipped recording (b), or names it where it may not."""

    found = []
    for letter in skipped:
        recording = f"{letter}-session"
        # The file's own name or any folder it is in.
        if recording in name:
            found.append(f"named after {letter}")
        if Path(name).suffix.lower() in TEXT_EXT:
            text = data.decode("utf-8", errors="replace")
            if MARK[letter] in text:
                found.append(f"holds {letter}'s transcript text")
            elif recording in text and name not in MAY_NAME_IT:
                found.append(f"names {letter}")
    return [f"{where}{name}: {', '.join(found)}"] if found else []


def _package_findings(package: Path, work: Path, skipped: tuple[str, ...] = ("b",)) -> list[str]:
    found = []
    for path in sorted(package.rglob("*")):
        if path.is_file():
            found += _findings(path.relative_to(package).as_posix(), path.read_bytes(), skipped=skipped)
        if path.is_file() and path.suffix.lower() == ".zip":
            # The portable ZIP in the package, as the Workbench offers it: the one this run made, or
            # one an earlier run of this package left.
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    found += _findings(info.filename, archive.read(info), f"{path.name}:", skipped)
    # The portable ZIP, built by the real builder from a copy of the package.
    copy = work / "zip-copy" / package.name
    shutil.copytree(package, copy)
    sys.path.insert(0, str(SRC))
    from media_manglers.core import session_review

    session_review.build_portable_agent_zip(copy, max_size_mb=100)
    with zipfile.ZipFile(copy / session_review.PORTABLE_ZIP_FILENAME) as archive:
        for info in archive.infolist():
            found += _findings(info.filename, archive.read(info), "ZIP:", skipped)
    return found


def _export_prompts_for_b(package: Path) -> list[Path]:
    """The Workbench's Export prompts, pressed on each of b's tickets: drafts written into the package."""

    sys.path.insert(0, str(SRC))
    from media_manglers_workbench.evidence import load_evidence_package
    from media_manglers_workbench.prompts import export_prompt_drafts

    loaded = load_evidence_package(package)
    written = []
    for item in loaded.all_items:
        if item.source_filename.startswith(NAME):
            paths = export_prompt_drafts(loaded, item)
            written += [paths.codex_path, paths.claude_path]
    return written


def _stale_tickets(package: Path) -> list[str]:
    """Ticket folders and screenshots that are not the current tickets' own (196).

    After a recording is skipped the tickets are numbered again, so a ticket folder of the earlier
    run may now be another recording's ticket, or no ticket at all. Every ticket folder must be a
    current ticket, and every screenshot a ticket shows must be one rendered from its own recording.
    """

    tickets = json.loads((package / "CANDIDATE_TICKETS.json").read_text(encoding="utf-8-sig"))
    current = tickets["candidates"] + tickets["unrendered_candidates"]
    found = [f"evidence_items/{folder.name}: not a ticket of this package"
             for folder in sorted((package / "evidence_items").glob("*"))
             if folder.is_dir() and folder.name not in {c["evidence_id"] for c in current}]
    for ticket in tickets["candidates"]:
        source_id = ticket["source_id"]
        own = (f"artifacts/sources/{source_id}/",
               f"artifacts/sources/s-{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:12]}/")
        for frame in ticket.get("frames") or []:
            for image in [frame] + list(frame.get("panels") or []):
                relative = str(image.get("relative_path") or "")
                if not relative.startswith(own):
                    found.append(f"{ticket['evidence_id']}: shows {relative}, not from {source_id}")
                elif not (package / relative).is_file():
                    found.append(f"{ticket['evidence_id']}: {relative} is missing")
    return found


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class SkippedRecordingLeavesNothingInThePackageTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        folder = Path(cls._temp.name) / "recordings"
        folder.mkdir()
        first = _three_track_recording(folder / "a-session.mkv")
        shutil.copy(first, folder / f"{NAME}.mkv")
        shutil.copy(first, folder / "c-session.mkv")
        cls.recordings = [first, folder / f"{NAME}.mkv", folder / "c-session.mkv"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def _check(self, *, continue_run: bool = False, first_run_arguments: str = "-StopAfter Transcription",
               log_says: str = "", completed: int | None = None, export_prompts: bool = False,
               **skip: object) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "out"
            if continue_run:
                # Continue (115): an earlier run in the same folder transcribed every recording, or
                # built the whole package.
                failure = _run_batch(root / "first-run", self.recordings, out, arguments=first_run_arguments,
                                     own_problems=bool(skip.get("own_problems")))
                self.assertEqual(failure, "")
                if "-StopAfter" not in first_run_arguments:
                    # The earlier run rendered b's own media, which the Continue must not keep.
                    earlier = out / "codex-evidence-package" / "artifacts"
                    self.assertTrue(any((earlier / "sources").glob(f"{NAME}-*/audio/*.mp3")))
                    self.assertTrue(any((earlier / "narration").glob(f"{NAME}-*/clips/*.mp4")))
                if "PortableZip" in first_run_arguments:
                    # And the portable ZIP, holding all of b, that the Workbench offers.
                    self.assertTrue((out / "codex-evidence-package" / "ticket-agent-handoff.zip").is_file())
                if export_prompts:
                    # The operator pressed Export prompts on b's tickets in the Workbench.
                    drafts = _export_prompts_for_b(out / "codex-evidence-package")
                    self.assertTrue(drafts)
                    self.assertTrue(all(MARK["b"] in path.read_text(encoding="utf-8") for path in drafts))
            failure = _run_batch(root / "run", self.recordings, out, **skip)
            self.assertEqual(failure, "")
            package = out / "codex-evidence-package"
            if "PortableZip" in str(skip.get("arguments") or ""):
                # This run made its own portable ZIP, which is checked below as the Workbench offers it.
                self.assertTrue((package / "ticket-agent-handoff.zip").is_file())
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8-sig"))
            statuses = {source["source_filename"]: source["status"] for source in manifest["sources"]}
            # Skipped, said so, and the package was still built from the others.
            self.assertEqual(statuses[f"{NAME}.mkv"], "operator_skipped", statuses)
            self.assertIn("skipped by the operator; nothing from this recording is in the package",
                          (package / "EVIDENCE_QUALITY_REPORT.md").read_text(encoding="utf-8-sig"))
            self.assertIn(MARK["a"], (package / "CANDIDATE_TICKETS.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(_package_findings(package, root), [])
            self.assertEqual(_stale_tickets(package), [])
            # Its audio is gone from the package, and the manifest says so.
            skipped_source = next(s for s in manifest["sources"] if s["source_filename"] == f"{NAME}.mkv")
            self.assertEqual(
                (skipped_source["audio_status"], skipped_source["audio_path"], skipped_source["transcription_input_path"]),
                ("not_in_package", "", ""), skipped_source)
            # 201: and the manifest does not point at its transcripts, which went too.
            self.assertEqual(
                {key: value for key, value in skipped_source.items()
                 if "transcript" in key and key.endswith("_path") and value}, {}, skipped_source)
            if log_says:
                self.assertIn(log_says, (package / "codex_evidence_run.log").read_text(encoding="utf-8-sig"))
            if completed is not None:
                # The run's own count leaves out what was skipped while the package was built.
                result = json.loads((root / "run" / "result.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(result["CompletedCount"], completed, result)

    def test_skipped_before_it_is_transcribed(self) -> None:
        self._check(skip_first=True)

    def test_skipped_while_it_is_transcribed(self) -> None:
        self._check(skip_at="during")

    def test_skipped_just_after_its_transcript_is_written(self) -> None:
        self._check(skip_at="right_after")

    def test_skipped_while_the_next_recording_is_transcribed(self) -> None:
        self._check(skip_at="postloop")

    def test_skipped_while_the_package_is_built(self) -> None:
        # While bug detection runs: before anything is rendered or written.
        self._check(skip_while_packaging="evidence-package-detect", log_says="while the package was built")

    def test_skipped_after_the_package_was_written_but_before_the_run_ended(self) -> None:
        # While the package is written and its narration visuals are made: it is built again without it.
        self._check(skip_while_packaging="evidence-package-write", log_says="while the package was built")

    def test_skipped_on_continue_after_an_earlier_run_transcribed_it(self) -> None:
        self._check(skip_first=True, continue_run=True)

    # In the tests below each recording talks about problems of its own, so b's own tickets are
    # rendered: its screenshots, audio excerpt, narration clips and review video exist.

    def test_skipped_while_the_package_is_written_after_its_media_was_rendered(self) -> None:
        self._check(skip_while_packaging="evidence-package-write", own_problems=True,
                    log_says="while the package was built", completed=2)

    def test_skipped_on_continue_after_an_earlier_run_built_the_whole_package(self) -> None:
        self._check(skip_first=True, continue_run=True, first_run_arguments="", own_problems=True)

    def test_skipped_while_the_package_is_written_when_stopping_after_consolidation(self) -> None:
        # The Workbench setting 'Stop after evidence stage' = Consolidation.
        self._check(skip_while_packaging="evidence-package-write", own_problems=True,
                    arguments="-StopAfter Consolidation", log_says="while the package was built")

    def test_skipped_on_continue_after_an_earlier_run_built_the_whole_package_and_its_zip(self) -> None:
        # The earlier run also made the portable ZIP; this one does not make one.
        self._check(skip_first=True, continue_run=True, first_run_arguments="-HandoffMode PortableZip",
                    own_problems=True)

    def test_skipped_on_continue_that_makes_the_zip_again(self) -> None:
        # Both runs make the portable ZIP. The narration visuals of the earlier run (which name b's
        # words) are still in the folder when this run's ZIP is made.
        self._check(skip_first=True, continue_run=True, first_run_arguments="-HandoffMode PortableZip",
                    own_problems=True, arguments="-HandoffMode PortableZip")

    def test_skipped_while_the_package_is_written_when_making_the_zip(self) -> None:
        # The package and its ZIP are made again without b, while the narration visuals made with
        # b on the first try are still in the folder.
        self._check(skip_while_packaging="evidence-package-write", own_problems=True,
                    arguments="-HandoffMode PortableZip", log_says="while the package was built", completed=2)

    def test_skipped_on_continue_when_stopping_after_consolidation(self) -> None:
        # 'Stop after evidence stage' = Consolidation makes no narration visuals, so the earlier
        # run's are not written again; this run's ZIP must not take them either.
        self._check(skip_first=True, continue_run=True, first_run_arguments="-HandoffMode PortableZip",
                    own_problems=True, arguments="-StopAfter Consolidation -HandoffMode PortableZip")

    def test_skipped_on_continue_after_its_prompts_were_exported(self) -> None:
        # Export prompts in the Workbench wrote drafts of b's tickets into the package; after the
        # skip those ticket numbers belong to other recordings, or to none.
        self._check(skip_first=True, continue_run=True, first_run_arguments="", own_problems=True,
                    export_prompts=True)

    def _check_stopped_after_transcription(self, *, skip_everything: bool) -> None:
        # 'Stop after evidence stage' = Transcription on Continue: no package is built this time,
        # so the one an earlier run built with b in it, and its ZIP, must not be left looking current.
        skipped = ("a", "b", "c") if skip_everything else ("b",)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "out"
            package = out / "codex-evidence-package"
            failure = _run_batch(root / "first-run", self.recordings, out, arguments="-HandoffMode PortableZip",
                                 own_problems=True)
            self.assertEqual(failure, "")
            self.assertTrue((package / "ticket-agent-handoff.zip").is_file())
            failure = _run_batch(root / "run", self.recordings, out, arguments="-StopAfter Transcription",
                                 own_problems=True, skip_first=not skip_everything, skip_everything=skip_everything)
            self.assertEqual(failure, "")
            stage = json.loads((package / "WORKFLOW3_STAGE_MANIFEST.json").read_text(encoding="utf-8-sig"))
            statuses = {s["source_id"].split("-")[0]: s["status"] for s in stage["sources"]}
            self.assertEqual({letter for letter, status in statuses.items() if status == "operator_skipped"},
                             set(skipped), statuses)
            self.assertEqual(_package_findings(package, root, skipped=skipped), [])
            for name in ("ticket-agent-handoff.zip", "manifest.json", "CANDIDATE_TICKETS.json", "evidence_items"):
                self.assertFalse((package / name).exists(), name)
            self.assertIn("so no package was built", (package / "codex_evidence_run.log").read_text(encoding="utf-8-sig"))
            # What a Continue needs of the recordings not skipped is kept: their transcripts and the
            # raw copy of what Whisper heard.
            for letter in {"a", "b", "c"} - set(skipped):
                for folder in ("transcript/sources", "transcript/raw/sources"):
                    self.assertTrue(any((package / folder).glob(f"{letter}-session-*.transcript.json")), (letter, folder))

    def test_skipped_on_continue_when_stopping_after_transcription(self) -> None:
        self._check_stopped_after_transcription(skip_everything=False)

    def test_every_recording_skipped_on_continue_when_stopping_after_transcription(self) -> None:
        self._check_stopped_after_transcription(skip_everything=True)

    def test_every_recording_skipped_on_continue_after_an_earlier_run_built_the_whole_package(self) -> None:
        # The earlier run built the whole package and its portable ZIP; on Continue the operator
        # skips every recording, so no package is built and nothing of the earlier one may be left.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "out"
            package = out / "codex-evidence-package"
            failure = _run_batch(root / "first-run", self.recordings, out, arguments="-HandoffMode PortableZip",
                                 own_problems=True)
            self.assertEqual(failure, "")
            self.assertTrue((package / "ticket-agent-handoff.zip").is_file())
            self.assertTrue(any((package / "evidence_items").iterdir()))
            failure = _run_batch(root / "run", self.recordings, out, skip_everything=True)
            # The run says what it always said when nothing is usable.
            self.assertIn("No usable narration transcript was produced, so no package was built.", failure)
            stage = json.loads((package / "WORKFLOW3_STAGE_MANIFEST.json").read_text(encoding="utf-8-sig"))
            self.assertEqual({s["status"] for s in stage["sources"]}, {"operator_skipped"}, stage)
            # No package of the earlier run is left looking current: not its ZIP, manifest or tickets.
            self.assertEqual(_package_findings(package, root, skipped=("a", "b", "c")), [])
            self.assertFalse((package / "ticket-agent-handoff.zip").exists())
            self.assertFalse((package / "manifest.json").exists())
            self.assertIn("Every recording was skipped by you",
                          (package / "codex_evidence_run.log").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
