"""The privacy check and its hooks (tools/privacy).

Every example here is synthetic and built at run time, so this file never trips the check it tests,
and the tests need no private files: they pass on any computer and in GitHub Actions. Git runs with
a throw-away global configuration, so a developer's own git settings and hooks never take part.
Standard library only, so ``python -m unittest tests.test_privacy_check`` works without pytest.
"""

from __future__ import annotations

import contextlib
import io
import json
import marshal
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile
import zlib

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "privacy"))

import install_hooks  # noqa: E402
import privacy_check  # noqa: E402

BS = "\\"
# Synthetic examples, assembled here so no complete example appears in the source text.
SYNTHETIC_GENERIC = {
    "user-profile-path": "log at C:" + BS + "Users" + BS + "Zedwick" + BS + "notes.txt",
    "checkout-path": "built in E:" + BS + "work" + BS + "Git" + "Hub" + BS + "tool" + BS + "x.py",
    "cloud-sync-path": "saved to C:" + BS + "Box" + BS + "One" + "Drive" + BS + "plans.docx",
    "default-computer-name": "host " + "DESKTOP" + "-" + "Q7ZK2M4",
    "network-share-host": "copy to " + BS + BS + "quill" + "pad" + BS + "drop" + BS + "a.txt",
    "network-share-url": "open smb" + "://quill" + "pad/drop",
    "email-address": "write to zed" + "@" + "corp-mail.net",
    "ai-chat-link": "see https://chat" + "gpt.com/c/" + "a1b2c3",
    "private-patterns-file": "schema " + "media-manglers-" + "private-privacy/" + "1",
    "secret-github-token": "token gh" + "p_" + "A1" * 18,
    "secret-aws-access-key": "key AK" + "IA" + "Z" * 16,
    "secret-private-key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
    "secret-anthropic-key": "sk-" + "ant-" + "api03-" + "x" * 24,
}
MORE_GENERIC = [  # further shapes the review found missing at first
    ("user-profile-path", "/c/" + "Users/" + "Zedwick/notes.txt"),
    ("user-profile-path", "/mnt/c/" + "Users/" + "Zedwick/notes.txt"),
    ("user-profile-path", "C:" + BS + "msys64" + BS + "home" + BS + "zedwick" + BS + "x"),
    ("user-profile-path", "C:" + BS + "Users" + BS + "Zed Quill" + "feather" + BS + "Documents"),
    ("checkout-path", "/c/work/Git" + "Hub/tool/x.py"),
    ("default-computer-name", "ssh " + "desktop" + "-" + "q7zk2m4"),
    ("network-share-host", "path:" + BS + BS + "quill" + "pad" + BS + "drop"),
    ("network-share-host", BS + BS + "ZEDWICK" + "-PC" + BS + "Users"),
    ("ai-chat-link", "https://chat" + "gpt.com/codex/" + "tasks/task_e_0123abcd"),
    ("ai-chat-link", "https://claude" + ".site/artifacts/abc"),
    ("ai-chat-link", "https://github" + ".com/copilot/c/abc"),
    ("secret-gitlab-token", "glpat" + "-" + "a1B2" * 6),
    ("secret-azure-sas", "https://x.blob.core.windows.net/c?sv=1&" + "sig=" + "a" * 40),
    # the second review round
    ("user-profile-path", "/cyg" + "drive/c/" + "Users/" + "Zedwick/notes.txt"),
    ("user-profile-path", "PATH=/usr/bin:" + "/home/" + "zedwick/.local/bin"),
    ("user-profile-path", BS + BS + "wsl$" + BS + "Ubuntu" + BS + "home" + BS + "zedwick" + BS + "x"),
    ("checkout-path", "D:" + BS + "My Code" + BS + "Git" + "Hub" + BS + "x.py"),
    ("cloud-sync-path", "--out=C:" + BS + "Box" + BS + "One" + "Drive" + BS + "x"),
    ("default-computer-name", "log_" + "DESKTOP" + "-" + "Q7ZK2M4.txt"),
    ("network-share-url", "file:" + "////quill" + "pad/drop/x"),
    ("network-share-url", "smb" + "://zed@quill" + "pad/drop"),
    ("ai-chat-link", "https://chat.openai" + ".com/g/g-abc/c/123"),
    ("ai-chat-link", "https://gemini.google" + ".com/u/1/app/abc123"),
    ("secret-slack-token", "xapp" + "-1-" + "A1B2C3D4E5F6"),
]
FINE = [
    "C:" + BS + "Users" + BS + "Example" + BS + "AppData",
    "C:" + BS + "Users" + BS + "Example and then more words",
    "C:" + BS + "Users" + BS + "All Users" + BS + "Microsoft",
    "/home/" + "you/project",
    "/home/" + "runner/work/app/app/src",
    "you" + "@" + "example.com",
    "logo" + "@" + "2x.png",
    "12345+someone" + "@" + "users.noreply.github.com",
    "Co-Authored-By: a bot <no" + "reply@" + "vendor.dev>",
    BS + BS + "server" + BS + "share" + BS + "file.txt",
    '"' + BS + BS + "microsoft" + BS + BS + "windowsapps" + BS + BS + '"',
    "https://claude.com/claude-code",
    "https://github.com/" + "dropbox/dropbox-sdk-python",
    "src/integrations/" + "dropbox/client.py",
    "C:" + BS + "Program Files" + BS + "Tool" + BS + "tool.exe",
    "colour #111 and issue 152",
    "DESKTOP" + "-" + "version is not a computer",
    "DESKTOP" + "-" + "SESSION is a variable",
    "Profiles live in C:" + BS + "Users" + BS + " on Windows.",
    "/home/" + "node/app",
    "sprite" + "@" + "2x.avif",
    "https://claude.ai" + "/code",
    "/usr/lib/python3/site-packages/" + "dropbox/client.py",
    "C:" + BS + "ProgramData" + BS + "Git" + "Hub" + BS + "x",
    "key AK" + "IA" + "IOSFODNN7" + "EXAMPLE",
]
PRIVATE_TOKEN = "Quux" + "bert"  # a made-up maintainer name for the private-layer tests
PRIVATE_CONFIG = {
    "schema": privacy_check.CONFIG_SCHEMA,
    "rules": [
        {"id": "maintainer-name", "pattern": "quux" + "bert", "flags": "i", "why": "synthetic name"},
        {"id": "package-only", "pattern": "OLD" + "OWNER", "scopes": ["package"], "why": "synthetic"},
    ],
    "allow": [{"pattern": "quux" + "bert-the-library", "flags": "i", "why": "a synthetic public name"}],
}


def _rmtree(path: str) -> None:
    def onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=onerror)


def _pyinstaller_exe(entries) -> bytes:
    """A minimal PyInstaller-style executable: a CArchive (and a PYZ) after some leading bytes."""
    body, toc = b"", b""
    for name, payload, kind in entries:
        packed = zlib.compress(payload)
        encoded = name.encode("utf-8") + b"\x00"
        encoded += b"\x00" * ((16 - (18 + len(encoded)) % 16) % 16)
        toc += struct.pack("!IIIIBc", 18 + len(encoded), len(body), len(packed), len(payload), 1, kind) + encoded
        body += packed
    cookie = "!8sIIii64s"
    package = body + toc
    trailer = struct.pack(cookie, privacy_check.PYI_MAGIC, len(package) + struct.calcsize(cookie), len(body),
                          len(toc), 312, b"python312.dll")
    return b"MZ" + b"\x00" * 200 + package + trailer


def _pyz(modules) -> bytes:
    data, index = b"", {}
    for name, payload in modules:
        packed = zlib.compress(payload)
        index[name] = (0, 12 + len(data), len(packed))
        data += packed
    toc_offset = 12 + len(data)
    return b"PYZ\x00" + b"\x00" * 4 + struct.pack("!i", toc_offset) + data + marshal.dumps(index)


class _Sandbox(unittest.TestCase):
    """A temporary folder, a git configuration of its own, and a private-patterns path inside it."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="privacy-"))
        self.addCleanup(_rmtree, str(self.tmp))
        (self.tmp / ".gitignore").write_text("*\n", encoding="utf-8")  # never committable from a parent repo
        gitconfig = self.tmp / "gitconfig"
        gitconfig.write_text(
            "[user]\n\tname = Synthetic Tester\n\temail = tester@example.com\n"
            "[init]\n\tdefaultBranch = main\n[core]\n\tautocrlf = false\n[commit]\n\tgpgsign = false\n"
            "[tag]\n\tgpgsign = false\n[advice]\n\tnestedTag = false\n",
            encoding="utf-8")
        self.config_path = self.tmp / "private" / "privacy-private.json"
        env = {"GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
               privacy_check.CONFIG_ENV: str(self.config_path)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_private_config(self, data=None) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(PRIVATE_CONFIG if data is None else data), encoding="utf-8")

    def git(self, cwd: Path, *args: str, check: bool = True, stdin: str = "") -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", *args], cwd=str(cwd), input=stdin.encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace')}")
        return proc

    def sha(self, repo: Path, rev: str = "HEAD") -> str:
        return self.git(repo, "rev-parse", rev).stdout.decode().strip()

    def new_repo(self, name: str = "repo") -> Path:
        repo = self.tmp / name
        repo.mkdir()
        self.git(repo, "init", "-q")
        return repo

    def commit(self, repo: Path, rel: str, content, message: str = "change", *extra: str) -> str:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        self.git(repo, "add", "-A")
        self.git(repo, *extra, "commit", "-q", "-m", message)
        return self.sha(repo)

    def run_check(self, *argv: str, stdin_text=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = privacy_check.main(list(argv), stdin_text=stdin_text)
        return code, out.getvalue() + err.getvalue()

    def remote_and_clone(self):
        bare = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(bare))
        work = self.tmp / "work"
        self.git(self.tmp, "clone", "-q", str(bare), str(work))
        self.commit(work, "README.md", "first\n", "first")
        self.git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.git(work, "fetch", "-q", "origin")
        return bare, work

    def push_check(self, work: Path, head: str, remote: str = "origin", ref: str = "refs/heads/topic",
                   remote_sha: str = "0" * 40, private: bool = True):
        argv = (["--private"] if private else []) + ["--repo", str(work), "push", remote, remote]
        return self.run_check(*argv, stdin_text=f"{ref} {head} {ref} {remote_sha}\n")


class GenericRuleTests(unittest.TestCase):
    def _rule_ids(self, text: str, scope: str = privacy_check.REPO):
        scanner = privacy_check.Scanner(None, [])
        scanner.scan_text(text, "example", scanner.rules_for(scope), scope)
        return {f.rule.rule_id for f in scanner.findings}

    def test_each_generic_rule_finds_its_synthetic_example(self) -> None:
        for rule_id, text in SYNTHETIC_GENERIC.items():
            with self.subTest(rule=rule_id):
                self.assertIn(rule_id, self._rule_ids(text))
        for rule_id, text in MORE_GENERIC:
            with self.subTest(rule=rule_id, text=text):
                self.assertIn(rule_id, self._rule_ids(text))

    def test_every_non_secret_rule_has_an_example_here(self) -> None:
        tested = set(SYNTHETIC_GENERIC) | {r for r, _ in MORE_GENERIC}
        untested = {r.rule_id for r in privacy_check.GENERIC_RULES} - tested
        self.assertTrue(all(r.startswith("secret-") for r in untested), untested)

    def test_placeholders_and_ordinary_text_are_not_findings(self) -> None:
        for text in FINE:
            with self.subTest(text=text):
                self.assertEqual(self._rule_ids(text), set())

    def test_escaped_share_path_counts_the_same_as_a_written_one(self) -> None:
        escaped = '"' + BS * 4 + "quillpad" + BS * 2 + "drop" + '"'
        self.assertIn("network-share-host", self._rule_ids(escaped))

    def test_package_scope(self) -> None:
        package_rules = {r.rule_id for r in privacy_check.Scanner(None, []).rules_for(privacy_check.PACKAGE)}
        self.assertNotIn("email-address", package_rules)
        self.assertIn("user-profile-path", package_rules)
        self.assertIn("secret-github-token", package_rules)
        # Qt's own build account is third-party, and a bare key header is a TLS library constant.
        qt_path = "C:" + BS + "Users" + BS + "qt" + BS + "work" + BS + "qt"
        self.assertEqual(self._rule_ids(qt_path, privacy_check.PACKAGE), set())
        self.assertIn("user-profile-path", self._rule_ids(qt_path))
        header = "-----BEGIN " + "RSA PRIVATE" + " KEY-----\x00-----BEGIN DSA"
        self.assertEqual(self._rule_ids(header, privacy_check.PACKAGE), set())
        keyed = "-----BEGIN " + "PRIVATE" + " KEY-----\\n" + "MIIE" + "a" * 60
        self.assertIn("secret-private-key", self._rule_ids(keyed, privacy_check.PACKAGE))

    def test_masking_never_repeats_the_whole_match(self) -> None:
        secret = SYNTHETIC_GENERIC["secret-github-token"].split()[-1]
        masked = privacy_check.mask(secret)
        self.assertNotIn(secret, masked)
        self.assertIn(f"{len(secret)} chars", masked)

    def test_a_long_run_of_backslashes_scans_quickly(self) -> None:
        line = "see C:" + BS * 200 + "x users github"
        started = time.perf_counter()
        self._rule_ids(line)
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_allowlist_globs_are_exact_and_pinned(self) -> None:
        self.assertTrue(privacy_check.glob_match("licenses/zlib.txt", "licenses/*"))
        self.assertFalse(privacy_check.glob_match("licenses/deep/x.py", "licenses/*"))
        self.assertFalse(privacy_check.glob_match("LICENSES/zlib.txt", "licenses/*"))
        entries = privacy_check.load_allowlist()
        self.assertEqual(entries, [
            ("licenses/*", ("email-address",)),
            ("THIRD_PARTY_NOTICES.txt", ("email-address",)),
            ("tools/privacy/privacy_check.py", ("private-patterns-file",)),
            ("tools/privacy/README.md", ("private-patterns-file",)),
        ])


class PrivateConfigTests(_Sandbox):
    def test_private_check_refuses_when_the_patterns_file_is_missing(self) -> None:
        repo = self.new_repo()
        self.commit(repo, "a.txt", "hello\n")
        code, output = self.run_check("--private", "--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_REFUSED)
        self.assertIn("fails closed", output)

    def test_private_check_refuses_an_invalid_or_degenerate_patterns_file(self) -> None:
        repo = self.new_repo()
        self.commit(repo, "a.txt", f"{PRIVATE_TOKEN}\n")
        schema = privacy_check.CONFIG_SCHEMA
        good_rule = {"id": "x", "pattern": "quux" + "bert"}
        cases = {
            "not json": "not json",
            "wrong schema": {"schema": "else", "rules": [good_rule]},
            "no rules": {"schema": schema, "rules": []},
            "bad regex": {"schema": schema, "rules": [{"id": "x", "pattern": "("}]},
            "bad scope": {"schema": schema, "rules": [{**good_rule, "scopes": ["elsewhere"]}]},
            "scope string": {"schema": schema, "rules": [{**good_rule, "scopes": "repo"}]},
            "null pattern": {"schema": schema, "rules": [{"id": "x", "pattern": None}]},
            "list pattern": {"schema": schema, "rules": [{"id": "x", "pattern": ["q"]}]},
            "empty pattern": {"schema": schema, "rules": [{"id": "x", "pattern": ""}]},
            "matches anything": {"schema": schema, "rules": [{"id": "x", "pattern": ".*"}]},
            "null id": {"schema": schema, "rules": [{"id": None, "pattern": "quux"}]},
            "allow everything": {"schema": schema, "rules": [good_rule], "allow": [{"pattern": ".+"}]},
            "package rules only": {"schema": schema, "rules": [{**good_rule, "scopes": ["package"]}]},
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        for name, content in cases.items():
            with self.subTest(case=name):
                text = content if isinstance(content, str) else json.dumps(content)
                self.config_path.write_text(text, encoding="utf-8")
                code, _ = self.run_check("--private", "--repo", str(repo), "tree")
                self.assertEqual(code, privacy_check.EXIT_REFUSED)

    def test_patterns_file_that_could_be_committed_is_refused(self) -> None:
        repo = self.new_repo()
        self.commit(repo, "a.txt", "hello\n")
        inside = repo / "config" / "privacy-private.json"
        inside.parent.mkdir()
        inside.write_text(json.dumps(PRIVATE_CONFIG), encoding="utf-8")
        with mock.patch.dict(os.environ, {privacy_check.CONFIG_ENV: str(inside)}):
            code, output = self.run_check("--private", "--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_REFUSED)
        self.assertIn("could be committed", output)

    def test_private_rule_finds_its_token_without_printing_it(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        self.commit(repo, "notes.md", f"Written by {PRIVATE_TOKEN} on a quiet day.\n")
        self.commit(repo, f"{PRIVATE_TOKEN}-notes.md", "AK" + "IA" + "Z" * 16 + "\n")
        code, output = self.run_check("--private", "--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("private:maintainer-name", output)
        self.assertIn("secret-aws-access-key", output)
        self.assertNotIn(PRIVATE_TOKEN.lower(), output.lower())

    def test_without_private_the_private_token_is_not_checked(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        self.commit(repo, "notes.md", f"Written by {PRIVATE_TOKEN}.\n")
        code, _ = self.run_check("--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_CLEAN)

    def test_allow_pattern_package_scope_and_pyinstaller_archives(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        self.commit(repo, "notes.md", f"Uses {PRIVATE_TOKEN}-the-library and OLD" + "OWNER in a link.\n")
        code, output = self.run_check("--private", "--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_CLEAN, output)
        package = self.tmp / "package"
        package.mkdir()
        (package / "about.txt").write_text("built by OLD" + "OWNER\n", encoding="utf-8")
        code, output = self.run_check("--private", "paths", str(package))
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("private:package-only", output)
        (package / "about.txt").unlink()
        exe = _pyinstaller_exe([
            ("struct", b"plain module bytes", b"m"),
            ("PYZ-00.pyz", _pyz([("app.settings", b"owner = 'OLD" + b"OWNER'")]), b"z"),
        ])
        self.assertNotIn(b"OWNER", exe)  # compressed: invisible to a plain byte search
        (package / "App.exe").write_bytes(exe)
        code, output = self.run_check("--private", "paths", str(package))
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.assertIn("App.exe!PYZ-00.pyz!app.settings", output)


class GitScanTests(_Sandbox):
    def test_tree_passes_clean_files_and_fails_a_secret(self) -> None:
        repo = self.new_repo()
        self.commit(repo, "README.md", "Write to you" + "@" + "example.com.\n")
        self.assertEqual(self.run_check("--repo", str(repo), "tree")[0], privacy_check.EXIT_CLEAN)
        self.commit(repo, "config.txt", SYNTHETIC_GENERIC["secret-aws-access-key"] + "\n")
        code, output = self.run_check("--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("config.txt:1: secret-aws-access-key", output)

    def test_tree_reads_zip_members_and_reports_each_finding_once(self) -> None:
        repo = self.new_repo()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("inner/readme.txt", SYNTHETIC_GENERIC["secret-github-token"])
        self.commit(repo, "fixture.zip", buffer.getvalue())
        self.commit(repo, "blob.bin", b"\x00\x01 " + SYNTHETIC_GENERIC["secret-aws-access-key"].encode() + b"\n")
        code, output = self.run_check("--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("fixture.zip!inner/readme.txt", output)
        self.assertEqual(output.count("secret-aws-access-key"), 1)

    def test_allowlisted_path_keeps_license_contact_addresses(self) -> None:
        repo = self.new_repo()
        self.commit(repo, "licenses/zlib.txt", "Contact: zed" + "@" + "corp-mail.net\n")
        self.assertEqual(self.run_check("--repo", str(repo), "tree")[0], privacy_check.EXIT_CLEAN)

    def test_staged_files_names_and_binaries(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        self.commit(repo, "a.txt", "start\n")
        self.assertEqual(self.run_check("--private", "--repo", str(repo), "staged")[0], privacy_check.EXIT_CLEAN)
        (repo / "blob.bin").write_bytes(b"\x00\x01" + f"by {PRIVATE_TOKEN}".encode("utf-16-le") + b"\x00\xff")
        self.git(repo, "add", "blob.bin")
        code, output = self.run_check("--private", "--repo", str(repo), "staged")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.assertIn("blob.bin", output)
        self.git(repo, "reset", "-q")
        empty = repo / "AREA" / f"{PRIVATE_TOKEN}-recordings" / ".gitkeep"
        empty.parent.mkdir(parents=True)
        empty.write_bytes(b"")
        self.git(repo, "add", "AREA")
        code, output = self.run_check("--private", "--repo", str(repo), "staged")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.assertIn("(file name)", output)

    def test_a_textconv_driver_cannot_hide_content(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        self.commit(repo, ".gitattributes", "*.notes diff=quiet\n")
        self.git(repo, "config", "diff.quiet.textconv", "sh -c true")
        (repo / "a.notes").write_text(f"{PRIVATE_TOKEN}\n", encoding="utf-8")
        self.git(repo, "add", "a.notes")
        code, _ = self.run_check("--private", "--repo", str(repo), "staged")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)

    def test_commit_message_file(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        message = self.tmp / "MSG"
        for text, expected in (
                (f"fix things\nthanks {PRIVATE_TOKEN}\n", privacy_check.EXIT_FINDINGS),
                (f"fix things\n# {PRIVATE_TOKEN}: git commit -m keeps comment lines\n", privacy_check.EXIT_FINDINGS),
                (f"fix things\n{privacy_check.SCISSORS}\n{PRIVATE_TOKEN} below the scissors is cut\n",
                 privacy_check.EXIT_CLEAN)):
            with self.subTest(text=text[:30]):
                message.write_text(text, encoding="utf-8")
                self.assertEqual(self.run_check("--private", "--repo", str(repo), "message", str(message))[0],
                                 expected)

    def test_staged_checks_the_commit_identity(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        (repo / "a.txt").write_text("fine\n", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        self.assertEqual(self.run_check("--private", "--repo", str(repo), "staged")[0], privacy_check.EXIT_CLEAN)
        with mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": f"{PRIVATE_TOKEN} T"}):
            code, output = self.run_check("--private", "--repo", str(repo), "staged")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("author", output)

    def test_lfs_files_are_read_from_the_local_store_or_refused(self) -> None:
        import hashlib

        self.write_private_config()
        repo = self.new_repo()
        content = f"{PRIVATE_TOKEN} diary\n".encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        pointer = (privacy_check.LFS_HEADER + f"\noid sha256:{digest}\nsize {len(content)}\n".encode("ascii"))
        (repo / "diary.notes").write_bytes(pointer)
        self.git(repo, "add", "diary.notes")
        code, output = self.run_check("--private", "--repo", str(repo), "staged")
        self.assertEqual(code, privacy_check.EXIT_REFUSED, output)
        stored = repo / ".git" / "lfs" / "objects" / digest[:2] / digest[2:4] / digest
        stored.parent.mkdir(parents=True)
        stored.write_bytes(content)
        code, output = self.run_check("--private", "--repo", str(repo), "staged")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.assertIn("LFS content", output)

    def test_archives_compressed_streams_and_compiled_code(self) -> None:
        import bz2
        import lzma

        self.write_private_config()
        token = f"{PRIVATE_TOKEN} notes".encode("utf-8") * 5
        pdf = b"%PDF-1.4\n1 0 obj << /Filter /FlateDecode >>\nstream\n" + zlib.compress(token) + b"\nendstream\n"

        def nested(depth: int) -> bytes:
            data = token
            for level in range(depth):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(f"level{level}.zip" if level else "note.txt", data)
                data = buffer.getvalue()
            return data

        host = "DESKTOP" + "-" + "Q7ZK2M4"  # a rule anchored at both ends: what a glued-on byte would hide
        compiled = marshal.dumps(compile(f"HOST = '{host}'\nX = 1\n", "m.py", "exec"))
        utf16 = b"\x00\x01" + f"{host}\x00".encode("utf-16-le") + "next".encode("utf-16-le") + b"\x00\xff"
        cases = {
            "notes.bz2": (bz2.compress(token), privacy_check.EXIT_FINDINGS),
            "notes.xz": (lzma.compress(token), privacy_check.EXIT_FINDINGS),
            "doc.pdf": (pdf, privacy_check.EXIT_FINDINGS),
            "m.pyc": (b"\x00" * 16 + compiled, privacy_check.EXIT_FINDINGS),
            "strings.bin": (utf16, privacy_check.EXIT_FINDINGS),
            "deep.zip": (nested(privacy_check.MAX_NESTING + 2), privacy_check.EXIT_REFUSED),
        }
        for name, (data, expected) in cases.items():
            with self.subTest(file=name):
                folder = self.tmp / f"pkg-{name}"
                folder.mkdir()
                (folder / name).write_bytes(data)
                code, output = self.run_check("--private", "paths", "--scope", "repo", str(folder))
                self.assertEqual(code, expected, output)

    def test_package_labels_mask_every_rule(self) -> None:
        package = self.tmp / "package"
        package.mkdir()
        address = "zed" + "@" + "corp-mail.net"
        (package / f"{address}.txt").write_text("AK" + "IA" + "Z" * 16 + "\n", encoding="utf-8")
        code, output = self.run_check("paths", str(package))
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertNotIn(address, output)

    def test_invalid_allowlists_are_refused(self) -> None:
        for content in ('{"paths": [', '{"paths": [{"glob": "x", "rules": "email-address"}]}',
                        '{"paths": [{"glob": "x", "rules": ["emial-address"]}]}',
                        '{"paths": [{"glob": "x", "rules": ["private:x"]}]}'):
            with self.subTest(content=content):
                path = self.tmp / "allow.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(privacy_check.Refused):
                    privacy_check.load_allowlist(path)

    def test_a_config_whose_ids_would_print_private_text_is_refused(self) -> None:
        repo = self.new_repo()
        self.commit(repo, "a.txt", "fine\n")
        self.write_private_config({"schema": privacy_check.CONFIG_SCHEMA,
                                   "rules": [{"id": "quux" + "bert", "pattern": "quux" + "bert", "flags": "i"}]})
        self.assertEqual(self.run_check("--private", "--repo", str(repo), "tree")[0], privacy_check.EXIT_REFUSED)

    def test_the_explicit_config_wins_over_the_environment(self) -> None:
        self.write_private_config()
        other = self.tmp / "other" / "privacy-private.json"
        other.parent.mkdir()
        other.write_text(json.dumps({"schema": privacy_check.CONFIG_SCHEMA,
                                     "rules": [{"id": "unrelated", "pattern": "zzqqzz"}]}), encoding="utf-8")
        repo = self.new_repo()
        self.commit(repo, "a.txt", f"{PRIVATE_TOKEN}\n")
        with mock.patch.dict(os.environ, {privacy_check.CONFIG_ENV: str(other)}):
            self.assertEqual(self.run_check("--private", "--repo", str(repo), "tree")[0], privacy_check.EXIT_CLEAN)
            code, _ = self.run_check("--private", "--config", str(self.config_path), "--repo", str(repo), "tree")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)

    def test_publish_reads_everything_committed_not_the_working_copy(self) -> None:
        self.write_private_config()
        repo = self.new_repo()
        self.commit(repo, "a.md", f"{PRIVATE_TOKEN}\n")
        (repo / "a.md").write_text("clean\n", encoding="utf-8")
        code, output = self.run_check("--repo", str(repo), "publish")
        self.assertEqual(code, privacy_check.EXIT_REFUSED, output)  # the working copy differs from HEAD
        self.commit(repo, "a.md", "clean\n")
        self.git(repo, "checkout", "-q", "-b", "side")
        self.commit(repo, "c.md", "clean too\n")
        self.git(repo, "checkout", "-q", "-")
        code, output = self.run_check("--repo", str(repo), "publish")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)  # the old version is still in history

    def test_pre_push_blocks_a_commit_that_adds_a_private_token(self) -> None:
        self.write_private_config()
        _, work = self.remote_and_clone()
        head = self.commit(work, "notes.md", f"{PRIVATE_TOKEN} was here\n", "add notes")
        code, output = self.push_check(work, head)
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.assertRegex(output, r"notes\.md@[0-9a-f]{7}:1")
        self.assertIn("1 commit(s)", output)

    def test_pre_push_blocks_add_then_remove(self) -> None:
        self.write_private_config()
        _, work = self.remote_and_clone()
        self.commit(work, "notes.md", f"{PRIVATE_TOKEN} was here\n", "add notes")
        head = self.commit(work, "notes.md", "nothing to see\n", "remove it again")
        self.assertEqual(self.run_check("--private", "--repo", str(work), "tree")[0], privacy_check.EXIT_CLEAN)
        code, output = self.push_check(work, head)
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.assertRegex(output, r"notes\.md@[0-9a-f]{7}:1: private:maintainer-name")
        self.assertIn("2 commit(s)", output)

    def test_pre_push_reads_whole_commits_and_tags(self) -> None:
        self.write_private_config()
        _, work = self.remote_and_clone()
        cases = [
            ("message", lambda: self.commit(work, "a.txt", "fine\n", f"thanks {PRIVATE_TOKEN}")),
            ("message after a marker", lambda: self.commit(
                work, "b.txt", "fine\n", f"tidy\n\x1d\x1dEND-OF-MESSAGE\nthanks {PRIVATE_TOKEN}")),
            ("author name", lambda: self.commit(work, "c.txt", "fine\n", "x", "-c", f"user.name={PRIVATE_TOKEN} T")),
            ("file after a marker", lambda: self.commit(
                work, "d.txt", f"\x1e\x1eCOMMIT {PRIVATE_TOKEN} line\n", "x")),
        ]
        for name, make in cases:
            with self.subTest(case=name):
                self.git(work, "reset", "-q", "--hard", "origin/main")
                head = make()
                code, output = self.push_check(work, head)
                self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.git(work, "reset", "-q", "--hard", "origin/main")
        self.git(work, "-c", "user.email=zed" + "@" + "corp-mail.net", "commit", "-q", "--allow-empty", "-m", "x")
        code, output = self.push_check(work, self.sha(work), private=False)
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("author", output)
        code, output = self.run_check("--identity-findings", "warn", "--repo", str(work), "push", "origin",
                                      stdin_text=f"refs/heads/t {self.sha(work)} refs/heads/t {'0' * 40}\n")
        self.assertEqual(code, privacy_check.EXIT_CLEAN, output)
        self.assertIn("warning", output)

    def test_pre_push_reads_tags_blobs_and_trees_sent_directly(self) -> None:
        self.write_private_config()
        _, work = self.remote_and_clone()
        self.git(work, "tag", "-a", "inner", "-m", f"cut by {PRIVATE_TOKEN}")
        self.git(work, "tag", "-a", "outer", "-m", "clean", "inner")
        blob = self.git(work, "hash-object", "-w", "--stdin", stdin=f"{PRIVATE_TOKEN} notes\n").stdout.decode().strip()
        clean_blob = self.git(work, "hash-object", "-w", "--stdin", stdin="clean\n").stdout.decode().strip()
        tree = self.git(work, "mktree", stdin=f"100644 blob {clean_blob}\t{PRIVATE_TOKEN}.txt\n").stdout.decode().strip()
        cases = {
            "tag of a tag": ("refs/tags/outer", self.sha(work, "outer")),
            "blob as a tag": ("refs/tags/blobtag", blob),
            "tree as a tag": ("refs/tags/treetag", tree),
            "tag by id to another namespace": ("refs/custom/x", self.sha(work, "inner")),
        }
        for name, (ref, oid) in cases.items():
            with self.subTest(case=name):
                code, output = self.push_check(work, oid, ref=ref)
                self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)

    def test_pre_push_sees_empty_files_gitlinks_zips_and_ignores_replacements(self) -> None:
        self.write_private_config()
        _, work = self.remote_and_clone()
        self.git(work, "config", "diff.submodule", "log")
        cases = {}
        cases["empty file in a named folder"] = lambda: self.commit(
            work, f"AREA/{PRIVATE_TOKEN}-recordings/.gitkeep", b"", "keep")
        cases["renamed empty file"] = lambda: (
            self.commit(work, "keep.txt", b"", "keep"),
            self.git(work, "push", "-q", "origin", "HEAD:refs/heads/main"),
            self.git(work, "mv", "keep.txt", f"{PRIVATE_TOKEN}.txt"),
            self.git(work, "commit", "-q", "-m", "rename"),
            self.sha(work))[-1]

        def gitlink():
            other = self.sha(work)
            self.git(work, "update-index", "--add", "--cacheinfo", f"160000,{other},vendor/{PRIVATE_TOKEN}-sub")
            self.git(work, "commit", "-q", "-m", "submodule")
            return self.sha(work)

        cases["submodule entry"] = gitlink

        def zipped():
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("notes.txt", f"{PRIVATE_TOKEN}\n" * 20)
            return self.commit(work, "fixture.zip", buffer.getvalue(), "zip")

        cases["deflated zip member"] = zipped

        def replaced():
            bad = self.commit(work, "r.txt", f"{PRIVATE_TOKEN}\n", "bad")
            self.git(work, "reset", "-q", "--hard", "HEAD~1")
            good = self.commit(work, "r.txt", "clean\n", "good")
            self.git(work, "replace", bad, good)
            self.git(work, "reset", "-q", "--hard", bad)
            return bad

        cases["replace ref"] = replaced
        for name, make in cases.items():
            with self.subTest(case=name):
                self.git(work, "fetch", "-q", "origin")
                self.git(work, "reset", "-q", "--hard", "origin/main")
                head = make()
                code, output = self.push_check(work, head)
                self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
                self.assertNotIn(PRIVATE_TOKEN.lower(), output.lower())

    def test_pre_push_asks_the_destination_what_it_already_has(self) -> None:
        self.write_private_config()
        bare, work = self.remote_and_clone()
        old = self.commit(work, "old.md", f"{PRIVATE_TOKEN}\n", "old private")
        self.git(work, "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main")
        self.git(work, "fetch", "-q", "origin")
        head = self.commit(work, "new.md", "clean\n", "new clean")
        # The destination already has the private commit: only the new one is checked.
        self.assertEqual(self.push_check(work, head, ref="refs/heads/main", remote_sha=old)[0], privacy_check.EXIT_CLEAN)
        self.assertEqual(self.push_check(work, head)[0], privacy_check.EXIT_CLEAN)
        # A new, empty repository has nothing: the whole history is checked, whatever the clone's
        # remote-tracking refs say, including after the remote is re-pointed with set-url.
        public = self.tmp / "public.git"
        self.git(self.tmp, "init", "-q", "--bare", str(public))
        code, output = self.push_check(work, head, remote=str(public))
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        self.git(work, "remote", "set-url", "origin", str(public))
        code, output = self.push_check(work, head)
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)

    def test_a_deletion_sends_nothing(self) -> None:
        _, work = self.remote_and_clone()
        code, output = self.run_check("--repo", str(work), "push", "origin", "origin",
                                      stdin_text=f"(delete) {'0' * 40} refs/heads/gone {'1' * 40}\n")
        self.assertEqual(code, privacy_check.EXIT_CLEAN, output)

    def test_push_lines_with_spaces_are_read_and_unreadable_lines_refused(self) -> None:
        self.write_private_config()
        _, work = self.remote_and_clone()
        head = self.commit(work, "notes.md", f"{PRIVATE_TOKEN}\n", "tidy the notes")
        code, output = self.run_check("--private", "--repo", str(work), "push", "origin", "origin",
                                      stdin_text=f"HEAD^{{/tidy the}} {head} refs/heads/n1 {'0' * 40}\n")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
        code, output = self.run_check("--private", "--repo", str(work), "push", "origin", "origin",
                                      stdin_text="something git would never send\n")
        self.assertEqual(code, privacy_check.EXIT_REFUSED, output)

    def test_range_and_ci_push(self) -> None:
        repo = self.new_repo()
        base = self.commit(repo, "a.txt", "one\n")
        self.commit(repo, "a.txt", SYNTHETIC_GENERIC["ai-chat-link"] + "\n")
        head = self.commit(repo, "a.txt", "two\n")
        code, output = self.run_check("--repo", str(repo), "range", f"{base}..{head}")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS)
        self.assertIn("ai-chat-link", output)
        # A force-push leaves GitHub's old tip outside the checkout: ci-push falls back to everything the
        # pushed ref reaches that no other branch or tag reaches, instead of refusing.
        bare = self.tmp / "gh.git"
        self.git(self.tmp, "init", "-q", "--bare", str(bare))
        # One push creates two branches and a tag on the same new commits: none may hide the others.
        self.git(repo, "tag", "v1", head)
        self.git(repo, "push", "-q", str(bare), f"{base}:refs/heads/main", f"{head}:refs/heads/feature",
                 f"{head}:refs/heads/feature2", "refs/tags/v1:refs/tags/v1")
        ci = self.tmp / "ci"
        self.git(self.tmp, "init", "-q", str(ci))
        self.git(ci, "fetch", "-q", str(bare), "+refs/heads/*:refs/remotes/origin/*", "+refs/tags/*:refs/tags/*")
        with mock.patch.dict(os.environ, {privacy_check.DEFAULT_BRANCH_ENV: "main"}):
            for ref, before in (("refs/heads/feature", "f" * 40), ("refs/heads/feature2", "0" * 40),
                                ("refs/tags/v1", "0" * 40)):
                with self.subTest(ref=ref):
                    code, output = self.run_check("--repo", str(ci), "ci-push", "--before", before,
                                                  "--after", head, "--ref", ref)
                    self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)
            code, output = self.run_check("--repo", str(ci), "ci-push", "--before", "0" * 40, "--after", base,
                                          "--ref", "refs/heads/main")
            self.assertEqual(code, privacy_check.EXIT_CLEAN, output)
        code, output = self.run_check("--repo", str(ci), "history")
        self.assertEqual(code, privacy_check.EXIT_FINDINGS, output)


@unittest.skipUnless(shutil.which("git"), "git is needed to run hooks")
class InstalledHookTests(_Sandbox):
    """The installed hooks, run by git itself."""

    def _clone_with_hooks(self, mode: str, expect: int = 0) -> Path:
        bare = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(bare))
        work = self.tmp / "work"
        self.git(self.tmp, "clone", "-q", str(bare), str(work))
        target = work / "tools" / "privacy"
        target.mkdir(parents=True)
        for name in ("privacy_check.py", "allowlist.json"):
            shutil.copyfile(REPO_ROOT / "tools" / "privacy" / name, target / name)
        self.commit(work, ".gitignore", "CLAUDE.local.md\nAGENTS.local.md\n", "start")
        self.git(work, "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main")
        self.git(work, "fetch", "-q", "origin")
        self.assertEqual(self._install(work, "--mode", mode), expect)
        return work

    def _install(self, work: Path, *args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return install_hooks.main(["--repo", str(work), *args])

    def _try_commit(self, work: Path, rel: str, text: str, message: str = "try") -> subprocess.CompletedProcess:
        (work / rel).write_text(text, encoding="utf-8")
        self.git(work, "add", rel)
        return self.git(work, "commit", "-q", "-m", message, check=False)

    def test_private_hooks_block_commits_and_pushes_and_refuse_without_patterns(self) -> None:
        self.write_private_config()
        work = self._clone_with_hooks("private")
        hooks = work / ".git" / "hooks"
        for name in ("pre-commit", "pre-merge-commit", "commit-msg", "pre-push"):
            self.assertIn("Mode: private", (hooks / name).read_text(encoding="utf-8"))
        self.assertNotIn(PRIVATE_TOKEN, (hooks / "pre-commit").read_text(encoding="utf-8"))

        blocked = self._try_commit(work, "notes.md", f"{PRIVATE_TOKEN}\n")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("private:maintainer-name", blocked.stderr.decode("utf-8", "replace"))
        self.git(work, "reset", "-q", "HEAD", "notes.md")
        self.assertNotEqual(self._try_commit(work, "ok.md", "fine\n", f"thanks {PRIVATE_TOKEN}").returncode, 0)
        self.git(work, "reset", "-q", "HEAD", "ok.md")

        # Add, then remove, committed past the pre-commit hook: the pre-push hook still blocks it.
        self.git(work, "add", "notes.md")
        self.git(work, "commit", "-q", "--no-verify", "-m", "add")
        self.git(work, "rm", "-q", "notes.md")
        self.git(work, "commit", "-q", "-m", "remove")
        pushed = self.git(work, "push", "origin", "HEAD:refs/heads/topic", check=False)
        self.assertNotEqual(pushed.returncode, 0)
        self.assertEqual(self.git(work, "ls-remote", "origin", "refs/heads/topic").stdout.strip(), b"")

        # An edit to the working-tree checker cannot weaken the installed hooks.
        (work / "tools" / "privacy" / "privacy_check.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        self.assertNotEqual(self._try_commit(work, "again.md", f"{PRIVATE_TOKEN}\n").returncode, 0)
        self.git(work, "reset", "-q", "HEAD", "again.md")
        self.git(work, "checkout", "-q", "--", "tools/privacy/privacy_check.py")

        os.remove(self.config_path)
        refused = self._try_commit(work, "clean.md", "clean\n")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("REFUSED", refused.stderr.decode("utf-8", "replace"))

    def test_auto_mode_never_downgrades_private_hooks(self) -> None:
        self.write_private_config()
        work = self._clone_with_hooks("private")
        os.remove(self.config_path)
        self.assertEqual(self._install(work), 1)  # auto keeps private mode, and says the patterns are missing
        self.assertIn("Mode: private", (work / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8"))
        self.assertEqual(self._install(work, "--mode", "public"), 0)  # only an explicit request downgrades
        self.assertIn("Mode: public", (work / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8"))

    def test_private_mode_without_patterns_installs_refusing_hooks_and_says_so(self) -> None:
        work = self._clone_with_hooks("private", expect=1)
        refused = self._try_commit(work, "clean.md", "clean\n")
        self.assertNotEqual(refused.returncode, 0)

    def test_public_hooks_use_generic_rules_only(self) -> None:
        self.write_private_config()
        work = self._clone_with_hooks("public")
        self.assertEqual(self._try_commit(work, "notes.md", f"{PRIVATE_TOKEN}\n").returncode, 0)
        blocked = self._try_commit(work, "key.txt", SYNTHETIC_GENERIC["secret-github-token"] + "\n")
        self.assertNotEqual(blocked.returncode, 0)
        self._install(work, "--uninstall")
        self.assertFalse((work / ".git" / "hooks" / "pre-commit").exists())
        self.assertFalse((work / ".git" / "hooks" / install_hooks.SNAPSHOT_DIR).exists())

    def test_foreign_hooks_are_never_half_replaced_and_still_run(self) -> None:
        work = self._clone_with_hooks("public")
        self._install(work, "--uninstall")
        hooks = work / ".git" / "hooks"
        marker = work / "foreign-ran.txt"
        (hooks / "pre-push").write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\nexit 0\n", encoding="utf-8")
        (hooks / "pre-push").chmod(0o755)
        self.assertEqual(self._install(work, "--mode", "public"), 1)
        self.assertFalse((hooks / "pre-commit").exists())  # nothing written on a refusal
        self.assertEqual(self._install(work, "--mode", "public", "--force"), 0)
        self.assertTrue((hooks / "pre-push.before-privacy").exists())
        self.assertEqual(self._install(work, "--mode", "public", "--force"), 0)  # re-install keeps the backup
        self.commit(work, "x.txt", "fine\n", "x")
        self.git(work, "push", "-q", "origin", "HEAD:refs/heads/ok")
        self.assertTrue(marker.exists())
        self._install(work, "--uninstall")
        self.assertIn("foreign-ran", (hooks / "pre-push").read_text(encoding="utf-8"))

    def test_a_blocked_push_never_runs_a_kept_hook(self) -> None:
        self.write_private_config()
        work = self._clone_with_hooks("public")
        self._install(work, "--uninstall")
        hooks = work / ".git" / "hooks"
        marker = work / "foreign-ran.txt"
        (hooks / "pre-push").write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\nexit 0\n", encoding="utf-8")
        (hooks / "pre-push").chmod(0o755)
        self.assertEqual(self._install(work, "--mode", "private", "--force"), 0)
        self.git(work, "add", "-A")
        (work / "n.md").write_text(f"{PRIVATE_TOKEN}\n", encoding="utf-8")
        self.git(work, "add", "n.md")
        self.git(work, "commit", "-q", "--no-verify", "-m", "x")
        self.assertNotEqual(self.git(work, "push", "origin", "HEAD:refs/heads/t", check=False).returncode, 0)
        self.assertFalse(marker.exists())

    def test_private_hooks_work_in_a_linked_worktree(self) -> None:
        self.write_private_config()
        work = self._clone_with_hooks("private")
        linked = self.tmp / "linked"
        self.git(work, "worktree", "add", "-q", "-b", "side", str(linked))
        self.assertEqual(self._try_commit(linked, "ok.md", "fine\n").returncode, 0)
        self.assertNotEqual(self._try_commit(linked, "bad.md", f"{PRIVATE_TOKEN}\n").returncode, 0)
        self.git(linked, "reset", "-q", "HEAD", "bad.md")
        self.assertEqual(self.git(linked, "push", "origin", "HEAD:refs/heads/side", check=False).returncode, 0)

    def test_an_older_checkout_cannot_replace_the_installed_checker(self) -> None:
        work = self._clone_with_hooks("public")
        old = self.sha(work)
        self.commit(work, "newer.txt", "newer\n", "newer")
        self.assertEqual(self._install(work, "--mode", "public"), 0)
        self.git(work, "checkout", "-q", old)
        self.assertEqual(self._install(work, "--mode", "public"), 1)
        self.assertEqual(self._install(work, "--mode", "public", "--force"), 0)

    def test_installer_refuses_a_hooks_path_setting(self) -> None:
        bare = self.tmp / "r.git"
        self.git(self.tmp, "init", "-q", "--bare", str(bare))
        work = self.tmp / "w"
        self.git(self.tmp, "clone", "-q", str(bare), str(work))
        (work / "tools" / "privacy").mkdir(parents=True)
        for name in ("privacy_check.py", "allowlist.json"):
            shutil.copyfile(REPO_ROOT / "tools" / "privacy" / name, work / "tools" / "privacy" / name)
        self.git(work, "config", "core.hooksPath", ".githooks")
        self.assertEqual(self._install(work, "--mode", "public"), 1)
        self.assertFalse((work / ".githooks").exists())

    def test_private_install_copies_local_agent_rules_without_overwriting(self) -> None:
        self.write_private_config()
        rules = self.config_path.parent / "local-rules"
        rules.mkdir()
        (rules / "AGENTS.local.md").write_text("local rules\n", encoding="utf-8")
        work = self._clone_with_hooks("private")
        self.assertEqual((work / "AGENTS.local.md").read_text(encoding="utf-8"), "local rules\n")
        self.assertEqual(self.git(work, "status", "--porcelain").stdout.strip(), b"")


class ThisRepositoryTests(unittest.TestCase):
    def test_this_repository_passes_the_generic_check(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = privacy_check.main(["--repo", str(REPO_ROOT), "tree"])
        self.assertEqual(code, privacy_check.EXIT_CLEAN, err.getvalue())

    def test_the_workflow_runs_the_check_on_pull_requests_pushes_and_tags(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "privacy-check.yml").read_text(encoding="utf-8")
        for needle in ("pull_request", "push:", "tags:", "schedule:", "fetch-depth: 0", "privacy_check.py\" tree",
                       "range \"$BASE_SHA..$HEAD_SHA\"", "ci-push", "history", "tests.test_privacy_check",
                       "--identity-findings warn", "PRIVACY_DEFAULT_BRANCH"):
            self.assertIn(needle, workflow)
        self.assertNotIn("--private", workflow)
        # v6 or later keeps a pushed annotated tag as a tag object, so the tag's own lines are read.
        checkout = re.search(r"uses: actions/checkout@[0-9a-f]{40} # v(\d+)\.", workflow)
        self.assertIsNotNone(checkout, "the checkout action is not pinned to a v6-or-later commit")
        self.assertGreaterEqual(int(checkout.group(1)), 6)

    def test_every_action_is_pinned_to_a_full_commit(self) -> None:
        """A tag such as v6 can be moved to other code; a full commit cannot. Each pin names its release."""
        pinned = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40} # v\d+\.\d+\.\d+$")
        workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
        self.assertTrue(workflows)
        seen = 0
        for workflow in workflows:
            for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
                found = re.match(r"\s*(?:-\s+)?uses:\s*(.+?)\s*$", line)
                if found:
                    seen += 1
                    self.assertRegex(found.group(1), pinned, f"{workflow.name}:{number}")
        self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()
