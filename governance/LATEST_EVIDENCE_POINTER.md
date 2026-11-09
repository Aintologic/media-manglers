# LATEST_EVIDENCE_POINTER.md

## Status

This repository's canonical current truth is `governance/CURRENT_PROJECT_TRUTH.md`.

Implementation reality is established by the current repository files and Git
state, the test suite, and the packaged build. Detailed validation evidence —
run logs, screenshots, packaged outputs and verification records — is kept in the
operator's local evidence store and is not committed to this repository.

## How to read project state

- Approved scope and intended behavior: `governance/CURRENT_PROJECT_TRUTH.md`,
  then the governing GitHub issue, then the approved plan, then `AGENTS.md`.
- Actual implementation: the current repository files and Git state, the test
  suite results, and the packaged build.

## Repo-safe rule

- Keep machine-local evidence, run logs, screenshots and packaged outputs out of
  the tracked repository unless they are explicitly promoted.
- Do not infer repository truth from an untracked local evidence folder alone.
- `governance/CURRENT_PROJECT_TRUTH.md` remains the highest-precedence truth
  source. This pointer only records where validation evidence currently lives.
