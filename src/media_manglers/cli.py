"""CLI entry point for tracked Media Manglers Python helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any, Callable

from .contracts import CommandResult, read_json_file, write_json_file
from .core.readmes import write_package_readme_from_request
from .core.race_video import requests as race_video
from .core import (
    app_locks,
    archive_catalog,
    evidence_package,
    file_steps,
    frame_render,
    inbox_records,
    review_finalization,
    review_findings,
    review_inbox,
    review_ledger,
    review_orchestration,
    review_preparation,
    review_queue,
    review_relocation,
    review_results,
    review_targeted_evidence,
    safe_write,
    narration_evidence,
    private_runtime,
    raw_bin_library,
    scratch,
    user_folders,
    zip_writer,
    track_levels,
    transcript_only,
    speech_facts,
    voice_track,
    whisper_models,
    cross_track_check,
)
from .providers import argos_local, hybrid_text, whisper_local


Handler = Callable[[dict[str, Any]], dict[str, Any]]

# 224 (Wave B1): these command-line actions write Review Media Inbox's records or its folder, so each takes the
# Inbox's lock first and is refused with one plain line while another run holds it. Reconcile, Process and the
# relocation tool take the lock themselves (Process and reconcile attach to a run already going; relocation has
# its own refusals), and the checks that only read need none. A helper the PowerShell host calls inside its own
# Process loop says coordinator_lock_held, because the host holds the lock.
INBOX_WRITERS = {
    "review-ledger-migrate",
    "review-media-inbox-scan",
    "review-media-inbox-prepare",
    "review-media-inbox-repair",
    "review-media-inbox-import-preliminary",
    "review-media-inbox-targeted-plan",
    "review-media-inbox-targeted-complete",
    "review-media-inbox-import-results",
    "review-media-inbox-finalization-preview",
    "review-media-inbox-finalize",
}

# These work only on records that already exist (F5). When the ledger they name is not there, they are refused
# here in one plain line, before they read, write or lock anything: taking the lock would leave a lock file (and,
# for a mistyped path, its folders) behind, and targeted complete and a resumed finalize write into their batch
# before their own check finds the ledger gone.
INBOX_EXISTING_RECORDS = {
    "review-media-inbox-repair",
    "review-media-inbox-import-preliminary",
    "review-media-inbox-targeted-plan",
    "review-media-inbox-targeted-complete",
    "review-media-inbox-import-results",
    "review-media-inbox-finalization-preview",
    "review-media-inbox-finalize",
}


# 224 (Wave B2a, Decision 4): only the old Review New Videos workflow called these, and it could never run, so
# they are retired rather than carried into the library. Each refuses in one line before it reads, writes or
# locks anything.
RETIRED_REVIEW_NEW_VIDEOS = ("review-ledger-lookup", "review-ledger-record", "review-ledger-match-sha")
RETIRED_REVIEW_NEW_VIDEOS_MESSAGE = "This old Review New Videos helper was retired; use Review Media Inbox."


def _retired_review_new_videos(payload: dict[str, Any]) -> dict[str, Any]:
    raise ValueError(RETIRED_REVIEW_NEW_VIDEOS_MESSAGE)


def _writes_inbox(command: str, payload: dict[str, Any]) -> bool:
    return command in INBOX_WRITERS


def _inbox_ledger(command: str, payload: dict[str, Any]) -> str:
    """The ledger an Inbox action works on, so its lock can be taken; "" when the request names none (the
    action's own check then refuses it)."""

    if command in {"review-media-inbox-targeted-complete", "review-media-inbox-finalize"} and payload.get("plan_path"):
        # These work on the ledger their plan names, whatever else the request says.
        try:
            plan = json.loads(Path(str(payload["plan_path"])).read_text(encoding="utf-8-sig"))
            named = str(plan.get("ledger_path") or "").strip() if isinstance(plan, dict) else ""
        except (OSError, UnicodeError, ValueError):
            named = ""
        if named:
            return named
    cli = payload.get("cli") if isinstance(payload.get("cli"), dict) else {}
    if str(payload.get("inbox_folder") or cli.get("inbox_folder") or "").strip():
        # 224 (Wave B2b): a request may name the Inbox folder itself; the ledger's name in it is its note.
        return str(inbox_records.ledger_file(payload))
    value = str(payload.get("ledger_path") or cli.get("ledger_path") or "").strip()
    if not value and command in {"review-media-inbox-scan", "review-media-inbox-prepare"}:
        scan_result = payload.get("scan_result") if isinstance(payload.get("scan_result"), dict) else {}
        settings = scan_result.get("settings") if isinstance(scan_result.get("settings"), dict) else {}
        value = str(settings.get("ledger_path") or "").strip()
        if not value:
            try:
                config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
                value = str(review_inbox.resolve_settings(cli or payload, config)["ledger_path"] or "").strip()
            except (KeyError, TypeError, ValueError):
                value = ""
    if not value and payload.get("plan_path"):
        # Targeted complete and finalize name their plan; the plan names the ledger.
        try:
            plan = json.loads(Path(str(payload["plan_path"])).read_text(encoding="utf-8-sig"))
            value = str(plan.get("ledger_path") or "").strip() if isinstance(plan, dict) else ""
        except (OSError, UnicodeError, ValueError):
            value = ""
    return value


def _run(command: str, handler: Handler, payload: dict[str, Any]) -> dict[str, Any]:
    ledger = _inbox_ledger(command, payload) if _writes_inbox(command, payload) else ""
    if not ledger:
        return handler(payload)
    if command in INBOX_EXISTING_RECORDS:
        # 224 (Wave B2b): an Inbox that opens nothing yet says why; then "are this folder's records in the
        # library", not "is there a file": the ledger's name holds a note since the move.
        found = inbox_records.current_status(ledger)
        if not found.ready:
            raise inbox_records.InboxNotReady(found.message, found.state)
        if not inbox_records.has_records(ledger):
            raise inbox_records.LedgerMissing(inbox_records.ledger_file(ledger))
    with inbox_records.writing(ledger, coordinator_lock_held=bool(payload.get("coordinator_lock_held"))):
        return handler(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media_manglers",
        description="Tracked cross-platform helper CLI for Media Manglers.",
    )
    subparsers = parser.add_subparsers(dest="command")

    for name in (
        "whisper-probe",
        "whisper-plan",
        "whisper-transcribe",
        "argos-status",
        "argos-probe",
        "argos-install",
        "argos-translate",
        "hybrid-translate",
        "hybrid-validate",
        "evidence-package-build",
        "evidence-package-detect",
        "evidence-package-write",
        "transcript-only-index",
        "archive-catalog-build",
        "archive-catalog-search",
        "review-ledger-lookup",
        "review-ledger-record",
        "review-ledger-match-sha",
        "review-ledger-migrate",
        "review-ledger-validate",
        "review-media-inbox-scan",
        "review-media-inbox-reconcile",
        "review-media-inbox-process",
        "review-media-inbox-prepare",
        "review-media-inbox-repair",
        "review-media-inbox-relocate",
        "review-media-inbox-import-preliminary",
        "review-media-inbox-targeted-plan",
        "review-media-inbox-targeted-complete",
        "review-media-inbox-import-results",
        "review-media-inbox-finalization-preview",
        "review-media-inbox-finalize",
        "review-media-inbox-finalization-status",
        "write-package-readme",
        "folder-check",
        "zip-write",
        "frames-render",
        "audio-extract",
        "voice-track-detect",
        "voice-track-known",
        "narration-cross-check",
        "narration-evidence-plan",
        "narration-evidence-write",
        "race-video-validate",
        "race-video-add-version",
        "race-video-render",
        "race-video-check",
        "race-video-feedback",
        "race-video-analyze",
        "race-video-transcribe",
        "race-video-look",
        "race-video-review-kit",
        "race-video-cut-points",
        "race-video-usage",
        "race-video-prompt",
        "race-video-save-mask",
        "race-video-projects",
        "race-video-export",
        "race-video-panel-still",
        "race-video-prepare",
        "race-video-fresh-edit",
        "raw-bin-scan",
        "raw-bin-deep-scan",
        "raw-bin-reapply",
        "track-levels",
        "whisper-models",
        "whisper-model-download",
    ):
        command = subparsers.add_parser(
            name,
            help="Run a tracked Media Manglers helper command.",
        )
        command.add_argument("--request-file", required=True)
        command.add_argument("--result-file", required=True)

    # Installer plan, Stage 2: new file steps for programs that are not Python (the uninstaller's
    # "file-step remove-addons"), through the one shared helper.
    file_step = subparsers.add_parser(FILE_STEP, help="Run a new file step through the shared safe file helper.")
    file_step.add_argument("action", choices=("remove-addons", "run"))
    file_step.add_argument("--request-file", default="")
    file_step.add_argument("--result-file", default="")

    return parser


FILE_STEP = "file-step"


def _file_step(args: argparse.Namespace) -> int:
    """0 when the step succeeded; 2 when another program still holds a file; 1 for any other refusal. The result
    goes to ``--result-file``, or to standard output as one line of JSON."""

    code = 0
    try:
        if args.action == "remove-addons":
            data = file_steps.remove_addons()
        else:
            if not args.request_file:
                raise ValueError("file-step run needs --request-file with the steps to carry out.")
            payload = read_json_file(args.request_file).get("payload") or {}
            data = {"steps": file_steps.run_steps(list(payload.get("steps") or []))}
        result = CommandResult(ok=True, data=data, error="")
    except safe_write.FileInUse as exc:
        code = 2
        result = CommandResult(ok=False, data={"holders": file_steps.holder_data(exc)}, error=str(exc))
    except (OSError, ValueError, KeyError) as exc:
        code = 1
        result = CommandResult(ok=False, data={}, error=str(exc))
    if args.result_file:
        write_json_file(args.result_file, result.to_dict())
    else:
        print(json.dumps(result.to_dict(), ensure_ascii=False), flush=True)
    return code


def _build_handlers() -> dict[str, Handler]:
    return {
        "whisper-probe": lambda payload: whisper_local.probe_environment(),
        "whisper-plan": whisper_local.build_runtime_plan_from_request,
        # 211: the one output-folder rule, asked by the backend.
        "folder-check": user_folders.check_folders_from_request,
        # 209: the one ZIP writer, for the backend's ZIPs.
        "zip-write": zip_writer.write_zip_from_request,
        # 214: the one frame renderer, for the backend's screenshots.
        "frames-render": frame_render.render_from_request,
        # 214: the one audio decoder, for the backend's narration WAV.
        "audio-extract": voice_track.extract_from_request,
        "whisper-transcribe": whisper_local.transcribe_from_request,
        "argos-status": lambda payload: argos_local.get_module_status(),
        "argos-probe": argos_local.probe_from_request,
        "argos-install": argos_local.install_from_request,
        "argos-translate": argos_local.translate_from_request,
        "hybrid-translate": hybrid_text.translate_from_request,
        "hybrid-validate": hybrid_text.validate_from_request,
        "evidence-package-build": evidence_package.build_package_from_request,
        "evidence-package-detect": evidence_package.detect_from_request,
        "evidence-package-write": evidence_package.write_outputs_from_request,
        "transcript-only-index": transcript_only.write_outputs_from_request,
        "archive-catalog-build": archive_catalog.build_catalog_from_request,
        "archive-catalog-search": archive_catalog.search_catalog_from_request,
        **{name: _retired_review_new_videos for name in RETIRED_REVIEW_NEW_VIDEOS},
        "review-ledger-migrate": review_ledger.migrate_from_request,
        "review-ledger-validate": review_ledger.validate_from_request,
        "review-media-inbox-scan": review_inbox.scan_from_request,
        "review-media-inbox-reconcile": review_orchestration.reconcile_from_request,
        "review-media-inbox-process": review_orchestration.process_from_request,
        "review-media-inbox-prepare": review_preparation.prepare_from_request,
        "review-media-inbox-repair": review_preparation.repair_from_request,
        "review-media-inbox-relocate": review_relocation.relocate_from_request,
        "review-media-inbox-import-preliminary": review_findings.import_from_request,
        "review-media-inbox-targeted-plan": review_targeted_evidence.plan_from_request,
        "review-media-inbox-targeted-complete": review_targeted_evidence.complete_from_request,
        "review-media-inbox-import-results": review_results.import_from_request,
        "review-media-inbox-finalization-preview": review_finalization.preview_from_request,
        "review-media-inbox-finalize": review_finalization.finalize_from_request,
        "review-media-inbox-finalization-status": review_finalization.status_from_request,
        "write-package-readme": write_package_readme_from_request,
        # 264: the shared detection, with what it measured kept in the library, and the quick question asked first.
        "voice-track-detect": speech_facts.detect_from_request,
        "voice-track-known": speech_facts.known_from_request,
        "narration-cross-check": cross_track_check.check_from_request,
        "narration-evidence-plan": narration_evidence.plan_from_request,
        "narration-evidence-write": narration_evidence.write_index_from_request,
        "race-video-validate": race_video.validate_from_request,
        "race-video-add-version": race_video.add_version_from_request,
        "race-video-render": race_video.render_from_request,
        "race-video-check": race_video.check_from_request,
        "race-video-feedback": race_video.feedback_from_request,
        "race-video-analyze": race_video.analyze_from_request,
        "race-video-transcribe": race_video.transcribe_from_request,
        "race-video-look": race_video.look_from_request,
        "race-video-review-kit": race_video.review_kit_from_request,
        "race-video-cut-points": race_video.cut_points_from_request,
        "race-video-usage": race_video.usage_from_request,
        "race-video-prompt": race_video.prompt_from_request,
        "race-video-save-mask": race_video.save_mask_from_request,
        "race-video-projects": race_video.projects_from_request,
        "race-video-export": race_video.export_from_request,
        "race-video-panel-still": race_video.panel_still_from_request,
        "race-video-prepare": race_video.prepare_from_request,
        "race-video-fresh-edit": race_video.fresh_edit_from_request,
        # 220: the raw bin library's scan and Deep scan.
        "raw-bin-scan": raw_bin_library.scan_from_request,
        "raw-bin-deep-scan": raw_bin_library.deep_scan_from_request,
        # 220: new rules or Track roles applied to the library without reading any recording.
        "raw-bin-reapply": raw_bin_library.reapply_from_request,
        # 125, 135 (Wave 8): the sound level of every track, for the player's waveform lanes.
        "track-levels": track_levels.measure_from_request,
        # Installer plan, Stage 3: which Whisper models are on this PC and right (reads only), and the download
        # the operator approved (only the approval runs it).
        "whisper-models": whisper_models.status_from_request,
        "whisper-model-download": whisper_models.download_from_request,
    }


def main(argv: Sequence[str] | None = None) -> int:
    # Installer plan, Stage 1: our own Python gets our downloaded speech libraries before any command runs;
    # a Python already on the PC is left exactly as it is.
    private_runtime.use_addons()
    # Installer plan, Stage 2: every helper run holds this, so the installer can see Media Manglers is running.
    app_locks.hold_running_lock()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == FILE_STEP:
        return _file_step(args)

    # 196: the helper's own temporary files follow MEDIA_MANGLERS_SCRATCH_ROOT when it is set.
    scratch.use_scratch_root()
    handlers = _build_handlers()
    handler = handlers[args.command]
    request = read_json_file(args.request_file)
    payload = request.get("payload") or {}

    try:
        data = _run(args.command, handler, payload)
        write_json_file(
            args.result_file,
            CommandResult(ok=True, data=data, error="").to_dict(),
        )
        return 0
    except Exception as exc:
        write_json_file(
            args.result_file,
            CommandResult(ok=False, data={}, error=str(exc)).to_dict(),
        )
        return 1
