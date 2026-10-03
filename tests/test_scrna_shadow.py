"""Rehearsal source boundaries and diagnostic interpretation; no biological qualification."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from diana_omics.scrna_io import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script("prepare_scrna_shadow")
review = load_script("review_scrna_shadow")


@pytest.fixture
def public_fixture(tmp_path, monkeypatch):
    manifests = tmp_path / "manifests/scrna/controls"
    manifests.mkdir(parents=True)
    lock = json.loads((ROOT / "manifests/scrna/controls/sources.lock.json").read_text())
    for control in lock["controls"]:
        label = control["control"]
        metadata_path = ROOT / f"manifests/scrna/controls/{label}.metadata.json"
        (manifests / f"{label}.metadata.json").write_bytes(metadata_path.read_bytes())
        contract = json.loads((ROOT / f"manifests/scrna/controls/{label}.intake.json").read_text())
        source = tmp_path / "data/raw/scrna" / prepare.SOURCES[label]
        source.mkdir(parents=True)
        for entry in control["files"]:
            path = source / entry["path"]
            path.write_bytes(f"fabricated transfer fixture: {label}/{entry['role']}".encode())
            entry.update(sha256=sha256_file(path), size_bytes=path.stat().st_size)
        contract["captures"][0]["files"] = [{k: v for k, v in entry.items() if k != "url"} for entry in control["files"]]
        (manifests / f"{label}.intake.json").write_text(json.dumps(contract))
    (manifests / "sources.lock.json").write_text(json.dumps(lock))
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    monkeypatch.setattr(review, "ROOT", tmp_path)
    # This fixture tests source classification/copy boundaries, not H5 reading.
    monkeypatch.setattr(review, "inspect_delivery", lambda *args: {"ready_for_postcount_qc": True})
    return tmp_path


def test_rehearsal_keeps_public_donor_and_source_identity(public_fixture):
    destination = public_fixture / "private/shadow"
    provenance = prepare.prepare(destination)
    assert review.verify_public_sources(destination) == provenance
    assert provenance["source_classification"] == "public_control"
    groups = {c["public_donor_group"] for c in provenance["cases"]["breast"]["captures"]}
    assert groups == {"public-breast-donor-001"}
    contract = json.loads((destination / "breast/contract.json").read_text())
    assert contract["evidence_lane"] == "patient_research"
    assert len(contract["captures"]) == 2
    assert all(c["clinical_subtype"] == "unknown" for c in contract["captures"])
    for capture in contract["captures"]:
        for item in capture["files"]:
            assert sha256_file(destination / "breast/delivery" / item["path"]) == item["sha256"]
    with pytest.raises(ValueError, match="existing"):
        prepare.prepare(destination)


def test_changed_matrix_rejected_before_creating_delivery(public_fixture):
    source = public_fixture / "data/raw/scrna/Breast_Cancer_3p/Breast_Cancer_3p_raw_feature_bc_matrix.h5"
    source.write_bytes(b"not the locked public source")
    destination = public_fixture / "private/shadow"
    with pytest.raises(ValueError, match="checksum/size"):
        prepare.prepare(destination)
    assert not destination.exists()


def test_patient_source_classification_cannot_be_exported(public_fixture):
    destination = public_fixture / "private/shadow"
    provenance = prepare.prepare(destination)
    provenance["source_classification"] = "patient_research"
    (destination / "public_rehearsal.json").write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="source-locked"):
        review.verify_public_sources(destination)


def test_unlocked_source_hash_cannot_be_exported(public_fixture):
    destination = public_fixture / "private/shadow"
    prepare.prepare(destination)
    path = destination / "breast/contract.json"
    contract = json.loads(path.read_text())
    contract["captures"][0]["files"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="committed public controls"):
        review.verify_public_sources(destination)


def test_unknown_clinical_metadata_cannot_be_replaced_by_claim(public_fixture):
    destination = public_fixture / "private/shadow"
    prepare.prepare(destination)
    path = destination / "breast/contract.json"
    contract = json.loads(path.read_text())
    contract["captures"][0]["clinical_subtype"] = "TNBC"
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="clinical metadata"):
        review.verify_public_sources(destination)


def test_extra_rehearsal_notes_cannot_enter_public_export(public_fixture):
    destination = public_fixture / "private/shadow"
    provenance = prepare.prepare(destination)
    provenance["private_note"] = "fabricated identity outside public provenance"
    (destination / "public_rehearsal.json").write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="source-locked"):
        review.verify_public_sources(destination)


def test_diagnostics_partition_overlapping_flags_without_counting_rescued_cells():
    frame = pd.DataFrame({"fails_low_genes": [True, False, False, False, False], "fails_low_umis": [True, True, False, False, False],
                          "fails_mt": [True, False, True, False, False], "pct_counts_mt": [90, 10, 50, 10, 10],
                          "doublet_class": ["not_called_core_qc_fail"] * 3 + ["doublet", "singlet"],
                          "passes_core_qc": [False, False, False, True, True], "passes_QC": [False] * 4 + [True],
                          "qc_failure_reasons": ["fails_low_genes;fails_low_umis;fails_mt", "fails_low_umis", "fails_mt", "scDblFinder_doublet", None]})
    result = review.diagnostics(frame, {"retained_cells": 1, "thresholds": {"max_pct_mt": 40.0}})
    assert sum(result["exclusive_exclusion_partition"].values()) == 5
    wider = next(row for row in result["mt_sensitivity_review_only"] if row["mt_ceiling_percent"] == 60)
    assert wider["core_eligible_barcodes"] == 3
    assert wider["newly_eligible_without_doublet_call"] == 1
    assert result["exclusive_exclusion_partition"]["retained"] == 1


def test_alias_changes_are_ignored_but_numeric_drift_is_detected(tmp_path):
    current, previous = tmp_path / "current", tmp_path / "previous"
    current.mkdir()
    previous.mkdir()
    for name in ("all_cells_qc.csv", "umap.csv", "markers.csv", "cluster_marker_scores.csv"):
        for path, alias in ((current, "shadow"), (previous, "control")):
            pd.DataFrame({"capture_id": [alias], "value": [1.25]}, index=["barcode"]).to_csv(path / name)
    method = {"method_sha256": "same"}
    result = review.comparison(current, previous, method, method)
    assert all(result[name]["shared_non_alias_columns_exact"] for name in result if name.endswith(".csv"))
    pd.DataFrame({"capture_id": ["shadow"], "value": [1.26]}, index=["barcode"]).to_csv(current / "umap.csv")
    assert review.comparison(current, previous, method, method)["umap.csv"]["shared_non_alias_columns_exact"] is False
