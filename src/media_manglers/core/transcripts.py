"""Shared transcript helpers for tracked Python provider commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import coerce_segment_records


def format_srt_time(seconds: float) -> str:
    total_ms = int(round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02},{millis:03}"


def write_transcript_files(
    output_dir: str | Path,
    json_name: str,
    srt_name: str,
    text_name: str,
    result: dict[str, Any],
) -> tuple[Path, Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    payload = dict(result)
    payload["segments"] = coerce_segment_records(payload.get("segments") or [])

    json_path = output_path / json_name
    srt_path = output_path / srt_name
    text_path = output_path / text_name

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with text_path.open("w", encoding="utf-8") as handle:
        for segment in payload["segments"]:
            if segment["text"]:
                handle.write(segment["text"] + "\n")

    with srt_path.open("w", encoding="utf-8") as handle:
        for index, segment in enumerate(payload["segments"], start=1):
            start_ts = format_srt_time(segment.get("start", 0))
            end_ts = format_srt_time(segment.get("end", 0))
            handle.write(f"{index}\n{start_ts} --> {end_ts}\n{segment['text']}\n\n")

    return json_path, srt_path, text_path
