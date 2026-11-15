# Dependencies and setup

1. Launch the Workbench and let its read-only readiness check complete.
2. Open **Settings > Dependencies** when the review names a blocker, or choose
   **Refresh readiness** after changing a tool.
3. Read each component's purpose and plain-language state.
4. Use **Choose path**, **Check**, or the offered guidance only for the item that
   is not ready.

The readiness check opens no media and makes no system change. It checks Media
Manglers helpers, Windows PowerShell, Python, FFmpeg/FFprobe, yt-dlp, Whisper,
the selected model, PyTorch, CUDA, CPU fallback and VLC as applicable. yt-dlp is
required only for web-video URL reviews; an old build is called out before a
provider change turns into an unexplained download failure. VLC is needed only
when **Settings > Video player** is set to VLC.

Closing the Workbench while the check is running closes it at once: the check
is stopped, with any tool it had started, and runs again at the next launch.

> **Download approval:** A Whisper model is never downloaded without your
> approval, in any feature. Each model a workflow will load has its own row: New
> Review's model, the main model saved in Settings (Find my bug reports, the raw
> bin's scans and the AI Video Editor load it), `base.en` (every review and scan
> uses it to find your voice) and the AI Video Editor's quick-pass model. A model
> already in your Whisper cache that matches the file Whisper published is used
> as it is, with no download. A missing model, or one that does not match, offers
> **Approve download**: it shows the size, and on **Yes** downloads that one
> model, checks it against the published file, and then checks readiness again.
> If you approve another model while one is downloading, it waits its turn and
> starts by itself after the first. While a model downloads, nothing reads it: its
> row says it is downloading. A model that does not match is never replaced
> without that approval. If the check against the published file could not
> finish, the row says the model was not checked, and each run checks it before
> using it. **Start**, **Find my bug reports**, the raw bin's scans and the AI
> Video Editor's **Prepare** do not start while a model they load is missing,
> does not match, is downloading, or has not been checked since you changed it;
> each says which model and what to do.

Only one Workbench runs at a time, because every copy of Media Manglers on this
PC shares one library and one settings folder. Starting a second one says so and
closes it.

## First launch: setting up speech recognition

Media Manglers comes with its own FFmpeg and its own Python. Its Python needs
speech-recognition files that are too large to ship with it, so the first launch
asks one question:

> Media Manglers needs speech-recognition files to make transcripts: about
> 0.34 GB from the Python Package Index and the Whisper model server. They are
> saved in your user folder, not in the program folder. Download now?

- **Download** sets them up while you keep working. A bar across the top of
  every page shows how far it is. The speech libraries (PyTorch and their
  partners) go to `%LOCALAPPDATA%\MediaManglers\addons`, and the small
  `base.en` model, which every review uses to find your voice, goes to your
  Whisper model cache. A copy of `base.en` already in that cache is used as it
  is. When it finishes, readiness is checked again.
- **Not now** sets nothing up and does not ask again at start-up. The
  **Speech recognition** row in **Settings > Dependencies** then says it is not
  set up and offers **Set up**, which asks the same question. Transcripts need
  it; everything else works without it.

Every file is pinned: it is checked against the checksum it was published
with, and kept only when it matches. Every download's certificate is checked
by Windows itself. Nothing is installed into any other Python, and nothing is
added to PATH. If the setup is interrupted, choosing **Set up** again finishes
it, reusing what was already downloaded. Your chosen Whisper model (for example
`medium`, 1.5 GB) still downloads only after its own **Approve download**.

If a Python of yours is used instead of Media Manglers' own (see **Python**
below), it has its own speech libraries, so only a missing `base.en` is offered.

## Getting a missing tool

When a tool the reviews need is missing, a bar at the top of the window says so
once per launch, names each missing tool and offers **Download**,
**Open Settings > Dependencies** and **Not now**. It never blocks browsing the
app; **Start** stays blocked until the tool is there.

In **Settings > Dependencies**, a missing or outdated tool has a **Download**
button next to its usual action. **Download** opens the tool's official page in
your browser. Select the row to see that page and, where Windows Package Manager
has the tool, the `winget install` command with **Copy winget command**. Paste
the command into a terminal yourself. Apart from the speech-recognition setup
above, which you agree to, the Workbench never downloads or installs a tool, and
never changes PATH; after installing, choose **Check readiness**.

| Tool | What it is for | Official page | Windows Package Manager |
|---|---|---|---|
| FFmpeg (includes FFprobe) | Audio, frames, clips and stream details | <https://ffmpeg.org/download.html> | `winget install --id Gyan.FFmpeg -e` |
| Python | Runs the helpers and Local Whisper | <https://www.python.org/downloads/windows/> | `winget install --id Python.Python.3.12 -e` |
| Local Whisper | Local transcripts | <https://github.com/openai/whisper#setup> | none; Media Manglers' own Python carries it. For a Python of yours, installed with pip into that Python |
| PyTorch | Runs Whisper on CPU or graphics card | <https://pytorch.org/get-started/locally/> | none; for Media Manglers' own Python, **Set up** downloads it. For a Python of yours, installed with pip, chosen for your graphics card |
| yt-dlp | Web-video URLs in Full Review | <https://github.com/yt-dlp/yt-dlp#installation> | `winget install --id yt-dlp.yt-dlp -e` |
| PowerShell | Runs the Video Mangler workflow | <https://learn.microsoft.com/powershell/scripting/install/install-powershell-on-windows> | `winget install --id Microsoft.PowerShell -e` (Windows PowerShell is built into Windows) |
| VLC media player | Optional player for **Play with > VLC** | <https://www.videolan.org/vlc/> | `winget install --id VideoLAN.VLC -e` |

## Where the Workbench looks for each tool

The Workbench and the `Video Mangler.ps1` and `Audio Mangler.ps1` scripts look
in the same order:

1. the path you chose with **Choose path** (in the scripts, `-FFmpegPath`,
   `-FFprobePath`, `-PythonExe` or `-YtDlpPath`);
2. for FFprobe, the file beside the FFmpeg in use;
3. the copy that comes with Media Manglers, in the `runtime` folder of its
   application folder, when your edition carries one (FFmpeg and FFprobe, and
   for the Workbench and `Video Mangler.ps1` also Media Manglers' own Python;
   `Audio Mangler.ps1` never uses Media Manglers' own Python, only one of
   yours);
4. the system PATH;
5. the folders the tool's own installer uses, such as the Windows Package
   Manager folders and Program Files.

If a chosen FFmpeg, FFprobe or yt-dlp path no longer exists, the next places are
tried and the row says which copy is used; a chosen Python that no longer exists
is reported, not replaced. Paths the check finds are used but not saved: only
**Choose path** saves one. Select a row to see where its tool came from:
**Bundled with Media Manglers**, **Downloaded by Media Manglers**, **Your chosen
path**, **Already on this PC** or **Part of Windows**.

**Python.** Without a chosen Python, Media Manglers uses its own private Python
when your edition carries one. A Python already on your PC is used instead only
when it can do something ours cannot: use your graphics card for Whisper, or
run Argos Translate when translation is set to Local with a language other than
English (English comes from Whisper itself). Its row then says "Kept your
Python because …". The Workbench and `Video Mangler.ps1` look for a Python of
yours in the same places: PATH, the `py` launcher Python's own installer adds,
and the folders that installer uses. If you change **Translate to** or the
processing mode after readiness has run, **Start** asks you to choose **Refresh
readiness** first, so the right Python is used. The Workbench never installs,
upgrades or removes anything in your own Python or in another program; only the
console script, run by hand, offers to install Argos Translate into a Python of
yours, and only after you confirm it. The speech libraries Media Manglers' own
Python needs are kept in `%LOCALAPPDATA%\MediaManglers\addons`, and only its own
Python uses them. If they are not set up yet, a run says to choose **Set up**;
it never suggests pip, which Media Manglers' own Python does not have.

**Paths saved by an earlier version.** An earlier version saved paths it found
as if you had chosen them. Once, when such a saved FFmpeg, FFprobe or Python
path differs from the copy that comes with Media Manglers, the Workbench asks
whether to **Use the bundled copies** or **Keep my paths** (the default). Nothing
changes until you choose.

[Previous: Review Media Inbox](REVIEW_NEW_VIDEOS.md) · [Back to Help](README.md) · [Next: Progress and results](PROGRESS_RESULTS.md)
