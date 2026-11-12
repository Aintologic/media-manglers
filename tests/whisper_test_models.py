"""Whisper models for tests (installer plan, Stage 3).

Every feature loads a model through the one approval check (``whisper_local.load_whisper_model``): only a model
already in the Whisper cache and matching the SHA-256 in Whisper's own model table is loaded. A test that replaces
Whisper with a stand-in wraps it in ``checked_whisper``: the stand-in gets a model table, and each model it may be
asked for is put in the test run's own model cache (a scratch folder, see ``conftest.py``) with that checksum, as
on a PC where the operator approved it. Stage 3's own tests use ``install_models`` for missing and damaged ones.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable

from media_manglers.core import whisper_models

NAMES = ("tiny.en", "tiny", "base.en", "base", "small.en", "small", "medium.en", "medium", "large-v1", "large-v2",
         "large-v3", "large", "large-v3-turbo", "turbo")


def model_bytes(name: str) -> bytes:
    return f"test model {name}".encode("utf-8")


def install_models(names: Iterable[str] = NAMES, *, damaged: Iterable[str] = (),
                   missing: Iterable[str] = ()) -> dict[str, str]:
    """A model table for ``names``, with each model's file in the test cache: right, ``damaged`` or ``missing``."""

    damaged, missing = set(damaged), set(missing)
    cache = whisper_models.cache_dir()
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
