"""Hybrid Accuracy text-translation helpers for text-only OpenAI workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import socket
from typing import Any, Protocol
import unicodedata
from urllib import error, request

from ..core.transcripts import write_transcript_files


JsonObject = dict[str, Any]

HYBRID_PRIVACY_CLASS = "audio local / text uploaded"
HYBRID_DEFAULT_TARGET_LANGUAGE = "en"
HYBRID_DEFAULT_BATCH_SIZE = 4
HYBRID_DEFAULT_CONTEXT_SEGMENTS = 1
HYBRID_JSON_PROMPT_ONLY_MODEL_IDS = {
    "gpt-5-mini",
    "gpt-5-mini-2025-08-07",
}
HYBRID_MODEL_CONFIG: dict[str, dict[str, Any]] = {
    "Private": {
        "default": "gpt-4o-mini-2024-07-18",
        "approved_models": [
            "gpt-4o-mini-2024-07-18",
            "gpt-4.1-mini-2025-04-14",
            "gpt-5-mini",
            "gpt-5-mini-2025-08-07",
        ],
    },
    "Public": {
        "default": "gpt-4o-mini-2024-07-18",
        "approved_models": [
            "gpt-4o-mini-2024-07-18",
            "gpt-4.1-mini-2025-04-14",
        ],
    },
}
HYBRID_MODEL_PRICING_PER_MILLION_USD: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-mini-2025-04-14": {"input": 0.40, "output": 1.60},
}
PROJECT_ENV_VARS = {
    "Private": "OPENAI_API_KEY_PRIVATE",
    "Public": "OPENAI_API_KEY_PUBLIC",
}
DEFAULT_ASSISTANT_META_PATTERNS = (
    "please provide the german transcript segment",
    "return only the translated text",
    "here is the translation",
    "translated text:",
    "translation:",
    "assistant:",
)
DEFAULT_MOJIBAKE_PATTERNS = (
    "â",
    "â€™",
    "â€œ",
    "â€",
    "â€”",
    "â€“",
    "â€¦",
    "Ã",
    "ï»¿",
)
LANGUAGE_LABELS = {
    "de": "German",
    "en": "English",
}
KNOWN_BAD_EXAMPLE_SOURCE = "so heißt das in Crew Chief selber"
KNOWN_BAD_EXAMPLE_GOOD = "that is what it is called in Crew Chief itself"
KNOWN_BAD_EXAMPLE_BAD = "I am the Crew Chief myself."
_FENCED_JSON_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_WORD_PATTERN = re.compile(r"\b\w+\b", re.UNICODE)
_REPEATED_WORD_PATTERN = re.compile(r"\b([^\W\d_]{2,})\b(?:[\s,.;:!?-]+\1\b){2,}", re.IGNORECASE)
_REPEATED_CHAR_PATTERN = re.compile(r"(.)\1{5,}")
_NON_WORD_COMPRESSION_PATTERN = re.compile(r"^[\W_]+$", re.UNICODE)


class TranslationTransport(Protocol):
    """Minimal protocol for a mockable OpenAI transport."""

    def list_models(self) -> list[str]:
        """Return visible model ids for the selected project."""

    def translate_chat_completion(
        self,
        *,
        model: str,
        messages: list[JsonObject],
    ) -> JsonObject:
        """Translate one batch and return content plus usage metadata."""


@dataclass(slots=True)
class ModelResolution:
    requested_model: str
    used_model: str
    approved_models: list[str]
    accessible_models: list[str]
    selection_source: str
    discovery_status: str
    warning: str = ""

    def to_dict(self) -> JsonObject:
        return asdict(self)


class HybridTranslationError(RuntimeError):
    """Operator-facing Hybrid Accuracy failure."""


class HybridTransportError(HybridTranslationError):
    """HTTP/network failure metadata for the OpenAI transport."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "unexpected",
        status_code: int = 0,
        response_body: str = "",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.response_body = response_body


class OpenAiChatCompletionsTransport:
    """Small stdlib-only transport for chat completions and model discovery."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int = 120,
        api_base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._api_base_url = api_base_url.rstrip("/")
        self._model_ids: list[str] | None = None

    def _json_request(
        self,
        *,
        method: str,
        endpoint: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        url = f"{self._api_base_url}{endpoint}"
        body = None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "Media-Manglers-Hybrid-Accuracy",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise _http_error_to_transport_error(exc.code, response_body) from exc
        except error.URLError as exc:
            message = str(getattr(exc, "reason", exc))
            category = "timeout" if isinstance(getattr(exc, "reason", None), socket.timeout) else "network"
            raise HybridTransportError(
                f"OpenAI text translation request failed: {message}",
                category=category,
            ) from exc
        except TimeoutError as exc:
            raise HybridTransportError(
                "OpenAI text translation request timed out.",
                category="timeout",
            ) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HybridTranslationError(
                "OpenAI returned a non-JSON response for Hybrid Accuracy translation.",
            ) from exc

    def list_models(self) -> list[str]:
        if self._model_ids is None:
            payload = self._json_request(method="GET", endpoint="/models")
            self._model_ids = [
                str(item.get("id") or "").strip()
                for item in payload.get("data") or []
                if str(item.get("id") or "").strip()
            ]
        return list(self._model_ids)

    def translate_chat_completion(
        self,
        *,
        model: str,
        messages: list[JsonObject],
    ) -> JsonObject:
        payload: JsonObject = {
            "model": model,
            "messages": messages,
        }
        if _hybrid_model_uses_temperature(model):
            payload["temperature"] = 0
        if _hybrid_model_uses_response_format(model):
            payload["response_format"] = {"type": "json_object"}
        response_payload = self._json_request(
            method="POST",
            endpoint="/chat/completions",
            payload=payload,
        )
        content = _extract_chat_completion_content(response_payload)
        usage_payload = response_payload.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_payload.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_payload.get("completion_tokens") or 0),
            "total_tokens": int(usage_payload.get("total_tokens") or 0),
        }
        return {
            "content": content,
            "usage": usage,
            "model": str(response_payload.get("model") or model).strip(),
        }


def _hybrid_model_uses_response_format(model: str) -> bool:
    return str(model or "").strip().lower() not in HYBRID_JSON_PROMPT_ONLY_MODEL_IDS


def _hybrid_model_uses_temperature(model: str) -> bool:
    return str(model or "").strip().lower() not in HYBRID_JSON_PROMPT_ONLY_MODEL_IDS


def _http_error_to_transport_error(status_code: int, response_body: str) -> HybridTransportError:
    message = ""
    error_code = ""
    error_type = ""
    try:
        payload = json.loads(response_body or "{}")
        error_payload = payload.get("error") or {}
        message = str(error_payload.get("message") or "").strip()
        error_code = str(error_payload.get("code") or "").strip().lower()
        error_type = str(error_payload.get("type") or "").strip().lower()
    except json.JSONDecodeError:
        payload = {}

    lowered_message = message.lower()
    if status_code == 401:
        return HybridTransportError(
            "Hybrid Accuracy translation could not authenticate with the selected OpenAI project key.",
            category="unauthorized",
            status_code=status_code,
            response_body=response_body,
        )
    if status_code == 403:
        if "model" in lowered_message or error_code in {"model_not_found", "permission_denied"}:
            return HybridTransportError(
                "Model unavailable for selected OpenAI project.",
                category="model_unavailable",
                status_code=status_code,
                response_body=response_body,
            )
        return HybridTransportError(
            "Hybrid Accuracy translation does not have permission for the selected OpenAI project.",
            category="permission_denied",
            status_code=status_code,
            response_body=response_body,
        )
    if status_code == 404 and ("model" in lowered_message or error_code == "model_not_found"):
        return HybridTransportError(
            "Model unavailable for selected OpenAI project.",
            category="model_unavailable",
            status_code=status_code,
            response_body=response_body,
        )
    if status_code == 429:
        category = "quota" if error_code == "insufficient_quota" or error_type == "insufficient_quota" else "rate_limit"
        return HybridTransportError(
            message or "OpenAI rejected the request with HTTP 429.",
            category=category,
            status_code=status_code,
            response_body=response_body,
        )
    if status_code >= 500:
        return HybridTransportError(
            message or f"OpenAI returned HTTP {status_code}.",
            category="server_error",
            status_code=status_code,
            response_body=response_body,
        )
    if "model" in lowered_message or error_code == "model_not_found":
        return HybridTransportError(
            "Model unavailable for selected OpenAI project.",
            category="model_unavailable",
            status_code=status_code,
            response_body=response_body,
        )
    return HybridTransportError(
        message or f"OpenAI returned HTTP {status_code}.",
        category="unexpected",
        status_code=status_code,
        response_body=response_body,
    )


def _extract_chat_completion_content(payload: JsonObject) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise HybridTranslationError("OpenAI returned no chat completion choices for Hybrid Accuracy translation.")

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "") == "text" and str(item.get("text") or "").strip():
                text_parts.append(str(item["text"]))
        joined = "\n".join(text_parts).strip()
        if joined:
            return joined
    raise HybridTranslationError(
        "OpenAI returned an empty Hybrid Accuracy translation response.",
    )


def _normalize_segment(segment: dict[str, Any], fallback_id: int) -> JsonObject:
    return {
        "id": int(segment.get("id", fallback_id)),
        "start": float(segment.get("start", 0.0)),
        "end": float(segment.get("end", 0.0)),
        "text": str(segment.get("text", "") or "").strip(),
    }


def _normalize_project(project: str | None) -> str:
    normalized = str(project or "Private").strip().title()
    if normalized not in PROJECT_ENV_VARS:
        raise HybridTranslationError(
            "Hybrid Accuracy only supports OpenAiProject Private or Public.",
        )
    return normalized


def _coerce_target_codes(targets: Any) -> list[str]:
    if targets is None:
        return []
    if isinstance(targets, str):
        return [part.strip().lower() for part in targets.split(",") if part.strip()]
    return [str(item).strip().lower() for item in targets if str(item).strip()]


def _language_label(language_code: str) -> str:
    code = str(language_code or "").strip().lower()
    if not code:
        return "the source language"
    return LANGUAGE_LABELS.get(code, code)


def _estimate_word_count(text: str) -> int:
    return len(_WORD_PATTERN.findall(text))


def _search_normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(character for character in normalized.casefold() if not unicodedata.combining(character))


def _contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    if term.casefold() in text.casefold():
        return True
    return _search_normalized(term) in _search_normalized(text)


def _clip_text(value: str, *, limit: int = 240) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _normalize_translation_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("text", "translation", "translated_text", "value"):
            candidate = value.get(key)
            if str(candidate or "").strip():
                return str(candidate).strip()
        return ""
    return str(value or "").strip()


def _coerce_segment_id(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _strip_code_fences(raw_text: str) -> str:
    match = _FENCED_JSON_PATTERN.match(raw_text.strip())
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def _merge_usage_totals(totals: JsonObject, batch_usage: JsonObject) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        totals[key] = int(totals.get(key) or 0) + int(batch_usage.get(key) or 0)


def estimate_text_cost_usd(model: str, usage: JsonObject) -> float | None:
    pricing = HYBRID_MODEL_PRICING_PER_MILLION_USD.get(str(model or "").strip())
    if not pricing:
        return None
    prompt_tokens = int((usage or {}).get("prompt_tokens") or 0)
    completion_tokens = int((usage or {}).get("completion_tokens") or 0)
    estimated = (
        (prompt_tokens * float(pricing["input"]))
        + (completion_tokens * float(pricing["output"]))
    ) / 1_000_000.0
    return round(estimated, 10)


def validate_hybrid_target_languages(targets: Any) -> list[str]:
    normalized = _coerce_target_codes(targets)
    if not normalized:
        return [HYBRID_DEFAULT_TARGET_LANGUAGE]
    if len(normalized) != 1 or normalized[0] != HYBRID_DEFAULT_TARGET_LANGUAGE:
        raise HybridTranslationError(
            "Hybrid Accuracy currently supports exactly one target language: English ('en').",
        )
    return normalized


def load_source_transcript_segments(transcript_json_path: str | Path) -> JsonObject:
    payload = json.loads(Path(transcript_json_path).read_text(encoding="utf-8-sig"))
    segments = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(payload.get("segments") or [], start=1)
    ]
    return {
        "language": str(payload.get("language", "") or "").strip(),
        "source_language": str(payload.get("source_language", "") or "").strip(),
        "task": str(payload.get("task", "") or "").strip(),
        "text": str(payload.get("text", "") or "").strip(),
        "expected_named_entities": _normalize_expected_named_entities(
            payload.get("expected_named_entities") or [],
        ),
        "segments": segments,
    }


def load_glossary(glossary_path: str | Path) -> JsonObject:
    resolved_path = Path(glossary_path)
    try:
        raw_text = resolved_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise HybridTranslationError(
            f"Hybrid Accuracy protected terms profile file not found: {resolved_path}"
        ) from exc

    payload = json.loads(raw_text)
    payload["profile"] = str(payload.get("profile", "") or "").strip()
    payload["lane_id"] = str(payload.get("lane_id", "") or "").strip()
    terms = payload.get("terms") or []
    payload["terms"] = [
        {
            "source_term": str(term.get("source_term", "") or "").strip(),
            "preferred_translations": [
                str(item).strip()
                for item in (term.get("preferred_translations") or [])
                if str(item).strip()
            ],
            "notes": str(term.get("notes", "") or "").strip(),
            "forbidden_patterns": [
                str(item).strip()
                for item in (term.get("forbidden_patterns") or [])
                if str(item).strip()
            ],
        }
        for term in terms
        if str(term.get("source_term", "") or "").strip()
    ]
    return payload


def _normalize_expected_named_entities(expected_named_entities: Any) -> list[JsonObject]:
    normalized: list[JsonObject] = []
    for item in expected_named_entities or []:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        normalized.append(
            {
                "term": term,
                "category": str(item.get("category") or "").strip(),
                "expected_in_translation": bool(item.get("expected_in_translation")),
                "bad_forms": [
                    str(value).strip()
                    for value in (item.get("bad_forms") or [])
                    if str(value).strip()
                ],
            }
        )
    return normalized


def build_segment_batches(
    source_segments: list[dict[str, Any]],
    *,
    batch_size: int = HYBRID_DEFAULT_BATCH_SIZE,
    context_segments: int = HYBRID_DEFAULT_CONTEXT_SEGMENTS,
) -> list[JsonObject]:
    normalized = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(source_segments, start=1)
    ]
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    batches: list[JsonObject] = []
    for start_index in range(0, len(normalized), batch_size):
        batch_segments = normalized[start_index : start_index + batch_size]
        before = normalized[max(0, start_index - context_segments) : start_index]
        after = normalized[
            start_index + batch_size : start_index + batch_size + context_segments
        ]
        batches.append(
            {
                "batch_index": len(batches) + 1,
                "segment_ids": [segment["id"] for segment in batch_segments],
                "segments": batch_segments,
                "context_before": before,
                "context_after": after,
            }
        )
    return batches


def build_translation_request_payload(
    batch: JsonObject,
    *,
    source_language: str,
    target_language: str,
    glossary: JsonObject,
    model: str,
    expected_named_entities: list[JsonObject] | None = None,
    repair_instructions: list[str] | None = None,
    previous_response_text: str = "",
) -> JsonObject:
    glossary_lines: list[str] = []
    for term in glossary.get("terms") or []:
        source_term = str(term.get("source_term", "") or "").strip()
        if not source_term:
            continue
        preferred = ", ".join(term.get("preferred_translations") or []) or "preserve intent"
        details = [f"{source_term} -> {preferred}"]
        if str(term.get("notes", "") or "").strip():
            details.append(f"note: {term['notes']}")
        forbidden = ", ".join(term.get("forbidden_patterns") or [])
        if forbidden:
            details.append(f"forbidden: {forbidden}")
        glossary_lines.append(" - " + "; ".join(details))

    normalized_expected_named_entities = _normalize_expected_named_entities(expected_named_entities)
    protected_terms_profile = str(glossary.get("profile", "") or "").strip()
    has_protected_terms = bool(glossary_lines)
    system_lines = [
        "You translate transcript batches from the source language into English.",
        "Return one JSON object and nothing else.",
        'Use this schema exactly: {"translations":{"<segment_id>":"<english translation>"}}.',
        "Do not summarize, compress, merge, omit, or reorder segments.",
        "Preserve meaning and speaker intent.",
        "Preserve real place names, track names, product names, brand names, and other proper nouns exactly when they are identifiable from context.",
        "Do not replace a named entity with a nearby-looking English word or place name.",
        (
            "Preserve product, app, brand, UI, and domain terms according to the protected terms profile."
            if has_protected_terms
            else "Preserve product, app, brand, UI, and domain terms when the source context makes them important."
        ),
        "If a source segment is blank, return an empty string for that segment id.",
    ]
    if normalized_expected_named_entities:
        system_lines.append(
            "Expected named entities may be supplied for this file. Keep them exactly as written in English and avoid any listed bad forms.",
        )
    if protected_terms_profile == "de-en-sim-racing":
        system_lines.extend(
            [
                "Treat Crew Chief as an app/product name when the source context indicates the app.",
                f'Known bad example: "{KNOWN_BAD_EXAMPLE_SOURCE}" -> "{KNOWN_BAD_EXAMPLE_GOOD}".',
                f'Do not translate it as "{KNOWN_BAD_EXAMPLE_BAD}"',
                "Keep punctuation, domain terms, and acronyms such as DRS and Full Course Yellow intact when required by context.",
            ]
        )
    if repair_instructions:
        system_lines.append("The previous response failed validation. Fix every listed issue in the retry.")

    user_payload: JsonObject = {
        "task": "Translate transcript segments",
        "source_language": _language_label(source_language),
        "target_language": _language_label(target_language),
        "expected_segment_ids": batch.get("segment_ids") or [],
        "context_before": [
            {"id": item["id"], "text": item["text"]}
            for item in batch.get("context_before") or []
        ],
        "segments": [
            {
                "id": item["id"],
                "start": item["start"],
                "end": item["end"],
                "text": item["text"],
            }
            for item in batch.get("segments") or []
        ],
        "context_after": [
            {"id": item["id"], "text": item["text"]}
            for item in batch.get("context_after") or []
        ],
        "protected_terms_profile": protected_terms_profile,
        "protected_terms_rules": glossary_lines,
        "expected_named_entities": normalized_expected_named_entities,
    }
    if protected_terms_profile == "de-en-sim-racing":
        user_payload["known_bad_example"] = {
            "source": KNOWN_BAD_EXAMPLE_SOURCE,
            "correct_translation": KNOWN_BAD_EXAMPLE_GOOD,
            "incorrect_translation": KNOWN_BAD_EXAMPLE_BAD,
        }
    if repair_instructions:
        user_payload["retry_validation_issues"] = repair_instructions
    if previous_response_text:
        user_payload["previous_response_text"] = previous_response_text

    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "\n".join(system_lines),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ],
        "batch_index": batch.get("batch_index"),
        "expected_segment_ids": list(batch.get("segment_ids") or []),
        "context_before": batch.get("context_before") or [],
        "context_after": batch.get("context_after") or [],
    }


def parse_translation_response(raw_text: str) -> JsonObject:
    normalized = _strip_code_fences(raw_text)
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise HybridTranslationError(
            "Hybrid Accuracy translation did not return valid JSON.",
        ) from exc

    if not isinstance(payload, dict):
        raise HybridTranslationError(
            "Hybrid Accuracy translation JSON must be an object keyed by segment id.",
        )

    translations_payload = payload.get("translations")
    if translations_payload is None:
        translations_payload = payload

    mapping: dict[int, str] = {}
    if isinstance(translations_payload, dict):
        for raw_id, value in translations_payload.items():
            segment_id = _coerce_segment_id(raw_id)
            if segment_id is None:
                continue
            mapping[segment_id] = _normalize_translation_text(value)
    elif isinstance(translations_payload, list):
        for item in translations_payload:
            if not isinstance(item, dict):
                continue
            segment_id = _coerce_segment_id(item.get("id"))
            if segment_id is None:
                continue
            mapping[segment_id] = _normalize_translation_text(item)
    else:
        raise HybridTranslationError(
            "Hybrid Accuracy translation JSON must contain a 'translations' object keyed by segment id.",
        )

    if not mapping:
        raise HybridTranslationError(
            "Hybrid Accuracy translation JSON did not contain any translated segment ids.",
        )

    unexpected_keys = sorted(
        key
        for key in payload.keys()
        if key not in {"translations"} and _coerce_segment_id(key) is None
    )
    return {
        "translations": mapping,
        "unexpected_json_keys": unexpected_keys,
    }


def detect_assistant_meta_contamination(text: str) -> list[str]:
    lowered = text.lower()
    return [pattern for pattern in DEFAULT_ASSISTANT_META_PATTERNS if pattern in lowered]


def detect_mojibake(text: str) -> list[str]:
    return [pattern for pattern in DEFAULT_MOJIBAKE_PATTERNS if pattern in text]


def detect_repeated_or_fragmented_garbage(text: str, *, source_text: str = "") -> list[str]:
    matches: list[str] = []
    repeated_word_match = _REPEATED_WORD_PATTERN.search(text)
    if repeated_word_match:
        repeated_phrase = repeated_word_match.group(0).strip().lower()
        if repeated_phrase not in str(source_text or "").strip().lower():
            matches.append("repeated_word")
    if _REPEATED_CHAR_PATTERN.search(text):
        matches.append("repeated_character")
    if text.strip() and _NON_WORD_COMPRESSION_PATTERN.match(text.strip()):
        matches.append("non_word_only")
    return matches


def detect_glossary_violations(
    source_segments: list[dict[str, Any]],
    translated_segments: list[dict[str, Any]],
    glossary: JsonObject,
) -> list[JsonObject]:
    violations: list[JsonObject] = []
    terms = glossary.get("terms") or []
    translated_lookup = {
        _normalize_segment(segment, fallback_id=index)["id"]: _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(translated_segments, start=1)
    }
    for index, source_segment in enumerate(source_segments, start=1):
        normalized_source = _normalize_segment(source_segment, fallback_id=index)
        translated_segment = translated_lookup.get(normalized_source["id"])
        if not translated_segment:
            continue
        source_text = normalized_source["text"]
        translated_text = translated_segment["text"]
        source_text_lower = source_text.lower()
        translated_text_lower = translated_text.lower()
        for term in terms:
            source_term = str(term.get("source_term", "") or "").strip()
            if not source_term or source_term.lower() not in source_text_lower:
                continue
            preferred = term.get("preferred_translations") or []
            forbidden = term.get("forbidden_patterns") or []
            if preferred and not any(item.lower() in translated_text_lower for item in preferred):
                violations.append(
                    {
                        "segment_id": normalized_source["id"],
                        "source_term": source_term,
                        "issue": "missing_preferred_translation",
                        "translation_text": translated_text,
                    }
                )
            for pattern in forbidden:
                if pattern.lower() in translated_text_lower:
                    violations.append(
                        {
                            "segment_id": normalized_source["id"],
                            "source_term": source_term,
                            "issue": "forbidden_translation_pattern",
                            "translation_text": translated_text,
                            "forbidden_pattern": pattern,
                        }
                    )
    return violations


def detect_named_entity_violations(
    translated_segments: list[dict[str, Any]],
    expected_named_entities: list[JsonObject] | None,
    *,
    enforce_expected_in_translation: bool = False,
) -> list[JsonObject]:
    violations: list[JsonObject] = []
    normalized_expected = _normalize_expected_named_entities(expected_named_entities)
    if not normalized_expected:
        return violations

    normalized_translated = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(translated_segments, start=1)
    ]
    combined_translation_text = "\n".join(
        segment["text"] for segment in normalized_translated if segment["text"]
    )

    for item in normalized_expected:
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        bad_forms = [str(value).strip() for value in (item.get("bad_forms") or []) if str(value).strip()]
        bad_form_matches = [value for value in bad_forms if _contains_term(combined_translation_text, value)]
        translation_present = _contains_term(combined_translation_text, term)
        if not bad_form_matches and not (
            enforce_expected_in_translation
            and bool(item.get("expected_in_translation"))
            and not translation_present
        ):
            continue

        matching_segment_ids = sorted(
            {
                segment["id"]
                for segment in normalized_translated
                if any(_contains_term(segment["text"], candidate) for candidate in [term, *bad_forms])
            }
        )
        issues: list[str] = []
        if enforce_expected_in_translation and bool(item.get("expected_in_translation")) and not translation_present:
            issues.append("missing from English translation")
        if bad_form_matches:
            issues.append("bad form in English translation")

        violations.append(
            {
                "term": term,
                "category": str(item.get("category") or "").strip(),
                "translation_present": translation_present,
                "bad_form_matches": bad_form_matches,
                "matching_segment_ids": matching_segment_ids,
                "issue": "; ".join(issues),
            }
        )

    return violations


def _collect_segment_warning(
    warning_map: dict[int, list[JsonObject]],
    *,
    segment_id: int,
    issue: str,
    detail: JsonObject,
) -> None:
    warning_map.setdefault(segment_id, []).append({"issue": issue, **detail})


def validate_translated_segments(
    source_segments: list[dict[str, Any]],
    translated_segments: list[dict[str, Any]],
    *,
    glossary: JsonObject | None = None,
    expected_named_entities: list[JsonObject] | None = None,
    enforce_expected_entity_presence: bool = False,
    unexpected_segment_ids: list[int] | None = None,
) -> JsonObject:
    normalized_source = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(source_segments, start=1)
    ]
    normalized_translated = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(translated_segments, start=1)
    ]
    source_ids = [segment["id"] for segment in normalized_source]
    source_id_set = set(source_ids)
    translated_ids = [segment["id"] for segment in normalized_translated]
    translated_lookup = {segment["id"]: segment for segment in normalized_translated}

    errors: list[str] = []
    warning_map: dict[int, list[JsonObject]] = {}
    unexpected_ids = sorted(
        {
            coerced
            for item in (unexpected_segment_ids or [])
            for coerced in [_coerce_segment_id(item)]
            if coerced is not None
        }
    )
    missing_ids = [segment_id for segment_id in source_ids if segment_id not in translated_lookup]
    if missing_ids:
        errors.append(
            "Missing translated segment ids: "
            + ", ".join(str(segment_id) for segment_id in missing_ids),
        )

    translated_known_ids = [segment_id for segment_id in translated_ids if segment_id in source_id_set]
    order_preserved = translated_known_ids == [segment_id for segment_id in source_ids if segment_id in translated_lookup]
    if not order_preserved:
        errors.append("Translated segment order changed.")

    timestamps_preserved = True
    empty_translation_matches: list[JsonObject] = []
    contamination_matches: list[JsonObject] = []
    mojibake_matches: list[JsonObject] = []
    compression_warnings: list[JsonObject] = []
    garbage_pattern_matches: list[JsonObject] = []

    source_lookup = {segment["id"]: segment for segment in normalized_source}
    for source_segment in normalized_source:
        translated_segment = translated_lookup.get(source_segment["id"])
        if not translated_segment:
            continue
        if (
            source_segment["start"] != translated_segment["start"]
            or source_segment["end"] != translated_segment["end"]
        ):
            timestamps_preserved = False
            errors.append(
                f"Translated segment timestamps changed for segment id {source_segment['id']}.",
            )

        text = translated_segment["text"]
        if source_segment["text"] and not text:
            empty_record = {
                "segment_id": translated_segment["id"],
                "text": text,
            }
            empty_translation_matches.append(empty_record)
            _collect_segment_warning(
                warning_map,
                segment_id=translated_segment["id"],
                issue="empty_translation",
                detail={},
            )

        contamination = detect_assistant_meta_contamination(text)
        if contamination:
            contamination_record = {
                "segment_id": translated_segment["id"],
                "matches": contamination,
                "text": text,
            }
            contamination_matches.append(contamination_record)
            _collect_segment_warning(
                warning_map,
                segment_id=translated_segment["id"],
                issue="assistant_meta_contamination",
                detail={"matches": contamination},
            )

        mojibake = detect_mojibake(text)
        if mojibake:
            mojibake_record = {
                "segment_id": translated_segment["id"],
                "matches": mojibake,
                "text": text,
            }
            mojibake_matches.append(mojibake_record)
            _collect_segment_warning(
                warning_map,
                segment_id=translated_segment["id"],
                issue="mojibake",
                detail={"matches": mojibake},
            )

        garbage_matches = detect_repeated_or_fragmented_garbage(
            text,
            source_text=source_segment["text"],
        )
        if garbage_matches:
            garbage_record = {
                "segment_id": translated_segment["id"],
                "matches": garbage_matches,
                "text": text,
            }
            garbage_pattern_matches.append(garbage_record)
            _collect_segment_warning(
                warning_map,
                segment_id=translated_segment["id"],
                issue="garbage_pattern",
                detail={"matches": garbage_matches},
            )

        source_words = _estimate_word_count(source_segment["text"])
        translated_words = _estimate_word_count(text)
        if source_words >= 4 and translated_words <= max(1, math.floor(source_words * 0.33)):
            compression_record = {
                "segment_id": translated_segment["id"],
                "source_word_count": source_words,
                "translated_word_count": translated_words,
                "source_text": source_segment["text"],
                "translation_text": text,
            }
            compression_warnings.append(compression_record)
            _collect_segment_warning(
                warning_map,
                segment_id=translated_segment["id"],
                issue="compression_warning",
                detail={
                    "source_word_count": source_words,
                    "translated_word_count": translated_words,
                },
            )

    glossary_violations = detect_glossary_violations(
        normalized_source,
        normalized_translated,
        glossary or {"terms": []},
    )
    for violation in glossary_violations:
        _collect_segment_warning(
            warning_map,
            segment_id=int(violation["segment_id"]),
            issue=str(violation["issue"]),
            detail={
                "source_term": violation.get("source_term"),
                "forbidden_pattern": violation.get("forbidden_pattern"),
            },
        )

    named_entity_violations = detect_named_entity_violations(
        normalized_translated,
        expected_named_entities,
        enforce_expected_in_translation=enforce_expected_entity_presence,
    )
    for violation in named_entity_violations:
        for segment_id in violation.get("matching_segment_ids") or []:
            _collect_segment_warning(
                warning_map,
                segment_id=int(segment_id),
                issue="named_entity_violation",
                detail={
                    "term": violation.get("term"),
                    "bad_form_matches": violation.get("bad_form_matches"),
                },
            )

    segment_warnings = [
        {
            "segment_id": segment_id,
            "warnings": warnings,
        }
        for segment_id, warnings in sorted(warning_map.items())
    ]
    source_word_count = sum(_estimate_word_count(segment["text"]) for segment in normalized_source)
    translated_word_count = sum(_estimate_word_count(segment["text"]) for segment in normalized_translated)
    english_source_ratio = (
        round(translated_word_count / source_word_count, 4)
        if source_word_count
        else None
    )

    warning_count = (
        len(segment_warnings)
        + len(glossary_violations)
        + len(named_entity_violations)
        + len(unexpected_ids)
    )
    valid = (
        not errors
        and not empty_translation_matches
        and not contamination_matches
        and not mojibake_matches
        and not glossary_violations
        and not named_entity_violations
        and not compression_warnings
        and not garbage_pattern_matches
    )

    return {
        "shape_ok": not errors,
        "valid": valid,
        "order_preserved": order_preserved,
        "timestamps_preserved": timestamps_preserved,
        "source_segment_count": len(normalized_source),
        "translated_segment_count": len(normalized_translated),
        "missing_segment_ids": missing_ids,
        "unexpected_segment_ids": unexpected_ids,
        "errors": errors,
        "warning_count": warning_count,
        "segment_warnings": segment_warnings,
        "empty_translation_matches": empty_translation_matches,
        "empty_translation_count": len(empty_translation_matches),
        "contamination_matches": contamination_matches,
        "contamination_count": len(contamination_matches),
        "mojibake_matches": mojibake_matches,
        "mojibake_count": len(mojibake_matches),
        "encoding_artifact_matches": mojibake_matches,
        "encoding_artifact_count": len(mojibake_matches),
        "glossary_violations": glossary_violations,
        "glossary_violation_count": len(glossary_violations),
        "named_entity_violations": named_entity_violations,
        "named_entity_violation_count": len(named_entity_violations),
        "compression_warnings": compression_warnings,
        "compression_warning_count": len(compression_warnings),
        "garbage_pattern_matches": garbage_pattern_matches,
        "garbage_pattern_count": len(garbage_pattern_matches),
        "source_word_count": source_word_count,
        "translated_word_count": translated_word_count,
        "english_source_ratio": english_source_ratio,
        "validated_segment_ids": [
            segment["id"] for segment in normalized_source if segment["id"] in translated_lookup
        ],
    }


def write_validation_report(report: JsonObject, output_report_path: str | Path) -> Path:
    destination = Path(output_report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def write_translation_artifacts(
    translated_segments: list[dict[str, Any]],
    *,
    output_dir: str | Path,
    source_language: str,
    target_language: str,
    glossary: JsonObject,
    validation_status: str,
    model_resolution: ModelResolution,
) -> dict[str, str]:
    payload = {
        "language": target_language,
        "source_language": source_language,
        "task": "translate",
        "privacy_class": HYBRID_PRIVACY_CLASS,
        "lane_id": str(glossary.get("lane_id") or ""),
        "glossary_profile": str(glossary.get("profile") or ""),
        "validation_status": validation_status,
        "requested_model": model_resolution.requested_model,
        "translation_model": model_resolution.used_model,
        "segments": translated_segments,
        "text": " ".join(
            segment["text"]
            for segment in translated_segments
            if str(segment.get("text") or "").strip()
        ).strip(),
    }
    json_path, srt_path, text_path = write_transcript_files(
        output_dir,
        "transcript.json",
        "transcript.srt",
        "transcript.txt",
        payload,
    )
    return {
        "transcript_json_path": str(json_path),
        "transcript_srt_path": str(srt_path),
        "transcript_txt_path": str(text_path),
    }


def get_api_key_for_project(
    project: str,
    *,
    env: dict[str, str] | None = None,
) -> str:
    normalized_project = _normalize_project(project)
    variable_name = PROJECT_ENV_VARS[normalized_project]
    source = env if env is not None else os.environ
    value = str(source.get(variable_name) or "").strip()
    if not value:
        raise HybridTranslationError(
            f"Hybrid Accuracy translation needs {variable_name} for OpenAiProject {normalized_project}.",
        )
    return value


def resolve_model_selection(
    *,
    project: str,
    requested_model: str = "",
    transport: TranslationTransport,
) -> ModelResolution:
    normalized_project = _normalize_project(project)
    config = HYBRID_MODEL_CONFIG[normalized_project]
    approved_models = [str(model).strip() for model in config["approved_models"]]
    default_model = str(config["default"]).strip()
    explicit_request = str(requested_model or "").strip()
    if explicit_request and explicit_request not in approved_models:
        raise HybridTranslationError(
            f"Requested Hybrid Accuracy model '{explicit_request}' is not approved for {normalized_project}. "
            f"Approved models: {', '.join(approved_models)}",
        )

    accessible_models: list[str] = []
    discovery_status = "success"
    warning = ""
    try:
        visible_model_ids = transport.list_models()
        visible_lookup = {model_id.strip().lower() for model_id in visible_model_ids}
        accessible_models = [
            model
            for model in approved_models
            if model.strip().lower() in visible_lookup
        ]
    except HybridTransportError as exc:
        if exc.category in {"unauthorized", "permission_denied", "model_unavailable"}:
            raise
        discovery_status = "fallback"
        warning = str(exc)

    requested_effective = explicit_request or default_model
    if accessible_models:
        if explicit_request:
            if explicit_request not in accessible_models:
                raise HybridTranslationError("Model unavailable for selected OpenAI project.")
            return ModelResolution(
                requested_model=explicit_request,
                used_model=explicit_request,
                approved_models=approved_models,
                accessible_models=accessible_models,
                selection_source="explicit",
                discovery_status=discovery_status,
                warning=warning,
            )
        if default_model in accessible_models:
            return ModelResolution(
                requested_model=default_model,
                used_model=default_model,
                approved_models=approved_models,
                accessible_models=accessible_models,
                selection_source="default",
                discovery_status=discovery_status,
                warning=warning,
            )
        return ModelResolution(
            requested_model=default_model,
            used_model=accessible_models[0],
            approved_models=approved_models,
            accessible_models=accessible_models,
            selection_source="fallback-accessible",
            discovery_status=discovery_status,
            warning=warning or "Hybrid Accuracy default model was unavailable, so another approved visible model was selected.",
        )

    if discovery_status == "success":
        raise HybridTranslationError("Model unavailable for selected OpenAI project.")

    return ModelResolution(
        requested_model=requested_effective,
        used_model=requested_effective,
        approved_models=approved_models,
        accessible_models=[],
        selection_source="explicit-unverified" if explicit_request else "default-unverified",
        discovery_status=discovery_status,
        warning=warning,
    )


def _build_translated_segments_from_mapping(
    batch_segments: list[dict[str, Any]],
    translation_mapping: dict[int, str],
) -> tuple[list[JsonObject], list[int], list[int]]:
    expected_ids = [segment["id"] for segment in batch_segments]
    translated_segments: list[JsonObject] = []
    missing_ids: list[int] = []
    for segment in batch_segments:
        segment_id = segment["id"]
        if segment_id not in translation_mapping:
            missing_ids.append(segment_id)
            continue
        translated_segments.append(
            {
                "id": segment_id,
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": str(translation_mapping[segment_id] or "").strip(),
            }
        )

    unexpected_ids = sorted(
        segment_id
        for segment_id in translation_mapping
        if segment_id not in set(expected_ids)
    )
    return translated_segments, missing_ids, unexpected_ids


def _build_retry_instructions(validation: JsonObject) -> list[str]:
    instructions: list[str] = []
    if validation.get("missing_segment_ids"):
        instructions.append(
            "Return every expected segment id exactly once: "
            + ", ".join(str(item) for item in validation["missing_segment_ids"]),
        )
    if validation.get("empty_translation_count"):
        instructions.append("Do not leave translated text empty.")
    if validation.get("contamination_count"):
        instructions.append("Remove assistant chatter, labels, and meta commentary.")
    if validation.get("mojibake_count"):
        instructions.append("Remove mojibake or broken encoding artifacts.")
    if validation.get("glossary_violation_count"):
        instructions.append("Follow the protected terms profile exactly for protected product and UI terms.")
    if validation.get("named_entity_violation_count"):
        named_entity_violations = validation.get("named_entity_violations") or []
        terms = list(
            dict.fromkeys(
                str(item.get("term") or "").strip()
                for item in named_entity_violations
                if str(item.get("term") or "").strip()
            )
        )
        bad_forms = list(
            dict.fromkeys(
                str(match).strip()
                for item in named_entity_violations
                for match in (item.get("bad_form_matches") or [])
                if str(match).strip()
            )
        )
        instruction = "Preserve expected named entities exactly"
        if terms:
            instruction += ": " + ", ".join(terms)
        instruction += "."
        if bad_forms:
            instruction += " Do not use these bad forms: " + ", ".join(bad_forms) + "."
        instructions.append(instruction)
    if validation.get("compression_warning_count"):
        instructions.append("Do not summarize or compress the meaning.")
    if validation.get("garbage_pattern_count"):
        instructions.append("Remove repeated or fragmented garbage patterns.")
    if validation.get("unexpected_segment_ids"):
        instructions.append("Do not invent extra segment ids.")
    if not instructions:
        instructions.append("Return clean JSON keyed by segment id with one English translation per segment.")
    return instructions


def _build_single_segment_recovery_batches(
    batch: JsonObject,
    *,
    context_segments: int = HYBRID_DEFAULT_CONTEXT_SEGMENTS,
) -> list[JsonObject]:
    normalized_context_before = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(batch.get("context_before") or [], start=1)
    ]
    normalized_segments = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(batch.get("segments") or [], start=1)
    ]
    normalized_context_after = [
        _normalize_segment(segment, fallback_id=index)
        for index, segment in enumerate(batch.get("context_after") or [], start=1)
    ]
    if len(normalized_segments) <= 1:
        return [batch]

    all_segments = normalized_context_before + normalized_segments + normalized_context_after
    start_offset = len(normalized_context_before)
    recovery_batches: list[JsonObject] = []

    for segment_offset, segment in enumerate(normalized_segments):
        position = start_offset + segment_offset
        recovery_batches.append(
            {
                "batch_index": f"{batch.get('batch_index')}.{segment_offset + 1}",
                "parent_batch_index": batch.get("batch_index"),
                "segment_ids": [segment["id"]],
                "segments": [segment],
                "context_before": all_segments[max(0, position - context_segments) : position],
                "context_after": all_segments[position + 1 : position + 1 + context_segments],
            }
        )

    return recovery_batches


def _translate_batch(
    batch: JsonObject,
    *,
    source_language: str,
    target_language: str,
    glossary: JsonObject,
    expected_named_entities: list[JsonObject] | None,
    model_resolution: ModelResolution,
    transport: TranslationTransport,
) -> JsonObject:
    raw_response_text = ""
    batch_usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    retry_used = False
    attempt_details: list[JsonObject] = []

    expected_ids = list(batch.get("segment_ids") or [])
    for attempt_index in range(1, 3):
        request_payload = build_translation_request_payload(
            batch,
            source_language=source_language,
            target_language=target_language,
            glossary=glossary,
            model=model_resolution.used_model,
            expected_named_entities=expected_named_entities,
            repair_instructions=(
                _build_retry_instructions(attempt_details[-1]["validation"])
                if attempt_details and attempt_details[-1].get("validation")
                else None
            ),
            previous_response_text=raw_response_text if attempt_details else "",
        )

        try:
            response_payload = transport.translate_chat_completion(
                model=model_resolution.used_model,
                messages=request_payload["messages"],
            )
        except HybridTransportError as exc:
            if exc.category in {"model_unavailable", "unauthorized", "permission_denied"}:
                raise
            batch_result = {
                "batch_index": batch["batch_index"],
                "segment_ids": expected_ids,
                "status": "failed",
                "retry_used": retry_used,
                "attempt_count": attempt_index,
                "error": str(exc),
                "error_category": exc.category,
                "usage": dict(batch_usage_totals),
                "validation": {
                    "valid": False,
                    "shape_ok": False,
                    "errors": [str(exc)],
                    "warning_count": 1,
                    "source_segment_count": len(batch.get("segments") or []),
                    "translated_segment_count": 0,
                    "missing_segment_ids": expected_ids,
                    "unexpected_segment_ids": [],
                    "contamination_count": 0,
                    "mojibake_count": 0,
                    "glossary_violation_count": 0,
                    "named_entity_violation_count": 0,
                    "compression_warning_count": 0,
                    "garbage_pattern_count": 0,
                    "empty_translation_count": 0,
                    "segment_warnings": [],
                    "source_word_count": sum(
                        _estimate_word_count(str(item.get("text") or ""))
                        for item in batch.get("segments") or []
                    ),
                    "translated_word_count": 0,
                    "english_source_ratio": 0.0,
                },
                "translated_segments": [],
            }
            return batch_result

        raw_response_text = str(response_payload.get("content") or "").strip()
        usage = response_payload.get("usage") or {}
        _merge_usage_totals(batch_usage_totals, usage)

        try:
            parsed_response = parse_translation_response(raw_response_text)
            translation_mapping = parsed_response["translations"]
            translated_segments, missing_ids, unexpected_ids = _build_translated_segments_from_mapping(
                batch.get("segments") or [],
                translation_mapping,
            )
            validation = validate_translated_segments(
                batch.get("segments") or [],
                translated_segments,
                glossary=glossary,
                expected_named_entities=expected_named_entities,
                unexpected_segment_ids=unexpected_ids,
            )
        except HybridTranslationError as exc:
            validation = {
                "valid": False,
                "shape_ok": False,
                "errors": [str(exc)],
                "warning_count": 1,
                "source_segment_count": len(batch.get("segments") or []),
                "translated_segment_count": 0,
                "missing_segment_ids": expected_ids,
                "unexpected_segment_ids": [],
                "contamination_count": 0,
                "mojibake_count": 0,
                "glossary_violation_count": 0,
                "named_entity_violation_count": 0,
                "compression_warning_count": 0,
                "garbage_pattern_count": 0,
                "empty_translation_count": 0,
                "segment_warnings": [],
                "source_word_count": sum(
                    _estimate_word_count(str(item.get("text") or ""))
                    for item in batch.get("segments") or []
                ),
                "translated_word_count": 0,
                "english_source_ratio": 0.0,
            }
            translated_segments = []

        attempt_details.append(
            {
                "attempt": attempt_index,
                "raw_response_preview": _clip_text(raw_response_text),
                "validation": validation,
            }
        )
        if validation.get("valid"):
            return {
                "batch_index": batch["batch_index"],
                "segment_ids": expected_ids,
                "status": "accepted",
                "retry_used": retry_used,
                "attempt_count": attempt_index,
                "usage": dict(batch_usage_totals),
                "validation": validation,
                "translated_segments": translated_segments,
                "attempts": attempt_details,
            }

        if attempt_index == 1:
            retry_used = True
            continue

    final_validation = attempt_details[-1]["validation"] if attempt_details else {
        "valid": False,
        "shape_ok": False,
        "errors": ["Hybrid Accuracy translation failed before validation completed."],
        "warning_count": 1,
    }
    return {
        "batch_index": batch["batch_index"],
        "segment_ids": expected_ids,
        "status": "failed",
        "retry_used": retry_used,
        "attempt_count": len(attempt_details),
        "usage": dict(batch_usage_totals),
        "validation": final_validation,
        "translated_segments": [],
        "attempts": attempt_details,
        "error": "; ".join(final_validation.get("errors") or []),
    }


def _translate_batch_with_single_segment_recovery(
    batch: JsonObject,
    *,
    source_language: str,
    target_language: str,
    glossary: JsonObject,
    expected_named_entities: list[JsonObject] | None,
    model_resolution: ModelResolution,
    transport: TranslationTransport,
    context_segments: int,
) -> JsonObject:
    primary_result = _translate_batch(
        batch,
        source_language=source_language,
        target_language=target_language,
        glossary=glossary,
        expected_named_entities=expected_named_entities,
        model_resolution=model_resolution,
        transport=transport,
    )
    if primary_result.get("status") == "accepted":
        primary_result["split_recovery_used"] = False
        primary_result["failed_segment_ids"] = []
        return primary_result

    expected_ids = list(batch.get("segment_ids") or [])
    if (
        len(batch.get("segments") or []) <= 1
        or str(primary_result.get("error_category") or "").strip()
    ):
        primary_result["split_recovery_used"] = False
        primary_result["failed_segment_ids"] = expected_ids
        return primary_result

    recovery_batches = _build_single_segment_recovery_batches(
        batch,
        context_segments=context_segments,
    )
    recovery_results: list[JsonObject] = []
    recovered_segments: list[JsonObject] = []
    recovered_segment_ids: list[int] = []
    failed_segment_ids: list[int] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    _merge_usage_totals(usage_totals, primary_result.get("usage") or {})
    retry_used = bool(primary_result.get("retry_used"))

    for recovery_batch in recovery_batches:
        recovery_result = _translate_batch(
            recovery_batch,
            source_language=source_language,
            target_language=target_language,
            glossary=glossary,
            expected_named_entities=expected_named_entities,
            model_resolution=model_resolution,
            transport=transport,
        )
        recovery_results.append(recovery_result)
        retry_used = retry_used or bool(recovery_result.get("retry_used"))
        _merge_usage_totals(usage_totals, recovery_result.get("usage") or {})
        if recovery_result.get("status") == "accepted":
            translated_segments = recovery_result.get("translated_segments") or []
            recovered_segments.extend(translated_segments)
            recovered_segment_ids.extend(int(item["id"]) for item in translated_segments)
            continue
        failed_segment_ids.extend(int(item) for item in (recovery_result.get("segment_ids") or []))

    if recovered_segments:
        expected_order = {segment_id: index for index, segment_id in enumerate(expected_ids)}
        recovered_segments.sort(key=lambda item: expected_order.get(int(item["id"]), len(expected_order)))
    validation = validate_translated_segments(
        batch.get("segments") or [],
        recovered_segments,
        glossary=glossary,
        expected_named_entities=expected_named_entities,
    )

    failure_messages = [
        str(item.get("error") or "").strip()
        for item in recovery_results
        if item.get("status") != "accepted" and str(item.get("error") or "").strip()
    ]
    status = (
        "accepted"
        if validation.get("valid") and not failed_segment_ids
        else "partial"
        if recovered_segments
        else "failed"
    )
    return {
        "batch_index": batch["batch_index"],
        "segment_ids": expected_ids,
        "status": status,
        "retry_used": retry_used,
        "split_recovery_used": True,
        "split_recovery_strategy": "single-segment",
        "attempt_count": int(primary_result.get("attempt_count") or 0)
        + sum(int(item.get("attempt_count") or 0) for item in recovery_results),
        "usage": usage_totals,
        "validation": validation,
        "translated_segments": recovered_segments,
        "recovered_segment_ids": sorted(set(recovered_segment_ids)),
        "failed_segment_ids": sorted(set(failed_segment_ids)),
        "attempts": primary_result.get("attempts") or [],
        "recovery_results": recovery_results,
        "initial_batch_result": {
            "status": primary_result.get("status"),
            "validation": primary_result.get("validation"),
            "error": str(primary_result.get("error") or ""),
        },
        "error": "; ".join(failure_messages),
    }


def run_hybrid_translation(
    *,
    transcript_json_path: str | Path,
    output_dir: str | Path,
    glossary_path: str | Path | None = None,
    source_language: str = "",
    target_language: str = HYBRID_DEFAULT_TARGET_LANGUAGE,
    openai_project: str = "Private",
    requested_model: str = "",
    expected_named_entities: list[JsonObject] | None = None,
    batch_size: int = HYBRID_DEFAULT_BATCH_SIZE,
    context_segments: int = HYBRID_DEFAULT_CONTEXT_SEGMENTS,
    transport: TranslationTransport | None = None,
    output_report_path: str | Path | None = None,
    estimated_cost_usd: float | None = None,
) -> JsonObject:
    target_languages = validate_hybrid_target_languages([target_language])
    normalized_project = _normalize_project(openai_project)
    transcript = load_source_transcript_segments(transcript_json_path)
    source_segments = transcript["segments"]
    if not source_segments:
        raise HybridTranslationError(
            "Hybrid Accuracy translation needs a source transcript with at least one segment.",
        )

    resolved_glossary_path = str(glossary_path or "").strip()
    glossary = load_glossary(resolved_glossary_path) if resolved_glossary_path else {"profile": "", "lane_id": "", "terms": []}
    normalized_expected_named_entities = _normalize_expected_named_entities(
        expected_named_entities or transcript.get("expected_named_entities") or [],
    )
    normalized_source_language = (
        str(source_language or "").strip().lower()
        or str(transcript.get("source_language") or "").strip().lower()
        or str(transcript.get("language") or "").strip().lower()
        or "unknown"
    )

    effective_transport = transport
    if effective_transport is None:
        api_key = get_api_key_for_project(normalized_project)
        effective_transport = OpenAiChatCompletionsTransport(api_key=api_key)

    model_resolution = resolve_model_selection(
        project=normalized_project,
        requested_model=requested_model,
        transport=effective_transport,
    )
    batches = build_segment_batches(
        source_segments,
        batch_size=int(batch_size or HYBRID_DEFAULT_BATCH_SIZE),
        context_segments=int(context_segments or HYBRID_DEFAULT_CONTEXT_SEGMENTS),
    )

    batch_results: list[JsonObject] = []
    accepted_translated_segments: list[JsonObject] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    warnings: list[str] = []
    retry_used = False
    split_recovery_used = False
    failed_segment_ids: list[int] = []

    for batch in batches:
        batch_result = _translate_batch_with_single_segment_recovery(
            batch,
            source_language=normalized_source_language,
            target_language=target_languages[0],
            glossary=glossary,
            expected_named_entities=normalized_expected_named_entities,
            model_resolution=model_resolution,
            transport=effective_transport,
            context_segments=int(context_segments or HYBRID_DEFAULT_CONTEXT_SEGMENTS),
        )
        batch_results.append(batch_result)
        retry_used = retry_used or bool(batch_result.get("retry_used"))
        split_recovery_used = split_recovery_used or bool(batch_result.get("split_recovery_used"))
        _merge_usage_totals(usage_totals, batch_result.get("usage") or {})
        if batch_result.get("translated_segments"):
            accepted_translated_segments.extend(batch_result.get("translated_segments") or [])
        if batch_result.get("status") != "accepted":
            failed_segment_ids.extend(
                int(item)
                for item in (
                    batch_result.get("failed_segment_ids")
                    or batch_result.get("segment_ids")
                    or []
                )
            )
            if str(batch_result.get("error") or "").strip():
                warnings.append(str(batch_result["error"]))

    failed_segment_ids = sorted(set(failed_segment_ids))
    overall_validation = validate_translated_segments(
        [
            segment
            for segment in source_segments
            if segment["id"] in {item["id"] for item in accepted_translated_segments}
        ],
        accepted_translated_segments,
        glossary=glossary,
        expected_named_entities=normalized_expected_named_entities,
        enforce_expected_entity_presence=True,
    )
    has_full_segment_coverage = len(accepted_translated_segments) == len(source_segments)
    validation_status = (
        "accepted"
        if has_full_segment_coverage and overall_validation.get("valid")
        else "rejected"
        if not accepted_translated_segments or has_full_segment_coverage
        else "partial"
    )
    resolved_estimated_cost_usd = (
        estimated_cost_usd
        if estimated_cost_usd is not None
        else estimate_text_cost_usd(model_resolution.used_model, usage_totals)
    )
    failed_batch_count = sum(1 for item in batch_results if item.get("status") != "accepted")
    failed_batch_validations = [
        item.get("validation") or {}
        for item in batch_results
        if item.get("status") != "accepted"
    ]
    failed_batch_segment_warnings = [
        warning
        for validation in failed_batch_validations
        for warning in (validation.get("segment_warnings") or [])
    ]
    failed_batch_contamination_matches = [
        match
        for validation in failed_batch_validations
        for match in (validation.get("contamination_matches") or [])
    ]
    failed_batch_mojibake_matches = [
        match
        for validation in failed_batch_validations
        for match in (validation.get("mojibake_matches") or [])
    ]
    failed_batch_glossary_violations = [
        match
        for validation in failed_batch_validations
        for match in (validation.get("glossary_violations") or [])
    ]
    failed_batch_compression_warnings = [
        match
        for validation in failed_batch_validations
        for match in (validation.get("compression_warnings") or [])
    ]
    failed_batch_garbage_matches = [
        match
        for validation in failed_batch_validations
        for match in (validation.get("garbage_pattern_matches") or [])
    ]

    artifact_paths = write_translation_artifacts(
        accepted_translated_segments,
        output_dir=output_dir,
        source_language=normalized_source_language,
        target_language=target_languages[0],
        glossary=glossary,
        validation_status=validation_status,
        model_resolution=model_resolution,
    )

    report: JsonObject = {
        "lane_id": str(glossary.get("lane_id") or ""),
        "source_language": normalized_source_language,
        "target_language": target_languages[0],
        "glossary_path": resolved_glossary_path,
        "glossary_profile": str(glossary.get("profile") or ""),
        "protected_terms_path": resolved_glossary_path,
        "protected_terms_profile": str(glossary.get("profile") or ""),
        "expected_named_entities": normalized_expected_named_entities,
        "privacy_class": HYBRID_PRIVACY_CLASS,
        "segment_count": len(source_segments),
        "translated_segment_count": len(accepted_translated_segments),
        "failed_segment_count": len(failed_segment_ids),
        "failed_segment_ids": failed_segment_ids,
        "failed_batch_count": failed_batch_count,
        "validation_status": validation_status,
        "output_status": validation_status,
        "warning_count": int(overall_validation.get("warning_count") or 0)
        + sum(int(item.get("warning_count") or 0) for item in failed_batch_validations)
        + len(warnings),
        "contamination_count": int(overall_validation.get("contamination_count") or 0)
        + sum(int(item.get("contamination_count") or 0) for item in failed_batch_validations),
        "mojibake_count": int(overall_validation.get("mojibake_count") or 0)
        + sum(int(item.get("mojibake_count") or 0) for item in failed_batch_validations),
        "encoding_artifact_count": int(overall_validation.get("encoding_artifact_count") or 0)
        + sum(int(item.get("encoding_artifact_count") or 0) for item in failed_batch_validations),
        "glossary_violation_count": int(overall_validation.get("glossary_violation_count") or 0)
        + sum(int(item.get("glossary_violation_count") or 0) for item in failed_batch_validations),
        "protected_terms_violation_count": int(overall_validation.get("glossary_violation_count") or 0)
        + sum(int(item.get("glossary_violation_count") or 0) for item in failed_batch_validations),
        "named_entity_violation_count": int(overall_validation.get("named_entity_violation_count") or 0)
        + sum(int(item.get("named_entity_violation_count") or 0) for item in failed_batch_validations),
        "compression_warning_count": int(overall_validation.get("compression_warning_count") or 0)
        + sum(int(item.get("compression_warning_count") or 0) for item in failed_batch_validations),
        "garbage_pattern_count": int(overall_validation.get("garbage_pattern_count") or 0)
        + sum(int(item.get("garbage_pattern_count") or 0) for item in failed_batch_validations),
        "segment_warnings": (overall_validation.get("segment_warnings") or []) + failed_batch_segment_warnings,
        "per_batch_results": batch_results,
        "retry_used": retry_used,
        "split_recovery_used": split_recovery_used,
        "requested_model": model_resolution.requested_model,
        "used_model": model_resolution.used_model,
        "translation_model": model_resolution.used_model,
        "model_resolution": model_resolution.to_dict(),
        "openai_project": normalized_project,
        "usage": usage_totals,
        "estimated_cost_usd": resolved_estimated_cost_usd,
        "source_word_count": sum(_estimate_word_count(segment["text"]) for segment in source_segments),
        "translated_word_count": sum(_estimate_word_count(segment["text"]) for segment in accepted_translated_segments),
        "english_source_ratio": (
            round(
                sum(_estimate_word_count(segment["text"]) for segment in accepted_translated_segments)
                / max(1, sum(_estimate_word_count(segment["text"]) for segment in source_segments)),
                4,
            )
            if source_segments
            else None
        ),
        "transcript_artifacts": artifact_paths,
        "accepted_segment_ids": [segment["id"] for segment in accepted_translated_segments],
        "errors": warnings,
        "contamination_matches": (overall_validation.get("contamination_matches") or []) + failed_batch_contamination_matches,
        "mojibake_matches": (overall_validation.get("mojibake_matches") or []) + failed_batch_mojibake_matches,
        "glossary_violations": (overall_validation.get("glossary_violations") or []) + failed_batch_glossary_violations,
        "named_entity_violations": (overall_validation.get("named_entity_violations") or []),
        "compression_warnings": (overall_validation.get("compression_warnings") or []) + failed_batch_compression_warnings,
        "garbage_pattern_matches": (overall_validation.get("garbage_pattern_matches") or []) + failed_batch_garbage_matches,
        "shape_ok": bool(overall_validation.get("shape_ok")),
        "accepted": validation_status == "accepted",
    }

    report_path = write_validation_report(
        report,
        output_report_path or (Path(output_dir) / "validation_report.json"),
    )
    report["validation_report_path"] = str(report_path)
    return report


def validate_from_request(payload: JsonObject) -> JsonObject:
    transcript_json_path = payload.get("transcript_json_path")
    source_segments_payload = payload.get("source_segments")
    translated_segments_payload = payload.get("translated_segments") or []
    glossary_path = payload.get("glossary_path")
    output_report_path = payload.get("output_report_path")

    if transcript_json_path:
        transcript = load_source_transcript_segments(str(transcript_json_path))
        source_segments = transcript["segments"]
        expected_named_entities = transcript.get("expected_named_entities") or []
        source_language = (
            str(transcript.get("source_language") or "").strip()
            or str(transcript.get("language") or "").strip()
        )
    else:
        source_segments = [
            _normalize_segment(segment, fallback_id=index)
            for index, segment in enumerate(source_segments_payload or [], start=1)
        ]
        expected_named_entities = payload.get("expected_named_entities") or []
        source_language = str(payload.get("source_language") or "").strip()

    glossary = load_glossary(glossary_path) if glossary_path else {"profile": "", "lane_id": "", "terms": []}
    report = validate_translated_segments(
        source_segments,
        translated_segments_payload,
        glossary=glossary,
        expected_named_entities=expected_named_entities,
        enforce_expected_entity_presence=True,
    )
    report["source_language"] = source_language
    report["target_languages"] = validate_hybrid_target_languages(
        payload.get("target_languages"),
    )
    report["batch_count"] = len(
        build_segment_batches(
            source_segments,
            batch_size=int(payload.get("batch_size") or HYBRID_DEFAULT_BATCH_SIZE),
            context_segments=int(payload.get("context_segments") or HYBRID_DEFAULT_CONTEXT_SEGMENTS),
        )
    )
    report["glossary_profile"] = str(glossary.get("profile") or "")
    report["glossary_path"] = str(glossary_path or "")
    report["protected_terms_profile"] = str(glossary.get("profile") or "")
    report["protected_terms_path"] = str(glossary_path or "")
    report["protected_terms_violation_count"] = int(report.get("glossary_violation_count") or 0)
    report["privacy_class"] = HYBRID_PRIVACY_CLASS
    report["validation_status"] = "accepted" if report.get("valid") else "rejected"
    report["translated_segment_count"] = int(report.get("translated_segment_count") or 0)
    report["failed_segment_count"] = max(
        0,
        int(report.get("source_segment_count") or 0) - int(report.get("translated_segment_count") or 0),
    )

    if output_report_path:
        report_path = write_validation_report(report, str(output_report_path))
        report["output_report_path"] = str(report_path)

    return report


def translate_from_request(payload: JsonObject) -> JsonObject:
    transcript_json_path = str(payload.get("transcript_json_path") or "").strip()
    output_dir = str(payload.get("output_dir") or "").strip()
    glossary_path = str(payload.get("glossary_path") or "").strip()
    if not transcript_json_path:
        raise HybridTranslationError("Hybrid Accuracy translation needs transcript_json_path.")
    if not output_dir:
        raise HybridTranslationError("Hybrid Accuracy translation needs output_dir.")
    return run_hybrid_translation(
        transcript_json_path=transcript_json_path,
        output_dir=output_dir,
        glossary_path=glossary_path or None,
        source_language=str(payload.get("source_language") or ""),
        target_language=str(payload.get("target_language") or HYBRID_DEFAULT_TARGET_LANGUAGE),
        openai_project=str(payload.get("openai_project") or "Private"),
        requested_model=str(payload.get("requested_model") or ""),
        expected_named_entities=payload.get("expected_named_entities") or [],
        batch_size=int(payload.get("batch_size") or HYBRID_DEFAULT_BATCH_SIZE),
        context_segments=int(payload.get("context_segments") or HYBRID_DEFAULT_CONTEXT_SEGMENTS),
        output_report_path=payload.get("output_report_path"),
    )
