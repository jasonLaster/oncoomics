import copy
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from diana_omics.scrna_io import artifact_index, sha256_file, validate_artifact_index, validate_config, write_json
from diana_omics.scrna_release import COUNT_AUDIT_CHECKS, REQUIRED_EVIDENCE, SCOPE, assess_release, config_digest, run_state

ROOT = Path(__file__).parents[1]


def test_claimed_verified_metadata_without_source_is_rejected():
    config = json.loads((ROOT / "manifests/scrna/breast/calibration.json").read_text())
    config["datasets"][0]["capture_scope"] = "verified_single_capture"
    with pytest.raises(ValueError, match="capture_evidence"):
        validate_config(config)


@pytest.mark.parametrize("field,value", [("n_hvg", 999999), ("seed", -1), ("qc_mad_multiplier", float("nan")),
                                        ("leiden_resolution", 0), ("miqc_challenger", "false")])
def test_invalid_parameters_fail_before_cloud_compute(field, value):
    config = json.loads((ROOT / "manifests/scrna/breast/calibration.json").read_text())
    config["parameters"][field] = value
    with pytest.raises(ValueError):
        validate_config(config)


def test_artifact_index_rejects_duplicate_reserved_and_oversized_entries():
    record = {"path": "sample/all_cells_qc.csv", "sha256": "a" * 64, "size_bytes": 100}
    validate_artifact_index([record])
    for bad in ([record, record], [dict(record, path="run_manifest.json")], [dict(record, size_bytes=2**40)],
                [dict(record, sha256="bad")], [dict(record, path="../outside")], []):
        with pytest.raises(ValueError):
            validate_artifact_index(bad)


def test_monitor_distinguishes_failure_staleness_and_qc_acceptance():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    started = {"started_at": (now - timedelta(seconds=2101)).isoformat(), "timeout_seconds": 1800}
    assert run_state(None, None, None, now)["state"] == "not_found"
    assert run_state(started, None, None, now)["state"] == "stale"
    started["started_at"] = (now - timedelta(seconds=10)).isoformat()
    assert run_state(started, None, None, now)["state"] == "running"
    assert run_state(started, {"status": "failed"}, None, now)["state"] == "failed"
    complete = {"status": "complete", "artifact_index_sha256": "a" * 64, "calibration_status": "needs_review"}
    report = run_state(started, None, complete, now)
    assert report["state"] == "complete" and report["calibration_status"] == "needs_review"
    assert run_state(started, {"status": "failed"}, complete, now)["state"] == "inconsistent"


@pytest.fixture
def release_fixture(tmp_path):
    """Fabricated control packet: exercises admission mechanics, never cohort evidence."""
    root = tmp_path / "run"
    root.mkdir()
    config = json.loads((ROOT / "manifests/scrna/breast/calibration.json").read_text())
    for dataset in config["datasets"]:
        dataset.update(capture_scope="verified_single_capture", chemistry_status="verified")
        evidence = {"sample_id": dataset["sample_id"], "url": "https://example.org/test-only", "sha256": "a" * 64,
                    "locator": "fabricated unit-test evidence"}
        dataset.update(capture_evidence=evidence, chemistry_evidence=evidence)
    gates = {key: True for key in ("input_cells_match", "retention", "cluster_count", "finite_embedding", "seed_stability",
                                  "raw_counts_preserved", "doublets_called", "compartment_retention",
                                  "capture_metadata_resolved", "chemistry_metadata_resolved")}
    summaries = {d["dataset_id"]: {"gates": gates, "coarse_reference_balanced_accuracy": 0.95, "unknown_label_fraction": 0.01,
                                  "ambient_rna_status": "assessed_raw_droplets", "production_ready": True} for d in config["datasets"]}
    write_json(root / "input_manifest.json", config)
    write_json(root / "calibration_summary.json", summaries)
    source_dir = root / "source"
    source_dir.mkdir()
    source = ROOT / "src/diana_omics"
    names = ["scrna.py", "scrna_io.py", "scrna_qc.py", "scrna_miqc.py", "scrna_release.py"]
    for name in names:
        shutil.copyfile(source / name, source_dir / name)
    shutil.copyfile(ROOT / "scripts/modal/scrna_platform.py", source_dir / "modal_runner.py")
    write_json(root / "source_hashes.json", {name: sha256_file(source / name) for name in names})
    write_json(root / "python_packages.json", {})
    write_json(root / "artifact_index.json", artifact_index(root))
    digest = sha256_file(root / "artifact_index.json")
    write_json(root / "run_manifest.json", {"run_id": "test-only", "status": "complete", "evidence_lane": "public_benchmark",
                                            "artifact_index_sha256": digest})
    audit = tmp_path / "audit.json"
    write_json(audit, {"run_id": "test-only", "status": "pass", "artifact_index_sha256": digest,
                      "checks": {d["dataset_id"]: dict.fromkeys(COUNT_AUDIT_CHECKS, True) for d in config["datasets"]}})
    report = tmp_path / "fabricated_report.txt"
    report.write_text("UNIT TEST ONLY - no biological evidence\n")
    reports = {kind: {"status": "validated", "reviewer": "test-only", "source": "test-only",
                      "path": report.name, "sha256": sha256_file(report)} for kind in REQUIRED_EVIDENCE}
    reports["held_out_donors"].update(training_donors=["train"], evaluation_donors=["eval1", "eval2", "eval3"],
                                    subtypes=["TNBC", "ER+", "HER2+"], training_studies=["calibration"], evaluation_studies=["external"])
    packet = tmp_path / "packet.json"
    write_json(packet, {"scope": SCOPE, "config_sha256": config_digest(config), "artifact_index_sha256": digest, "reports": reports})
    return root, config, audit, packet


def test_completion_and_true_flags_cannot_bypass_missing_validation(release_fixture):
    root, config, audit, _ = release_fixture
    report = assess_release(root, config, audit)
    assert report["decision"] == "quarantined" and not report["production_ready"]
    assert any("Missing reviewed" in text for text in report["blockers"])


def test_admission_requires_exact_frozen_recipe_and_disjoint_donors(release_fixture):
    root, config, audit, packet = release_fixture
    assert assess_release(root, config, audit, packet)["decision"] == "admitted"
    changed = copy.deepcopy(config)
    changed["parameters"]["qc_mad_multiplier"] = 4
    assert assess_release(root, changed, audit, packet)["decision"] == "quarantined"
    data = json.loads(packet.read_text())
    data["reports"]["held_out_donors"]["evaluation_donors"] = ["train"]
    write_json(packet, data)
    assert assess_release(root, config, audit, packet)["decision"] == "quarantined"


def test_tampering_after_collection_or_with_validation_fails_closed(release_fixture):
    root, config, audit, packet = release_fixture
    (root / "calibration_summary.json").write_text("{}")
    with pytest.raises(ValueError, match="size mismatch"):
        assess_release(root, config, audit, packet)


def test_stale_count_audit_cannot_authorize_release(release_fixture):
    root, config, audit, packet = release_fixture
    data = json.loads(audit.read_text())
    data["artifact_index_sha256"] = "b" * 64
    write_json(audit, data)
    assert assess_release(root, config, audit, packet)["decision"] == "quarantined"
