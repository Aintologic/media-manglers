# Privacy check

This folder keeps personal and machine-specific details out of the repository. It
has two layers.

| Layer | What it catches | Where it runs | Needs private files? |
|---|---|---|---|
| **Generic** (committed) | absolute paths into a user profile, a source checkout or a cloud-sync folder (Windows, Git Bash, WSL, MSYS and Cygwin forms); default Windows computer names; network-share hosts; e-mail addresses; links to AI chat sessions, tasks and share pages; common secret and token formats; a private-patterns file committed by mistake | GitHub Actions on every pull request, push and tag; your own hooks; any time by hand | No |
| **Private** (never committed) | your own names, computer names, folder layout and private repository names | your own hooks and pre-publish check | Yes, and it **fails closed** without them |

GitHub's own push protection covers credentials, but not names or paths. That is
why these checks exist.

## For everyone

Run the check on every tracked file (Python 3.9 or newer, no other packages):

```
python tools/privacy/privacy_check.py
```

It prints `privacy check passed` or lists each finding as `place: rule`, with the
matched text shortened (in file names too), so the output never spreads what it
found. Exit codes: `0` clean, `1` findings, `2` refused (something could not be
checked safely).

| Command | What it scans |
|---|---|
| `privacy_check.py tree` | every tracked file (the default) |
| `privacy_check.py staged` | every staged file in full, every staged path, and the author and committer the commit will carry |
| `privacy_check.py message FILE` | a commit message, comment lines included (up to git's scissors line) |
| `privacy_check.py range BASE..HEAD` | every object in the range (see below) |
| `privacy_check.py history` | every object any branch, tag or other ref reaches |
| `privacy_check.py paths FOLDER-OR-ZIP` | files byte by byte (a built package) |
| `privacy_check.py rules` | lists the rules |

The history commands (`range`, `history`, the pre-push hook, the GitHub Actions
checks) work on git's objects, not on diff text. They read every commit and tag in
full (author, committer and tagger lines, every header and the message), the entry
names of every tree (so empty files and submodule entries count), and every file
version in full. Text added in one commit and removed in a later one is still
found, because the earlier version is still in history.

Every command also reads inside files: ZIP members (including Office documents),
gzip, bzip2 and xz data, PDF streams, the strings inside compiled Python and
PyInstaller executables, UTF-16 text in binaries, and Git LFS files (from the
clone's LFS store; when an LFS file's content is not there, the check refuses).
Archives nested more than five deep are refused rather than skipped.

Install the generic rules as git hooks in your clone (nothing is committed):

```
python tools/privacy/install_hooks.py --mode public
```

It installs pre-commit and pre-merge-commit (staged files), commit-msg (the
message) and pre-push (everything the push sends). `--status` shows what is
installed and `--uninstall` removes it.

### Placeholders that pass

Use these in docs and tests instead of real values: `C:\Users\Example\...`,
`/home/you/...`, `you@example.com` (or any `example.com`, `.test` or `.invalid`
address), a GitHub `users.noreply.github.com` address, `\\server\share`, and
synthetic secrets built at run time (see `tests/test_privacy_check.py`).

`allowlist.json` lifts named generic rules for named paths only: the e-mail rule
for third-party license texts (`licenses/*`, `THIRD_PARTY_NOTICES.txt`), and the
private-patterns-file rule for this checker and this README. Matching is
case-sensitive and `*` never crosses a `/`. The allowlist can never lift a private
rule, and the tests pin its entries so widening one is a visible change.

### Commit author addresses

Your commits' author and committer lines become public with the repository. Use
your GitHub noreply address (`git config user.email <id>+<name>@users.noreply.github.com`).
In GitHub Actions an ordinary e-mail address in those lines is reported as a
warning rather than a failure (every other finding there still fails); the local
hooks treat it as a finding.

### What GitHub Actions runs

On every pull request it scans the tracked files and everything the pull request
adds, using the base branch's copy of the checker. On every push and tag it scans
everything the push added (for a new branch, a tag or a force-push: everything
the pushed ref reaches that the default branch does not), using the previous
commit's copy of the checker. Once a week, and on demand, it scans every branch
and tag, because GitHub sends no push event when more than three tags are pushed
at once.

## For a maintainer with private patterns

### Where the private patterns live

In one JSON file outside every repository folder, so every clone on the computer
finds it and none can commit it:

- default: `~/.config/media-manglers/privacy-private.json`
  (on Windows, `%USERPROFILE%\.config\media-manglers\privacy-private.json`)
- or any path named by the `MEDIA_MANGLERS_PRIVACY_CONFIG` environment variable,
  which wins over the default. If the variable names a missing file, the check
  refuses; it never falls back.

The check refuses a patterns file that sits inside a git repository where it
could be committed.

Its shape (synthetic example):

```json
{
  "schema": "media-manglers-private-privacy/1",
  "rules": [
    {"id": "full-name", "pattern": "Jane[\\s._-]+Example", "flags": "i", "why": "full name"},
    {"id": "computer-names", "pattern": "\\bJANE-PC\\d*\\b", "flags": "i", "why": "computer names"},
    {"id": "folder-layout", "pattern": "[CD]:[\\\\/]+PRIVATE(?![A-Za-z0-9])", "flags": "i",
     "scopes": ["repo", "package"], "why": "folder layout"}
  ],
  "allow": [
    {"pattern": "12345\\+janeexample@users\\.noreply\\.github\\.com", "why": "public commit address"}
  ]
}
```

- `pattern` is a non-empty Python regular expression; `flags` may hold `i`, `m`,
  `s`. A pattern (or allow entry) that matches empty text or an ordinary sentence
  is refused, because it would check nothing or everything.
- `scopes`: `repo` checks source files, staged files, messages and history;
  `package` checks the bytes of built files. Both by default. Use `repo` only for
  a rule that third-party binaries could trip (a common first name, for example).
  Both scopes need at least one rule.
- `allow` lifts a match that sits entirely inside an allowed match on the same
  line. To keep your name in commit author lines but only with your noreply
  address, allow the whole `author <name> <noreply address>` form.
- The output names the rule and the place, never the private text itself.

If a `local-rules` folder sits next to the file, `install_hooks.py --mode private`
copies the `CLAUDE.local.md` and `AGENTS.local.md` in it into the clone (only when
git ignores them, and never over an existing file). These hold the machine-local
agent rules described in `AGENTS.md` and `CLAUDE.md`.

### Install the private hooks in a clone

```
python tools/privacy/install_hooks.py --mode private
```

- The hooks run a copy of the checker that the installer places in the clone's
  hooks folder, taken from the last commit, so an edit to the working tree cannot
  weaken them. After the checker changes, re-run the installer; the hooks print a
  note when they are out of date. The installer refuses to replace that copy from
  a checkout that does not build on the commit it came from (an older branch in
  another worktree, say) unless `--force` is given.
- Private hooks name the patterns file they were installed with (`--config`), so
  setting `MEDIA_MANGLERS_PRIVACY_CONFIG` later cannot swap other patterns in.
- pre-commit also checks the author and committer the commit will carry, and
  commit-msg checks every line git may keep.
- **pre-push** checks everything the push sends, measured against what the
  destination itself advertises right now (`git ls-remote`), never against this
  clone's remote-tracking refs. Re-pointing a remote (`git remote set-url`) or
  pushing to a new, empty repository therefore checks the whole history being
  sent. Ref names, tags of tags, and blobs or trees pushed directly are checked
  too, and local `git replace` objects are ignored.
- Every hook **refuses** and blocks the commit or push (non-zero exit) when the
  private patterns are missing or invalid, when Python cannot be found, or when
  the installed checker copy is missing.
- Re-running the installer in its default mode never turns private hooks into
  public ones. `--mode private` exits non-zero when the patterns are missing (the
  hooks it installs then refuse every commit and push).
- An existing hook the installer did not write is kept only with `--force`, as
  `<hook>.before-privacy`. It runs after the privacy check has passed, so a hook
  such as git-lfs never uploads anything for a push the check blocks. When git's
  `core.hooksPath` is set the installer refuses unless `--allow-hooks-path` is
  given, because that folder may be shared or tracked.
- In a repository with several worktrees, all of them share one hooks folder; the
  installer says so.

`git commit --no-verify` and `git push --no-verify` skip hooks, and so does the
plumbing command `git send-pack`. Do not use them to get past a finding; rewrite
the commit instead (for example with an interactive rebase), then push.

### Pre-publish check

Before publishing anything (making a repository public, a release, a package),
check everything committed in the repository and the built package together, with
the private patterns required:

```
python tools/privacy/privacy_check.py publish --path dist/VideoManglerWorkbench
```

It reads every object any branch, tag or other ref reaches (not the working
copy, which it requires to match the last commit), and every packaged file,
including inside ZIP files and the PyInstaller executable's compressed archive,
where the frozen app's own code lives.

## What it does not catch

- Text inside pictures (screenshots): check those by eye or with OCR before
  publishing.
- Private details written in an unusual form that no rule describes. The rules
  catch the common shapes; a human review before publishing is still needed.
- Anything pasted directly into an issue, a pull request description or a comment
  on GitHub. Those never pass through git; check them before posting.
- A pull request that edits `.github/workflows/privacy-check.yml` itself: GitHub
  runs the pull request's own copy of that file. Require review for changes to
  `.github/` and `tools/privacy/` (branch protection).
