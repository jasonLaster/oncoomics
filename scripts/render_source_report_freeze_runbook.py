#!/usr/bin/env python3
"""Render private-freeze commands for the seven source HRD report packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from hrd_report_inventory import (
    REQUIRED_METHOD_IDS,
    source_report_packet_dirs,
)
from publish_reviewed_public_report import METHOD_CONTRACTS, REGION, RUN_ID
from render_ai_synthesis_runbook import (
    FORBIDDEN_TOKENS,
    required_absent as ai_required_absent,
    required_existing as ai_required_existing,
)
from runbook_io import (
    Raw,
    bash_block,
    block,
    missing_required_files,
    preexisting_create_only_paths,
    shell_join,
    source_private_receipt_path,
    timestamped_runbook_assignment,
    unique_paths,
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


def forbidden_flags() -> list[str]:
    return [
        token
        for value in FORBIDDEN_TOKENS
        for token in ("--forbidden-token", value)
    ]


def source_packet_dirs(
    root: Path,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
) -> dict[str, Path]:
    return source_report_packet_dirs(
        root,
        RUN_ID,
        sigprofiler_report_dir,
        sequenza_report_dir,
    )


def validate_packet_dirs(paths: dict[str, Path]) -> None:
    if tuple(paths) != REQUIRED_METHOD_IDS:
        raise ValueError(
            "source packet directories must follow the pinned seven-method order"
        )
    missing = [
        f"{method_id}={path}"
        for method_id, path in paths.items()
        if path.is_symlink() or not path.is_dir()
    ]
    if missing:
        raise ValueError("source packet directories are missing: " + ", ".join(missing))

    for method_id, path in paths.items():
        expected = set(METHOD_CONTRACTS[method_id]["files"])
        observed = {child.name for child in path.iterdir()}
        if observed != expected:
            missing_files = sorted(expected - observed)
            unexpected = sorted(observed - expected)
            details = []
            if missing_files:
                details.append("missing " + ",".join(missing_files))
            if unexpected:
                details.append("unexpected " + ",".join(unexpected))
            raise ValueError(
                f"{method_id} packet directory inventory is not exact: "
                + "; ".join(details)
            )

        invalid = sorted(
            child.name
            for child in path.iterdir()
            if child.is_symlink() or not child.is_file()
        )
        if invalid:
            raise ValueError(
                f"{method_id} packet directory contains invalid paths: "
                + ",".join(invalid)
            )


def receipt_path(root: Path, receipt_stem: str, method_id: str) -> Path:
    return source_private_receipt_path(root, receipt_stem, method_id)


def publish_command(
    scripts: Path,
    packet_dir: Path,
    method_id: str,
    receipt_output: Path,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "publish_private_report.py",
        "--packet-dir",
        packet_dir,
        "--method-id",
        method_id,
        "--receipt-output",
        receipt_output,
        "--region",
        REGION,
        *forbidden_flags(),
        "--apply",
    ]


def ai_runbook_command(
    scripts: Path,
    root: Path,
    output: str | Path,
    receipt_paths: Iterable[Path],
    receipt_stem: str = "terminal",
) -> list[str | Path]:
    return [
        "python3",
        scripts / "render_ai_synthesis_runbook.py",
        "--output",
        output,
        "--root",
        root,
        "--receipt-stem",
        receipt_stem,
        *[
            token
            for path in receipt_paths
            for token in ("--private-publication-receipt", path)
        ],
    ]


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return unique_paths(
        (
            scripts / "hrd_report_inventory.py",
            scripts / "forbidden_text.py",
            scripts / "publish_private_report.py",
            scripts / "render_ai_synthesis_runbook.py",
            *ai_required_existing(root),
        )
    )


def required_absent(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    return (
        *(
            receipt_path(root, receipt_stem, method_id)
            for method_id in REQUIRED_METHOD_IDS
        ),
        *ai_required_absent(root, receipt_stem),
    )


def render(
    root: Path,
    receipt_stem: str,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
) -> str:
    scripts = root / "scripts"
    packet_dirs = source_packet_dirs(root, sigprofiler_report_dir, sequenza_report_dir)
    receipt_paths = [
        receipt_path(root, receipt_stem, method_id)
        for method_id in REQUIRED_METHOD_IDS
    ]

    lines = [
        "# Diana WGS seven-source private freeze handoff",
        "",
        f"- Run: `{RUN_ID}`",
        "- Boundary: freeze each reviewed source HRD packet with the checked-in "
        "private publisher, then render the exact seven-receipt AI review and "
        "comparative-synthesis handoff.",
        "- Preserve the canonical seven-method order pinned in "
        "`scripts/hrd_report_inventory.py`.",
        "",
        "## 1. Freeze the seven source report packets",
        "",
    ]
    for method_id, packet_dir in packet_dirs.items():
        lines.extend(
            [
                f"### {method_id}",
                "",
                block(
                    publish_command(
                        scripts,
                        packet_dir,
                        method_id,
                        receipt_path(root, receipt_stem, method_id),
                    )
                ),
            ]
        )

    lines.extend(
        [
            "## 2. Render the independent AI review and synthesis handoff",
            "",
            bash_block(
                [
                    timestamped_runbook_assignment(
                        "AI_REVIEW_RUNBOOK",
                        root / ".codex-tmp/hrd-reports/ai-review",
                        f"{receipt_stem}.post-reports-runbook",
                    ),
                    shell_join(
                        ai_runbook_command(
                            scripts,
                            root,
                            Raw('"$AI_REVIEW_RUNBOOK"'),
                            receipt_paths,
                            receipt_stem,
                        )
                    ),
                ]
            ),
        ]
    )

    text = "\n".join(lines).rstrip() + "\n"
    leaked = [token for token in STALE_TOKENS if token in text]
    if leaked:
        raise AssertionError(f"source freeze runbook contains stale tokens: {leaked}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--receipt-stem", default="terminal")
    parser.add_argument("--sigprofiler-report-dir", type=Path)
    parser.add_argument("--sequenza-report-dir", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    missing = missing_required_files(required_existing(root))
    if missing:
        raise SystemExit(
            "Fail-closed: missing source freeze runbook prerequisites: "
            + ", ".join(str(path) for path in missing)
        )
    try:
        validate_packet_dirs(
            source_packet_dirs(
                root,
                args.sigprofiler_report_dir,
                args.sequenza_report_dir,
            )
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    preexisting = preexisting_create_only_paths(
        required_absent(root, args.receipt_stem)
    )
    if preexisting:
        raise SystemExit(
            "Fail-closed: source private-freeze create-only outputs already exist: "
            + ", ".join(str(path) for path in preexisting)
        )
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")

    write_once(
        args.output,
        render(
            root,
            args.receipt_stem,
            args.sigprofiler_report_dir,
            args.sequenza_report_dir,
        ),
    )
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
