"""Settings shared by the whole test suite.

127: the apps put their folders in the user's own Videos and Music folders and refuse to write
results into a temp folder. Tests must never touch a real user's folders, and their throw-away output
lives in temp folders, so for the whole run the user folders point at a scratch folder and temp output
is allowed. Tests of those rules set or clear the variables themselves.

196: the suite never writes to the system temp folder. When this repository's AREA51\\TEMP folder
exists, TEMP, TMP, TMPDIR, tempfile and MEDIA_MANGLERS_SCRATCH_ROOT point at AREA51\\TEMP\\pytest-scratch
for the whole run, and every process a test starts inherits that. Without AREA51 (outside this
checkout) the normal temp folder is used. MEDIA_MANGLERS_TESTS_SYSTEM_TEMP keeps the temp folder the
run started with, so a test can check that nothing was left there.
"""

from __future__ import annotations

import atexit
import gc
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

# The fixture below looks at the backend's own module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SYSTEM_TEMP_ENV = "MEDIA_MANGLERS_TESTS_SYSTEM_TEMP"
_AREA51_TEMP = Path(__file__).resolve().parents[1] / "AREA51" / "TEMP"

# A test process started by another keeps the first one's answer.
os.environ.setdefault(SYSTEM_TEMP_ENV, tempfile.gettempdir())
if _AREA51_TEMP.is_dir():
    _SCRATCH = _AREA51_TEMP / "pytest-scratch"
    _SCRATCH.mkdir(exist_ok=True)
    for _name in ("TEMP", "TMP", "TMPDIR", "MEDIA_MANGLERS_SCRATCH_ROOT"):
        os.environ[_name] = str(_SCRATCH)
    tempfile.tempdir = str(_SCRATCH)


@pytest.fixture(autouse=True)
def _each_test_its_own_library(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    """242, 243: every Workbench a test starts opens the library and keeps its runs there, so each test
    gets an empty library of its own, as each already gets a settings.json of its own. A test that points
    the library somewhere itself still does."""

    monkeypatch.setenv("MEDIA_MANGLERS_LIBRARY_ROOT", str(tmp_path_factory.mktemp("library")))
    yield
    # 224 (Wave B2b): the Inbox keeps one library connection per helper; a test's end lets it go, so the test's
    # own library folder can be removed.
    from media_manglers.core import inbox_records

    inbox_records.release_all()


_windows_waiting: set = set()


def _any_thread_running() -> bool:
    QThread = sys.modules["PySide6.QtCore"].QThread
    is_valid = sys.modules["shiboken6"].isValid
    # A thread Qt has deleted may still have its Python object; it is not running.
    return any(isinstance(item, QThread) and is_valid(item) and item.isRunning() for item in gc.get_objects())


def _qt_application():
    widgets = sys.modules.get("PySide6.QtWidgets")
    return widgets.QApplication.instance() if widgets is not None else None


@pytest.fixture(autouse=True)
def _no_windows_left_behind():
    """224: a test's own windows are removed when it ends. Closing a window only hides it, and each new Workbench
    sets the application's theme, which every live widget in the process answers, so a process running many tests
    got slower with every window left: tests that took seconds took minutes, and one run spun for eleven hours.
    Windows made before the test (a class's shared one) stay. Removing a window whose thread still runs would end
    the process, so while any thread runs its windows wait for a later test's end."""

    application = _qt_application()
    before = (set(application.topLevelWidgets()) - _windows_waiting) if application is not None else set()
    yield
    application = _qt_application()
    if application is None:
        return
    application.processEvents()
    found = [item for item in application.topLevelWidgets() if item not in before and item.parent() is None]
    _windows_waiting.clear()
    if not found:
        return
    if _any_thread_running():
        _windows_waiting.update(found)
        return
    for item in found:
        item.deleteLater()
    core = sys.modules["PySide6.QtCore"]
    core.QCoreApplication.sendPostedEvents(None, core.QEvent.Type.DeferredDelete)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "inbox_moved: the test's library holds the Inbox's records (the one-time move is done; 224)")


@pytest.fixture(autouse=True)
def _inbox_records_moved(request: pytest.FixtureRequest, _each_test_its_own_library: None):
    """224 (Wave B2b): the Inbox opens nothing until its records have moved into the library. A test module
    marked ``inbox_moved`` gets a library already marked so (nothing to move), as the Workbench marks one at its
    first start when no ledger is named."""

    if request.node.get_closest_marker("inbox_moved") is not None:
        from tests import inbox_library

        inbox_library.ready()
    yield


@pytest.fixture(autouse=True)
def _test_scratch_is_not_this_repository(monkeypatch: pytest.MonkeyPatch):
    """The scratch folder sits inside this checkout, and the review relocation refuses any
    destination inside a git repository (196). That refusal is about the operator's repositories,
    not about where the tests keep their throw-away files, so the checkout holding the scratch
    folder is not counted. A repository a test makes inside the scratch folder still is."""

    if not _AREA51_TEMP.is_dir():
        yield
        return
    try:
        from media_manglers.core import review_relocation
    except ImportError:
        yield
        return
    real = review_relocation._repository_ancestor
    checkout = _AREA51_TEMP.parents[1].resolve()
    scratch = _SCRATCH.resolve()

    def ancestor(root: Path) -> Path | None:
        found = real(root)
        if found is not None and Path(found).resolve() == checkout and Path(root).resolve().is_relative_to(scratch):
            return None
        return found

    monkeypatch.setattr(review_relocation, "_repository_ancestor", ancestor)
    yield


_USER_FOLDERS = Path(tempfile.mkdtemp(prefix="mm-tests-user-folders-"))
atexit.register(shutil.rmtree, _USER_FOLDERS, True)

os.environ["MEDIA_MANGLERS_VIDEOS_FOLDER"] = str(_USER_FOLDERS / "Videos")
os.environ["MEDIA_MANGLERS_MUSIC_FOLDER"] = str(_USER_FOLDERS / "Music")
os.environ["MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT"] = "1"
# 220: the raw bin library of a test run lives in a scratch folder, never the real one.
os.environ["MEDIA_MANGLERS_LIBRARY_ROOT"] = str(_USER_FOLDERS / "raw-bin-library")
os.environ["MEDIA_MANGLERS_CACHE_ROOT"] = str(_USER_FOLDERS / "cache")
# 226: the Workbench's saved settings (the settings.json core reads through
# whisper_options.read_saved_settings) come from a scratch folder, never the operator's own. A test, or
# a test process started by another with its own value, keeps that value.
os.environ.setdefault("MEDIA_MANGLERS_WORKBENCH_APPDATA", str(_USER_FOLDERS / "workbench-appdata"))
# 226: and the Workbench's local app data (its logs and temporary files) too. A test that starts the
# Workbench without folders of its own wrote its "Workbench started" log into the real logs folder on
# every full run. The scratch folder is the run's own as well, even without this checkout's AREA51.
os.environ.setdefault("MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA", str(_USER_FOLDERS / "workbench-localappdata"))
os.environ.setdefault("MEDIA_MANGLERS_SCRATCH_ROOT", str(_USER_FOLDERS / "scratch"))
# 226: the AI Video Editor's privacy masks come from an empty store of the run's own, never the
# operator's: every editor command reads the stored masks itself now. A test that needs masks points
# this at a store of its own; a test process started by another keeps that one's value.
os.environ.setdefault("MEDIA_MANGLERS_RACE_VIDEO_PRIVACY", str(_USER_FOLDERS / "race-video-privacy"))
# No watched recordings folders unless a test names some: never the operator's saved ones.
os.environ["MEDIA_MANGLERS_RECORDINGS_FOLDERS"] = ""

# 226: a test that swaps modules in sys.modules for one block (mock.patch.dict, for a fake Whisper)
# also removes, on the way out, every module first imported inside that block. numpy cannot be loaded
# twice in one process, so a numpy first imported there broke every later test in that process. It is
# imported here, before any test runs, so such a block always finds it already loaded and keeps it.
try:
    import numpy  # noqa: F401
except ImportError:  # pragma: no cover - the test runtime ships numpy
    pass
