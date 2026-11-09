# Technical reference / developer documentation

This page is intentionally separate from operator instructions.

Developer-facing topics include canonical artifact IDs, provisional evidence
clusters, reconciliation, privacy enforcement, batching, rendering cadence,
progress event schema, build identity, package parity, and screenshot refresh.

Generated artifacts use separate logical and physical identities. The logical
identity remains verbose in manifests and reconciliation data. The physical
path is deterministically compacted, with a hash suffix when required, so the
complete artifact path stays within the Windows compatibility budget without
weakening integrity accounting.

Review Media Inbox final-results import uses a versioned JSON contract and
durable `staged`, `accepted`, or `rejected` validation phase. Accepted results
are normalized into `final_results` plus final-stage finding records. Exact
retry reconciles the ledger and preserved validation file; a different
submission cannot silently replace accepted immutable history.

The aggregate Process surface adds queue contract v1, Process result contract
v1, and a checksummed atomic run-journal contract v1 without changing SQLite
schema version 2 or the existing package contracts. `queue-index.json` is a
deterministic reconstruction, not authoritative lifecycle state. External
return paths start absent; stable size/mtime and SHA-256 checks distinguish a
complete candidate from a changing file, generated legacy template, or
unchanged accepted/rejected submission.

Prepared-source manifests remain schema version 1 and add an optional complete
`artifact_inventory`. Frame records add requested and achieved timestamps,
size, SHA-256, and dimensions while retaining `timestamp_seconds` as the
backward-compatible achieved-time field. Legacy manifests without the additive
inventory remain readable, but every artifact they explicitly declare must
still exist in integrity and on disk. Queue reconstruction revalidates source
packages before exposing either preliminary or final external-return paths.

Review Media Inbox's records live in the library, in its `inbox_` tables, with
every ID unchanged from the old ledger. The Inbox's folder stays where it is
(its queue, batches, history, locks and the files the outside agent reads and
writes) and is registered in the library; the **Inbox folder** setting
(`review_inbox_folder`) names it. The old `review_ledger_path` setting is kept,
so an older build finds the note file and stops.

The records move once, at the first start of a build that has this step
(`src/media_manglers/core/inbox_move.py`), under the Inbox's lock. First the
ledger and the library are copied to
`<library>\backups\migrations\<date-time>-wave-b\`, with a list of the Inbox
folder's files by hash, and the settings and profiles; that folder is never
pruned, and its `HOW_TO_RESTORE.txt` says how to put things back. One
transaction copies every table and checks counts, states, fingerprints, links
and counters. Then the original ledger takes a dated name beside a small note
file left at its old name, in one atomic swap, and a receipt
(`MOVE_RECEIPT.json`, and a row in `legacy_imports`) records the numbers. Any
failure up to the swap removes what was imported, and a crash at any point is
finished or undone at the next start. A second run changes nothing. Until the
move is complete the Inbox opens nothing and its page says why in one line, so
no new record can appear ahead of the real ones. An older ledger than version
2 is refused, unchanged. After the move, rules in the library keep what was
accepted: an accepted result is never changed or removed, a retention record is
never removed and changes only where its history is, and a recording is never
removed.

Those records are opened only through the Inbox's store
(`src/media_manglers/core/inbox_records.py`). A reader never writes and
never takes the Inbox's lock or a write lock. It refuses a library that a newer
version moved on, and an Inbox folder other than the one the library registers.
Each helper keeps one library connection, shared by what it opens.
Every command-line action that writes the ledger or the Inbox folder takes the
Inbox's one lock, `<Inbox folder>\.orchestration\process.lock`, first. The
migrate helper and the scan, prepare, repair, import, targeted-evidence and
finalization helpers wait while another run holds it: they try again every
quarter second for up to ten seconds (the Workbench's own short status check
holds it for a moment, and the Workbench writes how long into its log), and
only then are refused with "The Inbox is busy with another run. Try again
when it finishes." The host's standalone TargetedEvidence action waits the same
way; its Process loop, whose lock the app holds itself, never waits. Only
another run holding the lock counts as busy: any other refusal says plainly
what Windows refused. Process and reconcile attach to the run already going,
and the relocation tool keeps its own refusals. The status check, Process
and the command-line writers may start a new Inbox, so their lock makes the
Inbox folder when it is not there yet; the relocation tool, which works on an
Inbox folder that is already there, makes only its `.orchestration` folder and
never the folders of a mistyped path. A stop
request is the one write made without the lock: a signal file for the running
run to read (beside its lock from the command line, in the Workbench's
temporary folder for Stop after current). Helpers the PowerShell host calls
inside its own Process loop, and inside the standalone TargetedEvidence action,
pass `coordinator_lock_held` because the host already holds that lock. A
command-line action that works on existing records (an import, targeted
evidence, finalization, repair) is refused in one plain line when there are no
records for its Inbox folder ("There are no Review Media Inbox records for ...,
so nothing was changed."), before it reads, writes or locks anything. The old Review New
Videos helpers (`review-ledger-lookup`, `-record` and `-match-sha`) are
retired: each refuses with "This old Review New Videos helper was retired; use
Review Media Inbox." and changes nothing.

Every file and folder the Inbox moves, renames, replaces or removes goes
through one helper (`safe_write`). Antivirus scanners, the search indexer and
Explorer thumbnails open a file the app has just written for a moment, and
Windows refuses to rename or delete it, or the folder holding it, until they
let go. The helper waits only for such a hold by another program, up to ten
seconds per step, and names that program when it gives up. A move or removal
never waits for the app itself (the Workbench, the host and helpers it
started, and their children), which stops at once as a fault in the app; a
small file's replace still waits a moment for the app's own reader, as the
host reads the Inbox's progress file every half second. While a folder is
deleted, "the directory is not empty" (a file in it waiting to be deleted
until a scan lets go) is a hold too. Nothing is written over,
a folder moves only within one drive, a file moving to another drive is copied
and checked before the original goes, and a folder to be deleted is renamed to
a trash name first. When another program blocks only the clean-up of a
temporary copy after a step has succeeded, or Windows refuses that clean-up
for any other reason, the result is kept, a plain warning says why, and the
next Inbox run removes the leftover (they are noted
in `<Inbox folder>\.orchestration\leftovers.json`). A trash folder that a crash
left half deleted is on no list; the next clean-up in the same folder removes
it, as only the helper makes those names. No antivirus exclusion is needed or
made.

The Inbox's frame check lists the time of every picture in a recording from
the packets the file already stores (`ffprobe -show_entries
packet=pts_time,flags`), with the same rounding, de-duplication and sorting
as the full frame-by-frame check it replaced; on every recording compared
while it was built the two lists were identical, so packages do not change
for such recordings. Packets the decoder drops (flag `D`) are left out. A
recording whose first kept packet is not a keyframe, or with a packet that
has no time or is marked damaged, is checked frame by frame instead, and
so is one whose screenshot from a packet's time fails or shows another
picture (then the screenshots are taken again only when that list differs).
Both checks, and the audio decode, are followed by
`src/media_manglers/core/streaming_progress.py`: stopped only when nothing
moves for 180 seconds, with a plain reason, and reported as they go (the
frame-by-frame check again, when it must run, under **Rendering neutral
visuals**; with no known length, how far without a percent). Repair uses the
same checks without progress, as it reports none.

Progress events (`MM_PROGRESS_V1`) with `progress_kind` `work_units` carry
`completed`, `total` and `work_unit` (`seconds` of a recording, `bytes`, or
empty for counted items). The PowerShell host relays them with their unit,
keeps 64-bit counts, repeats the last measured state in its heartbeat, and
passes on a new count or a new activity line within the same step. The
Inbox's frame check reports `seconds`, with an activity such as `Checking
the video: 04:12 of 22:30 checked (18%)`.

The PowerShell host finds its own `config.json` under
`MEDIA_MANGLERS_WORKBENCH_APPDATA` when that is set (only tests and test
launchers set it), else under `APPDATA`, so a test Workbench never reads the
real profile's config. The Inbox's progress state file goes through the
host's scratch-folder rule (`MEDIA_MANGLERS_SCRATCH_ROOT`).

`review-media-inbox-repair` is the supported non-orchestration maintenance
command for an inconsistent prepared batch. Its request requires `ledger_path`,
`batch_id`, and `scratch_root`. It automatically identifies invalid source
packages, refuses a batch with accepted or pending external work, retains the
prior package under content-addressed batch-local repair history, and uses a
checksummed repair attempt and journal to resume across staging, promotion, and
ledger-commit crash boundaries. It preserves the existing batch and Process run
and does not scan or allocate sources.

`review-media-inbox-relocate` is the separate supported maintenance command for
adopting a complete generated Review Media Inbox tree after an approved storage
migration. Preview classifies every discovered absolute path as original media,
generated owned, derived runtime, historical/audit, or unknown, and writes a
checksummed immutable plan. Unknown fields fail closed. Original-media paths
remain under their approved read-only roots and are never rebound with
generated storage.

Each generated-root mapping requires a trusted migration record whose own
SHA-256, roots, complete relative-path inventory, sizes, hashes, containment,
regular-file status, and package identities verify against the new tree. The
old generated tree may be absent and is never probed. Apply requires an
explicit confirmation, a matching plan SHA-256, and the Review Media Inbox
process lock. It creates a timestamped backup of the library, uses a checksummed
recovery journal, commits the changes to the Inbox's records and the registered
Inbox folder transactionally, writes planned manifests atomically, regenerates
derived queue projections without importing returns, and verifies the records,
original-path snapshot, and package trees before completing one relocation audit
record. Retry resumes the same operation or returns `already_relocated`; rollback
puts back the rows it changed and the registered folder, leaving every other row
of the library alone, and the manifests and prior derived-projection state. After
a relocation, choose the new folder as the **Inbox folder** in Inbox settings.
Never edit the database, manifests, or journals manually.

Relocation may preserve a separately approved exact package-integrity defect,
but it never repairs that package. The supported
`review-media-inbox-repair` operation remains a later, separately authorized
action.

The optional `exact_source_paths` Process field (PowerShell JSON scalar
`-ReviewInboxExactSourcePathsJson`; packaged Workbench repeatable
`--review-inbox-exact-source`) is a run-scoped qualification restriction. It is
resolved only after the normal complete scan, against the scan's exact path,
canonical path, configured source/recurse boundary, eligibility, source ID,
identity, size, and nanosecond modification time. The selected IDs and bound
identity metadata are checksummed in run-journal v1. Missing, changed,
ineligible, outside-root, over-limit, or All-pending combinations fail closed
before preparation. A guarded full-hash callback also stops a restricted Fast
scan if ledger history would otherwise require completely hashing a
non-allowlisted source. Empty input leaves the ordinary workload algorithm
unchanged. The launch-only paths are excluded from app settings and profiles.

Finalization uses an immutable SHA-256 plan, `finalization_runs` and
`retention_records`, a checksummed phase journal, short content-addressed
batch-local quarantine names, verified retained-history manifests/inventories,
and one final SQLite transaction. Recovery phases are `planned`, `quarantined`,
`history_staged`, `history_promoted`, `ledger_committed`, and
`cleanup_complete`. Every action is resolved beneath the batch, history, or
finalization root; symlinks, path escapes, changed files, and corrupted plans or
journals fail closed.

- Repository truth: [`../../governance/CURRENT_PROJECT_TRUTH.md`](../../governance/CURRENT_PROJECT_TRUTH.md)
- Screenshot refresh: [SCREENSHOT_MAINTENANCE.md](SCREENSHOT_MAINTENANCE.md)

[Previous: Troubleshooting](TROUBLESHOOTING.md) · [Back to Help](README.md)
