#!/usr/bin/env python3
"""Render exact AI-review and comparative-synthesis handoff commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
from pathlib import Path
from typing import Any, Iterable

from ai_model_catalog import (
    MODEL_CATALOG_RECEIPT,
    MODEL_CATALOG_VERIFIED_AT,
    REVIEWER_A,
    REVIEWER_B,
)
from hrd_report_inventory import (
    BLOCKED_CROSSCHECK_REPORT_DIRS,
    REPORT_METHOD_IDS,
    REQUIRED_METHOD_IDS,
)
from prepare_ai_review_run import METHOD_ARGUMENTS
from publish_reviewed_public_report import (
    REGION,
    RUN_ID,
    SUBJECT_ALIAS,
    validate_private_receipt,
)

FORBIDDEN_TOKENS = ("E019_S01", "DRF-PSN49561", "echo-personalis", "personalis")


class Raw(str):
    """Shell token that should be emitted without shell quoting."""


def shell_join(values: Iterable[str | os.PathLike[str]]) -> str:
    return " ".join(
        str(value) if isinstance(value, Raw) else shlex.quote(os.fspath(value))
        for value in values
    )


def block(command: Iterable[str | os.PathLike[str]]) -> str:
    return "```bash\n" + shell_join(command) + "\n```\n"


def bash_block(lines: Iterable[str]) -> str:
    return "```bash\n" + "\n".join(lines) + "\n```\n"


def timestamped_runbook_assignment(variable: str, directory: Path, stem: str) -> str:
    prefix = shlex.quote(str(directory / f"{stem}."))
    return f"{variable}={prefix}$(date -u +%Y%m%dT%H%M%SZ).md"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def validate_private_report_receipt(
    receipt_path: Path,
    method_id: str,
    report_manifest_path: Path,
) -> dict[str, str | int]:
    _, expected, rows = validate_private_receipt(receipt_path, method_id)
    manifest_row = next(
        (row for row in rows if row["relative_path"] == "report_manifest.json"),
        None,
    )
    if manifest_row is None:
        raise ValueError(f"{method_id} private receipt omits report_manifest.json")
    if report_manifest_path.is_symlink() or not report_manifest_path.is_file():
        raise ValueError(f"{method_id} local report_manifest.json is missing")

    local_manifest_sha256 = sha256_path(report_manifest_path)
    if manifest_row["sha256"] != local_manifest_sha256:
        raise ValueError(f"{method_id} local report_manifest.json is not receipt-bound")

    return {
        "method_id": method_id,
        "receipt": str(receipt_path),
        "destination_prefix": str(
            load_object(receipt_path, f"{method_id} private publication receipt")[
                "destination_prefix"
            ]
        ),
        "report_manifest_version_id": str(manifest_row["version_id"]),
        "report_manifest_sha256": local_manifest_sha256,
        "object_count": len(expected),
    }


def validate_private_report_receipts(
    receipt_paths: Iterable[Path],
    manifests: dict[str, Path],
) -> tuple[dict[str, str | int], ...]:
    paths = list(receipt_paths)
    if len(paths) != len(REQUIRED_METHOD_IDS):
        raise ValueError("exactly seven private publication receipts are required")

    method_ids = [
        str(load_object(path, "private publication receipt").get("method_id", ""))
        for path in paths
    ]
    if method_ids != list(REQUIRED_METHOD_IDS):
        raise ValueError(
            "private publication receipts must be passed in canonical "
            f"seven-method order; observed={method_ids!r}"
        )

    summaries = []
    for index, path in enumerate(paths):
        method_id = REQUIRED_METHOD_IDS[index]
        summaries.append(
            validate_private_report_receipt(path, method_id, manifests[method_id])
        )
    return tuple(summaries)


def report_manifest_paths(
    root: Path,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
) -> dict[str, Path]:
    reports = root / ".codex-tmp/hrd-reports"
    crosschecks = reports / "crosschecks"
    blocked = reports / "blocked-crosschecks"
    paths = {
        "deterministic_full_wgs": (
            reports / "deterministic-full/report/report_manifest.json"
        ),
        "rosalind_diana_wgs": (
            root / "results/rosalind_hrd/diana_wgs" / RUN_ID / "report_manifest.json"
        ),
        "sequenza_scarhrd": (
            sequenza_report_dir or crosschecks / "sequenza_scarhrd"
        )
        / "report_manifest.json",
        "sigprofiler_sbs3": (
            sigprofiler_report_dir or crosschecks / "sigprofiler_sbs3"
        )
        / "report_manifest.json",
    }
    for method_id, directory in BLOCKED_CROSSCHECK_REPORT_DIRS.items():
        paths[method_id] = blocked / directory / "report_manifest.json"
    return paths


def prepare_manifest_flags(paths: dict[str, Path]) -> list[str | Path]:
    return [
        token
        for method_id, argument in METHOD_ARGUMENTS
        for token in ("--" + argument.replace("_", "-"), paths[method_id])
    ]


def manifest_flags(paths: dict[str, Path], flag: str = "--source-manifest") -> list[str | Path]:
    return [
        token
        for method_id in REQUIRED_METHOD_IDS
        for token in (flag, paths[method_id])
    ]


def require_method_flags() -> list[str]:
    return [
        token
        for method_id in REQUIRED_METHOD_IDS
        for token in ("--require-method", method_id)
    ]


def forbidden_flags() -> list[str]:
    return [
        token
        for value in FORBIDDEN_TOKENS
        for token in ("--forbidden-token", value)
    ]


def append_receipt_suffix(stem: Path, suffix: str) -> Path:
    return stem.parent / f"{stem.name}{suffix}"


def publish_command(
    scripts: Path,
    source: Path,
    method_id: str,
    receipt_stem: Path,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "publish_private_report.py",
        "--packet-dir",
        source,
        "--method-id",
        method_id,
        "--receipt-output",
        append_receipt_suffix(receipt_stem, ".private.json"),
        "--region",
        REGION,
        *forbidden_flags(),
        "--apply",
    ]


def reviewed_publication_receipt_paths(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    reports = root / ".codex-tmp/hrd-reports"
    source_receipt_root = reports / "deterministic-full"
    ai_receipt_root = reports / "ai-review" / RUN_ID / "publication-receipts"
    receipt_paths = {
        method_id: source_receipt_root / f"{receipt_stem}.{method_id}.private.json"
        for method_id in REQUIRED_METHOD_IDS
    }
    receipt_paths.update(
        {
            "ai_review_reviewer_a": (
                ai_receipt_root / f"{receipt_stem}.ai-reviewer-a.private.json"
            ),
            "ai_review_reviewer_b": (
                ai_receipt_root / f"{receipt_stem}.ai-reviewer-b.private.json"
            ),
            "comparative_hrd_synthesis": (
                ai_receipt_root / f"{receipt_stem}.comparative-synthesis.private.json"
            ),
        }
    )
    return tuple(receipt_paths[method_id] for method_id in REPORT_METHOD_IDS)


def comparative_synthesis_command(
    scripts: Path,
    manifests: dict[str, Path],
    bundle: Path,
    reviewer_a: Path,
    reviewer_b: Path,
    synthesis: Path,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "generate_comparative_hrd_synthesis.py",
        *manifest_flags(manifests),
        *require_method_flags(),
        "--review-bundle",
        bundle / "review_bundle.json",
        "--bundle-manifest",
        bundle / "bundle_manifest.json",
        "--reviewer-a-dir",
        reviewer_a,
        "--reviewer-b-dir",
        reviewer_b,
        "--output-dir",
        synthesis,
    ]


def reviewed_publication_runbook_command(
    scripts: Path,
    output: str | Path,
    receipt_paths: Iterable[Path],
) -> list[str | Path]:
    return [
        "python3",
        scripts / "render_reviewed_publication_runbook.py",
        "--output",
        output,
        *[
            token
            for path in receipt_paths
            for token in ("--private-publication-receipt", path)
        ],
    ]


def model_catalog_receipt_path(root: Path) -> Path:
    return (
        root
        / ".codex-tmp/hrd-reports/ai-review/model-catalog-receipts"
        / RUN_ID
        / MODEL_CATALOG_RECEIPT
    )


def ai_private_receipt_paths(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    receipt_root = (
        root
        / ".codex-tmp/hrd-reports/ai-review"
        / RUN_ID
        / "publication-receipts"
    )
    return (
        receipt_root / f"{receipt_stem}.ai-reviewer-a.private.json",
        receipt_root / f"{receipt_stem}.ai-reviewer-b.private.json",
        receipt_root / f"{receipt_stem}.comparative-synthesis.private.json",
    )


def reviewed_public_receipt_paths(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    return (
        *(
            root
            / ".codex-tmp/hrd-reports/publication"
            / f"{receipt_stem}.{method_id}.public{suffix}.json"
            for method_id in REPORT_METHOD_IDS
            for suffix in (".dry", "")
        ),
        root / ".codex-tmp/public-index" / f"public-index.{receipt_stem}.dry.json",
        root / ".codex-tmp/public-index" / f"public-index.{receipt_stem}.json",
    )


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return (
        scripts / "hrd_report_inventory.py",
        scripts / "prepare_ai_review_run.py",
        scripts / "build_ai_review_bundle.py",
        scripts / "stage_ai_review_inputs.py",
        scripts / "validate_ai_review.py",
        scripts / "finalize_ai_review.py",
        scripts / "generate_comparative_hrd_synthesis.py",
        scripts / "publish_private_report.py",
        scripts / "render_reviewed_publication_runbook.py",
        scripts / "write_ai_model_catalog_receipt.py",
    )


def required_absent(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    return (
        model_catalog_receipt_path(root),
        root / ".codex-tmp/hrd-reports/ai-review" / RUN_ID,
        root / ".codex-tmp/hrd-reports/synthesis" / RUN_ID,
        *ai_private_receipt_paths(root, receipt_stem),
        *reviewed_public_receipt_paths(root, receipt_stem),
    )


def write_once(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def render(
    root: Path,
    receipt_stem: str,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    receipt_summaries: tuple[dict[str, str | int], ...] = (),
) -> str:
    reports = root / ".codex-tmp/hrd-reports"
    scripts = root / "scripts"
    manifests = report_manifest_paths(root, sigprofiler_report_dir, sequenza_report_dir)

    run_root = reports / "ai-review" / RUN_ID
    catalog = model_catalog_receipt_path(root)
    bundle = run_root / "bundle"
    reviewer_inputs = run_root / "reviewer-inputs"
    reviewer_a = run_root / "reviewer-a"
    reviewer_b = run_root / "reviewer-b"
    synthesis = reports / "synthesis" / RUN_ID
    receipt_root = run_root / "publication-receipts"

    lines = [
        "# Diana WGS independent AI review and synthesis handoff",
        "",
        f"- Run: `{RUN_ID}`",
        f"- Subject alias: `{SUBJECT_ALIAS}`",
        "- Boundary: prepare one de-identified seven-method bundle, stage exact "
        "two-file reviewer inputs, validate two isolated model outputs, "
        "generate the comparative synthesis, then privately publish reviewer "
        "and synthesis reports.",
        "- Do not run until all seven source report manifests below exist, have "
        "been privately frozen, and match the passed private publication "
        "receipts exactly.",
        "",
    ]
    if receipt_summaries:
        lines.extend(
            [
                "## 0. Private publication receipt gate",
                "",
                "The renderer bound this handoff to seven passed private "
                "publication receipts in canonical method order:",
                "",
            ]
        )
        for summary in receipt_summaries:
            lines.append(
                f"- `{summary['method_id']}`: `report_manifest.json` VersionId "
                f"`{summary['report_manifest_version_id']}`, SHA-256 "
                f"`{summary['report_manifest_sha256']}`"
            )
        lines.append("")

    lines.extend(
        [
            "## 1. Materialize the pinned model catalog receipt",
            "",
            block(
                [
                    "python3",
                    scripts / "write_ai_model_catalog_receipt.py",
                    "--output",
                    catalog,
                    "--attest-models-latest",
                ]
            ),
            "## 2. Prepare the seven-method AI review run",
            "",
            block(
                [
                    "python3",
                    scripts / "prepare_ai_review_run.py",
                    *prepare_manifest_flags(manifests),
                    "--output-dir",
                    run_root,
                    "--subject-alias",
                    SUBJECT_ALIAS,
                    "--model-catalog-receipt",
                    catalog,
                    "--model-catalog-verified-at",
                    MODEL_CATALOG_VERIFIED_AT,
                    "--reviewer-a-provider",
                    REVIEWER_A[0],
                    "--reviewer-a-model-id",
                    REVIEWER_A[1],
                    "--reviewer-b-provider",
                    REVIEWER_B[0],
                    "--reviewer-b-model-id",
                    REVIEWER_B[1],
                    *forbidden_flags(),
                ]
            ),
            "## 3. Invoke reviewers in isolated sessions",
            "",
            f"- Reviewer A receives only "
            f"`{reviewer_inputs / 'reviewer-a-input/review_bundle.json'}` and "
            f"`{reviewer_inputs / 'reviewer-a-input/reviewer-a.prompt.md'}`; "
            f"write only `report.md`, `claims.csv`, and `review_manifest.json` "
            f"into `{reviewer_a}`.",
            f"- Reviewer B receives only "
            f"`{reviewer_inputs / 'reviewer-b-input/review_bundle.json'}` and "
            f"`{reviewer_inputs / 'reviewer-b-input/reviewer-b.prompt.md'}`; "
            f"write only `report.md`, `claims.csv`, and `review_manifest.json` "
            f"into `{reviewer_b}`.",
            "",
            "## 4. Validate isolated reviewer outputs",
            "",
            block(
                [
                    "python3",
                    scripts / "validate_ai_review.py",
                    "--bundle-dir",
                    bundle,
                    *manifest_flags(manifests),
                    "--reviewer",
                    "A",
                    "--review-dir",
                    reviewer_a,
                    "--model-catalog-receipt",
                    catalog,
                    *forbidden_flags(),
                ]
            ),
            block(
                [
                    "python3",
                    scripts / "validate_ai_review.py",
                    "--bundle-dir",
                    bundle,
                    *manifest_flags(manifests),
                    "--reviewer",
                    "B",
                    "--review-dir",
                    reviewer_b,
                    "--other-review-dir",
                    reviewer_a,
                    "--model-catalog-receipt",
                    catalog,
                    *forbidden_flags(),
                ]
            ),
            "## 5. Generate the comparative synthesis",
            "",
            block(
                comparative_synthesis_command(
                    scripts,
                    manifests,
                    bundle,
                    reviewer_a,
                    reviewer_b,
                    synthesis,
                )
            ),
            "## 6. Finalize AI reviewer report manifests",
            "",
            block(
                [
                    "python3",
                    scripts / "finalize_ai_review.py",
                    "--bundle-dir",
                    bundle,
                    "--review-dir",
                    reviewer_a,
                    "--reviewer",
                    "A",
                    "--model-catalog-receipt",
                    catalog,
                    "--output",
                    reviewer_a / "report_manifest.json",
                ]
            ),
            block(
                [
                    "python3",
                    scripts / "finalize_ai_review.py",
                    "--bundle-dir",
                    bundle,
                    "--review-dir",
                    reviewer_b,
                    "--reviewer",
                    "B",
                    "--model-catalog-receipt",
                    catalog,
                    "--output",
                    reviewer_b / "report_manifest.json",
                ]
            ),
            "## 7. Publish reviewed private AI and synthesis reports",
            "",
            block(
                publish_command(
                    scripts,
                    reviewer_a,
                    "ai_review_reviewer_a",
                    receipt_root / f"{receipt_stem}.ai-reviewer-a",
                )
            ),
            block(
                publish_command(
                    scripts,
                    reviewer_b,
                    "ai_review_reviewer_b",
                    receipt_root / f"{receipt_stem}.ai-reviewer-b",
                )
            ),
            block(
                publish_command(
                    scripts,
                    synthesis,
                    "comparative_hrd_synthesis",
                    receipt_root / f"{receipt_stem}.comparative-synthesis",
                )
            ),
            "## 8. Render the reviewed-public publication handoff",
            "",
            bash_block(
                [
                    timestamped_runbook_assignment(
                        "REVIEWED_PUBLIC_RUNBOOK",
                        reports / "publication",
                        f"{receipt_stem}.reviewed-public-runbook",
                    ),
                    shell_join(
                        reviewed_publication_runbook_command(
                            scripts,
                            Raw('"$REVIEWED_PUBLIC_RUNBOOK"'),
                            reviewed_publication_receipt_paths(root, receipt_stem),
                        )
                    ),
                ]
            ),
        ]
    )

    text = "\n".join(lines).rstrip() + "\n"
    forbidden = (
        "PRIVATE" + "_",
        "REPLACE" + "_WITH",
        "EXACT" + "_",
        "ISO" + "_8601",
        "ISO" + "-8601",
    )
    leaked = [token for token in forbidden if token in text]
    if leaked:
        raise AssertionError(f"runbook contains placeholders: {leaked}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--receipt-stem", default="terminal")
    parser.add_argument("--sigprofiler-report-dir", type=Path)
    parser.add_argument("--sequenza-report-dir", type=Path)
    parser.add_argument(
        "--private-publication-receipt",
        action="append",
        type=Path,
        required=True,
        help=(
            "repeat once for each source-method private publication receipt, "
            "in canonical method-inventory order"
        ),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    missing = [path for path in required_existing(root) if not path.is_file()]
    if missing:
        raise SystemExit(
            "Fail-closed: missing AI synthesis runbook prerequisites: "
            + ", ".join(str(path) for path in missing)
        )
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")
    preexisting = [
        path
        for path in required_absent(root, args.receipt_stem)
        if path.exists() or path.is_symlink()
    ]
    if preexisting:
        raise SystemExit(
            "Fail-closed: AI synthesis create-only outputs already exist: "
            + ", ".join(str(path) for path in preexisting)
        )

    manifests = report_manifest_paths(
        root,
        args.sigprofiler_report_dir,
        args.sequenza_report_dir,
    )
    try:
        receipt_summaries = validate_private_report_receipts(
            args.private_publication_receipt,
            manifests,
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    write_once(
        args.output,
        render(
            root,
            args.receipt_stem,
            args.sigprofiler_report_dir,
            args.sequenza_report_dir,
            receipt_summaries,
        ),
    )
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
