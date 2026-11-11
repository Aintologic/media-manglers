"""Installer plan, Stage 3: no feature downloads a Whisper model without approval, and valid cached models are reused.

The one check is in ``whisper_local.load_whisper_model``. Each feature's path is run here with a model that is
valid, damaged and missing in the test run's own model cache (``conftest.py`` points Whisper's cache at a scratch
folder). The stand-in Whisper behaves as the real one does when it is called: it would download a missing model
itself. So "never called" is checked, and a damaged file must stay byte for byte as it was.
"""

from __future__ import annotations

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
import wave
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import raw_bin_library, safe_write, track_levels, user_folders, voice_track, whisper_models  # noqa: E402
from media_manglers.core.whisper_models import DAMAGED, MISSING, UNKNOWN, VALID, ModelNotApproved  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from media_manglers_workbench import dependencies  # noqa: E402
from media_manglers_workbench.resources import RuntimeResources  # noqa: E402
from tests.whisper_test_models import install_models, model_bytes  # noqa: E402


class RealishWhisper:
    """Behaves as Whisper does when called: a missing model is downloaded by Whisper itself, into the cache."""

    def __init__(self, table: dict[str, str]) -> None:
        self._MODELS = table
        self.loads: list[tuple[str, object, object]] = []
        self.downloads: list[str] = []

    def load_model(self, name: str, device: object = None, download_root: object = None, **_options: object):
        self.loads.append((name, device, download_root))
        target = Path(str(download_root or whisper_models.cache_dir())) / f"{name}.pt"
        if not target.is_file():
            self.downloads.append(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(model_bytes(name))
        model = mock.Mock()
        model.transcribe.return_value = {"language": "en", "text": " hello there",
                                         "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": " hello there"}]}
        return model


class _CpuTorch:
    class cuda:  # noqa: N801 - torch's own name
        @staticmethod
        def is_available() -> bool:
            return False

    @staticmethod
    def manual_seed(_seed: int) -> None:
        return None


def _wav(path: Path, seconds: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


class ModelCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def _whisper(self, *, damaged: tuple[str, ...] = (), missing: tuple[str, ...] = ()) -> RealishWhisper:
        return RealishWhisper(install_models(damaged=damaged, missing=missing))

    def _patched(self, whisper: RealishWhisper):
        return mock.patch.dict(sys.modules, {"whisper": whisper, "torch": _CpuTorch()})


class TheOneCheckTests(ModelCase):
    def test_the_cache_is_where_whisper_keeps_it(self) -> None:
        self.assertEqual(whisper_models.cache_dir(), self.root / "cache" / "whisper")

    def test_states(self) -> None:
        table = install_models(damaged=("small",), missing=("medium",))
        self.assertEqual(whisper_models.model_state("base.en", table=table).state, VALID)
        self.assertEqual(whisper_models.model_state("small", table=table).state, DAMAGED)
        self.assertEqual(whisper_models.model_state("medium", table=table).state, MISSING)
        self.assertEqual(whisper_models.model_state("enormous", table=table).state, UNKNOWN)

    def test_a_valid_cached_model_is_loaded_by_name_from_its_folder_with_no_download(self) -> None:
        whisper = self._whisper()
        with self._patched(whisper):
            whisper_local.load_whisper_model("medium", "cpu")
        self.assertEqual(whisper.loads, [("medium", "cpu", str(whisper_models.cache_dir()))])
        self.assertEqual(whisper.downloads, [])

    def test_a_missing_model_is_refused_and_whisper_is_never_called(self) -> None:
        whisper = self._whisper(missing=("medium",))
        with self._patched(whisper), self.assertRaises(ModelNotApproved) as caught:
            whisper_local.load_whisper_model("medium", "cpu")
        self.assertEqual((whisper.loads, whisper.downloads), ([], []))
        self.assertEqual((caught.exception.model, caught.exception.state), ("medium", MISSING))
        self.assertIn("Approve its download in Settings > Dependencies", str(caught.exception))
        self.assertFalse((whisper_models.cache_dir() / "medium.pt").exists())

    def test_a_damaged_model_is_refused_and_never_silently_replaced(self) -> None:
        whisper = self._whisper(damaged=("medium",))
        path = whisper_models.cache_dir() / "medium.pt"
        before = path.read_bytes()
        with self._patched(whisper), self.assertRaises(ModelNotApproved) as caught:
            whisper_local.load_whisper_model("medium", "cpu")
        self.assertEqual(caught.exception.state, DAMAGED)
        self.assertEqual(whisper.loads, [])
        self.assertEqual(path.read_bytes(), before)

    def test_a_name_whisper_does_not_know_is_refused(self) -> None:
        whisper = self._whisper()
        with self._patched(whisper), self.assertRaises(ModelNotApproved) as caught:
            whisper_local.load_whisper_model("enormous", "cpu")
        self.assertEqual(caught.exception.state, UNKNOWN)
        self.assertEqual(whisper.loads, [])

    def test_a_stand_in_without_a_model_table_cannot_get_past_the_check(self) -> None:
        bare = types.SimpleNamespace(load_model=mock.Mock())
        with mock.patch.dict(sys.modules, {"whisper": bare}), self.assertRaises(ModelNotApproved):
            whisper_local.load_whisper_model("medium", "cpu")
        bare.load_model.assert_not_called()

    def test_whispers_table_is_read_from_its_source_without_importing_it(self) -> None:
        package = self.root / "site" / "whisper"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(textwrap.dedent("""
            import torch  # importing Whisper loads PyTorch; reading its table must not
            _MODELS = {
                "base.en": "https://example.invalid/whisper/abc123/base.en.pt",
            }
            """), encoding="utf-8")
        # The path is set in the code itself: the test runtime's Python ignores PYTHONPATH.
        code = (f"import json, sys; sys.path[0:0] = {[str(self.root / 'site'), str(REPO_ROOT / 'src')]!r}; "
                "from media_manglers.core import whisper_models; "
                "print(json.dumps([whisper_models.model_table(), 'whisper' in sys.modules, 'torch' in sys.modules]))")
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        table, whisper_loaded, torch_loaded = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(table, {"base.en": "https://example.invalid/whisper/abc123/base.en.pt"})
        self.assertFalse(whisper_loaded)
        self.assertFalse(torch_loaded)


class EveryFeaturePathTests(ModelCase):
    """Each feature's own path to Whisper, with a valid, a damaged and a missing model."""

    def _cases(self):
        return (("valid", {}), ("damaged", {"damaged": ("base.en", "medium", "small")}),
                ("missing", {"missing": ("base.en", "medium", "small")}))

    def _assert_refused_or_loaded(self, case: str, whisper: RealishWhisper, run) -> None:
        if case == "valid":
            run()
            self.assertTrue(whisper.loads)
            self.assertTrue(all(root == str(whisper_models.cache_dir()) for _name, _device, root in whisper.loads))
        else:
            with self.assertRaises(ModelNotApproved):
                run()
            self.assertEqual(whisper.loads, [], "Whisper was never called")
        self.assertEqual(whisper.downloads, [], "nothing was downloaded")

    def test_transcripts_main_start_transcript_only_inbox_and_deep_scan(self) -> None:
        # whisper_local.transcribe_from_request is the transcription of the main Start (Full Review, Transcript
        # Only, AI / Ticket Evidence), the Inbox, the raw bin's Deep scan and the AI Video Editor's Prepare.
        audio = _wav(self.root / "audio.wav")
        for case, kwargs in self._cases():
            with self.subTest(case):
                whisper = self._whisper(**kwargs)
                request = {"audio_path": str(audio), "output_dir": str(self.root / "out" / case),
                           "model_name": "medium", "language_code": "en", "prefer_gpu": True,
                           "narration_speech_mode": "Continuous", "heartbeat_interval_seconds": 60}
                with self._patched(whisper):
                    self._assert_refused_or_loaded(case, whisper,
                                                   lambda: whisper_local.transcribe_from_request(request))

    def test_voice_probes_full_review_find_my_bug_reports_and_the_raw_bin_scan(self) -> None:
        # The shared voice detection's probes (base.en) and the AI Video Editor's quick passes (small, with each
        # word's time, which needs the model loaded by name).
        for case, kwargs in self._cases():
            for model, words in (("base.en", False), ("small", True)):
                with self.subTest(case=case, model=model):
                    whisper = self._whisper(**kwargs)
                    with self._patched(whisper):
                        self._assert_refused_or_loaded(case, whisper, lambda: voice_track.whisper_transcriber(
                            model, False, "en", word_timestamps=words))

    def test_a_raw_bin_scan_stops_once_and_keeps_what_it_finished(self) -> None:
        folder = self.root / "recordings"
        folder.mkdir()
        for name in ("a.mkv", "b.mkv"):
            (folder / name).write_bytes(b"not really a video")
        old = time.time() - 3600
        for path in folder.iterdir():
            os.utime(path, (old, old))
        calls: list[str] = []

        def examine(path, *_args, **_kwargs):
            calls.append(Path(path).name)
            raise ModelNotApproved("base.en", MISSING)

        options = raw_bin_library.ScanOptions(folders=[str(folder)], library_root=str(self.root / "library"),
                                              cache_folder=str(self.root / "scan-cache"), stable_after_seconds=0)
        with mock.patch.object(raw_bin_library, "examine", side_effect=examine):
            summary = raw_bin_library.scan(options)
        self.assertEqual(summary["status"], "model_not_approved")
        self.assertIn("base.en", summary["message"])
        self.assertEqual(calls, ["a.mkv"], "stopped once, not failed recording by recording")

    def test_a_deep_scan_stops_once(self) -> None:
        with mock.patch.object(raw_bin_library, "deep_scan", side_effect=ModelNotApproved("medium", MISSING)), \
                mock.patch.object(raw_bin_library, "connect", return_value=mock.Mock()):
            with self.assertRaises(ModelNotApproved):
                raw_bin_library.deep_scan_from_request({"recording_ids": [1, 2], "library_root": str(self.root)})

    def test_waveforms_and_speech_facts_in_the_background_skip_with_a_note(self) -> None:
        frames = mock.Mock()
        frames.read.return_value = {0: []}
        frames.ordinals = [0]
        frames.peaks = {}
        jump = mock.Mock(needs_listen=True)
        printed = io.StringIO()
        with mock.patch.object(track_levels.speech_facts, "record_measure", return_value=True), \
                mock.patch.object(track_levels.speech_facts, "jump_points", return_value=jump), \
                mock.patch.object(track_levels.voice_track, "activity_from_frames", return_value={}), \
                mock.patch.object(track_levels.voice_track, "track_details", return_value={}), \
                mock.patch.object(track_levels.voice_track, "detect_from_activities",
                                  side_effect=ModelNotApproved("base.en", MISSING)), \
                mock.patch("sys.stdout", printed):
            ended = track_levels._store_facts(Path("recording.mkv"), frames, [{}], 60.0, ffmpeg="ffmpeg", facts={},
                                              stopped=lambda: False, work=self.root)
        self.assertEqual(ended, "not_stored")
        self.assertIn('"listening_skipped": "model_not_approved"', printed.getvalue())
        frames.remove.assert_not_called()  # the checkpoint stays for a later try

    def test_find_my_bug_reports_checks_its_models_before_it_starts(self) -> None:
        from media_manglers_workbench.app import WorkbenchWindow
        from media_manglers_workbench.resources import DependencyStatus

        rows = [DependencyStatus("Whisper model: medium", "ready", key="whisper_model", model="medium"),
                DependencyStatus("Whisper model: base.en", "needs_setup", key="whisper_model_voice", model="base.en",
                                 detail="Not on this PC yet.")]
        fake = types.SimpleNamespace(runner_thread=None, resources=types.SimpleNamespace(dependencies=rows))
        fake.model_blockers = lambda models: WorkbenchWindow.model_blockers(fake, models)
        from media_manglers_workbench import app as app_module
        with mock.patch.object(app_module, "warn") as warned:
            started = WorkbenchWindow.start_external_run(fake, mock.Mock(), title="Find my bug reports",
                                                         settings={"whisper_model": "medium"}, queue_items=["a.mkv"],
                                                         listener=None, kind="bug_reports")
        self.assertFalse(started)
        self.assertIn("base.en", warned.call_args.args[2])


class ApprovedDownloadTests(ModelCase):
    def _opener(self, body: bytes, calls: list[str]):
        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                self.close()

        def opener(url: str, _timeout: float):
            calls.append(url)
            return Response(body)

        return opener

    def test_a_valid_cached_model_is_reused_with_no_download(self) -> None:
        table = install_models()
        calls: list[str] = []
        found = whisper_models.download_model("medium", table=table, opener=self._opener(b"x", calls))
        self.assertEqual((found.state, calls), (VALID, []))

    def test_an_approved_download_is_checked_before_it_is_put_in_place(self) -> None:
        table = install_models(missing=("medium",))
        calls: list[str] = []
        progress: list[tuple[int, int]] = []
        found = whisper_models.download_model("medium", table=table, opener=self._opener(model_bytes("medium"), calls),
                                              progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(found.state, VALID)
        self.assertEqual(calls, [table["medium"]])
        self.assertEqual(progress[-1], (len(model_bytes("medium")), len(model_bytes("medium"))))
        self.assertEqual(list(whisper_models.cache_dir().glob("*" + whisper_models.PARTIAL_SUFFIX)), [])

    def test_a_download_that_does_not_match_is_never_put_in_place(self) -> None:
        table = install_models(missing=("medium",))
        with self.assertRaises(safe_write.DownloadNotChecked):
            whisper_models.download_model("medium", table=table, opener=self._opener(b"something else", []))
        self.assertFalse((whisper_models.cache_dir() / "medium.pt").exists())
        self.assertEqual(list(whisper_models.cache_dir().glob("*" + whisper_models.PARTIAL_SUFFIX)), [])

    def test_a_damaged_model_is_replaced_only_by_the_approved_download(self) -> None:
        table = install_models(damaged=("medium",))
        found = whisper_models.download_model("medium", table=table, opener=self._opener(model_bytes("medium"), []))
        self.assertEqual(found.state, VALID)
        self.assertEqual((whisper_models.cache_dir() / "medium.pt").read_bytes(), model_bytes("medium"))

    def test_the_download_job_reports_progress_and_its_result(self) -> None:
        from PySide6.QtWidgets import QApplication

        from media_manglers_workbench.app import ModelDownloadThread

        QApplication.instance() or QApplication([])
        work = self.root / "job"
        script = textwrap.dedent(f"""
            import json, pathlib, time
            work = pathlib.Path({str(work)!r})
            request = json.loads((work / "request.json").read_text(encoding="utf-8"))
            (work / "progress.json").write_text(json.dumps({{"model": "medium", "done": 50, "total": 100}}))
            time.sleep(0.8)
            (work / "result.json").write_text(json.dumps({{"ok": True, "data": {{"models": [
                {{"name": name}} for name in request["payload"]["models"]]}}}}))
            """)
        thread = ModelDownloadThread([sys.executable, "-c", script], work / "request.json", work / "result.json",
                                     work / "progress.json", ["medium"])
        seen: list[str] = []
        finished: list[tuple[bool, str]] = []
        thread.progress_changed.connect(seen.append)
        thread.download_finished.connect(lambda ok, message: finished.append((ok, message)))
        thread.start()
        deadline = time.monotonic() + 30
        while thread.isRunning() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.05)
        QApplication.processEvents()
        self.assertTrue(thread.wait(5000))
        QApplication.processEvents()
        self.assertTrue(any("medium" in text and "50%" in text for text in seen), seen)
        self.assertEqual(finished, [(True, "Downloaded and checked: medium.")])


class ReadinessTests(ModelCase):
    """Readiness, with a compatible Python of yours selected: a missing base.en gets the approval offered, a valid
    cached model is reused with no download, and nothing is downloaded or set up for it."""

    def test_the_rows_from_a_real_probe_in_a_python_of_yours(self) -> None:
        # A stand-in Whisper installed in "your" Python: the probe reads its table from the source, never imports it.
        site = self.root / "your-site"
        (site / "whisper").mkdir(parents=True)
        table = install_models(missing=("base.en",), damaged=("small",))
        (site / "whisper" / "__init__.py").write_text(
            "raise ImportError('the readiness check must not import Whisper to check models')\n"
            f"_MODELS = {table!r}\n", encoding="utf-8")
        # "Your" Python is this test's own; the Workbench's real probe runs in it, through the real runner. Its
        # folders are put on the path ahead of the probe's own text (the test runtime's Python ignores PYTHONPATH).
        paths = [str(site), str(REPO_ROOT / "src")]

        def runner(argv, timeout, env):
            code = f"import sys; sys.path[0:0] = {paths!r}\n" + argv[2]
            return dependencies._default_runner([argv[0], "-c", code, *argv[3:]], timeout, env)

        states = dependencies._model_states(sys.executable, ["medium", "base.en", "small"], None, runner)
        self.assertEqual({name: state["state"] for name, state in states.items()},
                         {"medium": VALID, "base.en": MISSING, "small": DAMAGED})
        rows = {model: dependencies._model_row(key, model, purpose, states[model], checked_at="now")
                for key, model, purpose in dependencies.required_models("medium", "small")}
        self.assertEqual(rows["medium"].status, "ready")
        self.assertEqual(rows["medium"].action_kind, "")
        self.assertIn("no download", rows["medium"].detail)
        self.assertEqual(rows["base.en"].action_kind, "approve_model_download")
        self.assertEqual(rows["base.en"].key, "whisper_model_voice")
        self.assertEqual(rows["small"].action_kind, "approve_model_download")
        self.assertIn("never replaced without your approval", rows["small"].detail)
        self.assertFalse(user_folders.addons_root().exists(), "no speech libraries for a Python of yours")

    def test_a_kept_python_of_yours_gets_the_same_model_rows(self) -> None:
        # Exception 1 keeps a Python with working CUDA; its model rows come from that Python.
        root = self.root
        ours = root / "app" / "runtime" / "python" / "python.exe"
        yours = root / "Python312" / "python.exe"
        for path in (ours, yours):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"placeholder")
        base = {"python_version": "3.12.10", "helper_import_ok": True, "whisper_import_ok": True,
                "torch_import_ok": True, "argos_available": False, "model_known": True, "model_cached": False}
        probes = {str(ours.resolve()): {**base, "cuda_available": False},
                  str(yours.resolve()): {**base, "cuda_available": True}}
        asked: list[str] = []

        def runner(argv, _timeout, _env):
            executable = str(Path(argv[0]).resolve())
            if "-c" in argv and argv[argv.index("-c") + 1] == dependencies._MODEL_PROBE:
                asked.append(executable)
                states = {"medium": {"state": VALID, "path": "medium.pt"}, "base.en": {"state": MISSING}}
                return subprocess.CompletedProcess(argv, 0, json.dumps(states), "")
            if executable in probes:
                return subprocess.CompletedProcess(argv, 0, json.dumps({**probes[executable], "python_path": executable}), "")
            return subprocess.CompletedProcess(argv, 1, "", "synthetic")

        resources = RuntimeResources(app_root=REPO_ROOT, script_path=None, backend_source_root=None, icon_path=None,
                                     powershell_exe="", python_exe=str(ours), ffmpeg_exe="", ffprobe_exe="",
                                     packaged=True, bundled_dir=str(root / "app" / "runtime"))
        result = dependencies.run_dependency_preflight(resources, selected_model="medium", runner=runner,
                                                       python_candidates=[str(yours)])
        rows = {item.key: item for item in result.dependencies}
        self.assertEqual(Path(result.python_exe).resolve(), yours.resolve())
        self.assertEqual(asked, [str(yours.resolve())], "the models are checked in the Python that will run Whisper")
        self.assertEqual(rows["whisper_model"].status, "ready")
        self.assertEqual(rows["whisper_model_voice"].action_kind, "approve_model_download")


if __name__ == "__main__":
    unittest.main()
