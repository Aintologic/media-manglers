# Workbench Screenshot Maintenance

The tracked Help images use synthetic paths, filenames, dependency states, and review state. They must never be captured from operator history or private media.

## Capture command

Run from the repository root on Windows:

```powershell
$begin = "<your-foreground-helpers>\Agent-BeginForeground.ps1"
$end = "<your-foreground-helpers>\Agent-EndForeground.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $begin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
try {
    py tools\gui\Capture-WorkbenchHelpScreenshots.py --output-dir docs\workbench\images
}
finally {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $end
}
```

The two foreground helpers are machine-local scripts you supply; they are not part of this repository (see [`governance/FOREGROUND_VISUAL_WORK_PROTOCOL.md`](../../governance/FOREGROUND_VISUAL_WORK_PROTOCOL.md)). If you have none, use the off-screen capture below. If the begin helper fails, do not launch the capture. Call the end helper exactly once after a successful begin, including after capture failure.

### Off-screen capture (no window, no focus steal)

When the operator is using the desktop (for example the Workbench is running a real review), capture off-screen instead. No foreground helpers are needed because no window is shown:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QPA_FONTDIR = "C:\Windows\Fonts"   # required, or text renders as boxes
py tools\gui\Capture-WorkbenchHelpScreenshots.py --output-dir docs\workbench\images
```

Off-screen output matches the Windows renderer closely enough for Help images; run the visual QA checklist below either way.

## What the capture does

- Uses the normal Windows Qt renderer.
- Creates a temporary settings/profile root and removes it after capture.
- Injects a fake runner and synthetic `C:\MM-DEMO` state.
- Does not open media, run a review, read operator history, or call the network.
- Refuses to capture visible operator identity or non-demo Windows paths.

The generated files are:

- `images/workbench-home.png`
- `images/find-bug-reports.png`
- `images/find-bug-reports-results.png`
- `images/new-review-narration.png`
- `images/review-and-run-blockers.png`
- `images/queue-and-progress.png`
- `images/dependency-readiness.png`

## Visual QA checklist

Inspect every PNG at original resolution before committing it:

- normal text is readable and contains no missing-glyph boxes;
- headings, rows, actions, progress bars, and selected states are not overlapped;
- intentional below-the-fold content has a visible scrollbar;
- no private name, hostname, source path, output path, recent run, or evidence content is present;
- narration recommendation, confidence, selection reason, and confirmation state are visible;
- progress shows distinct overall/current-stage bars and both queue items;
- dependency states and row actions are fully readable;
- the app version shown matches the version being documented (currently `v0.11.0`).

After capture, run the Help/link/privacy tests (`tests/test_workbench_help.py`) and the Workbench GUI layout tests (`tests/test_workbench_gui.py`). Do not treat image generation alone as acceptance.
