"""Whisper models for tests (installer plan, Stage 3).

Every feature loads a model through the one approval check (``whisper_local.load_whisper_model``): only a model
already in the Whisper cache and matching the SHA-256 in Whisper's own model table is loaded. A test that replaces
Whisper with a stand-in wraps it in ``checked_whisper``: the stand-in gets a model table, and each model it may be
asked for is put in the test run's own model cache (a scratch folder, see ``conftest.py``) with that checksum, as
on a PC where the operator approved it. Stage 3's own tests use ``install_models`` for missing and damaged ones.
"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from media_manglers.core import whisper_models

# M16 of the Wave I-A review: the shared test setup (conftest.py) points Whisper's model cache at a scratch folder
# whose name starts with this; a test file run on its own, outside pytest, would otherwise write the tiny stand-in
# models over the operator's real ones. So the cache is moved to a scratch folder of its own here, and
# ``install_models`` refuses any other cache.
TEST_FOLDER_MARK = "mm-tests-user-folders-"
_SCRATCH = Path(__file__).resolve().parents[1] / "AREA51" / "TEMP" / "pytest-scratch"
if TEST_FOLDER_MARK not in os.environ.get("XDG_CACHE_HOME", ""):
    import atexit
    import shutil

    if _SCRATCH.parent.is_dir():
        _SCRATCH.mkdir(exist_ok=True)
    _OWN = Path(tempfile.mkdtemp(prefix=TEST_FOLDER_MARK, dir=str(_SCRATCH) if _SCRATCH.is_dir() else None))
    atexit.register(shutil.rmtree, _OWN, True)
    os.environ["XDG_CACHE_HOME"] = str(_OWN / "xdg-cache")


def _test_cache() -> Path:
    """The Whisper cache, when it is a test folder: the run's own, or a temporary folder a test made."""

    cache = whisper_models.cache_dir()
    resolved = cache.resolve()
    folders = [path.resolve() for path in (_SCRATCH, Path(tempfile.gettempdir())) if path.is_dir()]
    if TEST_FOLDER_MARK not in str(cache) and not any(resolved.is_relative_to(folder) for folder in folders):
        raise RuntimeError(f"The test models go only into a test folder's Whisper cache, never into {cache}.")
    return cache

NAMES = ("tiny.en", "tiny", "base.en", "base", "small.en", "small", "medium.en", "medium", "large-v1", "large-v2",
         "large-v3", "large", "large-v3-turbo", "turbo")


def model_bytes(name: str) -> bytes:
    return f"test model {name}".encode("utf-8")


def install_models(names: Iterable[str] = NAMES, *, damaged: Iterable[str] = (),
                   missing: Iterable[str] = ()) -> dict[str, str]:
    """A model table for ``names``, with each model's file in the test cache: right, ``damaged`` or ``missing``."""

    damaged, missing = set(damaged), set(missing)
    cache = _test_cache()
    cache.mkdir(parents=True, exist_ok=True)
    table: dict[str, str] = {}
    for name in names:
        data = model_bytes(name)
        table[name] = f"https://models.invalid/whisper/{sha256(data).hexdigest()}/{name}.pt"
        path = cache / f"{name}.pt"
        if name in missing:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(b"damaged " + data if name in damaged else data)
    return table


class CheckedWhisper:
    """A Whisper stand-in whose models are in the test cache and match its model table. Every other call goes to
    the stand-in; ``loads`` records each model loaded, with the folder it was loaded from."""

    def __init__(self, inner: Any, names: Iterable[str] = NAMES) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_MODELS", install_models(names))
        object.__setattr__(self, "loads", [])

    def load_model(self, name: str, device: Any = None, download_root: Any = None, **_options: Any) -> Any:
        self.loads.append((name, device, download_root))
        return self._inner.load_model(name, device)

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._inner, attribute)


def checked_whisper(inner: Any, names: Iterable[str] = NAMES) -> CheckedWhisper:
    return CheckedWhisper(inner, names)


def whisper_gets_file_names() -> Any:
    """A patch for tests whose Whisper stand-in answers by the file it is given (a chunk's name) or is given a fake
    sound file: Whisper gets the file name, as before H2 of the Wave I-A review. How the app really reads the sound
    for Whisper is proven in ``tests/test_whisper_never_starts_ffmpeg.py``."""

    from unittest import mock  # noqa: PLC0415

    from media_manglers.providers import whisper_local  # noqa: PLC0415

    return mock.patch.object(whisper_local, "whisper_audio", side_effect=lambda path, _ffmpeg="": str(path))
