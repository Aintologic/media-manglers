"""The one downloader Media Manglers uses for what it fetches from the internet (installer plan, Stage 4).

Everything the app downloads goes through ``download_file``: the speech libraries at first launch and every Whisper
model the operator approves. One way, with all of the care:

- only ``https`` addresses, and every certificate is checked through Windows' own certificate verification (the
  ``truststore`` package hands the connection's certificate chain to Windows, the same check Windows' own programs
  use, so a root certificate Windows has not fetched yet is fetched the way Windows always does). Verification is
  never turned off, and there is no second way to download: a connection Windows does not trust stops the
  download with a plain message, and nothing is switched silently to another tool;
- the bytes go to ``<name>.partial`` beside the final name, are flushed to the disk, are checked against the
  SHA-256 the file was pinned to, and only then are given their name (``safe_write.place_checked``, the new file
  steps' rules from Stage 2). A file that does not match is removed and never looks like the real one;
- what an interrupted download left is never reused; a short network failure is tried again a few times.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import ssl
import sys
import time
from typing import Any, Callable
from urllib.parse import urlparse

from . import safe_write

PARTIAL_SUFFIX = ".partial"
CHUNK_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 60.0
ATTEMPTS = 3
USER_AGENT = "MediaManglers"
# What the result files and the readiness rows call the certificate check.
WINDOWS_CHECK = "Windows certificate verification"


class DownloadFailed(OSError):
    """A download did not finish: the network, the server or the certificate check stopped it. Nothing was put in
    place."""


class CertificateNotTrusted(DownloadFailed):
    """Windows did not trust the connection's certificate, so nothing was downloaded."""


Opener = Callable[[str, float], Any]
Progress = Callable[[int, int], None]


def tls_context() -> ssl.SSLContext:
    """A client context whose certificate check is done by the operating system's own verifier: on Windows,
    Windows' certificate verification. Without ``truststore`` the download is refused, never weakened."""

    try:
        import truststore  # noqa: PLC0415
    except ImportError as exc:
        raise DownloadFailed(
            "This Python cannot check download certificates through Windows (it has no truststore package), so "
            "nothing was downloaded. Media Manglers' own Python has it. When running from the source, install "
            "truststore into the Python in use (it is listed in pyproject.toml), then try again.") from exc
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return context


def verification() -> str:
    """How certificates are checked, in the words a result file records."""

    return WINDOWS_CHECK if sys.platform == "win32" else "the operating system's certificate verification"


def _https_only(url: str) -> None:
    if urlparse(url).scheme != "https":
        raise DownloadFailed(f"Media Manglers downloads only over a checked https connection; refused {url}.")


def open_url(url: str, timeout: float = TIMEOUT_SECONDS) -> Any:
    """Open ``url`` (https only, redirects included) for reading, with every certificate checked through Windows."""

    import urllib.request  # noqa: PLC0415

    class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, D102
            _https_only(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    _https_only(url)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls_context()), HttpsOnlyRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return opener.open(request, timeout=timeout)


def _causes(exc: BaseException) -> list[BaseException]:
    """``exc`` and the exceptions behind it (a URLError's reason, a cause, a context), never anything else."""

    found: list[BaseException] = []
    current: object = exc
    while isinstance(current, BaseException) and current not in found and len(found) < 8:
        found.append(current)
        reason = getattr(current, "reason", None)
        current = reason if isinstance(reason, BaseException) else (current.__cause__ or current.__context__)
    return found


def _is_certificate_problem(exc: BaseException) -> bool:
    return any(isinstance(item, ssl.SSLCertVerificationError)
               or (isinstance(item, ssl.SSLError) and "CERTIFICATE" in str(item).upper()) for item in _causes(exc))


def is_disk_full(exc: BaseException) -> bool:
    import errno  # noqa: PLC0415

    return any(isinstance(item, OSError) and (item.errno == errno.ENOSPC or getattr(item, "winerror", None) in (39, 112))
               for item in _causes(exc))


def _host(url: str) -> str:
    return urlparse(url).hostname or url


def _plain_failure(exc: BaseException, url: str, name: str) -> DownloadFailed:
    if is_disk_full(exc):
        return DownloadFailed(f"{name} was not downloaded: the disk is full. Nothing was put in place. Free some "
                              "space, then try again.")
    if _is_certificate_problem(exc):
        return CertificateNotTrusted(
            f"{name} was not downloaded: Windows did not trust the certificate of {_host(url)}, so the connection "
            f"was refused and nothing was saved. Check the PC's date and time and the network connection, then try "
            f"again. ({exc})")
    return DownloadFailed(
        f"{name} could not be downloaded from {_host(url)}: {exc}. Nothing was put in place. Check the network "
        f"connection, then try again.")


def sha256_of(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_checked_copy(target: str | os.PathLike[str], sha256: str) -> bool:
    """Whether ``target`` is already there and matches ``sha256`` (a finished download is reused, never fetched
    twice)."""

    path = Path(target)
    try:
        return path.is_file() and sha256_of(path) == str(sha256 or "").strip().casefold()
    except OSError:
        return False


def _transient(exc: BaseException) -> bool:
    import http.client  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415

    if _is_certificate_problem(exc) or isinstance(exc, DownloadFailed):
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 429, 500, 502, 503, 504}
    return isinstance(exc, (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError))


def _fetch(url: str, partial: Path, *, opener: Opener, progress: Progress | None, size: int) -> int:
    done = 0
    with opener(url, TIMEOUT_SECONDS) as response, open(partial, "wb") as handle:
        headers = getattr(response, "headers", None) or {}
        total = int(headers.get("Content-Length") or 0) or size
        while True:
            chunk = response.read(CHUNK_BYTES)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
        handle.flush()
        os.fsync(handle.fileno())
    return done


def download_file(url: str, target: str | os.PathLike[str], sha256: str, *, size: int = 0, replace: bool = False,
                  name: str = "", opener: Opener = open_url, progress: Progress | None = None,
                  budget: safe_write.StepBudget | None = None, attempts: int = ATTEMPTS,
                  pause: Callable[[float], None] = time.sleep) -> Path:
    """Download ``url`` to ``target``: into ``<target>.partial``, checked against ``sha256`` (and ``size`` when
    given), and only then given its name. ``replace`` lets an approved download take the place of a damaged copy;
    otherwise a file already at ``target`` is never written over."""

    target = Path(target)
    name = name or target.name
    if not str(sha256 or "").strip():
        raise DownloadFailed(f"{name} has no pinned checksum, so it is not downloaded.")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + PARTIAL_SUFFIX)
    for attempt in range(1, max(1, attempts) + 1):
        if os.path.lexists(partial):
            # What an interrupted download left is never reused.
            safe_write.remove(partial, budget=safe_write.StepBudget())
        try:
            written = _fetch(url, partial, opener=opener, progress=progress, size=size)
            if size and written != size:
                raise DownloadFailed(f"{name} arrived with {written:,} bytes instead of {size:,}.")
        except BaseException as exc:  # noqa: BLE001 - every failure removes the partial file first
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if attempt < attempts and _transient(exc):
                pause(min(8.0, 2.0 ** attempt))
                continue
            if isinstance(exc, DownloadFailed):
                raise
            raise _plain_failure(exc, url, name) from exc
        break
    return safe_write.place_checked(partial, target, sha256, replace=replace,
                                    budget=budget or safe_write.StepBudget())
