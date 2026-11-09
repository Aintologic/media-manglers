from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.evidence_package import consolidate_candidate_outcomes


def _candidate(index: int, text: str, *, source: str = "source-a", duplicate_of: str = "") -> dict[str, object]:
    evidence_id = f"ticket-{index:03d}"
    return {
        "evidence_id": evidence_id,
        "source_id": source,
        "source_filename": f"{source}.mkv",
        "marker_timestamp_seconds": float(index * 10),
        "transcript_excerpt": text,
        "confidence": "explicit",
        "duplicate_role": "supporting_duplicate" if duplicate_of else "primary",
        "duplicate_of": duplicate_of,
        "narration_context": {"entries": [{"kind": "speech", "text": text}]},
    }


class OutcomeConsolidationTests(unittest.TestCase):
    def test_setup_negative_correction_duplicate_and_compound_are_explainable(self) -> None:
        candidates = [
            _candidate(1, "I am going to talk about bugs."),
            _candidate(2, "Make the sidebar labels bolder. Also remove the duplicate close button."),
            _candidate(3, "Make the sidebar labels bolder.", duplicate_of="ticket-002"),
            _candidate(4, "Scratch that correction: add a new feature instead."),
            _candidate(5, "No other issues."),
            _candidate(6, "Use the replay to test those earlier changes."),
        ]
        outcomes = consolidate_candidate_outcomes(candidates)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(candidates[0]["outcome_classification"], "transition_setup")
        self.assertEqual(candidates[2]["outcome_classification"], "duplicate_supporting")
        self.assertEqual(candidates[3]["outcome_classification"], "correction")
        self.assertEqual(candidates[4]["outcome_classification"], "negative_no_ticket")
        self.assertEqual(candidates[5]["outcome_classification"], "supporting_validation")
        self.assertEqual(sum(len(outcome["corrections"]) for outcome in outcomes), 1)
        self.assertTrue(
            all(outcome["record_label"] == "PROVISIONAL EVIDENCE CLUSTER" for outcome in outcomes)
        )
        self.assertTrue(all(not outcome["final_ticket_decision"] for outcome in outcomes))
        self.assertTrue(all(outcome["primary_choice_reason"] for outcome in outcomes))
        self.assertTrue(all(outcome["source_mentions"] for outcome in outcomes))
        self.assertTrue(all(outcome["linked_evidence_candidate_ids"] for outcome in outcomes))
        self.assertTrue(all(outcome["summary_is_provisional"] for outcome in outcomes))
        self.assertTrue(all(outcome["provisional_title"] for outcome in outcomes))
        self.assertTrue(all(outcome["source_mention_ids"] for outcome in outcomes))
        self.assertTrue(all(outcome["source_timestamps"] for outcome in outcomes))
        self.assertTrue(
            all(outcome["transcript_and_narration_references"] for outcome in outcomes)
        )

    def test_cross_source_similar_request_becomes_support(self) -> None:
        candidates = [
            _candidate(1, "Standardize the status bar icon and font sizes."),
            _candidate(2, "Standardize status bar font and icon sizes.", source="source-b"),
        ]
        outcomes = consolidate_candidate_outcomes(candidates)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(len(outcomes[0]["source_mentions"]), 2)

    def test_two_source_example_consolidates_to_seven_outcomes(self) -> None:
        candidates = [
            _candidate(1, "I am going to talk about the review requests."),
            _candidate(2, "Add a search box to the library page."),
            _candidate(3, "Add a search box to the library page. Also show a progress bar during export."),
            _candidate(4, "For example, validate the search box request."),
            _candidate(5, "Supporting example: test that progress bar."),
            _candidate(6, "Rename the Jobs tab to Queue in every menu. Next, standardize the toolbar button heights."),
            _candidate(7, "This is just context about the review flow."),
            _candidate(8, "Add a keyboard shortcut for the trim tool."),
            _candidate(9, "Make the startup splash screen shorter.", source="source-b"),
            _candidate(10, "Correction: make the startup splash screen shorter and skippable.", source="source-b", duplicate_of="ticket-009"),
            _candidate(11, "Standardize the toolbar button heights. Also warn about low disk space.", source="source-b"),
            _candidate(12, "Supporting example: validate the warning behavior.", source="source-b"),
            _candidate(13, "Scratch that: those are multiple tickets for the button height and warning actions.", source="source-b", duplicate_of="ticket-012"),
            _candidate(14, "No other issues.", source="source-b"),
        ]
        outcomes = consolidate_candidate_outcomes(candidates)
        self.assertEqual(len(outcomes), 7)
        self.assertEqual(sum(1 for outcome in outcomes if outcome["source_mentions"][0]["source_id"] == "source-a"), 5)
        self.assertEqual(sum(1 for outcome in outcomes if outcome["source_mentions"][0]["source_id"] == "source-b"), 2)
        self.assertEqual(candidates[0]["outcome_classification"], "transition_setup")
        self.assertEqual(candidates[6]["outcome_classification"], "context_only")
        self.assertEqual(candidates[9]["outcome_classification"], "correction")
        self.assertEqual(candidates[12]["outcome_classification"], "correction")
        self.assertEqual(len(candidates[12]["outcome_ids"]), 2)
        self.assertEqual(candidates[13]["outcome_classification"], "negative_no_ticket")
        self.assertTrue(any(len(outcome["corrections"]) == 1 for outcome in outcomes))
        self.assertTrue(any(len(outcome["source_mentions"]) >= 3 for outcome in outcomes))
        outcome_by_id = {outcome["outcome_id"]: outcome for outcome in outcomes}
        for compound_candidate, required_terms in (
            (candidates[2], ("search box", "progress bar")),
            (candidates[10], ("button heights", "disk space")),
        ):
            self.assertEqual(len(compound_candidate["outcome_ids"]), 2)
            self.assertTrue(
                all(term in compound_candidate["transcript_excerpt"] for term in required_terms)
            )
            for outcome_id in compound_candidate["outcome_ids"]:
                self.assertIn(
                    compound_candidate["evidence_id"],
                    outcome_by_id[outcome_id]["linked_evidence_candidate_ids"],
                )

    def test_replay_mode_keeps_later_observations_text_only(self) -> None:
        candidates = [
            _candidate(1, "Make the alert sound quieter.", source="source-b"),
            _candidate(2, "Use this replay to validate the alert behavior.", source="source-b"),
            _candidate(3, "Make this later observation a ticket.", source="source-b"),
        ]
        outcomes = consolidate_candidate_outcomes(candidates)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(candidates[1]["outcome_classification"], "supporting_validation")
        self.assertEqual(candidates[2]["outcome_classification"], "validation_followup")
        self.assertFalse(candidates[2]["render_eligible"])


if __name__ == "__main__":
    unittest.main()
