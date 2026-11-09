"""Shared artifact-shaping helpers for tracked Python provider commands."""

from __future__ import annotations

from typing import Any


def coerce_segment_records(segments: list[dict[str, Any]] | list[Any]) -> list[dict[str, Any]]:
    coerced: list[dict[str, Any]] = []
    for segment in segments or []:
        coerced.append(
            {
                "id": segment.get("id"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": str(segment.get("text") or "").strip(),
            }
        )
    return coerced
