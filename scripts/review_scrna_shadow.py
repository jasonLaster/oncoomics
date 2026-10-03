#!/usr/bin/env python3
"""Export a small public-control QC rehearsal report after source and artifact verification."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_intake import inspect_delivery  # noqa: E402
from diana_omics.scrna_io import safe_id, sha256_file  # noqa: E402
from diana_omics.scrna_private import digest_json  # noqa: E402
from diana_omics.scrna_trust import assess_case, verify_patient_run  # noqa: E402

BASELINES = {
    "pbmc1k": ("intake-pbmc1k-final-20261002T201500Z", "control-pbmc1k"),
    "breast-standard": ("intake-breast-standard-final-20261002T201500Z", "control-breast-standard"),
    "breast-lt": ("intake-breast-lt-v3-20261002T193000Z", "control-breast-lt"),
}
ALIAS_COLUMNS = {"capture_id", "donor_id", "sample_id", "timepoint", "doublet_partition"}
AMBIENT_DEFAULTS = {"package": "SoupX", "version": "1.6.2", "contamination_range": [0.01, 0.8],
                    "source": "https://cran.r-project.org/src/contrib/SoupX_1.6.2.tar.gz",
                    "source_sha256": "9b6226cd7c0691498a874d5c029f8ff81fd2060295c298985397521c1f7ee3a5",
                    "source_file": "SoupX/R/autoEstCont.R", "wrapper_overrides_range": False}


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def verify_public_sources(rehearsal: Path) -> dict:
    """Only exact committed public matrices may produce this shareable report."""
    provenance = read(rehearsal / "public_rehearsal.json")
    lock_path = ROOT / "manifests/scrna/controls/sources.lock.json"
    lock = read(lock_path)
    if set(provenance) != {"schema_version", "source_classification", "execution_lane", "purpose", "source_lock_sha256", "cases", "limitations"} or provenance.get("source_classification") != "public_control" or provenance.get("execution_lane") != "patient_research" or provenance.get("source_lock_sha256") != sha256_file(lock_path):
        raise ValueError("Not a source-locked public rehearsal")
    if provenance["schema_version"] != 1 or provenance["purpose"] != "Public-data rehearsal of the patient intake and post-count QC path" or provenance["limitations"] != lock["limitations"]:
        raise ValueError("Unexpected public rehearsal metadata")
    controls = {item["control"]: item for item in lock["controls"]}
    expected_cases = {"breast": {"breast-standard", "breast-lt"}, "pbmc": {"pbmc1k"}}
    if set(provenance["cases"]) != set(expected_cases):
        raise ValueError("Unexpected rehearsal cases")
    for case, mappings in provenance["cases"].items():
        if set(mappings) != {"case_id", "captures"} or mappings["case_id"] != f"shadow-public-{case}-001":
            raise ValueError("Unexpected rehearsal case identity")
        if {m["control"] for m in mappings["captures"]} != expected_cases[case] or len(mappings["captures"]) != len(expected_cases[case]):
            raise ValueError("Unexpected public capture mapping")
        contract = read(rehearsal / case / "contract.json")
        if contract["case_id"] != f"shadow-public-{case}-001" or contract["evidence_lane"] != "patient_research":
            raise ValueError("Patient data may not be exported through the public rehearsal")
        if {c["capture_id"] for c in contract["captures"]} != {m["capture_id"] for m in mappings["captures"]}:
            raise ValueError("Capture set differs from public rehearsal")
        for mapping in mappings["captures"]:
            label = mapping["control"]
            source = controls[label]
            capture = next(c for c in contract["captures"] if c["capture_id"] == mapping["capture_id"])
            if set(mapping) != {"capture_id", "control", "public_donor_group", "source_page"} or mapping["source_page"] != source["source_page"]:
                raise ValueError("Unexpected public source metadata")
            expected_clinical = "not_applicable" if label == "pbmc1k" else "unknown"
            if capture["capture_id"] != f"shadow-{label}-001" or any(capture[field] != expected_clinical for field in ("clinical_subtype", "treatment_status")):
                raise ValueError("Unexpected identifying/clinical metadata in public rehearsal")
            if sorted((f["role"], f["sha256"], f["size_bytes"]) for f in capture["files"]) != sorted(
                    (f["role"], f["sha256"], f["size_bytes"]) for f in source["files"]):
                raise ValueError("Source files are not the committed public controls")
            packet = read(rehearsal / case / "delivery" / capture["metadata"]["path"])
            original_path = ROOT / f"manifests/scrna/controls/{label}.metadata.json"
            if sha256_file(original_path) != source["metadata_sha256"]:
                raise ValueError("Committed public metadata checksum changed")
            original = read(original_path)
            original.update(capture_id=capture["capture_id"], specimen_id=f"shadow-{label}-specimen",
                            source_classification="public_control", execution_purpose="patient_lane_shadow_rehearsal",
                            public_donor_group=source["donor_group"])
            if packet != original or mapping["public_donor_group"] != source["donor_group"]:
                raise ValueError("Rehearsal packet differs from public source metadata")
        if not inspect_delivery(contract, rehearsal / case / "delivery")["ready_for_postcount_qc"]:
            raise ValueError("Public rehearsal no longer passes intake")
    return provenance


def comparison(current: Path, previous: Path, current_method: dict, previous_method: dict) -> dict:
    result = {"baseline": previous.parent.name, "same_method_identity": current_method["method_sha256"] == previous_method["method_sha256"]}
    for name in ("all_cells_qc.csv", "umap.csv", "markers.csv", "cluster_marker_scores.csv"):
        left = pd.read_csv(current / name, index_col=0 if name != "markers.csv" else None)
        right = pd.read_csv(previous / name, index_col=0 if name != "markers.csv" else None)
        columns = sorted(set(left.columns) & set(right.columns) - ALIAS_COLUMNS)
        try:
            pd.testing.assert_frame_equal(left[columns], right[columns], check_exact=True)
            equal = True
        except AssertionError:
            equal = False
        result[name] = {"shared_non_alias_columns_exact": equal, "columns_compared": columns,
                        "new_columns": sorted(set(left.columns) - set(right.columns))}
    return result


def diagnostics(frame: pd.DataFrame, metrics: dict) -> dict:
    """Partition exclusions exactly and calculate posthoc core eligibility, never rescue cells."""
    low_g, low_u, mt = (frame[name].astype(bool) for name in ("fails_low_genes", "fails_low_umis", "fails_mt"))
    doublet = frame.doublet_class.eq("doublet")
    counts = {"low_genes_first": int(low_g.sum()), "low_umis_after_genes": int((~low_g & low_u).sum()),
              "mt_after_genes_and_umis": int((~low_g & ~low_u & mt).sum()),
              "doublets_after_core": int((~low_g & ~low_u & ~mt & doublet).sum()), "retained": int(frame.passes_QC.sum())}
    if sum(counts.values()) != len(frame) or counts["retained"] != metrics["retained_cells"]:
        raise ValueError("Exclusion partition does not match actual QC")
    if not np.array_equal(frame.passes_QC.to_numpy(), (~low_g & ~low_u & ~mt & ~doublet).to_numpy()):
        raise ValueError("Unexpected QC exclusion rule")
    reasons = frame.qc_failure_reasons.fillna("retained").value_counts().to_dict()
    current = metrics["thresholds"]["max_pct_mt"]
    sensitivity = []
    for ceiling in sorted(set([20.0, 30.0, 40.0, 50.0, 60.0, 80.0, 100.0, current])):
        eligible = ~low_g & ~low_u & frame.pct_counts_mt.le(ceiling)
        sensitivity.append({"mt_ceiling_percent": ceiling, "is_active_policy": ceiling == current,
                            "core_eligible_barcodes": int(eligible.sum()),
                            "newly_eligible_without_doublet_call": int((eligible & ~frame.passes_core_qc).sum())})
    return {"exclusive_exclusion_partition": counts, "overlapping_failure_combinations": {str(k): int(v) for k, v in reasons.items()},
            "mt_sensitivity_review_only": sensitivity,
            "sensitivity_limit": "Changing the MT ceiling requires a separate method run and new doublet calls; these are core eligibility counts, not rescued cells or a recommendation."}


def intake_fault_rehearsal(rehearsal: Path) -> dict:
    """Read-only mutations of the contract; original files and staged intake remain untouched."""
    original = read(rehearsal / "breast/contract.json")
    original["captures"] = original["captures"][:1]
    delivery = rehearsal / "breast/delivery"
    results = {}
    for name in ("count_checksum_mismatch", "metadata_checksum_mismatch", "duplicate_capture_counts", "unexpected_identifying_field"):
        contract = copy.deepcopy(original)
        capture = contract["captures"][0]
        if name == "count_checksum_mismatch":
            next(f for f in capture["files"] if f["role"] == "filtered_h5")["sha256"] = "0" * 64
        elif name == "metadata_checksum_mismatch":
            capture["metadata"]["sha256"] = "0" * 64
        elif name == "duplicate_capture_counts":
            duplicate = copy.deepcopy(capture)
            duplicate.update(capture_id="shadow-duplicate", metadata={"status": "unresolved"})
            contract["captures"].append(duplicate)
        else:
            contract["patient_name"] = "fabricated-fault-rehearsal"
        try:
            inspect_delivery(contract, delivery)
        except ValueError:
            results[name] = {"observed": "rejected", "expected_behavior": True}
        else:
            raise ValueError(f"Intake fault was not rejected: {name}")
    for name in ("unresolved_pooled_capture", "nuclei_outside_current_qc_scope", "filtered_only_ambient_gap"):
        contract = copy.deepcopy(original)
        capture = contract["captures"][0]
        if name == "unresolved_pooled_capture":
            capture.update(pooled_donors=True, metadata={"status": "unresolved"})
        elif name == "nuclei_outside_current_qc_scope":
            contract["material"] = "nuclei"
            capture["metadata"] = {"status": "unresolved"}
        else:
            capture["files"] = [f for f in capture["files"] if not f["role"].startswith("raw_")]
        inspected = inspect_delivery(contract, delivery)
        if name == "filtered_only_ambient_gap":
            passed = inspected["ready_for_postcount_qc"] and inspected["captures"][0]["details"]["ambient_status"] == "not_assessable_without_raw_droplets"
            observed = "provisional QC permitted; ambient assessment unavailable"
        else:
            passed = not inspected["ready_for_postcount_qc"]
            observed = "post-count QC blocked"
        if not passed:
            raise ValueError(f"Intake fault gave unexpected compatibility: {name}")
        results[name] = {"observed": observed, "expected_behavior": True}
    return {"source_files_mutated": False, "cloud_runs_for_faults": False, "checks": results}


def export(rehearsal: Path, run_ids: dict, destination: Path) -> dict:
    provenance = verify_public_sources(rehearsal)
    if destination.exists() or not destination.resolve().is_relative_to((ROOT / "results/scrna/validation").resolve()):
        raise ValueError("Use a new results/scrna/validation/ directory for this verified public report")
    report = {"schema_version": 1, "source_classification": "public_control", "execution_lane": "patient_research",
              "biological_accuracy_established": False, "clinical_ready": False, "provenance": provenance, "cases": {}, "captures": {}}
    report["intake_fault_rehearsal"] = intake_fault_rehearsal(rehearsal)
    report["ambient_published_defaults"] = AMBIENT_DEFAULTS
    report["report_source_hashes"] = {name: sha256_file(ROOT / "scripts" / name) for name in ("prepare_scrna_shadow.py", "review_scrna_shadow.py")}
    exports = []
    for case, run_id in run_ids.items():
        safe_id(run_id)
        run = ROOT / "private/scrna/runs" / run_id
        contract, method, metrics = verify_patient_run(run)
        local_contract = read(rehearsal / case / "contract.json")
        manifest = read(run / "run_manifest.json")
        # Remote filenames differ by design; the original source contract is bound by intake digest.
        if manifest["intake_id"] != digest_json(local_contract) or contract["case_id"] != local_contract["case_id"] or contract["evidence_lane"] != "patient_research":
            raise ValueError("Run differs from the verified public rehearsal")
        audit = rehearsal / case / "source_audit.json"
        decision = assess_case(run, audit=audit)
        if decision["decision"] != "provisional_hold" or decision["clinical_ready"] is not False:
            raise ValueError("Rehearsal must retain unresolved qualification and human-review holds")
        report["cases"][case] = {"run_id": run_id, "manifest": manifest, "method": method,
                                "source_audit": read(audit), "assessment": decision}
        for mapping in provenance["cases"][case]["captures"]:
            capture = mapping["capture_id"]
            label = mapping["control"]
            directory = run / capture
            frame = pd.read_csv(directory / "all_cells_qc.csv", index_col=0)
            baseline_id, baseline_capture = BASELINES[label]
            previous = ROOT / "private/scrna/runs" / baseline_id
            _, old_method, _ = verify_patient_run(previous)
            report["captures"][label] = {"capture_id": capture, "metrics": metrics[capture],
                                          "diagnostics": diagnostics(frame, metrics[capture]),
                                          "comparison": comparison(directory, previous / baseline_capture, method, old_method),
                                          "compartment_losses": pd.read_csv(directory / "provisional_compartment_losses.csv").to_dict(orient="records")}
            ambient = metrics[capture]["ambient_assessment"]
            lower_bound = ambient.get("version") == AMBIENT_DEFAULTS["version"] and ambient.get("rho_min") == 0.01 and ambient.get("rho_max") == 0.01
            report["captures"][label]["ambient_review"] = {"estimate_at_published_lower_bound": lower_bound,
                "interpretation": "The 1% fit is at the published default search boundary. Inspect the ambient model; this does not establish contamination is truly 1% or absent." if lower_bound else "Inspect ambient identifiability and diagnostics before interpretation."}
            for name in ("qc_thresholds.png", "umap_leiden.png", "umap_coarse_label_hint.png", "provisional_compartment_losses.csv", "cluster_stability.csv"):
                exports.append((directory / name, Path(label) / name))
    destination.mkdir(parents=True)
    for source, relative in exports:
        target = destination / relative
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
    report["exported_artifacts"] = [{"path": relative.as_posix(), "sha256": sha256_file(source), "size_bytes": source.stat().st_size} for source, relative in exports]
    write(destination / "shadow_review.json", report)
    write(destination / "public_rehearsal.json", provenance)
    sections = []
    lines = ["# Public-data patient-path shadow run", "", "Public controls only; no Diana data. Clinical readiness: no. All unresolved outputs remain on provisional hold.", "",
             "Two sorted breast libraries represent one public donor. Subtype, treatment, and reference content fingerprint remain unknown. PBMC is a technical control. This is post-count QC, not a FASTQ-to-count validation.", "",
             "| Control | Input | Retained | Retention | Seed ARI | Failed QC screens |", "|---|---:|---:|---:|---:|---|"]
    for label, details in report["captures"].items():
        metrics = details["metrics"]
        failed = ", ".join(key for key, value in metrics["gates"].items() if not value) or "none"
        lines.append(f"| {label} | {metrics['input_cells']} | {metrics['retained_cells']} | {metrics['retained_fraction']:.1%} | {metrics['seed_stability_ari']:.3f} | {failed} |")
        losses = details["compartment_losses"]
        rows = "".join(f"<tr><td>{escape(str(row['review_marker_hint_all_barcodes']))}</td><td>{row['input_cells']}</td><td>{row['retained_cells']}</td><td>{row['retained_fraction']:.1%}</td></tr>" for row in losses)
        exclusion = details["diagnostics"]["exclusive_exclusion_partition"]
        exclusion_rows = "".join(f"<tr><td>{escape(key)}</td><td>{value:,}</td></tr>" for key, value in exclusion.items())
        compared = details["comparison"]
        exact = all(value["shared_non_alias_columns_exact"] for key, value in compared.items() if key.endswith(".csv"))
        method_note = "Same method identity." if compared["same_method_identity"] else "The earlier method predates added review and custody fields; method identities differ."
        sections.append(f"""<section><h2>{escape(label)}</h2><p>{metrics['retained_cells']:,} / {metrics['input_cells']:,} retained ({metrics['retained_fraction']:.1%}); seed ARI {metrics['seed_stability_ari']:.3f} (median of {metrics['clustering_stability']['pairs_per_resolution']} seed pairs; minimum {metrics['clustering_stability']['min_pairwise_ari']:.3f}; resolution {metrics['clustering_stability']['selected_resolution']} chosen by stability alone, <a href="{label}/cluster_stability.csv">sweep</a>). Screens needing review: {escape(failed)}.</p>
<p>SoupX diagnostic status: {escape(metrics['ambient_rna_status'])}; candidate counts never selected for analysis. Unknown/mixed cluster hints: {metrics['unknown_label_fraction']:.1%}.</p>
<p>{escape(details['ambient_review']['interpretation'])}</p><p>Earlier-run comparison: {'all shared numerical, decision, marker and embedding columns match exactly' if exact else 'differences require inspection in the evidence JSON'}. {escape(method_note)}</p>
<h3>Exclusive exclusion counts</h3><p>Rules are counted in order to avoid counting overlapping flags twice.</p><table><tr><th>Decision</th><th>Barcodes</th></tr>{exclusion_rows}</table>
<img src="{label}/qc_thresholds.png" alt="Observed QC distributions and frozen thresholds"><div class="plots"><img src="{label}/umap_leiden.png" alt="Provisional clustering"><img src="{label}/umap_coarse_label_hint.png" alt="Coarse marker hints"></div>
<h3>Loss by review-only per-cell marker hint</h3><p>These hints are uncalibrated; they do not establish cell identity or malignancy. They differ from cluster annotations and never filter cells.</p>
<table><tr><th>Hint</th><th>Input</th><th>Retained</th><th>Retention</th></tr>{rows}</table><p><a href="{label}/provisional_compartment_losses.csv">Compartment loss CSV</a></p></section>""")
    all_exact = all(value["shared_non_alias_columns_exact"] for details in report["captures"].values() for key, value in details["comparison"].items() if key.endswith(".csv"))
    comparison_note = "All shared non-alias QC, selection, marker, and UMAP columns match the earlier runs exactly." if all_exact else "Earlier-run comparisons include differences; inspect the evidence JSON. Cluster-dependent outputs are expected to change when the stability-selected resolution differs from the earlier fixed 0.5."
    lines.extend(["", "All source-to-checkpoint audits pass ten checks per capture. " + comparison_note + " Method identity equality is recorded separately; LT's baseline predates added review and custody fields.", "",
                  "Seven read-only intake fault scenarios behaved as expected: changed count/metadata checksums, duplicate capture counts, and an extra identifying field were rejected; unresolved pooled capture and nuclei were blocked; filtered-only intake retained an explicit ambient assessment gap.", "",
                  "SoupX estimates at the 1% lower boundary of the published [1.6.2 default range](https://cran.r-project.org/src/contrib/SoupX_1.6.2.tar.gz) are flagged for review in the evidence JSON. They do not establish that true contamination is 1% or absent. The wrapper does not override the range; corrections remain diagnostic and unused.", "",
                  "The report records exclusion overlaps and a diagnostic MT sensitivity table. Changing thresholds would require a new analysis; newly eligible cells have no doublet calls.", "",
                  "Canonical complete outputs are in private/scrna/runs/<run_id> and versioned KMS-encrypted private S3. This directory is a small, explicitly public-source review export; it is not a complete run or method qualification certificate.", "",
                  "Before interpreting Diana's cell composition, review excluded barcodes and compartment losses, ambient diagnostics, doublets, unstable clusters, and unknown annotations with the sample metadata. Preserve the intake/qualification holds until the independent evidence and reviewer sign-off are available.", "",
                  "See [review.html](review.html) and [shadow_review.json](shadow_review.json) for provenance, method identities, canonical artifact manifests, audit checks, and default assessment decisions."])
    (destination / "README.md").write_text("\n".join(lines) + "\n")
    (destination / "review.html").write_text("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Public shadow QC review</title>
<style>body{font:16px/1.5 system-ui;background:#f5f7fa;color:#173047;max-width:1100px;margin:auto;padding:24px}section{background:white;border:1px solid #ccd6e0;border-radius:10px;margin:24px 0;padding:20px}img{width:100%;height:auto}.plots{display:grid;grid-template-columns:1fr 1fr;gap:10px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd}a{color:#17547c}@media(max-width:650px){.plots{grid-template-columns:1fr}body{padding:12px}}</style>
<h1>Shadow run complete; breast QC needs review</h1><p>Public 10x controls executed through the patient research intake and QC path on Modal and private S3. No Diana data. Clinical readiness: no. All cases remain on provisional hold.</p>
<p>Two breast captures from one sorted-cell public donor; subtype and treatment unknown. PBMC is a separate technical control. Frozen retention screen: at least 70%; seed ARI screen: median pairwise ARI across ten Leiden seeds of at least 0.85. These are review screens, not biological truth.</p>
<p>Count integrity, biological validity, and patient admission are separate decisions. Full-barcode checkpoints remain intact. No integration, differential expression, or malignancy inference. This rehearsal does not validate upstream cell calling or FASTQ processing.</p>""" + "".join(sections) + """<p>Review the breast compartment losses and clustering instability before interpreting cell proportions. Ambient and doublet estimates lack independent truth labels; marker margins are not probabilities.</p><p><a href="shadow_review.json">Machine-readable evidence, comparisons and MT sensitivity</a> · <a href="public_rehearsal.json">Public provenance</a> · <a href="README.md">Scope and next steps</a></p></html>""")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearsal", type=Path, required=True)
    parser.add_argument("--breast-run-id", required=True)
    parser.add_argument("--pbmc-run-id", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.rehearsal, {"breast": args.breast_run_id, "pbmc": args.pbmc_run_id}, args.destination)
    print(json.dumps({"cases": len(result["cases"]), "captures": len(result["captures"]), "clinical_ready": result["clinical_ready"]}))
