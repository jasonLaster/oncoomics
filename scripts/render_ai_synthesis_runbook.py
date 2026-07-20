#!/usr/bin/env python3
"""Render exact AI-review and comparative-synthesis handoff commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from ai_model_catalog import (
    MODEL_CATALOG_RECEIPT,
    MODEL_CATALOG_VERIFIED_AT,
    REVIEWER_A,
    REVIEWER_B,
)
from forbidden_text import DEFAULT_FORBIDDEN_TOKENS
from hrd_report_inventory import (
    AI_REVIEW_METHOD_IDS,
    COMPARATIVE_METHOD_IDS,
    INVENTORY_ID,
    REPORT_METHOD_IDS,
    REQUIRED_METHOD_IDS,
    source_report_manifest_paths,
)
from prepare_ai_review_run import MANIFEST_ARGUMENTS
from publish_reviewed_public_report import (
    METHOD_CONTRACTS,
    REGION,
    RUN_ID,
    SUBJECT_ALIAS,
    exact_non_null_version_id,
    private_report_prefix,
    validate_private_receipt_payload,
)
from render_reviewed_publication_runbook import (
    required_absent as reviewed_public_required_absent,
)
from render_reviewed_publication_runbook import (
    required_existing as reviewed_public_required_existing,
)
from runbook_io import (
    Raw,
    bash_block,
    block,
    load_json_object_with_sha256,
    missing_required_files,
    preexisting_create_only_paths,
    read_stable_file,
    require_real_input_file,
    shell_join,
    sha256_bytes,
    source_private_receipt_paths,
    timestamped_runbook_assignment,
    unique_paths,
    write_once,
)

FORBIDDEN_TOKENS = DEFAULT_FORBIDDEN_TOKENS
AI_PRIVATE_RECEIPT_STEMS = (
    (AI_REVIEW_METHOD_IDS[0], "ai-reviewer-a"),
    (AI_REVIEW_METHOD_IDS[1], "ai-reviewer-b"),
    (COMPARATIVE_METHOD_IDS[0], "comparative-synthesis"),
)
PRIVATE_REPORT_RECEIPT_SUMMARY_KEYS = {
    "method_id",
    "receipt",
    "destination_prefix",
    "report_manifest_version_id",
    "report_manifest_sha256",
    "object_count",
}


def sha256_path(path: Path) -> str:
    return sha256_bytes(read_stable_file(path, f"{path.name} SHA-256 input"))


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


def validate_private_report_receipt(
    receipt_path: Path,
    private_receipt: dict[str, object],
    method_id: str,
    report_manifest_path: Path,
) -> dict[str, str | int]:
    expected, rows = validate_private_receipt_payload(private_receipt, method_id)
    manifest_row = next(
        (row for row in rows if row["relative_path"] == "report_manifest.json"),
        None,
    )
    if manifest_row is None:
        raise ValueError(f"{method_id} private receipt omits report_manifest.json")
    require_real_input_file(
        report_manifest_path,
        f"{method_id} local report_manifest.json",
    )
    report_path = report_manifest_path.parent / "report.md"
    require_real_input_file(report_path, f"{method_id} local report.md")
    if report_path.stat().st_size <= 0:
        raise ValueError(f"{method_id} local report.md is missing")
    manifest, local_manifest_sha256 = load_json_object_with_sha256(
        report_manifest_path,
        f"{method_id} local report manifest",
    )
    if manifest.get("method_id") != method_id:
        raise ValueError(f"{method_id} local report_manifest.json has the wrong method")
    if manifest.get("report_sha256") != sha256_path(report_path):
        raise ValueError(f"{method_id} local report_manifest.json is not report-bound")

    if manifest_row["sha256"] != local_manifest_sha256:
        raise ValueError(f"{method_id} local report_manifest.json is not receipt-bound")
    version_id = exact_non_null_version_id(
        manifest_row.get("version_id"),
        f"{method_id} report_manifest.json",
    )

    return {
        "method_id": method_id,
        "receipt": str(receipt_path),
        "destination_prefix": str(private_receipt["destination_prefix"]),
        "report_manifest_version_id": version_id,
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

    receipts = [
        load_json_object_with_sha256(path, "private publication receipt")
        for path in paths
    ]
    method_ids = [str(receipt.get("method_id", "")) for receipt, _ in receipts]
    if method_ids != list(REQUIRED_METHOD_IDS):
        raise ValueError(f"private publication receipts must be passed in canonical seven-method order; observed={method_ids!r}")

    summaries = []
    for index, (path, (receipt, _)) in enumerate(zip(paths, receipts)):
        method_id = REQUIRED_METHOD_IDS[index]
        summaries.append(
            validate_private_report_receipt(
                path,
                receipt,
                method_id,
                manifests[method_id],
            )
        )
    return tuple(summaries)


def report_manifest_paths(
    root: Path,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
) -> dict[str, Path]:
    return source_report_manifest_paths(
        root,
        RUN_ID,
        sigprofiler_report_dir,
        sequenza_report_dir,
        deterministic_report_dir=deterministic_report_dir,
        rosalind_report_dir=rosalind_report_dir,
        blocked_crosscheck_root=blocked_crosscheck_root,
    )


def prepare_manifest_flags(paths: dict[str, Path]) -> list[str | Path]:
    return [
        token
        for method_id, argument in zip(REQUIRED_METHOD_IDS, MANIFEST_ARGUMENTS)
        for token in ("--" + argument.replace("_", "-"), paths[method_id])
    ]


def expected_source_manifest_flags(
    receipt_summaries: Iterable[dict[str, str | int]],
) -> list[str]:
    return [
        token
        for summary in receipt_summaries
        for token in (
            "--expected-source-manifest-sha256",
            f"{summary['method_id']}={summary['report_manifest_sha256']}",
        )
    ]


def require_receipt_summaries(
    receipt_summaries: Iterable[dict[str, str | int]],
) -> tuple[dict[str, str | int], ...]:
    summaries = tuple(receipt_summaries)
    method_ids = [str(summary.get("method_id", "")) for summary in summaries]
    if method_ids != list(REQUIRED_METHOD_IDS):
        raise ValueError(
            f"AI synthesis rendering requires seven receipt-bound source manifests in canonical order; observed={method_ids!r}"
        )
    for summary in summaries:
        if set(summary) != PRIVATE_REPORT_RECEIPT_SUMMARY_KEYS:
            raise ValueError(
                f"{summary.get('method_id', 'unknown')} private receipt "
                "summary envelope is not exact"
            )
        method_id = str(summary["method_id"])
        try:
            private_report_prefix(
                method_id,
                str(summary.get("destination_prefix", "")),
            )
        except ValueError as error:
            raise ValueError(
                f"{method_id} private receipt destination is malformed"
            ) from error
        try:
            exact_non_null_version_id(
                summary.get("report_manifest_version_id"),
                f"{method_id} report_manifest.json",
            )
        except ValueError as error:
            raise ValueError(
                f"{method_id} report_manifest.json VersionId is malformed"
            ) from error
        require_summary_receipt(summary.get("receipt"), method_id)
        object_count = summary.get("object_count")
        expected_object_count = len(METHOD_CONTRACTS[method_id]["files"])
        if type(object_count) is not int or object_count != expected_object_count:
            raise ValueError(
                f"{method_id} private receipt object count is malformed"
            )
        require_summary_sha256(
            summary.get("report_manifest_sha256"),
            f"{summary['method_id']} report_manifest.json",
        )
    return summaries


def manifest_flags(paths: dict[str, Path], flag: str = "--source-manifest") -> list[str | Path]:
    return [token for method_id in REQUIRED_METHOD_IDS for token in (flag, paths[method_id])]


def require_method_flags() -> list[str]:
    return [token for method_id in REQUIRED_METHOD_IDS for token in ("--require-method", method_id)]


def forbidden_flags() -> list[str]:
    return [token for value in FORBIDDEN_TOKENS for token in ("--forbidden-token", value)]


def publish_command(
    scripts: Path,
    source: Path,
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
        source,
        "--method-id",
        method_id,
        "--receipt-output",
        receipt_output,
        "--region",
        REGION,
        *forbidden_flags(),
        *forbidden_tokens_file_flags,
    ]
    if apply:
        if dry_run_receipt is None:
            raise ValueError("AI private report apply command requires a dry-run receipt")
        command.extend(["--dry-run-receipt", dry_run_receipt])
        command.append("--apply")
    elif dry_run_receipt is not None:
        raise ValueError("--dry-run-receipt is only valid with --apply")
    return command


def private_publish_blocks(
    scripts: Path,
    packet_dir: Path,
    method_id: str,
    dry_receipt: Path,
    apply_receipt: Path,
    forbidden_tokens_file: Path | None = None,
) -> tuple[str, ...]:
    return (
        block(
            publish_command(
                scripts,
                packet_dir,
                method_id,
                dry_receipt,
                forbidden_tokens_file=forbidden_tokens_file,
                apply=False,
            )
        ),
        *private_publish_checklist(
            method_id,
            packet_dir,
            dry_receipt,
            apply_receipt,
        ),
        block(
            publish_command(
                scripts,
                packet_dir,
                method_id,
                apply_receipt,
                forbidden_tokens_file=forbidden_tokens_file,
                apply=True,
                dry_run_receipt=dry_receipt,
            )
        ),
    )


def private_publish_checklist(
    method_id: str,
    packet_dir: Path,
    dry_receipt: Path,
    apply_receipt: Path,
) -> list[str]:
    return [
        f"Review `{dry_receipt}` before private AI report apply:",
        "",
        f"- [ ] `method_id` is `{method_id}` and `source_packet_dir` is "
        f"`{packet_dir}`.",
        "- [ ] `expected_files` exactly matches the method contract for this "
        "packet and no extra files are present.",
        "- [ ] `forbidden_token_count` is nonzero and "
        "`forbidden_token_sha256` matches the token set used for the dry-run.",
        "- [ ] `checks.packet_inventory_exact`, "
        "`checks.packet_manifest_no_call_boundary`, "
        "`checks.packet_report_kind_exact`, and "
        "`checks.packet_forbidden_token_scan` are all true.",
        f"- [ ] `{apply_receipt}` does not already exist and the private "
        "destination prefix is expected to have no version history.",
        "- [ ] The matching apply will enforce `checks.dry_run_receipt`, "
        "`checks.destination_initially_empty`, `checks.destination_sse_kms`, "
        "`checks.destination_full_object_sha256`, "
        "`checks.destination_non_null_versions`, and "
        "`checks.destination_exact_one_version_no_delete_history`.",
        "- [ ] Running the following `--apply` command is still the intended "
        "private publication action.",
    ]


def reviewed_publication_receipt_paths(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    receipt_paths = {
        **dict(
            zip(
                REQUIRED_METHOD_IDS,
                source_private_receipt_paths(root, receipt_stem, REQUIRED_METHOD_IDS),
            )
        ),
        **dict(
            zip(
                (*AI_REVIEW_METHOD_IDS, *COMPARATIVE_METHOD_IDS),
                ai_private_receipt_paths(root, receipt_stem),
            )
        ),
    }
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


def reviewer_input_paths(
    reviewer_inputs: Path,
    reviewer: str,
) -> tuple[Path, Path]:
    reviewer_label = reviewer.lower()
    input_dir = reviewer_inputs / f"reviewer-{reviewer_label}-input"
    return input_dir / "review_bundle.json", input_dir / f"reviewer-{reviewer_label}.prompt.md"


def reviewer_output_checklist(
    reviewer: str,
    review_bundle: Path,
    reviewer_prompt: Path,
    review_dir: Path,
) -> list[str]:
    return [
        f"Review Reviewer {reviewer} output in `{review_dir}` before validation:",
        "",
        f"- [ ] The isolated session received only `{review_bundle}` and "
        f"`{reviewer_prompt}`.",
        "- [ ] The reviewer did not receive the other reviewer's prompt, "
        "output directory, context, or validation result.",
        f"- [ ] `{review_dir}` contains only `report.md`, `claims.csv`, and "
        "`review_manifest.json` before validation.",
        "- [ ] `review_manifest.json` records the correct reviewer ID, the "
        "catalog-pinned model, a unique invocation, and the independence "
        "attestation.",
        "- [ ] `claims.csv` preserves source evidence IDs with allowed states "
        "and never proposes an HRD state beyond the authorized ceiling.",
        "- [ ] `report.md` is source-grounded and includes no raw-data paths, "
        "private identifiers, or clinical-actionability escalation.",
        "- [ ] Run the matching `validate_ai_review.py` command below before "
        "synthesis or finalization.",
    ]


def reviewed_publication_runbook_command(
    scripts: Path,
    root: Path,
    output: str | Path,
    receipt_paths: Iterable[Path],
    receipt_stem: str = "terminal",
    *,
    forbidden_tokens_file: Path | None = None,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "render_reviewed_publication_runbook.py",
        "--output",
        output,
        "--root",
        root,
        "--receipt-stem",
        receipt_stem,
        *(["--forbidden-tokens-file", forbidden_tokens_file] if forbidden_tokens_file is not None else []),
        *[token for path in receipt_paths for token in ("--private-publication-receipt", path)],
    ]


def model_catalog_receipt_path(root: Path) -> Path:
    return root / ".codex-tmp/hrd-reports/ai-review/model-catalog-receipts" / RUN_ID / MODEL_CATALOG_RECEIPT


def ai_private_receipt_paths(
    root: Path, receipt_stem: str, suffix: str = ""
) -> tuple[Path, ...]:
    receipt_root = root / ".codex-tmp/hrd-reports/ai-review" / RUN_ID / "publication-receipts"
    return tuple(receipt_root / f"{receipt_stem}.{stem}.private{suffix}.json" for _, stem in AI_PRIVATE_RECEIPT_STEMS)


def ai_private_receipt_outputs(
    root: Path, receipt_stem: str, suffix: str = ""
) -> tuple[tuple[str, Path], ...]:
    receipt_paths = ai_private_receipt_paths(root, receipt_stem, suffix)
    return tuple((method_id, receipt_paths[index]) for index, (method_id, _) in enumerate(AI_PRIVATE_RECEIPT_STEMS))


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return unique_paths(
        (
            scripts / "hrd_report_inventory.py",
            scripts / "ai_model_catalog.py",
            scripts / "forbidden_text.py",
            scripts / "prepare_ai_review_run.py",
            scripts / "build_ai_review_bundle.py",
            scripts / "stage_ai_review_inputs.py",
            scripts / "validate_ai_review.py",
            scripts / "finalize_ai_review.py",
            scripts / "generate_comparative_hrd_synthesis.py",
            scripts / "publish_private_report.py",
            scripts / "render_reviewed_publication_runbook.py",
            *reviewed_public_required_existing(root),
            scripts / "write_ai_model_catalog_receipt.py",
        )
    )


def required_absent(root: Path, receipt_stem: str) -> tuple[Path, ...]:
    return (
        model_catalog_receipt_path(root),
        root / ".codex-tmp/hrd-reports/ai-review" / RUN_ID,
        root / ".codex-tmp/hrd-reports/synthesis" / RUN_ID,
        *ai_private_receipt_paths(root, receipt_stem, ".dry"),
        *ai_private_receipt_paths(root, receipt_stem),
        *reviewed_public_required_absent(root, receipt_stem),
    )


def render(
    root: Path,
    receipt_stem: str,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    receipt_summaries: tuple[dict[str, str | int], ...] = (),
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
    forbidden_tokens_file: Path | None = None,
) -> str:
    receipt_summaries = require_receipt_summaries(receipt_summaries)
    reports = root / ".codex-tmp/hrd-reports"
    scripts = root / "scripts"
    manifests = report_manifest_paths(
        root,
        sigprofiler_report_dir,
        sequenza_report_dir,
        deterministic_report_dir=deterministic_report_dir,
        rosalind_report_dir=rosalind_report_dir,
        blocked_crosscheck_root=blocked_crosscheck_root,
    )

    run_root = reports / "ai-review" / RUN_ID
    catalog = model_catalog_receipt_path(root)
    bundle = run_root / "bundle"
    reviewer_inputs = run_root / "reviewer-inputs"
    reviewer_a = run_root / "reviewer-a"
    reviewer_b = run_root / "reviewer-b"
    synthesis = reports / "synthesis" / RUN_ID
    ai_private_packet_dirs = {
        AI_REVIEW_METHOD_IDS[0]: reviewer_a,
        AI_REVIEW_METHOD_IDS[1]: reviewer_b,
        COMPARATIVE_METHOD_IDS[0]: synthesis,
    }
    dry_private_receipt_outputs = dict(
        ai_private_receipt_outputs(root, receipt_stem, ".dry")
    )

    lines = [
        "# Diana WGS independent AI review and synthesis handoff",
        "",
        f"- Run: `{RUN_ID}`",
        f"- Subject alias: `{SUBJECT_ALIAS}`",
        f"- Reviewer A model: `{REVIEWER_A[0]}/{REVIEWER_A[1]}`",
        f"- Reviewer B model: `{REVIEWER_B[0]}/{REVIEWER_B[1]}`",
        "- Boundary: prepare one de-identified seven-method bundle, stage exact "
        "two-file reviewer inputs, validate two isolated model outputs, "
        "generate the comparative synthesis, then privately publish reviewer "
        "and synthesis reports.",
        "- Do not run until all seven source report manifests below exist, have "
        "been privately frozen, and match the passed private publication "
        "receipts exactly.",
        "",
    ]
    lines.extend(
        [
            "## 0. Private publication receipt gate",
            "",
            "The renderer bound this handoff to seven passed private publication receipts in canonical method order:",
            "",
        ]
    )
    for summary in receipt_summaries:
        method_id = str(summary["method_id"])
        lines.append(
            f"- `{method_id}`: `{manifests[method_id]}` -> "
            f"`report_manifest.json` VersionId "
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
                    "--inventory-id",
                    INVENTORY_ID,
                    *prepare_manifest_flags(manifests),
                    *expected_source_manifest_flags(receipt_summaries),
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
                    *(["--forbidden-tokens-file", forbidden_tokens_file] if forbidden_tokens_file is not None else []),
                    *forbidden_flags(),
                ]
            ),
            "## 3. Invoke reviewers in isolated sessions",
            "",
            f"- Reviewer A receives only "
            f"`{reviewer_input_paths(reviewer_inputs, 'A')[0]}` and "
            f"`{reviewer_input_paths(reviewer_inputs, 'A')[1]}`; "
            f"write only `report.md`, `claims.csv`, and `review_manifest.json` "
            f"into `{reviewer_a}`.",
            f"- Reviewer B receives only "
            f"`{reviewer_input_paths(reviewer_inputs, 'B')[0]}` and "
            f"`{reviewer_input_paths(reviewer_inputs, 'B')[1]}`; "
            f"write only `report.md`, `claims.csv`, and `review_manifest.json` "
            f"into `{reviewer_b}`.",
            "",
            *reviewer_output_checklist(
                "A",
                *reviewer_input_paths(reviewer_inputs, "A"),
                reviewer_a,
            ),
            "",
            *reviewer_output_checklist(
                "B",
                *reviewer_input_paths(reviewer_inputs, "B"),
                reviewer_b,
            ),
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
                    *(["--forbidden-tokens-file", forbidden_tokens_file] if forbidden_tokens_file is not None else []),
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
                    *(["--forbidden-tokens-file", forbidden_tokens_file] if forbidden_tokens_file is not None else []),
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
            *[
                line
                for method_id, receipt_output in ai_private_receipt_outputs(root, receipt_stem)
                for line in private_publish_blocks(
                    scripts,
                    ai_private_packet_dirs[method_id],
                    method_id,
                    dry_private_receipt_outputs[method_id],
                    receipt_output,
                    forbidden_tokens_file=forbidden_tokens_file,
                )
            ],
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
                            root,
                            Raw('"$REVIEWED_PUBLIC_RUNBOOK"'),
                            reviewed_publication_receipt_paths(root, receipt_stem),
                            receipt_stem,
                            forbidden_tokens_file=forbidden_tokens_file,
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
    parser.add_argument("--deterministic-report-dir", type=Path)
    parser.add_argument("--rosalind-report-dir", type=Path)
    parser.add_argument("--blocked-crosscheck-root", type=Path)
    parser.add_argument("--sigprofiler-report-dir", type=Path)
    parser.add_argument("--sequenza-report-dir", type=Path)
    parser.add_argument("--forbidden-tokens-file", type=Path)
    parser.add_argument(
        "--private-publication-receipt",
        action="append",
        type=Path,
        required=True,
        help=("repeat once for each source-method private publication receipt, in canonical method-inventory order"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    missing = missing_required_files(required_existing(root))
    if missing:
        raise SystemExit("Fail-closed: missing AI synthesis runbook prerequisites: " + ", ".join(str(path) for path in missing))
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")
    preexisting = preexisting_create_only_paths(required_absent(root, args.receipt_stem))
    if preexisting:
        raise SystemExit("Fail-closed: AI synthesis create-only outputs already exist: " + ", ".join(str(path) for path in preexisting))

    manifests = report_manifest_paths(
        root,
        args.sigprofiler_report_dir,
        args.sequenza_report_dir,
        deterministic_report_dir=args.deterministic_report_dir,
        rosalind_report_dir=args.rosalind_report_dir,
        blocked_crosscheck_root=args.blocked_crosscheck_root,
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
            deterministic_report_dir=args.deterministic_report_dir,
            rosalind_report_dir=args.rosalind_report_dir,
            blocked_crosscheck_root=args.blocked_crosscheck_root,
            forbidden_tokens_file=args.forbidden_tokens_file,
        ),
    )
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
