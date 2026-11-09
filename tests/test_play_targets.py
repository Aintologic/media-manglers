"""What to play, which comes next, and where VLC is (125).

No Qt is imported here on purpose: ``play_targets`` has to stay usable
without it, and this file importing cleanly is part of the proof.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers_workbench import play_targets  # noqa: E402
from media_manglers_workbench.audio_detection import SUPPORTED_MEDIA_EXTENSIONS  # noqa: E402
from media_manglers_workbench.play_targets import (  # noqa: E402
    PLAYER_CHOICES,
    PLAYER_INTERNAL,
    PLAYER_SYSTEM,
    PLAYER_VLC,
    VIDEO_SUFFIXES,
    PlaySequence,
    PlayTarget,
    build_vlc_command,
    find_vlc,
    is_video_path,
    next_target,
    normalize_player_choice,
)
from media_manglers_workbench.recording_lists import path_key  # noqa: E402


# Invented names only: this repository is public.
SESSION_ONE = r"Q:\Captured Sessions\synthetic-session-one.mkv"
SESSION_TWO = r"Q:\Captured Sessions\synthetic-session-two.mkv"
SESSION_THREE = r"Q:\Captured Sessions\synthetic-session-three.mkv"
SESSION_FOUR = r"Q:\Captured Sessions\synthetic-session-four.mkv"
NOT_IN_LIST = r"Q:\Captured Sessions\synthetic-one-off.mkv"
PACKAGE = r"Q:\Reviews\synthetic-run\codex-evidence-package"
REVIEW_COPY = PACKAGE + r"\narration\review_video_synthetic-session-one.mp4"

WINDOWS_ENVIRON = {
    "ProgramFiles": r"P:\Apps",
    "ProgramFiles(x86)": r"P:\Apps (x86)",
}
VLC_IN_PROGRAM_FILES = r"P:\Apps\VideoLAN\VLC\vlc.exe"
VLC_IN_PROGRAM_FILES_X86 = r"P:\Apps (x86)\VideoLAN\VLC\vlc.exe"
VLC_MAC_SYSTEM = "/Applications/VLC.app/Contents/MacOS/VLC"
VLC_MAC_USER = "/Users/synthetic/Applications/VLC.app/Contents/MacOS/VLC"


def _sequence(*paths: str, label: str = "Synthetic list") -> PlaySequence:
    return PlaySequence(targets=tuple(PlayTarget(path=Path(item)) for item in paths), label=label)


class PlayerChoiceTests(unittest.TestCase):
    def test_constants_are_the_stored_values(self) -> None:
        self.assertEqual(PLAYER_INTERNAL, "internal")
        self.assertEqual(PLAYER_VLC, "vlc")
        self.assertEqual(PLAYER_SYSTEM, "system")
        self.assertEqual(PLAYER_CHOICES, ("internal", "vlc", "system"))

    def test_known_choices_are_kept(self) -> None:
        for choice in PLAYER_CHOICES:
            self.assertEqual(normalize_player_choice(choice), choice)

    def test_unknown_values_become_the_built_in_player(self) -> None:
        for value in ("", "   ", "mpv", "builtin", "vlc.exe", None, 0, 1, True, 2.5, ["vlc"], {"vlc": 1}, b"vlc"):
            with self.subTest(value=value):
                self.assertEqual(normalize_player_choice(value), PLAYER_INTERNAL)

    def test_case_and_stray_spaces_do_not_lose_a_clear_choice(self) -> None:
        self.assertEqual(normalize_player_choice("VLC"), PLAYER_VLC)
        self.assertEqual(normalize_player_choice("System"), PLAYER_SYSTEM)
        self.assertEqual(normalize_player_choice("  Internal \n"), PLAYER_INTERNAL)
        self.assertEqual(normalize_player_choice(" vLc "), PLAYER_VLC)


class VideoPathTests(unittest.TestCase):
    def test_suffixes_come_from_the_supported_media_set(self) -> None:
        self.assertIsInstance(VIDEO_SUFFIXES, frozenset)
        self.assertEqual(VIDEO_SUFFIXES, frozenset(item.lower() for item in SUPPORTED_MEDIA_EXTENSIONS))
        for suffix in (".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v"):
            self.assertIn(suffix, VIDEO_SUFFIXES)

    def test_no_sound_only_container_counts_as_video(self) -> None:
        for suffix in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus"):
            self.assertNotIn(suffix, VIDEO_SUFFIXES)
            self.assertFalse(is_video_path(rf"Q:\Captured Sessions\synthetic-voice{suffix}"))

    def test_video_names_are_recognised_whatever_the_case_or_type(self) -> None:
        self.assertTrue(is_video_path(SESSION_ONE))
        self.assertTrue(is_video_path(Path(SESSION_ONE)))
        self.assertTrue(is_video_path(SESSION_ONE.upper()))
        self.assertTrue(is_video_path("/captured sessions/synthetic.session.one.MP4"))
        self.assertTrue(is_video_path(f"  {SESSION_TWO}  "))
        for suffix in VIDEO_SUFFIXES:
            self.assertTrue(is_video_path(f"synthetic-session{suffix}"))

    def test_other_things_are_not_video(self) -> None:
        for value in (
            "",
            "   ",
            ".",
            r"Q:\Captured Sessions",
            r"Q:\Captured Sessions\synthetic-notes.txt",
            r"Q:\Captured Sessions\manifest.json",
            r"Q:\Captured Sessions\synthetic-session-one.mkv.part",
            r"Q:\Captured Sessions\folder.mkv\synthetic-notes",
            "Queued item 3",
            ".mkv",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_video_path(value))

    def test_a_web_address_is_not_a_file_even_when_it_ends_like_one(self) -> None:
        address = "https://video.example/watch/synthetic-session.mp4"
        self.assertFalse(is_video_path(address))
        self.assertFalse(is_video_path(address.upper()))
        self.assertFalse(is_video_path("https://video.example/watch?v=synthetic"))
        # Callers wrap the value in Path() first, which rewrites the slashes.
        self.assertFalse(is_video_path(Path(address)))
        self.assertFalse(is_video_path(r"https:\video.example\watch\synthetic-session.mp4"))
        self.assertFalse(is_video_path("https:/video.example/watch/synthetic-session.mp4"))

    def test_it_never_touches_the_disk(self) -> None:
        with (
            patch.object(Path, "exists", side_effect=AssertionError("disk touched")),
            patch.object(Path, "is_file", side_effect=AssertionError("disk touched")),
            patch("os.path.isfile", side_effect=AssertionError("disk touched")),
        ):
            self.assertTrue(is_video_path(SESSION_ONE))


class PlayTargetTests(unittest.TestCase):
    def test_defaults(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE))
        self.assertEqual(target.path, Path(SESSION_ONE))
        self.assertEqual(target.start_seconds, 0.0)
        self.assertIsNone(target.package_root)
        self.assertEqual(target.label, "")
        self.assertIsNone(target.voice_track)

    def test_play_target_is_frozen(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE), start_seconds=12.5, voice_track=2)
        for name, value in (
            ("path", Path(SESSION_TWO)),
            ("start_seconds", 1.0),
            ("package_root", Path("Q:/Packages")),
            ("label", "changed"),
            ("voice_track", 5),
        ):
            with self.subTest(field=name), self.assertRaises(FrozenInstanceError):
                setattr(target, name, value)
        with self.assertRaises((AttributeError, TypeError)):
            target.extra = 1  # type: ignore[attr-defined]
        self.assertEqual(target.start_seconds, 12.5)

    def test_play_sequence_is_frozen(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO)
        with self.assertRaises(FrozenInstanceError):
            sequence.targets = ()  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            sequence.label = "changed"  # type: ignore[misc]
        self.assertEqual(PlaySequence(targets=()).label, "")

    def test_targets_compare_and_hash_by_value(self) -> None:
        first = PlayTarget(path=Path(SESSION_ONE), start_seconds=3.0)
        same = PlayTarget(path=Path(SESSION_ONE), start_seconds=3.0)
        self.assertEqual(first, same)
        self.assertEqual(len({first, same}), 1)
        self.assertEqual(hash(_sequence(SESSION_ONE)), hash(_sequence(SESSION_ONE)))

    def test_a_sequence_is_a_snapshot_of_the_list_it_was_given(self) -> None:
        rows = [PlayTarget(path=Path(SESSION_ONE)), PlayTarget(path=Path(SESSION_TWO))]
        sequence = PlaySequence(targets=rows)  # type: ignore[arg-type]
        rows.clear()
        self.assertIsInstance(sequence.targets, tuple)
        self.assertEqual([str(item.path) for item in sequence.targets], [SESSION_ONE, SESSION_TWO])

        # A generator can be read once; the snapshot has to survive a second look.
        one_shot = (PlayTarget(path=Path(item)) for item in (SESSION_ONE, SESSION_TWO))
        lazily = PlaySequence(targets=one_shot)  # type: ignore[arg-type]
        self.assertEqual(len(lazily.targets), 2)
        self.assertEqual(len(lazily.targets), 2)

    def test_loose_values_are_tidied_once_at_construction(self) -> None:
        loose: dict[str, object] = {
            "path": SESSION_ONE,
            "package_root": "Q:/Packages/synthetic",
            "start_seconds": "41.5",
        }
        target = PlayTarget(**loose)  # type: ignore[arg-type]
        self.assertIsInstance(target.path, Path)
        self.assertEqual(target.path, Path(SESSION_ONE))
        self.assertIsInstance(target.package_root, Path)
        self.assertEqual(target.start_seconds, 41.5)

        no_package: object = ""
        self.assertIsNone(PlayTarget(path=Path(SESSION_ONE), package_root=no_package).package_root)  # type: ignore[arg-type]
        for value in (None, "soon", -3, float("nan"), float("inf")):
            with self.subTest(value=value):
                target = PlayTarget(path=Path(SESSION_ONE), start_seconds=value)  # type: ignore[arg-type]
                self.assertEqual(target.start_seconds, 0.0)


class StandInTests(unittest.TestCase):
    """A file that plays in a recording's place, and a file that is no recording at all."""

    def test_a_recording_is_its_own_recording(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE))
        self.assertIsNone(target.stands_in_for)
        self.assertEqual(target.recording_path, Path(SESSION_ONE))
        self.assertFalse(target.is_package_file)

    def test_a_stand_in_names_the_recording_it_plays_for(self) -> None:
        target = PlayTarget(path=Path(REVIEW_COPY), package_root=Path(PACKAGE), stands_in_for=Path(SESSION_ONE))
        # The copy is what plays...
        self.assertEqual(target.path, Path(REVIEW_COPY))
        # ...and the recording is what never-use, skip and the transcript are
        # about. The copy's own path must never reach the never-use list.
        self.assertEqual(target.recording_path, Path(SESSION_ONE))
        # It sits inside a package folder, but it knows its recording, so it
        # is not treated as a file that has none.
        self.assertFalse(target.is_package_file)

    def test_a_clip_inside_a_package_folder_is_a_package_file(self) -> None:
        clip = PlayTarget(path=Path(PACKAGE) / "clips" / "synthetic-clip-001.mp4")
        self.assertTrue(clip.is_package_file)
        self.assertEqual(clip.recording_path, clip.path)
        # A copy opened straight from the package, with nothing said about
        # which recording it is a copy of, is no different from a clip.
        self.assertTrue(PlayTarget(path=Path(REVIEW_COPY)).is_package_file)
        # Windows does not care about the case of a folder name.
        self.assertTrue(PlayTarget(path=Path(PACKAGE.upper()) / "clips" / "synthetic-clip-001.mp4").is_package_file)

    def test_a_clip_inside_a_renamed_package_is_known_by_the_package_it_came_with(self) -> None:
        # A package that was unzipped or renamed has another folder name, so
        # the name alone would let its clips pass as the operator's recordings.
        renamed = Path(r"Q:\Unzipped\synthetic-package-from-friday")
        clip = PlayTarget(path=renamed / "clips" / "synthetic-clip-001.mp4", package_root=renamed)
        self.assertTrue(clip.is_package_file)
        # Case does not matter, and the package folder itself is not "inside" it.
        self.assertTrue(
            PlayTarget(path=Path(str(renamed).upper()) / "a.mp4", package_root=renamed).is_package_file
        )
        self.assertFalse(PlayTarget(path=renamed, package_root=renamed).is_package_file)
        # A recording played WITH a package (so its transcript is found) lives
        # elsewhere, and is still one of the operator's recordings.
        self.assertFalse(PlayTarget(path=Path(SESSION_ONE), package_root=renamed).is_package_file)
        # A folder that merely starts with the same letters is another folder.
        self.assertFalse(
            PlayTarget(path=Path(str(renamed) + "-notes") / "a.mp4", package_root=renamed).is_package_file
        )

    def test_a_recording_elsewhere_is_not_a_package_file(self) -> None:
        for path in (
            SESSION_ONE,
            # The whole folder name, not a piece of one.
            r"Q:\Reviews\codex-evidence-package-notes\synthetic-session-one.mkv",
            r"Q:\Reviews\my-codex-evidence-package\synthetic-session-one.mkv",
            r"Q:\Reviews\synthetic-run\codex-evidence-package.mkv",
        ):
            with self.subTest(path=path):
                self.assertFalse(PlayTarget(path=Path(path)).is_package_file)

    def test_the_stand_in_is_tidied_like_the_other_paths_and_is_frozen(self) -> None:
        loose: object = SESSION_ONE
        target = PlayTarget(path=Path(REVIEW_COPY), stands_in_for=loose)  # type: ignore[arg-type]
        self.assertIsInstance(target.stands_in_for, Path)
        self.assertEqual(target.stands_in_for, Path(SESSION_ONE))
        with self.assertRaises(FrozenInstanceError):
            target.stands_in_for = Path(SESSION_TWO)  # type: ignore[misc]

        nothing: object = ""
        blank = PlayTarget(path=Path(REVIEW_COPY), stands_in_for=nothing)  # type: ignore[arg-type]
        self.assertIsNone(blank.stands_in_for)
        self.assertEqual(blank.recording_path, Path(REVIEW_COPY))

    def test_a_stand_in_is_a_different_target_from_the_recording_and_from_the_bare_copy(self) -> None:
        stand_in = PlayTarget(path=Path(REVIEW_COPY), stands_in_for=Path(SESSION_ONE))
        self.assertNotEqual(stand_in, PlayTarget(path=Path(REVIEW_COPY)))
        self.assertNotEqual(stand_in, PlayTarget(path=Path(SESSION_ONE)))
        self.assertEqual(stand_in, PlayTarget(path=Path(REVIEW_COPY), stands_in_for=Path(SESSION_ONE)))


class OpenedAtTests(unittest.TestCase):
    """Where in its own frozen list a recording was opened."""

    def test_a_list_starts_at_its_first_row(self) -> None:
        self.assertEqual(_sequence(SESSION_ONE, SESSION_TWO).opened_at, 0)
        self.assertEqual(PlaySequence(targets=()).opened_at, 0)

    def test_the_place_is_kept_and_is_frozen(self) -> None:
        sequence = PlaySequence(targets=_sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE).targets, opened_at=2)
        self.assertEqual(sequence.opened_at, 2)
        with self.assertRaises(FrozenInstanceError):
            sequence.opened_at = 0  # type: ignore[misc]

    def test_a_place_before_the_list_is_its_first_row(self) -> None:
        for value in (-1, -300):
            with self.subTest(value=value):
                self.assertEqual(PlaySequence(targets=(), opened_at=value).opened_at, 0)

    def test_junk_is_the_first_row_and_never_an_error(self) -> None:
        for value in (None, "", "soon", [], {}, object(), float("nan")):
            with self.subTest(value=value):
                self.assertEqual(PlaySequence(targets=(), opened_at=value).opened_at, 0)  # type: ignore[arg-type]
        # A number too large to be a whole number at all is junk too, not a crash.
        self.assertEqual(PlaySequence(targets=(), opened_at=float("inf")).opened_at, 0)  # type: ignore[arg-type]
        # A number that arrived as text, or with a fraction, is still a number.
        targets = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE).targets
        self.assertEqual(PlaySequence(targets=targets, opened_at="2").opened_at, 2)  # type: ignore[arg-type]
        self.assertEqual(PlaySequence(targets=targets, opened_at=1.9).opened_at, 1)  # type: ignore[arg-type]
        # With nothing in the list there is only one place it can be.
        self.assertEqual(PlaySequence(targets=(), opened_at=2).opened_at, 0)

    def test_a_place_beyond_the_list_becomes_the_last_row_and_nothing_raises(self) -> None:
        # The player calls opened_on() from a Qt slot on every open, where an
        # IndexError would surface as a crash, so the place is kept inside the list.
        targets = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE).targets
        sequence = PlaySequence(targets=targets, opened_at=99)
        self.assertEqual(sequence.opened_at, 2)
        self.assertIs(sequence.opened_on(PlayTarget(path=Path(NOT_IN_LIST))), sequence)
        self.assertEqual(sequence.opened_on(PlayTarget(path=Path(SESSION_ONE))).opened_at, 0)
        target, reason = next_target(sequence, SESSION_ONE, set())
        self.assertEqual((target.path, reason), (Path(SESSION_TWO), "next"))
        self.assertEqual(next_target(sequence, SESSION_THREE, set()), (None, "end_of_list"))
        self.assertEqual(next_target(sequence, NOT_IN_LIST, set()), (None, "no_list"))

    def test_lists_that_differ_only_in_the_opened_row_are_different_lists(self) -> None:
        targets = _sequence(SESSION_ONE, SESSION_TWO).targets
        self.assertNotEqual(PlaySequence(targets=targets, opened_at=0), PlaySequence(targets=targets, opened_at=1))
        self.assertEqual(PlaySequence(targets=targets, opened_at=1), PlaySequence(targets=targets, opened_at=1))


class OpenedOnTests(unittest.TestCase):
    def test_the_same_list_with_the_new_place(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE, label="Synthetic list")
        moved_on = sequence.opened_on(PlayTarget(path=Path(SESSION_THREE)))
        self.assertEqual(moved_on.opened_at, 2)
        self.assertIs(moved_on.targets, sequence.targets)
        self.assertEqual(moved_on.label, "Synthetic list")
        # The list it was made from is frozen, and is left as it was.
        self.assertEqual(sequence.opened_at, 0)

    def test_it_searches_forward_from_the_current_place_first(self) -> None:
        # One recording on rows 1 and 3, the way History shows it.
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_ONE, SESSION_THREE)
        one = PlayTarget(path=Path(SESSION_ONE))
        self.assertEqual(sequence.opened_on(one).opened_at, 0)
        at_two = PlaySequence(targets=sequence.targets, opened_at=1)
        # From row 2 the nearest row of that recording BELOW is row 3, and
        # the list only ever moves down.
        self.assertEqual(at_two.opened_on(one).opened_at, 2)
        # Already standing on a row of it: it stays there.
        at_three = PlaySequence(targets=sequence.targets, opened_at=2)
        self.assertEqual(at_three.opened_on(one).opened_at, 2)

    def test_it_falls_back_to_a_row_above_for_something_opened_out_of_order(self) -> None:
        sequence = PlaySequence(targets=_sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE).targets, opened_at=2)
        self.assertEqual(sequence.opened_on(PlayTarget(path=Path(SESSION_ONE))).opened_at, 0)

    def test_a_recording_that_is_not_in_the_list_leaves_the_list_as_it_is(self) -> None:
        sequence = PlaySequence(targets=_sequence(SESSION_ONE, SESSION_TWO).targets, opened_at=1)
        self.assertIs(sequence.opened_on(PlayTarget(path=Path(NOT_IN_LIST))), sequence)

    def test_case_does_not_matter_and_a_stand_in_is_found_by_its_recording(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        self.assertEqual(sequence.opened_on(PlayTarget(path=Path(SESSION_TWO.upper()))).opened_at, 1)
        stand_in = PlayTarget(path=Path(REVIEW_COPY), stands_in_for=Path(SESSION_THREE))
        self.assertEqual(sequence.opened_on(stand_in).opened_at, 2)
        # The copy on its own is no row of this list.
        self.assertIs(sequence.opened_on(PlayTarget(path=Path(REVIEW_COPY))), sequence)


class BuildVlcCommandTests(unittest.TestCase):
    VLC = VLC_IN_PROGRAM_FILES

    def test_from_the_start_and_playing(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE))
        self.assertEqual(build_vlc_command(self.VLC, target, autoplay=True), [self.VLC, str(Path(SESSION_ONE))])

    def test_from_the_start_and_paused(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE))
        self.assertEqual(
            build_vlc_command(self.VLC, target, autoplay=False),
            [self.VLC, "--start-paused", str(Path(SESSION_ONE))],
        )

    def test_at_a_moment_and_playing(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE), start_seconds=2467.25)
        self.assertEqual(
            build_vlc_command(self.VLC, target, autoplay=True),
            [self.VLC, "--start-time=2467.250", str(Path(SESSION_ONE))],
        )

    def test_at_a_moment_and_paused(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE), start_seconds=90)
        self.assertEqual(
            build_vlc_command(self.VLC, target, autoplay=False),
            [self.VLC, "--start-time=90.000", "--start-paused", str(Path(SESSION_ONE))],
        )

    def test_start_time_is_written_to_the_millisecond(self) -> None:
        target = PlayTarget(path=Path(SESSION_ONE), start_seconds=1.23456)
        self.assertEqual(build_vlc_command(self.VLC, target, autoplay=True)[1], "--start-time=1.235")

    def test_a_start_that_is_not_after_zero_adds_nothing(self) -> None:
        for value in (0, 0.0, -5.0, float("nan"), float("inf")):
            with self.subTest(value=value):
                target = PlayTarget(path=Path(SESSION_ONE), start_seconds=value)
                self.assertEqual(
                    build_vlc_command(self.VLC, target, autoplay=True),
                    [self.VLC, str(Path(SESSION_ONE))],
                )

    def test_the_recording_is_always_the_last_argument_and_one_argument(self) -> None:
        # The folder name has a space in it: it must stay one list entry and
        # never be quoted by hand, because the list goes to Popen as it is.
        command = build_vlc_command(self.VLC, PlayTarget(path=Path(SESSION_TWO), start_seconds=5), autoplay=False)
        self.assertEqual(command[-1], str(Path(SESSION_TWO)))
        self.assertTrue(all(isinstance(item, str) for item in command))
        self.assertNotIn('"', "".join(command))


class _Probe:
    """Injected stand-ins for PATH, the file system and the registry."""

    def __init__(self, *, on_path=None, files=(), registry: str = "") -> None:
        self.on_path = dict(on_path or {})
        self.files = set(files)
        self.registry = registry
        self.calls: list[tuple[str, str]] = []

    def which(self, name: str) -> str | None:
        self.calls.append(("which", name))
        return self.on_path.get(name)

    def exists(self, path: str) -> bool:
        self.calls.append(("exists", path))
        return path in self.files

    def registry_install_dir(self) -> str:
        self.calls.append(("registry", ""))
        return self.registry

    def find(self, configured: str = "", *, environ=None, platform: str = "win32") -> str:
        return find_vlc(
            configured,
            which=self.which,
            exists=self.exists,
            environ=WINDOWS_ENVIRON if environ is None else environ,
            registry_install_dir=self.registry_install_dir,
            platform=platform,
        )


class FindVlcTests(unittest.TestCase):
    CONFIGURED = r"V:\Portable Tools\vlc\vlc.exe"

    def test_the_configured_path_wins_and_nothing_else_is_looked_at(self) -> None:
        probe = _Probe(
            on_path={"vlc.exe": r"P:\OnPath\vlc.exe"},
            files={self.CONFIGURED, VLC_IN_PROGRAM_FILES},
            registry=r"R:\Registered\VLC",
        )
        self.assertEqual(probe.find(self.CONFIGURED), self.CONFIGURED)
        self.assertEqual(probe.calls, [("exists", self.CONFIGURED)])

    def test_a_configured_path_pasted_with_quotes_and_spaces_still_works(self) -> None:
        probe = _Probe(files={self.CONFIGURED})
        self.assertEqual(probe.find(f'  "{self.CONFIGURED}" '), self.CONFIGURED)

    def test_a_configured_path_that_is_gone_falls_back_to_looking(self) -> None:
        probe = _Probe(on_path={"vlc.exe": r"P:\OnPath\vlc.exe"})
        self.assertEqual(probe.find(self.CONFIGURED), r"P:\OnPath\vlc.exe")
        self.assertEqual(probe.calls[:2], [("exists", self.CONFIGURED), ("which", "vlc.exe")])

    def test_a_blank_configured_path_is_never_checked(self) -> None:
        for blank in ("", "   ", '""', None):
            with self.subTest(blank=blank):
                probe = _Probe()
                self.assertEqual(probe.find(blank), "")  # type: ignore[arg-type]
                self.assertNotIn(("exists", ""), probe.calls)

    def test_path_is_asked_for_vlc_exe_first_then_vlc(self) -> None:
        probe = _Probe(on_path={"vlc.exe": r"P:\OnPath\vlc.exe", "vlc": r"P:\OnPath\vlc"})
        self.assertEqual(probe.find(), r"P:\OnPath\vlc.exe")
        self.assertEqual(probe.calls, [("which", "vlc.exe")])

        probe = _Probe(on_path={"vlc": r"P:\OnPath\vlc"})
        self.assertEqual(probe.find(), r"P:\OnPath\vlc")
        self.assertEqual(probe.calls, [("which", "vlc.exe"), ("which", "vlc")])

    def test_path_beats_the_install_folders_and_the_registry(self) -> None:
        probe = _Probe(
            on_path={"vlc.exe": r"P:\OnPath\vlc.exe"},
            files={VLC_IN_PROGRAM_FILES, r"R:\Registered\VLC\vlc.exe"},
            registry=r"R:\Registered\VLC",
        )
        self.assertEqual(probe.find(), r"P:\OnPath\vlc.exe")
        self.assertNotIn(("registry", ""), probe.calls)

    def test_program_files_is_checked_before_program_files_x86(self) -> None:
        probe = _Probe(files={VLC_IN_PROGRAM_FILES, VLC_IN_PROGRAM_FILES_X86})
        self.assertEqual(probe.find(), VLC_IN_PROGRAM_FILES)
        self.assertNotIn(("exists", VLC_IN_PROGRAM_FILES_X86), probe.calls)

        probe = _Probe(files={VLC_IN_PROGRAM_FILES_X86})
        self.assertEqual(probe.find(), VLC_IN_PROGRAM_FILES_X86)
        self.assertEqual(
            probe.calls,
            [
                ("which", "vlc.exe"),
                ("which", "vlc"),
                ("exists", VLC_IN_PROGRAM_FILES),
                ("exists", VLC_IN_PROGRAM_FILES_X86),
            ],
        )

    def test_the_registry_is_the_last_place_looked(self) -> None:
        registered = r"R:\Registered\VLC\vlc.exe"
        probe = _Probe(files={registered}, registry=r"R:\Registered\VLC")
        self.assertEqual(probe.find(), registered)
        self.assertEqual(
            probe.calls,
            [
                ("which", "vlc.exe"),
                ("which", "vlc"),
                ("exists", VLC_IN_PROGRAM_FILES),
                ("exists", VLC_IN_PROGRAM_FILES_X86),
                ("registry", ""),
                ("exists", registered),
            ],
        )

    def test_a_registry_folder_with_a_trailing_slash_is_joined_once(self) -> None:
        registered = r"R:\Registered\VLC\vlc.exe"
        for folder in ("R:\\Registered\\VLC\\", "R:\\Registered\\VLC/", "  R:\\Registered\\VLC  "):
            with self.subTest(folder=folder):
                probe = _Probe(files={registered}, registry=folder)
                self.assertEqual(probe.find(), registered)

    def test_a_registry_folder_without_vlc_in_it_is_not_returned(self) -> None:
        probe = _Probe(registry=r"R:\Registered\VLC")
        self.assertEqual(probe.find(), "")
        self.assertIn(("exists", r"R:\Registered\VLC\vlc.exe"), probe.calls)

    def test_a_blank_registry_answer_checks_nothing(self) -> None:
        for answer in ("", "   ", None):
            with self.subTest(answer=answer):
                probe = _Probe(registry=answer)  # type: ignore[arg-type]
                self.assertEqual(probe.find(), "")
                self.assertNotIn(("exists", r"\vlc.exe"), probe.calls)
                self.assertEqual(probe.calls[-1], ("registry", ""))

    def test_missing_program_files_variables_are_skipped(self) -> None:
        registered = r"R:\Registered\VLC\vlc.exe"
        probe = _Probe(files={registered}, registry=r"R:\Registered\VLC")
        self.assertEqual(probe.find(environ={}), registered)
        self.assertEqual(
            probe.calls,
            [("which", "vlc.exe"), ("which", "vlc"), ("registry", ""), ("exists", registered)],
        )

    def test_nothing_anywhere_gives_an_empty_string(self) -> None:
        for platform in ("win32", "darwin", "linux"):
            with self.subTest(platform=platform):
                self.assertEqual(_Probe().find(platform=platform, environ={}), "")

    def test_the_built_in_registry_lookup_is_used_when_none_is_passed(self) -> None:
        registered = r"R:\Registered\VLC\vlc.exe"
        with patch.object(play_targets, "_vlc_registry_install_dir", return_value=r"R:\Registered\VLC") as lookup:
            found = find_vlc(
                which=lambda name: None,
                exists=lambda path: path == registered,
                environ={},
                platform="win32",
            )
        self.assertEqual(found, registered)
        lookup.assert_called_once_with()

    def test_the_real_environment_is_read_when_none_is_passed(self) -> None:
        with patch.dict(os.environ, {"ProgramFiles": r"P:\Apps"}):
            found = find_vlc(
                which=lambda name: None,
                exists=lambda path: path == VLC_IN_PROGRAM_FILES,
                registry_install_dir=lambda: "",
                platform="win32",
            )
        self.assertEqual(found, VLC_IN_PROGRAM_FILES)

    def test_mac_checks_the_shared_applications_folder_then_the_personal_one(self) -> None:
        environ = {"HOME": "/Users/synthetic"}
        probe = _Probe(files={VLC_MAC_SYSTEM, VLC_MAC_USER})
        self.assertEqual(probe.find(environ=environ, platform="darwin"), VLC_MAC_SYSTEM)

        probe = _Probe(files={VLC_MAC_USER})
        self.assertEqual(probe.find(environ=environ, platform="darwin"), VLC_MAC_USER)
        self.assertEqual(
            probe.calls,
            [("which", "vlc"), ("exists", VLC_MAC_SYSTEM), ("exists", VLC_MAC_USER)],
        )

    def test_mac_without_a_home_folder_checks_only_the_shared_one(self) -> None:
        probe = _Probe()
        self.assertEqual(probe.find(environ={}, platform="darwin"), "")
        self.assertEqual(probe.calls, [("which", "vlc"), ("exists", VLC_MAC_SYSTEM)])

    def test_the_registry_and_windows_folders_are_windows_only(self) -> None:
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform):
                probe = _Probe(
                    files={VLC_IN_PROGRAM_FILES, r"R:\Registered\VLC\vlc.exe"},
                    registry=r"R:\Registered\VLC",
                )
                self.assertEqual(probe.find(platform=platform), "")
                self.assertNotIn(("registry", ""), probe.calls)
                self.assertNotIn(("exists", VLC_IN_PROGRAM_FILES), probe.calls)
                self.assertNotIn(("which", "vlc.exe"), probe.calls)

    def test_other_systems_rely_on_path_alone(self) -> None:
        probe = _Probe(on_path={"vlc": "/usr/bin/vlc"})
        self.assertEqual(probe.find(platform="linux", environ={}), "/usr/bin/vlc")
        self.assertEqual(probe.calls, [("which", "vlc")])


class _FakeKey:
    def __init__(self, value: object) -> None:
        self.value = value
        self.closed = False

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.closed = True
        return False


class _FakeWinreg:
    """The few names ``_vlc_registry_install_dir`` uses, with no real registry behind them."""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x0100
    KEY_WOW64_32KEY = 0x0200

    def __init__(self, values: dict[tuple[str, int], object], *, error: BaseException | None = None) -> None:
        self.values = values
        self.error = error
        self.opened: list[tuple[str, str, int]] = []
        self.queried: list[str] = []
        self.keys: list[_FakeKey] = []

    def OpenKey(self, hive: str, sub_key: str, reserved: int, access: int) -> _FakeKey:  # noqa: N802
        view = access & (self.KEY_WOW64_64KEY | self.KEY_WOW64_32KEY)
        self.opened.append((hive, sub_key, view))
        if self.error is not None:
            raise self.error
        if access & self.KEY_READ != self.KEY_READ or reserved != 0:
            raise AssertionError("the key must be opened read-only")
        if (hive, view) not in self.values:
            raise FileNotFoundError(sub_key)
        key = _FakeKey(self.values[(hive, view)])
        self.keys.append(key)
        return key

    def QueryValueEx(self, key: _FakeKey, name: str) -> tuple[object, int]:  # noqa: N802
        self.queried.append(name)
        if isinstance(key.value, BaseException):
            raise key.value
        return key.value, 1


class VlcRegistryLookupTests(unittest.TestCase):
    KEY = r"SOFTWARE\VideoLAN\VLC"

    def _lookup(self, fake: object) -> str:
        with patch.object(play_targets, "winreg", fake):
            return play_targets._vlc_registry_install_dir()

    def test_machine_wide_64_bit_entry_is_read_first(self) -> None:
        fake = _FakeWinreg(
            {
                ("HKLM", _FakeWinreg.KEY_WOW64_64KEY): r"R:\Registered\VLC",
                ("HKCU", _FakeWinreg.KEY_WOW64_32KEY): r"R:\Personal\VLC",
            }
        )
        self.assertEqual(self._lookup(fake), r"R:\Registered\VLC")
        self.assertEqual(fake.opened, [("HKLM", self.KEY, _FakeWinreg.KEY_WOW64_64KEY)])
        self.assertEqual(fake.queried, ["InstallDir"])
        self.assertTrue(all(key.closed for key in fake.keys))

    def test_both_hives_and_both_views_are_tried_in_order(self) -> None:
        fake = _FakeWinreg({("HKCU", _FakeWinreg.KEY_WOW64_32KEY): r"R:\Personal\VLC"})
        self.assertEqual(self._lookup(fake), r"R:\Personal\VLC")
        self.assertEqual(
            fake.opened,
            [
                ("HKLM", self.KEY, _FakeWinreg.KEY_WOW64_64KEY),
                ("HKLM", self.KEY, _FakeWinreg.KEY_WOW64_32KEY),
                ("HKCU", self.KEY, _FakeWinreg.KEY_WOW64_64KEY),
                ("HKCU", self.KEY, _FakeWinreg.KEY_WOW64_32KEY),
            ],
        )

    def test_a_blank_or_unreadable_entry_does_not_hide_a_later_one(self) -> None:
        fake = _FakeWinreg(
            {
                ("HKLM", _FakeWinreg.KEY_WOW64_64KEY): "   ",
                ("HKLM", _FakeWinreg.KEY_WOW64_32KEY): FileNotFoundError("InstallDir"),
                ("HKCU", _FakeWinreg.KEY_WOW64_64KEY): None,
                ("HKCU", _FakeWinreg.KEY_WOW64_32KEY): r"  R:\Personal\VLC  ",
            }
        )
        self.assertEqual(self._lookup(fake), r"R:\Personal\VLC")

    def test_vlc_not_registered_gives_an_empty_string(self) -> None:
        fake = _FakeWinreg({})
        self.assertEqual(self._lookup(fake), "")
        self.assertEqual(len(fake.opened), 4)

    def test_any_failure_gives_an_empty_string(self) -> None:
        for error in (PermissionError("denied"), RuntimeError("unexpected"), ValueError("odd value")):
            with self.subTest(error=error):
                self.assertEqual(self._lookup(_FakeWinreg({}, error=error)), "")
        # A registry module missing the names this relies on is a failure too.
        self.assertEqual(self._lookup(object()), "")

    def test_no_registry_module_gives_an_empty_string(self) -> None:
        self.assertEqual(self._lookup(None), "")


class NextTargetTests(unittest.TestCase):
    def test_the_next_recording_in_the_list(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        target, reason = next_target(sequence, SESSION_ONE, set())
        self.assertEqual(reason, "next")
        self.assertIs(target, sequence.targets[1])

    def test_position_is_found_by_path_not_by_index(self) -> None:
        # The player was opened on the third row.  A caller that tracked "row 0"
        # would be handed the second recording; the path says the fourth.
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE, SESSION_FOUR)
        target, reason = next_target(sequence, Path(SESSION_THREE), set())
        self.assertEqual(reason, "next")
        self.assertEqual(target.path, Path(SESSION_FOUR))

        # The same snapshot still answers correctly after the rows it came from
        # were rebuilt in another order: only the snapshot's own order counts.
        reordered = _sequence(SESSION_FOUR, SESSION_THREE, SESSION_TWO, SESSION_ONE)
        target, reason = next_target(reordered, Path(SESSION_THREE), set())
        self.assertEqual(target.path, Path(SESSION_TWO))

    def test_differing_case_is_the_same_recording(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        target, reason = next_target(sequence, SESSION_ONE.upper(), set())
        self.assertEqual(reason, "next")
        self.assertEqual(target.path, Path(SESSION_TWO))

        shouting = _sequence(SESSION_ONE.upper(), SESSION_TWO.upper(), SESSION_THREE)
        target, reason = next_target(shouting, SESSION_ONE.lower(), {path_key(SESSION_TWO)})
        self.assertEqual(reason, "next")
        self.assertEqual(target.path, Path(SESSION_THREE))

    def test_no_sequence_is_no_list(self) -> None:
        self.assertEqual(next_target(None, SESSION_ONE, set()), (None, "no_list"))

    def test_a_single_target_is_no_list(self) -> None:
        self.assertEqual(next_target(_sequence(SESSION_ONE), SESSION_ONE, set()), (None, "no_list"))
        self.assertEqual(next_target(PlaySequence(targets=()), SESSION_ONE, set()), (None, "no_list"))

    def test_current_absent_is_no_list(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO)
        self.assertEqual(next_target(sequence, NOT_IN_LIST, set()), (None, "no_list"))
        self.assertEqual(next_target(sequence, "", set()), (None, "no_list"))

    def test_the_last_recording_is_the_end_of_the_list(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        self.assertEqual(next_target(sequence, SESSION_THREE, set()), (None, "end_of_list"))

    def test_there_is_no_wrap_around(self) -> None:
        # Everything before the current recording is still allowed, and is
        # still never offered.
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        self.assertEqual(next_target(sequence, SESSION_THREE, {path_key(SESSION_THREE)}), (None, "end_of_list"))

    def test_excluded_recordings_are_skipped(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE, SESSION_FOUR)
        excluded = {path_key(SESSION_ONE), path_key(SESSION_TWO), path_key(SESSION_THREE)}
        target, reason = next_target(sequence, SESSION_ONE, excluded)
        self.assertEqual(reason, "next")
        self.assertEqual(target.path, Path(SESSION_FOUR))

    def test_everything_after_being_excluded_is_the_end_of_the_list(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE, SESSION_FOUR)
        excluded = {path_key(SESSION_THREE), path_key(SESSION_FOUR)}
        self.assertEqual(next_target(sequence, SESSION_TWO, excluded), (None, "end_of_list"))

    def test_excluded_may_be_paths_as_stored_rather_than_keys(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        target, reason = next_target(sequence, SESSION_ONE, {SESSION_TWO.upper()})
        self.assertEqual(reason, "next")
        self.assertEqual(target.path, Path(SESSION_THREE))

    def test_another_row_of_the_same_recording_is_not_next(self) -> None:
        moments = PlaySequence(
            targets=(
                PlayTarget(path=Path(SESSION_ONE), start_seconds=10),
                PlayTarget(path=Path(SESSION_ONE), start_seconds=95),
                PlayTarget(path=Path(SESSION_TWO), start_seconds=4),
            )
        )
        target, reason = next_target(moments, SESSION_ONE, set())
        self.assertEqual(reason, "next")
        self.assertEqual(target.path, Path(SESSION_TWO))
        self.assertEqual(target.start_seconds, 4.0)

        only_one_recording = PlaySequence(targets=moments.targets[:2])
        self.assertEqual(next_target(only_one_recording, SESSION_ONE, set()), (None, "end_of_list"))

    def test_next_goes_on_from_the_row_that_was_opened_not_the_first_row_showing_the_recording(self) -> None:
        # History has one row per run, so one recording is on rows 1 and 3.
        rows = _sequence(SESSION_ONE, SESSION_TWO, SESSION_ONE, SESSION_FOUR).targets

        opened_from_row_three = PlaySequence(targets=rows, opened_at=2)
        target, reason = next_target(opened_from_row_three, SESSION_ONE, set())
        self.assertEqual((target.path, reason), (Path(SESSION_FOUR), "next"))

        # Opened from row 1, the same recording moves on to row 2 as before.
        opened_from_row_one = PlaySequence(targets=rows, opened_at=0)
        target, reason = next_target(opened_from_row_one, SESSION_ONE, set())
        self.assertEqual((target.path, reason), (Path(SESSION_TWO), "next"))

    def test_the_last_row_is_the_end_of_the_list_even_when_the_recording_is_on_an_earlier_row_too(self) -> None:
        rows = _sequence(SESSION_ONE, SESSION_TWO, SESSION_ONE).targets
        # Found by path alone this went back to row 2 and never said "last".
        opened_from_the_last_row = PlaySequence(targets=rows, opened_at=2)
        self.assertEqual(next_target(opened_from_the_last_row, SESSION_ONE, set()), (None, "end_of_list"))

    def test_an_opened_row_that_names_something_else_is_searched_from_not_trusted(self) -> None:
        rows = _sequence(SESSION_ONE, SESSION_TWO, SESSION_ONE, SESSION_FOUR).targets
        # The row says recording two; the player says it has recording one
        # open. The first row of recording one AT OR AFTER the opened row is used.
        target, _reason = next_target(PlaySequence(targets=rows, opened_at=1), SESSION_ONE, set())
        self.assertEqual(target.path, Path(SESSION_FOUR))
        # And when there is none below, a row above is better than "no list":
        # recording two is on row 2, and what follows row 2 is row 3.
        target, reason = next_target(PlaySequence(targets=rows, opened_at=3), SESSION_TWO, set())
        self.assertEqual((target, reason), (rows[2], "next"))

    def test_an_opened_row_beyond_the_list_is_tolerated(self) -> None:
        rows = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE).targets
        for opened_at in (3, 4, 10_000):
            with self.subTest(opened_at=opened_at):
                target, reason = next_target(PlaySequence(targets=rows, opened_at=opened_at), SESSION_TWO, set())
                self.assertEqual((target.path, reason), (Path(SESSION_THREE), "next"))

    def test_a_stand_in_moves_on_like_the_recording_it_plays_for(self) -> None:
        # The player has the small review copy open; the list holds the recordings.
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        stand_in = PlayTarget(path=Path(REVIEW_COPY), stands_in_for=Path(SESSION_TWO))
        target, reason = next_target(sequence, stand_in.recording_path, set())
        self.assertEqual((target.path, reason), (Path(SESSION_THREE), "next"))
        # Asked about by its own path, the copy is in no list at all.
        self.assertEqual(next_target(sequence, stand_in.path, set()), (None, "no_list"))

    def test_a_list_that_holds_a_stand_in_compares_it_by_its_recording(self) -> None:
        held = PlaySequence(
            targets=(
                PlayTarget(path=Path(SESSION_ONE)),
                PlayTarget(path=Path(REVIEW_COPY), stands_in_for=Path(SESSION_TWO)),
                PlayTarget(path=Path(SESSION_THREE)),
            )
        )
        # Its place is found by the recording...
        target, reason = next_target(held, SESSION_TWO, set())
        self.assertEqual((target.path, reason), (Path(SESSION_THREE), "next"))
        # ...it is what comes after recording one, copy and all...
        target, _reason = next_target(held, SESSION_ONE, set())
        self.assertEqual((target.path, target.stands_in_for), (Path(REVIEW_COPY), Path(SESSION_TWO)))
        # ...and marking the RECORDING never-use is what skips it.
        target, _reason = next_target(held, SESSION_ONE, {path_key(SESSION_TWO)})
        self.assertEqual(target.path, Path(SESSION_THREE))
        target, _reason = next_target(held, SESSION_ONE, {path_key(REVIEW_COPY)})
        self.assertEqual(target.path, Path(REVIEW_COPY))

    def test_the_sequence_and_the_excluded_set_are_left_alone(self) -> None:
        sequence = _sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        before = sequence.targets
        excluded = {path_key(SESSION_TWO)}
        next_target(sequence, SESSION_ONE, excluded)
        self.assertIs(sequence.targets, before)
        self.assertEqual(excluded, {path_key(SESSION_TWO)})

    def test_the_target_that_comes_back_keeps_its_details(self) -> None:
        package = Path(r"Q:\Packages\synthetic-package")
        sequence = PlaySequence(
            targets=(
                PlayTarget(path=Path(SESSION_ONE)),
                PlayTarget(path=Path(SESSION_TWO), start_seconds=30, package_root=package, label="Two", voice_track=3),
            ),
            label="Find my bug reports list",
        )
        target, _reason = next_target(sequence, SESSION_ONE, set())
        self.assertEqual(target.package_root, package)
        self.assertEqual(target.label, "Two")
        self.assertEqual(target.voice_track, 3)
        self.assertEqual(target.start_seconds, 30.0)


class ModuleBoundaryTests(unittest.TestCase):
    """The import graph in the plan: pure, and only leaf modules underneath."""

    @classmethod
    def setUpClass(cls) -> None:
        source = (REPO_ROOT / "src" / "media_manglers_workbench" / "play_targets.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(source)

    def _imports(self, nodes) -> tuple[set[str], set[str]]:
        absolute: set[str] = set()
        relative: set[str] = set()
        for node in nodes:
            if isinstance(node, ast.Import):
                absolute.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative.add(node.module or "")
                else:
                    absolute.add((node.module or "").split(".")[0])
        return absolute, relative

    def test_no_qt_and_nothing_that_could_start_a_program(self) -> None:
        absolute, _relative = self._imports(ast.walk(self.tree))
        self.assertFalse({"PySide6", "shiboken6", "subprocess"} & absolute)
        self.assertTrue(absolute <= set(sys.stdlib_module_names) | {"__future__"}, absolute)

    def test_project_imports_are_the_two_leaf_modules(self) -> None:
        _absolute, relative = self._imports(ast.walk(self.tree))
        self.assertEqual(relative, {"audio_detection", "recording_lists"})

    def test_every_import_is_at_module_top(self) -> None:
        # A function-local import of a project module escapes the packaged build.
        nested = [
            node
            for holder in ast.walk(self.tree)
            if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in ast.walk(holder)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertEqual(nested, [])


if __name__ == "__main__":
    unittest.main()
