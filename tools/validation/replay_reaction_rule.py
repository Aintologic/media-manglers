"""Replay the AI Video Editor's short-reaction rule on recorded Whisper output (226). Local use only.

A regression case folder holds ``case.json`` and the recorded Whisper runs it names (``raw_attempts``
of a ``*.raw.json``), with the lines the operator said (``must_keep``) and the stretches where they said
nothing (``must_not``, ``no_line_before_seconds``). Each run is replayed through today's sparse filters
the way whisper_local applies them (per chunk, the first attempt that needs no retry; then the
cross-chunk loop check), and the rule (``sparse_narration.select_short_reactions`` and
``add_short_reactions``) is applied to the attempts that were used. The tool prints how many known
invented lines come back and which candidate lines are kept. It writes nothing.

The rule measures the narration track over each line (the 90th percentile of its 50 ms frames, in
dBFS). Recorded cases hold no audio, so a level list stands in, and the output says which:

    --levels FILE --track N        an AI Video Editor analysis.json: loudness_per_second, keyed by the
                                   0-based track. The loudest second over the line stands in for the
                                   50 ms peak (coarse: one second of RMS for a word of half a second).
    --frame-levels FILE --track N  50 ms frame levels in dB from the shared 16 kHz decode, as an .npz
                                   with one array per track named rms_<0-based track>. The frames the
                                   rule measures, but counted from the start of the recording rather
                                   than from the start of the line.

Without either, the level test is not applied: every line that passes shape and anchor counts as kept
(the worst case). The recording's quiet (the VAD noise floor) comes from --noise-floor-dbfs, else a
``*.vad.json`` beside the run, else the 20th percentile of the level list.

Usage, from the repository root:

    AREA51\\TEMP\\workbench-build\\python-3.12.10-embed-amd64\\python.exe -B tools\\validation\\replay_reaction_rule.py CASE_FOLDER [--frame-levels FILE --track 2]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from media_manglers.core import sparse_narration as sn  # noqa: E402

LevelFunction = Callable[[float, float], "float | None"]


def replay(raw_attempts: list[dict[str, Any]], prompt: str) -> tuple[list[dict], list[dict], list[dict]]:
    """whisper_local's sparse selection on recorded attempts, with today's filters: the kept lines
    before the cross-chunk loop check, the attempt used for each chunk (its ``filtered_segments`` as
    today's filter makes them), and the lines of thrown-out chunks' later attempts."""

    by_chunk: dict[int, list[dict]] = {}
    for attempt in raw_attempts:
        by_chunk.setdefault(int(attempt["chunk_index"]), []).append(attempt)
    accepted: list[dict] = []
    used: list[dict] = []
    thrown_out: list[dict] = []
    for index in sorted(by_chunk):
        attempts = sorted(by_chunk[index], key=lambda item: int(item["attempt"]))
        chosen = None
        for attempt in attempts:
            segments, filtered = sn.filter_sparse_decoder_segments(
                [dict(segment) for segment in attempt.get("segments") or []],
                context_segments=accepted, prompt_text=prompt)
            if not sn.chunk_repetition_requires_retry(sn.chunk_repetition_metrics(accepted, segments)):
                chosen = (attempt, segments, filtered)
                break
        if chosen is None:
            thrown_out.extend(segment for attempt in attempts if int(attempt["attempt"]) >= 2
                              for segment in attempt.get("segments") or [])
            continue
        attempt, segments, filtered = chosen
        accepted.extend(segments)
        used.append({"chunk_index": index, "attempt": int(attempt["attempt"]), "interval": attempt.get("interval") or {},
                     "segments": attempt.get("segments") or [], "filtered_segments": filtered})
    return accepted, used, thrown_out


def per_second_levels(path: Path, track: int) -> tuple[LevelFunction, list[float], str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    values = [float(value) for value in (data.get("loudness_per_second") or {}).get(str(track - 1)) or []]
    if not values:
        raise SystemExit(f"{path.name} has no loudness_per_second for Track {track}.")

    def level(start: float, end: float) -> float | None:
        first, last = int(math.floor(start)), max(int(math.floor(start)) + 1, int(math.ceil(end)))
        window = values[max(0, first):min(len(values), last)]
        return max(window) if window else None

    return level, values, (f"PROXY: per-second dB of Track {track} from {path.name} (loudness_per_second); the "
                           "loudest second over a line stands in for its 50 ms peak")


def frame_levels(path: Path, track: int) -> tuple[LevelFunction, list[float], str]:
    import numpy  # noqa: PLC0415

    with numpy.load(str(path)) as archive:
        key = f"rms_{track - 1}"
        if key not in archive.files:
            raise SystemExit(f"{path.name} has no {key}.")
        values = [float(value) for value in archive[key].astype("float32")]
    frame = sn.PEAK_FRAME_SECONDS

    def level(start: float, end: float) -> float | None:
        first = int(math.floor(start / frame + 1e-9))
        last = max(first + 1, int(math.ceil(end / frame - 1e-9)))
        window = sorted(values[max(0, first):min(len(values), last)])
        if not window:
            return None
        return window[min(len(window) - 1, int(len(window) * (1.0 - sn.PEAK_LOUD_SHARE)))]

    return level, values, (f"PROXY: 50 ms frame dB of Track {track} from {path.name}; the rule's own measure "
                           "(90th percentile of the line's frames), with frames counted from the recording's start")


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * share)))]


def _number(item: dict, key: str) -> float:
    try:
        return float(item.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def _in_stretch(start: float, text: str, case: dict) -> list[str]:
    """The case's stretches of no speech this line falls in."""

    found = []
    before = float(case.get("no_line_before_seconds") or 0.0)
    if start < before:
        found.append(f"before {before:g} s")
    for unwanted in case.get("must_not") or []:
        if float(unwanted["from"]) <= start <= float(unwanted["to"]) and \
                str(unwanted.get("contains") or "").lower() in text.lower():
            found.append(str(unwanted.get("note") or f"{unwanted['from']}-{unwanted['to']} s"))
    return found


def run_case(folder: Path, level: LevelFunction | None, floor_given: float | None, floor_values: list[float],
             proxy: str) -> int:
    case = json.loads((folder / "case.json").read_text(encoding="utf-8-sig"))
    prompt = str(case.get("prompt") or "")
    print(f"Case: {folder.name}")
    print(f"  Level: {proxy}")
    totals = {"runs": 0, "back": 0, "added": 0, "sampled": 0, "shaped": 0}
    distinct: dict[tuple[float, str], list[str]] = {}
    for name in case["raw_attempt_files"]:
        raw = json.loads((folder / name).read_text(encoding="utf-8"))
        accepted, used, thrown_out = replay(raw["raw_attempts"], prompt)
        if floor_given is not None:
            floor, floor_source = floor_given, "given"
        else:
            vad = folder / (name[: -len(".raw.json")] + ".vad.json") if name.endswith(".raw.json") else None
            if vad is not None and vad.is_file():
                floor = sn.rms_dbfs(json.loads(vad.read_text(encoding="utf-8")).get("noise_floor"))
                floor_source = vad.name
            elif floor_values:
                floor, floor_source = _percentile(floor_values, 0.20), "20th percentile of the level list"
            else:
                floor, floor_source = -120.0, "unknown (no floor test)"
        sampled = [item for attempt in used for item in attempt["filtered_segments"]
                   if item["reason"] == sn.SHORT_REACTION_REASON]
        only_bar = [item for item in sampled if sn.only_fault_is_the_sampled_bar(item["segment"], prompt)]
        shaped = []
        for attempt in used:
            chunk = _number(attempt["interval"], "end_seconds") - _number(attempt["interval"], "start_seconds")
            for item in attempt["filtered_segments"]:
                if item in only_bar and sn.is_short_burst(item["segment"], chunk, len(attempt["segments"])):
                    shaped.append(item)
        anchored = [item for item in shaped if sn.short_reaction_anchor(item["segment"], accepted, prompt) is not None]
        def line_level(start: float, end: float) -> float | None:
            # Without a level list every line counts as loud: the worst case.
            return level(start, end) if level is not None else 0.0

        reactions = sn.select_short_reactions(used, accepted, line_level, floor, prompt_text=prompt)
        kept, _loops = sn.drop_phrase_loops(accepted, context_segments=thrown_out)
        lines_with, left_out, added = sn.add_short_reactions(kept, reactions, context_segments=thrown_out,
                                                             prompt_text=prompt)
        back = [(item, _in_stretch(_number(item["segment"], "start"), str(item["segment"].get("text") or ""), case))
                for item in added]
        back = [(item, where) for item, where in back if where]
        totals["runs"] += 1
        totals["sampled"] += len(sampled)
        totals["shaped"] += len(shaped)
        totals["back"] += len(back)
        totals["added"] += len(added)
        print(f"  Run {name}: {len(kept)} lines kept without the rule; sampled-guess drops in used attempts "
              f"{len(sampled)}; only that fault {len(only_bar)}; short burst {len(shaped)}; real line within "
              f"{sn.SHORT_REACTION_ANCHOR_SECONDS:g} s {len(anchored)}; "
              f"{'loud enough' if level is not None else 'level NOT tested'} {len(reactions)}; kept {len(added)}; "
              f"left out after the loop check {len(left_out)}. Noise floor {floor:.1f} dBFS ({floor_source}).")
        print(f"    Known invented lines back: {len(back)}")
        for item, where in back:
            print(f"      BACK {_clock(_number(item['segment'], 'start'))} {item['segment'].get('text', '').strip()!r} in {where}")
        for item in added:
            segment = item["segment"]
            key = (round(_number(segment, "start"), 2), str(segment.get("text") or "").strip())
            distinct.setdefault(key, []).append(name)
            level_text = f"{item['line_dbfs']:.1f} dB" if level is not None else "level not tested"
            print(f"      kept {_clock(key[0])} {key[1]!r} ({level_text}; real line at {_clock(item['anchor_start'])})")
        if level is not None:
            for item in anchored:
                segment = item["segment"]
                if any(added_item["segment"].get("start") == segment.get("start") for added_item in added):
                    continue
                start, end = _number(segment, "start"), _number(segment, "end")
                value = level(start, max(end, start + sn.SHORT_REACTION_MIN_LEVEL_SECONDS))
                value_text = "unknown" if value is None else f"{value:.1f} dB"
                print(f"      not loud enough {_clock(start)} {str(segment.get('text') or '').strip()!r} ({value_text}; "
                      f"needs above {sn.NEAR_SILENT_DBFS:g} and at least {floor + sn.SHORT_REACTION_OVER_FLOOR_DB:.1f})")
        for wanted in case.get("must_keep") or []:
            if not any(abs(_number(line, "start") - float(wanted["start"])) <= 2.0
                       and wanted["contains"].lower() in str(line.get("text") or "").lower() for line in lines_with):
                print(f"    LOST a line the operator said: {wanted}")
    print(f"  Total: {totals['runs']} runs; {totals['sampled']} sampled-guess drops in used attempts, "
          f"{totals['shaped']} of them short bursts; {totals['added']} reactions kept ({len(distinct)} distinct); "
          f"known invented lines back: {totals['back']}")
    return totals["back"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("case_folder", type=Path)
    parser.add_argument("--levels", type=Path, help="an analysis.json with loudness_per_second (per-second proxy)")
    parser.add_argument("--frame-levels", type=Path, help="an .npz of 50 ms frame levels, rms_<0-based track>")
    parser.add_argument("--track", type=int, default=2, help="the narration track number, from 1 (default 2)")
    parser.add_argument("--noise-floor-dbfs", type=float, help="the recording's VAD noise floor in dBFS")
    args = parser.parse_args(argv)
    if args.levels and args.frame_levels:
        parser.error("give --levels or --frame-levels, not both")
    level: LevelFunction | None = None
    values: list[float] = []
    proxy = "NONE: the level test is not applied; every line passing shape and anchor counts as kept (worst case)"
    if args.levels:
        level, values, proxy = per_second_levels(args.levels, args.track)
    elif args.frame_levels:
        level, values, proxy = frame_levels(args.frame_levels, args.track)
    if not (args.case_folder / "case.json").is_file():
        parser.error(f"{args.case_folder} has no case.json")
    back = run_case(args.case_folder, level, args.noise_floor_dbfs, values, proxy)
    return 1 if back else 0


if __name__ == "__main__":
    raise SystemExit(main())
