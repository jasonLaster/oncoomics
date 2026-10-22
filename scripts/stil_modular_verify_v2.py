"""Independently reconstruct v2 assessable-stroma outputs and QC gates; not accuracy validation.

With ``--legacy-run`` the same three gates are evaluated on an earlier two-class
run (native and competition masks), so old and new values sit side by side.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diana_omics import stil_sampling, stil_tissue  # noqa: E402

V2_SEGMENTED, V2_CLASSIFIED = "completed_multiclass_segmentation_v2", "completed_assessable_stroma_v2"
LEGACY_TO_V2 = np.array([stil_tissue.BACKGROUND, stil_tissue.TUMOR, stil_tissue.STROMA], np.uint8)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_bundle(run):
    manifest = json.loads((run / "bundle_manifest.json").read_text())
    for artifact in manifest["files"]:
        relative = Path(artifact["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        path = run / relative
        assert path.stat().st_size == artifact["bytes"] and digest(path) == artifact["sha256"], str(path)
    return manifest


def nucleus_compartments(instances, region):
    """Instance IDs with at least half their pixels in ``region`` (independent of stil_tissue)."""
    ids, counts = np.unique(instances[instances > 0], return_counts=True)
    inside_ids, inside_counts = np.unique(instances[(instances > 0) & region], return_counts=True)
    inside = dict(zip(inside_ids.tolist(), inside_counts.tolist()))
    return {i for i, n in zip(ids.tolist(), counts.tolist()) if inside.get(i, 0) * 2 >= n}


def recount(labels, instances, cells, stroma_codes, tumor_code):
    stroma = np.isin(labels, stroma_codes)
    tissue = ~np.isin(labels, [stil_tissue.BACKGROUND, stil_tissue.ARTIFACT])
    immune = [c["instance_id"] for c in cells if c["class_name"] in ("Lymphocyte", "Plasma_cell")]
    inside = nucleus_compartments(instances, stroma)
    return {"tissue_pixels": int(tissue.sum()), "assessable_stroma_pixels": int(stroma.sum()),
            "tumor_pixels": int((labels == tumor_code).sum()),
            "immune_nuclear_pixels_in_assessable": int((np.isin(instances, immune) & stroma).sum()),
            "immune_nuclei": len(immune), "immune_nuclei_in_assessable": sum(i in inside for i in immune),
            "tumor_nuclei": sum(c["class_name"] == "tumor" for c in cells),
            "classified_nuclei": sum(c["class_name"] != "Unknown" for c in cells)}


def summarize(rows, area):
    total = {k: sum(r[k] for r in rows) for k in rows[0] if k != "nuclei"}
    return {"tiles": len(rows),
            "assessable_stroma_um2": total["assessable_stroma_pixels"] * area,
            "assessable_stroma_immune_nuclear_area_percent":
                100 * total["immune_nuclear_pixels_in_assessable"] / total["assessable_stroma_pixels"] if total["assessable_stroma_pixels"] else None,
            "immune_nuclei": total["immune_nuclei"],
            "immune_in_assessable_fraction": total["immune_nuclei_in_assessable"] / total["immune_nuclei"] if total["immune_nuclei"] else None,
            "tumor_mask_fraction": total["tumor_pixels"] / total["tissue_pixels"] if total["tissue_pixels"] else None,
            "tumor_nucleus_fraction": total["tumor_nuclei"] / total["classified_nuclei"] if total["classified_nuclei"] else None}


def verify_v2(run, inputs):
    manifest = check_bundle(run)
    sources = json.loads((inputs / "tile_manifest.json").read_text())
    by_id = {row["tile_id"]: row for row in sources["tiles"]}
    slides = {s["slide_key"]: s for s in sources["slides"]}
    results = {}
    for key in manifest["slide_keys"]:
        root = run / key
        segmentation = json.loads((root / "run_manifest.json").read_text())
        classification = json.loads((root / "classification_manifest.json").read_text())
        assert segmentation["status"] == V2_SEGMENTED and classification["status"] == V2_CLASSIFIED
        assert segmentation["tile_manifest_sha256"] == digest(inputs / "tile_manifest.json")
        assert classification["segmentation_manifest_sha256"] == digest(root / "run_manifest.json")
        assert classification["clinical_stil_percent"] is None and classification["nuclear_area_proxy_percent"] is None
        expected = {r["tile_id"] for r in sources["tiles"] if r["slide_key"] == key}
        assert {t["tile_id"] for t in classification["tiles"]} == expected
        glass = slides.get(key, {}).get("glass_rgb", [250., 250., 250.])
        rows, artifact_tiles = [], []
        for summary in classification["tiles"]:
            tile = by_id[summary["tile_id"]]
            folder = root / summary["tile_id"]
            source = inputs / tile["image_path"]
            assert digest(source) == tile["image_sha256"]
            rgb = np.asarray(Image.open(source).convert("RGB"))
            core = rgb[64:1088, 64:1088]
            masks = np.load(folder / "pixel_masks_v2.npz")
            glass_pixels = stil_sampling.white_pixels(core, glass)
            artifact = ndimage.binary_dilation(stil_sampling.ink_pixels(core), iterations=3)
            assert np.array_equal(masks["glass"], glass_pixels) and np.array_equal(masks["artifact"], artifact)
            probabilities = np.load(folder / "tissue_probabilities_v2.npz")
            stack = np.stack([probabilities[stil_tissue.LABELS[c]].astype(np.float32) for c in stil_tissue.MODEL_CLASSES])
            labels = np.array(stil_tissue.MODEL_CLASSES, np.uint8)[stack.argmax(0)]
            labels[glass_pixels] = stil_tissue.BACKGROUND
            labels[artifact] = stil_tissue.ARTIFACT
            assert np.array_equal(labels, np.load(folder / "tissue_labels_v2.npy"))
            instances = np.load(folder / "nucleus_instances_core.npy")
            assert np.array_equal(instances, np.load(folder / "nucleus_instances_halo.npy")[64:1088, 64:1088])
            cells = json.loads((folder / "cell_classifications.json").read_text())
            assert {c["instance_id"] for c in cells} == set(np.unique(instances).tolist()) - {0}
            counts = recount(labels, instances, cells, list(stil_tissue.ASSESSABLE), stil_tissue.TUMOR)
            for k in ("tissue_pixels", "assessable_stroma_pixels", "immune_nuclear_pixels_in_assessable", "immune_nuclei",
                      "immune_nuclei_in_assessable", "tumor_nuclei", "classified_nuclei"):
                assert counts[k] == summary[k], (summary["tile_id"], k)
            assert counts["tumor_pixels"] == summary["label_pixels"]["tumor"]
            qc = stil_sampling.tile_pixel_qc(rgb, 64, glass)
            if qc["ink_tile"] or qc["off_tissue_tile"]:
                artifact_tiles.append(summary["tile_id"])
            rows.append(counts)
        area = math.prod(by_id[classification["tiles"][0]["tile_id"]]["mpp_xy"])
        recomputed = summarize(rows, area)
        reported = classification["aggregate"]
        for k in ("assessable_stroma_immune_nuclear_area_percent", "immune_in_assessable_fraction",
                  "tumor_mask_fraction", "tumor_nucleus_fraction"):
            assert (reported[k] is None and recomputed[k] is None) or math.isclose(reported[k], recomputed[k], abs_tol=1e-9), k
        gates = stil_tissue.evaluate_gates(recomputed, segmentation["candidate_tissue_group"], artifact_tiles)
        assert gates == classification["qc_gates"], key
        results[key] = dict(recomputed, slide=tile["slide"], candidate_tissue_group=segmentation["candidate_tissue_group"],
                            qc_gates=gates, reused_nucleus_tiles=segmentation["reused_nucleus_tiles"],
                            artifact_and_arithmetic_checks="pass", clinical_stil_percent=None)
    return results


def legacy_gates(run, inputs, keys):
    """Evaluate gates on a two-class run. Assessable = predicted stroma (the old definition)."""
    sources = json.loads((inputs / "tile_manifest.json").read_text())
    by_id = {row["tile_id"]: row for row in sources["tiles"]}
    results = {}
    for key in keys:
        root = run / key
        classification = json.loads((root / "classification_manifest.json").read_text())
        variants = {"native": ([], "tissue_labels.npy"), "competition": ([], "tissue_labels_competition.npy")}
        artifact_tiles = []
        for summary in classification["tiles"]:
            tile = by_id[summary["tile_id"]]
            folder = root / summary["tile_id"]
            instances = np.load(folder / "nucleus_instances_core.npy")
            cells = json.loads((folder / "cell_classifications.json").read_text())
            for rows, name in variants.values():
                labels = LEGACY_TO_V2[np.load(folder / name)]
                rows.append(dict(recount(labels, instances, cells, [stil_tissue.STROMA], stil_tissue.TUMOR), nuclei=len(cells)))
            source = inputs / tile["image_path"]
            assert digest(source) == tile["image_sha256"]
            qc = stil_sampling.tile_pixel_qc(np.asarray(Image.open(source).convert("RGB")), 64)
            if qc["ink_tile"] or qc["off_tissue_tile"]:
                artifact_tiles.append(summary["tile_id"])
        area = math.prod(tile["mpp_xy"])
        group = tile["candidate_tissue_group"]
        results[key] = {"slide": tile["slide"], "candidate_tissue_group": group, "tiles": len(classification["tiles"]),
                        "reported_native_percent": classification["exploratory_model_stroma_nuclear_area_percent"],
                        "reported_competition_percent": classification["competition_model_stroma_nuclear_area_percent"],
                        "clinical_stil_percent": None}
        for variant, (rows, _) in variants.items():
            summary = summarize(rows, area)
            results[key][variant] = dict(summary, qc_gates=stil_tissue.evaluate_gates(summary, group, artifact_tiles))
        # The legacy ratio skipped tiles without nuclei; reproduce it to tie these counts to the old receipts.
        for variant, reported in (("native", "reported_native_percent"), ("competition", "reported_competition_percent")):
            callable_rows = [r for r in variants[variant][0] if r["assessable_stroma_pixels"] and r["nuclei"]]
            value = summarize(callable_rows, area)["assessable_stroma_immune_nuclear_area_percent"] if callable_rows else None
            expected = results[key][reported]
            assert (value is None and expected is None) or math.isclose(value, expected, abs_tol=1e-9), (key, variant)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="Collected v2 run")
    parser.add_argument("--inputs", type=Path, help="Local inputs used by the v2 run")
    parser.add_argument("--legacy-run", type=Path, help="Collected two-class run")
    parser.add_argument("--legacy-inputs", type=Path)
    parser.add_argument("--keys", default="", help="Comma-separated legacy slide keys; default the v2 run's keys")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {"evidence_classification": "internal_qc", "model_accuracy_validation": "not_established",
              "clinical_validation": "not_established", "clinical_stil_percent": None, "gates": stil_tissue.GATES}
    keys = [k for k in args.keys.split(",") if k]
    if args.run:
        result["v2"] = verify_v2(args.run, args.inputs)
        keys = keys or list(result["v2"])
    if args.legacy_run:
        result["legacy"] = legacy_gates(args.legacy_run, args.legacy_inputs, keys)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
