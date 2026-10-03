"""Patient post-count QC with explicit provisional outputs and no public promotion."""
from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from pathlib import Path

from .scrna_ambient import assess_ambient
from .scrna_intake import inspect_delivery, local_file, read_matrix
from .scrna_io import sha256_file, write_json
from .scrna_private import digest_json

PARAMETERS = {"seed": 42, "n_hvg": 2000, "n_pcs": 40, "n_neighbors": 15, "qc_mad_multiplier": 3,
              "leiden_resolution": 0.5, "leiden_iterations": -1, "miqc_challenger": False,
              # Resolution is chosen per capture by multi-seed reproducibility, never by labels or QC outcomes.
              "leiden_resolution_grid": [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0], "stability_seeds": 10}
ACCEPTANCE = {"retained_fraction_min": 0.7, "retained_fraction_max": 1, "clusters_min": 4, "clusters_max": 25,
              "seed_stability_ari_min": 0.85}
SCIENTIFIC_FILES = ("scrna.py", "scrna_io.py", "scrna_qc.py", "scrna_miqc.py", "scrna_intake.py", "scrna_ambient.py", "scrna_patient.py")


def execute_patient(contract: dict, source: Path, output: Path, runner_source: str) -> dict:
    from .scrna import analyze

    inspection = inspect_delivery(contract, source)
    if not inspection["ready_for_postcount_qc"]:
        raise ValueError("Intake is not compatible with post-count QC; inspect the local preflight")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "input_contract.json", contract)
    write_json(output / "intake_inspection.json", inspection)
    package_versions = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions() if dist.metadata["Name"]}
    write_json(output / "python_packages.json", {"python": platform.python_version(), "packages": package_versions})
    explicit = subprocess.run(["micromamba", "list", "--explicit"], capture_output=True, text=True, check=True)
    (output / "conda-explicit.txt").write_text(explicit.stdout)
    source_dir = output / "source"
    source_dir.mkdir()
    hashes = {}
    for name in SCIENTIFIC_FILES + ("scrna_private.py", "scrna_trust.py"):
        path = Path(__file__).with_name(name)
        (source_dir / name).write_bytes(path.read_bytes())
        hashes[name] = sha256_file(path)
    (source_dir / "modal_patient_runner.py").write_text(runner_source)
    hashes["modal_patient_runner.py"] = sha256_file(source_dir / "modal_patient_runner.py")
    write_json(output / "source_hashes.json", hashes)
    method = {"schema_version": 1, "scientific_sources": {name: hashes[name] for name in SCIENTIFIC_FILES},
              "parameters": PARAMETERS, "ambient_policy": "SoupX-1.6.2-diagnostic-only",
              "runner_sha256": hashes["modal_patient_runner.py"], "storage_source_sha256": hashes["scrna_private.py"],
              "annotation_policy": "tissue-marker-hints-no-calibrated-probability",
              "conda_explicit_sha256": sha256_file(output / "conda-explicit.txt"),
              "python_versions": {key: package_versions[key] for key in ("scanpy", "anndata", "numpy", "scipy", "pandas", "scikit-learn", "igraph", "leidenalg", "umap-learn")}}
    method["method_sha256"] = digest_json(method)
    write_json(output / "method_identity.json", method)
    summaries = {}
    for capture in contract["captures"]:
        paths = {item["role"]: local_file(source, item["path"]) for item in capture["files"]}
        counts = read_matrix(capture, paths)
        directory = output / capture["capture_id"]
        ambient = None
        if any(role.startswith("raw_") for role in paths):
            raw = read_matrix(capture, paths, raw=True)
            ambient = assess_ambient(counts, raw, output / (capture["capture_id"] + "-ambient"))
            del raw
        breast = contract["tissue"] == "breast tumor"
        resolved = capture["metadata"]["status"] == "reviewed" and "unknown" not in (capture["chemistry"], capture["reference"])
        dataset = {"dataset_id": capture["capture_id"], "format": capture["format"], "expected_cells": capture["expected_cells"],
                   "capture_id": capture["capture_id"], "donor_id": contract["case_id"], "sample_id": capture["specimen_id"],
                   "qc_profile": "human_breast_tumor" if breast else "human_pbmc",
                   "capture_scope": "verified_single_capture" if resolved else "sample_proxy_unresolved",
                   "chemistry_status": "verified" if resolved else "unresolved", "clinical_subtype": capture["clinical_subtype"],
                   "treatment_status": capture["treatment_status"], "timepoint": capture["timepoint"],
                   "upstream_processing": "Vendor filtered, uncorrected UMI matrix; raw lineage checked when available"}
        summaries[capture["capture_id"]] = analyze(dataset, PARAMETERS, ACCEPTANCE, {}, directory,
                                                   supplied_counts=counts, ambient_assessment=ambient)
    write_json(output / "qc_summary.json", summaries)
    write_patient_review(output, contract, summaries)
    return {"status": "qc_provisional", "captures": summaries, "method_sha256": method["method_sha256"], "clinical_ready": False}


def write_patient_review(output: Path, contract: dict, summaries: dict) -> None:
    from html import escape

    sections = []
    for capture_id, metrics in summaries.items():
        name = escape(capture_id)
        failed = [key for key, passed in metrics["gates"].items() if not passed]
        ambient = metrics["ambient_assessment"]
        sections.append(f'''<section><h2>{name}</h2>
          <p>{metrics['retained_cells']:,} / {metrics['input_cells']:,} filtered vendor barcodes in provisional analysis;
          {metrics['doublets_flagged']:,} scDblFinder calls; seed ARI {metrics['seed_stability_ari']:.3f} (median of {metrics['clustering_stability']['pairs_per_resolution']} seed pairs at selected resolution {metrics['clustering_stability']['selected_resolution']}).</p>
          <p>Review screens requiring attention: {escape(', '.join(failed) or 'none; method qualification and human review still required')}.</p>
          <p>Ambient status: {escape(ambient['status'])}. Correction is diagnostic only; analysis uses original counts.</p>
          <p>Unknown/mixed marker hints: {metrics['unknown_label_fraction']:.1%}. Marker margins are not probabilities.
          Epithelial expression does not establish malignancy.</p>
          <img src="{name}/qc_thresholds.png" alt="QC thresholds">
          <div class="plots"><img src="{name}/umap_leiden.png" alt="Clusters"><img src="{name}/umap_coarse_label_hint.png" alt="Provisional tissue hints"></div>
          <p><a href="{name}/all_cells_qc.csv">Every vendor barcode, including excluded cells</a> ·
          <a href="{name}/provisional_compartment_losses.csv">Loss by review-only tissue marker hint</a> ·
          <a href="{name}/all_cells_qc.h5ad">Original counts and correction challenger</a> ·
          <a href="{name}/analysis.h5ad">Provisional analysis</a> · <a href="{name}/cluster_stability.csv">Resolution stability sweep</a> · <a href="{name}/calibration.json">QC metrics</a></p></section>''')
    (output / "review.html").write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Single-cell intake and provisional QC</title><style>body{font:16px/1.5 system-ui;background:#f6f8fa;color:#182a39;margin:auto;padding:24px;max-width:1100px}
      section{background:white;border:1px solid #dbe3ea;border-radius:10px;padding:20px;margin:20px 0}.plots{display:grid;grid-template-columns:1fr 1fr;gap:10px}img{width:100%;height:auto}a{color:#17547c}
      @media(max-width:650px){body{padding:12px}.plots{grid-template-columns:1fr}}</style><h1>Intake verified; QC is provisional</h1>
      <p>Research review only. This completion report does not qualify the method, admit a patient result, or authorize treatment conclusions.
      Clinical readiness: no. Technical captures are analyzed separately. No integration, differential expression, or malignant-cell calling.</p>
      <p>The existing breast mitochondrial rule can remove biological populations. Review losses on the full-barcode checkpoint before interpreting cell composition.
      miQC is disabled. SoupX candidate counts are preserved when identifiable, and never automatically selected.</p>''' + "".join(sections) + '''
      <p><a href="method_identity.json">Method identity</a> · <a href="input_contract.json">Input contract</a> · <a href="artifact_index.json">Artifact checksums</a></p></html>''')
