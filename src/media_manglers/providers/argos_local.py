"""Tracked local Argos helpers for the phased migration."""

from __future__ import annotations

from typing import Any

from media_manglers.core.artifacts import coerce_segment_records


def _log(message: str) -> None:
    print(message, flush=True)


def get_module_status() -> dict[str, Any]:
    try:
        __import__("argostranslate.translate")
        return {"module_installed": True, "error": ""}
    except Exception as exc:
        return {"module_installed": False, "error": str(exc)}


def probe_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    from_code = str(payload.get("from_code") or "")
    to_code = str(payload.get("to_code") or "")
    result: dict[str, Any] = {
        "module_installed": False,
        "can_translate": False,
        "installed_languages": [],
        "error": "",
    }

    try:
        import argostranslate.translate

        result["module_installed"] = True
        languages = argostranslate.translate.get_installed_languages()
        installed_codes = {
            str(getattr(language, "code", "") or "")
            for language in languages
            if getattr(language, "code", "")
        }
        result["installed_languages"] = sorted(installed_codes)

        try:
            translation = argostranslate.translate.get_translation_from_codes(
                from_code,
                to_code,
            )
            result["can_translate"] = translation is not None
        except Exception as exc:
            result["error"] = str(exc)
    except Exception as exc:
        result["error"] = str(exc)

    return result


def install_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    from_code = str(payload.get("from_code") or "")
    to_code = str(payload.get("to_code") or "")

    import argostranslate.package
    import argostranslate.translate

    result: dict[str, Any] = {
        "success": False,
        "attempted_pairs": [],
        "installed_pairs": [],
        "error": "",
    }

    def add_pair(pairs: list[tuple[str, str]], seen: set[tuple[str, str]], source_code: str, target_code: str) -> None:
        if not source_code or not target_code or source_code == target_code:
            return
        key = (source_code, target_code)
        if key in seen:
            return
        seen.add(key)
        pairs.append(key)

    def install_pair(available_packages: list[Any], source_code: str, target_code: str) -> None:
        package_to_install = next(
            (
                package
                for package in available_packages
                if getattr(package, "from_code", "") == source_code
                and getattr(package, "to_code", "") == target_code
            ),
            None,
        )
        if package_to_install is None:
            raise RuntimeError(
                f"No Argos package index entry found for {source_code}->{target_code}"
            )
        download_path = package_to_install.download()
        argostranslate.package.install_from_path(download_path)

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    add_pair(pairs, seen, from_code, to_code)
    if from_code != "en" and to_code != "en":
        add_pair(pairs, seen, from_code, "en")
        add_pair(pairs, seen, "en", to_code)

    _log("[PY] Updating Argos package index...")
    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()

    for source_code, target_code in pairs:
        result["attempted_pairs"].append({"from": source_code, "to": target_code})
        try:
            _log(f"[PY] Installing Argos package {source_code}->{target_code}...")
            install_pair(available_packages, source_code, target_code)
            result["installed_pairs"].append({"from": source_code, "to": target_code})
        except Exception as exc:
            _log(f"[PY] Install note for {source_code}->{target_code}: {exc}")

    try:
        translation = argostranslate.translate.get_translation_from_codes(from_code, to_code)
        result["success"] = translation is not None
        if not result["success"]:
            result["error"] = f"Argos still cannot translate {from_code}->{to_code} after installation."
    except Exception as exc:
        result["error"] = str(exc)

    return result


def translate_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    import argostranslate.translate

    from_code = str(payload.get("from_code") or "")
    to_code = str(payload.get("to_code") or "")
    segments = coerce_segment_records(payload.get("segments") or [])
    translation = argostranslate.translate.get_translation_from_codes(from_code, to_code)
    translated_segments: list[dict[str, Any]] = []

    for index, segment in enumerate(segments, start=1):
        text = str(segment.get("text") or "").strip()
        translated_text = translation.translate(text) if text else ""
        translated_segments.append(
            {
                "id": segment.get("id"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": translated_text.strip(),
            }
        )

        if index == 1 or index % 25 == 0 or index == len(segments):
            _log(
                f"[PY] Argos translation still working... {index}/{len(segments)} segments translated"
            )

    return {
        "segments": translated_segments,
        "segments_count": len(translated_segments),
    }
