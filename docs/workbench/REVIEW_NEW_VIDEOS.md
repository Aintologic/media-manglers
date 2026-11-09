# Review Media Inbox

Use **5 Review Media Inbox** to prepare a local, resumable queue for external
Codex review. Original recordings are read-only: Media Manglers never modifies,
moves, renames, or deletes them.

## One-click operator flow

The normal workflow is:

1. Open **Review Media Inbox**.
2. Choose **Next 3**, **Up to N**, or **All pending**.
3. Select **Process new media**.
4. If a genuinely new ambiguous audio layout is found, choose the microphone
   track once. Processing resumes automatically.
5. When work is ready, use **Open Codex review queue** or **Copy Codex prompt**.
6. Return later and select **Process new media** again. Media Manglers detects
   stable valid files written by external Codex and continues automatically.
7. If review completed with disposable no-findings evidence, choose once whether
   to keep it or remove it. Keeping generated evidence is the safe default.

Opening the page performs only lightweight reconciliation. It may recover
already-started journals and recognize stable external returns, but it does not
scan new source folders, run FFmpeg or Whisper, render targeted media, or show a
cleanup decision merely because Workbench opened.

If required folders are not configured, use **Inbox settings**. A blank
**Evidence root** uses the main **Default output folder**, and a blank
**Scratch / work root** uses the app's temporary folder; beside each, the
dialog says **Using main setting** or **Overridden**. Processing
remains disabled until the page can explain which setting is missing.

If the app's library cannot be opened when Workbench starts (a damaged or
locked file, or a library a newer version moved on), Workbench says so once
when it starts. That session the Inbox page says the same in one line,
**Process new media** stays unavailable, and nothing in the Inbox folder is
started or changed. The next start that opens the library brings the Inbox
back as it was.

## Workload choices

**Next 3** is the default and recommended choice. It assigns no more than three
newly eligible sources.

**Up to N** accepts a whole number from 1 through 9,999 and defaults to 10.

**All pending** first builds one fixed oldest-first snapshot. Before any newly
eligible source is prepared, Workbench shows its source count, aggregate bytes,
scratch and evidence free space, largest-source temporary estimate, and a time
estimate when enough recent history exists. Cancelling the confirmation prepares
no new source.

Larger workloads are divided internally into batches of at most three sources,
but those batches are not an operator task. Existing recovery, external returns,
targeted evidence, and finalization always take priority and consume none of the
new-source budget. Files that appear after a run's snapshot wait for the next
run.

Processing is sequential. The 240-minute limit is a soft source boundary: the
current source finishes safely, then the run pauses before starting another.
**Stop after current** uses the same safe boundary and leaves the exact snapshot
and remaining quota resumable. It does not kill FFmpeg, Whisper, targeted
rendering, or finalization in the middle of an action.

## Fast and Full

Fast is the normal default. Full hashes every stable source in the configured
inventory and may read multiple terabytes, take a long time, and place sustained
load on source drives. Workbench requires a fresh confirmation for every Full
run. A saved setting never suppresses that warning.

## Narration audio

Audibility is checked before any microphone decision. Media Manglers samples
speech-dense regions from every audio stream. A stream whose bounded regions
have no meaningful signal is then decoded completely through a bounded-memory
pipe; no full-source WAV is retained. Exact digital zero is silent, extremely
low codec noise is ignored, quiet meaningful signal is preserved, and values
between the documented noise and audible boundaries stop as **Needs attention**
instead of guessing.

If every complete audio stream is silent or below that conservative noise
floor, the source is recorded as **No audible narration**. Workbench does not
show the microphone dialog, does not create a layout confirmation, and does not
run Whisper. The package contains an explicit
`not_applicable_no_audible_narration` transcript status, complete stream and
audibility metadata, neutral visual evidence, warnings, and integrity records.
The visual-only source still enters the Codex review queue and the same fixed
workload run continues.

No-audio sources, one genuinely audible safe track, and exact saved layout
fingerprints that still point to an audible stream proceed unattended. When
several tracks are audible and no saved answer applies, the shared voice
detection chooses the narration track, the same way Full Review and Find my bug
reports do, reading track names and the main **Narration track** setting
(Settings > General). Its transcript then goes through the same invented-line
filters. Only when the detection cannot tell does the source open one dialog
titled **Which track contains your microphone?**

The dialog identifies the source and lists one-based track choices, available
metadata and the places in each track where the inspection heard speech.
Silent and inconclusive tracks are labelled. **Play in the player** opens the
built-in player on top of the dialog, on that track, at the chosen place, with
**Next speech** and **Previous speech** between the places the inspection found,
and the waveform of every track. Close the player to come back to the dialog. **Use this track** stays
disabled until you have played that track and the inspection found it audible:
a recommendation alone never confirms anything, and a silent or inconclusive
track can never be confirmed. Primary status text does not expose private paths.

**Use this track** stores the exact audible layout confirmation and resumes the
same run. **Stop processing** or closing the dialog leaves the source safely
paused. Nothing in the dialog chooses a track on its own.

Workflow 3 keeps its existing New Review audio behavior. Workflow 5 does not
route through the New Review wizard.

## Codex review queue

The queue uses the **Inbox folder** in Inbox settings. It contains one
deterministic queue index and prompt plus references to the existing validated
batch packages. It does not duplicate source media or large evidence.

**Ready for Codex review** means a compact initial package awaits preliminary
review. **Additional local evidence** means a valid bounded request is queued or
being rendered. **Waiting on Codex** means requested local evidence is ready and
final results are awaited. **Done** counts terminal finalized sources.
**Manual review available** means retained non-final evidence is still available
to the operator; it is counted separately from **Done** and does not disable
processing of unrelated eligible media.

The queue prompt instructs external Codex to:

- review every active queued source;
- inspect relevant repositories and open and closed GitHub issues;
- distinguish bugs, requested features, completed work, duplicates, and
  supporting evidence;
- create or update issues only with operator authorization;
- write bounded additional-evidence requests and final structured results to
  the exact listed return paths;
- never edit source identities, manifests, integrity records, the ledger,
  original media, or internal orchestration files.

Return paths are absent until external Codex writes them. Media Manglers ignores
temporary or changing files, verifies stable size and modification time, and
validates the complete contract before advancing lifecycle state. An unchanged
accepted or rejected file is never processed repeatedly. One stable invalid file
produces one **Needs attention** message keyed to its content; replacing it with
changed content causes a fresh validation.

Working filenames from older versions remain compatible. A legacy generated template
is never accepted as an external submission.

## Visual timeline integrity and repair

Timeline positions come from unique frames that FFprobe can actually decode,
not only from the container's rounded nominal duration. Short recordings may
therefore contain fewer than the usual preferred six timeline frames. Media
Manglers preserves chronological order and never creates duplicate copies just
to reach a preferred count.

The times come from the packets the recording already stores, so the check
reads the file once without unpacking every picture, and **Validating source**
shows how far it has got (for example `Checking the video: 04:12 of 22:30
checked (18%)`). A recording whose packets cannot all be timed, or whose
screenshot from a packet's time fails, is checked picture by picture instead,
as before. The check stops only when nothing moves for three minutes (a drive
gone to sleep or disconnected), never for taking long.

Each rendered frame must exist, be non-empty, decode as an image at the expected
dimensions, and report its achieved timestamp before it can enter a source
manifest. The manifest describes only successfully produced artifacts.
`integrity.json` can report `complete: true` only when the source manifest,
integrity inventory, sizes, SHA-256 values, and actual contained files agree
exactly. An incomplete or inconsistent source package is not shown as **Ready
for Codex review**, even if an older integrity file claimed it was complete.

The supported repair action detects inconsistent source packages within an
existing batch. It rechecks the affected original against its complete identity,
retains the prior generated package in deterministic repair history, regenerates
only the affected visual package in bounded staging, verifies it, promotes it
atomically, and updates lifecycle state transactionally. Valid peer sources are
not rerendered, no new source is assigned, and the original remains read-only.
Interrupted and repeated repair calls resume the same recorded repair instead of
creating duplicate attempts, events, frames, or history directories.

## Moving generated queue storage

Generated Review Media Inbox storage can be moved independently from original
media. Original recordings may remain on a different read-only volume; moving
the generated queue never requires copying or rebinding them.

Relocation is an explicit maintenance operation and is never part of
**Process new media**. First run the supported
`review-media-inbox-relocate` command in preview mode with the Inbox folder, explicit
old/new generated-root mapping, approved original-media roots, and trusted
migration record. Preview verifies the complete adopted destination and writes
an immutable plan with an operator-readable count summary. Apply requires that
exact plan and an explicit confirmation.

Apply creates a timestamped backup of the library and a recovery journal, changes
only classified generated-owned records, refreshes active generated manifests, and
regenerates the queue index and prompt. A retry safely finishes the same
operation or reports that it is already relocated. A supported rollback puts back
the records it changed, the manifests, and the prior queue-projection state, and
leaves the rest of the library alone. After a relocation, choose the new folder as
the **Inbox folder** in Inbox settings.

Do not edit SQLite, manifests, or journals manually. Relocation does not render,
transcribe, review, finalize, clean up, or assign media. If an existing package
has a known frame-integrity defect, relocation preserves that truth; the
separate supported repair operation still requires its own approval afterward.

## Targeted evidence

A valid preliminary request may ask for bounded frames, supported panel crops,
or selected-audio context. Media Manglers revalidates the preserved submission,
source identity, prepared integrity, timestamps, and complete current source
SHA-256 before rendering only the requested material through the existing
Workflow 3 adapter.

Default compact preparation records supported panel definitions but does not
eagerly render panel crops. It also does not retain a complete source copy or an
extracted full WAV. Completed targeted requests are integrity-checked and are
not rendered again after a retry or relaunch.

## Final results and cleanup

External Codex remains responsible for semantic review and any
operator-authorized repository or GitHub work. Media Manglers validates complete
final results and automatically retains full evidence for issue-related,
already-implemented, duplicate/supporting, uncertain/manual-review, and
failed/retryable outcomes.

Only confirmed no-findings sources can contribute disposable generated
evidence. If their aggregate disposable size is zero, finalization continues
without a dialog. Otherwise Workbench asks once:

> Review is complete. Remove X of temporary generated evidence? Original
> recordings will not be touched.

**Keep generated evidence** retains the complete package and is the safe
default. **Remove temporary evidence** performs only the existing bounded,
hash-checked, journaled generated-file actions. The ordered plan hashes and
decision are persisted before execution, so a crash resumes the identical
decision without another prompt. A changed plan requires a new confirmation.

Original paths and parent folders are never cleanup targets. Mixed batches stay
truthful: uncertain sources remain `needs_manual_review`, failures remain
retryable, and only terminal sources contribute to **Done**.

## Technical details and compatibility

The primary page intentionally does not expose lifecycle labels, source IDs,
contracts, hashes, raw JSON, helper commands, or manual stage buttons.
**Technical details** opens a separate read-only diagnostics dialog for paths,
IDs, logs, hashes, and recovery information.

Legacy Scan, Prepare, preliminary import, targeted render, final-results import,
preview, and Finalize commands remain available to existing CLI consumers. A
headless legacy invocation still defaults safely to Scan. Workbench explicitly
uses the aggregate Process contract. Every one of these commands that writes
takes the Inbox's lock first, as Process does. While another run holds it, the
command waits up to ten seconds for it (the Workbench's short status check
holds it for a moment); if it is still held, the command changes nothing and
says: "The Inbox is busy with another run. Try again when it finishes."

Acceptance and qualification automation may launch Workbench with the
repeatable `--review-inbox-exact-source` argument. This is an advanced,
run-scoped safety boundary, not a normal workload choice: Workbench shows only a
path-free restricted-run banner and disables **All pending**. Process performs
the complete configured-folder scan first, admits only exact eligible matches
inside the configured source/recurse boundary, records their scanned IDs and
identity metadata in the checksummed journal, and never falls back to ordinary
Next 3. The restriction survives Stop/relaunch until those sources reach a
terminal review state. It is not saved in settings or profiles.

[Previous: Archive Catalog](ARCHIVE_CATALOG.md) · [Back to Help](README.md) · [Next: Dependencies and setup](DEPENDENCIES_SETUP.md)
