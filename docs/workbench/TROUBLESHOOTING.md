# Troubleshooting by what you see

## Start review is blocked

Read the blocker panel immediately above **Start review — blocked**. Use its
single dominant action. For Codex Evidence, **Confirm microphone for N files**
returns to the first unresolved source. Dependency blockers open the correct
Settings page.

## Source files do not appear

After choosing a folder, confirm the page reports `Found N supported source
files`. Then choose **Inspect N source files**. Inspection is required before
recommendations appear and does not modify recordings.

If the count is zero, verify the selected folder contains a supported local
media file rather than only text, shortcuts, or unsupported formats.

## Preview is wrong or silent

1. Select the intended source row.
2. Choose **Preview track**. The built-in player opens on that track and plays.
3. Read `Previewing: source — Track N`. It says `ready` once the player is
   playing that track.
4. If needed, select another track and choose **Preview track** again.
5. Confirm only when the displayed source/track contains microphone narration.

Changing rows or tracks pauses the player. If the identity says
`preview unavailable`, the built-in player could not play the recording:
choose the source again and try **Preview track** once more. The player's own
**Volume** applies to the preview; see
[the built-in player has no sound](#the-built-in-player-has-no-sound).

## The built-in player has no sound

1. Look at **Hear: Track N**. A recording often carries several audio tracks,
   and some of them are silent for the whole session. Choose another track.
2. Check the player's volume, then the volume of your speakers or headset.
3. Try **Hear: Track 1**.

The picture keeps playing whichever track you choose. See
[the built-in player](REVIEW_PLAYER.md#choosing-which-track-you-hear).

## VLC was not found

You chose **VLC** under **Settings > Video player**, and the Workbench could
not find it on this PC. Your videos open in the built-in player instead,
without asking, and the player says so each time.

To get VLC back, open **Settings > Video player**, choose **Find VLC…** and
point to `vlc.exe`. If VLC is not installed, install it yourself or set **Play
videos with** to **Built-in player**. The Workbench never installs VLC for you.

When you ask for VLC yourself, with **Right-click > Play with > VLC**, the
Workbench asks what to do instead: **Find VLC…**, or **Play here instead** to
use the built-in player this time. See
[the built-in player](REVIEW_PLAYER.md#vlc-was-not-found).

## The Workbench will not close yet

If the built-in player comes to the front and says it is still finishing, it
was still looking for a recording or its transcript on a slow disk. Wait a few
seconds and close the Workbench again. See
[the built-in player](REVIEW_PLAYER.md#the-player-stopped-when-you-closed-the-workbench).

## Dependency readiness and preflight

Readiness runs automatically at launch. Open **Settings > Dependencies** and
choose **Refresh readiness** after changing a tool. The check does not install
software, change PATH, download a model, or open media.

### Media Manglers helpers

Re-extract the complete application folder when the packaged helper or Python
sidecar is missing. Do not copy one executable out by itself.

### Windows PowerShell

Use the Windows PowerShell path detected by the Workbench. If it is missing or
blocked, repair Windows before retrying.

### FFmpeg and FFprobe

If FFmpeg is installed, use **Choose path** for the matching executables, then
run readiness again. If it is not, choose **Download** in its row for the
official page, or select the row and **Copy winget command**, and install it
yourself. See [Getting a missing tool](DEPENDENCIES_SETUP.md#getting-a-missing-tool).

### yt-dlp and web-video URLs

Full Review needs a current yt-dlp build for URL sources. If readiness says the
installed build is old, follow the update guidance and refresh readiness before
retrying. Provider errors such as HTTP 403 are shown against the failed URL;
other queued URLs continue when possible.

### Python Whisper and PyTorch

With Media Manglers' own Python, Whisper and PyTorch rows that say speech
recognition is not set up need the first-launch setup: choose **Set up** on the
**Speech recognition** row (see
[First launch](DEPENDENCIES_SETUP.md#first-launch-setting-up-speech-recognition)).
With a Python of yours, choose one that can import the packaged Media Manglers
module, Whisper, and PyTorch. The readiness detail explains which component is
missing.

### Speech recognition setup stopped

The setup keeps nothing half done: the speech libraries get their final folder
only when every file is in, checked and compiled. If it stops, read the message
on the bar at the top of the window, fix what it names, and choose **Set up**
again; files already downloaded and checked are reused.

- "Windows did not trust the certificate": Windows checked the connection and
  refused it, so nothing was downloaded. Check the PC's date and time and the
  network connection (a proxy or a filtering service can cause it), then try
  again. Media Manglers never turns the check off.
- "could not be downloaded": the network or the server failed. Try again later.
- "did not match its published checksum": the file that arrived was not the
  pinned one. It was removed; try again.
- "would need paths of … characters": your user folder's path is too long for
  Windows on this PC. Nothing was set up.
- "the disk … is full": free some space (the setup needs about 1.1 GB free: the
  downloads and the unpacked libraries), then choose **Set up** again.

If the **Speech recognition** row says the speech libraries "no longer load"
(for example after a security program removed part of them), choose **Set up**:
it downloads them again and replaces the copy in your user folder.

### Whisper model downloads

A model is downloaded only after you approve it with **Approve download** in
**Settings > Dependencies**, in every feature. Readiness alone never downloads
it. If a run, a scan or the AI Video Editor stops with "The Whisper model … is
not on this PC yet", approve that model there and run again. A model that does
not match the file Whisper published is not used, and it is never replaced
without that approval. A background job, such as the waveforms, skips listening
instead of asking, and listens once the model is there.

### Media Manglers is already open

Only one Workbench runs at a time, because every copy on this PC shares one
library and one settings folder. Switch to the window that is open.

### A file held by another program during a download or setup step

A download, or a step that unpacks or removes Media Manglers' own downloaded
files, waits at most ten seconds for a file another program has open (often a
virus scanner looking at a new file), and thirty seconds for the whole step.
If the file is still held, the step stops, names the program, and nothing is
lost. Wait a moment, or close that program, and try again.

### CUDA and CPU fallback

CUDA is optional when CPU fallback is ready. If neither is ready, repair the
selected Python/PyTorch runtime before starting.

## Evidence integrity failed

Keep the incomplete output. Do not publish or treat it as complete. The
integrity report names missing, failed, or unreconciled artifacts. Correct the
reported cause and rerun; do not reduce required artifact counts or turn the
failure into a warning.

## A generated name looks shorter than the source name

This is expected when the complete Windows output path would otherwise exceed
the supported compatibility budget. The Workbench shortens only the physical
artifact name and records the full logical identity in package manifests. Do
not manually rename the generated files; use the manifest or Workbench result
actions to identify them.

## Queue appears stuck

Check **Activity**, **Stage**, and the last-update warning. The Workbench keeps
**Cancel review** available during waiting. Technical details contains the raw
processing log if the plain-language state is insufficient.

## Cancellation does not settle immediately

Wait for the runner to release the current tool. The final state should say
`Cancelled`, remaining `0`, and ETA `Unavailable`. Finished sources stay
Completed; the active source becomes Cancelled.

## Online Help does not open

Choose **Open packaged Help**. Online links use the exact full Git commit in the
build. If that identity is unavailable or the browser cannot launch, the app
explains the packaged fallback instead of knowingly opening a `main` URL that
may not exist.

[Previous: Settings and migration](SETTINGS_MIGRATION.md) · [Back to Help](README.md) · [Next: Technical reference](TECHNICAL_REFERENCE.md)
