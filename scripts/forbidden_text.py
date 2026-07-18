"""Shared forbidden-token normalization for HRD report custody gates."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
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
    return "".join(character for character in normalized if unicodedata.category(character) != "Cf")


def has_unauthorized_hrd_classification(value: str) -> bool:
    """Return whether text makes a categorical HRD-positive/negative claim."""

    return UNAUTHORIZED_HRD_CLASSIFICATION.search(normalized_scan_text(value)) is not None


def forbidden_token_fingerprints(tokens: Iterable[str]) -> list[str]:
    """Return stable fingerprints for the normalized forbidden-token inventory."""

    return sorted(
        hashlib.sha256((FORBIDDEN_TOKEN_FINGERPRINT_DOMAIN + normalized_scan_text(token).casefold()).encode("utf-8")).hexdigest()
        for token in tokens
    )


def forbidden_tokens_from_file(path: Path) -> list[str]:
    """Load a non-empty JSON string array from a real forbidden-token file."""

    require_no_symlinked_ancestors(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"forbidden-token file must be a real file: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"forbidden-token file must contain a non-empty JSON string array: {path}")

    tokens = []
    for index, value in enumerate(payload):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"forbidden-token file {path} entry {index} must be a non-empty string")
        tokens.append(value.strip())
    return tokens


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"forbidden-token file parent may not be a symlink: {parent}")


def merge_forbidden_tokens(
    tokens: Iterable[str],
    *,
    files: Iterable[Path] = (),
) -> tuple[str, ...]:
    """Return a stable unique token tuple from explicit values and JSON files."""

    return tuple(
        sorted(
            {
                token.strip()
                for token in (
                    *tokens,
                    *(file_token for path in files for file_token in forbidden_tokens_from_file(path)),
                )
                if token.strip()
            },
            key=str.casefold,
        )
    )
