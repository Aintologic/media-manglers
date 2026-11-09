"""Machine-readable CLI request/result contracts for Media Manglers helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


JsonObject = dict[str, Any]
EVIDENCE_PACKAGE_REQUEST_SCHEMA_VERSION = 2


def _contract_float(value: Any, default: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _contract_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default if value is None else bool(value)


@dataclass(frozen=True, slots=True)
class EvidenceNarrationSettings:
    narration_context_pre_seconds: float = 120.0
    narration_context_post_seconds: float = 600.0
    narration_pause_threshold_seconds: float = 30.0
    narration_stop_at_next_ticket_boundary: bool = True
    fragmented_narration_mode: bool = True

    @classmethod
    def from_payload(cls, payload: JsonObject) -> "EvidenceNarrationSettings":
        return cls(
            narration_context_pre_seconds=_contract_float(
                payload.get("narration_context_pre_seconds"), 120.0
            ),
            narration_context_post_seconds=_contract_float(
                payload.get("narration_context_post_seconds"), 600.0
            ),
            narration_pause_threshold_seconds=_contract_float(
                payload.get("narration_pause_threshold_seconds"), 30.0
            ),
            narration_stop_at_next_ticket_boundary=_contract_bool(
                payload.get("narration_stop_at_next_ticket_boundary"), True
            ),
            fragmented_narration_mode=_contract_bool(
                payload.get("fragmented_narration_mode"), True
            ),
        )

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(slots=True)
class CommandEnvelope:
    payload: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(slots=True)
class CommandResult:
    ok: bool
    data: JsonObject = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> JsonObject:
        return asdict(self)


def read_json_file(path: str | Path) -> JsonObject:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json_file(path: str | Path, payload: JsonObject) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
