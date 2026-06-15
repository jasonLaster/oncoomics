from __future__ import annotations

from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json
from .plan_known_answer_benchmarks import PLAN_MANIFEST_PATH

SUMMARY_CSV_PATH = "results/clinicalization/known_answer_asset_integrity_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_asset_integrity_summary.json"


def _read_manifest(relative_path: str) -> list[dict[str, str]]:
    path = path_from_root(relative_path)
    if not path.exists():
        return []
    return parse_csv(read_text(path))


def plan_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(PLAN_MANIFEST_PATH)))


def _builds(rows: list[dict[str, str]]) -> set[str]:
    return {row.get("reference_build", "") for row in rows if row.get("reference_build", "")}


def _all_planned(rows: list[dict[str, str]], status_column: str) -> bool:
    return bool(rows) and all(row.get(status_column) == "planned_not_downloaded" for row in rows)


def _checksum_status(input_rows: list[dict[str, str]], truth_rows: list[dict[str, str]]) -> str:
    if _all_planned(input_rows, "source_status") and _all_planned(truth_rows, "asset_status"):
        return "pending_remote_checksum"
    return "requires_checksum_before_execution"


def integrity_rows(plans: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    for plan in plans:
        input_rows = _read_manifest(plan["input_manifest_path"])
        truth_rows = _read_manifest(plan["truth_asset_manifest"])
        input_builds = _builds(input_rows)
        truth_builds = _builds(truth_rows)
        all_builds = input_builds | truth_builds
        reference_status = "passed" if len(all_builds) == 1 else "failed"
        if reference_status != "passed":
            errors.append(
                f"{plan['benchmark_id']} has incompatible reference builds: "
                f"inputs={sorted(input_builds)} truth={sorted(truth_builds)}."
            )
        checksum_status = _checksum_status(input_rows, truth_rows)
        rows.append(
            {
                "benchmark_id": plan["benchmark_id"],
                "fixture_id": plan["fixture_id"],
                "dataset_id": plan["dataset_id"],
                "input_reference_builds": ";".join(sorted(input_builds)),
                "truth_reference_builds": ";".join(sorted(truth_builds)),
                "reference_compatibility_status": reference_status,
                "checksum_status": checksum_status,
                "benchmark_execution_ready": "no",
                "clinical_use_allowed": "no",
                "next_action": "Record source-published checksums or verified local checksums before approved benchmark execution.",
            }
        )
    return rows, errors


def main() -> None:
    plans = plan_rows()
    rows, errors = integrity_rows(plans)
    summary = {
        "status": "passed" if not errors else "failed",
        "benchmark_count": len(plans),
        "reference_compatible_count": sum(1 for row in rows if row["reference_compatibility_status"] == "passed"),
        "checksum_pending_count": sum(1 for row in rows if row["checksum_status"] == "pending_remote_checksum"),
        "benchmark_execution_ready": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Record source-published checksums or verified local checksums before any approved benchmark execution.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root(Path(SUMMARY_CSV_PATH).parent))
    write_csv(path_from_root(SUMMARY_CSV_PATH), rows)
    write_json(path_from_root(SUMMARY_JSON_PATH), {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": rows})
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Known-answer asset integrity verification passed.")


if __name__ == "__main__":
    main()
