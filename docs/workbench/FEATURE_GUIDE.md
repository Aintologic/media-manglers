# Every feature in one guide

The Video Mangler Workbench is one app with four features on one shared engine,
plus a few tools kept beside them. This page covers every one: what it is for,
how to start it, what you get, and its limits. Each section links to the full
guide for that feature.

Everything runs on your PC. Your recordings are only read, never changed,
moved or deleted, and nothing is uploaded unless you choose an AI processing
mode for Full Review.

| Feature | Start it from | Full guide |
| --- | --- | --- |
| [Find my bug reports](#find-my-bug-reports) | **Choose recordings** on Home, or **Bugs** in the left rail | [Find my bug reports](FIND_BUG_REPORTS.md) |
| [Package any video for AI](#package-any-video-for-ai) | The **Full Review** and **Transcript Only** cards on Home | [Full Review](FULL_REVIEW.md), [Transcript Only](TRANSCRIPT_ONLY.md) |
| [Watch the raw bin](#watch-the-raw-bin) | **Raw bin** and **Inbox** in the left rail, or their cards on Home | [Raw bin library](RAW_BIN_LIBRARY.md), [Review Media Inbox](REVIEW_NEW_VIDEOS.md) |
| [AI Video Editor](#ai-video-editor) | **AI Editor** in the left rail, or its card on Home | [AI Video Editor](AI_VIDEO_EDITOR.md) |
| [The built-in player](#the-built-in-player) | Double-click any recording | [Built-in player](REVIEW_PLAYER.md) |

The [shared parts](#what-every-feature-shares) (finding your voice, words to
spell right, progress, settings) work the same way everywhere.

## Find my bug reports

**What it is for.** You talk about bugs, fixes and feature ideas while you use
your software or drive. This turns those recordings into a package and a ready
prompt for Claude Code or Codex. Your AI agent reads what you said, shows you
the issues it would open, and opens them only after you approve.

**How to start it.**

1. On Home, press **Choose recordings** (or **Bugs** in the left rail).
2. Add recordings with **Add recordings…**, **Add newest**, or by dragging them
   onto the list. **Add newest** leaves out recordings already done and those
   on your never-use list; tick **Include ones already done** to add them. A
   recording identical to one already done (the same content, in another
   folder) counts as done too. Both lists are kept in the app's library.
3. Press **Find bug reports**. There is no microphone step: the app finds the
   track with your voice by itself.
4. When it ends, press **Copy prompt for Claude Code** or **Copy prompt for
   Codex** and paste it into your agent.

While it runs you can **Pause**, **Resume**, **Skip selected** or **Stop**. A
stopped run can be picked up later with **Continue**, even after closing the
Workbench.

**What you get.** A dated package folder under your output folder with, for
every stretch where you talked: screenshots (the full width and one per
monitor), a short clip with your voice, and the transcript. Each recording also
gets a small review video of the whole session. Moments where you only
mentioned a bug in passing are listed in `MENTIONED_NOT_ASKED.md`, so your
agent shows them to you instead of filing them. **Open package folder** shows
the package, and **Watch a recording…** plays a recording with its transcript.

**Limits.**

- A ticket needs a request ("make a ticket", "open an issue", "instructions for
  AI"). A request made in plain words without one of those phrases can be
  missed; your agent is told to read the full transcripts.
- A recording with no narration is a normal result: the run still ends as
  Done and says so.
- If the app cannot tell which track is your voice, it asks rather than
  guesses: press **Fix and continue…** and choose the track.
- Python, Whisper, PyTorch and FFmpeg are not part of the download; see
  [Dependencies and setup](DEPENDENCIES_SETUP.md).
- The package is kept as a folder on this PC. An optional ZIP export is not
  built yet.

The same engine is offered as **AI / Ticket Evidence** in **New Review**, with
the five-step wizard and a microphone check per recording. See
[AI / Ticket Evidence](CODEX_EVIDENCE.md).

## Package any video for AI

**What it is for.** Any video, a file on your PC or a web link, racing or not,
turned into screenshots, a transcript and clips that an AI can review, even
when the video itself is too big to upload.

### Full Review

**How to start it.**

1. On Home, press **Start** on the **Full Review** card.
2. In **Source**, choose a file or folder, or paste one or more web-video
   links, one per line.
3. Keep **Recommended settings** or choose a preset, then choose an output
   folder.
4. On **Review and run**, fix any named blocker, then press **Start review**.

**What you get.** For each video: a smaller copy, screenshots, the audio, a
transcript, optional translations, and an AI review ZIP (on by default). Each
output folder has `README_FOR_AI.md` and `AI_PACKAGE_MANIFEST.json` as the
starting point for Claude Code, Codex or another AI. Links inside are relative,
so the whole folder can be moved.

**Limits.**

- Web links need yt-dlp. Other features take local files only.
- **Processing mode** decides what may leave your PC: **Local** sends nothing;
  the AI and Hybrid modes send audio or transcript text to your OpenAI project.
  See [Processing and privacy modes](../guides/PROCESSING_MODES.md).
- On Auto, the transcript is made from your voice track when one is found,
  otherwise from the full mix. To force a track, use **Transcript audio mode**
  in **Advanced settings**; it then shows **Overridden**.

### Transcript Only

**How to start it.** On Home, press **Start** on the **Transcript Only** card,
choose a recording or folder, check the language and search choices, choose an
output folder and press **Start review**.

**What you get.** Timestamped transcripts and indexes, and literal search
results when you gave search words.

**Limits.** No screenshots or clips. Track choice works as in Full Review.

## Watch the raw bin

Two pages that look after your recordings folders. They use the same folders,
set once in **Inbox settings**.

### Raw bin library

**What it is for.** One lasting list of every recording in your recordings
folders: what the app thinks is in it, how much of it is idle, what you decided
to do with it, and what it is for.

**How to start it.** Press **Raw bin** in the left rail (or **Start** on the
**Raw bin library** card on Home), then **Scan now**. A first scan of a large
drive takes hours; it runs at low priority, so leave it overnight.

**What you get.**

- The app's guess for each recording: **Keep likely** (at least a minute of
  your speech), **Check**, **Probably nothing** or **Empty**.
- **Idle**: the share of the recording where the game sound was quiet for a
  minute or more. It says **(estimated)** when it came from the full mix.
- Your decision (**Keep**, **Delete candidate** or **Undecided**) and labels
  (Bug report, YouTube, Short, B-roll, Training, or **New label…**). They
  follow a recording that is renamed or moved. A different recording saved
  under a file name the library knows starts **Undecided** with no labels; the
  one that was there keeps its tags and is shown with **Show missing**.
- **Mined**: which feature already mined the recording for tickets: **Inbox**,
  **Bugs**, **Inbox + Bugs**, **Bugs: no narration**, or **Bugs (old list)**
  for an entry from before the library kept the list, matched by its path.
- **Deep scan** transcribes chosen recordings and counts your "flag for AI"
  requests.
- **Play** opens the recording at its first speech; **Export view…** saves the
  list as CSV or JSON.

**Limits.**

- The app only marks. It never moves or deletes a recording; **Delete
  candidate** is a note for you.
- Idle time comes from the game sound only. The game picture, which the AI
  Video Editor also uses, is not used here yet.
- **Deep scan** does not yet run the cross-track check the other features run,
  and does not give Whisper your words to spell right as a hint (it does
  correct the transcript with them).

### Review Media Inbox

**What it is for.** Reviewing new recordings in your folders a few at a time
and remembering which are done, with an outside Codex session doing the review.

**How to start it.** Press **Inbox** in the left rail (or **Start** on the
**Review Media Inbox** card on Home). Choose **Next 3**, **Up to N** or **All
pending**, then press **Process new media**. When work is ready, use **Open
Codex review queue** or **Copy Codex prompt**.

**What you get.** A compact evidence package per recording (screenshots, the
transcript of your voice track, track details), a review queue and prompt for
Codex, and a record of what is done. Come back later and press **Process new
media** again: the Inbox picks up what Codex wrote and carries on.

**Limits.**

- It asks you for the microphone track only when the voice detection cannot
  tell. **Use this track** unlocks once you have played that track.
- **Stop after current** waits for the recording in progress to reach a safe
  point.
- Its record of done recordings is kept apart from the raw bin library for now.

## AI Video Editor

**What it is for.** Turning a long narrated race recording into a short video
that tells the story of the race, ready for YouTube. Media Manglers analyses
and renders on your PC; your AI agent (Claude Code or Codex) decides the story
and the edit; you watch each version and say what to change.

**How to start it.**

1. Press **AI Editor** in the left rail (or **Start** on the **AI Video
   Editor** card on Home).
2. Press **Make a video from a recording**. **Choose a recording** lists the
   recordings the **Raw bin** knows, with what the app already knows about
   each: its guess, your speech and idle time, your decision and labels, what
   mined it, and a video already made from it. Pick one, or press **Browse for
   another file…**.
3. **Your voice** and **Game sound** start on **Auto**, which follows your
   track names and **Narration track** setting. Pick a track to override it
   for this recording (**Reset to Auto** goes back).
4. Choose an **AI budget** (**Light**, **Standard** or **Thorough**); the box
   says what each one changes.
5. Press **Prepare for the AI editor**. An hour-long race takes about 15 to 20
   minutes; a banner on the page shows how far it has got.
6. Press **Copy prompt for Claude Code** (or **Copy prompt for Codex**) and
   paste it into your agent.

To come back to a video, press **Continue** or its card under **Your videos**.
A video's toolbar holds the rest: **Video settings**, **Prompt**, **Story &
review** and **Files**.

**What you get.**

- Every version as a tab, with the editor's story and its own review under
  **Story & review**. The play choices are on the version's picture: **Play the
  preview**, or **Play the final (full quality)** with **Play the preview (quick,
  smaller)** beside it once there is a final; **Files › Render a preview** makes a
  1280x720 preview.
- Your notes, written in plain words, go back to the agent with **Save notes,
  copy prompt for Claude Code** (or **…for Codex**). Every earlier version is
  kept.
- **Approve and export…** renders a checked 1920x1080 video at the recording's
  own frame rate, up to 60 frames a second, into the video's export folder.
  **Export quality** offers **YouTube (recommended)**, **Highest quality** and
  **Smaller file**; one video can override the main setting.
- **Prompt › Start a fresh edit** makes a separate edit of the same race, so a
  second agent can make its own cut.
- **Privacy masks…** paints the parts of your cameras that must always be
  blurred, before any AI sees a picture.

**Limits.**

- In some recordings the sound runs up to about a second and a half ahead of
  the picture. The editor does not correct this yet, so a remark can be heard
  before the moment it is about.
- Dead time is found where the game picture stands still or goes black, or the
  game sound is quiet, for a minute or more. A replay or a moving menu looks
  like driving, so dead time there is not found.
- A run can be cancelled but not paused or skipped: each run is one recording,
  with nothing to pause or skip between its steps.
- A video always edits its own recording. A different file, even one with the
  same name, is refused unless it is an exact copy; if you moved the
  recording, put it back where it was.
- An export needs several gigabytes of free space while it is made.
- The masks stop mistakes. An AI agent that edits the project's files by hand
  on purpose could still get round them.

## The built-in player

**What it is for.** Watching a recording inside the Workbench, with its
transcript, every audio track and what the package found.

**How to start it.** Double-click a recording or a moment in almost any list:
**Find my bug reports**, **Queue / Progress**, **History**, **Recent runs**,
**New Review**, **Evidence**, **Session Review** and **Raw bin**. Right-click
offers **Play with**: the **Built-in player**, **VLC** or your **Default video
app**. **Settings > Video player > Play videos with** sets the usual choice.

**What you get.**

- **Hear: Track N** picks the track you hear; the track taken as your voice is
  marked **your voice**.
- One waveform lane per audio track (up to eight). Click a lane to go there,
  or its name to hear that track. **Waveforms** (W) shows or hides them.
- **Next sound** and **Previous sound** (Ctrl+Right and Ctrl+Left) on the track
  you hear; **Next moment** and **Previous moment** (] and [) between the
  moments the package found; **Next line** and **Previous line** (Down and Up)
  between transcript lines.
- The transcript line you are hearing, including lines that were left out and
  why.
- **Never use this recording** puts it on your never-use list and moves on to
  the next one.

**Limits.**

- VLC and the default video app give plain playback only.
- **Next sound** finds sound, not speech: on a microphone that also picks up the
  game or a fan, it can land a few seconds off. Use **Next line** to go from one
  thing you said to the next.
- The waveforms are measured the first time a recording opens, and never
  while a review is running. A clip or a small review copy has none.

## What every feature shares

- **Finding your voice.** Track names saved by OBS come first (a name with
  *narration* is your voice; *music*, *game*, *spotter*, *Discord* and similar
  never are). Then **Settings > General / Startup > Narration track, for
  recordings without track names**, which gives Tracks 1 to 6 **Auto**,
  **Narration**, **Never narration**, **Game audio** or **Full mix**. Then the
  app listens.
- **Words to spell right** (Settings > General / Startup). One list of your own
  names and terms, given to Whisper. `Word=heard as` also corrects the
  transcript.
- **Lines Whisper invents are left out**: stock phrases over silence, a phrase
  repeated over and over, lines heard on another track, and lines written while
  your microphone was almost silent. Each is listed with its reason and shown in
  the player. The same recording gives the same transcript every run.
- **Queue / Progress** and **History.** Every run shows its stage and log.
  History keeps every run, not only the last 30: the newest 200 first, and
  **Show more** for older ones. Each run keeps what happened to every
  recording in it. A run cut off by a crash or by closing the app shows
  **interrupted**.
  **Pause**, **Skip selected** and **Cancel review** work for Full Review,
  Transcript Only, Find my bug reports, the raw bin scan and the Inbox; an AI
  Video Editor run can only be cancelled.
- **Evidence**, **Session Review** and **Prompt Drafts** open a package a run
  made: its bug reports, its clips, the session timeline and the prompts.
- **Missing tools.** A bar at the top of the window names any required tool
  that is missing, with **Download**, **Open Settings > Dependencies** and **Not
  now**. In **Settings > Dependencies**, **Copy winget command** copies the
  install command. The app never downloads or installs a tool itself, and it
  downloads a Whisper model only when you approve it in **Settings >
  Dependencies**.
- **Text size** (Settings > General / Startup): **100%**, **110%**, **125%** or
  **150%**, for the whole app at once. **Ctrl+Plus**, **Ctrl+Minus** and
  **Ctrl+0** change it on any page and in the player.
- **Cache folder** (Settings > General / Startup). Waveforms and sound levels
  that can be rebuilt, with a size cap and **Clear cache**. Clearing it never
  loses a decision or a label.
- **Where your results go.** A *Media Mangler* folder in your **Videos** folder
  unless you choose another. A temporary folder is refused with the reason, and
  so is a folder inside your watched recordings folders, or anywhere on the
  drive that holds them unless that is the Windows drive.

## Kept beside the four

- **Archive Catalog.** A searchable catalog of a whole archive folder, with
  restore and upload-preparation lists. Press **Start** on its card on Home. It
  never uploads. See [Archive Catalog](ARCHIVE_CATALOG.md).
- **Command-line scripts.** `Video Mangler.ps1` and `Audio Mangler.ps1` run the
  same processing without the Workbench. See the
  [Video Mangler command-line guide](../guides/VIDEO_MANGLER.txt).

[Back to Help](README.md)
