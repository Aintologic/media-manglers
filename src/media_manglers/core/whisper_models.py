"""Whisper models on this PC: whether each is there and is the file Whisper published (installer plan, Stage 3).

No feature downloads a Whisper model without the operator's approval. The one check is in
``whisper_local.load_whisper_model``, the one place every feature loads a model: a model file already in the
Whisper cache whose SHA-256 matches the one in Whisper's own model address is loaded as it is, with no download
and no question; otherwise ``ModelNotApproved`` is raised and Whisper is never called, so it cannot download a
model by itself, and a file that does not match is never silently replaced. A download happens only when the
operator approves it, through ``download_model`` (the ``whisper-model-download`` helper command), which writes a
partial file, checks it against the published SHA-256 and only then puts it in place, by Stage 2's rules.

This holds whichever Python runs Whisper, ours or one of the operator's kept under an exception, because the
helper code that loads the model is always ours. Whisper's model table is read from Whisper itself: from the
loaded module when it is loaded, otherwise from its installed source, without importing it (importing Whisper
loads PyTorch).
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse

from . import safe_write

VALID, MISSING, DAMAGED, UNKNOWN = "valid", "missing", "damaged", "unknown"
PARTIAL_SUFFIX = ".mm-partial"


class ModelNotApproved(Exception):
    """The model is not on this PC as Whisper published it, and only the operator's approval downloads it."""

    def __init__(self, model: str, state: str, path: str = "") -> None:
        self.model, self.state, self.path = model, state, path
        super().__init__(not_approved_message(model, state, path))


def not_approved_message(model: str, state: str, path: str = "") -> str:
    if state == DAMAGED:
        return (f"The Whisper model {model} on this PC does not match the file Whisper published, so it was not used. "
                f"It is never replaced without your approval: approve its download in Settings > Dependencies, then "
                f"try again. ({path})")
    if state == UNKNOWN:
        return f"{model} is not a model this Whisper knows. Choose another Whisper model in Settings."
    return (f"The Whisper model {model} is not on this PC yet, and Media Manglers downloads a model only after you "
            f"approve it. Approve its download in Settings > Dependencies, then try again.")


@dataclass(frozen=True, slots=True)
class ModelState:
    name: str
    state: str
    path: str = ""
    size: int = 0
    sha256: str = ""
    url: str = ""

    @property
    def valid(self) -> bool:
        return self.state == VALID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Whisper's own model table ------------------------------------------------------------------------------------


def model_table(whisper_module: Any = None) -> dict[str, str]:
    """Whisper's model names and download addresses, from Whisper itself; {} when Whisper is not there."""

    module = whisper_module if whisper_module is not None else sys.modules.get("whisper")
    models = getattr(module, "_MODELS", None) if module is not None else None
    if isinstance(models, dict):
        return {str(name): str(url) for name, url in models.items()}
    return _table_from_source()


def _table_from_source() -> dict[str, str]:
    try:
        spec = importlib.util.find_spec("whisper")
    except (ImportError, ValueError, AttributeError):
        return {}
    if spec is None or not spec.origin or not str(spec.origin).endswith(".py"):
        return {}
    try:
        tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "_MODELS" for target in targets) and node.value is not None:
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return {}
            return {str(name): str(url) for name, url in value.items()} if isinstance(value, dict) else {}
    return {}


def cache_dir() -> Path:
    """Where Whisper keeps its models when it is not told otherwise, worked out exactly as Whisper does."""

    default = os.path.join(os.path.expanduser("~"), ".cache")
    return Path(os.getenv("XDG_CACHE_HOME", default)) / "whisper"


# Is it there, and is it right ----------------------------------------------------------------------------------

_verified: dict[tuple[str, int, int], str] = {}
_verified_lock = threading.Lock()


def _sha256(path: Path) -> str:
    stat = path.stat()
    key = (os.path.normcase(str(path)), int(stat.st_size), int(stat.st_mtime_ns))
    with _verified_lock:
        known = _verified.get(key)
    if known:
        return known
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    found = digest.hexdigest()
    with _verified_lock:
        _verified[key] = found
    return found


def model_state(name: str, *, table: dict[str, str] | None = None, root: str | os.PathLike[str] | None = None) -> ModelState:
    """Whether the model ``name`` is in the Whisper cache and matches the SHA-256 in Whisper's own address for it."""

    table = model_table() if table is None else table
    url = str(table.get(name) or "")
    if not url:
        return ModelState(name, UNKNOWN)
    parts = urlparse(url).path.split("/")
    expected = parts[-2] if len(parts) >= 2 else ""
    path = Path(root) if root is not None else cache_dir()
    path = path / os.path.basename(urlparse(url).path)
    if not path.is_file():
        return ModelState(name, MISSING, str(path), 0, expected, url)
    size = path.stat().st_size
    state = VALID if expected and _sha256(path) == expected.casefold() else DAMAGED
    return ModelState(name, state, str(path), int(size), expected, url)


def checked_model_file(name: str, *, table: dict[str, str] | None = None) -> Path:
    """The model's file when it is there and right; otherwise ``ModelNotApproved``."""

    found = model_state(name, table=table)
    if not found.valid:
        raise ModelNotApproved(name, found.state, found.path)
    return Path(found.path)


# The approved download ------------------------------------------------------------------------------------------


def _open(url: str, timeout: float) -> Any:
    import ssl  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    return urllib.request.urlopen(url, timeout=timeout, context=ssl.create_default_context())  # noqa: S310


def download_model(name: str, *, table: dict[str, str] | None = None, root: str | os.PathLike[str] | None = None,
                   opener: Callable[[str, float], Any] = _open,
                   progress: Callable[[int, int], None] | None = None) -> ModelState:
    """Download the approved model ``name`` into the Whisper cache, unless a valid copy is already there.

    Written to a partial file beside its final name, checked against the published SHA-256, and only then put in
    place (``safe_write.place_checked``, Stage 2's rules); a damaged copy is replaced only here, after approval."""

    found = model_state(name, table=table, root=root)
    if found.state == UNKNOWN:
        raise ValueError(not_approved_message(name, UNKNOWN))
    if found.valid:
        return found
    target = Path(found.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + PARTIAL_SUFFIX)
    budget = safe_write.StepBudget()
    if os.path.lexists(partial):
        safe_write.remove(partial, budget=budget)  # what an interrupted download left is never reused
    try:
        with opener(found.url, 60.0) as response, open(partial, "wb") as handle:
            total = int(getattr(response, "headers", {}).get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    safe_write.place_checked(partial, target, found.sha256, replace=found.state == DAMAGED, budget=safe_write.StepBudget())
    return model_state(name, table=table, root=root)


# Helper commands --------------------------------------------------------------------------------------------------


def status_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """``whisper-models``: the state of each named model. Reads only; never downloads."""

    table = model_table()
    names = [str(name) for name in payload.get("models") or [] if str(name).strip()]
    return {"cache_dir": str(cache_dir()), "models": [model_state(name, table=table).to_dict() for name in names]}


def download_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """``whisper-model-download``: download the models the operator approved (the approval dialog runs this)."""

    table = model_table()
    names = [str(name) for name in payload.get("models") or [] if str(name).strip()]
    progress_file = str(payload.get("progress_file") or "")
    results = []
    last = [0.0]
    for index, name in enumerate(names):
        def report(done: int, total: int, name: str = name, index: int = index) -> None:
            # About twice a second, and once at the end: the Workbench reads it for its job banner.
            now = time.monotonic()
            if not progress_file or (now - last[0] < 0.5 and done != total):
                return
            last[0] = now
            try:
                safe_write.write_json(progress_file, {"model": name, "index": index, "count": len(names),
                                                      "done": done, "total": total})
            except OSError:
                pass

        results.append(download_model(name, table=table, progress=report).to_dict())
    return {"cache_dir": str(cache_dir()), "models": results}
