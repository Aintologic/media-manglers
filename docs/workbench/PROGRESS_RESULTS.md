# Progress and results

## While a review runs

- **Queue size** is the number of real source files.
- **Current item** and **Stage** say what is active.
- **Overall** and **Current stage** use determinate percentages only when the
  backend supplies trustworthy totals.
- **ETA** says `Unavailable` when it cannot be calculated honestly.
- **Technical details and processing log** contains commands and raw diagnostics.
- For every run (Full Review, Transcript Only, Find my bug reports and Review
  Media Inbox), **Pause** / **Resume** frees the PC until you are ready, and
  **Skip selected** (or right-click a row, **Skip this recording**) skips
  recordings, including the one being worked on. A skipped recording is not a
  failure, and a run you paused still ends **Complete**. Review Media Inbox
  sees a skip at the next step of the recording it is preparing, and that
  recording waits for a later run. See [Find my bug reports](FIND_BUG_REPORTS.md).

For Review Media Inbox, **Stop after current** is cooperative. The active source,
targeted request, or journaled finalization action reaches its safe boundary,
but no additional work starts. The fixed workload snapshot and remaining quota
stay resumable. The primary page remains visible and uses only **Processing**,
**Ready for Codex review**, **Waiting on Codex**, **Needs audio choice**,
**Manual review available**, **Needs attention**, and **Done**.

`Completed`, `Failed`, `Skipped`, and `Cancelled` are terminal item states.
**Skipped** means you skipped it. A recording the run never started, after
**Cancel review** or after a failure, says **Cancelled**, as the headline does
after a Stop.
Phase text such as `Transcription complete` does not make a source Completed.
Review Media Inbox additionally reports blocked and retryable source counts and
keeps unavailable current-stage percentages indeterminate. While it checks a
recording's video, **Current stage** says how much of the recording is checked,
for example `04:12 of 22:30`. Its **Source** is always **Configured folders**:
it reads the folders in its own settings, never New Review's source box.

The job banner on the page that started a run shows its percent and time left
when they are known. While nothing is measured yet, it shows what the run is
doing instead, never a frozen `0%`.

## When the review settles

Read the result sentence first. Use **Open output** for the selected folder or
**Open evidence package** when a valid package was produced. A warning can be
non-blocking; failed integrity is always blocking.

On long Windows folder trees, generated physical file and folder names may be
shortened deterministically to stay within the supported path budget. Package
manifests keep the full logical source and artifact identity, so a shortened
physical name does not mean the source was renamed or evidence was discarded.

Review Media Inbox keeps raw lifecycle names in **Technical details**. On the
primary page, **Ready for Codex review** means the compact initial package awaits
preliminary review. **Additional local evidence** means a valid request is
queued or rendering. **Waiting on Codex** means requested evidence is ready and
final results are awaited. **Done** counts terminal finalized sources.
**Manual review available** reports retained non-final items separately and does
not prevent unrelated new media from being processed.

`targeted_evidence_ready` means every accepted request has a complete manifest
and verified artifacts, sources without requests have explicit accounting, and
the refreshed Codex prompt is ready. It still does not mean final results were
imported or the batch was finalized.

`results_received` means one complete immutable final-results submission passed
source coverage, identity, timestamp, disposition, issue-reference, and targeted
evidence revalidation. Rejected results do not change lifecycle state or permit
cleanup.

`finalizing` means an explicitly confirmed hashed plan has a durable recovery
journal. The Workbench shows the current quarantine/history/ledger phase and can
resume the same plan after interruption. Disposable quarantine is never removed
before retained history and the SQLite commit are verified.

`finalized_no_findings` and `finalized_with_findings` are terminal successful
states. `needs_manual_review` remains non-final, is not counted as **Done**, keeps
its evidence, and does not block unrelated eligible sources. `retryable_failure`
remains non-final and blocks continuation until its existing recovery path is
resolved. **Open retained history** remains available after a finalized batch
leaves the pending-batch list.

[Previous: Dependencies and setup](DEPENDENCIES_SETUP.md) · [Back to Help](README.md) · [Next: Settings and migration](SETTINGS_MIGRATION.md)
