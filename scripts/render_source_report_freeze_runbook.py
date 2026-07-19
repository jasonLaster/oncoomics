#!/usr/bin/env python3
"""Render private-freeze commands for the seven source HRD report packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

from forbidden_text import DEFAULT_FORBIDDEN_TOKENS
from generate_blocked_hrd_crosscheck_reports import (
    TERMINAL_SOURCE_REPORT_BINDING_SCOPE,
)
from hrd_report_inventory import (
    BLOCKED_CROSSCHECK_METHOD_IDS,
    EXECUTABLE_CROSSCHECK_METHOD_IDS,
    REQUIRED_METHOD_IDS,
    source_report_packet_dirs,
)
from publish_private_report import validate_packet_dir as validate_private_packet_dir
from publish_reviewed_public_report import METHOD_CONTRACTS, REGION, RUN_ID
from render_ai_synthesis_runbook import (
    required_absent as ai_required_absent,
)
from render_ai_synthesis_runbook import (
    required_existing as ai_required_existing,
)
from runbook_io import (
    Raw,
    bash_block,
    block,
    load_json_object,
    missing_required_files,
    preexisting_create_only_paths,
    require_real_input_file,
    shell_join,
    source_private_receipt_path,
    timestamped_runbook_assignment,
    unique_paths,
    write_once,
)
from validate_phase3_fast_report_packets import (
    canonical_forbidden_tokens,
    sha256_forbidden_tokens,
    validate_validation_receipt_matches_packets,
)

STALE_TOKENS = (
    ".codex-tmp/hrd-reports/publish_private_report.py",
    ".codex-tmp/hrd-reports/ai-review/render_ai_synthesis_runbook.py",
    "--receipt-upload-output",
    "--private-publication-upload-receipt",
    "--source-dir",
    "--expected-file",
)
BLOCKED_SOURCE_METHOD_IDS = (
    "deterministic_full_wgs",
    "rosalind_diana_wgs",
    *EXECUTABLE_CROSSCHECK_METHOD_IDS,
)


def forbidden_flags() -> list[str]:
    return [token for value in DEFAULT_FORBIDDEN_TOKENS for token in ("--forbidden-token", value)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_packet_dirs(
    root: Path,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
) -> dict[str, Path]:
    return source_report_packet_dirs(
        root,
        RUN_ID,
        sigprofiler_report_dir,
        sequenza_report_dir,
        deterministic_report_dir=deterministic_report_dir,
        rosalind_report_dir=rosalind_report_dir,
        blocked_crosscheck_root=blocked_crosscheck_root,
    )


def validate_packet_dirs(
    paths: dict[str, Path],
    phase3_fast_report_packet_validation: Path | None = None,
    phase3_fast_forbidden_tokens_file: Path | None = None,
) -> None:
    if (
        phase3_fast_report_packet_validation is not None
        and phase3_fast_forbidden_tokens_file is None
    ):
        raise ValueError(
            "Phase 3 fast report validation requires the forbidden-token file"
        )

    forbidden_tokens = tuple(DEFAULT_FORBIDDEN_TOKENS)
    expected_forbidden_tokens_sha256 = None
    if phase3_fast_forbidden_tokens_file is not None:
        require_real_input_file(
            phase3_fast_forbidden_tokens_file,
            "Phase 3 fast forbidden-token file",
        )
        forbidden_tokens = canonical_forbidden_tokens(phase3_fast_forbidden_tokens_file.read_text(encoding="utf-8"))
        expected_forbidden_tokens_sha256 = sha256_forbidden_tokens(forbidden_tokens)

    if tuple(paths) != REQUIRED_METHOD_IDS:
        raise ValueError("source packet directories must follow the pinned seven-method order")
    missing = [f"{method_id}={path}" for method_id, path in paths.items() if path.is_symlink() or not path.is_dir()]
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
            raise ValueError(f"{method_id} packet directory inventory is not exact: " + "; ".join(details))

        invalid = sorted(child.name for child in path.iterdir() if child.is_symlink() or not child.is_file())
        if invalid:
            raise ValueError(f"{method_id} packet directory contains invalid paths: " + ",".join(invalid))
        try:
            validate_private_packet_dir(path, method_id, forbidden_tokens)
        except ValueError as error:
            raise ValueError(f"{method_id} packet directory is invalid: {error}") from error
    validate_blocked_source_bindings(paths)
    if phase3_fast_report_packet_validation is not None:
        assert expected_forbidden_tokens_sha256 is not None
        validate_validation_receipt_matches_packets(
            phase3_fast_report_packet_validation,
            paths,
            forbidden_tokens,
            expected_forbidden_tokens_sha256,
            ("deterministic_full_wgs", "rosalind_diana_wgs"),
        )


def validate_blocked_source_bindings(paths: dict[str, Path]) -> None:
    expected = {
        method_id: sha256(paths[method_id] / "report_manifest.json")
        for method_id in BLOCKED_SOURCE_METHOD_IDS
    }
    expected_source_sha256 = {
        "generator": sha256(
            Path(__file__).with_name("generate_blocked_hrd_crosscheck_reports.py")
        ),
        **{
            f"{method_id}_report_manifest": digest
            for method_id, digest in expected.items()
        },
    }
    expected_lines = [
        f"- {method_id} report_manifest_sha256: `{digest}`"
        for method_id, digest in expected.items()
    ]

    for blocked_method_id in BLOCKED_CROSSCHECK_METHOD_IDS:
        packet_dir = paths[blocked_method_id]
        manifest = load_json_object(
            packet_dir / "report_manifest.json",
            f"{blocked_method_id} blocked report manifest",
        )
        method_spec = load_json_object(
            packet_dir / "method_spec.json",
            f"{blocked_method_id} blocked method spec",
        )
        review_summary = manifest.get("review_summary")
        source_sha256 = manifest.get("source_sha256")
        report_path = packet_dir / "report.md"
        require_real_input_file(
            report_path,
            f"{blocked_method_id} blocked report",
        )
        report = report_path.read_text(encoding="utf-8")
        observed_lines = [
            line
            for line in report.splitlines()
            if "report_manifest_sha256" in line
        ]
        if (
            method_spec.get("source_report_manifests") != expected
            or method_spec.get("source_report_binding_scope")
            != TERMINAL_SOURCE_REPORT_BINDING_SCOPE
            or manifest.get("source_report_binding_scope")
            != TERMINAL_SOURCE_REPORT_BINDING_SCOPE
            or not isinstance(review_summary, dict)
            or review_summary.get("source_report_manifests") != expected
            or review_summary.get("source_report_binding_scope")
            != TERMINAL_SOURCE_REPORT_BINDING_SCOPE
            or source_sha256 != expected_source_sha256
            or "source_report_manifests: `not_bound`" in report
            or observed_lines != expected_lines
        ):
            raise ValueError(
                f"{blocked_method_id} packet is not bound to current upstream "
                "report manifests"
            )


def receipt_path(root: Path, receipt_stem: str, method_id: str) -> Path:
    return source_private_receipt_path(root, receipt_stem, method_id)


def dry_receipt_path(root: Path, receipt_stem: str, method_id: str) -> Path:
    return source_private_receipt_path(root, receipt_stem, method_id).with_suffix(
        ".dry.json"
    )


def publish_command(
    scripts: Path,
    packet_dir: Path,
    method_id: str,
    receipt_output: Path,
    forbidden_tokens_file: Path | None = None,
    *,
    apply: bool,
    dry_run_receipt: Path | None = None,
) -> list[str | Path]:
    forbidden_tokens_file_flags: list[str | Path] = (
        ["--forbidden-tokens-file", forbidden_tokens_file] if forbidden_tokens_file is not None else []
    )
    command: list[str | Path] = [
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
        *forbidden_tokens_file_flags,
    ]
    if dry_run_receipt is not None:
        command.extend(["--dry-run-receipt", dry_run_receipt])
    if apply:
        command.append("--apply")
    return command


def ai_runbook_command(
    scripts: Path,
    root: Path,
    output: str | Path,
    receipt_paths: Iterable[Path],
    receipt_stem: str = "terminal",
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    forbidden_tokens_file: Path | None = None,
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
            for flag, path in (
                ("--deterministic-report-dir", deterministic_report_dir),
                ("--rosalind-report-dir", rosalind_report_dir),
                ("--blocked-crosscheck-root", blocked_crosscheck_root),
                ("--sigprofiler-report-dir", sigprofiler_report_dir),
                ("--sequenza-report-dir", sequenza_report_dir),
                ("--forbidden-tokens-file", forbidden_tokens_file),
            )
            if path is not None
            for token in (flag, path)
        ],
        *[token for path in receipt_paths for token in ("--private-publication-receipt", path)],
    ]


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return unique_paths(
        (
            scripts / "hrd_report_inventory.py",
            scripts / "forbidden_text.py",
            scripts / "generate_blocked_hrd_crosscheck_reports.py",
            scripts / "publish_private_report.py",
            scripts / "validate_phase3_fast_report_packets.py",
            scripts / "render_ai_synthesis_runbook.py",
            *ai_required_existing(root),
        )
    )


def required_absent(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    return (
        *(dry_receipt_path(root, receipt_stem, method_id) for method_id in REQUIRED_METHOD_IDS),
        *(receipt_path(root, receipt_stem, method_id) for method_id in REQUIRED_METHOD_IDS),
        *ai_required_absent(root, receipt_stem),
    )


def render(
    root: Path,
    receipt_stem: str,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
    phase3_fast_forbidden_tokens_file: Path | None = None,
) -> str:
    scripts = root / "scripts"
    packet_dirs = source_packet_dirs(
        root,
        sigprofiler_report_dir,
        sequenza_report_dir,
        deterministic_report_dir=deterministic_report_dir,
        rosalind_report_dir=rosalind_report_dir,
        blocked_crosscheck_root=blocked_crosscheck_root,
    )
    receipt_paths = [receipt_path(root, receipt_stem, method_id) for method_id in REQUIRED_METHOD_IDS]

    lines = [
        "# Diana WGS seven-source private freeze handoff",
        "",
        f"- Run: `{RUN_ID}`",
        "- Boundary: freeze each reviewed source HRD packet with the checked-in "
        "private publisher, then render the exact seven-receipt AI review and "
        "comparative-synthesis handoff.",
        "- Preserve the canonical seven-method order pinned in `scripts/hrd_report_inventory.py`.",
        "",
        "## 1. Freeze the seven source report packets",
        "",
    ]
    for method_id, packet_dir in packet_dirs.items():
        dry_receipt = dry_receipt_path(root, receipt_stem, method_id)
        apply_receipt = receipt_path(root, receipt_stem, method_id)
        lines.extend(
            [
                f"### {method_id}",
                "",
                block(
                    publish_command(
                        scripts,
                        packet_dir,
                        method_id,
                        dry_receipt,
                        forbidden_tokens_file=phase3_fast_forbidden_tokens_file,
                        apply=False,
                    )
                ),
                block(
                    publish_command(
                        scripts,
                        packet_dir,
                        method_id,
                        apply_receipt,
                        forbidden_tokens_file=phase3_fast_forbidden_tokens_file,
                        apply=True,
                        dry_run_receipt=dry_receipt,
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
                            deterministic_report_dir=deterministic_report_dir,
                            rosalind_report_dir=rosalind_report_dir,
                            blocked_crosscheck_root=blocked_crosscheck_root,
                            sigprofiler_report_dir=sigprofiler_report_dir,
                            sequenza_report_dir=sequenza_report_dir,
                            forbidden_tokens_file=phase3_fast_forbidden_tokens_file,
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
    parser.add_argument("--deterministic-report-dir", type=Path)
    parser.add_argument("--rosalind-report-dir", type=Path)
    parser.add_argument("--blocked-crosscheck-root", type=Path)
    parser.add_argument("--sigprofiler-report-dir", type=Path)
    parser.add_argument("--sequenza-report-dir", type=Path)
    parser.add_argument("--phase3-fast-report-packet-validation", type=Path)
    parser.add_argument(
        "--forbidden-tokens-file",
        "--phase3-fast-forbidden-tokens-file",
        dest="forbidden_tokens_file",
        type=Path,
    )
    args = parser.parse_args()

    root = args.root.resolve()
    missing = missing_required_files(required_existing(root))
    if missing:
        raise SystemExit("Fail-closed: missing source freeze runbook prerequisites: " + ", ".join(str(path) for path in missing))
    try:
        validate_packet_dirs(
            source_packet_dirs(
                root,
                args.sigprofiler_report_dir,
                args.sequenza_report_dir,
                deterministic_report_dir=args.deterministic_report_dir,
                rosalind_report_dir=args.rosalind_report_dir,
                blocked_crosscheck_root=args.blocked_crosscheck_root,
            ),
            args.phase3_fast_report_packet_validation,
            args.forbidden_tokens_file,
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    preexisting = preexisting_create_only_paths(required_absent(root, args.receipt_stem))
    if preexisting:
        raise SystemExit(
            "Fail-closed: source private-freeze create-only outputs already exist: " + ", ".join(str(path) for path in preexisting)
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
            deterministic_report_dir=args.deterministic_report_dir,
            rosalind_report_dir=args.rosalind_report_dir,
            blocked_crosscheck_root=args.blocked_crosscheck_root,
            phase3_fast_forbidden_tokens_file=args.forbidden_tokens_file,
        ),
    )
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
