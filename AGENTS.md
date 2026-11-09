# AGENTS.md

## Product identity

For current repository-canonical truth and evidence precedence, read:
- `governance/CURRENT_PROJECT_TRUTH.md`

## Read-first order

1. `governance/CURRENT_PROJECT_TRUTH.md`, including its latest evidence pointer or handoff
2. `AGENTS.md`
3. the governing GitHub issue
4. the approved plan for the scoped work
5. current implementation and validation evidence
6. `README.md` when repository orientation matters
7. `AI_AGENT_INTERACTION_PROTOCOL.md`
8. `governance/FOREGROUND_VISUAL_WORK_PROTOCOL.md` when the pass includes visible desktop or UI work
9. `.gitignore` when local-only material, artifacts, or output handling matters

## Non-negotiable product decisions

- Do not contradict `governance/CURRENT_PROJECT_TRUTH.md`.
- Do not introduce new architecture or workflows without explicit approval.
- If `governance/CURRENT_PROJECT_TRUTH.md` is still in template state, treat truth initialization as the first task.

## Current operator contract

- Optimize for operator usability, clarity, and safe execution.
- Prefer simple, explainable behavior over clever or complex design.
- Treat the operator as the decision-maker for the project, not as a programmer.
- Keep the primary report in plain English.
- Put implementation detail after the plain-English outcome.

## Operator approval and agent execution

- The operator approves goals, scope, merges, releases, deployments, cleanup, and destructive or difficult-to-reverse actions.
- After approval, the selected AI agent performs the approved repository, GitHub, merge, release, deployment, or cleanup action unless the operator explicitly asks to perform it manually.
- Do not hand routine development execution back to the operator when the agent can perform it safely within the approved scope.

## One engine, four features

- The Workbench is one engine with four features (see "What the Workbench does" in `governance/CURRENT_PROJECT_TRUTH.md`).
- A shared job (words to spell right, narration-track choice, invented-line filters, Whisper loading, audio extraction, screenshots, queue controls, ZIP building, the output-folder check, warning and status rules) exists once. Do not write a second copy; extend the shared one.
- Every feature that can use a shared job gets it by default; a feature turns it off only with a reason stated in the project truth.
- A fix to a shared job is not done until every feature that uses it has it.
- One main setting per job. A feature may override it, and the app shows "Using main setting" or "Overridden" next to it. No feature keeps its own copy of a shared setting.
- A wave is not done until `governance/CAPABILITIES.md` matches the code: every feature, screen and shared part, where it lives, and which features use it.

## UI rules

- `governance/UI_RULES.md` is the rule every change to the Workbench's screens follows: its colours,
  text sizes, spacing, button kinds, feedback where you click, job banners, step bars, selection
  style and left menu. Check a changed screen against its section 10 before calling it done.
- The shared parts it names live once, in `src/media_manglers_workbench/ui_parts.py` and the theme
  in `src/media_manglers_workbench/theme.py`. Use them; do not draw a second copy on a page.

## Decide, do not ask

- Do not stop to ask the operator a question you can reasonably decide yourself. Make the call, keep going, and list every call in the final report under "Calls I made", one line each.
- Stop only for:
  1. something that cannot be undone: deleting, force-pushing, closing an issue that is not part of the current wave, or anything that touches the drive holding the operator's recordings;
  2. a change the operator would notice in the app that is not in the approved plan;
  3. the end-of-wave test.
- On a blocker, pick the safest option, note it in the report, and continue.

## Complete deliverable rule

When revising instructions, playbooks, protocols, configuration, documentation, prompts, code, or other structured text:

- provide the complete replacement file or complete replacement block
- do not ask the operator to merge line edits unless explicitly requested
- provide exact filenames and replacement steps
- create downloadable artifacts when the current surface supports them
- provide a short checklist when multiple files must change

## Current release-candidate rule

- Do not redefine previously validated behavior without explicit approval.
- New work should build incrementally and be testable.

## Work tracking rules

GitHub Issues are the sole authoritative tracker. Work is delivered in waves, as defined in `governance/CURRENT_PROJECT_TRUTH.md` (Work Tracking).

- Do not create or maintain `TODO.md` or another parallel work board.
- Every execution pass names its wave parent issue. Verify the parent issue and approved scope before implementation.
- A wave is one operator-testable result on the operator's own recordings. Every open issue that blocks or hurts that result belongs in the wave: one branch, one pull request, one approval, one build at the end.
- Found mid-wave and part of the same result: fix it inside the wave and list it in the wave pull request and on the parent checklist. Do not open a separate issue or pull request for it.
- Found mid-wave and not part of the result: do not fix it and do not file it. Add one line under "Parking lot" in the wave report. Exception: data loss, a crash or a security problem — stop and tell the operator.
- Mid-wave, stop for the operator only for a decision that changes existing behaviour or cannot be undone, and batch those questions into one stop.
- If in-wave fixes would push the wave past double its approved effort estimate, stop and re-scope with the operator before continuing.
- Agents propose the next wave; the operator picks it. Creating, closing or commenting on issues still needs the operator's approval.
- Branches, commits and pull requests reference the parent issue. At the end of the wave, post one concise update on the parent issue.
- Keep a child issue open until its own acceptance is met; a merged "Fixes" line that closes an issue early is reported and the issue reopened with approval.
- If GitHub access is unavailable, do not create a substitute tracker. Continue only already-approved wave work when safe and report pending issue updates.

Historical plans and Git history preserve earlier `TODO.md` records. Current governance supersedes those old tracking instructions.

## Authority by purpose

Authorized scope and intended behavior are controlled by:

1. `governance/CURRENT_PROJECT_TRUTH.md`
2. the governing GitHub issue
3. the approved plan
4. `AGENTS.md`

Actual implementation and verification are controlled by:

1. current repository files and Git state
2. validation evidence
3. pull request and merge records
4. package, tag, and release records
5. AI-agent reports

Do not claim completion based only on an issue, plan, or agent statement.

## Local-only workspace rules

- `AREA51/` at repository root is the local-only working folder.
- Treat anything in `AREA51/` as non-canonical local input unless explicitly promoted.
- Never stage, commit, mirror, or summarize sensitive `AREA51/` content into tracked code, docs, issues, pull-request text, or releases without explicit approval.
- If a pass depends on `AREA51/`, describe that at a high level without exposing secrets.
- Do not hard-code machine-local paths into tracked repository docs unless explicitly approved.

## Machine-local rules

- One computer's own setup (its worktree and test-runtime setup, local test data, private checks) is kept out of the repository, in a git-ignored `AGENTS.local.md` at the repository root.
- If `AGENTS.local.md` exists, read it before starting work and follow it. It never overrides this file or `governance/CURRENT_PROJECT_TRUTH.md`.
- Never commit it, and never copy its contents into tracked files, issues, pull requests or releases.

## Privacy check

- The privacy check in `tools/privacy/` must pass before a push. GitHub Actions runs it on every pull request and push; `tools/privacy/README.md` explains how to run it and how to install it as git hooks.
- A finding in an earlier commit stays in history even after a later commit removes it: rewrite that commit before pushing.

## Local evidence and temp workspace assumptions

- The machine-local evidence root differs between machines. Do not assume one,
  and do not hard-code one here. Ask the operator which folder to use on the
  machine you are running on.
- A drive that holds the operator's recordings is read-only. Never write to it,
  including for evidence, even when a document elsewhere names a folder on it.
- All agent scratch work stays inside the repository, under `AREA51/TEMP/`: temporary files, test and validation output, local builds and their build environments, logs, and drafts.
- Never write agent work files to the system temporary folder (`%TEMP%`) or any other machine-level scratch location the operating system may purge. Keep agent work under `AREA51/TEMP/` inside the repository, so nothing is lost to such cleanup.
- The only exception is short-lived intermediates the app itself creates and deletes during a single run.
- Recorded media is read-only input. Never write next to the source recordings.
- These locations are local-only working areas, not canonical repository truth. Do not mirror their contents into tracked docs unless explicitly approved.

## Visual and foreground work rules

- Follow `governance/FOREGROUND_VISUAL_WORK_PROTOCOL.md` for visible desktop or UI work.
- Do not assume machine-specific helper scripts or GUI docs exist unless tracked in the repository.
- Keep machine-specific helper paths and low-level desktop automation detail out of tracked docs unless explicitly approved.

## Mode and handoff discipline

Before preparing or executing an AI-agent prompt:

- identify the selected agent
- recommend the operating mode
- recommend the model and effort
- recommend permission/access settings when relevant
- keep labels in normal text and bold the selected values
- tell the operator exactly where or how to select the mode before pasting

Mode guidance:

- **Plan Mode**: analysis and plan only; no implementation.
- **Execute Mode**: bounded implementation after approval.
- **Goal Mode**: longer, well-defined, multi-stage work only when the selected agent supports it and success criteria and safety boundaries are already clear.
- Do not use Goal Mode to bypass planning.
- Do not claim Claude Code or another agent has a Codex-specific mode unless that client explicitly provides it.
- If no named mode exists, use **Normal interactive mode**.

## Working rules for AI coding agents

Before major code changes:

1. review the newest evidence pack
2. read the governing GitHub issue
3. compare with legacy references when behavior is disputed
4. confirm the approved scope and plan
5. state assumptions
6. implement only the approved task
7. validate proportionately
8. update the GitHub issue
9. report the outcome in plain English before technical details
10. state what remains blocked or unverified
11. give the exact next gate or decision

Do not hide unrelated defects inside another issue.

Do not broaden scope without explicit approval.

If a feature is not trustworthy, say so plainly.

## Agent final-report format

Every final report should include:

### Outcome
Plain-English summary.

### What changed
Behavior and operator-visible impact.

### What remains
Required unfinished work, risks, or limits.

### Validation
What was actually tested or verified.

### Safety
Whether real data, originals, main, releases, or public material were affected.

### Next gate
The exact approval or next pass required.

### Technical record
Governing issue, branch, commits, files, and detailed test information.

## Additional settled rules

- Repository governance docs are the canonical current-truth source.
- GitHub Issues are the sole authoritative work tracker.
- External and local evidence is reference-only unless explicitly promoted.
- Prefer clarity over completeness.
- Do not guess when evidence is missing.
- If GitHub issue state, repository state, validation evidence, or agent claims disagree, reconcile them explicitly and call out the mismatch.
