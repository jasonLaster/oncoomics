import io
import json
import tarfile
from pathlib import Path

import pytest

from diana_omics.scrna_io import calibration_gates, extract_matrix, safe_id, safe_key, validate_config, verify_file


@pytest.mark.parametrize("value", ["../escape", "/absolute", "a//b", "a/../b", "a\\b", "a/./b"])
def test_input_custody_rejects_unsafe_keys(value):
    with pytest.raises(ValueError):
        safe_key(value)


def test_run_id_cannot_escape_result_prefix():
    with pytest.raises(ValueError):
        safe_id("run/../../other")


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE), ("matrix.mtx", tarfile.SYMTYPE)])
def test_archive_rejects_traversal_and_links(tmp_path, name, kind):
    archive = tmp_path / "input.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
        handle.addfile(info, io.BytesIO(b""))
    with pytest.raises(ValueError):
        extract_matrix(archive, tmp_path / "extracted")
    assert not (tmp_path / "escape").exists()


def test_corrupt_source_hash_stops_analysis(tmp_path):
    source = tmp_path / "counts.h5"
    source.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_file(source, "a" * 64)


def test_config_rejects_tissue_profile_mismatch_and_duplicate_ids():
    config = json.loads((Path(__file__).parents[1] / "manifests/scrna/calibration.json").read_text())
    validate_config(config)
    config["datasets"][0]["tissue"] = "breast tumor"
    with pytest.raises(ValueError, match="PBMC"):
        validate_config(config)
    config["datasets"][0]["tissue"] = "PBMC"
    config["datasets"][1]["dataset_id"] = config["datasets"][0]["dataset_id"]
    with pytest.raises(ValueError, match="Duplicate"):
        validate_config(config)


def test_absent_reference_evidence_cannot_pass():
    acceptance = json.loads((Path(__file__).parents[1] / "manifests/scrna/calibration.json").read_text())["acceptance"]
    metrics = {"input_cells": 2700, "retained_fraction": 0.9, "clusters": 8, "finite_embedding": True,
               "seed_stability_ari": 0.95, "raw_counts_preserved": True, "doublet_method": "scDblFinder"}
    gates = calibration_gates(metrics, 2700, acceptance, has_reference=True)
    assert gates["doublets_called"]
    assert not gates["reference_overlap"]
    assert not gates["reference_agreement"]
    metrics["doublet_method"] = "skipped"
    assert not calibration_gates(metrics, 2700, acceptance, False)["doublets_called"]
