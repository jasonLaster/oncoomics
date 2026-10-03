"""Verified count-run handoff to a separate, explicitly provisional post-count intake."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from .scrna_intake import local_file, validate_contract
from .scrna_io import sha256_file, validate_artifact_index
from .scrna_private import digest_json


def prepare_counted(run: Path, original: dict, original_delivery: Path, destination: Path) -> dict:
    validate_contract(original)
    if len(original["captures"]) != 1 or original["captures"][0]["format"] != "fastq":
        raise ValueError("A counted handoff requires one original FASTQ capture")
    manifest = json.loads((run / "run_manifest.json").read_text())
    index = json.loads((run / "artifact_index.json").read_text())
    validate_artifact_index(index)
    if manifest.get("status") != "complete" or manifest.get("scientific_status") != "count_generation_provisional" or manifest.get("intake_id") != digest_json(original) or manifest.get("evidence_lane") != original["evidence_lane"] or manifest.get("artifact_index_sha256") != sha256_file(run / "artifact_index.json"):
        raise ValueError("Count run is incomplete/stale or belongs to another intake")
    names = set()
    for item in index:
        path = local_file(run, item["path"])
        if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError("Count artifact integrity failed")
        names.add(item["path"])
    needed = {"count_receipt.json", "reference_lock.json"} | {f"{state}/{name}" for state in ("filtered", "raw") for name in ("matrix.mtx", "features.tsv", "barcodes.tsv")}
    if not needed <= names:
        raise ValueError("Count run lacks canonical raw/filtered matrices or reference controls")
    capture = original["captures"][0]
    receipt = json.loads((run / "count_receipt.json").read_text())
    if receipt.get("backend") != "STARsolo" or receipt.get("version") != "2.7.11b" or receipt.get("cell_calling_qualified_for_patient") is not False or receipt.get("reference_lock_sha256") != capture["reference_sha256"] or digest_json(json.loads((run / "reference_lock.json").read_text())) != capture["reference_sha256"]:
        raise ValueError("Count/reference receipt mismatch or unsupported qualification claim")
    packet_path = local_file(original_delivery, capture["metadata"]["path"])
    if capture["metadata"]["status"] != "reviewed" or sha256_file(packet_path) != capture["metadata"]["sha256"]:
        raise ValueError("Original reviewed metadata packet missing/changed")
    if destination.exists():
        raise ValueError("Count handoff destination must be new; retain failed or prior handoffs")
    destination.mkdir(parents=True, mode=0o700)
    contract = copy.deepcopy(original)
    derived = contract["captures"][0]
    derived["format"] = "10x_mtx"
    derived["files"] = []
    for state in ("filtered", "raw"):
        (destination / state).mkdir(mode=0o700)
        for role, filename in (("matrix", "matrix.mtx"), ("features", "features.tsv"), ("barcodes", "barcodes.tsv")):
            path = destination / state / filename
            shutil.copyfile(run / state / filename, path)
            path.chmod(0o600)
            derived["files"].append({"role": state + "_" + role, "path": path.relative_to(destination).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    derived["expected_cells"] = len((destination / "filtered/barcodes.tsv").read_text().splitlines())
    derived["count_origin"] = {"backend": "STARsolo", "version": "2.7.11b", "run_id": manifest["run_id"], "artifact_index_sha256": manifest["artifact_index_sha256"], "count_receipt_sha256": sha256_file(run / "count_receipt.json"), "qualified_for_patient": False}
    packet = json.loads(packet_path.read_text())
    packet["count_provenance"] = {**derived["count_origin"], "source_intake_id": manifest["intake_id"], "count_manifest_sha256": sha256_file(run / "run_manifest.json")}
    metadata = destination / "metadata.json"
    metadata.write_text(json.dumps(packet, indent=2) + "\n")
    metadata.chmod(0o600)
    derived["metadata"] = {"status": "reviewed", "path": "metadata.json", "sha256": sha256_file(metadata)}
    validate_contract(contract)
    target = destination / "contract.json"
    target.write_text(json.dumps(contract, indent=2) + "\n")
    target.chmod(0o600)
    return {"status": "counted_handoff_provisional", "filtered_barcodes": derived["expected_cells"], "count_origin": derived["count_origin"], "clinical_ready": False}
