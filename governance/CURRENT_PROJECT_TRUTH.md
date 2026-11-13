# CURRENT_PROJECT_TRUTH.md

## Purpose

This document defines the canonical current truth for the project.

If active project content disagrees, this document controls approved scope and intended behavior.

---

## Product Identity

Media Manglers started as a practical way to break video and audio into pieces that AI can review more accurately.

It was first built for sim racing. High-frame-rate footage moves fast, and generic AI video review kept missing the details that actually mattered. When the goal was to understand a braking zone, a side-by-side corner entry, or the difference between one lap and another, handing AI one giant video file usually produced broad summaries instead of useful review.

It was built by describing what it should do to AI and testing every step, with no traditional programming background required. That's the AÏntologic idea: describe it, build it. Getting there took a lot of iteration, re-explaining, and course-correcting until the outputs matched the review workflow it was meant to serve. What mattered was solving a real problem: collaborating with AI to review video footage.

Instead of treating media like one giant blob, Media Manglers turns it into a review package: proxy media, extracted frames, audio, transcripts, optional translations, comments exports, and optional upload-ready bundles for AI review.

The workflow turned out to be useful well beyond sim racing, for anyone who needs to inspect, summarize, translate, and hand off media without juggling five different utilities.

Media Manglers is a multi-purpose application, and it grows by adding capabilities. Alongside review packages for AI, it can turn a narrated recording into something to share: an edited video that tells the story of a session, with an external AI agent making the editorial decisions and Media Manglers doing the analysis and the rendering. Each new capability joins the same application; none replaces the ones before it.

That is what this project does: it turns messy, fast-moving media into something you can review on purpose.

---

## Current State

- Project stage: alpha
- Known limitations: Requires PowerShell
- Latest evidence pointer or handoff: `governance/LATEST_EVIDENCE_POINTER.md`
- Approved workflow: Video Mangler may provide a post-processing-only Codex Evidence Package / Ticket Capture Mode for local recordings. This workflow converts completed recordings into AI-reviewable issue evidence packages and must not require operator interaction while driving or recording.
- Approved workflow: Video Mangler may provide a standalone Archive Catalog / Glacier Prep Index for local raw video folders. This workflow creates searchable local catalog, restore-index, integrity, upload-prep, manual-notes, thumbnail/contact-sheet, and sidecar outputs only. It must not upload to AWS, execute Glacier restores, force Whisper transcription, or perform semantic AI routing.
- Approved workflow: Video Mangler may provide an on-demand, bounded, resumable Review Media Inbox workflow for operator-configured local folders. Media Manglers owns local scanning, normalized lifecycle records, safe media preparation/rendering, identity and contract validation, and finalization; an external AI coding agent owns semantic review, repository/GitHub inspection, and operator-authorized issue work. The workflow must keep original media read-only, preserve real paths and private project terms only in per-user configuration, default to Fast scanning with bounded oldest-first batches, treat 240 minutes as a soft source-boundary limit, and require an explicit warning before Full inventory hashing. It must not call AI, inspect GitHub, create issues, launch agents, upload evidence, or register background work. Its required completion boundary includes a validated preliminary-findings loop that resolves stable source identity and reuses Workflow 3 rendering machinery for targeted frames, supported panel crops, and audio before the external agent writes final results; That loop and finalization were built under 73; their acceptance on the operator's own recordings is Wave B's Inbox test (224).
- Approved Full Review improvement: Video Mangler may create high-detail panel crops for exact 5760x1080 Full Review sources, record explicit transcript audio-source metadata, and use that metadata to prevent unsafe transcript reuse. This does not complete Full Review/Codex evidence transcript/audio reuse, which remains tracked separately.
- Approved Full Review improvement: the Workbench may accept multiple supported web-video URLs in one ordered paste and create movable, agent-neutral AI study packages. The package front doors and manifests must use relative internal links and must not require the original output drive or folder. Profiles are optional for ordinary Full Review use, tool readiness is checked automatically, and URL-download failures must identify the affected source without mislabeling the entire queue. The existing local-only ticket-evidence boundary, Archive Catalog behavior, and Review Media Inbox safety boundary remain unchanged.
- Approved desktop surface: Video Mangler Workbench may provide task-oriented, hidden-process in-GUI execution for all five existing Video Mangler workflows. It must keep current-run controls separate from startup defaults, preserve per-user settings/profiles, retain local logs, and use `Video Mangler.ps1` as the media-processing source of truth.
- Approved evidence improvement: Workflow 3 may add deterministic complete-session mention timelines, explainable ticket-thread hints, unassigned-mention indexes, session-level Codex/Claude drafts, and a size-bounded text-first portable handoff ZIP. Relationship hints are suggestions and must never assert semantic ticket identity automatically.
- Approved launch surface: the repo may build a standalone Windows Workbench folder with a clickable GUI executable and packaged backend source sidecars.
- Approved (installer plan, decision 1; parent issue #3): Media Manglers ships its own tools. Both editions, the portable ZIP and the installer, are one packaged application folder that may carry its own FFmpeg and FFprobe and a private Python with the Whisper code, and the app uses those first (Whisper itself is given the sound the app read, so it never starts an FFmpeg of its own). A tool path the operator chose in Settings still wins. A Python already on the PC is used instead of ours only when it can use the graphics card for Whisper, or has Argos Translate for local translation, and its row says why. The speech libraries our Python needs are downloaded once into one per-user folder (`%LOCALAPPDATA%\MediaManglers\addons`), after the one question the app asks at first launch (the same in both editions; there is no installer checkbox), and only our own Python is given them. Everything the app downloads is pinned by SHA-256 and fetched over connections whose certificates Windows itself checks; that check is never turned off. Media Manglers never installs, upgrades or removes anything in a Python or other program already on the PC (the one exception: the console script, run by hand, offers to install Argos Translate into a Python of yours, and only after you confirm it), never changes its own Python, and adds nothing to PATH. A Whisper model is downloaded only after the operator approves it, in every feature; a valid model already in the Whisper cache is reused, and a damaged one is never replaced without approval. Settings > Dependencies still checks every tool, says where each came from, and lets the operator choose a path. New file steps (downloads, unpacking, removing downloaded add-ons) wait at most ten seconds per file and thirty per step for another program holding a file, trying again all the while, on folders of any size, then stop and name it, never lose data, and never advise closing, excluding or switching off the program that holds it. One Workbench runs at a time, because both editions share one library and one settings folder.
- Approved desktop surface: the Workbench may provide a built-in review player for local recordings - video playback with a choice of audio track, the package transcript shown at the playhead including lines the transcript filter left out and the recorded reason, and a control that adds the recording to the existing never-use list; and, as a second increment, a whole-recording waveform per audio track, jump to the next or previous sound on a chosen track, and timeline markers for findings an evidence package already contains. Operators may instead choose VLC or the operating system's default player, which give plain playback only. Approved in Wave 6 (220): the player starts on the track a page asks for, else on the track its transcript came from (212), and never overrides the operator's own pick; Next / Previous stretch jump between the speech or active stretches a page hands it; a waveform strip shows the heard track from levels the raw bin scan already measured. The player keeps original media read-only (waveform data is kept in the app's cache folder, one main setting, never beside the recording or on the recordings drive), adds no runtime dependency, and does not upload, call AI, or create issues. Approved in Wave 8 (125 Part 2): one waveform lane per audio track for any recording opened in the built-in player, measured once by the shared levels job and kept in the cache folder; a Waveforms button shows or hides them; Next / Previous sound on the track being heard; moments from the evidence package on the time bar.
- Approved workflow: Video Mangler may produce an edited, upload-ready video of a local narrated recording (150). Media Manglers builds a reusable analysis of the recording, stores each edit as a versioned project, renders preview and final videos with FFmpeg, and checks technical quality automatically; an external AI coding agent decides the story and the edit, assesses its own drafts, and revises them from the operator's plain-language feedback. It is added as its own page, "AI Video Editor", alongside the existing workflows and changes none of them. Original media stays read-only, every version is kept, and the Workbench does not call AI, upload, publish or create issues. Implementation proceeds phase by phase, each after the operator's review of the previous one. Approved in Wave 7 (226): the editor uses the shared engine; its voice and game tracks follow the track names and the Narration track setting (Track roles) on Auto, and a track picked on the page is an override for that recording, shown as Overridden; its transcripts get the shared invented-line filters plus one editor-only rule that keeps short real reactions; dead time found from the game sound and the game picture is pointed out to the AI editor, which is told to cut it unless it serves the story; the export is at the recording's own frame rate up to 60, its picture compressed once, with an export-quality main setting and a per-video override; a revision that changes only the sound reuses the rendered pictures; renders carry readable names; and the AI editor's commands cannot remove a privacy mask, or move, leave out or cover a masked camera in the layout fixed at Prepare.
- Approved: the raw bin library (215-217, Wave 6 220): a local SQLite library in the app's local data folder, backed up daily, of every recording in the operator's watched folders, with the app's guess (Keep likely / Check / Probably nothing / Empty, from the shared voice detection and its short voice probe; Keep likely needs at least a minute of speech on the narration track; no transcript is made unless the operator asks for a Deep scan), idle time from the game-audio track (estimated from the full mix, and labelled so, when the named or set game track is missing or silent), the operator's decision (Keep / Delete candidate / Undecided) and purpose labels, CSV/JSON export, and a cache folder with a size cap and Clear cache. Each recording is read from the recordings drive at most once per scan, and each finished one is committed, so an interruption loses at most the one in progress. New guess or idle rules and a changed Track roles setting are applied from what the library stored (speech seconds, every track's levels in the cache), without reading the recordings again. Mark only: the app never writes, moves or deletes anything on the recordings drive. Deletion is 218, parked.
- Approved (242, 243, Wave A1): every run is kept in the library, not only the last 30. A run is written there when it starts and closed when its process ends, and each feature writes each recording's outcome when it knows it (completed, completed with problems, no narration found, skipped by you, failed, cancelled, or not reported when nothing said); a later correction updates the same run. History shows every run, newest first, in pages with Show more; Home's Recent runs shows the newest five. A run cut off by a crash or a close is shown Interrupted; a raw bin scan that could not reach the recordings drive is Failed. The run history settings.json kept moves into the library once, with settings.json and the library backed up first, checked, and put back if the move does not check out; settings.json then holds no run history. Run history is personal: never in an export, a settings bundle, a package or anything shown to an outside agent.
- Approved (224, Wave B): Review Media Inbox's records move into the library once. The ledger and the library are backed up first, every table, state and accepted result is checked, and everything is put back if the move does not check out. The Inbox's folder stays where it is and is registered in the library, and the outside agent's files do not change. Afterwards every screen answers "reviewed by the Inbox" from the library.
- Approved (264, part of 242, Wave C1): speech facts in the library. Each recording's speech moments per track, the rule that measured them and who measured them are kept with its content (the full hash), so exact copies share them; until the content is known they belong to the one copy, only while its file keeps its size and time. One rule decides the narration track everywhere: your confirmed answer for this recording, your saved answer for this exact track layout where it applies today (the Inbox and the wizard; elsewhere it only breaks ties), the track names and then the Track roles setting, the stored automatic pick, and only then fresh detection. Choosing a track on Find my bug reports, the Inbox, the wizard or the AI Video Editor is your answer for that recording, kept with who and when; Automatic clears it, and a cleared answer stays on record. A run asks the library before it listens, so a known recording no longer shows Finding your voice, though it still reads the narration and is not meaningfully faster. On Find my bug reports the tie-breaker is the saved answer for that recording's own track layout, and a remembered Track 1 counts. The built-in player gets Next speech and Previous speech for any recording, including finer jumps for the raw bin once it is measured; the jumps land about 4 times in 10 within a second before a line's start on the history tested, and the 9-in-10 target of 264 stays open for Wave C1b. Speech facts are personal: never in an export, a package, a ZIP, a log or anything an outside agent reads, and never the words heard.

- Approved (242, audit H6 and M2, Wave C2): the AI Video Editor's projects are bound to their recording's content. A new video is bound at Prepare: from the library when it has read that very file, otherwise Prepare first reads it once, the step "Confirming which recording this is", before anything is written. A bound video's add-version, render, export and analyze accept only its own recording, decided by the full hash, so a different file with the same name, or a file saved in its place, is refused with a plain reason; the agent's files, brief and prompts do not change. Each analysis and render of a bound video names the content it was made from, and its first preview after binding renders once. Older videos keep working exactly as before until you link them, one at a time, from one dialog on the editor page (Link recordings…) that shows the evidence for each: its recording's name, folder, size and length, whether the path, size and time still match, whether the library has read it, files of the same size and time when it moved, and whether its sound matches. A file name alone is never offered. Linking keeps a copy of the project file first, adds only the binding and, for a recording that moved, its new place with the old one kept, so its earlier versions still render. Choose a recording shows every edit of a recording, by content, with how many there are. The library keeps an index of the projects and their versions, which the project files stay the authority over: it is brought up to date whenever the page is shown, on Refresh, when the page sees a change on disk, after each page run and at the end of the agent's own commands; a project no longer on disk is marked unavailable, never deleted.

---

## What the Workbench does

The Workbench is four features on one shared engine. A wave improves one or more features and never degrades another.

### Product rule: one engine

- A shared job exists once: the words to spell right, narration-track choice, the invented-line filters, Whisper loading, audio extraction, screenshot and frame extraction, queue controls (pause, skip, stop), ZIP building, the output-folder check, and the warning and status rules.
- Every feature that can use a shared job gets it by default. A feature turns one off only with a stated reason, recorded here.
- A fix to a shared job is not done until every feature that uses it has it.
- Each job has one main setting. A feature may override it, and the app shows "Using main setting" or "Overridden" next to it. No feature keeps its own copy of a shared setting.
- Stated reasons: each feature writes its own package, because the package is that feature's product. Review Media Inbox keeps its own output format, which is its contract with the outside review agent; for everything else it uses the shared code. Its records live in the library (224); its workspace (queue, batches, history, locks and the files the outside agent reads and writes) stays a folder of its own, registered in the library. The Inbox's track dialog and the wizard's track preview keep their own Next speech places, because they answer another question, "is this your microphone?" (264). Features 1-3 leave the short-reaction rule of the invented-line filters off, because a ticket or a review package needs words, not exclamations; only the AI Video Editor turns it on (226). The raw bin's idle time uses the game-audio signal only until the operator approves the game-picture signal there: it would change Idle values already in the library, and it adds a video decode to the scan's one read, whose cost is measured first (217). The AI Video Editor keeps its scene renders inside each project (`scene-cache`) rather than in the cache folder: a final's lossless scenes take several gigabytes while an export is made, and would push out the raw bin's cached data; they are removed once the export is placed (226). The AI Video Editor's runs have Stop only, no Pause or Skip: each run is one recording, and its long steps (the one read, Whisper, a render) run inside one process with nothing to pause or skip between them (226).
- Order of work: Wave 5 finishes the engine for features 1-3 (214); Wave 6 the raw bin (152, 220); Wave 7 the AI Video Editor joins the shared engine; Wave 8 the player and review screens; Wave 9 packaging, start-up and tools (225); Wave 10 transcripts and Find my bug reports; Wave 11 the Inbox and clean-up, including the decision on `Audio Mangler.ps1` (join the engine or retire).
- The map of every feature, screen and shared part, and where each lives, is `governance/CAPABILITIES.md`.

### The four features

1. **Package any video for AI** (the original purpose). Turns any video, a local file or a web link, racing or not, into screenshots, a transcript and clips that an AI can review despite upload limits. Entry: Home cards *Full Review* and *Transcript Only*; New Review wizard. State: working. Portable ZIP: on by default.
2. **Find my bug reports.** On demand, turns narrated recordings into a ticket package that the operator's local agent reads in place. Entry: Home hero and the *Bugs* rail button; the same engine is offered as *AI / Ticket Evidence* in the wizard, with no Home card (152). State: working. Portable ZIP: off; optional Export ZIP is 204.
3. **Watch the raw bin.** Keeps a library of every recording in the operator's folders, with the app's guess, idle time, the operator's decision and purpose labels (the raw bin library), and reviews new recordings and remembers which are done (Review Media Inbox). Entry: *Raw bin* and *Inbox* rail buttons and Home cards (152, 220). State: working. Scans are on demand. Archiving is not built: moving or deleting originals is 218, parked; the recordings drive stays read-only. Portable ZIP: off.
4. **AI Video Editor.** Turns a narrated recording into a YouTube-ready video; an external agent decides the edit, the Workbench analyses and renders. Entry: *AI Editor* rail button and Home card. State: working on the shared engine (Wave 7, 226). Portable ZIP: none; versioned project folders.

### The shared engine, as it is today

After Wave 5 (214) every shared job serves features 1, 2 and 3 from one place. Feature 4 joined in Wave 7 (226).

- Words to spell right: one list, reaching Whisper and the transcript corrections in 1, 2, 3 and 4.
- Narration-track choice: track names, the main **Narration track** setting and voice detection (`voice_track`) for 1 (Full Review and Transcript Only, on Auto), 2, 3 and 4. Full Review and Transcript Only share one rule: the narration track when one is found, with the strict narration filter; otherwise the full mix with the plain one, never "no narration found"; a chosen track overrides it. One rule (`speech_facts.narration_answer`, 264) goes first in every feature: your confirmed answer for this recording, then, where it applies, your saved answer for its exact track layout, then the track names and the setting, then the stored automatic pick, and only then listening, with a remembered pick as a tie-breaker. The Inbox asks the operator only when the detection cannot tell; there and in the wizard your saved answer for this exact layout still wins over the names and the detection, and your answer for this one recording comes before it. The AI Video Editor's voice and game-sound boxes start on your answer for this recording, else on Auto: the track names, then the Narration track setting, then the stored automatic pick, then voice detection by listening (for the game, the shared game-audio rule). Unlike 1 it never falls back to the full mix and stops with "Choose the voice track" instead, because an edit needs the voice on a track of its own; a track picked there overrides Auto for that recording.
- Invented-line filters: the text check in every `whisper_local` call; in narrated (sparse) speech, a line Whisper sampled at random and itself rates below its confidence bar, a line with too few words for its length, and Whisper writing its own prompt back are dropped and can never keep another line; every decode is seeded, so a recording gives the same transcript every run; the cross-track and near-silent checks (`cross_track_check`) wherever a narration track was chosen, in 1 and 2, the Inbox and the AI Video Editor (the raw bin's Deep scan does not run it yet: a gap, not a choice: 233); and the package checks warn about any such line that is kept. The AI Video Editor alone also keeps short real reactions (stated reason above).
- Whisper: loaded only by `whisper_local` (`load_whisper_model`, `pick_whisper_device`), for transcripts and the voice probes alike, for every feature. It loads only a model that is on this PC as Whisper published it (checked against Whisper's own SHA-256); a missing or damaged model is refused in every feature until the operator approves its download in Settings > Dependencies, and a background job skips with a note instead of asking. Model, GPU, language and speech mode are main settings every feature reads; one rule (`whisper_options`) turns them into the request for the raw bin, the Inbox and the AI Video Editor. The AI Video Editor's quick passes use Whisper small unless set to the main model, because they run over the whole race and Whisper small is much faster (decision C).
- Audio extraction: one decoder, `voice_track.extract_wav` (no time limit while FFmpeg moves; when it makes no progress it is stopped with anything it started), for voice detection, the Inbox's narration audio, the backend's narration WAV and all-tracks review mix for 1 and 2 (helper command `audio-extract`), Transcript Only's audio for Whisper, and the package MP3 (1, and Transcript Only's kept audio; helper format `mp3`). Every file is renamed into place only when FFmpeg finished it. The WAV is byte-for-byte what each made before. The AI Video Editor reads its recording once through the same decoder: every track's sound, and in the same read the game picture for its dead time (if the game picture cannot be read in that pass, the sound is read again on its own).
- Screenshots: one renderer, `frame_render`: moments in batches (2, 1's evidence add-on, 3's targeted evidence), exact frames with their real time (3's timeline) and one every N seconds (1's screenshots and panel screenshots). Screenshots are byte-for-byte what the old renderers made. It also makes the AI Video Editor's stills, close looks and contact sheets, blurred through the privacy masks by one blur builder.
- Clips and review copies: the evidence clip renderer for 2 and 3, including the Inbox's targeted evidence.
- Queue controls: Pause, Skip and Stop on Queue / Progress for every run of 1, 2 and 3; the AI Video Editor's runs have Stop only.
- ZIP building: one writer (`zip_writer`), long-path safe, for 1's AI review ZIP and the portable ZIP.
- Output-folder check: one rule (`user_folders`), asked by the wizard, Find my bug reports, the Inbox, the AI Video Editor, Settings and the backend. Since Wave 6 it also refuses any folder inside a watched recordings folder, and anywhere on a non-system drive that holds one, compared by volume, not drive letter.
- Built-in player: one window for 1, 2, 3 and 4. The Inbox's track choice opens it on top of its dialog (220), and the New Review wizard's Preview track opens it on the chosen track (136, Wave 8). It shows a waveform lane for every audio track, jumps between sounds on the track you hear, marks what the package found (125), and jumps between speech moments on your narration track for any recording once its speech facts are known (264).
- Same recording: one rule (`recording_identity`) for the Inbox and the raw bin: a sampled hash proposes, the full hash confirms, two live copies stay two entries.
- Recording records (the library, 242): one front door (`recording_records`) to what the app remembers about recordings and runs, for 1, 2, 3 and 4. It keeps them in the raw bin library's database in the app's local data folder, backed up daily; its structure moves up one step at a time, with a whole backup first that the daily pruning never removes, and a library a newer version moved on is never changed. Every run of every feature is kept there with each recording's outcome (243). The raw bin's scan engine (`raw_bin_library`) keeps the SQL for its own tables; nothing else opens the database. Review Media Inbox's records are in it since Wave B (224), kept by its own store (`inbox_records`). Speech facts and your narration answers are in it since Wave C1 (264), kept by `speech_facts`, the only code that reads or writes them. The AI Video Editor's projects are indexed in it since Wave C2 (242), through the front door; their project files stay the authority. Still apart until its own step: the Archive Catalog's database (frozen, 245).
- Track roles: "Game audio" is a kind of never-narration (narration choice unchanged); the game-audio track is found by name, the setting, then elimination (`voice_track.game_audio_track`); a game track named or set is never swapped for another. "Full mix" (220) is what a track named "Full Mix" is: narration only when nothing else qualifies, and the track idle time is estimated from (`voice_track.full_mix_track`). The elimination step never picks a track whose name marks it as never narration (music, spotter, engineer, Discord or voice chat; "System" can still be the game) (226). The raw bin and the AI Video Editor find the game track this way.
- Activity timeline (`activity_timeline`, 217 signal 1): idle stretches from the game-audio track, from the same one-pass decode as voice detection; estimated from the full mix when the game track is missing or silent the whole recording, otherwise unknown with the reason. Signal 2 (226): the game picture standing still or black, from its keyframes read in the same pass as the sound, and a combined timeline (idle when either signal finds a minute or more; each stretch says which signal found it), used by the AI Video Editor for its dead time. The raw bin uses signal 1 only (stated reason above).
- Cache folder (`app_cache`): one main setting for every rebuildable file (waveform levels for the player and the Raw bin), a size cap removing the least recently used first, and Clear cache.
- Waveform builds (`track_levels`, Wave 8): after a run of 1, 2 or 3, and for any recording opened in the built-in player. Stated reason: they are background cache work, not runs, so they are not on Queue / Progress or History; a run or closing the app stops them, and they resume later. The AI Video Editor's runs do not queue them (its page is Wave 7's). The same job measures speech facts for what you open and what a run just used, never the whole library; its checkpoint stays in the cache folder until the facts are stored, and when nothing else can tell the narration track it listens on the processor, never the graphics card, so a game running alongside keeps it (264).
- Built-in player on the AI Video Editor page (236): the same one player, shown inside the page, plays a version of an edited video. It shows no waveform lanes and asks for no waveform build, because an edited video has one track, the finished mix. Opened anywhere else, it works as above.
- Warning and status rules: one rule (`run_status`); notices that need no action are information, not warnings.
- Main settings: a feature's own value is an override, shown as **Using main setting** or **Overridden** (`main_settings`): 1's transcript audio mode (Full Review and Transcript Only), the Inbox's evidence and scratch folders, which use the main output folder and the app's temporary folder when left blank, and the AI Video Editor's track boxes (Auto follows Track roles), its quick passes (Whisper small, or the main Whisper model) and its export quality (Settings > AI Video Editor; one video can choose its own).
- Packaging stays per feature (stated reason above): AI review ZIP and package (1), evidence package (2), Inbox batches (3), project folders (4). The raw bin library's database is not a feature's package: it is the shared recording records (242).

Copies that should become one, not be deleted, are listed under "Known copies" in `governance/CAPABILITIES.md`. The six Review Media Inbox methods that `app.py` defined twice lost their never-called first copies in Wave 6 (220).

### Standing rules

- The drive that holds the operator's recordings is read-only: read from it, never write or delete. Agent scratch goes only in `AREA51/TEMP/`.
- Portable ZIP defaults: feature 1 on, 2 off (optional export), 3 off, 4 none.
- Every wave names the features it touches and proves the untouched ones still work, one smoke test each: (1) Full Review of a short file produces its package; (2) Find my bug reports on a short narrated recording produces a ticket; (3) Review Media Inbox scans a folder and prepares one recording; (4) AI Video Editor prepares a recording and renders a preview.
- Reports are in plain English, with full paths.
- Every hand-test sheet gives each test recording's size and length, and how long each step takes on the PC the test runs on, measured on the build being handed over (224, Wave B2a).

### In the code but not one of the four (kept, not deleted)

- `Audio Mangler.ps1`: a standalone audio script the Workbench does not use.
- Archive Catalog / Glacier prep: a cold-storage catalog with its own Home card, closest to 3. 124 was closed as replaced by the raw bin library (215); the Catalog stays beside it, unchanged, until the operator decides whether to merge or retire it.
- Translation and the Local / AI / Hybrid modes, with protected-terms profiles: part of 1 in practice.
- App-wide work: 138 licences, 159 build smoke launch, 188 missing tools, 193 closing during start-up, 96 clean-up, 125 built-in player (used by 1, 2, 3 and 4).

---

## Work Tracking

GitHub Issues are the sole authoritative work tracker. Work is delivered in waves.

- Every meaningful planned, active, blocked or deferred work item exists in GitHub Issues. No `TODO.md` or other parallel work board may exist.
- A wave is one result the operator can test first-hand on the operator's own recordings. It is not one issue. Each wave has one parent issue whose checklist links its child issues; the operator approves creating it.
- Every open issue that blocks or hurts the wave's result is fixed inside the wave: one branch, one pull request, one operator approval, one build for the operator to test.
- Work discovered during a wave that is part of the same result is fixed inside the wave and listed in the wave pull request and on the parent checklist. It does not need its own issue.
- Work discovered during a wave that is not part of the result is not fixed and not filed. It is recorded as one line under "Parking lot" in the wave report; the operator decides what becomes an issue. Exception: data loss, a crash or a security problem stops the wave and is reported to the operator at once.
- If in-wave fixes would push the wave past double its approved effort estimate, stop and re-scope with the operator before continuing.
- Agents propose the next wave; the operator chooses it.
- Plans, branches, commits, pull requests, chats, local notes, evidence and handoff files support the issues but do not replace them.
- If GitHub is unavailable, do not create a substitute tracker. Continue only already-approved wave work when safe and report the pending GitHub update.

Historical references to `TODO.md` remain part of Git history and approved historical plans. They are not current tracking authority.

---

## Operator Approval and Agent Execution

- The operator approves goals, scope, merges, releases, deployments, cleanup, and destructive or difficult-to-reverse actions.
- After approval, the selected AI agent performs the approved repository, GitHub, merge, release, deployment, or cleanup action unless the operator explicitly asks to perform it manually.
- Do not hand routine development execution back to the operator when the agent can perform it safely within the approved scope.

---

## Authority by Purpose

### Approved scope and intended behavior

Use, in order:

1. `governance/CURRENT_PROJECT_TRUTH.md`
2. the governing GitHub issue
3. the approved plan
4. `AGENTS.md`

### Actual implementation and validation

Use, in order:

1. current repository files and Git state
2. validation evidence
3. pull request and merge records
4. package, tag, and release records
5. AI-agent reports

An issue or plan does not prove implementation. An AI-agent report does not outrank repository state or validation evidence.

---

## Evidence and Truth Rules

- Repository governance documents define approved scope and intended behavior.
- Current repository behavior and validation define implementation reality.
- External or historical references are guidance only unless explicitly adopted.
- Local-only inputs such as `AREA51/` and machine-local temp/evidence folders are reference-only unless explicitly promoted into tracked repository material.
- When evidence and assumptions conflict, evidence wins.

---

## Stability Rule

- Do not redefine previously validated behavior without explicit approval.
- Changes must be incremental and testable.
- If something is uncertain, treat it as unproven rather than assumed.

---

## Product Continuity

- **New functionality is additive by default.** Existing capabilities are not removed, hidden, degraded or substantially redesigned to simplify the implementation of a new feature without the operator's explicit approval.
- Media Manglers is a multi-purpose application. A new capability is added alongside the existing ones; it does not replace them, re-centre the application on itself, or change how existing workflows are reached or behave.
- Every existing workflow and surface stays reachable and working: Find my bug reports, Full Review, Transcript Only, AI / Ticket Evidence, Archive Catalog, Review Media Inbox, Evidence, Session, Drafts, History, Settings and the built-in player. A capability that has become hard to reach is a defect to correct, not an accepted state.
- New capabilities reuse the shared navigation, settings, run, progress, history and player services rather than duplicating them.
- Before implementation, a new capability's plan lists what it reuses, what it adds and what it changes. Any change to existing user-facing behaviour, wording or location requires the operator's explicit approval. Underlying functionality is never deleted without explicit approval.
- A capability is complete only when the full test suite, a product-inventory test of navigation, Home, workflows and settings, and a GUI validation checklist on the packaged build show that existing workflows still behave as intended.
- The inventory protects working functionality; it does not freeze today's GUI. Known deficiencies are recorded separately, with their issues, and are never encoded as expected behaviour.

---

## Scope Guard

- Do not expand the project beyond Product Identity without explicit approval.
- New capabilities or workflows must be approved here before implementation.

---

## Document Precedence

For approved scope and intended behavior:

1. `governance/CURRENT_PROJECT_TRUTH.md`
2. governing GitHub issue
3. approved plan
4. `AGENTS.md`

For implementation and validation claims:

1. repository files and Git state
2. validation evidence
3. pull request, merge, package, tag, and release records
4. AI-agent reports

If sources disagree, call out the mismatch and follow the authority rules above.
