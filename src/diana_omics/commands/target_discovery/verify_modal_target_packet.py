from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...target_discovery import TARGET_DISCOVERY_RESULTS
from ...utils import read_json, write_json

DEFAULT_INPUT = "results/target_discovery/modal_target_packet.json"
DEFAULT_OUTPUT = f"{TARGET_DISCOVERY_RESULTS}/modal_target_packet_validation.json"


def main() -> None:
    input_path = Path(os.environ.get("MODAL_TARGET_PACKET", DEFAULT_INPUT))
    packet_path = input_path if input_path.is_absolute() else path_from_root(str(input_path))
    errors = validate_modal_target_packet(read_json(packet_path))
    status = "passed" if not errors else "failed"
    summary = {
        "status": status,
        "packet": str(input_path),
        "errors": errors,
        "boundary": (
            "Modal target packets can contribute derived engineering evidence only; "
            "they must not convert DNA-only callability into expression, protein, or therapy claims."
        ),
    }
    write_json(path_from_root(DEFAULT_OUTPUT), summary)
    if errors:
        raise SystemExit("Modal target packet is not ready:\n- " + "\n- ".join(errors))
    print(f"Modal target packet validation {status}: {input_path}")


def validate_modal_target_packet(packet: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if packet.get("schema") != "diana_modal_target_packet.v1":
        errors.append("schema must be diana_modal_target_packet.v1")
    if packet.get("status") != "partial_evidence":
        errors.append("status must be partial_evidence")

    execution = _mapping(packet.get("execution"))
    if execution.get("runtime") != "modal":
        errors.append("execution.runtime must be modal")
    if execution.get("s3Mount") != "modal.CloudBucketMount":
        errors.append("execution.s3Mount must be modal.CloudBucketMount")
    raw_data_mounted = execution.get("rawDataMounted")
    if raw_data_mounted not in {True, False}:
        errors.append("execution.rawDataMounted must be a boolean")
    if raw_data_mounted and os.environ.get("MODAL_TARGET_ALLOW_RAW") != "1":
        errors.append("MODAL_TARGET_ALLOW_RAW=1 is required to accept a raw mounted-BAM packet")

    summary = _mapping(packet.get("boardSummary"))
    if summary.get("candidateRows") != 37:
        errors.append("boardSummary.candidateRows must be 37")
    if summary.get("partialEvidenceRows") != 37:
        errors.append("boardSummary.partialEvidenceRows must be 37")
    if summary.get("readyRows") != 0:
        errors.append("boardSummary.readyRows must be 0")
    if "callableRows" in summary and summary.get("callableRows") != 37:
        errors.append("boardSummary.callableRows must be 37 when present")
    if "rnaEvidenceRows" in summary and summary.get("rnaEvidenceRows") != 37:
        errors.append("boardSummary.rnaEvidenceRows must be 37 when present")
    if summary.get("trop2Status") != "partial_evidence":
        errors.append("TROP-2 must remain partial_evidence")
    expected_trop2_rna = "partial_evidence" if summary.get("rnaEvidenceRows") == 37 else "no_call"
    if summary.get("trop2RnaStatus") != expected_trop2_rna:
        errors.append(f"TROP-2 RNA must remain {expected_trop2_rna}")
    if summary.get("trop2ProteinStatus") != "no_call":
        errors.append("TROP-2 protein must remain no_call")

    if not _records_have_sha256(packet.get("inputEvidence")):
        errors.append("inputEvidence must list SHA-256 records")
    if not _records_have_sha256(packet.get("outputs")):
        errors.append("outputs must list SHA-256 records")

    boundary = str(packet.get("boundary", ""))
    for phrase in ("raw BAM", "RNA expression", "surface protein", "drug sensitivity"):
        if phrase not in boundary:
            errors.append(f"boundary must mention {phrase}")

    return errors


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _records_have_sha256(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            return False
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            return False
        if not isinstance(item.get("path"), str) or not item["path"]:
            return False
    return True
