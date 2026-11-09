"""Build identity resolution for source and packaged Workbench runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from . import __version__


BUILD_IDENTITY_FILENAME = "workbench-build-identity.json"
PUBLIC_BUILD_IDENTITY_FILENAME = "BUILD_IDENTITY.json"
UNKNOWN_COMMIT = "UNKNOWN"
UNAVAILABLE = "Unavailable"


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    semantic_version: str
    file_version: str
    product_version: str
    full_commit: str
    short_commit: str
    build_timestamp_utc: str
    packaged: bool
    dirty: bool | None
    validation_label: str = ""

    @property
    def runtime_state(self) -> str:
        return "PACKAGED" if self.packaged else "SOURCE"

    @property
    def worktree_state(self) -> str:
        if self.dirty is True:
            return "DIRTY"
        if self.dirty is False:
            return "CLEAN"
        return "UNKNOWN"

    @property
    def friendly_version(self) -> str:
        return f"v{self.semantic_version}"

    @property
    def technical_identity(self) -> str:
        parts = [self.friendly_version, self.runtime_state, self.short_commit or UNKNOWN_COMMIT]
        parts.append(self.worktree_state)
        if self.validation_label:
            parts.append(self.validation_label)
        return " | ".join(parts)

    @property
    def display_identity(self) -> str:
        """Compatibility alias for the complete concise technical identity."""

        return self.technical_identity

    @property
    def diagnostic_text(self) -> str:
        return "\n".join(f"{label}: {value}" for label, value in self.details())

    def details(self) -> tuple[tuple[str, str], ...]:
        build_time = self.build_timestamp_utc or (UNAVAILABLE if self.packaged else "Not packaged (source run)")
        return (
            ("Semantic/display version", f"v{self.semantic_version}"),
            ("File version", self.file_version or UNAVAILABLE),
            ("Product version", self.product_version or UNAVAILABLE),
            ("Full Git commit SHA", self.full_commit or UNAVAILABLE),
            ("Short Git commit SHA", self.short_commit or UNKNOWN_COMMIT),
            ("Build date/time", build_time),
            ("Packaged/source-run state", self.runtime_state),
            ("Clean/dirty build state", self.worktree_state),
            ("Validation label", self.validation_label or "None"),
        )


def _fallback_identity(*, packaged: bool) -> BuildIdentity:
    return BuildIdentity(
        semantic_version=__version__,
        file_version=f"{__version__}.0",
        product_version=f"{__version__}.0",
        full_commit="",
        short_commit=UNKNOWN_COMMIT,
        build_timestamp_utc="" if packaged else "Not packaged (source run)",
        packaged=packaged,
        dirty=None,
    )


def _validated_commit(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", candidate) else ""


def _identity_from_payload(payload: dict[str, Any], *, packaged: bool) -> BuildIdentity:
    full_commit = _validated_commit(payload.get("full_git_commit"))
    short_commit = str(payload.get("short_git_commit") or "").strip().lower()
    if full_commit:
        short_commit = full_commit[:7]
    elif not re.fullmatch(r"[0-9a-fA-F]{7,12}", short_commit):
        short_commit = UNKNOWN_COMMIT
    dirty_value = payload.get("dirty")
    dirty = dirty_value if isinstance(dirty_value, bool) else None
    return BuildIdentity(
        semantic_version=str(payload.get("semantic_version") or __version__).lstrip("v"),
        file_version=str(payload.get("file_version") or f"{__version__}.0"),
        product_version=str(payload.get("product_version") or f"{__version__}.0"),
        full_commit=full_commit,
        short_commit=short_commit,
        build_timestamp_utc=str(payload.get("build_timestamp_utc") or ""),
        packaged=packaged,
        dirty=dirty,
        validation_label=str(payload.get("validation_label") or ""),
    )


def embedded_metadata_candidates() -> tuple[Path, ...]:
    candidates = [Path(__file__).resolve().with_name(BUILD_IDENTITY_FILENAME)]
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        candidates.append(Path(sys.executable).resolve().parent / PUBLIC_BUILD_IDENTITY_FILENAME)
    return tuple(candidates)


def load_packaged_build_identity(metadata_path: Path | None = None) -> BuildIdentity:
    candidates = (metadata_path,) if metadata_path is not None else embedded_metadata_candidates()
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return _identity_from_payload(payload, packaged=True)
    return _fallback_identity(packaged=True)


def _git_text(repo_root: Path, *arguments: str) -> tuple[bool, str]:
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return result.returncode == 0, result.stdout.strip()


def resolve_source_build_identity(repo_root: Path) -> BuildIdentity:
    commit_ok, commit_text = _git_text(repo_root, "rev-parse", "HEAD")
    full_commit = _validated_commit(commit_text) if commit_ok else ""
    status_ok, status_text = _git_text(repo_root, "status", "--porcelain=v1", "--untracked-files=normal")
    dirty = bool(status_text) if status_ok else None
    return BuildIdentity(
        semantic_version=__version__,
        file_version=f"{__version__}.0",
        product_version=f"{__version__}.0",
        full_commit=full_commit,
        short_commit=full_commit[:7] if full_commit else UNKNOWN_COMMIT,
        build_timestamp_utc="Not packaged (source run)",
        packaged=False,
        dirty=dirty,
    )


def resolve_build_identity(*, packaged: bool, repo_root: Path) -> BuildIdentity:
    if packaged:
        return load_packaged_build_identity()
    return resolve_source_build_identity(repo_root)
