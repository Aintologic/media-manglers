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

> **Download approval:** A missing Whisper model is never downloaded silently.
> Review the size/storage explanation and approve it explicitly.

## Getting a missing tool

When a tool the reviews need is missing, a bar at the top of the window says so
once per launch, names each missing tool and offers **Download**,
**Open Settings > Dependencies** and **Not now**. It never blocks browsing the
app; **Start** stays blocked until the tool is there.

In **Settings > Dependencies**, a missing or outdated tool has a **Download**
button next to its usual action. **Download** opens the tool's official page in
your browser. Select the row to see that page and, where Windows Package Manager
has the tool, the `winget install` command with **Copy winget command**. Paste
the command into a terminal yourself. The Workbench never downloads, installs,
or changes PATH; after installing, choose **Check readiness**.

| Tool | What it is for | Official page | Windows Package Manager |
|---|---|---|---|
| FFmpeg (includes FFprobe) | Audio, frames, clips and stream details | <https://ffmpeg.org/download.html> | `winget install --id Gyan.FFmpeg -e` |
| Python | Runs the helpers and Local Whisper | <https://www.python.org/downloads/windows/> | `winget install --id Python.Python.3.12 -e` |
| Local Whisper | Local transcripts | <https://github.com/openai/whisper#setup> | none; installed with pip into the Python above |
| PyTorch | Runs Whisper on CPU or graphics card | <https://pytorch.org/get-started/locally/> | none; installed with pip, chosen for your graphics card |
| yt-dlp | Web-video URLs in Full Review | <https://github.com/yt-dlp/yt-dlp#installation> | `winget install --id yt-dlp.yt-dlp -e` |
| PowerShell | Runs the Video Mangler workflow | <https://learn.microsoft.com/powershell/scripting/install/install-powershell-on-windows> | `winget install --id Microsoft.PowerShell -e` (Windows PowerShell is built into Windows) |
| VLC media player | Optional player for **Play with > VLC** | <https://www.videolan.org/vlc/> | `winget install --id VideoLAN.VLC -e` |

## Where the Workbench looks for each tool

The Workbench and the `Video Mangler.ps1` and `Audio Mangler.ps1` scripts look
in the same order:

1. the path you chose with **Choose path** (in the scripts, `-FFmpegPath`,
   `-FFprobePath`, `-PythonExe` or `-YtDlpPath`);
2. the system PATH;
3. the folders the tool's own installer uses, such as the Windows Package
   Manager folders and Program Files.

FFprobe is looked for beside FFmpeg first. If a chosen FFmpeg, FFprobe or yt-dlp
path no longer exists, the next places are tried and the row says which copy is
used; a chosen Python that no longer exists is reported, not replaced. Paths
the check finds are used but not saved: only **Choose path** saves one.

[Previous: Review Media Inbox](REVIEW_NEW_VIDEOS.md) · [Back to Help](README.md) · [Next: Progress and results](PROGRESS_RESULTS.md)
