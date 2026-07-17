#!/usr/bin/env python3
"""Render reviewed-public publication commands for all HRD report packets."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path
from typing import Any, Iterable

from hrd_report_inventory import REPORT_METHOD_IDS
from publish_reviewed_public_report import (
    METHOD_CONTRACTS,
    PRIVATE_BUCKET,
    PRIVATE_KMS_KEY_ARN,
    PUBLIC_BUCKET,
    PUBLIC_ROOT,
    REGION,
    RUN_ID,
    SUBJECT_ALIAS,
    validate_private_receipt,
)
from render_ai_synthesis_runbook import write_once


STALE_TOKENS = (
    ".codex-tmp/hrd-reports/publish_private_report.py",
    ".codex-tmp/hrd-reports/ai-review/render_ai_synthesis_runbook.py",
    "--receipt-upload-output",
    "--private-publication-upload-receipt",
    "--source-dir",
    "--expected-file",
)


def shell_join(values: Iterable[str | os.PathLike[str]]) -> str:
    return " ".join(shlex.quote(os.fspath(value)) for value in values)


def block(command: Iterable[str | os.PathLike[str]]) -> str:
    return "```bash\n" + shell_join(command) + "\n```\n"


def load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"private publication receipt is missing or a symlink: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"private publication receipt is not a JSON object: {path}")
    return value


def validate_private_report_receipts(
    receipt_paths: Iterable[Path],
) -> tuple[dict[str, str | int], ...]:
    paths = list(receipt_paths)
    if len(paths) != len(REPORT_METHOD_IDS):
        raise ValueError("exactly ten private publication receipts are required")

    method_ids = [str(load_object(path).get("method_id", "")) for path in paths]
    if method_ids != list(REPORT_METHOD_IDS):
        raise ValueError(
            "private publication receipts must be passed in canonical "
            f"ten-method order; observed={method_ids!r}"
        )

    summaries = []
    for index, path in enumerate(paths):
        method_id = REPORT_METHOD_IDS[index]
        _, _, rows = validate_private_receipt(path, method_id)
        summaries.append(
            {
                "method_id": method_id,
                "receipt": str(path),
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


def publish_command(
    scripts: Path,
    receipt_path: Path,
    method_id: str,
    output: Path,
    *,
    apply: bool,
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
    if apply:
        command.append("--apply")
    return command


def index_commands(root: Path, receipt_stem: str = "terminal") -> list[list[str | Path]]:
    scripts = root / "scripts"
    index = root / ".codex-tmp/public-index/objects.json"
    receipt_root = root / ".codex-tmp/public-index"
    return [
        [
            "python3",
            scripts / "build_public_results_index.py",
            "--output",
            index,
        ],
        [
            "python3",
            scripts / "publish_public_results_index.py",
            "--index",
            index,
            "--receipt-output",
            receipt_root / f"public-index.{receipt_stem}.dry.json",
        ],
        [
            "python3",
            scripts / "publish_public_results_index.py",
            "--index",
            index,
            "--receipt-output",
            receipt_root / f"public-index.{receipt_stem}.json",
            "--apply",
        ],
    ]


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return (
        scripts / "hrd_report_inventory.py",
        scripts / "publish_reviewed_public_report.py",
        scripts / "build_public_results_index.py",
        scripts / "publish_public_results_index.py",
    )


def render(
    root: Path,
    receipt_paths: Iterable[Path],
    receipt_stem: str,
    receipt_summaries: tuple[dict[str, str | int], ...] = (),
) -> str:
    paths = list(receipt_paths)
    scripts = root / "scripts"

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
    if receipt_summaries:
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
                f"`{summary['destination_prefix']}`"
            )
        lines.append("")

    lines.extend(["## 1. Dry-run and apply reviewed-public reports", ""])
    for index, method_id in enumerate(REPORT_METHOD_IDS):
        receipt = paths[index]
        lines.extend(
            [
                f"### {method_id}",
                "",
                block(
                    publish_command(
                        scripts,
                        receipt,
                        method_id,
                        receipt_output(root, receipt_stem, method_id, ".dry"),
                        apply=False,
                    )
                ),
                block(
                    publish_command(
                        scripts,
                        receipt,
                        method_id,
                        receipt_output(root, receipt_stem, method_id, ""),
                        apply=True,
                    )
                ),
            ]
        )

    lines.extend(
        [
            "## 2. Rebuild and publish the public index",
            "",
            *[block(command) for command in index_commands(root, receipt_stem)],
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
    missing = [path for path in required_existing(root) if not path.is_file()]
    if missing:
        raise SystemExit(
            "Fail-closed: missing reviewed-public runbook prerequisites: "
            + ", ".join(str(path) for path in missing)
        )
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")

    try:
        receipt_summaries = validate_private_report_receipts(
            args.private_publication_receipt
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    write_once(
        args.output,
        render(root, args.private_publication_receipt, args.receipt_stem, receipt_summaries),
    )
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
