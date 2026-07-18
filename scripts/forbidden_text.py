"""Shared forbidden-token normalization for HRD report custody gates."""

from __future__ import annotations

import hashlib
import html
import unicodedata
from typing import Iterable
from urllib.parse import unquote


FORBIDDEN_TOKEN_FINGERPRINT_DOMAIN = "diana-ai-review-forbidden-v1\0"


def normalized_scan_text(value: str) -> str:
    """Normalize text before scanning for encoded identifiers."""

    normalized = unicodedata.normalize("NFKC", html.unescape(value))
    for _ in range(2):
        decoded = unquote(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    return "".join(
        character for character in normalized if unicodedata.category(character) != "Cf"
    )


def forbidden_token_fingerprints(tokens: Iterable[str]) -> list[str]:
    """Return stable fingerprints for the normalized forbidden-token inventory."""

    return sorted(
        hashlib.sha256(
            (
                FORBIDDEN_TOKEN_FINGERPRINT_DOMAIN
                + normalized_scan_text(token).casefold()
            ).encode("utf-8")
        ).hexdigest()
        for token in tokens
    )
