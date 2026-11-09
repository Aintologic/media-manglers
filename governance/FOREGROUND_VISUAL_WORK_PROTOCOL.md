# FOREGROUND_VISUAL_WORK_PROTOCOL.md

## Purpose
This document defines the repo-safe protocol for visible desktop or UI work.

Use it when a pass needs a stable on-screen layout, visible desktop interaction,
or UI-state validation.

## Foreground Work Definition
Foreground or visual work includes tasks such as:

- launching or focusing desktop applications
- moving or resizing windows
- taking screenshots for visual validation
- checking overlays, transparency, opacity, or other UI states
- using the desktop or another application window as part of a comparison step

## Protocol
- Batch visible steps into one foreground phase when practical.
- Before starting a foreground phase, use the current machine's operator
  notification and control point if one is defined by higher-precedence
  instructions or machine-local policy.
- If that control point blocks or declines the phase, stop foreground work and
  report that it was blocked.
- Do not add extra chat permission prompts when the active machine protocol
  already provides the operator notification step.
- During the foreground phase, stay scoped to the current task and avoid
  unrelated desktop actions.
- Immediately after the foreground phase ends, run the current machine's
  matching end-of-phase notification or cleanup step when one exists.

## Repo-Safe Rule
- Keep machine-specific helper paths and low-level desktop automation details
  out of tracked repo docs unless explicitly approved.
- If a pass requires visible work and no machine-local foreground protocol is
  available, pause and ask for the safest next step instead of guessing.
