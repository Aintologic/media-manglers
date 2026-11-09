"""214: the shared filters against recorded runs that someone has checked by ear.

Each case lives only on the machine that made it, under AREA51/TEMP/regression-cases/<name>/ (never
committed: it holds what was said in a recording). Its case.json names the recorded
Whisper output of real runs (the raw_attempts of a *.transcript.raw.json) and lists the lines the
operator said (must_keep) and stretches where they said nothing (must_not, no_line_before_seconds).
Every recorded run is replayed through the shared sparse filters the way whisper_local applies them:
each must keep exactly what the operator said and nothing they did not, before the cross-track check runs.
226: so must it with the AI Video Editor's short-reaction rule on, taking every line as loud (these
cases hold no audio, so the level test cannot help). Without the folder, the tests are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import sparse_narration as sn  # noqa: E402

CASES = sorted((REPO_ROOT / "AREA51" / "TEMP" / "regression-cases").glob("*/case.json"))


def replay(raw_attempts: list[dict], prompt: str, *, keep_short_reactions: bool = False) -> list[dict]:
    """whisper_local's sparse selection, on recorded attempts: per chunk, the first attempt that
    does not need a retry, then the cross-chunk loop check. With ``keep_short_reactions`` the
    editor's rule is applied to the attempts used, with every line taken as loud."""

    by_chunk: dict[int, list[dict]] = {}
    for attempt in raw_attempts:
        by_chunk.setdefault(int(attempt["chunk_index"]), []).append(attempt)
    accepted: list[dict] = []
    used: list[dict] = []
    for index in sorted(by_chunk):
        selected: list[dict] = []
        for attempt in sorted(by_chunk[index], key=lambda item: int(item["attempt"])):
            segments, filtered = sn.filter_sparse_decoder_segments(
                [dict(segment) for segment in attempt.get("segments") or []],
                context_segments=accepted, prompt_text=prompt)
            if not sn.chunk_repetition_requires_retry(sn.chunk_repetition_metrics(accepted, segments)):
                selected = segments
                used.append({**attempt, "filtered_segments": filtered})
                break
        accepted.extend(selected)
    reactions = (sn.select_short_reactions(used, accepted, lambda start, end: 0.0, -120.0, prompt_text=prompt)
                 if keep_short_reactions else [])
    accepted, _loops = sn.drop_phrase_loops(accepted)
    if keep_short_reactions:
        accepted, _left_out, _added = sn.add_short_reactions(accepted, reactions, prompt_text=prompt)
    return accepted


@unittest.skipUnless(CASES, "no local regression cases on this machine")
class LocalRecordingRegressionTests(unittest.TestCase):
    def test_every_recorded_run_keeps_what_was_said_and_nothing_else(self) -> None:
        self._check_every_run(keep_short_reactions=False)

    def test_with_the_editors_short_reaction_rule_no_invented_line_comes_back(self) -> None:
        self._check_every_run(keep_short_reactions=True)

    def _check_every_run(self, *, keep_short_reactions: bool) -> None:
        for case_path in CASES:
            case = json.loads(case_path.read_text(encoding="utf-8-sig"))
            for name in case["raw_attempt_files"]:
                with self.subTest(case=case_path.parent.name, run=name):
                    raw = json.loads((case_path.parent / name).read_text(encoding="utf-8"))
                    kept = replay(raw["raw_attempts"], str(case.get("prompt") or ""),
                                  keep_short_reactions=keep_short_reactions)
                    lines = [(float(item["start"]), str(item.get("text") or "").strip()) for item in kept]
                    for wanted in case.get("must_keep") or []:
                        self.assertTrue(any(abs(start - float(wanted["start"])) <= 2.0 and wanted["contains"].lower() in text.lower()
                                            for start, text in lines), f"lost: {wanted}")
                    before = float(case.get("no_line_before_seconds") or 0.0)
                    self.assertEqual([line for line in lines if line[0] < before], [], "invented lines early on")
                    for unwanted in case.get("must_not") or []:
                        found = [line for line in lines if float(unwanted["from"]) <= line[0] <= float(unwanted["to"])
                                 and str(unwanted.get("contains") or "").lower() in line[1].lower()]
                        self.assertEqual(found, [], unwanted.get("note"))


if __name__ == "__main__":
    unittest.main()
