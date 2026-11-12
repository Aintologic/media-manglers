"""Installer plan, Stage 4: the shared first-launch setup and the one shared downloader.

The setup runs here against small stand-in wheels served by a stand-in connection, in a test folder that stands in
for the operator's user folder (``MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA`` moves ``addons_root()``; ``XDG_CACHE_HOME``
moves the Whisper cache). Every rule is checked the way the real setup applies it: the ``.partial`` file, the pinned
SHA-256, the wheel's own RECORD, the rename into place, older sets removed, models through the approval path. The
real downloads, from the Python Package Index through Windows' certificate check, are proven in Windows Sandbox.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
import urllib.error
import zipfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from media_manglers.core import downloads, private_runtime, safe_write, speech_setup, user_folders, whisper_models  # noqa: E402
from media_manglers.core.whisper_models import MISSING, VALID  # noqa: E402
from media_manglers_workbench import dependencies  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.tool_sources import FOUND_DOWNLOADED, FOUND_ON_PC  # noqa: E402
from outside_holder import OutsideHolder  # noqa: E402
from test_new_file_steps import FORBIDDEN_ADVICE  # noqa: E402
from whisper_test_models import install_models, model_bytes  # noqa: E402


def wheel_bytes(files: dict[str, bytes], dist: str = "pkg-1.0", *, record_override: dict[str, str] | None = None,
                unlisted: tuple[str, ...] = ()) -> bytes:
    """A wheel holding ``files`` and a RECORD listing each one's checksum, as every real wheel does."""

    buffer = io.BytesIO()
    rows: list[str] = []
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
            if name in unlisted:
                continue
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            rows.append(f"{name},sha256={(record_override or {}).get(name, digest)},{len(data)}")
        record = f"{dist}.dist-info/RECORD"
        rows.append(f"{record},,")
        archive.writestr(record, "\n".join(rows) + "\n")
    return buffer.getvalue()


class Served:
    """A stand-in connection: serves each address's bytes, and records every address asked for."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.calls: list[str] = []
        self.fail_once: dict[str, BaseException] = {}

    def __call__(self, url: str, _timeout: float):
        self.calls.append(url)
        if url in self.fail_once:
            raise self.fail_once.pop(url)
        body = self.files[url]

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                self.close()

        return Response(body)


class SetupCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {
            user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.root / "local"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        })
        self.env.start()
        self.app = self.root / "app"
        (self.app / "runtime" / "python").mkdir(parents=True)
        (self.app / private_runtime.APP_MARKER).write_text("# backend\n", encoding="utf-8")
        (self.app / "runtime" / "python" / "python.exe").write_bytes(b"placeholder")
        self.wheels = {
            "alpha-1.0-py3-none-any.whl": wheel_bytes({
                "alpha/__init__.py": b"VALUE = 1\n",
                "alpha/deep/module.py": b"def f():\n    return 2\n",
                "alpha-1.0.dist-info/METADATA": b"Name: alpha\nVersion: 1.0\n",
                "alpha-1.0.data/purelib/alpha_extra.py": b"EXTRA = 3\n",
                "alpha-1.0.data/scripts/alpha-tool": b"#!python\n",
            }, "alpha-1.0"),
            "beta-2.0-cp312-cp312-win_amd64.whl": wheel_bytes({
                "beta/__init__.py": b"from . import core\n",
                "beta/core.py": b"NAME = 'beta'\n",
                "beta/bin/protoc.exe": b"not wanted",
                "beta-2.0.dist-info/METADATA": b"Name: beta\nVersion: 2.0\n",
            }, "beta-2.0"),
        }
        self.write_lock()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def url(self, name: str) -> str:
        return f"https://files.invalid/{name}"

    def write_lock(self, wheels: dict[str, bytes] | None = None) -> speech_setup.SpeechLock:
        wheels = self.wheels if wheels is None else wheels
        files = [{"name": name.split("-")[0], "version": name.split("-")[1], "file": name, "url": self.url(name),
                  "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "licence": "MIT"}
                 for name, data in wheels.items()]
        skip = ["beta/bin/protoc.exe"]
        lock = {"set_id": speech_setup.set_id_for([(f["file"], f["sha256"]) for f in files], skip, "cp312",
                                                  "win_amd64"),
                "python": "cp312", "platform": "win_amd64", "skip_on_unpack": skip, "files": files,
                "total_bytes": sum(f["size"] for f in files)}
        speech_setup.lock_path(self.app).write_text(json.dumps(lock), encoding="utf-8")
        found = speech_setup.read_lock(self.app)
        assert found is not None
        return found

    def served(self, wheels: dict[str, bytes] | None = None) -> Served:
        return Served({self.url(name): data for name, data in (self.wheels if wheels is None else wheels).items()})

    def set_up(self, opener: Served, **options):
        return speech_setup.set_up_libraries(self.app, opener=opener, check_python=False, compile_workers=1,
                                             **options)

    def final(self) -> Path:
        lock = speech_setup.read_lock(self.app)
        assert lock is not None
        return speech_setup.set_folder(lock.set_id)


class LibrariesTests(SetupCase):
    def test_the_set_is_downloaded_checked_unpacked_compiled_and_renamed_into_place(self) -> None:
        opener = self.served()
        result = self.set_up(opener)
        final = self.final()
        self.assertEqual(final.parent, user_folders.addons_root(), "the one add-ons folder, from addons_root()")
        self.assertTrue(speech_setup.libraries_ready(self.app))
        self.assertEqual(sorted(opener.calls), sorted(self.url(name) for name in self.wheels))
        # The importable parts are there; scripts and the skipped program are not.
        self.assertEqual((final / "alpha" / "deep" / "module.py").read_bytes(), b"def f():\n    return 2\n")
        self.assertTrue((final / "alpha_extra.py").is_file(), "a .data folder's purelib goes beside the packages")
        self.assertTrue((final / "alpha-1.0.dist-info" / "METADATA").is_file())
        self.assertFalse(any(path.name == "alpha-tool" for path in final.rglob("*")))
        self.assertFalse((final / "beta" / "bin" / "protoc.exe").exists())
        # Compiled once, now, so Python never writes beside the libraries later.
        self.assertTrue(list((final / "alpha" / "deep" / "__pycache__").glob("module.*.pyc")))
        # Nothing left under a temporary name, and the downloaded files are gone.
        root = user_folders.addons_root()
        self.assertEqual(sorted(path.name for path in root.iterdir()), [final.name])
        self.assertFalse(list(root.rglob("*" + downloads.PARTIAL_SUFFIX)))
        marker = json.loads((final / speech_setup.MARKER_FILE).read_text(encoding="utf-8"))
        self.assertEqual(marker["certificates"], downloads.verification())
        self.assertEqual(result["download"]["downloaded"], 2)
        self.assertGreater(result["longest_path"], len(str(final)))

    def test_our_own_python_finds_the_set_and_no_other_python_does(self) -> None:
        self.set_up(self.served())
        private = self.app / "runtime" / "python" / "python.exe"
        path: list[str] = []
        self.assertEqual(private_runtime.use_addons(private, path), self.final())
        self.assertEqual(path, [str(self.final())])
        other: list[str] = []
        self.assertIsNone(private_runtime.use_addons(self.root / "Python312" / "python.exe", other))
        self.assertEqual(other, [])

    def test_the_start_up_hook_gives_our_python_its_set_in_every_process(self) -> None:
        # The backend checks Whisper with a bare "import whisper"; the hook in our Python's site-packages runs first.
        site = self.app / "runtime" / "python" / "Lib" / "site-packages"
        site.mkdir(parents=True)
        hook = private_runtime.write_addons_hook(site)
        lines = [line for line in hook.read_text(encoding="utf-8").splitlines() if line.startswith("import ")]
        self.assertEqual(lines, [private_runtime.ADDONS_HOOK_LINE], "Python runs only lines that start with import")
        with mock.patch.object(private_runtime, "use_addons") as used:
            exec(lines[0], {})  # noqa: S102 - exactly what Python's site module does with the line
        used.assert_called_once_with()
        with mock.patch.object(private_runtime, "use_addons", side_effect=RuntimeError("broken")):
            exec(lines[0], {})  # noqa: S102 - a failing hook changes nothing and stops nothing

    def test_a_finished_set_is_not_set_up_twice(self) -> None:
        self.set_up(self.served())
        again = self.served()
        result = self.set_up(again)
        self.assertTrue(result["already_set_up"])
        self.assertEqual(again.calls, [])

    def test_a_download_that_does_not_match_its_pin_is_never_used(self) -> None:
        wrong = dict(self.wheels)
        # The right size, so it is the checksum that refuses it.
        wrong["alpha-1.0-py3-none-any.whl"] = b"x" * len(self.wheels["alpha-1.0-py3-none-any.whl"])
        with self.assertRaises(safe_write.DownloadNotChecked):
            self.set_up(self.served(wrong))
        root = user_folders.addons_root()
        self.assertFalse((root / "downloads" / "alpha-1.0-py3-none-any.whl").exists())
        self.assertFalse(list(root.rglob("*" + downloads.PARTIAL_SUFFIX)))
        self.assertFalse(speech_setup.libraries_ready(self.app))

    def test_a_file_that_does_not_match_its_wheels_own_record_stops_the_setup(self) -> None:
        bad = dict(self.wheels)
        bad["alpha-1.0-py3-none-any.whl"] = wheel_bytes({"alpha/__init__.py": b"VALUE = 1\n"}, "alpha-1.0",
                                                        record_override={"alpha/__init__.py": "A" * 43})
        self.write_lock(bad)
        with self.assertRaises(speech_setup.SetupRefused) as caught:
            self.set_up(self.served(bad))
        self.assertIn("does not match", str(caught.exception))
        self.assertFalse(speech_setup.libraries_ready(self.app))
        root = user_folders.addons_root()
        self.assertEqual([path.name for path in root.iterdir()], ["downloads"],
                         "the half-built set is removed at once; only the checked downloads are kept")
        # A corrected list makes a new set, and the download that still matches its pin is reused.
        self.write_lock()
        opener = self.served()
        self.set_up(opener)
        self.assertTrue(speech_setup.libraries_ready(self.app))
        self.assertEqual([path.name for path in root.iterdir()], [self.final().name])
        self.assertEqual(opener.calls, [self.url("alpha-1.0-py3-none-any.whl")], "the matching download is reused")

    def test_a_full_disk_stops_the_setup_in_plain_words_and_removes_the_half_built_set(self) -> None:
        import errno

        def full(*_args, **_kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(speech_setup, "compile_folder", side_effect=full), \
                self.assertRaises(speech_setup.SetupRefused) as caught:
            self.set_up(self.served())
        self.assertIn("disk", str(caught.exception))
        self.assertIn("is full", str(caught.exception))
        self.assertFalse(any(path.name.endswith(speech_setup.TEMP_SUFFIX) for path in user_folders.addons_root().iterdir()))

    def test_a_set_that_no_longer_loads_is_set_up_again_on_request(self) -> None:
        self.set_up(self.served())
        (self.final() / "alpha" / "__init__.py").unlink()  # as if a scanner had quarantined part of it
        again = self.set_up(self.served())
        self.assertTrue(again["already_set_up"], "without repair a set that is there is left alone")
        repaired = self.set_up(self.served(), repair=True)
        self.assertTrue((self.final() / "alpha" / "__init__.py").is_file())
        self.assertTrue(any("no longer loaded" in note for note in repaired["notes"]))

    def test_an_already_set_up_copy_removes_downloads_left_by_an_earlier_setup(self) -> None:
        self.set_up(self.served())
        leftover = user_folders.addons_root() / "downloads" / "left.whl"
        leftover.parent.mkdir()
        leftover.write_bytes(b"left")
        self.set_up(self.served())
        self.assertFalse(leftover.parent.exists())

    def test_a_network_path_gets_windows_long_path_form(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows paths")
        self.assertEqual(speech_setup._long_path(Path(r"\\server\share\addons\x.py")),
                         r"\\?\UNC\server\share\addons\x.py")
        self.assertEqual(speech_setup._long_path(Path(r"C:\addons\x.py")), r"\\?\C:\addons\x.py")

    def test_a_cut_short_setup_of_the_same_set_is_removed_first(self) -> None:
        lock = speech_setup.read_lock(self.app)
        assert lock is not None
        half = self.final().with_name(self.final().name + speech_setup.TEMP_SUFFIX)
        (half / "alpha").mkdir(parents=True)
        (half / "alpha" / "__init__.py").write_text("HALF = 1\n", encoding="utf-8")
        result = self.set_up(self.served())
        self.assertTrue(any("cut short" in note for note in result["notes"]), result["notes"])
        self.assertEqual((self.final() / "alpha" / "__init__.py").read_bytes(), b"VALUE = 1\n")

    def test_a_file_its_wheels_record_does_not_name_is_refused(self) -> None:
        sneaky = dict(self.wheels)
        sneaky["alpha-1.0-py3-none-any.whl"] = wheel_bytes(
            {"alpha/__init__.py": b"VALUE = 1\n", "alpha/extra.py": b"X = 1\n"}, "alpha-1.0", unlisted=("alpha/extra.py",))
        self.write_lock(sneaky)
        with self.assertRaises(speech_setup.SetupRefused):
            self.set_up(self.served(sneaky))

    def test_a_library_carried_inside_a_wheel_with_its_own_record_is_unpacked_by_the_wheels_record(self) -> None:
        # setuptools, one of the pinned speech libraries, carries others in _vendor, each with its own RECORD.
        inner = b"inner-1.0.dist-info/RECORD,,\n"
        carrying = dict(self.wheels)
        carrying["alpha-1.0-py3-none-any.whl"] = wheel_bytes({
            "alpha/__init__.py": b"VALUE = 1\n",
            "alpha/_vendor/inner-1.0.dist-info/RECORD": inner,
            "alpha/_vendor/inner/__init__.py": b"INNER = 1\n",
        }, "alpha-1.0")
        self.write_lock(carrying)
        self.set_up(self.served(carrying))
        self.assertEqual((self.final() / "alpha" / "_vendor" / "inner" / "__init__.py").read_bytes(), b"INNER = 1\n")

    def test_a_member_that_would_land_outside_the_set_is_refused(self) -> None:
        for name in ("../evil.py", "/rooted.py", "C:/drive.py", "alpha/..\\up.py"):
            with self.subTest(name=name), self.assertRaises(speech_setup.SetupRefused):
                speech_setup._member_target(name, ())

    def test_downloads_a_cut_short_setup_finished_are_reused(self) -> None:
        wheels = user_folders.addons_root() / "downloads"
        wheels.mkdir(parents=True)
        (wheels / "beta-2.0-cp312-cp312-win_amd64.whl").write_bytes(self.wheels["beta-2.0-cp312-cp312-win_amd64.whl"])
        (wheels / ("alpha-1.0-py3-none-any.whl" + downloads.PARTIAL_SUFFIX)).write_bytes(b"half")
        opener = self.served()
        result = self.set_up(opener)
        self.assertEqual(opener.calls, [self.url("alpha-1.0-py3-none-any.whl")])
        self.assertEqual((result["download"]["downloaded"], result["download"]["reused"]), (1, 1))

    def test_older_sets_are_removed_and_one_another_program_holds_is_named_and_kept(self) -> None:
        root = user_folders.addons_root()
        for old in ("sp-0ld0ld01", "sp-0ld0ld02"):
            (root / old / "pkg").mkdir(parents=True)
            (root / old / "pkg" / "old.py").write_text("OLD = 1\n", encoding="utf-8")
        real_budget = safe_write.StepBudget
        with mock.patch.object(safe_write, "StepBudget", lambda *a, **k: real_budget(0.5, 1.0)), \
                OutsideHolder(root / "sp-0ld0ld02" / "pkg" / "old.py"):
            result = self.set_up(self.served())
        self.assertTrue(speech_setup.libraries_ready(self.app), "a held older set never fails the setup")
        self.assertEqual(result["older_sets_removed"], ["sp-0ld0ld01"])
        self.assertFalse((root / "sp-0ld0ld01").exists())
        note = " ".join(result["notes"])
        self.assertIn("sp-0ld0ld02", note)
        self.assertIn("python", note.casefold(), "the program holding it is named")
        # The next setup removes it.
        self.assertEqual(speech_setup.remove_older_sets(self.final().name[len(speech_setup.SET_PREFIX):], []),
                         ["sp-0ld0ld02"])

    def test_paths_windows_would_refuse_stop_the_setup_before_anything_is_unpacked(self) -> None:
        with mock.patch.object(speech_setup, "WINDOWS_PATH_LIMIT", 20), \
                mock.patch.object(speech_setup, "long_paths_enabled", return_value=False):
            with self.assertRaises(speech_setup.SetupRefused) as caught:
                self.set_up(self.served())
        self.assertIn("longer than Windows allows", str(caught.exception))
        root = user_folders.addons_root()
        self.assertFalse(any(path.name.startswith(speech_setup.SET_PREFIX) for path in root.iterdir()))
        self.assertEqual(len(list((root / "downloads").iterdir())), 2, "the downloads are kept for the next try")

    def test_the_longest_path_counts_the_compiled_files_too(self) -> None:
        final = Path("C:/x/sp-12345678")
        lengths = speech_setup._final_lengths("pkg/module.py", final)
        self.assertEqual(lengths[0], len("C:/x/sp-12345678/pkg/module.py"))
        self.assertEqual(lengths[1], len(f"C:/x/sp-12345678/pkg/__pycache__/module.{sys.implementation.cache_tag}.pyc"))

    def test_only_our_own_python_sets_up_the_libraries(self) -> None:
        opener = self.served()
        with self.assertRaises(speech_setup.SetupRefused) as caught:
            speech_setup.set_up_libraries(self.app, opener=opener)
        self.assertIn("own Python", str(caught.exception))
        self.assertEqual(opener.calls, [])
        self.assertFalse(user_folders.addons_root().exists())

    def test_a_python_of_another_version_is_refused(self) -> None:
        lock = speech_setup.read_lock(self.app)
        assert lock is not None
        other = speech_setup.SpeechLock(lock.set_id, "cp399", lock.platform, lock.files, lock.skip_on_unpack)
        with mock.patch.object(private_runtime, "is_private_python", return_value=True), \
                self.assertRaises(speech_setup.SetupRefused):
            speech_setup._check_python(other)

    def test_the_progress_file_says_what_is_happening(self) -> None:
        progress = self.root / "progress.json"
        seen: list[dict] = []
        self.set_up(self.served(), report=speech_setup.Reporter(str(progress), seen.append))
        stages = [item["stage"] for item in seen]
        for stage in ("download", "unpack", "compile", "finish"):
            self.assertIn(stage, stages)
        self.assertTrue(any(item["text"].startswith("Downloading the speech libraries") for item in seen))
        self.assertTrue(json.loads(progress.read_text(encoding="utf-8"))["text"])


class ModelsTests(SetupCase):
    def test_base_en_comes_through_the_approval_path(self) -> None:
        table = install_models(missing=("base.en",))
        opener = Served({table["base.en"]: model_bytes("base.en")})
        with mock.patch.object(whisper_models, "model_table", return_value=table):
            result = speech_setup.run_setup(app=self.app, libraries=False, models=["base.en"], opener=opener,
                                            check_python=False)
        self.assertEqual(opener.calls, [table["base.en"]])
        self.assertEqual(result["models"][0]["state"], VALID)
        self.assertFalse(result["models"][0]["reused"])
        self.assertNotIn("libraries", result, "a Python of yours has its own speech libraries")
        self.assertFalse(user_folders.addons_root().exists())

    def test_a_valid_cached_model_is_used_as_it_is(self) -> None:
        table = install_models()
        opener = Served({})
        with mock.patch.object(whisper_models, "model_table", return_value=table):
            result = speech_setup.run_setup(app=self.app, libraries=False, models=["base.en"], opener=opener,
                                            check_python=False)
        self.assertEqual(opener.calls, [])
        self.assertTrue(result["models"][0]["reused"])

    def test_the_whole_setup_libraries_then_base_en(self) -> None:
        table = install_models(missing=("base.en",))
        opener = Served({**{self.url(name): data for name, data in self.wheels.items()},
                         table["base.en"]: model_bytes("base.en")})
        with mock.patch.object(whisper_models, "model_table", return_value=table), \
                mock.patch.object(speech_setup, "compile_folder", wraps=lambda folder, workers=0: True):
            result = speech_setup.run_setup(app=self.app, opener=opener, check_python=False)
        self.assertTrue(speech_setup.libraries_ready(self.app))
        self.assertEqual(whisper_models.model_state("base.en", table=table).state, VALID)
        self.assertEqual(opener.calls[-1], table["base.en"], "the model comes after the libraries")
        self.assertEqual(result["certificates"], downloads.verification())

    def test_the_command_is_registered_and_refuses_another_python_in_plain_words(self) -> None:
        request, result = self.root / "request.json", self.root / "result.json"
        request.write_text(json.dumps({"payload": {"libraries": True, "models": []}}), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
        bootstrap = (f"import sys; sys.path.insert(0, {str(REPO_ROOT / 'src')!r}); "
                     "from media_manglers.cli import main; raise SystemExit(main(sys.argv[1:]))")
        completed = subprocess.run([sys.executable, "-c", bootstrap, "speech-setup", "--request-file", str(request),
                                    "--result-file", str(result)], capture_output=True, text=True, timeout=120,
                                   env=env, cwd=str(self.root), check=False)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        outcome = json.loads(result.read_text(encoding="utf-8"))
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome["error"])


class DownloaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_certificates_are_checked_by_windows(self) -> None:
        import truststore

        context = downloads.tls_context()
        self.assertIsInstance(context, truststore.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_without_windows_checking_nothing_is_downloaded_and_nothing_else_is_tried(self) -> None:
        with mock.patch.dict(sys.modules, {"truststore": None}):
            with self.assertRaises(downloads.DownloadFailed) as caught:
                downloads.open_url("https://files.invalid/x")
        self.assertIn("nothing was downloaded", str(caught.exception))

    def test_only_https_addresses(self) -> None:
        with self.assertRaises(downloads.DownloadFailed):
            downloads.download_file("http://files.invalid/x.whl", self.root / "x.whl", "0" * 64)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_file_without_a_pinned_checksum_is_never_downloaded(self) -> None:
        opener = Served({"https://files.invalid/x": b"x"})
        with self.assertRaises(downloads.DownloadFailed):
            downloads.download_file("https://files.invalid/x", self.root / "x", "", opener=opener)
        self.assertEqual(opener.calls, [])

    def test_a_certificate_windows_does_not_trust_stops_at_once_in_plain_words(self) -> None:
        url = "https://files.invalid/x"
        opener = Served({url: b"x"})
        opener.fail_once[url] = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
        pauses: list[float] = []
        with self.assertRaises(downloads.CertificateNotTrusted) as caught:
            downloads.download_file(url, self.root / "x", hashlib.sha256(b"x").hexdigest(), opener=opener,
                                    pause=pauses.append)
        self.assertEqual((opener.calls, pauses), ([url], []), "never tried again, never another way")
        text = str(caught.exception).casefold()
        self.assertIn("windows did not trust", text)
        for word in FORBIDDEN_ADVICE:
            self.assertNotIn(word, text)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_short_network_failure_is_tried_again(self) -> None:
        url = "https://files.invalid/x"
        opener = Served({url: b"payload"})
        opener.fail_once[url] = ConnectionResetError("reset")
        pauses: list[float] = []
        target = downloads.download_file(url, self.root / "x", hashlib.sha256(b"payload").hexdigest(), size=7,
                                         opener=opener, pause=pauses.append)
        self.assertEqual(target.read_bytes(), b"payload")
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(len(pauses), 1)

    def test_server_errors_are_tried_again_and_reported_in_plain_words(self) -> None:
        import email.message

        url = "https://files.invalid/x"
        busy = urllib.error.HTTPError(url, 503, "Service Unavailable", email.message.Message(), None)
        opener = Served({url: b"payload"})
        opener.fail_once[url] = busy
        pauses: list[float] = []
        downloads.download_file(url, self.root / "x", hashlib.sha256(b"payload").hexdigest(), opener=opener,
                                pause=pauses.append)
        self.assertEqual((len(opener.calls), len(pauses)), (2, 1), "a 503 is tried again")
        for failure, word in ((urllib.error.HTTPError(url, 404, "Not Found", email.message.Message(), None), "404"),
                              (urllib.error.URLError("no host given"), "no host given"),
                              (urllib.error.URLError(ssl.SSLError(1, "UNEXPECTED_EOF_WHILE_READING")), "EOF")):
            with self.subTest(failure=repr(failure)):
                opener = Served({url: b"payload"})
                opener.fail_once[url] = failure
                with self.assertRaises(downloads.DownloadFailed) as caught:
                    downloads.download_file(url, self.root / "y", hashlib.sha256(b"payload").hexdigest(),
                                            opener=opener, attempts=1)
                self.assertIn("could not be downloaded", str(caught.exception))
                self.assertIn(word, str(caught.exception))
                self.assertNotIsInstance(caught.exception, downloads.CertificateNotTrusted)

    def test_a_full_disk_is_named_not_the_network(self) -> None:
        import errno

        url = "https://files.invalid/x"
        opener = Served({url: b"payload"})
        opener.fail_once[url] = OSError(errno.ENOSPC, "No space left on device")
        with self.assertRaises(downloads.DownloadFailed) as caught:
            downloads.download_file(url, self.root / "x", hashlib.sha256(b"payload").hexdigest(), opener=opener)
        self.assertIn("disk is full", str(caught.exception))
        self.assertNotIn("network", str(caught.exception))

    def test_a_redirect_to_plain_http_is_refused(self) -> None:
        import urllib.request

        handler = None

        def capture(*handlers):
            nonlocal handler
            handler = next(item for item in handlers if isinstance(item, urllib.request.HTTPRedirectHandler))
            raise RuntimeError("stop before any connection")

        with mock.patch("urllib.request.build_opener", side_effect=capture), self.assertRaises(RuntimeError):
            downloads.open_url("https://files.invalid/x")
        request = urllib.request.Request("https://files.invalid/x")
        with self.assertRaises(downloads.DownloadFailed):
            handler.redirect_request(request, None, 302, "Found", {}, "http://mirror.invalid/x")
        self.assertIsNotNone(handler.redirect_request(request, None, 302, "Found", {}, "https://mirror.invalid/x"))

    def test_a_file_of_the_wrong_size_is_never_put_in_place(self) -> None:
        url = "https://files.invalid/x"
        with self.assertRaises(downloads.DownloadFailed):
            downloads.download_file(url, self.root / "x", hashlib.sha256(b"abc").hexdigest(), size=4,
                                    opener=Served({url: b"abc"}))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_the_whisper_models_use_the_shared_downloader(self) -> None:
        self.assertIs(whisper_models.download_model.__kwdefaults__["opener"], downloads.open_url)
        self.assertEqual(whisper_models.PARTIAL_SUFFIX, downloads.PARTIAL_SUFFIX)

    def test_no_code_turns_certificate_checks_off_or_downloads_another_way(self) -> None:
        forbidden = re.compile(r"CERT_NONE|_create_unverified_context|check_hostname\s*=\s*False|verify\s*=\s*False|"
                               r"PYTHONHTTPSVERIFY|curl\.exe|SkipCertificateCheck|ServerCertificateValidationCallback")
        places = [*(REPO_ROOT / "src").rglob("*.py"), *(REPO_ROOT / "tools" / "installer").rglob("*.p*")]
        found = [f"{path.relative_to(REPO_ROOT)}:{number}" for path in places
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
                 if forbidden.search(line)]
        self.assertEqual(found, [])

    def test_no_message_advises_an_exclusion_or_turning_protection_off(self) -> None:
        for module in (downloads, speech_setup):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for word in FORBIDDEN_ADVICE:
                        self.assertNotIn(word, node.value.casefold(), f"{module.__name__}: {node.value}")


class LockFileTests(unittest.TestCase):
    """The pinned list the build puts beside our own Python."""

    def test_the_repository_lock_is_consistent(self) -> None:
        lock = json.loads((REPO_ROOT / "tools" / "installer" / "speech-lock.json").read_text(encoding="utf-8"))
        files = lock["files"]
        self.assertEqual(lock["set_id"], speech_setup.set_id_for([(f["file"], f["sha256"]) for f in files],
                                                                 lock["skip_on_unpack"], lock["python"],
                                                                 lock["platform"]),
                         "a changed pin needs a new set id: run the lock maker again")
        self.assertEqual((lock["python"], lock["platform"]), ("cp312", "win_amd64"))
        self.assertEqual(lock["total_bytes"], sum(int(f["size"]) for f in files))
        for item in files:
            self.assertTrue(item["url"].startswith("https://files.pythonhosted.org/"), item["url"])
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(item["licence"], item["name"])
            self.assertTrue(item["url"].endswith("/" + item["file"]))
        self.assertIn("torch", {item["name"] for item in files})
        self.assertNotIn("pip", {item["name"] for item in files}, "no pip is ever downloaded")


# Readiness and the Workbench ----------------------------------------------------------------------------------


class ReadinessTests(SetupCase):
    def _preflight(self, probes: dict[str, dict], candidates: list[str] | None = None):
        def runner(argv, _timeout, _env):
            executable = str(Path(argv[0]).resolve())
            if "-c" in argv and argv[argv.index("-c") + 1] == dependencies._MODEL_PROBE:
                return subprocess.CompletedProcess(argv, 0, json.dumps({"base.en": {"state": MISSING}}), "")
            if executable in probes:
                return subprocess.CompletedProcess(argv, 0, json.dumps({**probes[executable],
                                                                         "python_path": executable}), "")
            return subprocess.CompletedProcess(argv, 1, "", "synthetic")

        resources = RuntimeResources(app_root=self.app, script_path=None, backend_source_root=None, icon_path=None,
                                     powershell_exe="", python_exe="", ffmpeg_exe="", ffprobe_exe="", packaged=True,
                                     bundled_dir=str(self.app / "runtime"))
        result = dependencies.run_dependency_preflight(resources, selected_model="base.en", runner=runner,
                                                       python_candidates=candidates or [])
        return {item.key: item for item in result.dependencies}

    def _ours(self) -> dict:
        return {"python_version": "3.12.10", "helper_import_ok": True, "whisper_import_ok": False,
                "torch_import_ok": False, "argos_available": False, "cuda_available": False,
                "error": "No module named 'torch'"}

    def test_before_the_setup_every_whisper_row_points_to_set_up(self) -> None:
        ours = str((self.app / "runtime" / "python" / "python.exe").resolve())
        rows = self._preflight({ours: self._ours()})
        speech = rows[dependencies.SPEECH_ROW]
        self.assertEqual((speech.name, speech.status, speech.action_kind),
                         ("Speech recognition", "needs_setup", "speech_setup"))
        self.assertFalse(speech.required, "transcripts need it; nothing else is affected")
        for key in ("whisper", "torch", "cpu_fallback"):
            self.assertEqual(rows[key].action_kind, "speech_setup", key)
        self.assertIn("not set up", rows["whisper"].detail)
        self.assertEqual(rows["whisper_model"].model_state, MISSING)

    def test_after_the_setup_the_row_says_downloaded_by_media_manglers(self) -> None:
        self.set_up(self.served())
        ours = str((self.app / "runtime" / "python" / "python.exe").resolve())
        loads = {**self._ours(), "whisper_import_ok": True, "torch_import_ok": True, "error": ""}
        rows = self._preflight({ours: loads})
        speech = rows[dependencies.SPEECH_ROW]
        self.assertEqual((speech.status, speech.found_by), ("ready", FOUND_DOWNLOADED))
        self.assertEqual(Path(speech.path), self.final())

    def test_a_kept_python_of_yours_needs_no_speech_libraries(self) -> None:
        ours = str((self.app / "runtime" / "python" / "python.exe").resolve())
        yours = self.root / "Python312" / "python.exe"
        yours.parent.mkdir()
        yours.write_bytes(b"placeholder")
        theirs = {**self._ours(), "whisper_import_ok": True, "torch_import_ok": True, "cuda_available": True}
        rows = self._preflight({ours: self._ours(), str(yours.resolve()): theirs}, [str(yours)])
        speech = rows[dependencies.SPEECH_ROW]
        self.assertEqual((speech.status, speech.found_by), ("ready", FOUND_ON_PC))
        self.assertIn("Not needed", speech.detail)
        self.assertNotEqual(rows["whisper"].action_kind, "speech_setup")

    def test_a_set_that_is_there_but_does_not_load_offers_set_up_again(self) -> None:
        self.set_up(self.served())
        ours = str((self.app / "runtime" / "python" / "python.exe").resolve())
        rows = self._preflight({ours: self._ours()})
        speech = rows[dependencies.SPEECH_ROW]
        self.assertEqual((speech.status, speech.model_state, speech.action_kind), ("needs_setup", "damaged", "speech_setup"))
        self.assertIn("no longer load", speech.detail)
        self.assertEqual(rows["torch"].action_kind, "speech_setup")
        self.assertIn("again", rows["torch"].detail)

    def test_a_python_of_yours_without_whisper_is_not_said_to_have_speech_libraries(self) -> None:
        ours = str((self.app / "runtime" / "python" / "python.exe").resolve())
        yours = self.root / "Chosen" / "python.exe"
        yours.parent.mkdir()
        yours.write_bytes(b"placeholder")
        # Exception 1 keeps a CUDA Python only when it has Whisper; a chosen Python is the only candidate.
        resources = RuntimeResources(app_root=self.app, script_path=None, backend_source_root=None, icon_path=None,
                                     powershell_exe="", python_exe=str(yours), ffmpeg_exe="", ffprobe_exe="",
                                     packaged=True, bundled_dir=str(self.app / "runtime"))

        def runner(argv, _timeout, _env):
            if "-c" in argv and argv[argv.index("-c") + 1] == dependencies._MODEL_PROBE:
                return subprocess.CompletedProcess(argv, 0, "{}", "")
            return subprocess.CompletedProcess(argv, 0, json.dumps({**self._ours(), "python_path": str(yours)}), "")

        result = dependencies.run_dependency_preflight(resources, selected_model="base.en", runner=runner,
                                                       configured_python=str(yours))
        speech = {item.key: item for item in result.dependencies}[dependencies.SPEECH_ROW]
        self.assertEqual(speech.status, "optional")
        self.assertNotIn("has its own speech libraries", speech.detail)

    def test_a_copy_without_a_speech_list_has_no_speech_row(self) -> None:
        speech_setup.lock_path(self.app).unlink()
        ours = str((self.app / "runtime" / "python" / "python.exe").resolve())
        rows = self._preflight({ours: self._ours()})
        self.assertNotIn(dependencies.SPEECH_ROW, rows)


class QuestionTests(SetupCase):
    def _window(self, rows: list[DependencyStatus], **attributes):
        from media_manglers_workbench.app import WorkbenchWindow

        fake = types.SimpleNamespace(
            resources=types.SimpleNamespace(dependencies=rows, bundled_dir=str(self.app / "runtime"),
                                            backend_source_root=REPO_ROOT / "src", python_exe=""),
            app_settings={"temp_folder": str(self.root / "work")}, speech_setup_thread=None, model_download_thread=None,
            first_launch_questions=True, _speech_question_asked=False, asked=[],
            dependency_summary=mock.Mock(), save_app_settings=mock.Mock(), _write_workbench_log=mock.Mock(),
            start_speech_setup=mock.Mock(return_value=True))
        fake._dependency_by_key = lambda key: next((item for item in rows if item.key == key), None)
        fake.private_python = types.MethodType(WorkbenchWindow.private_python, fake)
        fake.speech_setup_needs = types.MethodType(WorkbenchWindow.speech_setup_needs, fake)
        fake.speech_setup_question = WorkbenchWindow.speech_setup_question
        answer = attributes.pop("answer", True)
        fake._ask_speech_setup = lambda text: fake.asked.append(text) or answer
        for name, value in attributes.items():
            setattr(fake, name, value)
        fake.offer = types.MethodType(WorkbenchWindow.offer_speech_setup, fake)
        return fake

    def _rows(self, *, libraries: bool = True, voice: str = MISSING) -> list[DependencyStatus]:
        return [DependencyStatus("Speech recognition", "needs_setup" if libraries else "ready", key=dependencies.SPEECH_ROW),
                DependencyStatus("Whisper model: base.en", "ready" if voice == VALID else "needs_setup",
                                 key="whisper_model_voice", model="base.en", model_state=voice)]

    def test_the_question_names_the_size_and_where_the_files_go(self) -> None:
        window = self._window(self._rows())
        needs = window.speech_setup_needs()
        lock = speech_setup.read_lock(self.app)
        self.assertEqual(needs, {"libraries": True, "repair": False, "yours": False, "models": ["base.en"],
                                 "bytes": lock.total_bytes + speech_setup.VOICE_MODEL_BYTES})
        from media_manglers_workbench.app import WorkbenchWindow

        real = {**needs, "bytes": 196_521_225 + speech_setup.VOICE_MODEL_BYTES}
        text = WorkbenchWindow.speech_setup_question(real)
        self.assertIn("about 0.34 GB from the Python Package Index and the Whisper model server", text)
        self.assertIn("saved in your user folder, not in the program folder. Download now?", text)

    def test_download_starts_the_setup_once(self) -> None:
        window = self._window(self._rows())
        self.assertTrue(window.offer(first_launch=True))
        window.start_speech_setup.assert_called_once_with(libraries=True, models=["base.en"], repair=False, yours=False)
        self.assertFalse(window.offer(first_launch=True), "asked once per launch")
        self.assertEqual(len(window.asked), 1)

    def test_not_now_is_remembered_and_the_row_still_offers_set_up(self) -> None:
        window = self._window(self._rows(), answer=False)
        self.assertFalse(window.offer(first_launch=True))
        self.assertTrue(window.app_settings["speech_setup_declined"])
        window.start_speech_setup.assert_not_called()
        window._speech_question_asked = False  # a later launch
        self.assertFalse(window.offer(first_launch=True))
        self.assertEqual(len(window.asked), 1, "not asked again at start-up after Not now")
        window.offer()  # the row's Set up asks again
        self.assertEqual(len(window.asked), 2)

    def test_a_smoke_launch_never_asks(self) -> None:
        window = self._window(self._rows(), first_launch_questions=False)
        self.assertFalse(window.offer(first_launch=True))
        self.assertEqual(window.asked, [])

    def test_with_a_python_of_yours_only_the_missing_model_is_named(self) -> None:
        rows = self._rows(libraries=False)
        rows[0] = DependencyStatus("Speech recognition", "ready", key=dependencies.SPEECH_ROW, found_by=FOUND_ON_PC)
        needs = self._window(rows).speech_setup_needs()
        self.assertEqual(needs, {"libraries": False, "repair": False, "yours": True, "models": ["base.en"],
                                 "bytes": speech_setup.VOICE_MODEL_BYTES})
        from media_manglers_workbench.app import WorkbenchWindow

        text = WorkbenchWindow.speech_setup_question(needs)
        self.assertIn("base.en (about 145 MB)", text)
        self.assertNotIn("Python Package Index", text)

    def test_nothing_missing_means_no_question(self) -> None:
        window = self._window(self._rows(libraries=False, voice=VALID))
        self.assertIsNone(window.speech_setup_needs())
        self.assertFalse(window.offer(first_launch=True))
        self.assertEqual(window.asked, [])

    def test_a_damaged_base_en_is_left_to_its_own_approval(self) -> None:
        window = self._window(self._rows(libraries=False, voice="damaged"))
        self.assertIsNone(window.speech_setup_needs())

    def test_a_run_from_the_source_has_no_setup_of_its_own(self) -> None:
        (self.app / "runtime" / "python" / "python.exe").unlink()
        window = self._window(self._rows())
        self.assertIsNone(window.speech_setup_needs())

    def test_with_our_own_python_set_up_only_base_en_is_named_and_nothing_false_is_said(self) -> None:
        rows = self._rows(libraries=False)
        rows[0] = DependencyStatus("Speech recognition", "ready", key=dependencies.SPEECH_ROW, found_by=FOUND_DOWNLOADED)
        needs = self._window(rows).speech_setup_needs()
        self.assertFalse(needs["yours"])
        from media_manglers_workbench.app import WorkbenchWindow

        text = WorkbenchWindow.speech_setup_question(needs)
        self.assertIn("base.en (about 145 MB)", text)
        self.assertNotIn("Your own Python", text)

    def test_a_set_that_no_longer_loads_is_offered_again_as_a_repair(self) -> None:
        rows = self._rows()
        rows[0] = DependencyStatus("Speech recognition", "needs_setup", key=dependencies.SPEECH_ROW,
                                   found_by=FOUND_DOWNLOADED, model_state="damaged")
        window = self._window(rows)
        needs = window.speech_setup_needs()
        self.assertTrue(needs["repair"])
        from media_manglers_workbench.app import WorkbenchWindow

        self.assertIn("again", WorkbenchWindow.speech_setup_question(needs))
        window.offer()
        window.start_speech_setup.assert_called_once_with(libraries=True, models=["base.en"], repair=True, yours=False)

    def test_not_now_is_the_default_answer(self) -> None:
        from PySide6.QtWidgets import QApplication, QMessageBox

        from media_manglers_workbench import app as app_module
        from media_manglers_workbench.app import WorkbenchWindow

        QApplication.instance() or QApplication([])
        seen: dict[str, object] = {}

        def capture(box):
            seen["default"] = box.defaultButton().text()
            seen["escape"] = box.escapeButton().text()
            return 0

        with mock.patch.object(QMessageBox, "exec", capture):
            answer = WorkbenchWindow._ask_speech_setup(None, "question")
        self.assertEqual((seen["default"], seen["escape"], answer), ("Not now", "Not now", False))

    def test_set_up_while_the_setup_runs_says_so(self) -> None:
        window = self._window(self._rows(), speech_setup_thread=object())
        self.assertFalse(window.offer())
        self.assertIn("being set up now", window.dependency_summary.setText.call_args.args[0])
        self.assertEqual(window.asked, [])

    def test_one_download_job_at_a_time(self) -> None:
        from media_manglers_workbench.app import WorkbenchWindow

        window = self._window(self._rows(), model_download_thread=object())
        self.assertFalse(window.offer(first_launch=True), "the start-up question waits for the model download")
        self.assertFalse(WorkbenchWindow.start_speech_setup(window, libraries=True, models=["base.en"]))
        self.assertIn("model download is running", window.dependency_summary.setText.call_args.args[0])
        setup = self._window(self._rows(), speech_setup_thread=object(), model_download_thread=None)
        self.assertFalse(WorkbenchWindow.start_model_download(setup, ["base.en"]))
        self.assertIn("being set up now", setup.dependency_summary.setText.call_args.args[0])

    def test_every_feature_that_makes_a_transcript_refuses_in_one_plain_line(self) -> None:
        from media_manglers_workbench import app as app_module
        from media_manglers_workbench.app import WorkbenchWindow

        window = self._window(self._rows())
        window.runner_thread = None
        window.speech_blockers = types.MethodType(WorkbenchWindow.speech_blockers, window)
        self.assertEqual(len(window.speech_blockers()), 1)
        self.assertIn("Set up", window.speech_blockers()[0])
        for kind in sorted(app_module.SPEECH_RUN_KINDS):
            with self.subTest(kind=kind), mock.patch.object(app_module, "warn") as warned:
                started = WorkbenchWindow.start_external_run(window, mock.Mock(), title="t", settings={},
                                                             queue_items=["a.mkv"], listener=None, kind=kind)
                self.assertFalse(started)
                self.assertIn("Set up", warned.call_args.args[2])
        ready = self._window(self._rows(libraries=False, voice=VALID))
        self.assertEqual(WorkbenchWindow.speech_blockers(ready), [])

    def test_the_whisper_rows_offer_set_up_and_not_a_download_page(self) -> None:
        from media_manglers_workbench.tool_sources import needs_download

        row = DependencyStatus("Local Whisper", "needs_setup", key="whisper", action_kind="speech_setup")
        self.assertFalse(needs_download(row))
        self.assertTrue(needs_download(DependencyStatus("Local Whisper", "needs_setup", key="whisper",
                                                        action_kind="install_guide")))

    def test_the_setup_runs_in_our_own_python(self) -> None:
        from media_manglers_workbench import app as app_module
        from media_manglers_workbench.app import WorkbenchWindow

        window = self._window(self._rows())
        window._download_runner = types.MethodType(WorkbenchWindow._download_runner, window)
        window.setup_banner = mock.Mock()
        window._show_speech_setup = types.MethodType(WorkbenchWindow._show_speech_setup, window)
        window.SPEECH_SETUP_TOKEN, window.SPEECH_SETUP_TITLE = WorkbenchWindow.SPEECH_SETUP_TOKEN, "Setting up"
        started = mock.Mock()
        with mock.patch.object(app_module, "SpeechSetupThread", started):
            self.assertTrue(WorkbenchWindow.start_speech_setup(window, libraries=True, models=["base.en"]))
        argv = started.call_args.args[0]
        self.assertEqual(Path(argv[0]), self.app / "runtime" / "python" / "python.exe")
        self.assertIn("speech-setup", argv)
        self.assertEqual(started.call_args.kwargs, {"libraries": True, "models": ["base.en"], "repair": False})
        started.return_value.start.assert_called_once()
        self.assertEqual(window.setup_banner.show_job.call_args.args[0].token, "speech-setup")


class JobThreadTests(unittest.TestCase):
    def test_the_setup_job_reports_progress_and_its_result(self) -> None:
        from PySide6.QtWidgets import QApplication

        from media_manglers_workbench.app import SpeechSetupThread

        QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            script = textwrap.dedent(f"""
                import json, pathlib, time
                work = pathlib.Path({str(work)!r})
                request = json.loads((work / "request.json").read_text(encoding="utf-8"))
                assert request["payload"]["libraries"] is True and request["payload"]["models"] == ["base.en"]
                (work / "progress.json").write_text(json.dumps({{"stage": "download", "percent": 40,
                    "text": "Downloading the speech libraries: 80 MB of 197 MB"}}))
                time.sleep(0.8)
                (work / "result.json").write_text(json.dumps({{"ok": True, "data": {{"models": [
                    {{"name": "base.en", "reused": True}}]}}}}))
                """)
            thread = SpeechSetupThread([sys.executable, "-c", script], work / "request.json", work / "result.json",
                                       work / "progress.json", libraries=True, models=["base.en"])
            seen: list[tuple[str, int | None]] = []
            finished: list[tuple[bool, str]] = []
            thread.progress_changed.connect(lambda text: seen.append((text, thread.percent)))
            thread.download_finished.connect(lambda ok, message: finished.append((ok, message)))
            thread.start()
            deadline = time.monotonic() + 30
            while thread.isRunning() and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.05)
            self.assertTrue(thread.wait(5000))
            QApplication.processEvents()
        self.assertIn(("Downloading the speech libraries: 80 MB of 197 MB", 40), seen)
        self.assertEqual(finished, [(True, "Speech recognition is set up. The Whisper model base.en already on this "
                                           "PC was used as it is.")])

    def test_the_banner_floats_over_every_page_below_the_missing_tools_notice(self) -> None:
        from PySide6.QtWidgets import QApplication, QLabel, QWidget

        from media_manglers_workbench.ui_parts import JobBanner, JobInfo, float_at_top

        QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QVBoxLayout

        page = QWidget()
        page.resize(800, 600)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Media review workbench")
        layout.addWidget(title)
        layout.addStretch(1)
        notice = QLabel("Missing: FFmpeg", page)
        notice.setGeometry(0, 0, 800, 30)
        banner = JobBanner(page, link_text="Open Settings > Dependencies")
        float_at_top(banner, below=notice, reserve=layout)
        page.show()
        banner.show_job(JobInfo(token="speech-setup", title="Downloading the speech libraries", percent=10))
        QApplication.processEvents()
        self.assertEqual((banner.y(), banner.width()), (30, 800))
        self.assertGreaterEqual(title.y(), banner.y() + banner.height(), "the page's title is not covered")
        notice.hide()
        QApplication.processEvents()
        self.assertEqual(banner.y(), 0)
        page.resize(1000, 600)
        QApplication.processEvents()
        self.assertEqual(banner.width(), 1000)
        # A long failure message: the banner grows to show it, and the pages move down with it.
        short = banner.height()
        banner.show_job(JobInfo(token="speech-setup", title="Setting up speech recognition", state="attention",
                                detail="The speech library torch could not be downloaded from files.pythonhosted.org: "
                                       + "a long reason " * 40))
        QApplication.processEvents()
        QApplication.processEvents()
        self.assertGreater(banner.height(), short)
        self.assertGreaterEqual(banner.height(), banner.heightForWidth(banner.width()))
        self.assertGreaterEqual(title.y(), banner.y() + banner.height())
        self.assertIn("a long reason", banner.numbers_label.toolTip())
        banner.dismiss()
        QApplication.processEvents()
        self.assertEqual(layout.contentsMargins().top(), 0, "no room is kept once the banner is gone")
        page.close()


if __name__ == "__main__":
    unittest.main()
