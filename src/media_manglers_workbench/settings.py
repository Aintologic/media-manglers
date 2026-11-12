"""Persistent settings, profiles, and cleanup helpers for the workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable

from media_manglers.core import safe_write
from media_manglers.core.user_folders import videos_folder

from .metadata import DEFAULT_WORKFLOW, SETTING_METADATA, normalize_workflow
from .spelling_words import with_starter_words as _with_starter_spelling_words


SETTINGS_SCHEMA_VERSION = 8
PROFILE_SCHEMA_VERSION = 2
BUILT_IN_PROFILE_VERSION = 7
SETTINGS_BUNDLE_SCHEMA_VERSION = 2
SETTINGS_BUNDLE_TYPE = "media-manglers-workbench-settings"
PRIVATE_AUDIO_KEYS = {
    "evidence_audio_stream_index",
    "evidence_audio_stream_selection_confirmed",
    "evidence_audio_stream_selections_json",
    "voice_enrollment",
    "voice_signature",
    "narration_layouts",
}
APPDATA_OVERRIDE_ENV = "MEDIA_MANGLERS_WORKBENCH_APPDATA"
LOCALAPPDATA_OVERRIDE_ENV = "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA"
# 114: the never-use list and the already-done map. Both hold the operator's
# own recording paths (the map as its KEYS), so they belong to this PC only:
# never exported, never imported, never copied into a saved profile. Since
# Wave A2 (244) both live in the library; settings.json only ever holds them
# from an older build, until the next start moves them in.
BUG_REPORT_RECORDING_LIST_KEYS = (
    "bug_report_excluded_recordings",
    "bug_report_processed_recordings",
)
# 115, 244: the stopped run Continue picks up (its folder, recordings and
# track choices). The same: this PC only, and in the library since Wave A2.
BUG_REPORT_STOPPED_RUN_KEY = "bug_report_stopped_run"
ALWAYS_LOCAL_RUNTIME_KEYS = {
    "recent_runs",
    "recent_output_folders",
    "last_evidence_package",
    "window_geometry",
    # 125: the built-in player's window rectangle belongs to this screen.
    "review_player_geometry",
    *BUG_REPORT_RECORDING_LIST_KEYS,
    BUG_REPORT_STOPPED_RUN_KEY,
}
SENSITIVE_KEY_MARKERS = {
    "access_key",
    "api_key",
    "api_token",
    "auth_token",
    "credential",
    "hostname",
    "machine_fingerprint",
    "password",
    "private_key",
    "recording_fingerprint",
    "secret",
    "signed_url",
    "transcript_content",
    "transcript_text",
    "token",
    "user_name",
    "username",
    "validation_evidence",
    "voice_enrollment",
    "voice_signature",
}


@dataclass(frozen=True, slots=True)
class MachineLocalFieldSpec:
    expected_type: str
    access: str = "read"
    multiple: bool = False


MACHINE_LOCAL_FIELD_SPECS = {
    "input_path": MachineLocalFieldSpec("any"),
    "default_input_folder": MachineLocalFieldSpec("directory"),
    "output_folder": MachineLocalFieldSpec("directory", "write"),
    "repo_root": MachineLocalFieldSpec("directory"),
    "script_path": MachineLocalFieldSpec("file"),
    "dependency_python_path": MachineLocalFieldSpec("file"),
    "dependency_ffmpeg_path": MachineLocalFieldSpec("file"),
    "dependency_ffprobe_path": MachineLocalFieldSpec("file"),
    "dependency_ytdlp_path": MachineLocalFieldSpec("file"),
    "evidence_transcription_glossary_path": MachineLocalFieldSpec("file"),
    "evidence_panel_role_map_path": MachineLocalFieldSpec("file"),
    "evidence_resume_root": MachineLocalFieldSpec("directory"),
    "evidence_repo_map_path": MachineLocalFieldSpec("file"),
    "archive_catalog_path": MachineLocalFieldSpec("directory"),
    "archive_notes_csv": MachineLocalFieldSpec("file"),
    "review_source_folders": MachineLocalFieldSpec("directory", multiple=True),
    "review_evidence_root": MachineLocalFieldSpec("directory", "write"),
    "review_local_work_root": MachineLocalFieldSpec("directory", "write"),
    "review_ledger_path": MachineLocalFieldSpec("file", "write"),
    # 224 (Wave B2b): the Inbox's folder on THIS PC; its records are in the library.
    "review_inbox_folder": MachineLocalFieldSpec("directory", "write"),
    "log_folder": MachineLocalFieldSpec("directory", "write"),
    "temp_folder": MachineLocalFieldSpec("directory", "write"),
    # 220: the cache folder belongs to THIS PC.
    "cache_folder": MachineLocalFieldSpec("directory", "write"),
    # 125: where VLC lives on THIS PC, exactly like the dependency paths.
    "video_player_vlc_path": MachineLocalFieldSpec("file"),
    # 150: where the AI Video Editor keeps its projects on THIS PC.
    "race_video_output_folder": MachineLocalFieldSpec("directory", "write"),
}


@dataclass(frozen=True, slots=True)
class PathValidationResult:
    state: str
    resolved_path: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class SettingsImportEntry:
    scope: str
    key: str
    status: str
    detail: str
    value: str = ""


@dataclass(slots=True)
class SettingsImportResult:
    settings: dict[str, Any]
    imported_profile_names: list[str]
    source_schema_version: int
    entries: list[SettingsImportEntry] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        statuses = ("applied", "skipped", "unresolved", "incompatible", "ignored_for_safety")
        return {status: sum(entry.status == status for entry in self.entries) for status in statuses}

    def summary_text(self) -> str:
        counts = self.counts()
        lines = [
            f"Applied: {counts['applied']}",
            f"Skipped: {counts['skipped']}",
            f"Unresolved: {counts['unresolved']}",
            f"Incompatible: {counts['incompatible']}",
            f"Ignored for safety: {counts['ignored_for_safety']}",
            f"Custom profiles imported: {len(self.imported_profile_names)}",
        ]
        if self.source_schema_version < SETTINGS_BUNDLE_SCHEMA_VERSION:
            lines.append(
                f"Legacy bundle schema {self.source_schema_version} was migrated during import; the source file was unchanged."
            )
        return "\n".join(lines)

    def details_text(self) -> str:
        details: list[str] = []
        for entry in self.entries:
            if entry.status == "applied":
                continue
            status = entry.status.replace("_", " ")
            value = f"\n  Imported value: {entry.value}" if entry.value else ""
            details.append(f"{entry.scope} / {entry.key}: {status} — {entry.detail}{value}")
        return "\n\n".join(details) or "All supported imported fields were applied."


PathValidator = Callable[[str, MachineLocalFieldSpec, str], PathValidationResult]


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if value:
        return Path(value)
    return None


def user_profile_root() -> Path:
    value = os.environ.get("USERPROFILE")
    if value:
        return Path(value)
    return Path.home()


def roaming_appdata_root() -> Path:
    override = _env_path(APPDATA_OVERRIDE_ENV)
    if override:
        return override
    value = os.environ.get("APPDATA")
    if value:
        return Path(value)
    return user_profile_root() / "AppData" / "Roaming"


def local_appdata_root() -> Path:
    override = _env_path(LOCALAPPDATA_OVERRIDE_ENV)
    if override:
        return override
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    return user_profile_root() / "AppData" / "Local"


def default_output_folder() -> Path:
    return videos_folder() / "Media Mangler"


def default_input_folder() -> Path:
    return videos_folder()


def default_settings_root() -> Path:
    return roaming_appdata_root() / "MediaManglers" / "workbench"


def default_profiles_dir() -> Path:
    return default_settings_root() / "profiles"


def default_settings_path() -> Path:
    return default_settings_root() / "settings.json"


def default_log_folder() -> Path:
    return local_appdata_root() / "MediaManglers" / "Workbench" / "logs"


def default_temp_folder() -> Path:
    return local_appdata_root() / "MediaManglers" / "Workbench" / "temp"


def build_default_settings(repo_root: str = "") -> dict[str, Any]:
    settings = {item.key: item.default for item in SETTING_METADATA}
    settings.update(
        {
            "default_workflow": DEFAULT_WORKFLOW,
            "input_kind": "local",
            "default_input_folder": str(default_input_folder()),
            "output_folder": str(default_output_folder()),
            "repo_root": repo_root,
            "script_path": ".\\Video Mangler.ps1",
            "log_folder": str(default_log_folder()),
            "temp_folder": str(default_temp_folder()),
            "cleanup_retention_days": 14,
            "default_profile": "",
            "startup_page": "Home",
            "restore_window_geometry": True,
            "theme": "Dark",
            # 237: the text size in percent (100, 110, 125 or 150); a file without it opens at 100%.
            "text_size_percent": 100,
            "window_geometry": "",
            "recent_output_folders": [],
            "last_evidence_package": "",
            "dependency_python_path": "",
            "dependency_ffmpeg_path": "",
            "dependency_ffprobe_path": "",
            "dependency_ytdlp_path": "",
            # Installer plan, Stage 1: the one-time question about tool paths saved by an earlier version
            # that differ from the copies bundled with Media Manglers has been answered.
            "bundled_tools_question_answered": False,
            "whisper_model_download_approved": False,
            "review_inbox_order": "oldest",
            "review_inbox_max_files": 3,
            "review_inbox_max_duration_minutes": 240,
            "review_inbox_pending_batch_limit": 1,
            "review_inbox_workload_mode": "next_3",
            "review_inbox_new_source_limit": 10,
            "review_inbox_continuation": "",
            "review_inbox_decision_json": "",
            # 114's never-use list and already-done map are no settings any
            # more: they live in the library (244), so no default writes them.
            # 125: the built-in player. Where VLC lives and where the window
            # sat describe this PC only; see the two local-key sets above.
            "video_player": "internal",
            "video_autoplay": True,
            "video_player_vlc_path": "",
            "review_player_geometry": "",
            "review_player_volume": 0.8,
            # 125 Part 2: the built-in player's waveform lanes, shown until the operator hides them.
            "review_player_waveforms": True,
        }
    )
    return settings


def merge_settings(payload: dict[str, Any] | None, *, repo_root: str = "") -> dict[str, Any]:
    merged = build_default_settings(repo_root=repo_root)
    if payload:
        raw_settings = payload.get("settings") if "settings" in payload else payload
        if isinstance(raw_settings, dict):
            for key, value in raw_settings.items():
                merged[key] = value
    merged["default_workflow"] = normalize_workflow(merged.get("default_workflow"))
    return merged


def migrate_settings_payload(payload: dict[str, Any] | None, *, repo_root: str = "") -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    try:
        source_version = int(source.get("schemaVersion") or 1)
    except (TypeError, ValueError):
        source_version = 1
    settings = merge_settings(source, repo_root=repo_root)
    if source_version < 6:
        # Schema 6 replaces the legacy profile-driven startup with the plain
        # Full Review defaults. Presets remain available as optional choices.
        settings["default_workflow"] = DEFAULT_WORKFLOW
        settings["default_profile"] = ""
    if source_version < 7:
        # 201: the words to spell right keep what was saved and gain the starting words it
        # lacks, once. A starting word removed after this stays removed.
        settings["evidence_transcription_glossary_entries"] = _with_starter_spelling_words(
            settings.get("evidence_transcription_glossary_entries")
        )
    if source_version < 8:
        # 206: Package any video for AI makes its ZIP by default. A saved "off" from before was
        # the old default, not a choice, so it is turned on once; turned off again, it stays off.
        settings["create_ai_review_zip"] = True
    return {
        "schemaVersion": SETTINGS_SCHEMA_VERSION,
        "sourceSchemaVersion": source_version,
        "settings": settings,
    }


def load_settings(path: Path | None = None, *, repo_root: str = "") -> dict[str, Any]:
    settings_path = path or default_settings_path()
    if not settings_path.exists():
        return build_default_settings(repo_root=repo_root)
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return build_default_settings(repo_root=repo_root)
    return migrate_settings_payload(payload, repo_root=repo_root)["settings"]


def save_settings(settings: dict[str, Any], path: Path | None = None, *, repo_root: str = "") -> Path:
    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": SETTINGS_SCHEMA_VERSION,
        "settings": merge_settings(settings, repo_root=repo_root),
    }
    # 242: written beside and renamed into place, so a full disk or a crash never leaves half a file.
    safe_write.write_json(settings_path, payload)
    return settings_path


def _is_blank_setting(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")


def _is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    if normalized in PRIVATE_AUDIO_KEYS:
        return True
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)


def _contains_sensitive_nested_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _is_sensitive_key(key) or _contains_sensitive_nested_field(nested)
            for key, nested in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains_sensitive_nested_field(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "x-amz-signature=" in lowered
            or "x-goog-signature=" in lowered
            or "access_token=" in lowered
            or "auth_token=" in lowered
        )
    return False


def _value_looks_like_local_path(value: Any) -> bool:
    if isinstance(value, dict):
        # A map can keep the path as its key and something harmless, such as a
        # date, as its value; looking at values alone lets those paths through.
        return any(_value_looks_like_local_path(item) for item in value.values()) or any(
            _value_looks_like_local_path(key) for key in value
        )
    if isinstance(value, (list, tuple, set)):
        return any(_value_looks_like_local_path(item) for item in value)
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    return bool(
        re.search(r"(?i)(?:^|[\s;])(?:[a-z]:[\\/]|\\\\|%userprofile%|%appdata%|%localappdata%|%temp%|%tmp%)", text)
        or re.match(r"^(?:\.\.?[\\/]|~[\\/])", text)
    )


def _is_machine_local_field(key: str, value: Any) -> bool:
    return key in MACHINE_LOCAL_FIELD_SPECS or _value_looks_like_local_path(value)


def _classify_export_fields(
    settings: dict[str, Any],
    *,
    include_machine_paths: bool,
) -> tuple[dict[str, Any], dict[str, Any], set[str], set[str], set[str]]:
    portable: dict[str, Any] = {}
    machine_local: dict[str, Any] = {}
    machine_fields: set[str] = set()
    sensitive_fields: set[str] = set()
    runtime_fields: set[str] = set()
    for raw_key, value in settings.items():
        key = str(raw_key)
        if key in ALWAYS_LOCAL_RUNTIME_KEYS:
            runtime_fields.add(key)
            continue
        if _is_sensitive_key(key) or _contains_sensitive_nested_field(value):
            sensitive_fields.add(key)
            continue
        if _is_machine_local_field(key, value):
            machine_fields.add(key)
            if include_machine_paths and not _is_blank_setting(value):
                machine_local[key] = value
            continue
        portable[key] = value
    return portable, machine_local, machine_fields, sensitive_fields, runtime_fields


def export_settings_bundle(
    path: Path,
    settings: dict[str, Any],
    profile_manager: "ProfileManager",
    *,
    repo_root: str = "",
    include_machine_paths: bool = False,
) -> Path:
    portable_settings, machine_settings, machine_fields, sensitive_fields, runtime_fields = (
        _classify_export_fields(
            merge_settings(settings, repo_root=repo_root),
            include_machine_paths=include_machine_paths,
        )
    )
    included_machine_fields = set(machine_settings)
    custom_profiles: list[dict[str, Any]] = []
    for name in profile_manager.list_names():
        if profile_manager.is_builtin(name):
            continue
        loaded = profile_manager.load_with_metadata(name)
        portable_profile, machine_profile, profile_machine, profile_sensitive, profile_runtime = (
            _classify_export_fields(
                loaded.settings,
                include_machine_paths=include_machine_paths,
            )
        )
        profile_payload: dict[str, Any] = {
            "name": loaded.name,
            "workflow": loaded.workflow,
            "settings": portable_profile,
        }
        if machine_profile:
            profile_payload["machineLocalSettings"] = machine_profile
        custom_profiles.append(profile_payload)
        machine_fields.update(profile_machine)
        included_machine_fields.update(machine_profile)
        sensitive_fields.update(profile_sensitive)
        runtime_fields.update(profile_runtime)
    payload: dict[str, Any] = {
        "bundleType": SETTINGS_BUNDLE_TYPE,
        "schemaVersion": SETTINGS_BUNDLE_SCHEMA_VERSION,
        "settingsSchemaVersion": SETTINGS_SCHEMA_VERSION,
        "profileSchemaVersion": PROFILE_SCHEMA_VERSION,
        "exportMode": "this-pc-paths" if include_machine_paths else "portable",
        "settings": portable_settings,
        "customProfiles": custom_profiles,
        "portability": {
            "portableByDefault": True,
            "machineLocalValuesIncluded": include_machine_paths,
            "machineLocalValuesRequireValidationOnImport": True,
        },
        "exportAudit": {
            "portableSettingsCount": len(portable_settings),
            "customProfileCount": len(custom_profiles),
            "machineLocalFieldsIncluded": sorted(included_machine_fields),
            "machineLocalFieldsOmitted": sorted(machine_fields - included_machine_fields),
            "sensitiveFieldsExcludedCount": len(sensitive_fields),
            "runtimeFieldsExcluded": sorted(runtime_fields),
        },
    }
    if machine_settings:
        payload["machineLocalSettings"] = machine_settings
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def validate_import_path(
    value: str,
    spec: MachineLocalFieldSpec,
    repo_root: str = "",
) -> PathValidationResult:
    raw = str(value or "").strip().strip('"')
    expanded = os.path.expanduser(os.path.expandvars(raw))
    candidate = Path(expanded)
    if not candidate.is_absolute() and repo_root:
        candidate = Path(repo_root) / candidate
    try:
        exists = candidate.exists()
    except OSError as exc:
        return PathValidationResult("inaccessible", str(candidate), str(exc))
    if not exists:
        return PathValidationResult("missing", str(candidate), "Path does not exist on this computer.")
    try:
        if spec.expected_type == "file" and not candidate.is_file():
            return PathValidationResult("incompatible", str(candidate), "Expected a file, but found a directory.")
        if spec.expected_type == "directory" and not candidate.is_dir():
            return PathValidationResult("incompatible", str(candidate), "Expected a directory, but found a file.")
    except OSError as exc:
        return PathValidationResult("inaccessible", str(candidate), str(exc))
    access_mode = os.R_OK | (os.W_OK if spec.access == "write" else 0)
    if not os.access(candidate, access_mode):
        requirement = "read/write" if spec.access == "write" else "read"
        return PathValidationResult(
            "inaccessible",
            str(candidate),
            f"Path exists but {requirement} access is unavailable.",
        )
    applied_value = expanded if expanded != raw else raw
    return PathValidationResult("valid", applied_value, "Validated on this computer.")


def _split_machine_values(value: Any, spec: MachineLocalFieldSpec) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if spec.multiple:
        return [item.strip() for item in re.split(r"[;\r\n]+", text) if item.strip()]
    return [text]


def _apply_import_scope(
    portable_fields: dict[str, Any],
    machine_fields: dict[str, Any],
    current_values: dict[str, Any],
    *,
    scope: str,
    repo_root: str,
    entries: list[SettingsImportEntry],
    path_validator: PathValidator,
) -> dict[str, Any]:
    applied = dict(current_values)
    combined = dict(portable_fields)
    combined.update(machine_fields)
    for raw_key, value in combined.items():
        key = str(raw_key)
        if key in ALWAYS_LOCAL_RUNTIME_KEYS or _is_sensitive_key(key) or _contains_sensitive_nested_field(value):
            entries.append(
                SettingsImportEntry(scope, key, "ignored_for_safety", "Local runtime or sensitive data is never imported.")
            )
            continue
        if not _is_machine_local_field(key, value):
            applied[key] = value
            entries.append(SettingsImportEntry(scope, key, "applied", "Portable setting applied."))
            continue
        spec = MACHINE_LOCAL_FIELD_SPECS.get(key, MachineLocalFieldSpec("any"))
        values = _split_machine_values(value, spec)
        if not values:
            entries.append(
                SettingsImportEntry(scope, key, "skipped", "Imported machine-local value was blank; current value was preserved.")
            )
            continue
        validations = [path_validator(item, spec, repo_root) for item in values]
        incompatible = next((item for item in validations if item.state == "incompatible"), None)
        unresolved = next(
            (item for item in validations if item.state in {"missing", "inaccessible"}),
            None,
        )
        imported_display = "; ".join(values)
        if incompatible:
            entries.append(
                SettingsImportEntry(
                    scope,
                    key,
                    "incompatible",
                    incompatible.message,
                    imported_display,
                )
            )
            continue
        if unresolved:
            detail = (
                "Path is inaccessible on this computer; current value was preserved."
                if unresolved.state == "inaccessible"
                else "Path is missing on this computer; current value was preserved."
            )
            if unresolved.message:
                detail += f" {unresolved.message}"
            entries.append(SettingsImportEntry(scope, key, "unresolved", detail, imported_display))
            continue
        resolved_values = [item.resolved_path for item in validations]
        applied[key] = "; ".join(resolved_values) if spec.multiple else resolved_values[0]
        entries.append(SettingsImportEntry(scope, key, "applied", "Machine-local path validated and applied."))
    return applied


def import_settings_bundle(
    path: Path,
    current_settings: dict[str, Any],
    profile_manager: "ProfileManager",
    *,
    repo_root: str = "",
    path_validator: PathValidator | None = None,
) -> SettingsImportResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Settings bundle could not be read: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("bundleType") != SETTINGS_BUNDLE_TYPE:
        raise ValueError("This is not a Video Mangler Workbench settings bundle.")
    try:
        schema_version = int(payload.get("schemaVersion"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Settings bundle schemaVersion is missing or invalid.") from exc
    if schema_version > SETTINGS_BUNDLE_SCHEMA_VERSION or schema_version < 1:
        raise ValueError(f"Unsupported settings bundle schemaVersion: {schema_version}")
    imported_settings = payload.get("settings")
    if not isinstance(imported_settings, dict):
        raise ValueError("Settings bundle does not contain a settings object.")
    imported_machine = payload.get("machineLocalSettings") or {}
    if not isinstance(imported_machine, dict):
        raise ValueError("Settings bundle machineLocalSettings must be an object when present.")
    raw_profiles = payload.get("customProfiles") or []
    if not isinstance(raw_profiles, list):
        raise ValueError("Settings bundle customProfiles must be an array when present.")

    validator = path_validator or validate_import_path
    entries: list[SettingsImportEntry] = []
    applied_settings = _apply_import_scope(
        imported_settings,
        imported_machine,
        dict(current_settings),
        scope="Settings",
        repo_root=repo_root,
        entries=entries,
        path_validator=validator,
    )
    merged = merge_settings(applied_settings, repo_root=repo_root)

    imported_names: list[str] = []
    existing_names = set(profile_manager.list_names())
    for index, raw in enumerate(raw_profiles, start=1):
        if not isinstance(raw, dict) or not isinstance(raw.get("settings"), dict):
            entries.append(
                SettingsImportEntry(
                    f"Profile {index}",
                    "settings",
                    "skipped",
                    "Profile entry is missing a settings object.",
                )
            )
            continue
        raw_machine = raw.get("machineLocalSettings") or {}
        if not isinstance(raw_machine, dict):
            entries.append(
                SettingsImportEntry(
                    f"Profile {index}",
                    "machineLocalSettings",
                    "skipped",
                    "Profile machineLocalSettings is not an object.",
                )
            )
            continue
        base_name = _safe_import_profile_name(raw.get("name"))
        name = base_name
        suffix = 1
        while name in existing_names or profile_manager.is_builtin(name):
            suffix += 1
            name = f"{base_name} (imported {suffix})"
        profile_settings = _apply_import_scope(
            raw["settings"],
            raw_machine,
            build_default_settings(repo_root=repo_root),
            scope=f"Profile: {name}",
            repo_root=repo_root,
            entries=entries,
            path_validator=validator,
        )
        profile_manager.save(
            name,
            profile_settings,
            workflow=normalize_workflow(raw.get("workflow")),
        )
        existing_names.add(name)
        imported_names.append(name)
    return SettingsImportResult(
        settings=merged,
        imported_profile_names=imported_names,
        source_schema_version=schema_version,
        entries=entries,
    )


def _safe_import_profile_name(value: Any) -> str:
    filename = safe_profile_filename(str(value or "Imported Profile"))
    return Path(filename).stem or "Imported Profile"


def safe_profile_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip(" ._-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "Profile") + ".json"


def starter_profile_settings(repo_root: str = "") -> dict[str, dict[str, Any]]:
    base = build_default_settings(repo_root=repo_root)
    return {
        "Ticket Evidence Run": {
            **base,
            "default_workflow": "3",
            "input_kind": "local",
            "whisper_model": "medium",
            "pre_context_seconds": 120,
            "post_context_seconds": 240,
            "evidence_frame_cadence_seconds": 10,
            "evidence_max_frames_per_candidate": 60,
            "evidence_panel_crops": "Auto",
            "evidence_handoff_mode": "Both",
        },
        "iRacing Ticket Evidence - Balanced": {
            **base,
            "default_workflow": "3",
            "input_kind": "local",
            "fragmented_narration_mode": True,
            "language": "en",
            "narration_speech_mode": "Sparse",
            "evidence_render_density": "Compact",
            "evidence_profile_setup_name": "iRacing Ticket Evidence - Balanced",
            "narration_context_preset": "Driving / Extended",
            "pre_context_seconds": 90,
            "post_context_seconds": 120,
            "narration_context_pre_seconds": 120,
            "narration_context_post_seconds": 600,
            "narration_pause_threshold_seconds": 30,
            "narration_stop_at_next_ticket_boundary": True,
            "evidence_frame_offsets": "-90,-60,-45,-30,-15,-10,-5,-2,0,2,5,10,15,30,60,90,120",
            "evidence_frame_cadence_seconds": 15.0,
            "evidence_max_frames_per_candidate": 24,
            "evidence_max_items": 20,
            "evidence_panel_crops": "Auto",
            "evidence_handoff_mode": "Both",
        },
        "iRacing Telemetry Detail": {
            **base,
            "default_workflow": "3",
            "input_kind": "local",
            "fragmented_narration_mode": True,
            "language": "en",
            "narration_speech_mode": "Sparse",
            "evidence_render_density": "Compact",
            "evidence_profile_setup_name": "iRacing Telemetry Detail",
            "narration_context_preset": "Driving / Extended",
            "pre_context_seconds": 60,
            "post_context_seconds": 90,
            "narration_context_pre_seconds": 120,
            "narration_context_post_seconds": 600,
            "narration_pause_threshold_seconds": 30,
            "narration_stop_at_next_ticket_boundary": True,
            "evidence_frame_offsets": "-60,-45,-30,-20,-15,-10,-5,-2,-1,0,1,2,5,10,15,30,60,90",
            "evidence_frame_cadence_seconds": 15.0,
            "evidence_max_frames_per_candidate": 24,
            "evidence_max_items": 10,
            "evidence_panel_crops": "Auto",
            "evidence_handoff_mode": "Both",
        },
        "iRacing Long Explanation": {
            **base,
            "default_workflow": "3",
            "input_kind": "local",
            "fragmented_narration_mode": True,
            "language": "en",
            "narration_speech_mode": "Sparse",
            "evidence_render_density": "Compact",
            "evidence_profile_setup_name": "iRacing Long Explanation",
            "narration_context_preset": "Custom",
            "pre_context_seconds": 120,
            "post_context_seconds": 180,
            "narration_context_pre_seconds": 180,
            "narration_context_post_seconds": 900,
            "narration_pause_threshold_seconds": 30,
            "narration_stop_at_next_ticket_boundary": True,
            "evidence_frame_offsets": "-120,-90,-60,-30,-15,0,15,30,60,90,120,180",
            "evidence_frame_cadence_seconds": 15.0,
            "evidence_max_frames_per_candidate": 24,
            "evidence_max_items": 20,
            "evidence_panel_crops": "Auto",
            "evidence_handoff_mode": "Both",
        },
        "Full Review + Evidence": {
            **base,
            "default_workflow": "1",
            "input_kind": "local",
            "include_codex_evidence_package": True,
            "create_ai_review_zip": True,
            "full_review_panel_crops": "Auto",
        },
        "Transcript Search": {
            **base,
            "default_workflow": "2",
            "input_kind": "local",
            "transcript_only_recurse": True,
            "skip_transcript_only_audio": False,
        },
        "Archive Prep": {
            **base,
            "default_workflow": "4",
            "archive_action": "build",
            "archive_hash_mode": "Fast",
            "archive_thumbnail_mode": "Auto",
            "archive_max_thumbnails_per_video": 12,
        },
        "Review Media Inbox": {
            **base,
            "default_workflow": "5",
            "review_dedupe_mode": "Fast",
            "review_no_recurse": False,
            "review_inbox_order": "oldest",
            "review_inbox_max_files": 3,
            "review_inbox_max_duration_minutes": 240,
            "review_inbox_pending_batch_limit": 1,
            "review_inbox_workload_mode": "next_3",
            "review_inbox_new_source_limit": 10,
            "review_inbox_continuation": "",
            "review_inbox_decision_json": "",
        },
    }


def _profile_workflow(payload: dict[str, Any], settings: dict[str, Any]) -> str:
    return normalize_workflow(payload.get("workflow") or settings.get("default_workflow"))


def _profile_fingerprint(settings: dict[str, Any], workflow: str) -> str:
    fingerprint_settings = {
        key: value
        for key, value in settings.items()
        if key not in {"default_profile", "default_workflow"}
    }
    encoded = json.dumps(
        {"workflow": normalize_workflow(workflow), "settings": fingerprint_settings},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class LoadedProfile:
    name: str
    workflow: str
    settings: dict[str, Any]
    schema_version: int
    profile_type: str
    built_in_version: int = 0
    migration_status: str = ""
    migrated_from_built_in_version: int = 0
    missing_default_keys: tuple[str, ...] = ()

    @property
    def source_description(self) -> str:
        if self.profile_type == "built-in":
            if self.migration_status == "migrated-built-in":
                return (
                    f"Migrated built-in v{self.built_in_version} "
                    f"from v{self.migrated_from_built_in_version}"
                )
            return f"Built-in profile v{self.built_in_version}"
        if self.schema_version < PROFILE_SCHEMA_VERSION or self.missing_default_keys:
            return f"Migrated legacy profile (schema {self.schema_version} effective as {PROFILE_SCHEMA_VERSION})"
        if self.migration_status == "preserved-custom":
            return "Preserved custom settings from a legacy built-in"
        return f"Custom profile schema {self.schema_version}"


@dataclass(slots=True)
class ProfileManager:
    profiles_dir: Path | None = None
    repo_root: str = ""

    @property
    def root(self) -> Path:
        return self.profiles_dir or default_profiles_dir()

    def ensure_starter_profiles(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name, settings in starter_profile_settings(repo_root=self.repo_root).items():
            path = self.profile_path(name)
            if not path.exists():
                self._save_builtin(name, settings)
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("profileType") != "built-in":
                continue
            raw_settings = payload.get("settings")
            if not isinstance(raw_settings, dict):
                raw_settings = {}
            current_workflow = _profile_workflow(payload, raw_settings)
            stored_hash = str(payload.get("builtInDefaultsHash") or "")
            raw_hash = _profile_fingerprint(raw_settings, current_workflow)
            current_version = int(payload.get("builtInVersion") or 0)
            if current_version >= BUILT_IN_PROFILE_VERSION and stored_hash == raw_hash:
                continue
            if raw_settings and (not stored_hash or stored_hash != raw_hash):
                self._preserve_modified_builtin(name, payload, raw_settings, current_workflow, current_version)
            self._save_builtin(
                name,
                settings,
                migration_status="migrated-built-in" if current_version else "",
                migrated_from_built_in_version=current_version,
            )

    def _preserve_modified_builtin(
        self,
        name: str,
        payload: dict[str, Any],
        settings: dict[str, Any],
        workflow: str,
        built_in_version: int,
    ) -> Path:
        suffix = f"preserved legacy v{built_in_version or 'unknown'}"
        candidate = f"{name} ({suffix})"
        index = 2
        while self.profile_path(candidate).exists():
            candidate = f"{name} ({suffix} {index})"
            index += 1
        return self._write_profile(
            candidate,
            settings,
            workflow=workflow,
            profile_type="custom",
            migration_status="preserved-custom",
            migrated_from_built_in_version=built_in_version,
            source_schema_version=int(payload.get("schemaVersion") or 1),
        )

    def profile_path(self, name: str) -> Path:
        return self.root / safe_profile_filename(name)

    def list_names(self) -> list[str]:
        if not self.root.exists():
            return []
        names: list[str] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            name = str(payload.get("profileName") or path.stem)
            names.append(name)
        return names

    def load_with_metadata(self, name: str) -> LoadedProfile:
        payload = json.loads(self.profile_path(name).read_text(encoding="utf-8-sig"))
        raw_settings = payload.get("settings")
        if not isinstance(raw_settings, dict):
            raw_settings = {}
        defaults = build_default_settings(repo_root=self.repo_root)
        missing_default_keys = tuple(sorted(key for key in defaults if key not in raw_settings))
        settings = merge_settings(raw_settings, repo_root=self.repo_root)
        workflow = _profile_workflow(payload, settings)
        return LoadedProfile(
            name=str(payload.get("profileName") or name),
            workflow=workflow,
            settings=settings,
            schema_version=int(payload.get("schemaVersion") or 1),
            profile_type=str(payload.get("profileType") or "custom"),
            built_in_version=int(payload.get("builtInVersion") or 0),
            migration_status=str(payload.get("migrationStatus") or ""),
            migrated_from_built_in_version=int(payload.get("migratedFromBuiltInVersion") or 0),
            missing_default_keys=missing_default_keys,
        )

    def load(self, name: str) -> dict[str, Any]:
        loaded = self.load_with_metadata(name)
        return {**loaded.settings, "default_workflow": loaded.workflow}

    def profile_type(self, name: str) -> str:
        try:
            return self.load_with_metadata(name).profile_type
        except (OSError, json.JSONDecodeError):
            return ""

    def is_builtin(self, name: str) -> bool:
        return self.profile_type(name) == "built-in"

    def _write_profile(
        self,
        name: str,
        settings: dict[str, Any],
        *,
        workflow: str,
        profile_type: str,
        built_in_version: int | None = None,
        migration_status: str = "",
        migrated_from_built_in_version: int = 0,
        source_schema_version: int | None = None,
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        merged = merge_settings(settings, repo_root=self.repo_root)
        normalized_workflow = normalize_workflow(workflow)
        payload: dict[str, Any] = {
            "schemaVersion": PROFILE_SCHEMA_VERSION,
            "profileName": name,
            "profileType": profile_type,
            "workflow": normalized_workflow,
            "settings": merged,
        }
        if profile_type == "built-in":
            payload["builtInId"] = safe_profile_filename(name)[:-5].lower().replace(" ", "-")
            payload["builtInVersion"] = built_in_version or BUILT_IN_PROFILE_VERSION
            payload["builtInDefaultsHash"] = _profile_fingerprint(merged, normalized_workflow)
        if migration_status:
            payload["migrationStatus"] = migration_status
        if migrated_from_built_in_version:
            payload["migratedFromBuiltInVersion"] = migrated_from_built_in_version
        if source_schema_version is not None:
            payload["sourceSchemaVersion"] = source_schema_version
        path = self.profile_path(name)
        safe_write.write_json(path, payload)
        return path

    def _save_builtin(
        self,
        name: str,
        settings: dict[str, Any],
        *,
        migration_status: str = "",
        migrated_from_built_in_version: int = 0,
    ) -> Path:
        return self._write_profile(
            name,
            settings,
            workflow=normalize_workflow(settings.get("default_workflow")),
            profile_type="built-in",
            built_in_version=BUILT_IN_PROFILE_VERSION,
            migration_status=migration_status,
            migrated_from_built_in_version=migrated_from_built_in_version,
        )

    def save(self, name: str, settings: dict[str, Any], *, workflow: str | None = None) -> Path:
        if self.is_builtin(name):
            raise ValueError(f"Built-in profile '{name}' is protected. Use Save As to create a custom copy.")
        settings = {
            key: value for key, value in settings.items()
            if key not in BUG_REPORT_RECORDING_LIST_KEYS and key != BUG_REPORT_STOPPED_RUN_KEY
        }
        return self._write_profile(
            name,
            settings,
            workflow=normalize_workflow(workflow or settings.get("default_workflow")),
            profile_type="custom",
        )

    def delete(self, name: str) -> bool:
        path = self.profile_path(name)
        if not path.exists():
            return False
        if self.is_builtin(name):
            raise ValueError(f"Built-in profile '{name}' cannot be deleted.")
        path.unlink()
        return True


@dataclass(slots=True)
class CleanupResult:
    deleted_files: int = 0
    deleted_dirs: int = 0
    skipped_files: int = 0
    errors: list[str] | None = None

    def add_error(self, message: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(message)


def _resolve_existing_or_parent(path: Path) -> Path:
    if path.exists():
        return path.resolve()
    parent = path.parent
    if parent.exists():
        return parent.resolve() / path.name
    return path.resolve()


def is_within_path(path: Path, root: Path) -> bool:
    resolved_path = _resolve_existing_or_parent(path)
    resolved_root = _resolve_existing_or_parent(root)
    try:
        resolved_path.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def clean_workbench_owned_path(
    target_path: Path,
    *,
    owned_root: Path,
    retention_days: int,
    now: float | None = None,
) -> CleanupResult:
    if not is_within_path(target_path, owned_root):
        raise ValueError(f"Refusing to clean outside the workbench-owned root: {target_path}")
    result = CleanupResult(errors=[])
    if not target_path.exists():
        return result
    cutoff = (now if now is not None else time.time()) - (max(retention_days, 0) * 86400)
    for path in sorted(target_path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_file():
                if path.stat().st_mtime <= cutoff:
                    path.unlink()
                    result.deleted_files += 1
                else:
                    result.skipped_files += 1
            elif path.is_dir():
                try:
                    path.rmdir()
                    result.deleted_dirs += 1
                except OSError:
                    pass
        except OSError as exc:
            result.add_error(f"{path}: {exc}")
    return result


def new_workbench_log_path(log_folder: Path | None = None) -> Path:
    root = log_folder or default_log_folder()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return root / f"workbench-{timestamp}.log"
