from __future__ import annotations

from pathlib import Path
import re
import struct
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELP_ROOT = REPO_ROOT / "docs" / "workbench"
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers_workbench.app import (  # noqa: E402
    DEPENDENCY_HELP_ANCHORS,
    TRANSIENT_PROFILE_KEYS,
    WORKBENCH_HELP_ROOT_URL,
    WORKBENCH_HELP_URL,
    WORKBENCH_TROUBLESHOOTING_URL,
    WORKFLOW_HELP_URLS,
)
from media_manglers_workbench.levels_service import (  # noqa: E402
    STATE_FAILED,
    STATE_NO_AUDIO,
    STATE_STILL_RECORDING,
    STATE_WAITING_FOR_RUN,
)
from media_manglers_workbench.recording_lists import PROCESSED_KEY, recording_status_text  # noqa: E402
from media_manglers_workbench.review_package import reason_text  # noqa: E402
from media_manglers_workbench.review_player import (  # noqa: E402
    ALLOW_AGAIN_TEXT,
    BADGE_RESCUED,
    BADGE_SPOTTER,
    END_OF_LIST_TEXT,
    LOOKING_FOR_TRANSCRIPT_TEXT,
    MEASURE_AGAIN_LIBRARY_TOOLTIP,
    MEASURE_AGAIN_TEXT,
    NEVER_USE_TEXT,
    NO_AUDIT_TEXT,
    NO_WAVEFORMS_CLIP_TEXT,
    NO_WAVEFORMS_REVIEW_COPY_TEXT,
    NO_LIST_TEXT,
    NO_RESCUE_RECORD_TEXT,
    NO_TRANSCRIPT_TEXT,
    PACKAGE_FILE_NEVER_USE_TOOLTIP,
    PACKAGE_FILE_STATUS_TEXT,
    PACKAGE_FILE_TRANSCRIPT_TEXT,
    RELEASED_TRANSCRIPT_TEXT,
    SAVE_FAILED_TEXT,
    SKIP_TEXT,
    SKIP_TOOLTIP,
    UNKNOWN_MODE_TEXT,
    UNPLAYABLE_TEXT,
)
from media_manglers_workbench.video_open import (  # noqa: E402
    FIND_IT_TEXT,
    FIND_VLC_TEXT,
    MISSING_TEXT,
    OPEN_MOMENT_INTERNAL_TEXT,
    PLAY_FROM_START_TEXT,
    PLAY_HERE_TEXT,
    PLAY_MOMENT_TEXT,
    PLAY_REVIEW_COPY_TEXT,
    PLAY_WITH_TEXT,
    PLAYER_NAMES,
    SHOW_IN_FOLDER_TEXT,
    VLC_FAILED_TEXT,
    VLC_FALLBACK_NOTE,
    VLC_MISSING_FIND_ONLY_TEXT,
    VLC_MISSING_TEXT,
    VLC_NOT_FOUND_TEXT,
)


WORKBENCH_SOURCE = REPO_ROOT / "src" / "media_manglers_workbench"
MARKDOWN_FILES = tuple(sorted(HELP_ROOT.glob("*.md")))
OPERATOR_PAGES = (
    "GETTING_STARTED.md",
    "FULL_REVIEW.md",
    "TRANSCRIPT_ONLY.md",
    "CODEX_EVIDENCE.md",
    "ARCHIVE_CATALOG.md",
    "REVIEW_NEW_VIDEOS.md",
    "DEPENDENCIES_SETUP.md",
    "PROGRESS_RESULTS.md",
    "SETTINGS_MIGRATION.md",
    "TROUBLESHOOTING.md",
)
SCREENSHOTS = (
    HELP_ROOT / "images" / "workbench-home.png",
    HELP_ROOT / "images" / "new-review-narration.png",
    HELP_ROOT / "images" / "review-and-run-blockers.png",
    HELP_ROOT / "images" / "queue-and-progress.png",
    HELP_ROOT / "images" / "dependency-readiness.png",
)


def _anchor_for_heading(heading: str) -> str:
    anchor = heading.strip().casefold()
    anchor = re.sub(r"[^a-z0-9 _-]", "", anchor)
    anchor = re.sub(r"[ _]+", "-", anchor)
    return re.sub(r"-+", "-", anchor).strip("-")


def _anchors(path: Path) -> set[str]:
    return {
        _anchor_for_heading(match.group(1))
        for match in re.finditer(
            r"^#{1,6}\s+(.+?)\s*$",
            path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    }


def _as_read(text: str) -> str:
    # A help page is wrapped at the margin and a reader never sees where. One
    # space for every run of white space lets a quoted sentence be found
    # whether or not it happens to cross a line end in the file.
    return " ".join(text.split())


class WorkbenchHelpTests(unittest.TestCase):
    def test_help_documents_and_screenshots_exist(self) -> None:
        for path in (*MARKDOWN_FILES, *SCREENSHOTS):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)

    def test_local_markdown_links_and_images_resolve(self) -> None:
        link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        for document in MARKDOWN_FILES:
            text = document.read_text(encoding="utf-8")
            for target in link_pattern.findall(text):
                if target.startswith(("http://", "https://", "#")):
                    continue
                relative, _, anchor = target.partition("#")
                destination = (document.parent / relative).resolve()
                with self.subTest(document=document.name, target=target):
                    self.assertTrue(destination.is_file())
                    if anchor and destination.suffix.casefold() == ".md":
                        self.assertIn(anchor, _anchors(destination))

    def test_online_help_urls_match_repo_and_real_anchors(self) -> None:
        expected_root = "https://github.com/Aintologic/media-manglers/blob"
        self.assertEqual(WORKBENCH_HELP_ROOT_URL, expected_root)
        self.assertEqual(WORKBENCH_HELP_URL, "README.md")
        self.assertEqual(WORKBENCH_TROUBLESHOOTING_URL, "TROUBLESHOOTING.md")
        self.assertEqual(
            set(WORKFLOW_HELP_URLS.values()),
            {
                "FULL_REVIEW.md",
                "TRANSCRIPT_ONLY.md",
                "CODEX_EVIDENCE.md",
                "ARCHIVE_CATALOG.md",
                "REVIEW_NEW_VIDEOS.md",
            },
        )
        for document in WORKFLOW_HELP_URLS.values():
            self.assertTrue((HELP_ROOT / document).is_file())
        troubleshooting_anchors = _anchors(HELP_ROOT / "TROUBLESHOOTING.md")
        self.assertIn("dependency-readiness-and-preflight", troubleshooting_anchors)
        for anchor in DEPENDENCY_HELP_ANCHORS.values():
            self.assertIn(anchor, troubleshooting_anchors)

    def test_help_uses_current_operator_labels(self) -> None:
        combined = "\n".join(path.read_text(encoding="utf-8") for path in MARKDOWN_FILES)
        for label in (
            "Inspect N source files",
            "Preview track",
            "Confirm microphone",
            "Start review — blocked",
            "Codex Evidence",
            "Getting started",
            "Technical details and processing log",
            "Advanced / Diagnostics",
            "Debug details",
            # The built-in player (125): the two Settings > Video player
            # labels and the three player controls an operator looks up most.
            "Play videos with",
            "Start playing straight away",
            "Never use this recording",
            "Previous line",
            "Next line",
        ):
            with self.subTest(label=label):
                self.assertIn(label, combined)
        for old_label in (
            "Preview selected track",
            "This is my microphone narration",
            "Inspect audio tracks",
            "Open candidate evidence",
            "backend log",
            "Advanced backend",
        ):
            with self.subTest(old_label=old_label):
                self.assertNotIn(old_label.casefold(), combined.casefold())

    def test_operator_pages_have_scannable_navigation(self) -> None:
        for name in OPERATOR_PAGES:
            text = (HELP_ROOT / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertIn("Back to Help", text)
                self.assertIn("Previous:", text)
                self.assertTrue(
                    "Next:" in text or name == "TROUBLESHOOTING.md"
                )

    def test_review_player_page_is_reachable_and_uses_operator_words(self) -> None:
        """The built-in player's help page (125)."""

        page = (HELP_ROOT / "REVIEW_PLAYER.md").read_text(encoding="utf-8")
        # It sits outside the Previous/Next chain, like FIND_BUG_REPORTS.md, so
        # the links into it are the only way an operator reaches it.
        for linking_page in ("README.md", "FIND_BUG_REPORTS.md"):
            with self.subTest(linking_page=linking_page):
                self.assertIn(
                    "(REVIEW_PLAYER.md)",
                    (HELP_ROOT / linking_page).read_text(encoding="utf-8"),
                )
        self.assertTrue(page.rstrip().endswith("[Back to Help](README.md)"))
        # Engineering words that must never reach an operator. This is scoped to
        # the one page because TECHNICAL_REFERENCE.md may legitimately use them.
        for word in (
            "envelope",
            "backend",
            "libvlc",
            "qmediaplayer",
            "coalesce",
            # The names a package gives the transcriber's scores. Show the
            # numbers says them in plain words, and so must the page.
            "no_speech_prob",
            "avg_logprob",
            "compression_ratio",
        ):
            with self.subTest(word=word):
                self.assertNotIn(word, page.casefold())
        # The second increment (125 Part 2, Wave 8) is built, so the page describes it: the lanes and
        # their button, the sounds and the moments, each with the key it has.
        read = _as_read(page)
        for words in (
            "## Waveforms of every track",
            "**Waveforms**",
            "**Next sound** (Ctrl+Right)",
            "**Previous sound** (Ctrl+Left)",
            "## Moments the package found",
            "**Next moment** (])",
            "**Previous moment** ([)",
            "| W | Show or hide the waveforms |",
        ):
            with self.subTest(words=words):
                self.assertTrue(words in read, f"REVIEW_PLAYER.md does not say: {words!r}")

    def test_review_player_page_quotes_every_left_out_reason_exactly(self) -> None:
        """An operator searches Help for the sentence the player showed them."""

        page = (HELP_ROOT / "REVIEW_PLAYER.md").read_text(encoding="utf-8")
        # Synthetic inputs only: one with letters, one without, and a made-up
        # time span and code standing in for whatever a package recorded.
        shown = (
            reason_text("known_filler_phrase", "synthetic words"),
            reason_text("known_filler_phrase", "..."),
            reason_text("compression_ratio_threshold"),
            reason_text("combined_low_speech_information"),
            reason_text("repetition_persisted_after_retry", start=0.0, end=0.0).replace(
                "0:00:00", "H:MM:SS"
            ),
            reason_text("…"),
        )
        for sentence in shown:
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, page)

    def test_review_player_page_quotes_the_players_own_sentences(self) -> None:
        """The page and the player say the same thing, word for word.

        Imported by name on purpose: a sentence that is reworded, renamed or
        removed in the code fails here until the page says the new thing.
        """

        page = _as_read((HELP_ROOT / "REVIEW_PLAYER.md").read_text(encoding="utf-8"))
        # A made-up recording; the date is the stand-in the page uses for one.
        recording = "synthetic-session-one.mkv"
        quoted = {
            "recording_status_text, not done": f"`{recording_status_text({}, recording)}`",
            "recording_status_text, done": recording_status_text({PROCESSED_KEY: {recording: "<date>"}}, recording),
            # The transcript panel's notes.
            "LOOKING_FOR_TRANSCRIPT_TEXT": LOOKING_FOR_TRANSCRIPT_TEXT,
            "NO_TRANSCRIPT_TEXT": NO_TRANSCRIPT_TEXT,
            "NO_AUDIT_TEXT": NO_AUDIT_TEXT,
            "NO_RESCUE_RECORD_TEXT": NO_RESCUE_RECORD_TEXT,
            "UNKNOWN_MODE_TEXT": UNKNOWN_MODE_TEXT,
            "PACKAGE_FILE_TRANSCRIPT_TEXT": PACKAGE_FILE_TRANSCRIPT_TEXT,
            "RELEASED_TRANSCRIPT_TEXT": RELEASED_TRANSCRIPT_TEXT,
            "BADGE_RESCUED": BADGE_RESCUED,
            "BADGE_SPOTTER": BADGE_SPOTTER,
            # The "This recording" row and what never-use answers.
            "NEVER_USE_TEXT": NEVER_USE_TEXT,
            "ALLOW_AGAIN_TEXT": ALLOW_AGAIN_TEXT,
            "SKIP_TEXT": SKIP_TEXT,
            "SKIP_TOOLTIP": SKIP_TOOLTIP,
            "PACKAGE_FILE_STATUS_TEXT": PACKAGE_FILE_STATUS_TEXT,
            "PACKAGE_FILE_NEVER_USE_TOOLTIP": PACKAGE_FILE_NEVER_USE_TOOLTIP,
            "NO_LIST_TEXT": NO_LIST_TEXT,
            "END_OF_LIST_TEXT": END_OF_LIST_TEXT,
            "SAVE_FAILED_TEXT": SAVE_FAILED_TEXT,
            "UNPLAYABLE_TEXT": UNPLAYABLE_TEXT,
            # The waveform lanes (125 Part 2): what they say while there are none, and their right-click.
            "STATE_WAITING_FOR_RUN": STATE_WAITING_FOR_RUN,
            "STATE_STILL_RECORDING": STATE_STILL_RECORDING,
            "STATE_NO_AUDIO": STATE_NO_AUDIO,
            "STATE_FAILED": STATE_FAILED,
            "MEASURE_AGAIN_TEXT": MEASURE_AGAIN_TEXT,
            "MEASURE_AGAIN_LIBRARY_TOOLTIP": MEASURE_AGAIN_LIBRARY_TOOLTIP,
            "NO_WAVEFORMS_CLIP_TEXT": NO_WAVEFORMS_CLIP_TEXT,
            "NO_WAVEFORMS_REVIEW_COPY_TEXT": NO_WAVEFORMS_REVIEW_COPY_TEXT,
            # The right-click entries and the answers a message offers.
            "PLAY_MOMENT_TEXT": PLAY_MOMENT_TEXT,
            "PLAY_FROM_START_TEXT": PLAY_FROM_START_TEXT,
            "OPEN_MOMENT_INTERNAL_TEXT": OPEN_MOMENT_INTERNAL_TEXT,
            "PLAY_WITH_TEXT": PLAY_WITH_TEXT,
            "SHOW_IN_FOLDER_TEXT": SHOW_IN_FOLDER_TEXT,
            "FIND_IT_TEXT": FIND_IT_TEXT,
            "PLAY_REVIEW_COPY_TEXT": PLAY_REVIEW_COPY_TEXT,
            "FIND_VLC_TEXT": FIND_VLC_TEXT,
            "PLAY_HERE_TEXT": PLAY_HERE_TEXT,
            **{f"PLAYER_NAMES[{choice}]": name for choice, name in PLAYER_NAMES.items()},
            # A recording or VLC that cannot be found. The file name is the only
            # part of any of these that changes, so a stand-in is put in for it.
            "MISSING_TEXT": MISSING_TEXT.format(name="<file name>"),
            "VLC_NOT_FOUND_TEXT": VLC_NOT_FOUND_TEXT,
            "VLC_FALLBACK_NOTE": VLC_FALLBACK_NOTE,
            "VLC_MISSING_TEXT": VLC_MISSING_TEXT,
            "VLC_MISSING_FIND_ONLY_TEXT": VLC_MISSING_FIND_ONLY_TEXT,
            "VLC_FAILED_TEXT": VLC_FAILED_TEXT,
        }
        for constant, sentence in quoted.items():
            with self.subTest(constant=constant):
                # Not assertIn: its message would print the whole page.
                self.assertTrue(
                    _as_read(sentence) in page,
                    f"REVIEW_PLAYER.md does not quote {constant}: {sentence!r}",
                )

    def test_review_player_page_quotes_the_sentences_put_together_as_they_are_shown(self) -> None:
        """Sentences with a file name, a mode or a time in them have no constant.

        So each is written out here as the page words it, together with the
        fixed words that must still be in the code. Rewording one in the code
        fails here, which is the only thing that keeps the page from going
        quietly out of date.
        """

        page = _as_read((HELP_ROOT / "REVIEW_PLAYER.md").read_text(encoding="utf-8"))
        built = (
            (
                "review_player.py",
                "No filtering ran for this recording — it was transcribed in <mode> mode.",
                ("No filtering ran for this recording — it was transcribed in ", " mode."),
            ),
            (
                "review_player.py",
                "Nothing transcribed here. Next line at H:MM:SS.",
                ("Nothing transcribed here. Next line at ",),
            ),
            (
                "review_player.py",
                'You marked "<file name>" never-use.',
                ('You marked "', '" never-use.'),
            ),
            (
                "review_player.py",
                "Stopped. Press Play to carry on from <time>.",
                ("Stopped. Press Play to carry on from ",),
            ),
            (
                "review_player.py",
                "Playing the small review copy of <file name>.",
                ("Playing the small review copy of ",),
            ),
            # Show the numbers: three plain lines, then the wording before the
            # glossary, or the one sentence that says there is nothing to show.
            ("review_player.py", "Chance nobody was speaking:", ("Chance nobody was speaking: ",)),
            ("review_player.py", "How sure it was of the words:", ("How sure it was of the words: ",)),
            ("review_player.py", "How much it repeated itself:", ("How much it repeated itself: ",)),
            ("review_player.py", "above 2.4 means it was looping", ("(above 2.4 means it was looping)",)),
            ("review_player.py", "Before your glossary: …", ("Before your glossary: ",)),
            (
                "review_player.py",
                "This package recorded no numbers for this line.",
                ("This package recorded no numbers for this line.",),
            ),
            (
                "review_player.py",
                "This recording will be skipped in the run that is going now.",
                ("This recording will be skipped in the run that is going now.",),
            ),
            (
                "review_player.py",
                "This recording is not waiting in the run that is going now.",
                ("This recording is not waiting in the run that is going now.",),
            ),
            (
                "review_player.py",
                "On your never-use list",
                ('"On your never-use list"',),
            ),
            # The waveform lanes while the sound is measured (125 Part 2).
            (
                "levels_service.py",
                "Measuring the sound of every track: 40% (about 2 minutes left).",
                ("Measuring the sound of every track: ", "about {minutes} minutes left"),
            ),
            # Said in the player's window by the main window when it cannot close yet.
            (
                "app.py",
                "The built-in player is still finishing. Close the Workbench again in a moment.",
                ("The built-in player is still finishing. Close the Workbench again in a moment.",),
            ),
        )
        sources = {
            name: (WORKBENCH_SOURCE / name).read_text(encoding="utf-8")
            for name in {entry[0] for entry in built}
        }
        for module, on_page, in_code in built:
            with self.subTest(sentence=on_page):
                # Not assertIn: its message would print the whole page or module.
                self.assertTrue(_as_read(on_page) in page, f"REVIEW_PLAYER.md does not say: {on_page!r}")
                for words in in_code:
                    self.assertTrue(words in sources[module], f"{module} no longer says: {words!r}")

    def test_review_player_page_puts_the_controls_where_they_really_are(self) -> None:
        page = _as_read((HELP_ROOT / "REVIEW_PLAYER.md").read_text(encoding="utf-8"))
        # Only the seven buttons that have a key end their tooltip with it;
        # Hear this track, Undo, Skip and Never use have none.
        self.assertFalse("every button's tooltip ends with its key" in page)
        # Hear: Track N sits in the second row, with Speed and Volume, and the
        # results screen has a button of its own.
        for words in (
            "every button that has a key ends its tooltip with it",
            "**Speed**",
            "**Volume**",
            "Watch a recording…",
        ):
            with self.subTest(words=words):
                self.assertTrue(words in page, f"REVIEW_PLAYER.md does not say: {words!r}")

    def test_help_says_what_applying_a_profile_does_to_the_player_settings(self) -> None:
        """The player's settings ARE written into a saved profile file.

        What is true, and what the pages may say, is that applying a profile
        leaves them alone: that is what TRANSIENT_PROFILE_KEYS does.
        """

        for key in (
            "video_player",
            "video_autoplay",
            "video_player_vlc_path",
            "review_player_geometry",
            "review_player_volume",
        ):
            with self.subTest(key=key):
                self.assertIn(key, TRANSIENT_PROFILE_KEYS)
        true_sentence = "Applying a profile never changes how videos open"
        for name in ("SETTINGS_MIGRATION.md", "REVIEW_PLAYER.md"):
            text = _as_read((HELP_ROOT / name).read_text(encoding="utf-8"))
            with self.subTest(page=name):
                self.assertTrue(true_sentence in text, f"{name} does not say: {true_sentence!r}")
        # Said once in all of Help, and only about the never-use list and the
        # already-done record (114), which really are stripped on saving.
        combined = _as_read("\n".join(path.read_text(encoding="utf-8") for path in MARKDOWN_FILES))
        self.assertEqual(combined.count("never copied into a saved profile"), 1)

    def test_codex_evidence_guide_is_numbered_and_pictorial(self) -> None:
        text = (HELP_ROOT / "CODEX_EVIDENCE.md").read_text(encoding="utf-8")
        for step in range(1, 9):
            self.assertRegex(text, rf"(?m)^## {step}\.")
        for screenshot in SCREENSHOTS[1:]:
            self.assertIn(f"images/{screenshot.name}", text)
        for phrase in (
            "Expected:",
            "Required action",
            "saved layout",
            "Integrity failed",
            "Cancellation",
        ):
            self.assertIn(phrase.casefold(), text.casefold())

    def test_screenshots_are_valid_sanitized_documentation_images(self) -> None:
        # Public check: the committed screenshots must not carry obvious machine
        # or identity strings in their bytes/metadata. Each maintainer's own name,
        # host and drive denylist lives in a private, uncommitted pre-publish
        # check, so this test needs no private files to pass on any machine.
        forbidden = (
            b"C:\\Users\\",
            b"ExampleUser",
            b"CONFIDENTIAL",
            b"@example.com",
        )
        for path in SCREENSHOTS:
            data = path.read_bytes()
            with self.subTest(path=path.name):
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                width, height = struct.unpack(">II", data[16:24])
                self.assertGreaterEqual(width, 1200)
                self.assertGreaterEqual(height, 900)
                for value in forbidden:
                    self.assertNotIn(value.lower(), data.lower())

    def test_capture_is_synthetic_and_packaging_copies_all_help(self) -> None:
        capture = (
            REPO_ROOT / "tools" / "gui" / "Capture-WorkbenchHelpScreenshots.py"
        ).read_text(encoding="utf-8")
        self.assertIn('os.environ.setdefault("QT_QPA_PLATFORM", "windows")', capture)
        self.assertIn("TemporaryDirectory", capture)
        self.assertIn('DEMO_ROOT = Path(r"C:\\MM-DEMO")', capture)
        self.assertIn("_assert_sanitized", capture)
        self.assertIn("FakeRunner", capture)
        # The capture keeps every per-user folder in its temporary folder, so it never opens, upgrades
        # or shows the operator's own library, run history, cache or settings.
        for name in ("MEDIA_MANGLERS_LIBRARY_ROOT", "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA",
                     "MEDIA_MANGLERS_WORKBENCH_APPDATA", "MEDIA_MANGLERS_CACHE_ROOT",
                     "MEDIA_MANGLERS_VIDEOS_FOLDER", "MEDIA_MANGLERS_MUSIC_FOLDER"):
            self.assertIn(f'("{name}", ', capture)
        build_script = (
            REPO_ROOT / "tools" / "gui" / "Build-VideoManglerWorkbench.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('Join-Path $repoRoot "docs\\workbench"', build_script)
        self.assertIn("-Recurse -Force", build_script)


if __name__ == "__main__":
    unittest.main()
