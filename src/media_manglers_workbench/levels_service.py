"""Waveforms for the built-in player, measured one recording at a time in the background (125, 135).

The player asks for the levels of the recording it has open; a finished run hands over its
recordings so they are ready before anyone opens them. Looking a recording up (the cache, the raw bin
library) runs off the screen's thread, because the file's size and time are read from a drive that
may be asleep. Measuring runs the ``track-levels`` helper at low priority on a runner of its own.

It is cache work, not a run, so it is not on Queue / Progress or in History (the stated reason is in
the project truth). It never starts while a run is going; a run starting stops it, keeping what it
measured, and it carries on when the app is idle again. Closing the app stops it at once and never
refuses the close. With no runner factory (the test suite) it does nothing at all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from media_manglers.core import app_cache, track_levels
from media_manglers.core.scratch import scratch_root
from media_manglers.core.track_levels import Levels
from media_manglers.core.user_folders import recordings_folders

from .ai_video_editor import cli_command
from .recording_lists import path_key
from .run_control import RunControl

# Measuring waits this long after the player's last seek before it reads the drive again.
HOLD_AFTER_SEEK_MS = 3000
# A stop asked of the helper saves what it measured at once and ends it; a helper still there this
# much later is ended hard. Closing waits for the save, then ends the helper off the screen's thread
# and waits a little more at most.
HARD_STOP_MS = 10000
CLOSE_SAVE_WAIT_MS = 700
CLOSE_END_WAIT_MS = 2500
# Build folders left by an app that did not close normally are removed once they are this old.
STALE_FOLDER_SECONDS = 24 * 3600
# While recordings wait for the app to be idle, it looks again this often.
RETRY_MS = 5000
# The time left is said once measuring has run this long, so a first second's guess is never shown.
ESTIMATE_AFTER_SECONDS = 3.0
# The level of a second that is in the cache but was not in the lines heard (drawn as silence).
UNHEARD_DBFS = -120.0

STATE_WAITING_FOR_RUN = "The sound is measured once the run has finished."
STATE_STILL_RECORDING = "This recording is still being written; its sound is measured once it is finished."
STATE_FAILED = "The sound of this recording could not be measured."
STATE_NO_AUDIO = "This recording has no sound to show."

# A thread object destroyed while it still runs ends the whole process, so one that shutdown gave up
# waiting for is kept here until it ends.
_PARKED: set[QThread] = set()


def parked_threads() -> tuple[QThread, ...]:
    """Threads given up on at close and still running; the app's exit does not wait on them for long."""

    return tuple(thread for thread in _PARKED if thread.isRunning())


def _park(thread: QThread) -> None:
    if thread not in _PARKED:
        _PARKED.add(thread)
        thread.finished.connect(lambda: _PARKED.discard(thread))


def _time_left(seconds: float) -> str:
    if seconds < 60:
        return "less than a minute left"
    minutes = round(seconds / 60)
    return "about 1 minute left" if minutes == 1 else f"about {minutes} minutes left"


class _LookupThread(QThread):
    found = Signal(str, object)  # path key, Levels | None
    facts_found = Signal(str, object)  # path key, speech_facts.JumpPoints | None

    def __init__(self, key: str, path: Path, cache: Path, facts_lookup: Callable[[Path], Any] | None = None) -> None:
        super().__init__()
        self.key = key
        self.path = path
        self.cache = cache
        self.facts_lookup = facts_lookup

    def run(self) -> None:
        try:
            levels = track_levels.cached_levels(self.path, cache=self.cache)
        except Exception:  # noqa: BLE001 - a lookup that fails is a recording with no levels yet
            levels = None
        # 264: told first, so whether the waveform is all that is needed is known when its answer comes.
        if self.facts_lookup is not None:
            try:
                facts = self.facts_lookup(self.path)
            except Exception:  # noqa: BLE001 - stored facts only save work
                facts = None
            self.facts_found.emit(self.key, facts)
        self.found.emit(self.key, levels)


class _BuildThread(QThread):
    line = Signal(str)
    ended = Signal(object)  # the runner's result

    def __init__(self, command: Any, cwd: str, runner: Any) -> None:
        super().__init__()
        self.command = command
        self.cwd = cwd
        self.runner = runner

    def run(self) -> None:
        def told(_stream: str, text: str) -> None:
            self.line.emit(str(text))

        try:
            try:
                result = self.runner.run(self.command, told, cwd=self.cwd)
            except TypeError:
                result = self.runner.run(self.command, told)
        except Exception as exc:  # noqa: BLE001 - always one ending
            result = exc
        self.ended.emit(result)

    def cancel(self) -> None:
        self.runner.cancel()


class _Batch:
    def __init__(self, keys: list[str], listener: Any) -> None:
        self.keys = keys
        self.listener = listener


class LevelsService(QObject):
    """The one queue of waveform builds. The player's recording always goes first."""

    levels_changed = Signal(str)  # path key: new levels (part or all) for that recording
    state_changed = Signal(str)  # path key: what to say in the lanes while there are none or few
    facts_changed = Signal(str)  # path key: what Next speech knows about that recording (264)

    def __init__(
        self,
        *,
        resources: Callable[[], Any],
        settings: Callable[[], Mapping[str, Any]],
        is_idle: Callable[[], bool],
        runner_factory: Callable[[], Any] | None,
        availability_changed: Any = None,
        log: Callable[[str], None] | None = None,
        parent: QObject | None = None,
        tools_ready: Callable[[], bool] | None = None,
        facts_lookup: Callable[[Path], Any] | None = None,
        facts_request: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._resources = resources
        self._settings = settings
        self._is_idle = is_idle
        # The readiness check decides which Python and FFmpeg the helpers use; nothing is measured
        # before its answer (225). It takes a few seconds, so nothing is said meanwhile.
        self._tools_ready = tools_ready or (lambda: True)
        self._factory = runner_factory
        # 264: what Next speech knows about a recording (``speech_facts.jump_points``), asked off the screen's thread,
        # and what a read for its speech facts needs. Without them this job only makes waveforms.
        self._facts_lookup = facts_lookup
        self._facts_request = facts_request or (lambda: {})
        self._facts: dict[str, Any] = {}
        self._facts_tried: set[str] = set()  # read once this session, whatever came of it: never read in a loop
        self._log = log or (lambda _text: None)
        self._paths: dict[str, Path] = {}
        self._levels: dict[str, Levels] = {}
        self._states: dict[str, str] = {}
        self._done: dict[str, str] = {}  # path key -> final status: ready, in_use, no_audio, failed
        self._looked_up: set[str] = set()
        self._looking: set[str] = set()  # lookups still running: no build starts before its answer
        self._first: set[str] = set()  # looked up for the player: queued first once known
        self._queue: list[str] = []
        self._wanted: str | None = None
        self._fresh: set[str] = set()  # Measure the sound again: measured from the start, not resumed
        self._progress_from: tuple[float, int] | None = None  # (clock, seconds) at a build's first line
        self._lookups: set[_LookupThread] = set()
        self._build: _BuildThread | None = None
        self._building: str | None = None
        self._build_folder: Path | None = None
        self._control: RunControl | None = None
        self._stopping_for_run = False
        self._batches: list[_Batch] = []
        self._closed = False
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(HOLD_AFTER_SEEK_MS)
        self._hold.timeout.connect(self._resume_after_hold)
        self._retry = QTimer(self)
        self._retry.setInterval(RETRY_MS)
        self._retry.timeout.connect(self._pump)
        if availability_changed is not None:
            availability_changed.connect(self._pump)
        if self._factory is not None:
            self._remove_stale_folders()

    @staticmethod
    def _remove_stale_folders() -> None:
        """Build folders an app that did not close normally left in the temporary folder."""

        root = scratch_root() / "media_manglers_levels_runs"
        try:
            folders = [folder for folder in root.iterdir() if folder.is_dir()]
        except OSError:
            return
        now = time.time()
        for folder in folders:
            try:
                if now - folder.stat().st_mtime > STALE_FOLDER_SECONDS:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                continue

    # What pages ask ---------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._factory is not None and not self._closed

    def levels_for(self, path: Path | str) -> Levels | None:
        return self._levels.get(path_key(path))

    def state_for(self, path: Path | str) -> str:
        return self._states.get(path_key(path), "")

    def facts_for(self, path: Path | str) -> Any | None:
        return self._facts.get(path_key(path))

    def _needs_facts(self, key: str) -> bool:
        """This recording still has to be read or listened to for its speech facts (Q5: only what is opened or a run
        just used reaches this queue, never the whole library)."""

        facts = self._facts.get(key)
        return (self._facts_lookup is not None and key not in self._facts_tried and facts is not None
                and bool(facts.needs_read or facts.needs_listen))

    def want(self, path: Path | str) -> None:
        """The player opened this recording: find its levels, and measure them first if they are missing."""

        if not self.enabled:
            return
        key = path_key(path)
        self._paths[key] = Path(path)
        self._wanted = key
        known = self._levels.get(key)
        if self._facts_lookup is not None and key not in self._looking and key != self._building:
            # Asked again at each open: your answer for this recording may have changed on another screen.
            self._looked_up.discard(key)
        if known is not None and known.complete and (self._facts_lookup is None or key in self._looked_up):
            self.levels_changed.emit(key)
            return
        if known is not None and known.complete:
            self.levels_changed.emit(key)
        self._enqueue(key, first=True)

    def measure_again(self, path: Path | str) -> None:
        """Measure the sound again: this recording's own levels are measured from the start, first."""

        if not self.enabled:
            return
        key = path_key(path)
        self._paths[key] = Path(path)
        self._wanted = key
        self._fresh.add(key)
        self._levels.pop(key, None)
        self._done.pop(key, None)
        self._looked_up.add(key)
        self._say(key, "Measuring the sound of every track…")
        self.levels_changed.emit(key)
        if key == self._building:
            # The measure going now gives way; the fresh one starts once it has ended.
            self._stop_build(requeue=True)
            return
        self._enqueue(key, first=True)

    def queue(self, paths: Iterable[Path | str], listener: Any = None) -> None:
        """A finished run's recordings, measured after anything the player wants. ``listener`` (if any)
        is told ``on_waveforms(ready, total, working)`` as they become ready."""

        if not self.enabled:
            return
        keys = []
        for path in paths:
            key = path_key(path)
            self._paths.setdefault(key, Path(path))
            if key not in keys:
                keys.append(key)
        if listener is not None and keys:
            self._batches.append(_Batch(keys, listener))
        for key in keys:
            self._enqueue(key, first=False)
        self._tell_batches()

    def hold(self) -> None:
        """The player moved: measuring stops reading the drive for a moment, so the picture comes first."""

        if self._control is None or self._build is None:
            return
        if not self._control.paused:
            self._write_control(self._control.set_paused, True)
        self._hold.start()

    def stop_for_run(self) -> None:
        """A run is starting: stop measuring now, keeping what was measured, and carry on later."""

        if self._build is not None:
            self._stopping_for_run = True
            self._stop_build(requeue=True)

    def shutdown(self) -> None:
        """The app is closing: stop at once and never hold the close up."""

        self._closed = True
        self._retry.stop()
        self._hold.stop()
        self._queue.clear()
        if self._build is not None:
            thread, folder = self._build, self._build_folder
            self._stop_build(requeue=False, wait=True)
            # Its ending is never handled once the app is closing, so its folder goes here.
            if folder is not None and not thread.isRunning():
                shutil.rmtree(folder, ignore_errors=True)
        for thread in tuple(self._lookups):
            if thread.isRunning() and not thread.wait(200):
                _park(thread)
        self._lookups.clear()

    # The queue ------------------------------------------------------------------------------

    def _enqueue(self, key: str, *, first: bool) -> None:
        if key not in self._looked_up:
            self._looked_up.add(key)
            self._start_lookup(key, first=first)
            return
        if key in self._looking:
            # Asked again before the first answer: it is queued when the answer comes.
            if first:
                self._first.add(key)
            return
        known = self._levels.get(key)
        if (known is not None and known.complete and not self._needs_facts(key)) or key == self._building:
            return
        if self._done.get(key) in (track_levels.STATUS_NO_AUDIO,):
            return
        if key in self._queue:
            self._queue.remove(key)
        if first:
            self._queue.insert(0, key)
        else:
            self._queue.append(key)
        if key == self._wanted and self._building not in (None, key):
            # The player's recording goes first: a build of another one gives way and carries on later
            # from its checkpoint. The next build starts when that one has ended.
            self._stop_build(requeue=True)
            return
        self._pump()

    def _cache(self) -> Path:
        return app_cache.cache_root(str(self._settings().get("cache_folder") or ""))

    def _start_lookup(self, key: str, *, first: bool) -> None:
        thread = _LookupThread(key, self._paths[key], self._cache(), self._facts_lookup)
        self._looking.add(key)
        if first:
            self._first.add(key)
        # Connected to this object's own methods, so the answers arrive on the screen's thread.
        thread.facts_found.connect(self._on_facts_found)
        thread.found.connect(self._on_found)
        thread.finished.connect(self._lookup_finished)
        self._lookups.add(thread)
        thread.start()

    def _lookup_finished(self) -> None:
        for thread in tuple(self._lookups):
            if thread.isFinished():
                self._lookups.discard(thread)
                thread.deleteLater()

    def _on_facts_found(self, key: str, facts: Any) -> None:
        if self._closed:
            return
        self._facts[key] = facts
        self.facts_changed.emit(key)

    def _on_found(self, key: str, levels: Any) -> None:
        first = key in self._first
        self._first.discard(key)
        self._looking.discard(key)
        if self._closed:
            return
        # A lookup that started before Measure the sound again, or before this recording's build, is
        # out of date: the build's own lines carry its levels.
        if isinstance(levels, Levels) and key not in self._fresh and key != self._building:
            self._levels[key] = levels
            self.levels_changed.emit(key)
            if levels.complete and not self._needs_facts(key):
                self._done[key] = track_levels.STATUS_READY
                self._tell_batches()
                return
        self._enqueue(key, first=first or key == self._wanted)

    def _pump(self) -> None:
        if not self.enabled or self._build is not None or not self._queue:
            if not self._queue:
                self._retry.stop()
            return
        if not self._tools_ready():
            self._retry.start()
            return
        if not self._is_idle():
            for key in self._queue:
                self._say(key, STATE_WAITING_FOR_RUN)
            self._retry.start()
            return
        self._retry.stop()
        key = self._queue.pop(0)
        if key not in self._looked_up:
            # A build that was stopped saved more than its last lines said, and the next one carries on
            # from what it saved: look that up first, so the lanes carry on in the same place.
            self._enqueue(key, first=True)
            return
        self._start_build(key)

    def _say(self, key: str, text: str) -> None:
        if self._states.get(key) != text:
            self._states[key] = text
            self.state_changed.emit(key)

    # One build --------------------------------------------------------------------------------

    def _start_build(self, key: str) -> None:
        settings = self._settings()
        resources = self._resources()
        folder = scratch_root() / "media_manglers_levels_runs" / f"{datetime.now():%Y%m%d-%H%M%S-%f}"
        folder.mkdir(parents=True, exist_ok=True)
        self._control = RunControl.for_folder(folder)
        request, result = folder / "request.json", folder / "result.json"
        wants_facts = self._needs_facts(key)
        request.write_text(json.dumps({"payload": {
            "paths": [str(self._paths[key])],
            "ffmpeg": str(getattr(resources, "ffmpeg_exe", "") or "ffmpeg"),
            "ffprobe": str(getattr(resources, "ffprobe_exe", "") or "ffprobe"),
            "cache_folder": str(settings.get("cache_folder") or ""),
            "cache_cap_bytes": int(settings.get("cache_size_gb") or 10) * 1024 ** 3,
            "run_control_path": str(self._control.path),
            "recordings_folders": recordings_folders(),
            "fresh_paths": [str(self._paths[key])] if key in self._fresh else [],
            "work_dir": str(folder / "work"),
            **({"facts": self._facts_request()} if wants_facts else {}),
        }}, indent=2), encoding="utf-8")
        # Asked once: a fresh measure that is stopped carries on later from its own checkpoint.
        self._fresh.discard(key)
        self._progress_from = None
        command = cli_command(resources, "track-levels", request, result)
        self._building, self._build_folder = key, folder
        self._build = _BuildThread(command, str(getattr(resources, "app_root", "") or os.getcwd()), self._factory())
        self._build.line.connect(self._on_line)
        self._build.ended.connect(self._on_ended)
        self._say(key, "Measuring the sound of every track…")
        self._log(f"Waveforms: measuring {self._paths[key].name}.")
        self._build.start()

    def _on_line(self, text: str) -> None:
        key = self._building
        if key is None or not text.startswith(track_levels.PROGRESS_PREFIX):
            return
        try:
            event = json.loads(text[len(track_levels.PROGRESS_PREFIX):])
        except ValueError:
            return
        if isinstance(event, dict) and "reading_for_speech" in event:
            # A read for the speech facts of a recording whose lanes are whole already: they stay as they are.
            duration = float(event.get("duration") or 0.0)
            if duration > 0:
                self._say(key, f"Measuring the sound of every track: {min(1.0, float(event['reading_for_speech']) / duration):.0%}.")
            return
        tracks = event.get("tracks") if isinstance(event, dict) else None
        if not isinstance(tracks, dict):
            return
        levels = self._levels.get(key)
        if levels is None or levels.complete:
            levels = self._levels[key] = Levels(origin="measured")
        first = int(event.get("first") or 0)
        for name, values in tracks.items():
            if str(name).isdigit() and isinstance(values, list):
                track = levels.tracks.setdefault(int(name), [])
                del track[first:]
                # Seconds this side has not heard of yet stay quiet until the finished levels are read
                # back; they are never put in the place of others.
                track.extend([UNHEARD_DBFS] * (first - len(track)))
                track.extend(float(value) for value in values)
        duration = float(event.get("duration") or 0.0)
        levels.duration_seconds = duration
        if duration > 0:
            share = min(1.0, levels.seconds / duration)
            now = time.monotonic()
            if self._progress_from is None:
                self._progress_from = (now, levels.seconds)
            began, reached = self._progress_from
            rate = (levels.seconds - reached) / (now - began) if now - began >= ESTIMATE_AFTER_SECONDS else 0.0
            left = f" ({_time_left((duration - levels.seconds) / rate)})" if rate > 0 else ""
            self._say(key, f"Measuring the sound of every track: {share:.0%}{left}.")
        self.levels_changed.emit(key)

    def _on_ended(self, result: Any) -> None:
        thread, key, folder = self._build, self._building, self._build_folder
        self._build = self._building = self._build_folder = None
        self._control = None
        self._hold.stop()
        status = ""
        try:
            outcome = json.loads((folder / "result.json").read_text(encoding="utf-8")) if folder else {}
            items = (outcome.get("data") or {}).get("results") or []
            status = str(items[0].get("status") or "") if items else ""
        except (OSError, ValueError, AttributeError, IndexError):
            status = ""
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        if key is not None and not self._closed:
            self._finish(key, status, result)
        if thread is not None:
            thread.deleteLater()
        self._stopping_for_run = False
        # Always: a run that was over before this build had stopped sends no later notice, and the
        # queue waits by itself (with its retry) while a run is still going.
        QTimer.singleShot(0, self._pump)

    def _finish(self, key: str, status: str, result: Any) -> None:
        levels = self._levels.get(key)
        if status == track_levels.STATUS_READY and key in self._fresh:
            # It finished just as Measure the sound again was asked; it is still queued, from the start.
            self._levels.pop(key, None)
            self.levels_changed.emit(key)
            return
        if status == track_levels.STATUS_READY:
            if levels is not None:
                levels.complete = True
            self._done[key] = status
            self._facts_tried.add(key)
            self._say(key, "")
            self._log(f"Waveforms: {self._paths[key].name} is ready.")
            # The cache holds the whole result; the lines may have been read part way.
            self._looked_up.discard(key)
            self._enqueue(key, first=key == self._wanted)
        elif status == track_levels.STATUS_STOPPED or getattr(result, "status", "") == "cancelled":
            self._say(key, STATE_WAITING_FOR_RUN if self._stopping_for_run else "")
            # What it saved is looked up again before it carries on.
            self._looked_up.discard(key)
        elif status == track_levels.STATUS_IN_USE:
            self._done[key] = status
            self._say(key, STATE_STILL_RECORDING)
        elif status == track_levels.STATUS_NO_AUDIO:
            self._done[key] = status
            self._say(key, STATE_NO_AUDIO)
        else:
            self._done[key] = "failed"
            self._say(key, STATE_FAILED)
            self._log(f"Waveforms: {self._paths[key].name} could not be measured "
                      f"({status or getattr(result, 'error', '') or 'no result'}).")
        self.levels_changed.emit(key)
        self._tell_batches()

    def _stop_build(self, *, requeue: bool, wait: bool = False) -> None:
        thread, key = self._build, self._building
        if thread is None:
            return
        if requeue and key is not None and not self._closed:
            if key in self._queue:
                self._queue.remove(key)
            self._queue.insert(1 if self._queue and self._queue[0] == self._wanted else 0, key)
        if self._control is not None and key is not None:
            # The shared Skip: the helper saves what it measured and ends by itself within a second.
            self._write_control(self._control.skip, [str(self._paths[key])])
        self._log("Waveforms: measuring stopped; what was measured is kept.")
        if wait:
            # Closing: the helper saves what it measured as soon as it reads the stop, then it is ended,
            # off the screen's thread, so the window never freezes for long.
            if not thread.wait(CLOSE_SAVE_WAIT_MS):
                threading.Thread(target=thread.cancel, daemon=True).start()
                if not thread.wait(CLOSE_END_WAIT_MS):
                    _park(thread)
            return
        # Nothing here waits on the screen's thread; a helper that has not ended by itself is ended
        # hard later, and that too happens off the screen's thread.
        QTimer.singleShot(HARD_STOP_MS, lambda: self._end_hard(thread))

    def _end_hard(self, thread: _BuildThread) -> None:
        if thread is self._build and thread.isRunning():
            threading.Thread(target=thread.cancel, daemon=True).start()

    def _resume_after_hold(self) -> None:
        if self._control is not None and self._control.paused:
            self._write_control(self._control.set_paused, False)

    def _write_control(self, write: Callable[[Any], Any], value: Any) -> None:
        try:
            write(value)
        except OSError as exc:
            self._log(f"Waveforms: the measuring control file could not be written ({exc}).")

    def _tell_batches(self) -> None:
        for batch in list(self._batches):
            ready = sum(1 for key in batch.keys if self._done.get(key) == track_levels.STATUS_READY)
            finished = sum(1 for key in batch.keys if key in self._done)
            working = finished < len(batch.keys)
            callback = getattr(batch.listener, "on_waveforms", None)
            if callable(callback):
                callback(ready, len(batch.keys), working)
            if not working:
                self._batches.remove(batch)
