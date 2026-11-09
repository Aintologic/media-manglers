#!/usr/bin/env python3
"""Install the privacy hooks into this clone.

    python tools/privacy/install_hooks.py                # private mode if private patterns exist, else public
    python tools/privacy/install_hooks.py --mode private # require the private patterns (fails closed without them)
    python tools/privacy/install_hooks.py --mode public  # generic rules only
    python tools/privacy/install_hooks.py --status       # show what is installed
    python tools/privacy/install_hooks.py --uninstall    # remove the hooks this script installed

It installs four git hooks: pre-commit and pre-merge-commit (every staged file), commit-msg (the
message) and pre-push (every object the push sends). They are small shell scripts in the clone's
hooks folder, never committed. Each runs a copy of the checker that this script places in the hooks
folder, taken from the last commit, so an edit to the working tree cannot weaken the hooks. After
the checker changes, re-run this script; the hooks print a note when they are out of date.

Safety rules:
- In private mode the hooks refuse (and block) whenever the private patterns are missing or invalid.
- Re-running in the default auto mode never turns private hooks into public ones; only an explicit
  ``--mode public`` does that.
- An existing hook that this script did not write is left alone unless ``--force`` is given; then it
  is kept beside ours and still runs first.
- When git's ``core.hooksPath`` is set, the hooks folder may be shared by other repositories or
  tracked by git, so the script refuses unless ``--allow-hooks-path`` is given.
- In private mode the script also copies your local agent-rule files (``CLAUDE.local.md``,
  ``AGENTS.local.md``) into the clone when a ``local-rules`` folder sits next to the private patterns
  file. It never overwrites a file, and only copies a name git ignores.

Standard library only; Python 3.9 or newer.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import privacy_check  # noqa: E402  (the same folder)

MARKER = "media-manglers privacy hook"
SNAPSHOT_DIR = "media-manglers-privacy"
SNAPSHOT_FILES = ("privacy_check.py", "allowlist.json")
HOOKS: Dict[str, str] = {
    "pre-commit": "staged",
    "pre-merge-commit": "staged",
    "commit-msg": 'message "$1"',
    "pre-push": 'push "$@"',
}
LOCAL_RULE_FILES = ("CLAUDE.local.md", "AGENTS.local.md")

TEMPLATE = """#!/bin/sh
# {marker} ({name}), installed by tools/privacy/install_hooks.py. Mode: {mode}.
# Not committed. It runs the checker copied into the hooks folder at install time, so an edit in the
# working tree cannot weaken it. Re-run the installer to update it; --uninstall removes it.
snapshot={snapshot}
if [ ! -f "$snapshot/privacy_check.py" ]; then
  echo "privacy hook: the installed checker is missing; refusing ({name})." >&2
  echo "privacy hook: re-run python tools/privacy/install_hooks.py from a checkout that has it, or delete this hook file." >&2
  exit 1
fi
current=$(git rev-parse -q --verify HEAD:tools/privacy/privacy_check.py 2>/dev/null)
recorded=$(cat "$snapshot/SOURCE" 2>/dev/null)
if [ -n "$current" ] && [ "$current" != "$recorded" ]; then
  echo "privacy hook: note: this checkout's privacy checker differs from the installed one; re-run python tools/privacy/install_hooks.py to update the hooks." >&2
fi
py=""
for candidate in {candidates}; do
  if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    py="$candidate"
    break
  fi
done
if [ -z "$py" ]; then
  echo "privacy hook: no Python 3.9 or newer found; refusing ({name}). Install Python or re-run the installer." >&2
  exit 1
fi
before={before}
{body}
"""

# The privacy check runs first; a kept earlier hook (git-lfs, for example) runs only after it passed,
# so nothing that hook uploads or changes happens for a commit or push the check blocks.
BODY_SIMPLE = """"$py" "$snapshot/privacy_check.py"{private_flag} {command} || exit $?
if [ -x "$before" ]; then
  exec "$before" "$@"
fi
exit 0"""

BODY_PUSH = """input=$(cat)
printf '%s\\n' "$input" | "$py" "$snapshot/privacy_check.py"{private_flag} {command} || exit $?
if [ -x "$before" ]; then
  printf '%s\\n' "$input" | "$before" "$@" || exit $?
fi
exit 0"""


def git_out(args: Sequence[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise SystemExit(f"git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout.decode("utf-8", "replace").strip()


def hooks_dir(root: Path) -> Path:
    path = Path(git_out(["rev-parse", "--git-path", "hooks"], root))
    return (path if path.is_absolute() else (root / path)).resolve()


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def interpreter_candidates() -> List[str]:
    current = Path(sys.executable).resolve().as_posix() if sys.executable else ""
    return ([current] if current else []) + ["python3", "python"]


def hook_mode(path: Path) -> Optional[str]:
    """'private' or 'public' for a hook this script wrote; None for any other file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if MARKER not in text:
        return None
    return "private" if "Mode: private" in text else "public"


def snapshot_sources(root: Path) -> Tuple[Dict[str, bytes], str, bool]:
    """The checker files from the last commit (or the working tree when not committed yet)."""
    files: Dict[str, bytes] = {}
    committed = True
    for name in SNAPSHOT_FILES:
        rel = f"tools/privacy/{name}"
        proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(root), stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
        if proc.returncode == 0:
            files[name] = proc.stdout
        else:
            committed = False
            files[name] = (root / rel).read_bytes()
    source = git_out(["rev-parse", "-q", "--verify", "HEAD:tools/privacy/privacy_check.py"], root, check=False)
    return files, source, committed


def write_hook(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def copy_local_rules(root: Path, config_path: Path) -> List[str]:
    source = config_path.parent / "local-rules"
    copied: List[str] = []
    if not source.is_dir():
        return copied
    for name in LOCAL_RULE_FILES:
        src, dst = source / name, root / name
        if not src.is_file() or dst.exists():
            continue
        if subprocess.run(["git", "check-ignore", "-q", name], cwd=str(root)).returncode != 0:
            print(f"not copied: {name} is not ignored by git in this clone, so it could be committed")
            continue
        shutil.copyfile(src, dst)
        copied.append(name)
    return copied


def worktree_count(root: Path) -> int:
    listing = git_out(["worktree", "list", "--porcelain"], root, check=False)
    return sum(1 for line in listing.splitlines() if line.startswith("worktree "))


def install(root: Path, mode: str, force: bool, allow_hooks_path: bool) -> int:
    target = hooks_dir(root)
    hooks_path_setting = git_out(["config", "--get", "core.hooksPath"], root, check=False)
    if hooks_path_setting and not allow_hooks_path:
        print("refused: git's core.hooksPath is set, so the hooks folder may be shared by other repositories "
              "or tracked by git. Unset it, or re-run with --allow-hooks-path if that folder is yours alone.")
        return 1
    config_path, where = privacy_check.resolve_config_path()
    existing = {name: hook_mode(target / name) for name in HOOKS}
    if mode == "auto":
        had_private = any(m == "private" for m in existing.values())
        mode = "private" if (had_private or config_path.is_file()) else "public"
    # Check every hook before writing any, so a refusal leaves nothing half-installed.
    foreign = [n for n in HOOKS if (target / n).exists() and existing[n] is None]
    blocked_backups = [n for n in foreign if (target / f"{n}.before-privacy").exists()]
    if foreign and not force:
        print(f"refused: {', '.join(foreign)} already exist and were not installed by this script. Re-run with "
              "--force to keep them beside the privacy hooks (they still run first).")
        return 1
    if blocked_backups:
        print(f"refused: {', '.join(n + '.before-privacy' for n in blocked_backups)} already exist; "
              "move them away first so no earlier hook is lost.")
        return 1
    files, source, committed = snapshot_sources(root)
    snapshot = target / SNAPSHOT_DIR
    head = git_out(["rev-parse", "-q", "--verify", "HEAD"], root, check=False)
    recorded_commit = (snapshot / "COMMIT").read_text(encoding="ascii").strip() if (snapshot / "COMMIT").exists() else ""
    if recorded_commit and head and recorded_commit != head and not force:
        newer = subprocess.run(["git", "merge-base", "--is-ancestor", recorded_commit, head], cwd=str(root),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not newer:
            print("refused: the installed checker copy came from a commit this checkout does not build on (an "
                  "older or unrelated branch, perhaps in another worktree). Run the installer from the newest "
                  "checkout, or re-run with --force to replace it anyway.")
            return 1
    snapshot.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (snapshot / name).write_bytes(data)
    (snapshot / "SOURCE").write_text(source + "\n" if source else "", encoding="ascii")
    (snapshot / "COMMIT").write_text(head + "\n" if head else "", encoding="ascii")
    digest = hashlib.sha256(files["privacy_check.py"]).hexdigest()
    candidates = " ".join(shell_quote(c) for c in interpreter_candidates())
    # A private hook names its patterns file, so an environment variable cannot swap other patterns in.
    flag = f" --private --config {shell_quote(config_path.as_posix())}" if mode == "private" else ""
    for name in foreign:
        os.replace(target / name, target / f"{name}.before-privacy")  # keeps its mode and content
    for name, command in HOOKS.items():
        body = (BODY_PUSH if name == "pre-push" else BODY_SIMPLE).format(private_flag=flag, command=command)
        text = TEMPLATE.format(marker=MARKER, name=name, mode=mode, candidates=candidates,
                               snapshot=shell_quote(snapshot.as_posix()),
                               before=shell_quote((target / f"{name}.before-privacy").as_posix()), body=body)
        write_hook(target / name, text)
    print(f"installed {', '.join(HOOKS)} ({mode} mode) in {target.as_posix()}")
    print(f"checker copy: {snapshot.as_posix()} (sha256 {digest[:16]}...)"
          + ("" if committed else "; WARNING: taken from the working tree, the checker is not committed yet"))
    count = worktree_count(root)
    if count > 1:
        print(f"note: this hooks folder is shared by {count} worktrees of this repository; the hooks run in all of them")
    exit_code = 0
    if mode == "private":
        if config_path.is_file():
            print(f"private patterns: {where} (found)")
        else:
            print(f"private patterns: {where} (MISSING): the hooks will refuse every commit and push until it exists")
            exit_code = 1
        for name in copy_local_rules(root, config_path):
            print(f"copied local agent rules: {name}")
    else:
        print("generic rules only; for private patterns re-run with --mode private")
    return exit_code


def uninstall(root: Path) -> int:
    target = hooks_dir(root)
    for name in HOOKS:
        path = target / name
        if path.exists() and hook_mode(path) is not None:
            path.unlink()
            backup = target / f"{name}.before-privacy"
            if backup.exists():
                os.replace(backup, path)
            print(f"removed {name}")
    snapshot = target / SNAPSHOT_DIR
    if snapshot.is_dir():
        shutil.rmtree(snapshot)
    return 0


def status(root: Path) -> int:
    target = hooks_dir(root)
    print(f"hooks folder: {target.as_posix()}")
    for name in HOOKS:
        path = target / name
        mode = hook_mode(path)
        if not path.exists():
            print(f"{name}: not installed")
        elif mode is not None:
            print(f"{name}: installed ({mode} mode)")
        else:
            print(f"{name}: a different hook is installed")
    recorded = (target / SNAPSHOT_DIR / "SOURCE")
    current = git_out(["rev-parse", "-q", "--verify", "HEAD:tools/privacy/privacy_check.py"], root, check=False)
    if recorded.exists():
        same = recorded.read_text(encoding="ascii").strip() == current
        print(f"checker copy: {'up to date' if same else 'differs from this checkout: re-run the installer'}")
    config_path, where = privacy_check.resolve_config_path()
    print(f"private patterns: {where} ({'found' if config_path.is_file() else 'not found'})")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("auto", "private", "public"), default="auto")
    parser.add_argument("--force", action="store_true", help="keep an existing foreign hook beside ours")
    parser.add_argument("--allow-hooks-path", action="store_true", help="install even though core.hooksPath is set")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--repo", default=".", help="the clone (default: the current folder)")
    args = parser.parse_args(argv)
    root = Path(git_out(["rev-parse", "--show-toplevel"], Path(args.repo)))
    if args.uninstall:
        return uninstall(root)
    if args.status:
        return status(root)
    return install(root, args.mode, args.force, args.allow_hooks_path)


if __name__ == "__main__":
    sys.exit(main())
