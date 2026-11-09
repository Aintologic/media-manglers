#!/usr/bin/env python3
"""Privacy check: keep personal and machine-specific details out of this repository.

It has two layers:

- **Generic rules** (always on, committed, the same for everyone): absolute paths into a user
  profile, source-checkout or cloud-sync folder, default Windows computer names, network-share
  host names, e-mail addresses, links to AI chat sessions, and common secret and token formats.
  They need no private files, so the check passes on any computer and in GitHub Actions.
- **Private rules** (optional, never committed): your own names, computer names, folder
  paths and private repository names, read from a JSON file kept outside every repository folder.
  With ``--private`` the check refuses to run (fails closed) when that file is missing or invalid.

Commands (run ``privacy_check.py <command> --help`` for options):

  tree      every tracked file in the working tree (the default)
  staged    every file staged for the next commit, and the commit's author and committer
            (pre-commit and pre-merge-commit hooks)
  message   a commit message file (the commit-msg hook)
  push      every object a push sends, from the lines git gives a pre-push hook
  range     every object in a revision range such as BASE..HEAD (GitHub Actions on pull requests)
  ci-push   every object a push to GitHub added (GitHub Actions on pushes)
  history   every object reachable from any ref (GitHub Actions on a schedule; publish)
  paths     files, folders, archives and PyInstaller executables, byte by byte (a built package)
  publish   everything committed in this repository plus any --path; private rules required

The history commands work on git's objects, not on diff text: every commit and tag is read in full
(author, committer, tagger, every header and the message), every tree's entry names, and every blob
in full, including what is inside ZIP, gzip, bzip2 and xz files, PDF streams and Git LFS files.
What a push sends is measured against what the destination itself advertises (``git ls-remote``),
never against this clone's remote-tracking refs, so re-pointing a remote cannot hide old history.

Exit codes: 0 clean, 1 findings, 2 refused (missing or invalid private patterns, a git error, or
something that could not be checked). The output never repeats a private match and shortens every
generic match, in file names too, so a log or a pasted error does not spread what it found.
Standard library only; Python 3.9 or newer.
"""

from __future__ import annotations

import argparse
import bz2
import fnmatch
import gzip
import io
import json
import lzma
import marshal
import os
import re
import struct
import subprocess
import sys
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

CONFIG_ENV = "MEDIA_MANGLERS_PRIVACY_CONFIG"
DEFAULT_BRANCH_ENV = "PRIVACY_DEFAULT_BRANCH"
DEFAULT_CONFIG_DISPLAY = "~/.config/media-manglers/privacy-private.json"
CONFIG_SCHEMA = "media-manglers-private-privacy/1"
ALLOWLIST_FILE = Path(__file__).resolve().with_name("allowlist.json")

EXIT_CLEAN, EXIT_FINDINGS, EXIT_REFUSED = 0, 1, 2
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_NESTING = 5
GIT_TIMEOUT = 1800
SEP = r"[\\/]+"  # one or more path separators (escaped backslashes in code are just more of them)
# Ordinary text a private rule or allow entry must not match: a rule that does checks nothing useful
# (or everything), and an allow entry that does lifts every private rule.
NEUTRAL_CORPUS = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit 0123456789.",
    "the and of to in is it for on with as by at from this that be are was",
    "x" * 300,
    "a b c d e f g h i j k l m n o p q r s t u v w x y z " * 6,
    "C:\\Program Files\\Tool\\tool.exe /usr/local/bin/tool https://example.com/path?q=1",
)
SCISSORS = "# ------------------------ >8 ------------------------"
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"

# Scopes: "repo" rules read source text (files, staged changes, history); "package" rules read the
# bytes of built files, where third-party binaries legitimately carry e-mails and their own paths.
REPO, PACKAGE = "repo", "package"


def default_config_path() -> Path:
    return Path.home() / ".config" / "media-manglers" / "privacy-private.json"


# --------------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------------

@dataclass
class Rule:
    rule_id: str
    description: str
    pattern: "re.Pattern[str]"
    scopes: Tuple[str, ...] = (REPO,)
    private: bool = False
    hints: Tuple[str, ...] = ()  # lower-case substrings; the regex runs only when one is present
    allowed: Optional[Callable[["re.Match[str]", str], bool]] = None

    def matches(self, text: str, lowered: str, scope: str) -> Iterator["re.Match[str]"]:
        if self.hints and not any(h in lowered for h in self.hints):
            return
        for match in self.pattern.finditer(text):
            if self.allowed is not None and self.allowed(match, scope):
                continue
            yield match


PLACEHOLDER_USERS = {
    "example", "exampleuser", "example-user", "example user", "someone", "somebody", "public", "default",
    "default user", "all users", "shared", "user", "username", "user-name", "user name", "yourname",
    "your-name", "your name", "youruser", "yourusername", "your user", "myuser", "my-user", "myname", "you",
    "me", "name", "test", "testuser", "tester", "dev", "developer", "admin", "administrator", "operator",
    "owner", "synthetic", "fake", "placeholder", "foo", "bar", "alice", "bob", "jane", "john", "jdoe",
    "john doe", "jane doe", "runner", "runneradmin", "linuxbrew", "ubuntu", "vscode", "node", "pi",
    "vagrant", "jovyan", "root", "containeradministrator", "containeruser", "wdagutilityaccount",
}
# Names that third-party binaries carry: Qt's build account, and a CPython documentation example.
PACKAGE_THIRD_PARTY_USERS = {"qt", "barney"}
PLACEHOLDER_PREFIX = re.compile(
    r"^(?:example|synthetic|sample|placeholder|dummy|test|your|my)(?:$|[\d_.\- ])|^(?:user|test)\d+$")
PATH_STOP = "\\/\r\n\"'`<>|:*?,;%"


def _placeholder_user(name: str, scope: str) -> bool:
    lowered = name.strip().strip(".").lower()
    if not lowered or lowered in PLACEHOLDER_USERS:
        return True
    if scope == PACKAGE and lowered in PACKAGE_THIRD_PARTY_USERS:
        return True
    if any(ch in lowered for ch in "<>%${}*…[]()"):
        return True  # %USERNAME%, $env:USERNAME, <name>, {user}, ...
    return bool(PLACEHOLDER_PREFIX.match(lowered))


def _allowed_profile(match: "re.Match[str]", scope: str) -> bool:
    segment = match.group("user")
    following = match.string[match.end():match.end() + 1]
    # A folder name ends at a separator, so spaces belong to it ("C:\Users\Example User\x"). In prose
    # the path may just end ("C:\Users\Example and then"): then only the first word is the name.
    if not following or following not in "\\/%":
        segment = segment.split()[0] if segment.split() else segment
    return _placeholder_user(segment, scope)


EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net", "example.edu")
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")
NOREPLY_DOMAINS = ("users.noreply.github.com", "noreply.github.com")
IMAGE_SCALE = re.compile(r"^\d+(?:\.\d+)?x\.(?:png|jpe?g|gif|svg|webp|avif|ico|bmp|tiff?|jxl|json)$")


def _allowed_email(match: "re.Match[str]", scope: str) -> bool:
    address = match.group(0).lower()
    local, _, domain = address.rpartition("@")
    if domain in EXAMPLE_DOMAINS or domain.endswith(tuple("." + d for d in EXAMPLE_DOMAINS)):
        return True
    if domain.endswith(RESERVED_SUFFIXES) or domain == "localhost":
        return True
    if domain in NOREPLY_DOMAINS or domain.endswith(tuple("." + d for d in NOREPLY_DOMAINS)):
        return True
    if local in ("noreply", "no-reply", "git") or local.startswith(("noreply+", "no-reply+")):
        return True
    return bool(IMAGE_SCALE.match(domain))  # logo@2x.png: the high-DPI image naming convention


PLACEHOLDER_HOSTS = {"server", "host", "hostname", "localhost", "nas", "fileserver", "share", "computer",
                     "machine", "my-pc", "your-pc", "wsl$", "wsl.localhost", "?", ".", "127.0.0.1"}


def _placeholder_host(host: str) -> bool:
    host = host.lower()
    if host in PLACEHOLDER_HOSTS or host.endswith(("-server", "-host", "-nas", "-share")):
        return True
    return bool(re.match(r"^(?:example|synthetic|your|some|server|test|sample)(?:$|[\d_.\-])", host))


def _allowed_unc(match: "re.Match[str]", scope: str) -> bool:
    # In source code a single backslash is often written escaped ("\\folder\\file"): a two-backslash
    # start followed by escaped separators is an ordinary relative path, not a share. A real share is
    # \\host\share as written, or \\\\host\\share when every backslash is escaped.
    if (len(match.group("pre")), len(match.group("sep"))) not in ((2, 1), (4, 2)):
        return True
    return _placeholder_host(match.group("host"))


def _token_around(text: str, start: int) -> str:
    """The run of non-space characters containing position ``start`` (up to it)."""
    left = start
    while left > 0 and not text[left - 1].isspace() and text[left - 1] not in "\"'`(<[":
        left -= 1
    return text[left:start]


def _allowed_cloud(match: "re.Match[str]", scope: str) -> bool:
    before = _token_around(match.string, match.start())
    if "://" in before:
        return True  # a web address, such as a documentation link, not a folder on someone's disk
    # An option prefix is not part of the path: --out=C:\x, dir:C:\x.
    before = re.sub(r"^[\w.\-]{2,}[=:](?=[A-Za-z]:|[/\\~%$])", "", before)
    if re.search(r"(?i)(?:site|dist)-packages|node_modules", before):
        return True  # a library's own module folder
    return not re.match(r"^(?:[A-Za-z]:|~|%|\$|\\\\|/)", before)  # relative paths are someone's code


def _allowed_checkout(match: "re.Match[str]", scope: str) -> bool:
    first = re.split(r"[\\/]+", match.group(0))
    return len(first) > 1 and first[1].lower().startswith(("programdata", "program files"))


def _allowed_aws(match: "re.Match[str]", scope: str) -> bool:
    return match.group(0).endswith("EXAMPLE")  # AWS's own documentation example key


def _generic_rules() -> List[Rule]:
    rx = re.compile
    both = (REPO, PACKAGE)
    profile_roots = (
        r"(?<![A-Za-z0-9])[A-Za-z]:" + SEP + r"(?i:users)" + SEP,
        r"(?<![\w.-])(?:/mnt|/cygdrive)?/[a-zA-Z]/(?i:users)/",
        r"(?<![\w.-])(?:/var)?/home/",
        r"(?<![\w.-])/Users/",
        r"(?i:[\\/](?:msys64|msys32|msys2|cygwin64|cygwin)" + SEP + r"home)" + SEP,
        r"(?i:(?:\\\\|//)wsl(?:\$|\.localhost)" + SEP + r"[^\\/\s]+" + SEP + r"home)" + SEP,
        r"(?i:[a-z]%3a(?:%5c|%2f)+users(?:%5c|%2f)+)",
    )
    rules = [
        Rule("user-profile-path",
             "absolute path into a real user's profile folder (use a placeholder such as C:\\Users\\Example)",
             rx(r"(?:" + "|".join(profile_roots) + r")(?P<user>[^\s" + re.escape(PATH_STOP) + r"][^"
                + re.escape(PATH_STOP) + r"]*)"),
             scopes=both, hints=("users", "/home/", "\\home\\", "%3a"), allowed=_allowed_profile),
        Rule("checkout-path",
             "absolute path into a source-checkout folder (GitHub, GitLab, source\\repos); use a relative path",
             rx(r"(?i)(?:(?<![A-Za-z0-9])[a-z]:" + SEP + r"|(?<![\w.-])(?:/mnt|/cygdrive)?/[a-z]/)"
                + r"(?:[^\\/\r\n\"'`<>|:*?]+" + SEP + r"){0,10}?"
                + r"(?:github|gitlab|bitbucket|source" + SEP + r"repos)[\\/]"),
             scopes=both, hints=("github", "gitlab", "bitbucket", "repos"), allowed=_allowed_checkout),
        Rule("cloud-sync-path",
             "absolute path into a cloud-sync folder (OneDrive, Dropbox, Google Drive, iCloud Drive)",
             rx(r"(?i)[\\/](?:onedrive(?: - [^\\/\r\n\"']+|-[^\\/\r\n\"']+)?|dropbox|google drive|my drive"
                r"|icloud ?drive|box sync|cloudstorage" + SEP + r"[^\\/\r\n\"']+)[\\/]"),
             scopes=both, hints=("onedrive", "dropbox", "google drive", "my drive", "icloud", "box sync",
                                 "cloudstorage"), allowed=_allowed_cloud),
        Rule("default-computer-name",
             "a default Windows computer name (DESKTOP- or LAPTOP- and seven letters and digits, or WIN- and eleven)",
             rx(r"(?i)(?<![A-Za-z0-9])(?:(?:desktop|laptop)-(?=[a-z]*\d)[a-z0-9]{7}"
                r"|win-(?=[a-z]*\d)[a-z0-9]{11})(?![A-Za-z0-9])"),
             scopes=both, hints=("desktop-", "laptop-", "win-")),
        Rule("network-share-host",
             "a network-share path naming a real host (use \\\\server\\share)",
             rx(r"(?<![A-Za-z0-9_\\/])(?P<pre>\\\\\\\\|\\\\)(?P<host>[A-Za-z0-9][A-Za-z0-9._$-]{0,62})"
                r"(?P<sep>\\\\|\\)(?=[A-Za-z0-9$._ -])"),
             scopes=both, hints=("\\\\",), allowed=_allowed_unc),
        Rule("network-share-url",
             "an smb:// or file:// address naming a real host (use server as the host)",
             rx(r"(?i)\b(?:smb|file)://(?:[^@/\s]+@)?(?://)?(?P<host>[A-Za-z0-9][A-Za-z0-9._-]{0,62})(?=/|\s|$)"),
             scopes=both, hints=("smb://", "file://"), allowed=lambda m, s: _placeholder_host(m.group("host"))),
        Rule("email-address",
             "an e-mail address (use you@example.com, or a GitHub noreply address)",
             rx(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])"),
             hints=("@",), allowed=_allowed_email),
        Rule("ai-chat-link",
             "a link to an AI chat session, task or share page",
             rx(r"(?i)(?:https?://)?(?:www\.)?(?:"
                r"claude\.ai/(?:chat|share|project|code|artifact|public/artifacts)/[\w-]{4,}"
                r"|claude\.site/artifacts/"
                r"|chatgpt\.com/(?:c|share|codex/tasks|canvas/shared)/"
                r"|(?:chatgpt\.com|chat\.openai\.com)/g/[^/\s]+/c/"
                r"|chat\.openai\.com/(?:c|share)/"
                r"|gemini\.google\.com/(?:u/\d+/)?(?:app|share|gem)/"
                r"|g\.co/gemini/share/"
                r"|aistudio\.google\.com/(?:u/\d+/)?app/prompts/"
                r"|bard\.google\.com/"
                r"|copilot\.microsoft\.com/(?:chats|shares)/"
                r"|github\.com/copilot/(?:c|share)/"
                r"|chat\.mistral\.ai/chat/"
                r"|chat\.deepseek\.com/a/chat/"
                r"|meta\.ai/c/"
                r"|poe\.com/s/"
                r"|perplexity\.ai/(?:search|page)/"
                r"|grok\.com/(?:chat|share)/"
                r"|x\.com/i/grok"
                r"|huggingface\.co/chat/(?:conversation|r)/"
                r"|jules\.google\.com/task/"
                r")[^\s)\"'<>]*"),
             scopes=both,
             hints=("claude.ai", "claude.site", "chatgpt.com", "chat.openai", "gemini.google", "g.co/gemini",
                    "aistudio.google", "bard.google", "copilot", "mistral.ai", "deepseek.com", "meta.ai",
                    "poe.com", "perplexity.ai", "grok", "huggingface.co/chat", "jules.google")),
        Rule("private-patterns-file",
             "a private privacy-patterns file (it must stay outside every repository)",
             rx(r"media-manglers-private-privacy/\d"),
             scopes=both, hints=("media-manglers-private-privacy/",)),
    ]
    secrets = [
        ("secret-github-token", "a GitHub token",
         r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255})", ("gh", "github_pat_"), None),
        ("secret-gitlab-token", "a GitLab token", r"\bglpat-[A-Za-z0-9_-]{20,}", ("glpat-",), None),
        ("secret-aws-access-key", "an AWS access key id", r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])",
         ("akia", "asia"), _allowed_aws),
        ("secret-slack-token", "a Slack token or webhook",
         r"\bxox[abprs]-[A-Za-z0-9-]{10,}|\bxapp-\d-[A-Za-z0-9-]{10,}"
         r"|hooks\.slack\.com/(?:services|triggers|workflows)/[A-Za-z0-9/]{20,}", ("xox", "xapp-", "hooks.slack.com"),
         None),
        ("secret-discord-webhook", "a Discord webhook",
         r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]{60,}", ("discord",), None),
        ("secret-openai-key", "an OpenAI API key",
         r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}|\bsk-[A-Za-z0-9]{40,}", ("sk-",), None),
        ("secret-anthropic-key", "an Anthropic API key", r"\bsk-ant-[a-z]+\d{2}-[A-Za-z0-9_-]{20,}", ("sk-ant-",),
         None),
        ("secret-google-api-key", "a Google API key", r"\bAIza[0-9A-Za-z_-]{35}", ("aiza",), None),
        ("secret-google-oauth-secret", "a Google OAuth client secret", r"\bGOCSPX-[A-Za-z0-9_-]{28}", ("gocspx-",),
         None),
        ("secret-stripe-live-key", "a Stripe live key", r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}", ("_live_",), None),
        ("secret-azure-key", "an Azure account or shared-access key",
         r"(?:AccountKey|SharedAccessKey)=[A-Za-z0-9+/]{40,}={0,2}", ("accountkey=", "sharedaccesskey="), None),
        ("secret-azure-sas", "an Azure shared-access signature", r"(?:^|[?&\"'\s])sig=[A-Za-z0-9%+/=]{30,}",
         ("sig=",), None),
        ("secret-jwt", "a JSON web token", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
         ("eyj",), None),
        ("secret-npm-token", "an npm token", r"\bnpm_[A-Za-z0-9]{36}(?![A-Za-z0-9])", ("npm_",), None),
        ("secret-huggingface-token", "a Hugging Face token", r"\bhf_[A-Za-z0-9]{34,}", ("hf_",), None),
        ("secret-pypi-token", "a PyPI token", r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}", ("pypi-",), None),
        ("secret-telegram-token", "a Telegram bot token", r"(?<!\d)\d{8,10}:AA[A-Za-z0-9_-]{33}(?![A-Za-z0-9_-])",
         (":aa",), None),
        ("secret-sendgrid-key", "a SendGrid key", r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}", ("sg.",), None),
    ]
    for rule_id, description, pattern, hints, allowed in secrets:
        rules.append(Rule(rule_id, description, re.compile(pattern), scopes=both, hints=hints, allowed=allowed))
    # A private key header on its own counts in source text; in built files it needs a key body after
    # it, because TLS libraries carry the bare header as a constant.
    rules.append(Rule("secret-private-key", "a private key block",
                      re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
                      scopes=(REPO,), hints=("private key",)))
    rules.append(Rule("secret-private-key", "a private key block",
                      re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----(?:\\[rn]|\s)*"
                                 r"[A-Za-z0-9+/]{40}"),
                      scopes=(PACKAGE,), hints=("private key",)))
    return rules


GENERIC_RULES = _generic_rules()
GENERIC_IDS = {r.rule_id for r in GENERIC_RULES}
IDENTITY_PREFIXES = ("author ", "committer ", "tagger ")


# --------------------------------------------------------------------------------------------
# Private patterns
# --------------------------------------------------------------------------------------------

class Refused(Exception):
    """The check cannot run safely; it refuses instead of passing."""


@dataclass
class PrivateConfig:
    rules: List[Rule]
    allow: List["re.Pattern[str]"] = field(default_factory=list)


def _flags(text: str) -> int:
    flags = 0
    for ch in text:
        if ch == "i":
            flags |= re.IGNORECASE
        elif ch == "m":
            flags |= re.MULTILINE
        elif ch == "s":
            flags |= re.DOTALL
        else:
            raise ValueError(f"unknown regex flag {ch!r}")
    return flags


def resolve_config_path(explicit: str = "") -> Tuple[Path, str]:
    """Where the private patterns are expected, and how to name that place in a message.

    An installed hook passes ``--config`` with the path recorded at install time, so an environment
    variable cannot swap other patterns in under it.
    """
    if explicit:
        return Path(os.path.expanduser(explicit)).resolve(), "the patterns file the hooks were installed with"
    override = os.environ.get(CONFIG_ENV, "").strip()
    if override:
        return Path(os.path.expanduser(override)).resolve(), f"the file named by {CONFIG_ENV}"
    return default_config_path(), DEFAULT_CONFIG_DISPLAY


def _outside_env() -> Dict[str, str]:
    """git's environment for a folder outside the repository being checked: inside a hook git
    exports GIT_DIR and friends, which would otherwise point every git call at this repository."""
    env = _git_env()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES"):
        env.pop(name, None)
    return env


def _committable(path: Path) -> bool:
    """True when ``path`` lies inside a git work tree and git does not ignore it there."""
    folder = path.parent
    inside = subprocess.run(["git", "-C", str(folder), "rev-parse", "--is-inside-work-tree"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_outside_env())
    if inside.returncode != 0 or inside.stdout.strip() != b"true":
        return False
    ignored = subprocess.run(["git", "-C", str(folder), "check-ignore", "-q", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_outside_env())
    return ignored.returncode != 0


def _strict_pattern(item: object, where: str, what: str) -> "re.Pattern[str]":
    if not isinstance(item, dict):
        raise Refused(f"private patterns ({where}): {what} is not an object")
    pattern, flags = item.get("pattern"), item.get("flags", "")
    if not isinstance(pattern, str) or not pattern or not isinstance(flags, str):
        raise Refused(f"private patterns ({where}): {what} needs a non-empty string pattern")
    try:
        compiled = re.compile(pattern, _flags(flags))
    except (ValueError, re.error):
        raise Refused(f"private patterns ({where}): {what} does not compile") from None
    if compiled.search("") is not None or any(compiled.search(sample) for sample in NEUTRAL_CORPUS):
        raise Refused(f"private patterns ({where}): {what} matches ordinary text; refusing rather than "
                      "checking nothing (or everything)")
    return compiled


def load_private_config(path: Path, where: str) -> PrivateConfig:
    if not path.is_file():
        raise Refused(
            f"private patterns not found ({where}). This check fails closed: create that file "
            f"(see tools/privacy/README.md), or set {CONFIG_ENV} to its path.")
    if _committable(path):
        raise Refused(f"private patterns ({where}) sit inside a git repository where they could be committed; "
                      "keep them outside every repository folder")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise Refused(f"private patterns could not be read ({where}): {exc.__class__.__name__}") from None
    if not isinstance(data, dict) or data.get("schema") != CONFIG_SCHEMA:
        raise Refused(f"private patterns ({where}) must be a JSON object with \"schema\": \"{CONFIG_SCHEMA}\"")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise Refused(f"private patterns ({where}) have no rules; refusing rather than checking nothing")
    rules: List[Rule] = []
    seen: Set[str] = set()
    for index, item in enumerate(raw_rules, 1):
        compiled = _strict_pattern(item, where, f"rule {index}")
        rule_id, scopes, why = item.get("id"), item.get("scopes", [REPO, PACKAGE]), item.get("why", "")
        if not isinstance(rule_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", rule_id) or rule_id in seen:
            raise Refused(f"private patterns ({where}): rule {index} needs a unique id of letters, digits, . _ -")
        if not isinstance(scopes, list) or not scopes or any(s not in (REPO, PACKAGE) for s in scopes):
            raise Refused(f"private patterns ({where}): rule {index} scopes must be a list of repo / package")
        if not isinstance(why, str):
            raise Refused(f"private patterns ({where}): rule {index} why must be text")
        seen.add(rule_id)
        rules.append(Rule("private:" + rule_id, why or "private pattern", compiled, scopes=tuple(scopes),
                          private=True))
    allow_items = data.get("allow", [])
    if not isinstance(allow_items, list):
        raise Refused(f"private patterns ({where}): allow must be a list")
    allow = [_strict_pattern(item, where, f"allow entry {index}") for index, item in enumerate(allow_items, 1)]
    for scope in (REPO, PACKAGE):
        if not any(scope in r.scopes for r in rules):
            raise Refused(f"private patterns ({where}) have no rule for the {scope} scope")
    for rule in rules:  # the output prints ids and descriptions, so they must not hold private text
        for other in rules:
            if other.pattern.search(rule.rule_id) or other.pattern.search(rule.description):
                raise Refused(f"private patterns ({where}): a rule's id or why matches a private rule; "
                              "it would be printed in every finding")
    return PrivateConfig(rules, allow)


# --------------------------------------------------------------------------------------------
# Committed allowlist (paths whose content may legitimately trip a generic rule)
# --------------------------------------------------------------------------------------------

def glob_match(path: str, pattern: str) -> bool:
    """Case-sensitive; '*' never crosses a '/', so 'licenses/*' means files directly in licenses/."""
    parts, pats = path.split("/"), pattern.split("/")
    return len(parts) == len(pats) and all(fnmatch.fnmatchcase(p, q) for p, q in zip(parts, pats))


def load_allowlist(path: Path = ALLOWLIST_FILE) -> List[Tuple[str, Tuple[str, ...]]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = []
        for item in data["paths"]:
            glob, rules = item["glob"], item["rules"]
            if not isinstance(glob, str) or not glob or not isinstance(rules, list) or not rules:
                raise ValueError("empty entry")
            if any(not isinstance(r, str) or r not in GENERIC_IDS for r in rules):
                raise ValueError("unknown rule")
            entries.append((glob, tuple(rules)))
        return entries
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused("tools/privacy/allowlist.json is invalid (every entry needs a glob and a list of "
                      "generic rule ids)") from None


# --------------------------------------------------------------------------------------------
# Reading inside files
# --------------------------------------------------------------------------------------------

@dataclass
class Finding:
    where: str
    rule: Rule
    excerpt: str
    identity: bool = False  # in a commit's author, committer or tagger line

    def render(self) -> str:
        if self.rule.private:
            return f"  {self.where}: {self.rule.rule_id} ({self.rule.description})"
        return f"  {self.where}: {self.rule.rule_id}: {self.excerpt} ({self.rule.description})"


def mask(text: str) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) <= 4:
        return "…" * len(text)
    return f"{text[:2]}…{text[-1]} ({len(text)} chars)"


def decode_blob(data: bytes) -> Tuple[str, bool]:
    """(text, is_text). Binary data comes back as Latin-1 so every byte stays one character."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), True
        except UnicodeDecodeError:
            pass
    if b"\x00" in data[:8192]:
        return data.decode("latin-1"), False
    try:
        return data.decode("utf-8-sig"), True
    except UnicodeDecodeError:
        return data.decode("latin-1"), False


ASCII_RUN = re.compile(rb"[\x20-\x7e\t]{4,}")
UTF16_RUN = re.compile(rb"(?:[\x20-\x7e\t]\x00){4,}")


def binary_strings(data: bytes) -> str:
    """The readable strings in binary data, one per line (ASCII and UTF-16), like the strings tool:
    a word that ends where the next string begins still ends there."""
    parts = [m.group(0).decode("latin-1") for m in ASCII_RUN.finditer(data)]
    parts += [m.group(0).decode("utf-16-le", "replace") for m in UTF16_RUN.finditer(data)]
    return "\n".join(parts)


MARSHAL_SHORT = {ord("z"), ord("Z"), ord("z") | 0x80, ord("Z") | 0x80}
MARSHAL_LONG = {ord(c) | flag for c in "sutaA" for flag in (0, 0x80)}


def marshal_strings(data: bytes) -> str:
    """Strings inside marshalled Python code (.pyc files, PyInstaller modules), one per line. Read
    from the marshal type codes, so a string followed directly by the next object still ends."""
    out = []
    i, end = 0, len(data)
    while i < end - 1:
        code = data[i]
        if code in MARSHAL_SHORT:
            size = data[i + 1]
            piece = data[i + 2:i + 2 + size]
            if size >= 3 and len(piece) == size and all(32 <= b < 127 or b in (9, 10, 13) for b in piece):
                out.append(piece.decode("ascii"))
                i += 2 + size
                continue
        elif code in MARSHAL_LONG and i + 5 <= end:
            size = int.from_bytes(data[i + 1:i + 5], "little")
            if 3 <= size <= 1 << 20 and i + 5 + size <= end:
                piece = data[i + 5:i + 5 + size]
                try:
                    text = piece.decode("utf-8")
                except UnicodeDecodeError:
                    text = ""
                if text and sum(ch.isprintable() or ch in "\t\r\n" for ch in text) >= 0.9 * len(text):
                    out.append(text)
                    i += 5 + size
                    continue
        i += 1
    return "\n".join(out)


PYI_MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"


def pyinstaller_pieces(data: bytes) -> Optional[List[Tuple[str, bytes, bool]]]:
    """(name, bytes, is_code) for what a PyInstaller executable's archive holds; None if no archive."""
    pos = data.rfind(PYI_MAGIC)
    if pos < 0:
        return None
    cookie = "!8sIIii64s"
    _, pkg_len, toc_off, toc_len, _pyver, _pylib = struct.unpack_from(cookie, data, pos)
    start = pos + struct.calcsize(cookie) - pkg_len
    toc = data[start + toc_off:start + toc_off + toc_len]
    pieces: List[Tuple[str, bytes, bool]] = []
    i = 0
    while i < len(toc):
        entry_len, offset, size, _usize, compressed, kind = struct.unpack_from("!IIIIBc", toc, i)
        if entry_len <= 18:
            raise ValueError("bad archive entry")
        name = toc[i + 18:i + entry_len].rstrip(b"\x00").decode("utf-8", "replace")
        raw = data[start + offset:start + offset + size]
        blob = zlib.decompress(raw) if compressed else raw
        if kind == b"z" and blob[:4] == b"PYZ\x00":
            (pyz_toc_off,) = struct.unpack_from("!i", blob, 8)
            pyz_toc = marshal.loads(blob[pyz_toc_off:])
            items = pyz_toc.items() if isinstance(pyz_toc, dict) else pyz_toc
            for module, (_kind, mod_off, mod_len) in items:
                pieces.append((f"{name}!{module}", zlib.decompress(blob[mod_off:mod_off + mod_len]), True))
        else:
            pieces.append((name, blob, kind in (b"s", b"m", b"M")))
        i += entry_len
    return pieces


PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def inner_files(data: bytes, label: str) -> Optional[List[Tuple[str, bytes, bool]]]:
    """(name, bytes, is_code) for the files inside an archive or compressed stream; None if not one."""
    if data[:4] == b"PK\x03\x04":
        try:
            pieces = []
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if info.file_size > MAX_FILE_BYTES:
                        raise Refused(f"{label}: a member is too large to check")
                    pieces.append((info.filename, archive.read(info), info.filename.endswith(".pyc")))
            return pieces
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error):
            raise Refused(f"{label} looks like a ZIP file but could not be opened; check it by hand") from None
    for magic, opener, suffix in ((b"\x1f\x8b", gzip.decompress, "gunzip"), (b"BZh", bz2.decompress, "bunzip2"),
                                  (b"\xfd7zXZ\x00", lzma.decompress, "unxz")):
        if data.startswith(magic):
            try:
                inner = opener(data)
            except (OSError, EOFError, ValueError, lzma.LZMAError, zlib.error):
                return None  # not really compressed
            return [(suffix, inner, False)]
    if data.startswith(b"%PDF"):
        pieces = []
        for number, match in enumerate(PDF_STREAM.finditer(data), 1):
            try:
                pieces.append((f"stream {number}", zlib.decompress(match.group(1)), False))
            except zlib.error:
                continue  # not a Flate stream; its raw bytes are read with the file
        return pieces
    if PYI_MAGIC in data[-(1 << 20):]:
        try:
            return pyinstaller_pieces(data)
        except (ValueError, struct.error, zlib.error, EOFError, TypeError):
            raise Refused(f"{label} holds a PyInstaller archive that could not be expanded") from None
    return None


# --------------------------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------------------------

class Scanner:
    def __init__(self, private: Optional[PrivateConfig], allowlist: Sequence[Tuple[str, Tuple[str, ...]]],
                 lfs_dir: Optional[Path] = None):
        self.private = private
        self.allowlist = list(allowlist)
        self.lfs_dir = lfs_dir
        self.findings: List[Finding] = []
        self._seen: Set[Tuple[str, str]] = set()

    def rules_for(self, scope: str, path: str = "") -> List[Rule]:
        rules = [r for r in GENERIC_RULES if scope in r.scopes]
        if path:
            skipped = {rid for glob, rids in self.allowlist if glob_match(path, glob) for rid in rids}
            rules = [r for r in rules if r.rule_id not in skipped]
        if self.private is not None:
            rules += [r for r in self.private.rules if scope in r.scopes]
        return rules

    def _all_rules(self) -> List[Rule]:
        return list(GENERIC_RULES) + (list(self.private.rules) if self.private is not None else [])

    def _hits(self, text: str, rules: Sequence[Rule], scope: str,
              extra: Sequence[str] = ()) -> Iterator[Tuple[Rule, "re.Match[str]", str]]:
        variants = [text, *extra]
        if "\x00" in text and not extra:
            variants.append(text.replace("\x00", ""))
        for variant in variants:
            lowered = variant.lower()
            allow_spans: Optional[List[Tuple[int, int]]] = None
            for rule in rules:
                for match in rule.matches(variant, lowered, scope):
                    if rule.private and self.private is not None and self.private.allow:
                        if allow_spans is None:  # computed once per text, not once per match
                            allow_spans = [m.span() for a in self.private.allow for m in a.finditer(variant)]
                        if any(s <= match.start() and match.end() <= e for s, e in allow_spans):
                            continue
                    yield rule, match, variant

    def safe_label(self, label: str) -> str:
        """The label with every match of every rule masked, whatever the scope being checked."""
        spans = []
        for rule, match, variant in self._hits(label, self._all_rules(), REPO):
            if variant is label:
                spans.append((match.start(), match.end(), "[private]" if rule.private else mask(match.group(0))))
        for rule, match, variant in self._hits(label, self._all_rules(), PACKAGE):
            if variant is label:
                spans.append((match.start(), match.end(), "[private]" if rule.private else mask(match.group(0))))
        out, last = [], 0
        for start, end, repl in sorted(spans):
            if start < last:
                continue
            out.append(label[last:start])
            out.append(repl)
            last = end
        out.append(label[last:])
        return "".join(out)

    def scan_text(self, text: str, where: str, rules: Sequence[Rule], scope: str = REPO,
                  identity: bool = False, extra: Sequence[str] = ()) -> int:
        found = 0
        for rule, match, _variant in self._hits(text, rules, scope, extra):
            key = (where, rule.rule_id)
            if key in self._seen:
                continue  # one finding per rule per place is enough
            self._seen.add(key)
            self.findings.append(Finding(where, rule, mask(match.group(0)), identity))
            found += 1
        return found

    def scan_lines(self, text: str, where_prefix: str, rules: Sequence[Rule], scope: str = REPO) -> None:
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                self.scan_text(line, f"{where_prefix}:{number}", rules, scope)

    def scan_name(self, name: str, label: str, scope: str = REPO) -> str:
        """Scan a path or name; return the masked label to use for everything found under it."""
        rules = self.rules_for(scope, name)
        safe = self.safe_label(label)
        self.scan_text(name, f"{safe} (file name)", rules, scope)
        if Path(name).name.lower() == "privacy-private.json":
            rule = next(r for r in GENERIC_RULES if r.rule_id == "private-patterns-file")
            self.findings.append(Finding(f"{safe} (file name)", rule, mask(Path(name).name)))
        return safe

    def _lfs_content(self, data: bytes, label: str) -> Optional[bytes]:
        if not data.startswith(LFS_HEADER):
            return None
        found = re.search(rb"oid sha256:([0-9a-f]{64})", data)
        if not found:
            raise Refused(f"{label} is a Git LFS pointer that could not be read")
        oid = found.group(1).decode("ascii")
        stored = (self.lfs_dir / oid[:2] / oid[2:4] / oid) if self.lfs_dir is not None else None
        if stored is None or not stored.is_file():
            raise Refused(f"{label} is a Git LFS file whose content is not in this clone; it cannot be checked")
        return stored.read_bytes()

    def scan_content(self, data: bytes, label: str, scope: str, path: str, depth: int = 0,
                     is_code: bool = False) -> None:
        """Scan one file's bytes, and the files inside it (archives, compressed data, LFS, PyInstaller)."""
        if len(data) > MAX_FILE_BYTES:
            raise Refused(f"{label} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB; check it by hand")
        lfs = self._lfs_content(data, label)
        if lfs is not None:
            self.scan_content(lfs, f"{label} (LFS content)", scope, path, depth, is_code)
        rules = self.rules_for(scope, path)
        text, is_text = decode_blob(data)
        if is_text:
            self.scan_lines(text, label, rules, scope)
        else:
            code = is_code or path.endswith(".pyc")
            chunk = 1 << 20  # no line numbers in binary data; chunks keep memory bounded
            for begin in range(0, len(data), chunk):
                piece = data[max(0, begin - 256):begin + chunk]
                extra = [binary_strings(piece)] + ([marshal_strings(piece)] if code else [])
                self.scan_text(piece.decode("latin-1"), f"{label} (binary, near byte {begin})", rules, scope,
                               extra=extra)
        pieces = inner_files(data, label)
        if pieces is None:
            return
        if depth >= MAX_NESTING:
            raise Refused(f"{label} nests archives more than {MAX_NESTING} deep; check it by hand")
        for name, inner, inner_code in pieces:
            inner_label = self.scan_name(name, f"{label}!{name}", scope)
            self.scan_content(inner, inner_label, scope, f"{path}!{name}", depth + 1, inner_code)


# --------------------------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------------------------

def _git_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["GIT_NO_REPLACE_OBJECTS"] = "1"  # read the objects a push really sends, never local replacements
    env.pop("GIT_GRAFT_FILE", None)
    return env


def git(args: Sequence[str], cwd: Path, *, stdin: Optional[bytes] = None, check: bool = True,
        timeout: int = GIT_TIMEOUT) -> bytes:
    try:
        proc = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(cwd), input=stdin,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_git_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Refused(f"git {args[0]} took longer than {timeout} seconds") from None
    if check and proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Refused(f"git {args[0]} failed (exit {proc.returncode})" + (f": {message[-1][:200]}" if message else ""))
    return proc.stdout


def repo_root(start: Path) -> Path:
    return Path(git(["rev-parse", "--show-toplevel"], start).decode("utf-8").strip())


def lfs_dir_for(root: Path) -> Path:
    common = Path(git(["rev-parse", "--git-common-dir"], root).decode("utf-8").strip())
    return (common if common.is_absolute() else root / common) / "lfs" / "objects"


def is_zero(oid: str) -> bool:
    return bool(oid) and set(oid) == {"0"}


OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ObjectReader:
    """One ``git cat-file --batch`` process: read any object by id, size-delimited (no text parsing)."""

    def __init__(self, root: Path):
        self.proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=str(root), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_git_env())

    def read(self, oid: str) -> Tuple[Optional[str], bytes]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(oid.encode("ascii") + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().decode("ascii", "replace").split()
        if len(header) != 3:
            return None, b""
        size = int(header[2])
        if size > MAX_FILE_BYTES:
            self.close()
            raise Refused(f"object {oid[:12]} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB; check it by hand")
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)
        return header[1], data

    def present(self, oid: str) -> bool:
        kind, _ = self.read(oid)
        return kind is not None

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()  # type: ignore[union-attr]
            self.proc.wait()


def tree_entries(data: bytes, hash_len: int) -> Iterator[Tuple[str, str, str]]:
    """(mode, name, oid) for each entry of a raw tree object."""
    i = 0
    while i < len(data):
        space = data.index(b" ", i)
        nul = data.index(b"\x00", space)
        mode = data[i:space].decode("ascii")
        name = data[space + 1:nul].decode("utf-8", "replace")
        oid = data[nul + 1:nul + 1 + hash_len].hex()
        yield mode, name, oid
        i = nul + 1 + hash_len


OBJECT_HEADER = re.compile(r"^(?:tree|parent|object) (?:[0-9a-f]{40}|[0-9a-f]{64})$")


def scan_raw_object_text(scanner: Scanner, text: str, label: str) -> None:
    """A commit or tag object in full: every header (identities included) and the message."""
    rules = scanner.rules_for(REPO)
    in_header = True
    for number, line in enumerate(text.split("\n"), 1):
        if in_header and not line:
            in_header = False
            continue
        if in_header and OBJECT_HEADER.match(line):
            continue  # object ids only
        identity = in_header and line.startswith(IDENTITY_PREFIXES)
        part = line.split(" ", 1)[0] if identity else ("header" if in_header else "message")
        if line.strip():
            scanner.scan_text(line, f"{label} {part}:{number}" if not identity else f"{label} {part}",
                              rules, REPO, identity)


def scan_objects(scanner: Scanner, root: Path, positives: Sequence[str], negatives: Sequence[str],
                 everything: bool = False) -> int:
    """Every object reachable from ``positives`` (or from every ref) and not from ``negatives``.

    Commits and tags are read in full; trees by entry name (so empty files and submodule entries
    count); blobs in full, including what is inside archives. Returns the number of commits.
    """
    if not positives and not everything:
        return 0
    lines = list(positives) + ["^" + oid for oid in negatives]
    args = ["rev-list", "--objects"] + (["--all"] if everything else []) + ["--stdin"]
    listing = git(args, root, stdin=("\n".join(lines) + "\n").encode("ascii"))
    hash_len = 32 if git(["rev-parse", "--show-object-format"], root).strip() == b"sha256" else 20
    reader = ObjectReader(root)
    commits = 0
    try:
        for raw in listing.split(b"\n"):
            if not raw:
                continue
            oid_bytes, _, path_bytes = raw.partition(b" ")
            oid, path = oid_bytes.decode("ascii", "replace"), path_bytes.decode("utf-8", "replace")
            if not OID.match(oid):
                raise Refused("git rev-list printed something that is not an object id")
            kind, data = reader.read(oid)
            if kind == "commit":
                commits += 1
                scan_raw_object_text(scanner, data.decode("utf-8", "replace"), f"commit {oid[:9]}")
            elif kind == "tag":
                scan_raw_object_text(scanner, data.decode("utf-8", "replace"), f"tag {oid[:9]}")
            elif kind == "tree":
                for _mode, name, _entry in tree_entries(data, hash_len):
                    full = f"{path}/{name}" if path else name
                    scanner.scan_name(full, full)
            elif kind == "blob":
                label = (scanner.safe_label(path) if path else "blob") + f"@{oid[:7]}"
                scanner.scan_content(data, label, REPO, path or "")
            else:
                raise Refused(f"object {oid[:12]} is missing; the clone is incomplete")
    finally:
        reader.close()
    return commits


def destination_oids(root: Path, target: str) -> List[str]:
    """Object ids the destination advertises right now that this clone also has."""
    if not target or target.startswith("-"):
        raise Refused("the pre-push hook needs the destination's name or address")
    out = git(["ls-remote", target], root, timeout=300).decode("utf-8", "replace")
    advertised = sorted({line.split()[0] for line in out.splitlines() if line.strip() and OID.match(line.split()[0])})
    if not advertised:
        return []
    reader = ObjectReader(root)
    try:
        return [oid for oid in advertised if reader.present(oid)]
    finally:
        reader.close()


def commit_present(root: Path, oid: str) -> bool:
    proc = subprocess.run(["git", "cat-file", "-e", oid + "^{commit}"], cwd=str(root), env=_git_env(),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


# --------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------

def cmd_tree(scanner: Scanner, root: Path, include_untracked: bool) -> None:
    names = git(["ls-files", "-z"], root).split(b"\x00")
    if include_untracked:
        names += git(["ls-files", "-z", "--others", "--exclude-standard"], root).split(b"\x00")
    for raw in names:
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        path = root / rel
        label = scanner.scan_name(rel, rel)
        if path.is_symlink():
            scanner.scan_lines(os.readlink(path), f"{label} (link target)", scanner.rules_for(REPO, rel))
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            raise Refused(f"{label} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB; check it by hand")
        scanner.scan_content(path.read_bytes(), label, REPO, rel)


def cmd_staged(scanner: Scanner, root: Path) -> None:
    """Every staged file version in full (the index blobs), every staged path, and the identity the
    commit will carry."""
    for kind in ("author", "committer"):
        ident = git(["var", f"GIT_{kind.upper()}_IDENT"], root, check=False).decode("utf-8", "replace").strip()
        if ident:
            scanner.scan_text(f"{kind} {ident}", f"the commit's {kind}", scanner.rules_for(REPO), REPO, True)
    raw = git(["diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "--ignore-submodules=none"], root)
    fields = raw.split(b"\x00")
    reader = ObjectReader(root)
    try:
        i = 0
        while i < len(fields) - 1:
            meta = fields[i].decode("ascii", "replace")
            if not meta.startswith(":"):
                i += 1
                continue
            path = fields[i + 1].decode("utf-8", "replace")
            i += 2
            _old_mode, new_mode, _old, new, status = meta[1:].split()[:5]
            if status.startswith("D"):
                continue
            label = scanner.scan_name(path, path)
            if new_mode == "160000" or is_zero(new):
                continue
            kind, data = reader.read(new)
            if kind == "blob":
                scanner.scan_content(data, label, REPO, path)
    finally:
        reader.close()


def cmd_message(scanner: Scanner, message_file: str) -> None:
    """Every line git may keep, comment lines included (``git commit -m`` keeps them), up to the
    scissors line that git always cuts at."""
    text = Path(message_file).read_text(encoding="utf-8", errors="replace")
    kept = text.split(SCISSORS, 1)[0]
    scanner.scan_lines(kept, "commit message", scanner.rules_for(REPO))


def parse_push_line(line: str) -> Optional[Tuple[str, str, str, str]]:
    """git's pre-push line: '<local ref> <local oid> <remote ref> <remote oid>'. Only the first field
    can hold spaces (a source such as HEAD^{/two words}), so it is split from the right."""
    if not line.strip():
        return None
    parts = line.rstrip("\r").rsplit(" ", 3)
    if len(parts) != 4 or not OID.match(parts[1]) or not OID.match(parts[3]):
        raise Refused("the pre-push hook received a line it cannot read; refusing rather than skipping it")
    return parts[0], parts[1], parts[2], parts[3]


def cmd_push(scanner: Scanner, root: Path, remote: str, url: str, stdin_text: str) -> int:
    positives: List[str] = []
    negatives: Set[str] = set()
    reader = ObjectReader(root)
    try:
        for line in stdin_text.split("\n"):
            parsed = parse_push_line(line)
            if parsed is None:
                continue
            local_ref, local_oid, remote_ref, remote_oid = parsed
            if is_zero(local_oid):
                continue  # a deletion sends nothing
            for ref in {local_ref, remote_ref}:
                scanner.scan_text(ref, "ref name", scanner.rules_for(REPO))
            positives.append(local_oid)
            if not is_zero(remote_oid) and reader.present(remote_oid):
                negatives.add(remote_oid)
    finally:
        reader.close()
    if not positives:
        return 0
    negatives.update(destination_oids(root, url or remote))
    return scan_objects(scanner, root, positives, sorted(negatives))


def cmd_range(scanner: Scanner, root: Path, spec: str) -> int:
    base, sep, head = spec.partition("..")
    if not sep or not head:
        raise Refused("range must look like BASE..HEAD")
    if base and not is_zero(base):
        if not commit_present(root, base):
            raise Refused(f"range start {base[:12]} is not in this clone (fetch the full history)")
        return scan_objects(scanner, root, [head], [base])
    return scan_objects(scanner, root, [head], [])


def cmd_ci_push(scanner: Scanner, root: Path, before: str, after: str, ref: str, default_branch: str) -> int:
    """A push GitHub reports. When GitHub's old tip is here: before..after. Otherwise (a new branch or
    tag, or a force-push): everything the pushed ref reaches that the default branch does not, or the
    whole history when this is the default branch itself. Other new refs are never subtracted, because
    one push can create several refs that share the same new commits."""
    scanner.scan_text(ref, "ref name", scanner.rules_for(REPO))
    target = after
    if ref.startswith("refs/tags/"):
        target = git(["rev-parse", "--verify", ref], root, check=False).decode().strip() or after
    if before and not is_zero(before) and commit_present(root, before):
        return scan_objects(scanner, root, [target], [before])
    negatives = []
    if default_branch and ref != f"refs/heads/{default_branch}":
        tip = git(["rev-parse", "--verify", "-q", f"refs/remotes/origin/{default_branch}"], root, check=False)
        if tip.strip():
            negatives.append(tip.decode().strip())
    return scan_objects(scanner, root, [target], negatives)


def cmd_paths(scanner: Scanner, targets: Sequence[str], scope: str) -> int:
    count = 0
    for target in targets:
        base = Path(target)
        if not base.exists():
            raise Refused(f"path not found: {scanner.safe_label(base.name)}")
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for path in files:
            rel = path.name if path == base else path.relative_to(base).as_posix()
            label = scanner.scan_name(rel, rel, scope)
            scanner.scan_content(path.read_bytes(), label, scope, rel)
            count += 1
    return count


def cmd_publish(scanner: Scanner, root: Path, package_paths: Sequence[str]) -> Tuple[int, int]:
    """Everything committed in this repository (every object any ref reaches: branches, tags, notes,
    stashes) plus any built package. Refuses while tracked files differ from what is committed, so
    what is checked is what would be published."""
    dirty = git(["status", "--porcelain", "--untracked-files=no"], root).strip()
    if dirty:
        raise Refused("tracked files differ from the last commit; commit or discard the changes first, so "
                      "the check reads what would be published")
    commits = scan_objects(scanner, root, [], [], everything=True)
    count = cmd_paths(scanner, package_paths, PACKAGE) if package_paths else 0
    return commits, count


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--private", action="store_true",
                        help="also use the private patterns, and refuse (exit 2) if they are missing")
    parser.add_argument("--config", default="", help="the private patterns file (installed hooks pass this)")
    parser.add_argument("--repo", default=".", help="repository folder (default: the current one)")
    parser.add_argument("--identity-findings", choices=("fail", "warn"), default="fail",
                        help="warn: report an e-mail address in a commit author/committer/tagger line as a "
                             "warning instead of failing")
    sub = parser.add_subparsers(dest="command")
    tree = sub.add_parser("tree", help="scan every tracked file")
    tree.add_argument("--include-untracked", action="store_true", help="also files git does not ignore")
    sub.add_parser("staged", help="scan every staged file and the commit's identity (pre-commit)")
    message = sub.add_parser("message", help="scan a commit message file (commit-msg)")
    message.add_argument("file")
    push = sub.add_parser("push", help="scan every object a push sends (pre-push; reads git's lines on stdin)")
    push.add_argument("remote", nargs="?", default="", help="the remote name git passes the hook")
    push.add_argument("url", nargs="?", default="", help="the destination address git passes the hook")
    rng = sub.add_parser("range", help="scan every object in BASE..HEAD")
    rng.add_argument("spec")
    ci = sub.add_parser("ci-push", help="scan what a push to GitHub added (GitHub Actions)")
    ci.add_argument("--before", default="")
    ci.add_argument("--after", required=True)
    ci.add_argument("--ref", required=True)
    sub.add_parser("history", help="scan every object reachable from any ref")
    paths = sub.add_parser("paths", help="scan files, folders, archives and PyInstaller executables byte by byte")
    paths.add_argument("targets", nargs="+")
    paths.add_argument("--scope", choices=(REPO, PACKAGE), default=PACKAGE,
                       help="package (default) skips rules that third-party binaries legitimately trip")
    publish = sub.add_parser("publish", help="pre-publish: everything committed plus --path items, private required")
    publish.add_argument("--path", action="append", default=[], help="a built package folder or ZIP")
    sub.add_parser("rules", help="list the rule ids (never prints private patterns)")
    return parser


def main(argv: Optional[Sequence[str]] = None, stdin_text: Optional[str] = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "tree"
    use_private = args.private or command == "publish"
    try:
        private = None
        if use_private:
            path, where = resolve_config_path(args.config)
            private = load_private_config(path, where)
        root: Optional[Path] = None
        if command not in ("paths", "message", "rules"):
            root = repo_root(Path(args.repo))
        scanner = Scanner(private, load_allowlist(), lfs_dir_for(root) if root is not None else None)
        if command == "rules":
            listed = set()
            for scope in (REPO, PACKAGE):
                for rule in scanner.rules_for(scope):
                    if (rule.rule_id, rule.scopes) not in listed:
                        listed.add((rule.rule_id, rule.scopes))
                        print(f"{rule.rule_id}  [{', '.join(rule.scopes)}]  {rule.description}")
            return EXIT_CLEAN
        what = ""
        if command == "tree":
            cmd_tree(scanner, root, args.include_untracked)  # type: ignore[arg-type]
            what = "tracked and untracked files" if args.include_untracked else "tracked files"
        elif command == "staged":
            cmd_staged(scanner, root)  # type: ignore[arg-type]
            what = "staged files"
        elif command == "message":
            cmd_message(scanner, args.file)
            what = "the commit message"
        elif command == "push":
            text = stdin_text if stdin_text is not None else sys.stdin.read()
            count = cmd_push(scanner, root, args.remote, args.url, text)  # type: ignore[arg-type]
            what = f"everything this push sends ({count} commit(s))"
        elif command == "range":
            what = f"everything in the range ({cmd_range(scanner, root, args.spec)} commit(s))"  # type: ignore
        elif command == "ci-push":
            count = cmd_ci_push(scanner, root, args.before, args.after, args.ref,  # type: ignore[arg-type]
                                os.environ.get(DEFAULT_BRANCH_ENV, ""))
            what = f"everything the push added ({count} commit(s))"
        elif command == "history":
            what = f"everything any ref reaches ({scan_objects(scanner, root, [], [], everything=True)} commit(s))"  # type: ignore
        elif command == "paths":
            what = f"{cmd_paths(scanner, args.targets, args.scope)} file(s)"
        elif command == "publish":
            commits, count = cmd_publish(scanner, root, args.path)  # type: ignore[arg-type]
            what = f"everything committed ({commits} commit(s))" + (f" and {count} packaged file(s)" if args.path else "")
    except Refused as exc:
        print(f"privacy check REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    layer = "generic + private rules" if use_private else "generic rules"
    warn_only = args.identity_findings == "warn"

    def is_warning(finding: Finding) -> bool:
        return warn_only and finding.identity and finding.rule.rule_id == "email-address"

    failing = [f for f in scanner.findings if not is_warning(f)]
    for finding in (f for f in scanner.findings if is_warning(f)):
        prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "warning:"
        print(f"{prefix} {finding.where}: e-mail address {finding.excerpt} in a commit identity line; set "
              "user.email to your GitHub noreply address for future commits", file=sys.stderr)
    if failing:
        print(f"privacy check FAILED: {len(failing)} finding(s) in {what} ({layer}):", file=sys.stderr)
        for finding in failing:
            print(finding.render(), file=sys.stderr)
        print("Remove or replace each one. A finding in an earlier commit stays in history: rewrite that "
              "commit (for example with an interactive rebase) before pushing.", file=sys.stderr)
        return EXIT_FINDINGS
    print(f"privacy check passed: {what} ({layer}).")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
