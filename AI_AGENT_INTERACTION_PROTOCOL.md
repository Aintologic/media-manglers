# AI_AGENT_INTERACTION_PROTOCOL.md

## Purpose

This document defines the durable handoff workflow for AI coding agents used on this project, including Codex and Claude Code.

The repository remains the canonical implementation record.

GitHub Issues are the sole authoritative work tracker. Agent chat, planning text, local notes, branches, commits, and status claims support the issue but do not replace it.

## Handoff and operating modes

Every substantial AI-agent handoff must name the recommended mode.

Project handoff labels:

- `PLAN MODE`
- `EXECUTE MODE`
- `GOAL MODE` when the selected agent actually supports a goal-oriented mode

### Plan Mode

Use Plan Mode when:
- architecture is changing
- scope is broad or unclear
- the work is high-risk
- evidence conflicts
- major decisions remain unresolved
- destructive or difficult-to-reverse actions may occur
- the operator needs to approve an approach before changes begin

Plan Mode must not implement repository changes.

### Execute Mode

Use Execute Mode for a bounded implementation pass after the plan or scope is approved.

`EXECUTE MODE` is the project's implementation label. If the selected agent calls its normal implementation surface something else, tell the operator the exact client control or message box to use.

### Goal Mode

Use Goal Mode only when:
- the selected agent currently supports it
- the desired outcome is clear
- success criteria are explicit
- boundaries and exclusions are explicit
- the work may require multiple coordinated steps
- it is safe for the agent to continue toward completion without repeated prompting
- no unresolved high-risk decision requires operator approval

Do not use Goal Mode to bypass planning.

For Codex, Goal Mode may be recommended for a longer, well-defined outcome after scope and safety boundaries are settled.

For Claude Code, do not claim a Goal Mode exists unless the current client explicitly provides one. Use Plan Mode or an approved Execute Mode handoff and state the separate permission mode when relevant.

For other agents, use their actual current mode names. If no named mode exists, use **Normal interactive mode**.

## Agent selection

Choose the AI coding agent best suited to the specific task.

Do not automatically prefer Codex or Claude Code.

The handoff recommendation must state:
- Recommended agent
- Recommended mode
- Recommended model
- Recommended effort
- Recommended speed, when applicable
- Recommended permission mode, when applicable
- Required access level, when applicable
- Reason

Formatting:
- Keep field labels in normal text.
- Bold the selected values for agent, mode, model, effort, speed, permission mode, and access level.
- The reason may remain normal text.

## Operator approval and agent execution

- The operator approves goals, scope, merges, releases, deployments, cleanup, and destructive or difficult-to-reverse actions.
- After approval, the selected AI agent performs the approved repository, GitHub, merge, release, deployment, or cleanup action unless the operator explicitly asks to perform it manually.
- Do not hand routine development execution back to the operator when the agent can perform it safely within the approved scope.

## Work tracking

GitHub Issues are the sole authoritative tracker. Work is delivered in waves, as defined in `governance/CURRENT_PROJECT_TRUTH.md` (Work Tracking) and `AGENTS.md` (Work tracking rules).

- No manually maintained `TODO.md` or other parallel tracker may exist.
- A wave is one operator-testable result on the operator's own recordings, with one parent issue whose checklist links its child issues. The operator approves creating it.
- Every execution pass names its wave parent issue. Before implementation, verify that the parent issue exists, is open, and matches the approved scope.
- Plans link to the parent issue. Branches, commits and pull requests reference it.
- Every open issue that blocks or hurts the wave's result is fixed inside the wave: one branch, one pull request, one approval, one build at the end.
- Found mid-wave and part of the same result: fix it inside the wave and list it in the wave pull request and on the parent checklist. Do not open a separate issue or pull request for it.
- Found mid-wave and not part of the result: do not fix it and do not file it. Add one line under "Parking lot" in the wave report. Exception: data loss, a crash or a security problem — stop and tell the operator.
- Mid-wave, stop for the operator only for a decision that changes existing behaviour or cannot be undone, and batch those questions into one stop.
- If in-wave fixes would push the wave past double its approved effort estimate, stop and re-scope with the operator before continuing.
- Agents propose the next wave; the operator picks it. Creating, closing or commenting on issues still needs the operator's approval.
- At the end of the wave, add one concise update to the parent issue. Keep a child issue open until its own acceptance is met.
- If GitHub is unavailable, do not create a substitute tracker. Continue only already-approved wave work when safe and report pending issue updates.

Historical plans or records that mention `TODO.md` are not active tracking authority. Do not rewrite approved historical documents silently.

## Authority by purpose

Approved scope and intended behavior are controlled by:

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

Do not treat planned or reported work as implemented without repository evidence.

## Default working assumptions

Unless the operator says otherwise:
- use VS Code or the agent's normal repository workspace
- keep repository work PowerShell-friendly and beginner-friendly
- prefer safe automation over manual edits
- preserve current validated behavior
- avoid destructive actions without explicit approval

Do not hard-code a model version as a permanent default. Recommend the best currently available model for the task.

## Plan handling

- Approved plans should be recorded as dated Markdown files, linked from the governing GitHub issue. Keep development-history plan files in the project's private working area rather than committed to this repository, unless a higher-precedence location is explicitly selected.
- Plans must name and link the governing GitHub issue.
- The approved plan file must be named at the beginning of the execution pass.
- If a plan is superseded, record that explicitly rather than silently rewriting history.
- Do not implement while the agent is still waiting for plan approval.

## Execute handling

In `EXECUTE MODE`:
- name the governing GitHub issue
- name the approved plan file
- verify the current branch, workspace state, and relevant upstream state
- stay inside approved scope
- update the issue when work starts if status or scope needs clarification
- add a concise issue update when the pass ends
- report blockers, risks, failures, and unverified items plainly
- do not hide unrelated defects inside the current issue
- do not broaden scope without explicit approval

## Operator-facing approval handling

When the agent displays a decision screen, permission request, or numbered choice, the Project Navigator must first tell the operator exactly what to select.

### Codex

- Identify whether Codex is in Plan Mode, Execute Mode, Goal Mode, waiting for plan approval, requesting access, waiting for input, completed, failed, or interrupted.
- State the recommended mode in bold before the prompt.
- When Codex shows numbered plan-approval choices, name the exact numbered option.
- Use “Tell me what to do differently” only for plan amendments.
- Do not paste an execution or goal prompt while Codex is still waiting for plan approval.
- After an amended plan is returned, tell the operator whether to approve implementation or request another change.
- When Goal Mode is recommended, tell the operator to select **Goal Mode** before pasting and explain the intended outcome and completion criteria.

### Claude Code

- Identify whether Claude Code is in Plan Mode, an approved Execute Mode handoff, or is asking for permission, clarification, plan approval, command approval, repository access, or execution confirmation.
- State the recommended project mode in bold.
- State the recommended Claude Code permission mode in bold when relevant.
- Tell the operator the exact response or permission choice.
- Do not use Codex-specific button names or Goal Mode assumptions for Claude Code.
- Do not grant broader permissions than the approved scope requires.

## Complete deliverable rule

When an AI agent is asked to revise instructions, playbooks, protocols, configuration files, documentation, prompts, or code:

- produce the complete replacement file or complete replacement block
- do not require the operator to merge line edits
- provide exact filenames and replacement instructions
- provide downloadable artifacts when the current surface supports them
- provide a short checklist when multiple files must change

Diffs may be included as a technical record, but they are not the primary operator deliverable unless explicitly requested.

## Evidence handling

Use `governance/CURRENT_PROJECT_TRUTH.md` to locate the latest evidence pointer or handoff. Apply the **Authority by purpose** rules above when deciding whether the question concerns approved scope or actual implementation.

Agent scratch work stays inside the repository, under `AREA51/TEMP/`, as
`AGENTS.md` requires. Never write agent work files to the system temporary folder
(`%TEMP%`) or any other machine-level scratch location the operating system may
purge — anything left there can be lost without warning.

Where a machine provides a dedicated evidence workspace, `AGENTS.md` names it.
Read that file rather than assuming a path here.

Treat machine-local evidence and temp paths as reference-only unless explicitly promoted into tracked repository documentation.

Do not place machine-local absolute paths into tracked repository docs unless explicitly approved.

## Project-source mirror discipline

When a repository governance document, protocol, or approved plan is mirrored into project sources:

- the project-source copy must match the tracked repository text exactly
- do not keep competing active variants such as `.updated`, `.new`, duplicate-numbered copies, or replacement fragments
- drafts and superseded material should be clearly archived or removed
- when repository and project-source copies disagree, the repository copy wins and the project-source mirror must be refreshed

## Agent final-report requirement

Every AI coding agent should return a final report containing:

1. **Outcome in plain English**
2. **What changed**
3. **What this means for the operator**
4. **What remains**
5. **Validation performed**
6. **Safety and operational impact**
7. **Exact next gate or decision**
8. **Technical record**, including issue, branch, commits, files, and test details

The plain-English outcome must come before technical detail.

The report must clearly state whether:
- real media or private data was accessed
- originals were modified, moved, renamed, or deleted
- main changed
- a pull request was created or merged
- a package, tag, or release was created
- destructive actions occurred
- private information entered public or tracked material

## Failure and interruption handling

If an agent or machine is interrupted:
- do not assume work completed
- inspect repository and process state
- identify what is durable and what is partial
- do not discard or reset work automatically
- explain the recovery choice before acting
- treat uncertain state as unverified

## Final rule

Prefer clarity over completeness.

Do not guess when evidence is missing.

If repository truth, GitHub issue state, current implementation, validation evidence, and agent claims disagree, call out the mismatch and follow the highest-precedence evidence.
