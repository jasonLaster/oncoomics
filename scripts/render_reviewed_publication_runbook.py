#!/usr/bin/env python3
"""Render reviewed-public publication commands for all HRD report packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

from hrd_report_inventory import REPORT_METHOD_IDS
from publish_reviewed_public_report import (
    METHOD_CONTRACTS,
    PUBLIC_BUCKET,
    PUBLIC_ROOT,
    REGION,
    validate_private_receipt_payload,
)
from runbook_io import (
    block,
    load_json_object_with_sha256,
    missing_required_files,
    preexisting_create_only_paths,
    require_real_input_file,
    write_once,
)

STALE_TOKENS = (
    ".codex-tmp/hrd-reports/publish_private_report.py",
    ".codex-tmp/hrd-reports/ai-review/render_ai_synthesis_runbook.py",
    "--receipt-upload-output",
    "--private-publication-upload-receipt",
    "--source-dir",
    "--expected-file",
)
PRIVATE_RECEIPT_SUMMARY_KEYS = {
    "method_id",
    "receipt",
    "receipt_sha256",
    "destination_prefix",
    "object_count",
}


def sha256(path: Path) -> str:
    require_real_input_file(path, f"{path.name} SHA-256 input")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_summary_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} SHA-256 is malformed")
    return value


def require_summary_receipt(value: object, method_id: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\n" in value
        or "\r" in value
        or "\0" in value
        or value.lower() in {"null", "none"}
    ):
        raise ValueError(f"{method_id} private receipt path is malformed")
    return value


def validate_private_report_receipts(
    receipt_paths: Iterable[Path],
) -> tuple[dict[str, str | int], ...]:
    paths = list(receipt_paths)
    if len(paths) != len(REPORT_METHOD_IDS):
        raise ValueError("exactly ten private publication receipts are required")

    receipts = [
        load_json_object_with_sha256(path, "private publication receipt")
        for path in paths
    ]
    method_ids = [str(receipt.get("method_id", "")) for receipt, _ in receipts]
    if method_ids != list(REPORT_METHOD_IDS):
        raise ValueError(
            "private publication receipts must be passed in canonical "
            f"ten-method order; observed={method_ids!r}"
        )

    summaries = []
    for index, (path, (receipt, receipt_sha256)) in enumerate(zip(paths, receipts)):
        method_id = REPORT_METHOD_IDS[index]
        _, rows = validate_private_receipt_payload(receipt, method_id)
        summaries.append(
            {
                "method_id": method_id,
                "receipt": str(path),
                "receipt_sha256": receipt_sha256,
                "destination_prefix": destination_prefix(method_id),
                "object_count": len(rows),
            }
        )
    return tuple(summaries)


def destination_prefix(method_id: str) -> str:
    return (
        f"s3://{PUBLIC_BUCKET}/{PUBLIC_ROOT}"
        f"{METHOD_CONTRACTS[method_id]['destination']}"
    )


def receipt_output(root: Path, receipt_stem: str, method_id: str, suffix: str) -> Path:
    return (
        root
        / ".codex-tmp/hrd-reports/publication"
        / f"{receipt_stem}.{method_id}.public{suffix}.json"
    )


def public_index_path(root: Path) -> Path:
    return root / ".codex-tmp/public-index/objects.json"


def publish_command(
    scripts: Path,
    receipt_path: Path,
    receipt_sha256: str,
    method_id: str,
    output: Path,
    *,
    apply: bool,
    dry_run_receipt: Path | None = None,
    forbidden_tokens_file: Path | None = None,
) -> list[str | Path]:
    command: list[str | Path] = [
        "python3",
        scripts / "publish_reviewed_public_report.py",
        "--private-publication-receipt",
        receipt_path,
        "--method-id",
        method_id,
        "--destination-prefix",
        destination_prefix(method_id),
        "--receipt-output",
        output,
        "--region",
        REGION,
    ]
    command.extend(["--private-publication-receipt-sha256", receipt_sha256])
    if forbidden_tokens_file is not None:
        command.extend(["--forbidden-tokens-file", forbidden_tokens_file])
    if apply:
        if dry_run_receipt is None:
            raise ValueError("reviewed-public apply command requires a dry-run receipt")
        command.extend(["--dry-run-receipt", dry_run_receipt])
        command.append("--apply")
    elif dry_run_receipt is not None:
        raise ValueError("--dry-run-receipt is only valid with --apply")
    return command


def reviewed_public_report_checklist(
    method_id: str,
    dry_receipt: Path,
    destination_prefix: str,
) -> list[str]:
    return [
        f"Review `{dry_receipt}` before public report apply:",
        "",
        f"- [ ] `method_id` is `{method_id}` and matches the private packet.",
        "- [ ] `private_publication_receipt.sha256` matches the validated "
        "private-freeze receipt above.",
        f"- [ ] `destination_prefix` is `{destination_prefix}`.",
        "- [ ] `expected_files` and `source_objects` match the method contract.",
        "- [ ] `destination_initial_history_count` is `0` and "
        "`destination_objects` is `[]`.",
        "- [ ] `checks.private_receipt_exact_and_passed`, "
        "`checks.source_exact_versions`, `checks.source_sha256_and_bytes`, "
        "`checks.source_exact_kms`, `checks.second_forbidden_token_scan`, "
        "`checks.manifest_no_call_boundary`, `checks.source_report_kind_exact`, "
        "`checks.destination_initially_empty`, and "
        "`checks.packet_size_bounded` are all true.",
        "- [ ] Running the following `--apply` command is still the intended "
        "reviewed-public action.",
    ]


def index_commands(root: Path, receipt_stem: str = "terminal") -> list[list[str | Path]]:
    scripts = root / "scripts"
    index = public_index_path(root)
    dry_receipt, apply_receipt = public_index_receipt_paths(root, receipt_stem)
    reviewed_public_receipts = [
        receipt_output(root, receipt_stem, method_id, "")
        for method_id in REPORT_METHOD_IDS
    ]
    reviewed_public_receipt_args = [
        token
        for receipt in reviewed_public_receipts
        for token in ("--reviewed-public-receipt", receipt)
    ]
    return [
        [
            "python3",
            scripts / "build_public_results_index.py",
            "--output",
            index,
            *reviewed_public_receipt_args,
        ],
        [
            "python3",
            scripts / "publish_public_results_index.py",
            "--index",
            index,
            *reviewed_public_receipt_args,
            "--receipt-output",
            dry_receipt,
        ],
        [
            "python3",
            scripts / "publish_public_results_index.py",
            "--index",
            index,
            *reviewed_public_receipt_args,
            "--receipt-output",
            apply_receipt,
            "--dry-run-receipt",
            dry_receipt,
            "--apply",
        ],
    ]


def public_index_receipt_paths(root: Path, receipt_stem: str) -> tuple[Path, Path]:
    receipt_root = root / ".codex-tmp/public-index"
    return (
        receipt_root / f"public-index.{receipt_stem}.dry.json",
        receipt_root / f"public-index.{receipt_stem}.json",
    )


def public_index_checklist(root: Path, receipt_stem: str) -> list[str]:
    dry_receipt, _ = public_index_receipt_paths(root, receipt_stem)
    return [
        f"Review `{dry_receipt}` before public index apply:",
        "",
        f"- [ ] `index.path` is `{public_index_path(root)}`.",
        "- [ ] `index.sha256`, `index.bytes`, `index.object_count`, "
        "`index.total_size`, and `index.reviewed_public_receipt_count` match "
        "the rebuilt index.",
        "- [ ] `destination.bucket`, `destination.key`, and `destination.uri` "
        "point at the public results index.",
        "- [ ] `checks.index_schema`, `checks.index_allowlisted_prefixes`, "
        "`checks.index_sorted_unique_keys`, and "
        "`checks.index_reviewed_public_receipts` are all true.",
        "- [ ] The ten reviewed-public receipts are exactly the receipts just "
        "created for the report packets.",
        "- [ ] Running the following `--apply` command is still the intended "
        "public-index action.",
    ]


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return (
        scripts / "hrd_report_inventory.py",
        scripts / "ai_model_catalog.py",
        scripts / "build_ai_review_bundle.py",
        scripts / "runbook_io.py",
        scripts / "forbidden_text.py",
        scripts / "publish_reviewed_public_report.py",
        scripts / "build_public_results_index.py",
        scripts / "publish_public_results_index.py",
    )


def required_absent(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    return (
        *(
            receipt_output(root, receipt_stem, method_id, suffix)
            for method_id in REPORT_METHOD_IDS
            for suffix in (".dry", "")
        ),
        public_index_path(root),
        *public_index_receipt_paths(root, receipt_stem),
    )


def require_receipt_summaries(
    receipt_summaries: Iterable[dict[str, str | int]],
) -> tuple[dict[str, str | int], ...]:
    summaries = tuple(receipt_summaries)
    method_ids = [str(summary.get("method_id", "")) for summary in summaries]
    if method_ids != list(REPORT_METHOD_IDS):
        raise ValueError(
            "reviewed-public rendering requires ten private publication "
            f"receipts in canonical order; observed={method_ids!r}"
        )
    for summary in summaries:
        if set(summary) != PRIVATE_RECEIPT_SUMMARY_KEYS:
            raise ValueError(
                f"{summary.get('method_id', 'unknown')} private receipt "
                "summary envelope is not exact"
            )
        method_id = str(summary["method_id"])
        if str(summary.get("destination_prefix", "")) != destination_prefix(method_id):
            raise ValueError(
                f"{summary['method_id']} private receipt destination is malformed"
            )
        object_count = summary.get("object_count")
        if type(object_count) is not int or object_count <= 0:
            raise ValueError(
                f"{summary['method_id']} private receipt object count is malformed"
            )
        require_summary_receipt(
            summary.get("receipt"),
            method_id,
        )
        require_summary_sha256(
            summary.get("receipt_sha256"),
            f"{method_id} private receipt",
        )
    return summaries


def require_receipt_paths(
    receipt_paths: Iterable[Path],
    receipt_summaries: tuple[dict[str, str | int], ...],
) -> tuple[Path, ...]:
    paths = tuple(receipt_paths)
    if len(paths) != len(REPORT_METHOD_IDS):
        raise ValueError("reviewed-public rendering requires ten private receipts")

    for summary, path in zip(receipt_summaries, paths):
        if str(summary.get("receipt", "")) != str(path):
            raise ValueError(
                f"{summary['method_id']} private receipt path is not bound to "
                "the validated receipt summary"
            )
    return paths


def render(
    root: Path,
    receipt_paths: Iterable[Path],
    receipt_stem: str,
    receipt_summaries: tuple[dict[str, str | int], ...] = (),
    *,
    forbidden_tokens_file: Path | None = None,
) -> str:
    receipt_summaries = require_receipt_summaries(receipt_summaries)
    paths = require_receipt_paths(receipt_paths, receipt_summaries)
    scripts = root / "scripts"
    receipt_sha256_by_method = {
        str(summary["method_id"]): str(summary["receipt_sha256"])
        for summary in receipt_summaries
    }

    lines = [
        "# Diana WGS reviewed-public publication handoff",
        "",
        "- Boundary: publish the ten privately frozen reviewed HRD packets into "
        "their exact pseudonymous public prefixes, then rebuild and publish "
        "`public-index/objects.json` for `data.diana-tnbc.com` discovery.",
        "- Preserve the canonical ten-method order pinned in "
        "`scripts/hrd_report_inventory.py`.",
        "",
    ]
    lines.extend(
        [
            "## 0. Private publication receipt gate",
            "",
            "The renderer bound this handoff to ten passed private publication "
            "receipts in canonical report-method order:",
            "",
        ]
    )
    for summary in receipt_summaries:
        lines.append(
            f"- `{summary['method_id']}`: {summary['object_count']} files → "
            f"private receipt SHA-256 `{summary['receipt_sha256']}` -> "
            f"`{summary['destination_prefix']}`"
        )
    lines.append("")

    lines.extend(["## 1. Dry-run and apply reviewed-public reports", ""])
    for index, method_id in enumerate(REPORT_METHOD_IDS):
        receipt = paths[index]
        dry_receipt = receipt_output(root, receipt_stem, method_id, ".dry")
        apply_receipt = receipt_output(root, receipt_stem, method_id, "")
        destination = destination_prefix(method_id)
        lines.extend(
            [
                f"### {method_id}",
                "",
                block(
                    publish_command(
                        scripts,
                        receipt,
                        receipt_sha256_by_method[method_id],
                        method_id,
                        dry_receipt,
                        apply=False,
                        forbidden_tokens_file=forbidden_tokens_file,
                    )
                ),
                *reviewed_public_report_checklist(
                    method_id,
                    dry_receipt,
                    destination,
                ),
                "",
                block(
                    publish_command(
                        scripts,
                        receipt,
                        receipt_sha256_by_method[method_id],
                        method_id,
                        apply_receipt,
                        apply=True,
                        dry_run_receipt=dry_receipt,
                        forbidden_tokens_file=forbidden_tokens_file,
                    )
                ),
            ]
        )

    index_build, index_dry, index_apply = index_commands(root, receipt_stem)
    lines.extend(
        [
            "## 2. Rebuild and publish the public index",
            "",
            block(index_build),
            block(index_dry),
            *public_index_checklist(root, receipt_stem),
            "",
            block(index_apply),
        ]
    )

    text = "\n".join(lines).rstrip() + "\n"
    leaked = [token for token in STALE_TOKENS if token in text]
    if leaked:
        raise AssertionError(
            f"reviewed-public runbook contains stale tokens: {leaked}"
        )
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--receipt-stem", default="terminal")
    parser.add_argument("--forbidden-tokens-file", type=Path)
    parser.add_argument(
        "--private-publication-receipt",
        action="append",
        type=Path,
        required=True,
        help=(
            "repeat once for each private publication receipt, "
            "in canonical report-method order"
        ),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    missing = missing_required_files(required_existing(root))
    if missing:
        raise SystemExit(
            "Fail-closed: missing reviewed-public runbook prerequisites: "
            + ", ".join(str(path) for path in missing)
        )
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")
    preexisting = preexisting_create_only_paths(
        required_absent(root, args.receipt_stem)
    )
    if preexisting:
        raise SystemExit(
            "Fail-closed: reviewed-public create-only outputs already exist: "
            + ", ".join(str(path) for path in preexisting)
        )

    try:
        receipt_summaries = validate_private_report_receipts(
            args.private_publication_receipt
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    write_once(
        args.output,
        render(
            root,
            args.private_publication_receipt,
            args.receipt_stem,
            receipt_summaries,
            forbidden_tokens_file=args.forbidden_tokens_file,
        ),
    )
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
