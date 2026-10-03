"""Readiness failures and whole-file FASTQ checks, not biological counter validation."""
import copy
import gzip
import json
import runpy
from pathlib import Path

import pytest

from diana_omics.scrna_count import count_plan
from diana_omics.scrna_counted import prepare_counted
from diana_omics.scrna_intake import inspect_delivery, inspect_fastq
from diana_omics.scrna_io import sha256_file
from diana_omics.scrna_private import digest_json


@pytest.fixture
def count_fixture(tmp_path):
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/prepare_scrna_count_smoke.py"))
    root = tmp_path / "synthetic"
    namespace["prepare"](root)
    return root, json.loads((root / "contract.json").read_text()), json.loads((root / "reference_lock.json").read_text())


def test_count_plan_separates_synthetic_mechanics_from_patient_qualification(count_fixture):
    root, contract, reference = count_fixture
    plan = count_plan(contract, root, reference, root)
    assert plan["ready_for_reference_locked_counting"] and plan["count_generation_qualified_for_patient"] is False
    contract["evidence_lane"] = "patient_research"
    blocked = count_plan(contract, root, reference, root)
    assert not blocked["ready_for_reference_locked_counting"]
    assert any("Synthetic references" in reason for reason in blocked["blockers"])


@pytest.mark.parametrize("change", ["digest", "review", "assets", "version"])
def test_count_plan_rejects_reference_drift_or_missing_review(count_fixture, change):
    root, contract, reference = count_fixture
    reference = copy.deepcopy(reference)
    if change == "digest":
        contract["captures"][0]["reference_sha256"] = "0" * 64
        contract["captures"][0]["metadata"] = {"status": "unresolved"}
    elif change == "review":
        reference["review_status"] = "unperformed"
    elif change == "assets":
        reference["files"].pop("whitelist")
    else:
        reference["star_version"] = "unknown"
    assert not count_plan(contract, root, reference, root)["ready_for_reference_locked_counting"]


def test_count_plan_checks_reference_bytes_not_claimed_filename(count_fixture):
    root, contract, reference = count_fixture
    (root / "genome.fa").write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        count_plan(contract, root, reference, root)


def test_full_fastq_check_catches_error_after_sample_window(count_fixture):
    root, _, _ = count_fixture
    path = root / "R2.fastq.gz"
    with gzip.open(path, "rt") as source:
        lines = source.readlines()
    lines[10001 * 4] = "@wrong-mate\n"
    with gzip.open(path, "wt") as target:
        target.writelines(lines)
    paths = {role: root / (role + ".fastq.gz") for role in ("R1", "R2")}
    assert inspect_fastq(paths, "3prime_v3")["sampled_records"] == 10000
    with pytest.raises(ValueError, match="IDs do not align"):
        inspect_fastq(paths, "3prime_v3", limit=None)


@pytest.mark.parametrize("gap", [None, "wrong_intake", "corrupt", "missing_raw"])
def test_counted_handoff_checks_lineage_and_retains_unqualified_origin(count_fixture, tmp_path, gap):
    from scipy.io import mmwrite
    from scipy.sparse import coo_matrix

    root, contract, reference = count_fixture
    expected = json.loads((root / "expected_counts.json").read_text())
    bars = list(dict.fromkeys(row["barcode"] for row in expected["counts"]))
    run = tmp_path / "count_run"
    for state, selected in (("raw", bars), ("filtered", bars[:100])):
        directory = run / state
        directory.mkdir(parents=True)
        positions = {b: i for i, b in enumerate(selected)}
        rows = [row for row in expected["counts"] if row["barcode"] in positions]
        mmwrite(directory / "matrix.mtx", coo_matrix(([r["umis"] for r in rows], ([int(r["gene_id"].split("_")[-1]) for r in rows], [positions[r["barcode"]] for r in rows])), shape=(80, len(selected))))
        (directory / "barcodes.tsv").write_text("\n".join(selected) + "\n")
        (directory / "features.tsv").write_text("\n".join(f"TOY_ID_{i}\t{'MT-CO1' if i == 0 else 'GENE_'+str(i)}\tGene Expression" for i in range(80)) + "\n")
    (run / "reference_lock.json").write_text(json.dumps(reference))
    (run / "count_receipt.json").write_text(json.dumps({"backend": "STARsolo", "version": "2.7.11b", "cell_calling_qualified_for_patient": False, "reference_lock_sha256": digest_json(reference)}))
    if gap == "missing_raw":
        (run / "raw/matrix.mtx").unlink()
    index = [{"path": p.relative_to(run).as_posix(), "size_bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in sorted(run.rglob("*")) if p.is_file()]
    (run / "artifact_index.json").write_text(json.dumps(index))
    (run / "run_manifest.json").write_text(json.dumps({"run_id": "test-count-001", "status": "complete", "scientific_status": "count_generation_provisional",
       "intake_id": "0" * 64 if gap == "wrong_intake" else digest_json(contract), "evidence_lane": "public_control", "artifact_index_sha256": sha256_file(run / "artifact_index.json")}))
    if gap == "corrupt":
        (run / "filtered/matrix.mtx").write_text("corrupt")
    destination = tmp_path / "handoff"
    if gap:
        with pytest.raises(ValueError):
            prepare_counted(run, contract, root, destination)
        assert not destination.exists()
    else:
        result = prepare_counted(run, contract, root, destination)
        derived = json.loads((destination / "contract.json").read_text())
        assert result["filtered_barcodes"] == 100
        assert derived["captures"][0]["count_origin"]["qualified_for_patient"] is False
        assert inspect_delivery(derived, destination)["ready_for_postcount_qc"]
