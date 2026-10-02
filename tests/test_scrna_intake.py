"""Custody/compatibility tests use fabricated deliveries; they are not biological validation."""
import copy
import gzip
import json

import pytest

from diana_omics.scrna_intake import align_raw, inspect_delivery, inspect_fastq, local_file, read_matrix, validate_contract
from diana_omics.scrna_io import sha256_file

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
h5py = pytest.importorskip("h5py")
pytest.importorskip("anndata")
mmwrite = pytest.importorskip("scipy.io").mmwrite
csc_matrix = pytest.importorskip("scipy.sparse").csc_matrix


def barcode(index):
    bases = []
    for _ in range(16):
        bases.append("ACGT"[index % 4])
        index //= 4
    return "".join(bases) + "-1"


def write_h5(path, counts, barcodes, ids=None, symbols=None):
    matrix = csc_matrix(np.asarray(counts).T)
    ids = ids or ["ENSG1", "ENSG2", "ENSG3", "ENSG4"]
    symbols = symbols or ["MT-CO1", "CD3D", "LYZ", "EPCAM"]
    with h5py.File(path, "w") as handle:
        group = handle.create_group("matrix")
        for key, value in {"data": matrix.data, "indices": matrix.indices, "indptr": matrix.indptr, "shape": matrix.shape}.items():
            group.create_dataset(key, data=value)
        group.create_dataset("barcodes", data=np.asarray(barcodes, dtype="S"))
        features = group.create_group("features")
        for key, value in {"id": ids, "name": symbols, "feature_type": ["Gene Expression"] * len(ids), "genome": ["GRCh38"] * len(ids)}.items():
            features.create_dataset(key, data=np.asarray(value, dtype="S"))


@pytest.fixture
def delivery(tmp_path):
    filtered = np.tile([1, 10, 5, 0], (100, 1))
    raw = np.concatenate([filtered, np.tile([1, 0, 1, 0], (130, 1))])
    write_h5(tmp_path / "filtered.h5", filtered, [barcode(i) for i in range(100)])
    write_h5(tmp_path / "raw.h5", raw, [barcode(i) for i in range(230)])
    files = [{"role": role + "_h5", "path": role + ".h5", "sha256": sha256_file(tmp_path / (role + ".h5")),
              "size_bytes": (tmp_path / (role + ".h5")).stat().st_size} for role in ("filtered", "raw")]
    contract = {"schema_version": 1, "evidence_lane": "patient_research", "case_id": "test-case-001", "species": "Homo sapiens",
                "tissue": "breast tumor", "material": "whole_cell", "captures": [
                    {"capture_id": "test-cap-001", "specimen_id": "test-specimen-001", "chemistry": "3prime_v3", "assay": "10x_3prime_gex",
                     "reference": "GRCh38-test", "reference_sha256": "unknown", "format": "10x_h5", "expected_cells": 100, "pooled_donors": False,
                     "clinical_subtype": "TNBC", "treatment_status": "unknown", "timepoint": "unknown",
                     "metadata": {"status": "reviewed", "path": "vendor.json", "sha256": "0" * 64}, "files": files}]}
    capture = contract["captures"][0]
    packet = {key: capture[key] for key in ("capture_id", "specimen_id", "chemistry", "assay", "reference", "reference_sha256", "pooled_donors")}
    packet.update({key: contract[key] for key in ("species", "tissue", "material")})
    packet.update(complete_capture=True, reviewer="test_operator", source="fabricated_unit_test", source_sha256="0" * 64)
    (tmp_path / "vendor.json").write_text(json.dumps(packet))
    capture["metadata"]["sha256"] = sha256_file(tmp_path / "vendor.json")
    return tmp_path, contract, filtered, raw


def test_h5_custody_and_raw_lineage(delivery):
    root, contract, _, _ = delivery
    report = inspect_delivery(contract, root)
    assert report["custody_status"] == "custody_pass"
    assert report["ready_for_postcount_qc"]
    assert report["captures"][0]["details"]["raw_lineage"]["low_count_noncell_droplets"] == 130
    assert report["method_qualified"] is False


@pytest.mark.parametrize("field,value", [("material", "nuclei"), ("material", "unknown")])
def test_incompatible_material_can_be_inventoried_but_cannot_run(delivery, field, value):
    root, contract, _, _ = delivery
    contract[field] = value
    contract["captures"][0]["metadata"] = {"status": "unresolved"}
    assert not inspect_delivery(contract, root)["ready_for_postcount_qc"]


@pytest.mark.parametrize("field,value", [("pooled_donors", True), ("chemistry", "unknown"), ("reference", "unknown"), ("assay", "10x_5prime_gex")])
def test_unresolved_capture_metadata_cannot_run(delivery, field, value):
    root, contract, _, _ = delivery
    contract["captures"][0][field] = value
    contract["captures"][0]["metadata"] = {"status": "unresolved"}
    assert not inspect_delivery(contract, root)["ready_for_postcount_qc"]


def test_filtered_only_input_has_explicit_ambient_gap(delivery):
    root, contract, _, _ = delivery
    contract["captures"][0]["files"].pop()
    report = inspect_delivery(contract, root)
    assert report["ready_for_postcount_qc"]
    assert report["captures"][0]["details"]["ambient_status"] == "not_assessable_without_raw_droplets"


def test_changed_source_stops_intake(delivery):
    root, contract, _, _ = delivery
    (root / "filtered.h5").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        inspect_delivery(contract, root)


def test_capture_split_and_unknown_patient_fields_rejected(delivery):
    _, contract, _, _ = delivery
    extra = copy.deepcopy(contract)
    extra["patient_name"] = "never-copy-to-worker-arguments"
    with pytest.raises(ValueError, match="Unknown intake"):
        validate_contract(extra)
    contract["captures"].append(copy.deepcopy(contract["captures"][0]))
    with pytest.raises(ValueError, match="Duplicate capture"):
        validate_contract(contract)


def test_source_symlink_cannot_escape_delivery(delivery, tmp_path_factory):
    root, _, _, _ = delivery
    outside = tmp_path_factory.mktemp("outside") / "file"
    outside.write_text("private")
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        local_file(root, "link")


@pytest.mark.parametrize("bad", [0.5, -1, np.nan, np.inf])
def test_normalized_negative_nonfinite_matrix_rejected(delivery, bad):
    root, contract, counts, _ = delivery
    counts = counts.astype(float)
    counts[0, 0] = bad
    write_h5(root / "bad.h5", counts, [barcode(i) for i in range(100)])
    with pytest.raises(ValueError, match="integer UMI"):
        read_matrix(contract["captures"][0], {"filtered_h5": root / "bad.h5"})


def test_multiple_gem_groups_and_duplicate_feature_ids_rejected(delivery):
    root, contract, counts, _ = delivery
    bars = [barcode(i) for i in range(100)]
    bars[0] = bars[0].replace("-1", "-2")
    write_h5(root / "bad.h5", counts, bars)
    with pytest.raises(ValueError, match="Multiple GEM"):
        read_matrix(contract["captures"][0], {"filtered_h5": root / "bad.h5"})


def test_duplicate_symbols_preserve_gene_ids_and_survive_checkpoint(delivery):
    import anndata as ad

    root, contract, counts, _ = delivery
    write_h5(root / "duplicate-symbols.h5", counts, [barcode(i) for i in range(100)], symbols=["MT-CO1", "CD3D", "LYZ", "LYZ"])
    data = read_matrix(contract["captures"][0], {"filtered_h5": root / "duplicate-symbols.h5"})
    data.write_h5ad(root / "roundtrip.h5ad")
    recovered = ad.read_h5ad(root / "roundtrip.h5ad")
    assert recovered.var_names.is_unique
    assert list(recovered.var.gene_ids) == ["ENSG1", "ENSG2", "ENSG3", "ENSG4"]
    assert list(recovered.var.gene_symbols) == ["MT-CO1", "CD3D", "LYZ", "LYZ"]
    write_h5(root / "bad.h5", counts, [barcode(i) for i in range(100)], ids=["ENSG1"] * 4)
    with pytest.raises(ValueError, match="identifiers"):
        read_matrix(contract["captures"][0], {"filtered_h5": root / "bad.h5"})


def test_raw_feature_reordering_requires_exact_counts_and_symbols(delivery):
    root, contract, _, raw_counts = delivery
    capture = contract["captures"][0]
    filtered = read_matrix(capture, {"filtered_h5": root / "filtered.h5"})
    raw = read_matrix(capture, {"raw_h5": root / "raw.h5"}, raw=True)
    assert align_raw(filtered, raw[:, [2, 0, 3, 1]])["feature_reordered"]
    raw.X[0, 0] += 1
    with pytest.raises(ValueError, match="differs"):
        align_raw(filtered, raw)
    write_h5(root / "raw-no-empty.h5", raw_counts[:100], list(filtered.obs_names))
    no_empty = read_matrix(capture, {"raw_h5": root / "raw-no-empty.h5"}, raw=True)
    with pytest.raises(ValueError, match="Fewer than 100"):
        align_raw(filtered, no_empty)


def test_explicit_gzipped_mex_matches_h5(delivery):
    root, contract, counts, _ = delivery
    mex = dict(contract["captures"][0], format="10x_mtx")
    with gzip.open(root / "matrix.mtx.gz", "wb") as handle:
        mmwrite(handle, csc_matrix(counts.T))
    with gzip.open(root / "barcodes.tsv.gz", "wt") as handle:
        handle.write("\n".join(barcode(i) for i in range(100)) + "\n")
    with gzip.open(root / "features.tsv.gz", "wt") as handle:
        handle.write("\n".join(f"ENSG{i}\t{symbol}\tGene Expression" for i, symbol in enumerate(["MT-CO1", "CD3D", "LYZ", "EPCAM"], 1)) + "\n")
    matrix = read_matrix(mex, {"filtered_matrix": root / "matrix.mtx.gz", "filtered_features": root / "features.tsv.gz", "filtered_barcodes": root / "barcodes.tsv.gz"})
    h5 = read_matrix(contract["captures"][0], {"filtered_h5": root / "filtered.h5"})
    assert (matrix.X != h5.X).nnz == 0
    assert list(matrix.var.gene_ids) == list(h5.var.gene_ids)


def fastqs(root, mismatch=False, short=False):
    paths = {}
    for role, length in [("R1", 20 if short else 28), ("R2", 90)]:
        path = root / (role + ".fastq.gz")
        with gzip.open(path, "wt") as handle:
            for index in range(10):
                identity = index + 1 if mismatch and role == "R2" else index
                handle.write(f"@read-{identity} {1 if role == 'R1' else 2}:N:0:ACGT\n{'A' * length}\n+\n{'I' * length}\n")
        paths[role] = path
    return paths


def test_fastq_layout_and_mate_ids(tmp_path):
    report = inspect_fastq(fastqs(tmp_path), "3prime_v3")
    assert report["sampled_records"] == 10
    assert "full record validation still required" in report["validation_scope"]
    with pytest.raises(ValueError, match="IDs do not align"):
        inspect_fastq(fastqs(tmp_path, mismatch=True), "3prime_v3")
    with pytest.raises(ValueError, match="R1 too short"):
        inspect_fastq(fastqs(tmp_path, short=True), "3prime_v3")


def test_fastq_intake_never_claims_count_generation_ready(delivery):
    root, contract, _, _ = delivery
    capture = contract["captures"][0]
    capture["format"] = "fastq"
    capture["files"] = [{"role": role, "path": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path), "pair_id": "lane-001"} for role, path in fastqs(root).items()]
    report = inspect_delivery(contract, root)
    assert report["custody_status"] == "custody_pass"
    assert not report["ready_for_postcount_qc"]
    assert "count generation" in report["captures"][0]["qc_blockers"][-1]
