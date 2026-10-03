#!/usr/bin/env python3
"""Prepare hash-locked PUBLIC controls for a patient-lane rehearsal; never accepts patient inputs."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_intake import validate_contract  # noqa: E402
from diana_omics.scrna_io import sha256_file  # noqa: E402

SOURCES = {"pbmc1k": "pbmc1k-v3", "breast-standard": "Breast_Cancer_3p", "breast-lt": "Breast_Cancer_3p_LT"}
CASES = {"breast": ("breast-standard", "breast-lt"), "pbmc": ("pbmc1k",)}


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def prepare(destination: Path) -> dict:
    destination = destination.resolve()
    if not destination.is_relative_to((ROOT / "private").resolve()) or destination.exists():
        raise ValueError("Choose a new directory under private/; existing deliveries are never replaced")
    lock_path = ROOT / "manifests/scrna/controls/sources.lock.json"
    lock = json.loads(lock_path.read_text())
    if lock["evidence_lane"] != "public_control":
        raise ValueError("Only the committed public control source lock may be rehearsed")
    controls = {item["control"]: item for item in lock["controls"]}
    prepared = {"schema_version": 1, "source_classification": "public_control", "execution_lane": "patient_research",
                "purpose": "Public-data rehearsal of the patient intake and post-count QC path",
                "source_lock_sha256": sha256_file(lock_path), "cases": {}, "limitations": lock["limitations"]}
    # Verify the entire public source set before creating a delivery.
    for label in SOURCES:
        item = controls[label]
        metadata = ROOT / f"manifests/scrna/controls/{label}.metadata.json"
        if sha256_file(metadata) != item["metadata_sha256"]:
            raise ValueError(f"Public metadata changed: {label}")
        for entry in item["files"]:
            path = ROOT / "data/raw/scrna" / SOURCES[label] / entry["path"]
            if path.is_symlink() or path.stat().st_size != entry["size_bytes"] or sha256_file(path) != entry["sha256"]:
                raise ValueError(f"Public source checksum/size mismatch: {label}/{entry['role']}")
    destination.mkdir(parents=True, mode=0o700)
    for case, labels in CASES.items():
        delivery = destination / case / "delivery"
        delivery.mkdir(parents=True, mode=0o700)
        first = json.loads((ROOT / f"manifests/scrna/controls/{labels[0]}.intake.json").read_text())
        contract = {key: value for key, value in first.items() if key != "captures"}
        contract.update(evidence_lane="patient_research", case_id=f"shadow-public-{case}-001", captures=[])
        mappings = []
        for label in labels:
            public = json.loads((ROOT / f"manifests/scrna/controls/{label}.intake.json").read_text())
            capture = copy.deepcopy(public["captures"][0])
            capture.update(capture_id=f"shadow-{label}-001", specimen_id=f"shadow-{label}-specimen", timepoint="public_shadow_rehearsal")
            packet = json.loads((ROOT / f"manifests/scrna/controls/{label}.metadata.json").read_text())
            packet.update(capture_id=capture["capture_id"], specimen_id=capture["specimen_id"],
                          source_classification="public_control", execution_purpose="patient_lane_shadow_rehearsal",
                          public_donor_group=controls[label]["donor_group"])
            packet_path = delivery / label / "vendor-metadata.json"
            packet_path.parent.mkdir(mode=0o700)
            write_json(packet_path, packet)
            capture["metadata"].update(path=packet_path.relative_to(delivery).as_posix(), sha256=sha256_file(packet_path))
            if sorted((x["role"], x["sha256"], x["size_bytes"]) for x in capture["files"]) != sorted(
                    (x["role"], x["sha256"], x["size_bytes"]) for x in controls[label]["files"]):
                raise ValueError("Intake differs from the public source lock")
            for entry in capture["files"]:
                source = ROOT / "data/raw/scrna" / SOURCES[label] / entry["path"]
                target = delivery / label / entry["path"]
                shutil.copyfile(source, target)
                target.chmod(0o600)
                entry["path"] = target.relative_to(delivery).as_posix()
            contract["captures"].append(capture)
            mappings.append({"capture_id": capture["capture_id"], "control": label,
                             "public_donor_group": controls[label]["donor_group"], "source_page": controls[label]["source_page"]})
        validate_contract(contract)
        write_json(destination / case / "contract.json", contract)
        prepared["cases"][case] = {"case_id": contract["case_id"], "captures": mappings}
    write_json(destination / "public_rehearsal.json", prepared)
    return prepared


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(json.dumps({"source_classification": result["source_classification"], "cases": list(result["cases"])}))
