#!/usr/bin/env python3
"""Build a de-identified, model-safe review bundle from report manifests only."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import unquote

from hrd_report_inventory import (
    inventory_payload,
    inventory_sha256,
    require_pinned_methods,
)


ALLOWED_EVIDENCE_STATES = {"ready", "partial_evidence", "no_call", "blocked"}
ALLOWED_HRD_STATES = {"no_call", "positive", "negative"}
ALLOWED_CLASSIFICATION_QC = {"passed", "failed", "not_applicable", "blocked", "not_run"}
METHOD_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
SUBJECT_ALIAS = re.compile(r"^subject[0-9]{2,4}$")
MODEL_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{1,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?%?"
    r"(?![A-Za-z0-9])"
)
DENIED_KEYS = re.compile(
    r"(?:^|_)(?:patient|person|subject|participant|individual|donor|case|specimen|"
    r"sample|aliquot|library|name|mrn|dob|date_of_birth|email|vendor|accession|"
    r"barcode|external_id|institution|site|source_name|source_uri|result_uri|"
    r"s3_uri|gcs_uri|bucket|object_key|local_path|file_path)(?:$|_)",
    re.IGNORECASE,
)
DENIED_VALUE_PATTERNS = (
    re.compile(r"\b[A-Z][A-Z0-9+.-]*://", re.IGNORECASE),
    re.compile(r"arn:aws:", re.IGNORECASE),
    re.compile(
        r"(?:^|[\s'\"=(:,\[])(?:~[/\\]|/(?!/)(?:[^/\s'\"]+/)+[^/\s'\"]*|[A-Za-z]:[/\\]|\\\\[^\\\s]+\\)",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"\.(?:fastq|fq|bam|cram|sam|vcf|bcf|bai|crai|tbi|csi)(?:\.(?:gz|bgz))?"
        r"(?=$|[\s'\"?#,;:)>\]}])",
        re.IGNORECASE,
    ),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)

BUNDLE_FILENAMES = (
    "review_bundle.json",
    "reviewer-a.prompt.md",
    "reviewer-b.prompt.md",
    "bundle_manifest.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"manifest must be a JSON object: {path.name}")
    return value


def scan_text(text: str, forbidden_tokens: list[str], context: str) -> None:
    text = normalized_scan_text(text)
    for pattern in DENIED_VALUE_PATTERNS:
        if pattern.search(text):
            raise ValueError(
                f"unsafe raw object, URI, identifier, or local path in {context}"
            )
    lowered = text.lower()
    for token in forbidden_tokens:
        normalized_token = normalized_scan_text(token).lower()
        if normalized_token and normalized_token in lowered:
            raise ValueError(f"forbidden token found in {context}")


def normalized_scan_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(value))
    for _ in range(2):
        decoded = unquote(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    return "".join(
        character for character in normalized if unicodedata.category(character) != "Cf"
    )


def normalized_key(value: str) -> str:
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalized_scan_text(value))
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")


def forbidden_token_fingerprints(tokens: list[str]) -> list[str]:
    return sorted(
        hashlib.sha256(
            (
                "diana-ai-review-forbidden-v1\0"
                + normalized_scan_text(token).casefold()
            ).encode("utf-8")
        ).hexdigest()
        for token in tokens
    )


def sanitize(
    value: Any,
    forbidden_tokens: list[str],
    context: str = "review_summary",
) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number in {context}")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        scan_text(value, forbidden_tokens, context)
        return value
    if isinstance(value, list):
        if len(value) > 500:
            raise ValueError(f"too many values in {context}")
        return [sanitize(item, forbidden_tokens, f"{context}[]") for item in value]
    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError(f"too many keys in {context}")
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if DENIED_KEYS.search(normalized_key(key_text)):
                raise ValueError(
                    f"identifier or location key is prohibited in {context}"
                )
            scan_text(key_text, forbidden_tokens, f"{context} key")
            output[key_text] = sanitize(item, forbidden_tokens, f"{context}.{key_text}")
        return output
    raise ValueError(f"unsupported value type in {context}: {type(value).__name__}")


def json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def quantitative_facts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inventory every scalar number and exposed numeric string token."""
    facts: list[dict[str, Any]] = []

    def visit(value: Any, evidence_id: str, pointer: str) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            facts.append(
                {
                    "quantitative_fact_id": f"Q{len(facts) + 1:04d}",
                    "evidence_id": evidence_id,
                    "summary_path": pointer,
                    "value_kind": "number",
                    "exact_text": json.dumps(
                        value,
                        allow_nan=False,
                        separators=(",", ":"),
                    ),
                }
            )
            return
        if isinstance(value, str):
            for ordinal, match in enumerate(NUMBER_TOKEN.finditer(value), 1):
                facts.append(
                    {
                        "quantitative_fact_id": f"Q{len(facts) + 1:04d}",
                        "evidence_id": evidence_id,
                        "summary_path": pointer,
                        "value_kind": "string_token",
                        "token_ordinal": ordinal,
                        "exact_text": match.group(0),
                    }
                )
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, evidence_id, f"{pointer}/{index}")
            return
        if isinstance(value, dict):
            for key in sorted(value):
                visit(value[key], evidence_id, f"{pointer}/{json_pointer_token(str(key))}")

    for row in evidence:
        visit(row["review_summary"], row["evidence_id"], "review_summary")
    return facts


def parse_catalog_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("model catalog verification timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("model catalog verification timestamp must include timezone")
    now = datetime.now(timezone.utc)
    parsed_utc = parsed.astimezone(timezone.utc)
    if parsed_utc > now:
        raise ValueError("model catalog verification timestamp is in the future")
    if (now - parsed_utc).total_seconds() > 31 * 24 * 60 * 60:
        raise ValueError("model catalog verification is older than 31 days")
    return parsed_utc


def validate_catalog_receipt(
    path: Path,
    catalog_verified_at: str,
    model_contracts: dict[str, dict[str, Any]],
) -> str:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError("model catalog receipt is missing or empty")
    receipt = load_object(resolved)
    if receipt.get("schema_version") != 1:
        raise ValueError("model catalog receipt schema is unsupported")
    receipt_time = parse_catalog_time(
        str(receipt.get("catalog_verified_at", ""))
    ).isoformat()
    if receipt_time != catalog_verified_at:
        raise ValueError(
            "model catalog receipt timestamp differs from the attested timestamp"
        )
    if not str(receipt.get("provider_catalog", "")).strip() or not str(
        receipt.get("catalog_source", "")
    ).strip():
        raise ValueError("model catalog receipt lacks provider catalog provenance")
    rows = receipt.get("models")
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError(
            "model catalog receipt must contain exactly the two reviewer models"
        )
    observed: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("model catalog receipt contains a malformed model row")
        pair = (str(row.get("provider", "")), str(row.get("model_id", "")))
        if (
            pair in observed
            or row.get("available") is not True
            or row.get("latest_available") is not True
        ):
            raise ValueError(
                "model catalog receipt contains duplicate, unavailable, or non-latest models"
            )
        observed.add(pair)
    expected = {
        (row["provider"], row["model_id"]) for row in model_contracts.values()
    }
    if observed != expected:
        raise ValueError(
            "model catalog receipt does not match the pinned reviewer models"
        )
    return sha256(resolved)


def prompt(
    role: str,
    bundle_hash: str,
    subject_alias: str,
    model: dict[str, Any],
) -> str:
    common = f"""# Independent HRD evidence reviewer {role}

Input: `review_bundle.json` with SHA-256 `{bundle_hash}`.
Subject alias: `{subject_alias}`. Use this alias only; do not invent or infer any other subject identifier.
Pinned model: `{model['provider']}/{model['model_id']}`. The operator attested this was the latest available model in its catalog at `{model['catalog_verified_at']}`.

This is a narrative evidence audit, not an HRD algorithm or clinical workflow. Use only evidence IDs present in the bundle. Do not infer facts from filenames, outside knowledge, or absent raw data. Never request or reproduce FASTQ, BAM, CRAM, full VCF, S3/GCS URI, direct identifier, vendor identifier, clinical note, or credential content.

The bundle's `authorized_hrd_state` is an absolute ceiling. Do not write `HRD-positive` or `HRD-negative`, and do not propose `positive` or `negative`, unless that exact state is authorized in the bundle. Preserve each evidence source's exact `ready`, `partial_evidence`, `no_call`, or `blocked` state. A disagreement must be retained.

Numerical results are immutable. Every number used in narrative or claims must copy the `exact_text` of a cited `quantitative_fact_id`. Do not calculate, round, reformat, spell out, average, normalize, combine, or introduce a number. Arithmetic expressions are prohibited. If a derived number would help, describe the need without computing it.

Produce exactly:

1. `report.md`, with these headings in order: `# Independent HRD evidence review`, `## Methods and evidence`, `## Findings`, `## Disagreements`, `## Limitations`, `## Authorized conclusion`. Before the first section, state the exact authorization line `Authorized HRD state: <state>` and exact alias line `Subject alias: <alias>`, using backticks around the values. Cite every substantive paragraph or table with `[C###|E###]`; for multiple evidence sources use semicolons and make the cited evidence list exactly match that claim row.
2. `claims.csv` with the exact header:
   `claim_id,claim,evidence_ids,source_methods,evidence_states,support_level,caveat,disposition,proposed_hrd_state,quantitative_fact_ids,disagreement_status,disagreement_evidence_ids,resolution_needed`
3. `review_manifest.json` with reviewer ID, the exact pinned model contract, invocation ID/interface/start/end timestamps, subject alias, prompt SHA-256, input-bundle SHA-256, the pinned method-inventory SHA-256 `{inventory_sha256()}`, an exact two-file input-artifact hash inventory, the required independence/isolation attestation, and SHA-256 for `report.md` and `claims.csv`.

The exact input-artifact inventory is `review_bundle.json` plus this reviewer-specific prompt only. Attest that no other reviewer output, external research, or raw input was received.

Allowed support levels: `direct`, `indirect`, `conflicting`, `absent`.
Allowed dispositions: `supported`, `partially_supported`, `unsupported`, `cannot_assess`.
Allowed disagreement statuses: `none`, `method_conflict`, `insufficient_comparability`, `missing_evidence`.

Use semicolons for aligned lists in `evidence_ids`, `source_methods`, and `evidence_states`. Every evidence source in the bundle must be represented by at least one claim. Use `none` for an empty quantitative-fact or disagreement-evidence list. When disagreement status is `none`, use `not_applicable` for `resolution_needed`; otherwise cite the relevant evidence IDs and state the additional observation needed.
"""
    if role == "A":
        task = """
Role: evidence integrator.

- Summarize what each deterministic method measured.
- Identify concordant and discordant evidence without averaging disagreements.
- Separate sample evidence, public validation evidence, and research context.
- State the strongest supported conclusions and every unsupported conclusion.
- Include explicit uncertainty and missing-input gates.
"""
    else:
        task = """
Role: adversarial discrepancy reviewer. Work independently; do not consume reviewer A's report or claims.

- Attempt to falsify apparent conclusions in the bundle.
- Test reference, pairing, purity, subclonality, CN adapter, signature, SV, threshold, and calibration failure modes.
- Flag claims that exceed deterministic evidence.
- State what additional observation would resolve each material discrepancy.
"""
    return common + task


def authorized_state(rows: list[dict[str, Any]]) -> str:
    classified: set[str] = set()
    for row in rows:
        state = row["authorized_hrd_state"]
        if state in {"positive", "negative"}:
            if (
                row.get("classification_authorized") is not True
                or row.get("classification_qc_status") != "passed"
            ):
                raise ValueError(
                    "positive/negative manifest state lacks explicit authorization and passed QC"
                )
            if row.get("evidence_status") != "ready":
                raise ValueError(
                    "positive/negative manifest state requires ready evidence"
                )
            classified.add(state)
    if len(classified) > 1:
        raise ValueError(
            "deterministic manifests contain conflicting authorized HRD classifications"
        )
    return next(iter(classified), "no_call")


def prepare_output_dir(output: Path, expected_files: Iterable[str]) -> None:
    expected = set(expected_files)
    if output.is_symlink():
        raise ValueError("AI review bundle output may not be a symlink")
    if output.exists() and not output.is_dir():
        raise ValueError(f"AI review bundle output is not a directory: {output}")

    output.mkdir(parents=True, exist_ok=True)

    unexpected: list[str] = []
    invalid: list[str] = []
    for path in output.iterdir():
        if path.name not in expected:
            unexpected.append(path.name)
        elif path.is_symlink() or not path.is_file():
            invalid.append(path.name)
    if unexpected:
        raise ValueError(
            "AI review bundle output contains unexpected existing files: "
            + ", ".join(sorted(unexpected))
        )
    if invalid:
        raise ValueError(
            "AI review bundle output contains invalid existing bundle paths: "
            + ", ".join(sorted(invalid))
        )

    existing = sorted(path.name for path in output.iterdir() if path.name in expected)
    if existing:
        raise ValueError(
            "AI review bundle output already contains bundle files: "
            + ", ".join(existing)
        )


def copy_create_only(source: Path, destination: Path) -> None:
    with source.open("rb") as source_handle:
        try:
            file_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError as error:
            raise ValueError(
                "AI review bundle output already exists: " + destination.name
            ) from error

        try:
            destination_handle = os.fdopen(file_descriptor, "wb")
        except Exception:
            os.close(file_descriptor)
            destination.unlink(missing_ok=True)
            raise

        try:
            with destination_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    destination_handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def install_bundle_create_only(staged_paths: Sequence[Path], output: Path) -> None:
    installed: list[Path] = []
    try:
        for path in staged_paths:
            destination = output / path.name
            copy_create_only(path, destination)
            installed.append(destination)
    except Exception:
        for path in installed:
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", action="append", required=True, type=Path)
    parser.add_argument(
        "--require-method",
        action="append",
        required=True,
        help="Expected method ID, repeated in the exact manifest order.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--subject-alias", default="subject01")
    parser.add_argument("--reviewer-a-provider", required=True)
    parser.add_argument("--reviewer-a-model-id", required=True)
    parser.add_argument("--reviewer-b-provider", required=True)
    parser.add_argument("--reviewer-b-model-id", required=True)
    parser.add_argument("--model-catalog-verified-at", required=True)
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--attest-models-latest", action="store_true")
    args = parser.parse_args()

    output = args.output_dir.resolve()
    try:
        prepare_output_dir(output, BUNDLE_FILENAMES)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    forbidden = [token.strip() for token in args.forbidden_token if token.strip()]
    if not forbidden:
        raise SystemExit("Fail-closed: at least one --forbidden-token is required")
    if not SUBJECT_ALIAS.fullmatch(args.subject_alias):
        raise SystemExit("Fail-closed: subject alias must match subjectNN")
    if not args.attest_models_latest:
        raise SystemExit("Fail-closed: --attest-models-latest is required")

    required_methods = [str(value).strip() for value in args.require_method]
    if (
        not required_methods
        or any(not METHOD_ID.fullmatch(value) for value in required_methods)
        or len(set(required_methods)) != len(required_methods)
    ):
        raise SystemExit(
            "Fail-closed: required method inventory is empty, invalid, or duplicated"
        )
    try:
        require_pinned_methods(required_methods, "required method arguments")
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    try:
        catalog_verified = parse_catalog_time(
            args.model_catalog_verified_at
        ).isoformat()
        model_contracts = {
            "A": {
                "provider": args.reviewer_a_provider,
                "model_id": args.reviewer_a_model_id,
                "catalog_verified_at": catalog_verified,
                "latest_available_attested": True,
            },
            "B": {
                "provider": args.reviewer_b_provider,
                "model_id": args.reviewer_b_model_id,
                "catalog_verified_at": catalog_verified,
                "latest_available_attested": True,
            },
        }
        for role, model in model_contracts.items():
            if not MODEL_VALUE.fullmatch(model["provider"]) or not MODEL_VALUE.fullmatch(
                model["model_id"]
            ):
                raise ValueError(f"invalid pinned model identifier for reviewer {role}")
        if (model_contracts["A"]["provider"], model_contracts["A"]["model_id"]) == (
            model_contracts["B"]["provider"],
            model_contracts["B"]["model_id"],
        ):
            raise ValueError("reviewers A and B must use distinct pinned models")
        catalog_receipt_hash = validate_catalog_receipt(
            args.model_catalog_receipt,
            catalog_verified,
            model_contracts,
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    evidence: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {}
    observed_methods: list[str] = []
    for index, manifest_path in enumerate(args.manifest, 1):
        path = manifest_path.resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"Fail-closed: missing report manifest {manifest_path}")
        manifest = load_object(path)
        if manifest.get("schema_version") != 1:
            raise SystemExit(
                f"Fail-closed: unsupported report-manifest schema in {path.name}"
            )

        method = str(manifest.get("method_id") or manifest.get("route") or "")
        if not METHOD_ID.fullmatch(method):
            raise SystemExit(
                f"Fail-closed: invalid or missing method identifier in {path.name}"
            )
        if method in observed_methods:
            raise SystemExit(f"Fail-closed: duplicate method manifest for {method}")
        observed_methods.append(method)

        evidence_status = str(manifest.get("evidence_status", ""))
        if evidence_status not in ALLOWED_EVIDENCE_STATES:
            raise SystemExit(f"Fail-closed: invalid evidence status for {method}")
        hrd_state = str(
            manifest.get("authorized_hrd_state")
            or manifest.get("interpretation_status")
            or ""
        )
        if hrd_state not in ALLOWED_HRD_STATES:
            raise SystemExit(f"Fail-closed: invalid authorized HRD state for {method}")
        classification_qc = str(
            manifest.get("classification_qc_status", "not_applicable")
        )
        if classification_qc not in ALLOWED_CLASSIFICATION_QC:
            raise SystemExit(
                f"Fail-closed: invalid classification QC state for {method}"
            )
        report_hash = str(manifest.get("report_sha256", "")).lower()
        if not HEX64.fullmatch(report_hash):
            raise SystemExit(f"Fail-closed: missing report SHA-256 for {method}")

        report_path = path.parent / "report.md"
        if not report_path.is_file() or sha256(report_path) != report_hash:
            raise SystemExit(f"Fail-closed: report hash mismatch for {method}")

        try:
            raw_summary = manifest.get("review_summary")
            if not isinstance(raw_summary, dict) or not raw_summary:
                raise ValueError(f"missing non-empty review_summary for {method}")
            summary = sanitize(raw_summary, forbidden)
            scan_text(method, forbidden, "method identifier")
            report_kind = str(manifest.get("report_kind", "method"))
            scan_text(report_kind, forbidden, "report kind")
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error

        source_hashes = manifest.get("source_sha256", {})
        if not isinstance(source_hashes, dict) or not source_hashes or not all(
            HEX64.fullmatch(str(value).lower()) for value in source_hashes.values()
        ):
            raise SystemExit(f"Fail-closed: malformed source hashes for {method}")

        evidence.append(
            {
                "evidence_id": f"E{index:03d}",
                "method_id": method,
                "report_kind": report_kind,
                "evidence_status": evidence_status,
                "authorized_hrd_state": hrd_state,
                "classification_authorized": manifest.get(
                    "classification_authorized"
                )
                is True,
                "classification_qc_status": classification_qc,
                "report_sha256": report_hash,
                "source_artifact_sha256": sorted(
                    str(value).lower() for value in source_hashes.values()
                ),
                "review_summary": summary,
            }
        )
        input_hashes[f"E{index:03d}"] = sha256(path)

    if observed_methods != required_methods:
        raise SystemExit(
            "Fail-closed: observed method manifests do not exactly match the "
            "ordered required method inventory; "
            f"required={required_methods!r} observed={observed_methods!r}"
        )

    try:
        ceiling = authorized_state(evidence)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    facts = quantitative_facts(evidence)
    bundle = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "deidentified_independent_narrative_crosscheck",
        "subject_alias": args.subject_alias,
        "authorized_hrd_state": ceiling,
        "required_method_ids": required_methods,
        "method_inventory": inventory_payload(),
        "method_inventory_sha256": inventory_sha256(),
        "evidence_sources": evidence,
        "quantitative_facts": facts,
        "model_execution_contracts": model_contracts,
        "model_catalog_receipt_sha256": catalog_receipt_hash,
        "policy": {
            "raw_inputs_prohibited": True,
            "external_research_prohibited": True,
            "reviewers_independent": True,
            "other_reviewer_outputs_prohibited": True,
            "numerical_results_immutable": True,
            "classification_may_not_exceed_authorized_state": True,
        },
    }
    if len(json_bytes(bundle)) > 2 * 1024 * 1024:
        raise SystemExit("Fail-closed: review bundle exceeds 2 MiB")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ai-review-bundle-",
        dir=output.parent,
    ) as temporary:
        staging = Path(temporary)
        bundle_path = staging / "review_bundle.json"
        bundle_path.write_bytes(json_bytes(bundle))
        bundle_hash = sha256(bundle_path)

        prompt_paths = {}
        for role in ("A", "B"):
            path = staging / f"reviewer-{role.lower()}.prompt.md"
            path.write_text(
                prompt(role, bundle_hash, args.subject_alias, model_contracts[role]),
                encoding="utf-8",
            )
            prompt_paths[role] = path

        manifest = {
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "subject_alias": args.subject_alias,
            "authorized_hrd_state": ceiling,
            "required_method_ids": required_methods,
            "method_inventory": inventory_payload(),
            "method_inventory_sha256": inventory_sha256(),
            "input_manifest_sha256": input_hashes,
            "forbidden_token_sha256": forbidden_token_fingerprints(forbidden),
            "review_bundle_sha256": bundle_hash,
            "prompt_sha256": {
                role: sha256(path) for role, path in prompt_paths.items()
            },
            "model_execution_contracts": model_contracts,
            "model_catalog_receipt_sha256": catalog_receipt_hash,
        }
        manifest_path = staging / "bundle_manifest.json"
        manifest_path.write_bytes(json_bytes(manifest))

        try:
            install_bundle_create_only(
                (bundle_path, *prompt_paths.values(), manifest_path),
                output,
            )
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error

    print(f"Wrote de-identified AI review bundle: {output}")
    print(f"Authorized HRD state: {ceiling}; no model invoked")


if __name__ == "__main__":
    main()
