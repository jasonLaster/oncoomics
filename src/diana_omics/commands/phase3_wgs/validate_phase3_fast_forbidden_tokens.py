from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_parent
from .render_phase3_fast_input_manifest import ManifestError
from .safe_json_output import require_safe_output_path

DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/forbidden_tokens.json"
JSON_ENV = "PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON"
BASE64_JSON_ENV = "PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON_B64"
MIN_TOKEN_LENGTH = 3


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def normalize_forbidden_tokens(raw: Any) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError("PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON must be a non-empty JSON string array")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ManifestError("PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON must be valid JSON") from error

    if not isinstance(payload, list) or not payload:
        raise ManifestError("PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON must be a non-empty JSON string array")

    tokens: list[str] = []
    for index, value in enumerate(payload):
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(
                f"PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON[{index}] must be a non-empty string"
            )
        token = value.strip()
        if len(token) < MIN_TOKEN_LENGTH:
            raise ManifestError(
                f"PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON[{index}] must be at least {MIN_TOKEN_LENGTH} characters"
            )
        if _contains_control_character(token):
            raise ManifestError(
                f"PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON[{index}] must not contain control characters"
            )
        tokens.append(token)

    return sorted(set(tokens), key=str.casefold)


def write_forbidden_tokens(path: Path, tokens: list[str]) -> None:
    require_safe_output_path(path, "phase3 fast forbidden tokens output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(tokens, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def raw_forbidden_tokens_from_environment() -> str | None:
    encoded = os.environ.get(BASE64_JSON_ENV)
    if not encoded:
        return os.environ.get(JSON_ENV)

    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise ManifestError(f"{BASE64_JSON_ENV} must be Base64-encoded UTF-8 JSON") from error


def main() -> None:
    tokens = normalize_forbidden_tokens(raw_forbidden_tokens_from_environment())
    output = path_from_root(os.environ.get("PHASE3_WGS_FAST_FORBIDDEN_TOKENS_OUTPUT", DEFAULT_OUTPUT))
    write_forbidden_tokens(output, tokens)
    print(f"Phase 3 WGS fast forbidden token inventory written: {output}")


if __name__ == "__main__":
    main()
