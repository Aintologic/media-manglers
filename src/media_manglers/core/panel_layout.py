"""Shared three-panel layout helpers for Media Manglers."""

from __future__ import annotations

from typing import Any


THREE_PANEL_COMPOSITE_WIDTH = 5760
THREE_PANEL_COMPOSITE_HEIGHT = 1080
THREE_PANEL_CROP_WIDTH = 1920
THREE_PANEL_CROP_HEIGHT = 1080
PANEL_CROP_MODES = {"auto", "on", "off"}
PANEL_CROP_MODE_DEFAULT = "auto"

THREE_PANEL_DEFINITIONS = (
    {
        "role": "overview_cam",
        "label": "Overview Cam",
        "purpose": "Wide contextual view; may contain dashboard or monitor UI when the recording layout places it here.",
        "expected_evidence_types": ["scene context", "track", "vehicle", "dashboard monitor"],
        "crop_x": 0,
        "crop_y": 0,
        "crop_width": THREE_PANEL_CROP_WIDTH,
        "crop_height": THREE_PANEL_CROP_HEIGHT,
    },
    {
        "role": "driver_view",
        "label": "Driver View",
        "purpose": "Driver-facing view; inspect for cockpit, controls, overlays, or UI only when present.",
        "expected_evidence_types": ["cockpit", "controls", "overlays", "driver-facing UI"],
        "crop_x": THREE_PANEL_CROP_WIDTH,
        "crop_y": 0,
        "crop_width": THREE_PANEL_CROP_WIDTH,
        "crop_height": THREE_PANEL_CROP_HEIGHT,
    },
    {
        "role": "face_cam",
        "label": "Face Cam",
        "purpose": "Operator gesture and spoken-context view.",
        "expected_evidence_types": ["operator", "gesture", "spoken context"],
        "crop_x": THREE_PANEL_CROP_WIDTH * 2,
        "crop_y": 0,
        "crop_width": THREE_PANEL_CROP_WIDTH,
        "crop_height": THREE_PANEL_CROP_HEIGHT,
    },
)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_panel_crop_mode(value: Any) -> str:
    mode = _safe_text(value).strip().lower()
    if mode in PANEL_CROP_MODES:
        return mode
    return PANEL_CROP_MODE_DEFAULT


def resolve_panel_definitions(value: Any = None) -> tuple[dict[str, Any], ...]:
    """Merge optional role metadata/crops with the default physical layout."""

    definitions = {panel["role"]: dict(panel) for panel in THREE_PANEL_DEFINITIONS}
    if isinstance(value, dict) and "panels" in value:
        raw_values = value.get("panels") or []
    elif isinstance(value, dict):
        raw_values = [
            {"role": role, **(dict(payload) if isinstance(payload, dict) else {})}
            for role, payload in value.items()
        ]
    elif isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = []
    for raw in raw_values:
        if not isinstance(raw, dict):
            continue
        role = _safe_text(raw.get("role"))
        if not role:
            continue
        existing = definitions.get(role, {"role": role})
        merged = {**existing, **dict(raw), "role": role}
        expected = merged.get("expected_evidence_types") or []
        if isinstance(expected, str):
            expected = [item.strip() for item in expected.split(",") if item.strip()]
        merged["expected_evidence_types"] = list(expected)
        required_geometry = ("crop_x", "crop_y", "crop_width", "crop_height")
        if all(key in merged for key in required_geometry):
            definitions[role] = merged
    return tuple(definitions.values())


def detect_three_panel_layout(
    width: int | str | None,
    height: int | str | None,
    panel_definitions: Any = None,
) -> dict[str, Any]:
    frame_width = _coerce_int(width, 0)
    frame_height = _coerce_int(height, 0)
    is_match = frame_width == THREE_PANEL_COMPOSITE_WIDTH and frame_height == THREE_PANEL_COMPOSITE_HEIGHT
    return {
        "panel_detection": "three_panel_5760x1080" if is_match else "not_applicable",
        "source_width": frame_width,
        "source_height": frame_height,
        "panels": [dict(panel) for panel in resolve_panel_definitions(panel_definitions)] if is_match else [],
    }


def panel_crop_configuration(mode: Any, panel_definitions: Any = None) -> dict[str, Any]:
    normalized = normalize_panel_crop_mode(mode)
    definitions = resolve_panel_definitions(panel_definitions)
    return {
        "mode": normalized,
        "source_dimension_rule": "Only exact 5760x1080 source frames are split into panel crops.",
        "default_behavior": "Auto/On generates panel crops for exact 5760x1080 NVIDIA Surround sources; Off disables derived panel crops.",
        "panels": [
            {
                **dict(panel),
                "crop_filter": f"{panel['crop_width']}:{panel['crop_height']}:{panel['crop_x']}:{panel['crop_y']}",
            }
            for panel in definitions
        ],
    }
