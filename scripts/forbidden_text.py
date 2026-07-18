"""Shared forbidden-token normalization for HRD report custody gates."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from typing import Iterable
from urllib.parse import unquote


FORBIDDEN_TOKEN_FINGERPRINT_DOMAIN = "diana-ai-review-forbidden-v1\0"
UNAUTHORIZED_HRD_CLASSIFICATION = re.compile(
    r"\bHRD\s*[+-](?![A-Za-z0-9])|"
    r"\bHRD[-_ ]*(?:status|classification|call)?\s*(?:is|:|=)?\s*"
    r"(?:positive|negative)\b|"
    r"\bHRD(?:[-_ ]*(?:status|classification|call))?\s+(?:is\s+)?"
    r"(?:present|absent|detected|established|confirmed|high|low)\b|"
    r"\b(?:sample|tumou?r|case|profile|it)\s+(?:is|has)\s+(?:an?\s+)?HRD\b|"
    r"\b(?:positive|negative)\s+(?:for\s+)?HRD\b|"
    r"\b(?:HR|homologous[-_ ]recombination)(?:[-_ ]repair)?[-_ ]*"
    r"(?:deficient|proficient)\b|"
    r"\bhomologous\s+recombination\s+(?:deficiency|proficiency)\s+"
    r"(?:is\s+)?(?:present|absent|detected|established|confirmed)\b",
    re.IGNORECASE,
)


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


def has_unauthorized_hrd_classification(value: str) -> bool:
    """Return whether text makes a categorical HRD-positive/negative claim."""

    return UNAUTHORIZED_HRD_CLASSIFICATION.search(normalized_scan_text(value)) is not None


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
