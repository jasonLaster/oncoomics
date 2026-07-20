"""Shared forbidden-token normalization for HRD report custody gates."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import stat
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

FORBIDDEN_TOKEN_FINGERPRINT_DOMAIN = "diana-ai-review-forbidden-v1\0"
MIN_TOKEN_LENGTH = 3
DEFAULT_FORBIDDEN_TOKENS = (
    "DRF-PSN49561",
    "E019_S01",
    "echo-personalis",
    "personalis",
)
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


def contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def normalize_forbidden_token(value: Any, label: str) -> str:
    """Normalize one forbidden token and fail closed on ambiguous tokens."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    token = value.strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"{label} must be at least {MIN_TOKEN_LENGTH} characters")
    if contains_control_character(token):
        raise ValueError(f"{label} must not contain control characters")
    return token


def normalize_forbidden_tokens(
    values: Iterable[Any],
    *,
    label: str,
) -> list[str]:
    """Normalize a forbidden-token inventory into a stable unique list."""

    return sorted(
        {
            normalize_forbidden_token(value, f"{label}[{index}]")
            for index, value in enumerate(values)
        },
        key=str.casefold,
    )


def normalize_forbidden_tokens_json(raw: Any) -> list[str]:
    """Load a Phase 3 fast forbidden-token JSON string into a stable list."""

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("forbidden-token JSON must be a non-empty JSON string array")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("forbidden-token JSON must be valid JSON") from error

    if not isinstance(payload, list) or not payload:
        raise ValueError("forbidden-token JSON must be a non-empty JSON string array")

    return normalize_forbidden_tokens(payload, label="forbidden-token JSON")


def forbidden_token_fingerprints(tokens: Iterable[str]) -> list[str]:
    """Return stable fingerprints for the normalized forbidden-token inventory."""

    return sorted(
        hashlib.sha256((FORBIDDEN_TOKEN_FINGERPRINT_DOMAIN + normalized_scan_text(token).casefold()).encode("utf-8")).hexdigest()
        for token in tokens
    )


def forbidden_tokens_from_file(path: Path) -> list[str]:
    """Load a non-empty JSON string array from a real forbidden-token file."""

    text = read_real_forbidden_token_file(path)

    try:
        return normalize_forbidden_tokens_json(text)
    except ValueError as error:
        raise ValueError(f"forbidden-token file must contain a valid non-empty JSON string array: {path}") from error


def require_real_forbidden_token_file(path: Path) -> None:
    require_no_symlinked_ancestors(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"forbidden-token file must be a real file: {path}")


def read_real_forbidden_token_file(path: Path) -> str:
    require_real_forbidden_token_file(path)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"forbidden-token file must be a real file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read()
            after_read = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError as error:
        raise ValueError(f"forbidden-token file changed during read: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    require_no_symlinked_ancestors(path)
    if not os.path.samestat(opened, after_read) or not os.path.samestat(
        after_read,
        current,
    ):
        raise ValueError(f"forbidden-token file changed during read: {path}")

    try:
        return data.decode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"forbidden-token file must be UTF-8: {path}") from error


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
        normalize_forbidden_tokens(
            (
                *tokens,
                *(
                    file_token
                    for path in files
                    for file_token in forbidden_tokens_from_file(path)
                ),
            ),
            label="forbidden token",
        )
    )
