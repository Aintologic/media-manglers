"""Crash-safe relocation of generated-owned Review Media Inbox paths.

The operation deliberately treats original-media locations as immutable.  It
rebounds only registered generated-owned fields after a separately completed
and verified storage migration.  Old roots are handled lexically so an absent
or unavailable old volume is never probed.

Since Wave B2b (224, Q6) the Inbox's records are in the library, in its ``inbox_`` tables. The tool reads and
changes only those tables, also moves the Inbox folder registered in the library, backs the library up with
SQLite's own backup call, and its rollback puts back only the rows its own plan changed, from the old values
the plan holds, in one transaction: no library file is ever copied back.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any, Callable, Iterable
import uuid

from . import inbox_records, recording_records, review_ledger, review_orchestration, review_preparation, review_queue, safe_write


# 2 (224, Wave B2b): the plan names the library's inbox_ tables; a plan made before cannot be applied.
PLAN_VERSION = 2
JOURNAL_VERSION = 1
RESULT_VERSION = 1
ACTION = "review_media_inbox_relocate"
ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
DERIVED_RELATIVE_PATHS = {
    review_queue.QUEUE_INDEX_NAME.casefold(),
    review_queue.QUEUE_PROMPT_NAME.casefold(),
    ".orchestration/process.lock",
}
TERMINAL_ATTEMPT_STATES = {
    "prepared",
    "needs_audio_confirmation",
    "retryable_failure",
    "source_changed",
    "cancelled",
    "completed",
}
FINALIZATION_TERMINAL_STATES = {"cleanup_complete"}
_T = review_ledger.INBOX_TABLES
# The library's structure step 5 makes this table (``review_ledger.RELOCATION_TABLE``).
RELOCATION_TABLE = review_ledger.RELOCATION_TABLE

DIRECT_PATH_COLUMNS: dict[tuple[str, str], str] = {
    (_T["reviews"], "original_path"): "original_media",
    (_T["reviews"], "normalized_original_path"): "original_media",
    (_T["reviews"], "kept_package_path"): "generated_owned",
    (_T["source_locations"], "original_path"): "original_media",
    (_T["source_locations"], "normalized_path"): "original_media",
    (_T["batches"], "package_path"): "generated_owned",
    (_T["finalization_runs"], "journal_path"): "generated_owned",
    (_T["retention_records"], "history_path"): "generated_owned",
    (_T["relocation_runs"], "journal_path"): "generated_owned",
    (_T["relocation_runs"], "backup_path"): "generated_owned",
}
PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    _T["reviews"]: ("ledger_id",),
    _T["source_locations"]: ("location_id",),
    _T["batches"]: ("batch_id",),
    _T["finalization_runs"]: ("plan_sha256",),
    _T["retention_records"]: ("plan_sha256", "source_id"),
    _T["relocation_runs"]: ("operation_id",),
}
AUDIT_JSON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (_T["sources"], "source_id", "migration_provenance"),
    (_T["findings"], "finding_id", "details_json"),
    (_T["lifecycle_events"], "event_id", "details_json"),
    (_T["final_results"], "result_id", "details_json"),
    (_T["final_results"], "result_id", "external_assertions_json"),
    (_T["relocation_runs"], "operation_id", "mappings_json"),
)


class RelocationError(RuntimeError):
    """Raised when relocation cannot continue without weakening safety."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_token(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:20] or "unknown"


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    # 224 (Wave B1): the one safe writer replaces the file, byte for byte as the plan pinned it.
    safe_write.write_bytes(path, content, wait=safe_write.INBOX_WAIT_SECONDS)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RelocationError(f"{label} is unreadable or malformed: {exc}.") from exc


def _windows_path(value: str, label: str) -> str:
    text = os.path.expandvars(os.path.expanduser(str(value or "").strip()))
    if not ABSOLUTE_WINDOWS_PATH.match(text):
        raise RelocationError(f"{label} must be an absolute Windows path.")
    return ntpath.normpath(text)


def _path_key(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value))


def _relative_windows(root: str, target: str) -> str | None:
    root_value = _windows_path(root, "Root")
    target_value = _windows_path(target, "Target")
    try:
        relative = ntpath.relpath(target_value, root_value)
    except ValueError:
        return None
    if relative == ".":
        return ""
    if ntpath.isabs(relative) or relative == ".." or relative.startswith(f"..{ntpath.sep}"):
        return None
    return ntpath.normpath(relative)


def _contained(root: str, target: str) -> bool:
    return _relative_windows(root, target) is not None


def _replace_root(value: str, mapping: dict[str, Any]) -> str:
    relative = _relative_windows(str(mapping["old_root"]), value)
    if relative is None:
        raise RelocationError("A generated path is not contained by its selected old root.")
    replacement = ntpath.normpath(ntpath.join(str(mapping["new_root"]), relative))
    if not _contained(str(mapping["new_root"]), replacement):
        raise RelocationError("A generated-path replacement escaped its approved destination root.")
    return replacement


def _mapping_for(value: str, mappings: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [mapping for mapping in mappings if _contained(str(mapping["old_root"]), value)]
    if len(matches) > 1:
        raise RelocationError("A generated path matches more than one old generated root.")
    return matches[0] if matches else None


def _new_mapping_for(value: str, mappings: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [mapping for mapping in mappings if _contained(str(mapping["new_root"]), value)]
    if len(matches) > 1:
        raise RelocationError("A generated path matches more than one replacement root.")
    return matches[0] if matches else None


def _original_root_for(value: str, roots: list[str]) -> str | None:
    matches = [root for root in roots if _contained(root, value)]
    if len(matches) > 1:
        matches.sort(key=len, reverse=True)
    return matches[0] if matches else None


def _is_reparse(stat_result: os.stat_result) -> bool:
    return bool(
        getattr(stat_result, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _require_regular_path(path: Path, *, directory: bool, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RelocationError(f"{label} is missing or unavailable.") from exc
    if path.is_symlink() or _is_reparse(info):
        raise RelocationError(f"{label} is a symbolic link or reparse point.")
    if directory and not path.is_dir():
        raise RelocationError(f"{label} is not a directory.")
    if not directory and not path.is_file():
        raise RelocationError(f"{label} is not a regular file.")


def _walk_files(root: Path) -> list[Path]:
    _require_regular_path(root, directory=True, label="Verified destination root")
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise RelocationError("The verified destination tree could not be enumerated.") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise RelocationError("A destination entry could not be inspected safely.") from exc
            if entry.is_symlink() or _is_reparse(info):
                raise RelocationError(
                    f"The verified destination contains a symbolic link or reparse point: {path.name}."
                )
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise RelocationError(
                    f"The verified destination contains a non-regular entry: {path.name}."
                )
    return sorted(files, key=lambda item: str(item).casefold())


def _relative_key(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise RelocationError("A destination file escaped the verified root.") from exc
    if relative in {"", ".", ".."} or relative.startswith("../"):
        raise RelocationError("A destination file has an unsafe relative path.")
    return relative.casefold()


def _is_derived(relative: str) -> bool:
    key = relative.replace("\\", "/").casefold()
    return key in DERIVED_RELATIVE_PATHS or key.startswith(".relocation/")


def _derived_runtime_snapshot(queue_root: Path) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for relative in sorted(DERIVED_RELATIVE_PATHS):
        if relative == ".orchestration/process.lock":
            snapshot.append(
                {
                    "relative_path": relative,
                    "disposition": "regenerate",
                }
            )
            continue
        path = queue_root / Path(relative)
        if path.exists() and not path.is_file():
            raise RelocationError(
                f"A derived runtime projection is not a regular file: {relative}."
            )
        snapshot.append(
            {
                "relative_path": relative,
                "disposition": "regenerate",
                "existed_before": path.is_file(),
                "before_sha256": _sha256_file(path) if path.is_file() else "",
            }
        )
    return snapshot


def _repository_ancestor(root: Path) -> Path | None:
    current = root
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _normalise_record_files(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_files = record.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise RelocationError("The migration record has no verified file inventory.")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise RelocationError("The migration record contains a malformed file entry.")
        relative = str(raw.get("relative_path") or raw.get("RelativePath") or "").strip()
        item = str(raw.get("Item") or "").strip()
        if item and item != ntpath.basename(relative):
            relative = ntpath.join(item, relative)
        relative = ntpath.normpath(relative)
        if (
            not relative
            or ntpath.isabs(relative)
            or relative == ".."
            or relative.startswith(f"..{ntpath.sep}")
        ):
            raise RelocationError("The migration record contains an escaping relative path.")
        key = relative.replace("\\", "/").casefold()
        if key in seen:
            raise RelocationError("The migration record repeats a destination file.")
        seen.add(key)
        size_value = raw.get("size_bytes", raw.get("SizeBytes"))
        digest = str(raw.get("sha256") or raw.get("Sha256") or "").lower()
        if (
            isinstance(size_value, bool)
            or not isinstance(size_value, int)
            or size_value < 0
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RelocationError("The migration record contains invalid size or SHA-256 metadata.")
        result.append(
            {
                "relative_path": relative.replace("\\", "/"),
                "size_bytes": size_value,
                "sha256": digest,
            }
        )
    return sorted(result, key=lambda item: item["relative_path"].casefold())


def _normalise_mappings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_mappings = payload.get("mappings")
    if not isinstance(raw_mappings, list) or not raw_mappings:
        raise RelocationError("One or more generated-root mappings are required.")
    roots = [
        _windows_path(str(value), "Original-media root")
        for value in payload.get("original_media_roots") or []
    ]
    if not roots:
        raise RelocationError("At least one original-media root is required.")
    repository_roots = [
        _windows_path(str(value), "Repository root")
        for value in payload.get("repository_roots") or []
    ]
    mappings: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_mappings):
        if not isinstance(raw, dict):
            raise RelocationError("A generated-root mapping is malformed.")
        old_root = _windows_path(str(raw.get("old_root") or ""), "Old generated root")
        new_root = _windows_path(str(raw.get("new_root") or ""), "New generated root")
        if _path_key(old_root) == _path_key(new_root):
            raise RelocationError("Old and new generated roots must differ.")
        if ntpath.splitdrive(new_root)[0].casefold() != "c:":
            raise RelocationError("Verified relocation destinations must be on the approved C volume.")
        if _contained(old_root, new_root) or _contained(new_root, old_root):
            raise RelocationError("Old and new generated roots overlap unsafely.")
        if any(_contained(root, new_root) or _contained(new_root, root) for root in roots):
            raise RelocationError("A generated destination overlaps an original-media root.")
        if any(_contained(root, new_root) or _contained(new_root, root) for root in repository_roots):
            raise RelocationError("A generated destination overlaps a repository.")
        new_path = Path(new_root)
        _require_regular_path(new_path, directory=True, label="New generated root")
        repository = _repository_ancestor(new_path)
        if repository is not None:
            raise RelocationError("A generated destination is inside a repository.")
        record_path = Path(
            _windows_path(
                str(raw.get("migration_record_path") or ""),
                "Migration record path",
            )
        )
        _require_regular_path(record_path, directory=False, label="Migration record")
        actual_record_sha = _sha256_file(record_path)
        expected_record_sha = str(raw.get("migration_record_sha256") or "").lower()
        if expected_record_sha and expected_record_sha != actual_record_sha:
            raise RelocationError("The migration-record SHA-256 does not match.")
        record = _read_json(record_path, "Migration record")
        if not isinstance(record, dict) or record.get("verified") is not True:
            raise RelocationError("The migration record is not marked verified.")
        record_old = _windows_path(str(record.get("source_root") or ""), "Migration-record source root")
        record_new = _windows_path(str(record.get("destination_root") or ""), "Migration-record destination root")
        if _path_key(record_old) != _path_key(old_root) or _path_key(record_new) != _path_key(new_root):
            raise RelocationError("The migration record does not identify the requested old and new roots.")
        mappings.append(
            {
                "mapping_index": index,
                "old_root": old_root,
                "new_root": new_root,
                "migration_record_path": str(record_path),
                "migration_record_sha256": actual_record_sha,
                "record_files": _normalise_record_files(record),
            }
        )
    for left_index, left in enumerate(mappings):
        for right in mappings[left_index + 1 :]:
            for left_root in (str(left["old_root"]), str(left["new_root"])):
                for right_root in (str(right["old_root"]), str(right["new_root"])):
                    if _contained(left_root, right_root) or _contained(right_root, left_root):
                        raise RelocationError("Generated-root mappings overlap one another.")
    return mappings


def _verify_migration_mapping(
    mapping: dict[str, Any],
    *,
    allowed_changed: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(str(mapping["new_root"]))
    expected = {
        str(item["relative_path"]).casefold(): item
        for item in mapping["record_files"]
        if not _is_derived(str(item["relative_path"]))
    }
    actual_files = _walk_files(root)
    actual = {
        _relative_key(root, path): path
        for path in actual_files
        if not _is_derived(path.relative_to(root).as_posix())
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        raise RelocationError(f"The verified destination is missing {len(missing)} recorded file(s).")
    if extra:
        raise RelocationError(f"The verified destination contains {len(extra)} prohibited extra file(s).")
    changed = {item.casefold() for item in allowed_changed or set()}
    verified_count = 0
    verified_bytes = 0
    for key, record in expected.items():
        if key in changed:
            continue
        path = actual[key]
        info = path.lstat()
        if info.st_size != int(record["size_bytes"]):
            raise RelocationError(f"A verified destination file has the wrong size: {record['relative_path']}.")
        if _sha256_file(path) != str(record["sha256"]):
            raise RelocationError(f"A verified destination file has the wrong SHA-256: {record['relative_path']}.")
        verified_count += 1
        verified_bytes += info.st_size
    return {
        "mapping_index": int(mapping["mapping_index"]),
        "record_file_count": len(expected),
        "verified_unchanged_file_count": verified_count,
        "verified_unchanged_bytes": verified_bytes,
        "allowed_changed_file_count": len(changed & set(expected)),
        "missing_file_count": 0,
        "extra_file_count": 0,
        "reparse_point_count": 0,
        "old_root_accessed": False,
    }


def _connect_read_only(_path: Path | None = None) -> sqlite3.Connection:
    # 224 (Wave B2b): the Inbox's records in the library, opened by the Inbox's store for this tool, which moves the
    # Inbox folder itself (so it is not held to the folder registered now).
    return inbox_records.relocation_connection()


def _schema_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _row_identity(row: sqlite3.Row, columns: Iterable[str]) -> dict[str, Any]:
    return {column: row[column] for column in columns}


def _walk_strings(value: Any, pointer: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _walk_strings(nested, (*pointer, str(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk_strings(nested, (*pointer, str(index)))
    elif isinstance(value, str) and ABSOLUTE_WINDOWS_PATH.match(value):
        yield pointer, value


def _inspect_ledger(
    ledger_path: Path,
    mappings: list[dict[str, Any]],
    original_roots: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    connection = _connect_read_only(ledger_path)
    changes: list[dict[str, Any]] = []
    classifications: list[dict[str, Any]] = []
    originals: list[dict[str, Any]] = []
    try:
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise RelocationError("The ledger failed SQLite integrity validation.")
        if inbox_records.link_problems(connection):
            raise RelocationError("The ledger has foreign-key violations.")
        if recording_records.stored_version(connection) < recording_records.SCHEMA_VERSION:
            raise RelocationError("Relocation requires the library holding Review Media Inbox's records.")
        tables = _schema_tables(connection)
        for table in sorted(tables):
            # 224 (Wave B2b): only the Inbox's own tables; the library's other tables are not relocated.
            if not table.startswith("inbox_"):
                continue
            columns = [
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            for column in columns:
                if "path" in column.casefold() and (table, column) not in DIRECT_PATH_COLUMNS:
                    raise RelocationError(
                        f"Unknown path-bearing ledger field: {table}.{column}."
                    )
        for (table, column), classification in DIRECT_PATH_COLUMNS.items():
            if table not in tables:
                continue
            keys = PRIMARY_KEYS[table]
            query_columns = [*keys, column]
            rows = connection.execute(
                f'SELECT {", ".join(query_columns)} FROM "{table}" ORDER BY {", ".join(keys)}'
            ).fetchall()
            for row in rows:
                value = str(row[column] or "").strip()
                if not value:
                    continue
                record = {
                    "surface": "ledger",
                    "record": f"{table}.{column}",
                    "keys": _row_identity(row, keys),
                    "classification": classification,
                }
                if classification == "original_media":
                    root = _original_root_for(value, original_roots)
                    if root is None:
                        raise RelocationError(
                            f"An original-media ledger field is outside the approved original roots: {table}.{column}."
                        )
                    record.update({"action": "unchanged", "root": root})
                    originals.append(
                        {
                            "record": f"{table}.{column}",
                            "keys": record["keys"],
                            "value": _path_key(value),
                        }
                    )
                else:
                    mapping = _mapping_for(value, mappings)
                    if mapping is not None:
                        replacement = _replace_root(value, mapping)
                        record.update(
                            {
                                "action": "relocate",
                                "mapping_index": int(mapping["mapping_index"]),
                            }
                        )
                        changes.append(
                            {
                                "table": table,
                                "keys": record["keys"],
                                "column": column,
                                "before": value,
                                "after": replacement,
                                "classification": classification,
                                "mapping_index": int(mapping["mapping_index"]),
                            }
                        )
                    else:
                        new_mapping = _new_mapping_for(value, mappings)
                        if new_mapping is None:
                            raise RelocationError(
                                f"A generated-owned ledger path is outside every approved mapping: {table}.{column}."
                            )
                        record.update(
                            {
                                "action": "already_relocated",
                                "mapping_index": int(new_mapping["mapping_index"]),
                            }
                        )
                classifications.append(record)
        for table, identity_column, json_column in AUDIT_JSON_COLUMNS:
            if table not in tables:
                continue
            rows = connection.execute(
                f'SELECT "{identity_column}", "{json_column}" FROM "{table}" ORDER BY "{identity_column}"'
            ).fetchall()
            for row in rows:
                text = str(row[json_column] or "").strip()
                if not text:
                    continue
                try:
                    document = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RelocationError(
                        f"Structured audit field {table}.{json_column} is malformed."
                    ) from exc
                for pointer, value in _walk_strings(document):
                    classifications.append(
                        {
                            "surface": "ledger_audit",
                            "record": f"{table}.{json_column}",
                            "keys": {identity_column: row[identity_column]},
                            "json_pointer": "/" + "/".join(pointer),
                            "classification": "historical_audit",
                            "action": "unchanged",
                            "root_kind": (
                                "original_media"
                                if _original_root_for(value, original_roots)
                                else "historical_generated_or_tooling"
                            ),
                        }
                    )
        schema_values = connection.execute(
            f"SELECT key, value FROM {_T['schema_metadata']} ORDER BY key"
        ).fetchall() if _T["schema_metadata"] in tables else []
        for row in schema_values:
            if ABSOLUTE_WINDOWS_PATH.match(str(row["value"] or "")):
                raise RelocationError(
                    f"Unknown path-bearing schema metadata field: {row['key']}."
                )
    finally:
        connection.close()
    original_sha = _canonical_sha(sorted(originals, key=lambda item: _canonical_sha(item)))
    return changes, classifications, {
        "record_count": len(originals),
        "sha256": original_sha,
    }


def _json_pointer_get(document: Any, pointer: tuple[str, ...]) -> Any:
    value = document
    for token in pointer:
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _json_pointer_set(document: Any, pointer: tuple[str, ...], replacement: Any) -> None:
    if not pointer:
        raise RelocationError("A JSON relocation patch cannot replace the document root.")
    value = document
    for token in pointer[:-1]:
        value = value[int(token)] if isinstance(value, list) else value[token]
    last = pointer[-1]
    if isinstance(value, list):
        value[int(last)] = replacement
    else:
        value[last] = replacement


def _run_original_pointer(pointer: tuple[str, ...]) -> bool:
    joined = "/".join(pointer)
    return bool(
        re.fullmatch(r"run/scan_settings/source_folders/\d+", joined)
        or re.fullmatch(r"run/snapshot/\d+/path", joined)
        or re.fullmatch(r"run/pending_resume/selected_sources/\d+/path", joined)
        or re.fullmatch(r"run/inflight_chunk/\d+/path", joined)
        or re.fullmatch(r"run/exact_source_restriction/requested_paths/\d+", joined)
        or re.fullmatch(r"run/exact_source_restriction/bound_sources/\d+/path", joined)
    )


def _document_family(relative: str) -> str:
    value = relative.replace("\\", "/").casefold()
    if value.startswith(".orchestration/") and value.endswith(".json"):
        return "run_journal"
    if value.startswith("history/"):
        return "retained_history"
    if re.fullmatch(r"batches/[^/]+/batch-manifest\.json", value):
        return "batch_manifest"
    if re.fullmatch(r"batches/[^/]+/sources/[^/]+/source-manifest\.json", value):
        return "source_manifest"
    if value.endswith("/attempt-state.json") and "/.staging/" in value:
        return "attempt_state"
    if "/.staging/targeted-evidence/" in value and value.endswith(".json"):
        return "targeted_plan"
    if "/.finalization/plan-" in value and value.endswith(".json"):
        return "finalization_plan"
    if "/.finalization/journal-" in value and value.endswith(".json"):
        return "finalization_journal"
    if "/.repairs/" in value and value.endswith("repair-journal.json"):
        return "repair_journal"
    if value in {review_queue.QUEUE_INDEX_NAME.casefold()}:
        return "derived_runtime"
    return "other"


def _render_document(
    document: dict[str, Any],
    *,
    family: str,
    patches: list[dict[str, Any]],
    operation_id: str,
    created_utc: str,
    mappings: list[dict[str, Any]],
) -> bytes:
    updated = deepcopy(document)
    for patch in patches:
        pointer = tuple(str(item) for item in patch["pointer"])
        if _json_pointer_get(updated, pointer) != patch["before"]:
            raise RelocationError("A planned JSON path no longer has its inspected value.")
        _json_pointer_set(updated, pointer, patch["after"])
    history = {
        "operation_id": operation_id,
        "relocated_utc": created_utc,
        "mappings": [
            {
                "old_root": str(mapping["old_root"]),
                "new_root": str(mapping["new_root"]),
            }
            for mapping in mappings
        ],
    }
    if family == "run_journal":
        run = updated.get("run")
        if not isinstance(run, dict):
            raise RelocationError("A run journal has no valid run document.")
        entries = run.setdefault("relocation_history", [])
        if not isinstance(entries, list):
            raise RelocationError("A run journal has malformed relocation history.")
        if not any(str(item.get("operation_id") or "") == operation_id for item in entries if isinstance(item, dict)):
            entries.append(history)
        updated["run_sha256"] = review_orchestration._sha256(run)
        return review_orchestration._canonical_bytes(updated)
    entries = updated.setdefault("relocation_history", [])
    if not isinstance(entries, list):
        raise RelocationError("A generated manifest has malformed relocation history.")
    if not any(str(item.get("operation_id") or "") == operation_id for item in entries if isinstance(item, dict)):
        entries.append(history)
    return json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _inspect_json_files(
    queue_root: Path,
    mappings: list[dict[str, Any]],
    original_roots: list[str],
    batch_states: dict[str, str],
    finalization_states: dict[str, str],
    operation_id: str,
    created_utc: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    file_changes: list[dict[str, Any]] = []
    classifications: list[dict[str, Any]] = []
    originals: list[dict[str, Any]] = []
    for path in _walk_files(queue_root):
        relative = path.relative_to(queue_root).as_posix()
        if _is_derived(relative) or path.suffix.casefold() != ".json":
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        family = _document_family(relative)
        strings = list(_walk_strings(document))
        if not strings:
            continue
        patches: list[dict[str, Any]] = []
        parts = relative.replace("\\", "/").split("/")
        batch_id = parts[1] if len(parts) > 2 and parts[0].casefold() == "batches" else ""
        for pointer, value in strings:
            classification = ""
            action = "unchanged"
            mapping: dict[str, Any] | None = None
            if family == "run_journal":
                if pointer == ("run", "scan_settings", "ledger_path"):
                    classification = "generated_owned"
                elif _run_original_pointer(pointer):
                    classification = "original_media"
                elif pointer[:2] == ("run", "relocation_history"):
                    classification = "historical_audit"
                else:
                    raise RelocationError(
                        f"Unknown path-bearing run-journal field: /{'/'.join(pointer)}."
                    )
            elif family == "batch_manifest":
                joined = "/".join(pointer)
                if re.fullmatch(r"prepared_sources/\d+/package_path", joined) or re.fullmatch(
                    r"finalization/history_destinations/\d+", joined
                ):
                    classification = "generated_owned"
                elif joined.startswith("relocation_history/"):
                    classification = "historical_audit"
                else:
                    raise RelocationError(
                        f"Unknown path-bearing batch-manifest field: /{joined}."
                    )
            elif family == "source_manifest":
                classification = (
                    "original_media"
                    if pointer == ("original_location",)
                    else "historical_audit"
                )
            elif family == "attempt_state":
                status_value = str(document.get("status") or "")
                if status_value not in TERMINAL_ATTEMPT_STATES:
                    raise RelocationError(
                        "Relocation is refused while a non-terminal preparation attempt contains a path."
                    )
                classification = "historical_audit"
            elif family == "targeted_plan":
                status_value = batch_states.get(batch_id, "")
                if status_value in {
                    "needs_manual_review",
                    "finalized_no_findings",
                    "finalized_with_findings",
                    "retryable_failure",
                }:
                    classification = "historical_audit"
                elif pointer in {("batch_path",), ("ledger_path",)}:
                    classification = "generated_owned"
                else:
                    raise RelocationError(
                        f"Unknown path-bearing targeted-evidence field: /{'/'.join(pointer)}."
                    )
            elif family == "finalization_plan":
                state = finalization_states.get(batch_id, "")
                if state not in FINALIZATION_TERMINAL_STATES:
                    raise RelocationError(
                        "Relocation is refused while finalization has not reached cleanup_complete."
                    )
                classification = "historical_audit"
            elif family in {
                "retained_history",
                "finalization_journal",
            }:
                classification = "historical_audit"
            elif family == "repair_journal":
                phase = str(document.get("phase") or document.get("status") or "")
                if phase not in {"complete", "completed", "promoted", "ledger_committed"}:
                    raise RelocationError(
                        "Relocation is refused while a package repair journal is active."
                    )
                classification = "historical_audit"
            else:
                raise RelocationError(
                    f"Unknown path-bearing JSON document: {relative}."
                )
            record = {
                "surface": "json",
                "record": relative,
                "json_pointer": "/" + "/".join(pointer),
                "classification": classification,
                "action": action,
            }
            if classification == "original_media":
                root = _original_root_for(value, original_roots)
                if root is None:
                    raise RelocationError(
                        f"An original-media JSON field is outside every approved original root: {relative}."
                    )
                record["root"] = root
                originals.append(
                    {
                        "record": relative,
                        "json_pointer": record["json_pointer"],
                        "value": _path_key(value),
                    }
                )
            elif classification == "generated_owned":
                mapping = _mapping_for(value, mappings)
                if mapping is not None:
                    replacement = _replace_root(value, mapping)
                    action = "relocate"
                    record.update(
                        {
                            "action": action,
                            "mapping_index": int(mapping["mapping_index"]),
                        }
                    )
                    patches.append(
                        {
                            "pointer": list(pointer),
                            "before": value,
                            "after": replacement,
                            "classification": classification,
                            "mapping_index": int(mapping["mapping_index"]),
                        }
                    )
                else:
                    mapping = _new_mapping_for(value, mappings)
                    if mapping is None:
                        raise RelocationError(
                            f"A generated-owned JSON field is outside every approved mapping: {relative}."
                        )
                    record.update(
                        {
                            "action": "already_relocated",
                            "mapping_index": int(mapping["mapping_index"]),
                        }
                    )
            classifications.append(record)
        if patches:
            before = path.read_bytes()
            after = _render_document(
                document,
                family=family,
                patches=patches,
                operation_id=operation_id,
                created_utc=created_utc,
                mappings=mappings,
            )
            file_changes.append(
                {
                    "path": str(path),
                    "relative_path": relative,
                    "family": family,
                    "before_sha256": _sha256_bytes(before),
                    "after_sha256": _sha256_bytes(after),
                    "patches": patches,
                }
            )
    return file_changes, classifications, originals


def _batch_states(ledger_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    connection = _connect_read_only(ledger_path)
    try:
        batches = {
            str(row["batch_id"]): str(row["status"] or "")
            for row in connection.execute(
                "SELECT batch_id, status FROM inbox_batches ORDER BY batch_id"
            )
        }
        finalizations = {
            str(row["batch_id"]): str(row["status"] or "")
            for row in connection.execute(
                "SELECT batch_id, status FROM inbox_finalization_runs ORDER BY batch_id"
            )
        }
        return batches, finalizations
    finally:
        connection.close()


def _known_exception_map(payload: dict[str, Any]) -> dict[tuple[str, int], dict[str, str]]:
    result: dict[tuple[str, int], dict[str, str]] = {}
    for raw in payload.get("known_package_integrity_exceptions") or []:
        if not isinstance(raw, dict):
            raise RelocationError("A known package-integrity exception is malformed.")
        batch_id = str(raw.get("batch_id") or "")
        source_id = raw.get("source_id")
        tree_sha = str(raw.get("tree_sha256") or "").lower()
        error_sha = str(raw.get("error_sha256") or "").lower()
        if (
            not batch_id
            or isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id < 1
            or len(tree_sha) != 64
            or len(error_sha) != 64
        ):
            raise RelocationError("A known package-integrity exception is incomplete.")
        result[(batch_id, source_id)] = {
            "tree_sha256": tree_sha,
            "error_sha256": error_sha,
        }
    return result


def _mapped_or_current(value: str, mappings: list[dict[str, Any]]) -> str:
    mapping = _mapping_for(value, mappings)
    if mapping is not None:
        return _replace_root(value, mapping)
    if _new_mapping_for(value, mappings) is not None:
        return ntpath.normpath(value)
    raise RelocationError("A generated package path is outside every approved mapping.")


def _verify_packages(
    ledger_path: Path,
    mappings: list[dict[str, Any]],
    exceptions: dict[tuple[str, int], dict[str, str]],
) -> dict[str, Any]:
    connection = _connect_read_only(ledger_path)
    package_records: list[dict[str, Any]] = []
    used_exceptions: set[tuple[str, int]] = set()
    try:
        batches = connection.execute(
            "SELECT batch_id, package_path FROM inbox_batches ORDER BY batch_id"
        ).fetchall()
        for batch in batches:
            batch_id = str(batch["batch_id"])
            batch_root = Path(_mapped_or_current(str(batch["package_path"]), mappings))
            _require_regular_path(batch_root, directory=True, label="Relocated batch package")
            manifest_path = batch_root / "batch-manifest.json"
            _require_regular_path(manifest_path, directory=False, label="Batch manifest")
            manifest = _read_json(manifest_path, "Batch manifest")
            if not isinstance(manifest, dict) or str(manifest.get("batch_id") or "") != batch_id:
                raise RelocationError("A destination batch manifest has the wrong package identity.")
            prepared = manifest.get("prepared_sources")
            if not isinstance(prepared, list):
                raise RelocationError("A destination batch has no prepared-source inventory.")
            ledger_sources = {
                int(row["source_id"]): row
                for row in connection.execute(
                    """
                    SELECT bs.source_id, bs.ordinal, s.stable_identity
                    FROM inbox_batch_sources bs
                    JOIN inbox_sources s ON s.source_id = bs.source_id
                    WHERE bs.batch_id = ? ORDER BY bs.ordinal
                    """,
                    (batch_id,),
                ).fetchall()
            }
            manifest_ids = {
                int(item.get("source_id"))
                for item in prepared
                if isinstance(item, dict)
                and isinstance(item.get("source_id"), int)
                and not isinstance(item.get("source_id"), bool)
            }
            if manifest_ids != set(ledger_sources):
                raise RelocationError("A destination package is unrelated to its ledger batch identity.")
            for item in prepared:
                if not isinstance(item, dict):
                    raise RelocationError("A destination batch source record is malformed.")
                source_id = int(item["source_id"])
                package_value = _mapped_or_current(str(item.get("package_path") or ""), mappings)
                source_root = Path(package_value)
                expected_root = batch_root / "sources" / str(item.get("source_token") or source_root.name)
                if _path_key(str(source_root)) != _path_key(str(expected_root)):
                    raise RelocationError("A destination source package is outside its batch or has the wrong identity.")
                _require_regular_path(source_root, directory=True, label="Prepared source package")
                tree_sha = review_preparation._tree_sha256(source_root)
                status = "valid"
                error = ""
                try:
                    review_preparation._validate_source_package(source_root)
                except Exception as exc:
                    status = "known_invalid"
                    error = f"{type(exc).__name__}: {exc}"
                    expected = exceptions.get((batch_id, source_id))
                    if (
                        expected is None
                        or expected["tree_sha256"] != tree_sha
                        or expected["error_sha256"] != _sha256_bytes(error.encode("utf-8"))
                    ):
                        raise RelocationError(
                            "A destination prepared package is internally inconsistent beyond an exact approved exception."
                        ) from exc
                    review_preparation._validate_salvageable_source_package(source_root)
                    used_exceptions.add((batch_id, source_id))
                package_records.append(
                    {
                        "batch_id": batch_id,
                        "source_id": source_id,
                        "source_token": source_root.name,
                        "tree_sha256": tree_sha,
                        "integrity_status": status,
                        "integrity_error_sha256": (
                            _sha256_bytes(error.encode("utf-8")) if error else ""
                        ),
                    }
                )
    finally:
        connection.close()
    unused = sorted(set(exceptions) - used_exceptions)
    if unused:
        raise RelocationError("A supplied package-integrity exception did not match an actual destination defect.")
    return {
        "source_package_count": len(package_records),
        "known_invalid_package_count": len(used_exceptions),
        "packages": package_records,
    }


def _operation_seed(
    ledger_path: Path,
    mappings: list[dict[str, Any]],
    original_roots: list[str],
    exceptions: dict[tuple[str, int], dict[str, str]],
) -> str:
    return _canonical_sha(
        {
            "ledger_path": _path_key(str(ledger_path)),
            "mappings": [
                {
                    "old_root": _path_key(str(item["old_root"])),
                    "new_root": _path_key(str(item["new_root"])),
                    "migration_record_sha256": item["migration_record_sha256"],
                }
                for item in mappings
            ],
            "original_media_roots": [_path_key(item) for item in original_roots],
            "known_package_integrity_exceptions": [
                {
                    "batch_id": key[0],
                    "source_id": key[1],
                    **exceptions[key],
                }
                for key in sorted(exceptions)
            ],
        }
    )


def _plan_path(queue_root: Path, operation_id: str) -> Path:
    return queue_root / ".relocation" / "plans" / f"{operation_id}.json"


def _safe_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256"}
    }


def _load_plan(path: Path, expected_sha: str = "") -> dict[str, Any]:
    plan = _read_json(path, "Relocation plan")
    if not isinstance(plan, dict) or plan.get("plan_version") != PLAN_VERSION:
        raise RelocationError("The relocation plan has an unsupported version.")
    recorded = str(plan.get("plan_sha256") or "")
    actual = _canonical_sha(_safe_plan(plan))
    if recorded != actual or expected_sha and expected_sha != actual:
        raise RelocationError("The relocation plan SHA-256 does not match its immutable content.")
    return plan


def preview_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    ledger_path = Path(
        _windows_path(str(payload.get("ledger_path") or ""), "Ledger path")
    )
    # 224 (Wave B2b): the Inbox's records are in the library; the ledger's name in the folder is a note, or
    # nothing for an Inbox that never had a ledger. The folder is what must be there.
    _require_regular_path(ledger_path.parent, directory=True, label="Review Media Inbox folder")
    mappings = _normalise_mappings(payload)
    original_roots = [
        _windows_path(str(value), "Original-media root")
        for value in payload.get("original_media_roots") or []
    ]
    if not any(_path_key(str(ledger_path)) == _path_key(str(Path(item["new_root"]) / ledger_path.name)) for item in mappings):
        if not any(_contained(str(item["new_root"]), str(ledger_path)) for item in mappings):
            raise RelocationError("The ledger must be contained by an approved new generated root.")
    queue_root = inbox_records.workspace(ledger_path)
    operation_seed = _operation_seed(
        ledger_path,
        mappings,
        original_roots,
        _known_exception_map(payload),
    )
    operation_id = f"relocation-{operation_seed[:24]}"
    path = _plan_path(queue_root, operation_id)
    lock_path = inbox_records.lock_file(queue_root)
    with inbox_records.ProcessLock(lock_path) as process_lock:
        if not process_lock.acquired:
            raise RelocationError("Review Media Inbox is active; relocation cannot inspect a moving queue.")
        if path.is_file():
            existing = _load_plan(path)
            return {
                "result_version": RESULT_VERSION,
                "action": ACTION,
                "status": "preview_existing",
                "operation_id": existing["operation_id"],
                "plan_path": str(path),
                "plan_sha256": existing["plan_sha256"],
                "summary": existing["summary"],
            }
        destination_verification = [
            _verify_migration_mapping(mapping) for mapping in mappings
        ]
        created_utc = _utc_now()
        database_changes, ledger_classifications, ledger_originals = _inspect_ledger(
            ledger_path,
            mappings,
            original_roots,
        )
        registered_before = _registered_folder_for(mappings, queue_root)
        batch_states, finalization_states = _batch_states(ledger_path)
        file_changes, file_classifications, file_originals = _inspect_json_files(
            queue_root,
            mappings,
            original_roots,
            batch_states,
            finalization_states,
            operation_id,
            created_utc,
        )
        exceptions = _known_exception_map(payload)
        packages = _verify_packages(ledger_path, mappings, exceptions)
        original_records = sorted(
            [*file_originals],
            key=lambda item: _canonical_sha(item),
        )
        original_snapshot = {
            "ledger": ledger_originals,
            "json_record_count": len(original_records),
            "json_sha256": _canonical_sha(original_records),
        }
        classifications = [*ledger_classifications, *file_classifications]
        counts = {
            category: sum(
                1 for item in classifications if item["classification"] == category
            )
            for category in (
                "original_media",
                "generated_owned",
                "derived_runtime",
                "historical_audit",
                "unknown",
            )
        }
        counts["derived_runtime"] = 3
        counts["database_changes"] = len(database_changes)
        counts["file_changes"] = len(file_changes)
        summary = {
            "database_record_changes": len(database_changes),
            "generated_manifest_or_journal_changes": len(file_changes),
            "original_media_changes": 0,
            "unknown_path_fields": counts["unknown"],
            "destination_files_verified": sum(
                int(item["verified_unchanged_file_count"])
                for item in destination_verification
            ),
            "source_packages_verified": int(packages["source_package_count"]),
            "known_invalid_packages_preserved": int(
                packages["known_invalid_package_count"]
            ),
        }
        if counts["unknown"]:
            raise RelocationError("Relocation found unknown path-bearing fields.")
        plan_without_hash: dict[str, Any] = {
            "plan_version": PLAN_VERSION,
            "action": ACTION,
            "operation_id": operation_id,
            "created_utc": created_utc,
            "ledger_path": str(ledger_path),
            "queue_root": str(queue_root),
            # 224 (Wave B2b): where the library said the Inbox folder was; apply moves it to queue_root.
            "registered_folder_before": registered_before,
            "original_media_roots": original_roots,
            "mappings": [
                {
                    key: value
                    for key, value in mapping.items()
                    if key != "record_files"
                }
                | {"record_file_count": len(mapping["record_files"])}
                for mapping in mappings
            ],
            "destination_verification": destination_verification,
            "database_changes": database_changes,
            "file_changes": file_changes,
            "classifications": classifications,
            "classification_counts": counts,
            "original_snapshot": original_snapshot,
            "package_verification": packages,
            "derived_runtime_snapshot": _derived_runtime_snapshot(queue_root),
            "summary": summary,
        }
        plan = {
            **plan_without_hash,
            "plan_sha256": _canonical_sha(plan_without_hash),
        }
        _atomic_json(path, plan)
        return {
            "result_version": RESULT_VERSION,
            "action": ACTION,
            "status": "preview",
            "operation_id": operation_id,
            "plan_path": str(path),
            "plan_sha256": plan["plan_sha256"],
            "summary": summary,
        }


def _mapping_records_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for item in plan["mappings"]:
        record_path = Path(str(item["migration_record_path"]))
        if _sha256_file(record_path) != str(item["migration_record_sha256"]):
            raise RelocationError("A migration record changed after preview.")
        record = _read_json(record_path, "Migration record")
        mappings.append(
            {
                **item,
                "record_files": _normalise_record_files(record),
            }
        )
    return mappings


def _operation_paths(plan: dict[str, Any]) -> dict[str, Path]:
    root = (
        Path(str(plan["queue_root"]))
        / ".relocation"
        / "operations"
        / str(plan["operation_id"])
    )
    token = _timestamp_token(str(plan["created_utc"]))
    return {
        "root": root,
        "journal": root / "relocation-journal.json",
        # 224 (Wave B2b): the library, which holds the Inbox's records.
        "database_backup": root
        / "backup"
        / f"{recording_records.DATABASE_NAME}.pre-relocation-{token}.bak",
        "file_backups": root / "file-backups",
        "derived_backups": root / "derived-backups",
    }


def _journal_checksum(journal: dict[str, Any]) -> str:
    return _canonical_sha(
        {key: value for key, value in journal.items() if key != "journal_sha256"}
    )


def _write_journal(path: Path, journal: dict[str, Any]) -> None:
    payload = dict(journal)
    payload["journal_sha256"] = _journal_checksum(payload)
    _atomic_json(path, payload)


def _read_journal(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    journal = _read_json(path, "Relocation journal")
    if (
        not isinstance(journal, dict)
        or journal.get("journal_version") != JOURNAL_VERSION
        or str(journal.get("journal_sha256") or "") != _journal_checksum(journal)
    ):
        raise RelocationError("The relocation journal is malformed or has an invalid checksum.")
    return journal


def _fault(payload: dict[str, Any], phase: str) -> None:
    callback = payload.get("fault_injector")
    if callable(callback):
        callback(phase)


def _backup_database(ledger_path: Path, backup_path: Path, journal: dict[str, Any] | None) -> None:
    if journal is not None:
        # 224 (Wave B2a, note 4): a run already under way may have changed the records, so the backup taken
        # before it started is the one to keep. It must be a whole library: an empty file passes SQLite's
        # damage check, so the check also asks for the Inbox's own tables.
        whole = False
        if backup_path.is_file() and backup_path.stat().st_size > 0:
            connection = inbox_records.read_only_file(backup_path)
            try:
                whole = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] == ["ok"] \
                    and connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = "
                                           "'inbox_sources'").fetchone() is not None
            except sqlite3.Error:
                whole = False
            finally:
                connection.close()
        if not whole:
            raise RelocationError(
                "The relocation database backup from the interrupted run is missing or damaged, so nothing was "
                "changed.")
        return
    # No run has started, so the ledger is as it was: a file at the backup's name (left by an earlier try that
    # failed) is never trusted, and a fresh checked copy replaces it.
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_records.backup(ledger_path, backup_path, overwrite=True)


def _backup_files(plan: dict[str, Any], paths: dict[str, Path]) -> None:
    for change in plan["file_changes"]:
        source = Path(str(change["path"]))
        target = paths["file_backups"] / str(change["relative_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            # 224 (Wave B2a): checked under a partial name first, so a copy cut short never sits at the
            # backup's name.
            safe_write.copy_file(source, target)
        if _sha256_file(target) != str(change["before_sha256"]):
            raise RelocationError("A relocation file backup does not match the inspected manifest.")
    queue_root = Path(str(plan["queue_root"]))
    for item in plan["derived_runtime_snapshot"]:
        relative = str(item["relative_path"])
        if relative == ".orchestration/process.lock" or not item.get("existed_before"):
            # The live lock is never replaced while its handle is held.  A
            # projection that did not exist before relocation needs no backup;
            # rollback removes the regenerated copy instead.
            continue
        source = queue_root / Path(relative)
        _require_regular_path(
            source,
            directory=False,
            label="Derived runtime projection",
        )
        target = paths["derived_backups"] / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            safe_write.copy_file(source, target)
        expected = str(item["before_sha256"])
        if _sha256_file(target) != expected:
            raise RelocationError(
                "A derived runtime backup does not match the previewed projection."
            )


def _apply_database_changes(
    ledger_path: Path,
    plan: dict[str, Any],
    paths: dict[str, Path],
    payload: dict[str, Any],
) -> None:
    connection = inbox_records.relocation_connection(write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for change in plan["database_changes"]:
            table = str(change["table"])
            column = str(change["column"])
            keys = dict(change["keys"])
            where = " AND ".join(f'"{key}" = ?' for key in keys)
            row = connection.execute(
                f'SELECT "{column}" FROM "{table}" WHERE {where}',
                list(keys.values()),
            ).fetchone()
            if row is None:
                raise RelocationError("A planned ledger record disappeared before relocation.")
            current = str(row[column] or "")
            if _path_key(current) == _path_key(str(change["after"])):
                continue
            if _path_key(current) != _path_key(str(change["before"])):
                raise RelocationError("A planned ledger path changed after preview.")
            connection.execute(
                f'UPDATE "{table}" SET "{column}" = ? WHERE {where}',
                [change["after"], *keys.values()],
            )
        now = _utc_now()
        mappings_json = json.dumps(plan["mappings"], ensure_ascii=False, sort_keys=True)
        counts_json = json.dumps(plan["classification_counts"], sort_keys=True)
        # 224 (Wave B2b): the Inbox folder registered in the library moves with the relocation.
        _move_registered_folder(connection, plan, forward=True)
        existing = connection.execute(
            "SELECT plan_sha256 FROM inbox_relocation_runs WHERE operation_id = ?",
            (plan["operation_id"],),
        ).fetchone()
        if existing is not None and str(existing["plan_sha256"]) != str(plan["plan_sha256"]):
            raise RelocationError("A relocation operation ID already governs a different plan.")
        connection.execute(
            """
            INSERT INTO inbox_relocation_runs
                (operation_id, plan_sha256, status, journal_path, backup_path,
                 mappings_json, counts_json, created_utc, updated_utc)
            VALUES (?, ?, 'applying', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(operation_id) DO UPDATE SET
                status='applying',
                journal_path=excluded.journal_path,
                backup_path=excluded.backup_path,
                updated_utc=excluded.updated_utc
            """,
            (
                plan["operation_id"],
                plan["plan_sha256"],
                str(paths["journal"]),
                str(paths["database_backup"]),
                mappings_json,
                counts_json,
                plan["created_utc"],
                now,
            ),
        )
        _fault(payload, "during_database_transaction")
        violations = inbox_records.link_problems(connection)
        if violations:
            raise RelocationError("Relocation would create ledger foreign-key violations.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _apply_file_changes(plan: dict[str, Any], mappings: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    for index, change in enumerate(plan["file_changes"]):
        path = Path(str(change["path"]))
        current_sha = _sha256_file(path)
        if current_sha == str(change["after_sha256"]):
            continue
        if current_sha != str(change["before_sha256"]):
            raise RelocationError("A generated manifest changed after preview.")
        document = _read_json(path, "Generated manifest")
        if not isinstance(document, dict):
            raise RelocationError("A generated manifest is not a JSON object.")
        content = _render_document(
            document,
            family=str(change["family"]),
            patches=list(change["patches"]),
            operation_id=str(plan["operation_id"]),
            created_utc=str(plan["created_utc"]),
            mappings=mappings,
        )
        if _sha256_bytes(content) != str(change["after_sha256"]):
            raise RelocationError("A generated manifest no longer renders to its immutable planned identity.")
        _atomic_bytes(path, content)
        if index == 0:
            _fault(payload, "during_manifest_refresh")


def _verify_original_snapshot(
    ledger_path: Path,
    queue_root: Path,
    plan: dict[str, Any],
    mappings: list[dict[str, Any]],
) -> None:
    original_roots = [str(value) for value in plan["original_media_roots"]]
    _changes, _classifications, ledger_originals = _inspect_ledger(
        ledger_path,
        mappings,
        original_roots,
    )
    if ledger_originals != plan["original_snapshot"]["ledger"]:
        raise RelocationError("Original-media ledger paths changed during relocation.")
    originals: list[dict[str, Any]] = []
    for path in _walk_files(queue_root):
        relative = path.relative_to(queue_root).as_posix()
        if _is_derived(relative) or path.suffix.casefold() != ".json":
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        family = _document_family(relative)
        for pointer, value in _walk_strings(document):
            is_original = (
                family == "run_journal" and _run_original_pointer(pointer)
            ) or (
                family == "source_manifest" and pointer == ("original_location",)
            )
            if is_original:
                if _original_root_for(value, original_roots) is None:
                    raise RelocationError("An original-media JSON field escaped its approved root.")
                originals.append(
                    {
                        "record": relative,
                        "json_pointer": "/" + "/".join(pointer),
                        "value": _path_key(value),
                    }
                )
    originals.sort(key=lambda item: _canonical_sha(item))
    if (
        len(originals) != int(plan["original_snapshot"]["json_record_count"])
        or _canonical_sha(originals) != str(plan["original_snapshot"]["json_sha256"])
    ):
        raise RelocationError("Original-media manifest or run-journal paths changed during relocation.")


def _verify_database_after(ledger_path: Path, plan: dict[str, Any]) -> None:
    connection = _connect_read_only(ledger_path)
    try:
        if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise RelocationError("The relocated ledger failed SQLite integrity validation.")
        if inbox_records.link_problems(connection):
            raise RelocationError("The relocated ledger has foreign-key violations.")
        registered = inbox_records.registered_folder(connection)
        if registered is None or _path_key(str(registered)) != _path_key(str(plan["queue_root"])):
            raise RelocationError("The Inbox folder registered in the library does not match the immutable plan.")
        for change in plan["database_changes"]:
            keys = dict(change["keys"])
            where = " AND ".join(f'"{key}" = ?' for key in keys)
            row = connection.execute(
                f'SELECT "{change["column"]}" FROM "{change["table"]}" WHERE {where}',
                list(keys.values()),
            ).fetchone()
            if row is None or _path_key(str(row[0] or "")) != _path_key(str(change["after"])):
                raise RelocationError("A relocated ledger field does not match the immutable plan.")
    finally:
        connection.close()


def _verify_file_changes(plan: dict[str, Any]) -> None:
    for change in plan["file_changes"]:
        path = Path(str(change["path"]))
        if _sha256_file(path) != str(change["after_sha256"]):
            raise RelocationError("A relocated generated manifest does not match the immutable plan.")


def _verify_package_snapshot(
    ledger_path: Path,
    mappings: list[dict[str, Any]],
    plan: dict[str, Any],
) -> None:
    exceptions = {
        (str(item["batch_id"]), int(item["source_id"])): {
            "tree_sha256": str(item["tree_sha256"]),
            "error_sha256": str(item["integrity_error_sha256"]),
        }
        for item in plan["package_verification"]["packages"]
        if str(item["integrity_status"]) == "known_invalid"
    }
    current = _verify_packages(ledger_path, mappings, exceptions)
    expected = sorted(
        plan["package_verification"]["packages"],
        key=lambda item: (str(item["batch_id"]), int(item["source_id"])),
    )
    actual = sorted(
        current["packages"],
        key=lambda item: (str(item["batch_id"]), int(item["source_id"])),
    )
    if actual != expected:
        raise RelocationError("A source package changed during relocation.")


def _registered_folder_for(mappings: list[dict[str, Any]], queue_root: Path) -> str:
    """Where the library says the Inbox folder is, which must be this relocation's old folder (or already its new
    one, when an applied relocation is previewed again)."""

    connection = _connect_read_only()
    try:
        registered = inbox_records.registered_folder(connection)
    finally:
        connection.close()
    if registered is None:
        raise RelocationError("No Inbox folder is registered in the library, so there is nothing to relocate.")
    text = str(registered)
    if _path_key(text) == _path_key(str(queue_root)) or any(
            _path_key(text) == _path_key(str(item["old_root"])) or _contained(str(item["old_root"]), text)
            for item in mappings):
        return text
    raise RelocationError("The Inbox's records belong to an Inbox folder that is not one of this relocation's "
                          "folders, so nothing was changed.")


def _move_registered_folder(connection: sqlite3.Connection, plan: dict[str, Any], *, forward: bool) -> None:
    """The registered Inbox folder from where it was to the plan's queue root (or back, for a rollback)."""

    before = str(plan.get("registered_folder_before") or "")
    after = str(plan["queue_root"])
    source, target = (before, after) if forward else (after, before)
    current = inbox_records.registered_folder(connection)
    if current is None or not before:
        raise RelocationError("No Inbox folder is registered in the library, so nothing was changed.")
    if _path_key(str(current)) == _path_key(target):
        return
    if _path_key(str(current)) != _path_key(source):
        raise RelocationError("The Inbox folder registered in the library changed after preview.")
    now = _utc_now()
    connection.execute("UPDATE roots SET path = ?, path_key = ?, last_seen_utc = ? WHERE kind = ?",
                       (target, recording_records.path_key(target), now, inbox_records.ROOT_KIND))


def _roll_back_rows(plan: dict[str, Any]) -> None:
    connection = inbox_records.relocation_connection(write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for change in plan["database_changes"]:
            table = str(change["table"])
            column = str(change["column"])
            keys = dict(change["keys"])
            where = " AND ".join(f'"{key}" = ?' for key in keys)
            row = connection.execute(f'SELECT "{column}" FROM "{table}" WHERE {where}', list(keys.values())).fetchone()
            if row is None:
                raise RelocationError("A relocated ledger record disappeared before rollback.")
            current = str(row[0] or "")
            if _path_key(current) == _path_key(str(change["before"])):
                continue
            if _path_key(current) != _path_key(str(change["after"])):
                raise RelocationError("A relocated ledger path changed after relocation, so rollback stopped.")
            connection.execute(f'UPDATE "{table}" SET "{column}" = ? WHERE {where}',
                               [change["before"], *keys.values()])
        _move_registered_folder(connection, plan, forward=False)
        connection.execute("DELETE FROM inbox_relocation_runs WHERE operation_id = ? AND plan_sha256 = ?",
                           (plan["operation_id"], plan["plan_sha256"]))
        if inbox_records.link_problems(connection):
            raise RelocationError("Rollback would leave broken links between the Inbox's records.")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _mark_complete(ledger_path: Path, plan: dict[str, Any]) -> None:
    connection = inbox_records.relocation_connection(write=True)
    try:
        now = _utc_now()
        # The library connection a helper keeps counts every change it made; only this one is checked.
        changes_before = connection.total_changes
        connection.execute(
            """
            UPDATE inbox_relocation_runs
            SET status='completed', updated_utc=?, completed_utc=?
            WHERE operation_id=? AND plan_sha256=?
            """,
            (now, now, plan["operation_id"], plan["plan_sha256"]),
        )
        if connection.total_changes - changes_before != 1:
            raise RelocationError("The relocation audit record could not be completed.")
        connection.commit()
    finally:
        connection.close()


def apply_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("apply_confirmed") is not True:
        raise RelocationError("Explicit apply confirmation is required.")
    plan_path = Path(
        _windows_path(str(payload.get("plan_path") or ""), "Relocation plan path")
    )
    plan = _load_plan(plan_path, str(payload.get("plan_sha256") or ""))
    ledger_path = Path(str(plan["ledger_path"]))
    queue_root = Path(str(plan["queue_root"]))
    paths = _operation_paths(plan)
    mappings = _mapping_records_from_plan(plan)
    changed_relatives = {
        str(change["relative_path"]).casefold()
        for change in plan["file_changes"]
    }
    lock_path = inbox_records.lock_file(queue_root)
    with inbox_records.ProcessLock(lock_path) as process_lock:
        if not process_lock.acquired:
            raise RelocationError("Review Media Inbox is active; relocation cannot apply concurrently.")
        for mapping in mappings:
            if _contained(str(mapping["new_root"]), str(ledger_path)):
                changed_relatives.add(
                    Path(ledger_path)
                    .relative_to(Path(str(mapping["new_root"])))
                    .as_posix()
                    .casefold()
                )
            _verify_migration_mapping(mapping, allowed_changed=changed_relatives)
        journal = _read_journal(paths["journal"])
        if journal is not None and str(journal.get("plan_sha256") or "") != str(plan["plan_sha256"]):
            raise RelocationError("The relocation journal belongs to a different plan.")
        if journal is not None and journal.get("phase") == "completed":
            _verify_database_after(ledger_path, plan)
            _verify_file_changes(plan)
            _verify_original_snapshot(ledger_path, queue_root, plan, mappings)
            _verify_package_snapshot(ledger_path, mappings, plan)
            return {
                "result_version": RESULT_VERSION,
                "action": ACTION,
                "status": "already_relocated",
                "operation_id": plan["operation_id"],
                "plan_sha256": plan["plan_sha256"],
                "journal_path": str(paths["journal"]),
                "summary": plan["summary"],
            }
        _fault(payload, "before_backup")
        _backup_database(ledger_path, paths["database_backup"], journal)
        _backup_files(plan, paths)
        _fault(payload, "after_backup")
        if journal is None:
            journal = {
                "journal_version": JOURNAL_VERSION,
                "operation_id": plan["operation_id"],
                "plan_sha256": plan["plan_sha256"],
                "phase": "journal_created",
                "created_utc": _utc_now(),
                "updated_utc": _utc_now(),
                "recovery_count": 0,
                "database_backup_path": str(paths["database_backup"]),
            }
            _write_journal(paths["journal"], journal)
        else:
            journal["recovery_count"] = int(journal.get("recovery_count") or 0) + 1
            journal["updated_utc"] = _utc_now()
            _write_journal(paths["journal"], journal)
        _fault(payload, "after_journal")
        _apply_database_changes(ledger_path, plan, paths, payload)
        journal.update({"phase": "database_committed", "updated_utc": _utc_now()})
        _write_journal(paths["journal"], journal)
        _fault(payload, "after_database_commit")
        _apply_file_changes(plan, mappings, payload)
        journal.update({"phase": "manifests_refreshed", "updated_utc": _utc_now()})
        _write_journal(paths["journal"], journal)
        _fault(payload, "after_manifest_refresh")
        queue = review_queue.refresh_queue(
            {"ledger_path": str(ledger_path)},
            import_external=False,
        )
        journal.update(
            {
                "phase": "queue_regenerated",
                "updated_utc": _utc_now(),
                "queue_index_sha256": _sha256_file(
                    Path(str(queue["queue_index_path"]))
                ),
                "queue_prompt_sha256": _sha256_file(
                    Path(str(queue["queue_prompt_path"]))
                ),
            }
        )
        _write_journal(paths["journal"], journal)
        _fault(payload, "after_queue_regeneration")
        _verify_database_after(ledger_path, plan)
        _verify_file_changes(plan)
        _verify_original_snapshot(ledger_path, queue_root, plan, mappings)
        _verify_package_snapshot(ledger_path, mappings, plan)
        _fault(payload, "before_completion")
        _mark_complete(ledger_path, plan)
        journal.update(
            {
                "phase": "completed",
                "updated_utc": _utc_now(),
                "completed_utc": _utc_now(),
            }
        )
        _write_journal(paths["journal"], journal)
        return {
            "result_version": RESULT_VERSION,
            "action": ACTION,
            "status": "relocated",
            "operation_id": plan["operation_id"],
            "plan_sha256": plan["plan_sha256"],
            "journal_path": str(paths["journal"]),
            "database_backup_path": str(paths["database_backup"]),
            "summary": plan["summary"],
            "classification_counts": plan["classification_counts"],
            "queue_counts": queue["counts"],
            "queue_operator_status": queue["operator_status"],
            "recovery_count": int(journal.get("recovery_count") or 0),
        }


def _restore_file(source: Path, target: Path) -> None:
    _require_regular_path(source, directory=False, label="Relocation rollback backup")
    _atomic_bytes(target, source.read_bytes())


def rollback_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("rollback_confirmed") is not True:
        raise RelocationError("Explicit rollback confirmation is required.")
    plan_path = Path(
        _windows_path(str(payload.get("plan_path") or ""), "Relocation plan path")
    )
    plan = _load_plan(plan_path, str(payload.get("plan_sha256") or ""))
    ledger_path = Path(str(plan["ledger_path"]))
    queue_root = Path(str(plan["queue_root"]))
    paths = _operation_paths(plan)
    lock_path = inbox_records.lock_file(queue_root)
    with inbox_records.ProcessLock(lock_path) as process_lock:
        if not process_lock.acquired:
            raise RelocationError("Review Media Inbox is active; relocation rollback cannot run concurrently.")
        journal = _read_journal(paths["journal"])
        if journal is None:
            raise RelocationError("No relocation journal exists to roll back.")
        journal.update({"phase": "rolling_back", "updated_utc": _utc_now()})
        _write_journal(paths["journal"], journal)
        for change in plan["file_changes"]:
            backup = paths["file_backups"] / str(change["relative_path"])
            _restore_file(backup, Path(str(change["path"])))
            if _sha256_file(Path(str(change["path"]))) != str(change["before_sha256"]):
                raise RelocationError("Rollback could not restore a generated manifest exactly.")
        for backup in _walk_files(paths["derived_backups"]) if paths["derived_backups"].is_dir() else []:
            relative = backup.relative_to(paths["derived_backups"])
            _restore_file(backup, queue_root / relative)
        for item in plan["derived_runtime_snapshot"]:
            relative = str(item["relative_path"])
            if (
                relative != ".orchestration/process.lock"
                and not item.get("existed_before")
            ):
                projection = queue_root / Path(relative)
                if projection.exists() and not projection.is_file():
                    raise RelocationError(
                        "Rollback found a non-file derived runtime projection."
                    )
                if projection.is_file():
                    safe_write.remove(projection, wait=safe_write.INBOX_WAIT_SECONDS)
        # 224 (Wave B2b, Q6): the library holds much more than the Inbox, so its file is never copied back. Only the
        # rows this plan changed go back to the values the plan holds, with the registered Inbox folder and this
        # relocation's own record, in one transaction.
        _roll_back_rows(plan)
        connection = _connect_read_only(ledger_path)
        try:
            if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
                raise RelocationError("The restored pre-relocation database is invalid.")
        finally:
            connection.close()
        journal.update(
            {
                "phase": "rolled_back",
                "updated_utc": _utc_now(),
                "rolled_back_utc": _utc_now(),
            }
        )
        _write_journal(paths["journal"], journal)
        return {
            "result_version": RESULT_VERSION,
            "action": ACTION,
            "status": "rolled_back",
            "operation_id": plan["operation_id"],
            "plan_sha256": plan["plan_sha256"],
            "journal_path": str(paths["journal"]),
            "database_backup_path": str(paths["database_backup"]),
        }


def relocate_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview, apply, or roll back one explicit generated-storage relocation."""

    mode = str(payload.get("mode") or "").strip().lower()
    if not mode:
        if payload.get("apply_confirmed") is True:
            mode = "apply"
        elif payload.get("rollback_confirmed") is True:
            mode = "rollback"
        else:
            mode = "preview"
    if mode in {"preview", "dry_run", "dry-run"}:
        return preview_from_request(payload)
    if mode == "apply":
        return apply_from_request(payload)
    if mode == "rollback":
        return rollback_from_request(payload)
    raise RelocationError("mode must be preview, apply, or rollback.")
