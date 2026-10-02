#!/usr/bin/env python3
"""Local intake, private S3 custody, on-demand Modal QC, and independent case assessment."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from diana_omics.scrna_intake import inspect_delivery, validate_contract  # noqa: E402
from diana_omics.scrna_io import safe_id, sha256_file  # noqa: E402
from diana_omics.scrna_private import BUCKET, REGION, collect_private, run_prefix, stage_delivery, storage_guard  # noqa: E402
from diana_omics.scrna_trust import assess_case  # noqa: E402


def secure_write(path: Path, value) -> None:
    """Never put a patient report in a tracked repository directory or follow an output symlink."""
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT.resolve()) and not resolved.is_relative_to((ROOT / "private").resolve()):
        raise ValueError("Patient reports inside this repository must be under private/")
    if path.is_symlink():
        raise ValueError("Refusing symlink output")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    path.chmod(0o600)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="Hash local delivery files; write a protected inventory, without guessing capture/read roles")
    inventory.add_argument("--delivery", type=Path, required=True)
    inventory.add_argument("--report", type=Path, required=True)
    for name in ("inspect", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--contract", type=Path, required=True)
        command.add_argument("--delivery", type=Path, required=True)
        command.add_argument("--report", type=Path, required=True)
        if name == "stage":
            command.add_argument("--reference-lock", type=Path)
            command.add_argument("--reference-root", type=Path)
    count = commands.add_parser("count-plan")
    count.add_argument("--contract", type=Path, required=True)
    count.add_argument("--delivery", type=Path, required=True)
    count.add_argument("--reference-lock", type=Path, required=True)
    count.add_argument("--reference-root", type=Path, required=True)
    count.add_argument("--report", type=Path, required=True)
    handoff = commands.add_parser("prepare-counted", help="Verify a count run and build a separate provisional matrix intake")
    handoff.add_argument("--count-run-dir", type=Path, required=True)
    handoff.add_argument("--source-contract", type=Path, required=True)
    handoff.add_argument("--source-delivery", type=Path, required=True)
    handoff.add_argument("--destination", type=Path, required=True)
    handoff.add_argument("--report", type=Path, required=True)
    run = commands.add_parser("run", help="Use expiring signed S3 capabilities; execute one private post-count run")
    run.add_argument("--receipt", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    for name in ("status", "collect"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        if name == "collect":
            command.add_argument("--destination", type=Path, required=True)
    assess = commands.add_parser("assess", help="Separate method qualification from patient review; default provisional hold")
    assess.add_argument("--run-dir", type=Path, required=True)
    assess.add_argument("--certificate", type=Path)
    assess.add_argument("--approved-certificate-sha256", default="")
    assess.add_argument("--review", type=Path)
    assess.add_argument("--audit", type=Path)
    assess.add_argument("--report", type=Path, required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--run-dir", type=Path, required=True)
    audit.add_argument("--contract", type=Path, required=True)
    audit.add_argument("--delivery", type=Path, required=True)
    audit.add_argument("--report", type=Path, required=True)
    commands.add_parser("storage-check")
    args = parser.parse_args()
    try:
        if args.command == "inventory":
            files = []
            for path in sorted(args.delivery.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Delivery contains a symlink; resolve source custody explicitly")
                if path.is_file():
                    files.append({"path": path.relative_to(args.delivery).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
            if not files:
                raise ValueError("Delivery is empty")
            secure_write(args.report, {"files": files, "role_assignment": "requires vendor manifest and operator review"})
            print(json.dumps({"status": "inventory_complete", "files": len(files)}))
            return 0
        if args.command in {"inspect", "stage"}:
            contract = json.loads(args.contract.read_text())
            validate_contract(contract)
            if args.command == "inspect":
                result = inspect_delivery(contract, args.delivery)
            else:
                import boto3
                reference = json.loads(args.reference_lock.read_text()) if args.reference_lock else None
                if bool(args.reference_lock) != bool(args.reference_root):
                    raise ValueError("Supply both reference lock and reference root")
                result = stage_delivery(boto3.client("s3", region_name=REGION), contract, args.delivery, reference, args.reference_root)
            secure_write(args.report, result)
            inspection = result.get("inspection", result)
            ready_count = bool((result.get("count_plan") or {}).get("ready_for_reference_locked_counting"))
            print(json.dumps({"custody_status": inspection["custody_status"], "ready_for_postcount_qc": inspection["ready_for_postcount_qc"],
                              "ready_for_reference_locked_counting": ready_count, "captures": len(inspection["captures"]), "clinical_ready": False}))
            return 0 if inspection["ready_for_postcount_qc"] or ready_count else 2
        if args.command == "count-plan":
            from diana_omics.scrna_count import count_plan
            result = count_plan(json.loads(args.contract.read_text()), args.delivery, json.loads(args.reference_lock.read_text()), args.reference_root)
            secure_write(args.report, result)
            print(json.dumps({"ready_for_reference_locked_counting": result["ready_for_reference_locked_counting"], "count_generation_qualified_for_patient": False}))
            return 0 if result["ready_for_reference_locked_counting"] else 2
        if args.command == "prepare-counted":
            from diana_omics.scrna_counted import prepare_counted
            destination = args.destination.resolve()
            if destination.is_relative_to(ROOT.resolve()) and not destination.is_relative_to((ROOT / "private").resolve()):
                raise ValueError("Count handoff must use private/ or an external protected directory")
            result = prepare_counted(args.count_run_dir, json.loads(args.source_contract.read_text()), args.source_delivery, args.destination)
            secure_write(args.report, result)
            print(json.dumps({"status": result["status"], "filtered_barcodes": result["filtered_barcodes"], "clinical_ready": False}))
            return 0
        if args.command == "run":
            safe_id(args.run_id)
            receipt = json.loads(args.receipt.read_text())
            if not receipt["inspection"]["ready_for_postcount_qc"] and not (receipt.get("count_plan") or {}).get("ready_for_reference_locked_counting"):
                raise ValueError("Post-count QC blocked by intake")
            executable = shutil.which("uv")
            if not executable:
                raise ValueError("uv is required for the pinned Modal/boto3 client runtime")
            environment = dict(os.environ, SCRNA_STAGE_RECEIPT=str(args.receipt.resolve()), SCRNA_RUN_ID=args.run_id)
            return subprocess.run([executable, "run", "--no-project", "--python", "3.11", "--with", "modal==1.5.2", "--with", "boto3==1.40.45",
                                   "python", "-m", "modal", "run", str(ROOT / "scripts/modal/scrna_patient.py"), "--run-id", args.run_id],
                                  cwd=ROOT, env=environment, check=False).returncode
        if args.command == "assess":
            result = assess_case(args.run_dir, args.certificate, args.approved_certificate_sha256, args.review, args.audit)
            secure_write(args.report, result)
            print(json.dumps({key: result[key] for key in ("decision", "method_qualified", "clinical_ready", "blockers")}, indent=2))
            return 0 if result["decision"] == "reviewed_research" else 2
        if args.command == "audit":
            from diana_omics.scrna_patient_audit import audit_patient_counts
            result = audit_patient_counts(args.run_dir, json.loads(args.contract.read_text()), args.delivery)
            secure_write(args.report, result)
            print(json.dumps({"status": result["status"], "captures": len(result["captures"]), "biological_accuracy_established": False}))
            return 0
        import boto3
        from botocore.exceptions import ClientError
        s3 = boto3.client("s3", region_name=REGION)
        if args.command == "storage-check":
            print(json.dumps(storage_guard(s3), sort_keys=True))
            return 0
        if args.command == "collect":
            # Keep patient-derived artifacts out of tracked repository directories.
            destination = args.destination.resolve()
            if destination.is_relative_to(ROOT.resolve()) and not destination.is_relative_to((ROOT / "private").resolve()):
                raise ValueError("Patient collection must use private/ or an external protected directory")
            print(json.dumps(collect_private(s3, args.run_id, args.destination)))
            return 0
        markers = {}
        for name in ("_STARTED.json", "run_manifest.json", "_FAILED.json"):
            try:
                markers[name] = json.loads(s3.get_object(Bucket=BUCKET, Key=run_prefix(args.run_id) + name)["Body"].read())
            except ClientError as error:
                if error.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
                    raise
        if any(value.get("run_id") != args.run_id for value in markers.values()) or {"run_manifest.json", "_FAILED.json"} <= set(markers):
            state = "inconsistent"
        elif "_FAILED.json" in markers:
            state = "failed"
        elif "run_manifest.json" in markers:
            state = ("complete_count_provisional" if markers["run_manifest.json"].get("scientific_status") == "count_generation_provisional" else "complete_qc_provisional") if "_STARTED.json" in markers else "inconsistent"
        elif "_STARTED.json" in markers:
            started = datetime.fromisoformat(markers["_STARTED.json"]["started_at"])
            state = "stale" if (datetime.now(timezone.utc) - started).total_seconds() > markers["_STARTED.json"]["timeout_seconds"] + 300 else "running"
        else:
            state = "not_found"
        print(json.dumps({"run_id": args.run_id, "state": state, "retry_policy": "Investigate failures/stale runs, then use a new run ID"}))
        return 2 if state in {"failed", "stale", "inconsistent"} else 0
    except Exception as error:
        # Detailed paths/identifiers can occur in parser/library errors. Keep them in protected reports only.
        if getattr(args, "report", None):
            # An unsafe report destination must not reveal identifiers through a traceback.
            with suppress(Exception):
                secure_write(args.report, {"status": "blocked", "error_category": type(error).__name__, "detail": str(error)})
        print(json.dumps({"status": "blocked", "error_category": type(error).__name__, "action": "Inspect the protected report or private failure receipt"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
