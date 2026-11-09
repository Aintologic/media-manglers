"""The one "same recording" rule (220), shared by Review Media Inbox and the raw bin library.

A recording is known by its content, not its path, so its tags follow it when it is renamed or moved:

- An unchanged file (same path, size and modified time) is not read at all.
- The sampled hash (the size plus three 64 KB pieces: the start, the middle and the end) is cheap and
  proposes a match. It never decides one on its own.
- The full SHA-256 of the whole file confirms it. Two live copies with the same content stay two
  entries.

The raw bin reads each file from the recordings drive at most once per scan, so ``StreamingIdentity``
takes both hashes from the same bytes the audio decode reads: no second pass.

267: the AI Video Editor asks the same rule of two files on disk (``same_content``): is the path the
AI editor gave the project's own recording?
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable

SAMPLE_CHUNK_BYTES = 64 * 1024
READ_CHUNK_BYTES = 8 * 1024 * 1024


def sample_offsets(size: int, chunk_bytes: int = SAMPLE_CHUNK_BYTES) -> list[int]:
    return sorted({0, max(0, (size // 2) - (chunk_bytes // 2)), max(0, size - chunk_bytes)})


def _sampled_digest(size: int, pieces: list[tuple[int, bytes]]) -> str:
    digest = hashlib.sha256()
    digest.update(f"size:{size}\n".encode("ascii"))
    for offset, data in pieces:
        digest.update(f"offset:{offset};length:{len(data)}\n".encode("ascii"))
        digest.update(data)
    return digest.hexdigest()


def sampled_sha256_file(path: Path, *, chunk_bytes: int = SAMPLE_CHUNK_BYTES) -> str:
    """The sampled hash, reading only its three pieces."""

    size = int(Path(path).stat().st_size)
    pieces: list[tuple[int, bytes]] = []
    with Path(path).open("rb") as handle:
        for offset in sample_offsets(size, chunk_bytes):
            handle.seek(offset)
            pieces.append((offset, handle.read(chunk_bytes)))
    return _sampled_digest(size, pieces)


class StreamingIdentity:
    """Both hashes from one front-to-back read: feed every byte in order, then ``finish``."""

    def __init__(self, size: int, *, chunk_bytes: int = SAMPLE_CHUNK_BYTES) -> None:
        self.size = int(size)
        self.chunk_bytes = chunk_bytes
        self.position = 0
        self._full = hashlib.sha256()
        self._pieces = {offset: bytearray() for offset in sample_offsets(self.size, chunk_bytes)}

    def update(self, data: bytes) -> None:
        start = self.position
        end = start + len(data)
        self._full.update(data)
        for offset, piece in self._pieces.items():
            want_end = min(offset + self.chunk_bytes, self.size)
            if len(piece) >= want_end - offset or end <= offset or start >= want_end:
                continue
            take_from = max(offset + len(piece), start)
            piece.extend(data[take_from - start:min(end, want_end) - start])
        self.position = end

    @property
    def bytes_read(self) -> int:
        return self.position

    def finish(self) -> tuple[str, str]:
        """(sampled hash, full SHA-256). Raises when the file was not read exactly once, whole."""

        if self.position != self.size:
            raise RuntimeError(
                f"The recording changed or could not be read whole: read {self.position} of {self.size} bytes."
            )
        pieces = [(offset, bytes(piece)) for offset, piece in sorted(self._pieces.items())]
        return _sampled_digest(self.size, pieces), self._full.hexdigest()


def file_identity(path: Path, on_progress: Callable[[int, int], None] | None = None) -> tuple[str, str]:
    """(sampled hash, full SHA-256) of a file on disk, from one front-to-back read. ``on_progress`` hears the
    bytes read so far and the file's size after each piece (242, Wave C2: Prepare says how far it has got)."""

    path = Path(path)
    identity = StreamingIdentity(int(path.stat().st_size))
    with path.open("rb") as handle:
        while True:
            data = handle.read(READ_CHUNK_BYTES)
            if not data:
                break
            identity.update(data)
            if on_progress is not None:
                on_progress(identity.bytes_read, identity.size)
    return identity.finish()


def same_content(first: Path, second: Path) -> bool:
    """Whether two files on disk hold the same recording, by this rule: the same file under two names
    is; otherwise the size and the sampled hash propose a match, and only the full SHA-256 of both
    confirms it. The whole files are read only when the proposal holds. A file that is not there, or
    that changes while it is read, is not the same content."""

    first, second = Path(first), Path(second)
    try:
        if os.path.samefile(first, second):
            return True
        if first.stat().st_size != second.stat().st_size:
            return False
        if sampled_sha256_file(first) != sampled_sha256_file(second):
            return False
        return file_identity(first)[1] == file_identity(second)[1]
    except (OSError, RuntimeError):
        return False
