# Working on Media Manglers

Operational notes for Claude working in this repository.

## This file does not govern

`AGENTS.md` and `governance/CURRENT_PROJECT_TRUTH.md` are the governing
documents, in that order, and they apply to every agent. Read `AGENTS.md`
first. This file only records the Claude-specific operational detail those
documents do not cover: how to run the tests here and how to build. Where this
file and `AGENTS.md` appear to disagree, `AGENTS.md` wins.

In particular, `AGENTS.md` already settles who performs merges and where
scratch files go. Do not look for those answers here.

## Never put private information in a public place

The GitHub repository is public. Never write any of the following into an
issue, a pull request title or body, a commit message, a code comment, or any
committed file:

- Links to AI chat sessions of any kind. Agent tooling appends these to commit
  messages and pull request bodies by default. Strip them.
- Absolute paths from the operator's machine.
- Names of personal recordings, folders or media files.
- Anything from the operator's private conversations.

If you think an exception is warranted, ask first. Do not decide on your own.

The privacy check in `tools/privacy/` catches the common cases (paths into a
user profile or checkout, computer and share names, e-mail addresses, AI chat
links, secrets). GitHub Actions runs it on every pull request and push; see
`tools/privacy/README.md` to run it yourself or install it as git hooks.

This rule belongs in `AGENTS.md`, where every agent will read it. It is here
until that move is approved.

## Prove it before you close it

Do not close an issue, or claim a bug is fixed, on reasoning alone. Run the
code, show the output, and quote the evidence. "This should work now" is not
a result.

## Do not hand the operator a diff to apply

When something needs changing in a file the operator owns, supply the whole
replacement block, not a list of lines to delete or edit.

## Machine-local rules

Rules that only apply on one computer (its worktree and
test-runtime setup, local test data, private checks) are kept out of this
public file, in two git-ignored files at the repository root:

- `CLAUDE.local.md`: Claude Code loads it automatically, after this file.
- `AGENTS.local.md`: the same rules for every agent. `CLAUDE.local.md` pulls
  it in with the import line `@AGENTS.local.md`, and `AGENTS.md` tells other
  agents to read it.

Neither file is required; without them, follow this file and `AGENTS.md`.
Never commit either file or copy its contents anywhere public.

## Scratch files

Note that `AREA51/TEMP/` inside this repository is the correct place for
scratch work, per `AGENTS.md`. The folders that are forbidden are machine-level
scratch locations the operating system may purge (for example the system
temporary folder, `%TEMP%`), not any path containing the word TEMP.

## Running the tests

The test runtime is the build-only Python that the first build sets up, plus
pytest and numpy. In a fresh clone, follow "Build and test from a fresh clone"
in `tools/gui/README.md` once before running anything below.

From the repository root:

```
$env:QT_QPA_PLATFORM = 'offscreen'
AREA51\TEMP\workbench-build\python-3.12.10-embed-amd64\python.exe -m pytest tests -q -p no:cacheprovider -o "pythonpath=."
```

Notes:

- The `pythonpath` option must be exactly `pythonpath=.`. Adding `src` to it
  breaks collection with `No module named 'tests'`.
- `QT_QPA_PLATFORM=offscreen` is required or the GUI tests open real windows.
- Run one after another, the full suite takes 80 to 110 minutes. While
  iterating, run only the affected test files and save the full suite for
  before you push.

For the full suite before a push, run it in parallel instead (167). Every
test runs exactly once, spread over several processes; it sets
`QT_QPA_PLATFORM` itself and prints one PASSED or FAILED line at the end:

```
AREA51\TEMP\workbench-build\python-3.12.10-embed-amd64\python.exe tools\validation\run_tests_parallel.py
```

Each process's log is kept under `AREA51\TEMP\test-runs\<time>\`. If a test
fails only in the parallel run, run its file on its own with the command above
before calling it a real failure.

PowerShell functions inside `Video Mangler.ps1` are tested by parsing the file
with `Parser::ParseFile` and re-evaluating the relevant `FunctionDefinitionAst`
extents. See `tests/test_translation_provider.py` and `tests/test_run_control.py`
for the pattern.

## Building the workbench

```
tools\gui\Build-VideoManglerWorkbench.ps1 -Engine PyInstaller -UsePython312BuildRuntime -SmokeTest -ValidationLabel <label-with-no-spaces>
```

The build stamps its identity as CLEAN or DIRTY from `git status --porcelain`.
Untracked files count, so a stray scratch file will produce a DIRTY build.
Check `git status` before building.

The build ends with a 30-second offscreen smoke launch of the frozen
executable, and throws if it times out. Anything that blocks or hangs at
window construction fails the build rather than producing a diagnosable
runtime error.

When you tell the operator to launch a build, always give the version, the
commit hash, the CLEAN/DIRTY state and the SHA-256, so they can confirm they
are not testing an old binary.

## UI changes

Every change to a screen follows `governance/UI_RULES.md` (see the UI rules section of
`AGENTS.md`). Use the theme tokens in `theme.py` and the shared parts in `ui_parts.py`
(`bind_action` for feedback beside a button, `JobBanner` through the window's `make_job_banner`
for a long job). Screens can be photographed offscreen with real fonts by setting
`QT_QPA_FONTDIR` to the Windows Fonts folder; without it offscreen Qt draws every letter as a box.
An offscreen check is not proof that a screen fits: offscreen text is measured by another font
engine than the app's (on Windows the app draws text with GDI, `app.py::qt_arguments`). Check a
changed screen on the real display too, at every text size.

## Conventions

- Branch names: `codex/issue-<numbers>-<short-slug>`.
- Reference issues by number in commit messages; do not paste issue text.
- New behaviour needs a test in `tests/`.
- Documentation for workbench features lives in `docs/workbench/`.
- Keep spotter and filler phrase lists to distinctive multi-word phrases.
  A single common word matches inside ordinary narration and double-counts
  against the longer phrases, which corrupts the signals that decide whether
  a track is the operator's microphone or game audio.

## Talking to the operator

End substantial replies with a numbered list of exactly what to do, with exact
paths, and any text to be pasted elsewhere inside a fenced code block. Put
Windows paths in backticks — underscores in a bare path get eaten by markdown
and the resulting path does not work.
