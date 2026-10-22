"""Independently reconstruct sampled modular outputs; this is not accuracy validation."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(run, inputs, expected_slides):
    manifest = json.loads((run / "bundle_manifest.json").read_text())
    bundled = {artifact["path"]: artifact for artifact in manifest["files"]}
    assert len(bundled) == len(manifest["files"])
    for artifact in manifest["files"]:
        relative = Path(artifact["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        path = run / relative
        assert path.stat().st_size == artifact["bytes"] and digest(path) == artifact["sha256"], str(path)
    sources = json.loads((inputs / "tile_manifest.json").read_text())
    by_id = {row["tile_id"]: row for row in sources["tiles"]}
    assert len(by_id) == len(sources["tiles"])
    assert len(manifest["slide_keys"]) == expected_slides
    checks = []
    for key in manifest["slide_keys"]:
        root = run / key
        segmentation = json.loads((root / "run_manifest.json").read_text())
        classification = json.loads((root / "classification_manifest.json").read_text())
        for stage in (segmentation, classification):
            for artifact in stage["artifacts"]:
                member = bundled[str(Path(key) / artifact["path"])]
                assert member["sha256"] == artifact["sha256"] and member["bytes"] == artifact["bytes"]
        assert segmentation["status"] == "completed_two_components"
        assert segmentation["clinical_stil_percent"] is None and segmentation["pathologist_score"] is None
        assert classification["status"] == "completed_experimental_comparison"
        assert classification["clinical_stil_percent"] is None and classification["nuclear_area_proxy_percent"] is None
        assert classification["segmentation_manifest_sha256"] == digest(root / "run_manifest.json")
        assert classification["checkpoint_sha256"] == "e93362f4e894cad5d02cf72d944702f7fd9b95b5fc25eedf01406adf1c7b7ead"
        assert segmentation["VISTA_checkpoint_strict_load"] and classification["checkpoint_strict_load"]
        assert segmentation["tile_manifest_sha256"] == digest(inputs / "tile_manifest.json")
        tile_ids = [t["tile_id"] for t in segmentation["tiles"]]
        expected_ids = {row["tile_id"] for row in sources["tiles"] if row["slide_key"] == key}
        assert len(tile_ids) == len(set(tile_ids)) and set(tile_ids) == expected_ids
        assert {t["tile_id"] for t in classification["tiles"]} == expected_ids
        expected_organ = "lymph_node" if by_id[tile_ids[0]]["candidate_tissue_group"] == "axillary_sentinel_node" else "breast"
        assert classification["organ_head"] == expected_organ
        raw_area, stroma_area, threshold_area, unknown_area, nuclear_area = 0., 0., 0., 0., 0.
        competition_raw, competition_area, competition_filtered, competition_unknown, competition_nuclear = 0., 0., 0., 0., 0.
        total_nuclei, callable_tiles, competition_calls = 0, 0, 0
        coordinates = []
        for summary in classification["tiles"]:
            tile = by_id[summary["tile_id"]]
            assert tile["source_sha256"] == segmentation["source_sha256"] == classification["source_sha256"]
            assert digest(inputs / tile["image_path"]) == tile["image_sha256"]
            x, y = tile["origin_level0_xy"]
            assert all(x+1024 <= px or px+1024 <= x or y+1024 <= py or py+1024 <= y for px, py in coordinates)
            coordinates.append((x, y))
            folder = root / summary["tile_id"]
            labels = np.load(folder / "tissue_labels.npy", allow_pickle=False)
            instances = np.load(folder / "nucleus_instances_core.npy", allow_pickle=False)
            halo = np.load(folder / "nucleus_instances_halo.npy", allow_pickle=False)
            assert labels.shape == instances.shape == (1024, 1024)
            assert np.isin(labels, [0, 1, 2]).all()
            h = tile["halo_pixels"]
            assert np.array_equal(instances, halo[h:h+1024, h:h+1024])
            assert (instances >= 0).all()
            cells = json.loads((folder / "cell_classifications.json").read_text())
            ids = [row["instance_id"] for row in cells]
            assert len(ids) == len(set(ids)) and set(ids) == set(np.unique(instances)) - {0}
            arrays = np.load(folder / "class_probabilities.npz", allow_pickle=False)
            probabilities, classes = arrays["probabilities"], arrays["classes"].tolist()
            assert probabilities.shape == (len(arrays["instance_ids"]), len(classes))
            probability_ids = arrays["instance_ids"].tolist()
            assert len(classes) == len(set(classes))
            assert len(probability_ids) == len(set(probability_ids))
            assert set(probability_ids) == {c["instance_id"] for c in cells if c["class_name"] != "Unknown"}
            assert np.isfinite(probabilities).all() and ((probabilities >= 0) & (probabilities <= 1)).all()
            assert np.allclose(probabilities.sum(1), 1., atol=1e-5)
            probability_rows = dict(zip(arrays["instance_ids"].tolist(), probabilities))
            for cell in cells:
                if cell["class_name"] == "Unknown":
                    assert cell["probability"] == 0 and cell["rejection_reason"] == "context_exceeds_saved_halo"
                    continue
                row = probability_rows[cell["instance_id"]]
                assert cell["class_name"] == classes[int(row.argmax())]
                assert math.isclose(cell["probability"], float(row.max()), abs_tol=1e-7)
            stroma = labels == 2
            denominator = int(stroma.sum())
            immune_ids = [c["instance_id"] for c in cells if c["class_name"] in ("Lymphocyte", "Plasma_cell")]
            raw = int((np.isin(instances, immune_ids) & stroma).sum())
            assert raw == summary["raw_immune_nuclear_pixels"] and denominator == summary["predicted_stromal_pixels"]
            assert summary["clinical_stil_percent"] is None and summary["eligibility_reviewed"] is False
            assert summary["included_in_exploratory_aggregate"] == bool(denominator and cells)
            assert summary["classified_nuclei"] == len(cells)
            total_nuclei += len(cells)
            for threshold in (0., .5, .7, .9):
                accepted = [c["instance_id"] for c in cells if c["class_name"] in ("Lymphocyte", "Plasma_cell") and c["probability"] >= threshold]
                rejected = [c["instance_id"] for c in cells if c["class_name"] == "Unknown" or c["probability"] < threshold]
                assert int((np.isin(instances, accepted) & stroma).sum()) == summary["sensitivity"][str(threshold)]["immune_nuclear_pixels"]
                assert int((np.isin(instances, rejected) & stroma).sum()) == summary["sensitivity"][str(threshold)]["unresolved_nuclear_pixels"]
            if summary["included_in_exploratory_aggregate"]:
                area = math.prod(tile["mpp_xy"])
                assert math.isclose(area, summary["pixel_area_um2"], abs_tol=1e-12)
                raw_area += raw * area
                stroma_area += denominator * area
                threshold_area += summary["sensitivity"]["0.7"]["immune_nuclear_pixels"] * area
                unknown_area += summary["sensitivity"]["0.7"]["unresolved_nuclear_pixels"] * area
                nuclear_area += int(((instances > 0) & stroma).sum()) * area
                callable_tiles += 1
            probabilities = np.load(folder / "tissue_probabilities.npz", allow_pickle=False)
            tumor_probability, stroma_probability = probabilities["Tumor"], probabilities["Stroma"]
            for probability in (tumor_probability, stroma_probability):
                assert probability.shape == labels.shape
                assert np.isfinite(probability).all() and ((probability >= 0) & (probability <= 1)).all()
            expected_mask = np.where(stroma_probability > tumor_probability, 2,
                                     np.where(tumor_probability > stroma_probability, 1, 0)).astype(np.uint8)
            expected_mask[np.maximum(tumor_probability, stroma_probability) < .5] = 0
            competition_mask = np.load(folder / "tissue_labels_competition.npy", allow_pickle=False)
            assert np.array_equal(competition_mask, expected_mask)
            comp = summary["competition"]
            stroma = competition_mask == 2
            assert comp["predicted_stromal_pixels"] == int(stroma.sum())
            assert comp["included_in_exploratory_aggregate"] == bool(stroma.any() and cells)
            assert comp["raw_immune_nuclear_pixels"] == int((np.isin(instances, immune_ids) & stroma).sum())
            for threshold in (0., .5, .7, .9):
                accepted = [c["instance_id"] for c in cells if c["class_name"] in ("Lymphocyte", "Plasma_cell") and c["probability"] >= threshold]
                rejected = [c["instance_id"] for c in cells if c["class_name"] == "Unknown" or c["probability"] < threshold]
                assert comp["sensitivity"][str(threshold)]["immune_nuclear_pixels"] == int((np.isin(instances, accepted) & stroma).sum())
                assert comp["sensitivity"][str(threshold)]["unresolved_nuclear_pixels"] == int((np.isin(instances, rejected) & stroma).sum())
            if comp["included_in_exploratory_aggregate"]:
                competition_calls += 1
                area = math.prod(tile["mpp_xy"])
                competition_raw += comp["raw_immune_nuclear_pixels"] * area
                competition_area += comp["predicted_stromal_pixels"] * area
                competition_filtered += comp["sensitivity"]["0.7"]["immune_nuclear_pixels"] * area
                competition_unknown += comp["sensitivity"]["0.7"]["unresolved_nuclear_pixels"] * area
                competition_nuclear += int(((instances > 0) & stroma).sum()) * area
        assert total_nuclei == classification["total_nuclei"] and callable_tiles == classification["callable_tiles"]
        assert classification["tile_no_calls"] == len(tile_ids) - callable_tiles
        assert competition_calls == classification["competition_callable_tiles"]
        actual = classification["exploratory_model_stroma_nuclear_area_percent"]
        if stroma_area:
            assert math.isclose(100*raw_area/stroma_area, actual, abs_tol=1e-9)
        else:
            assert actual is None
        competition_score = classification["competition_model_stroma_nuclear_area_percent"]
        if competition_area:
            assert math.isclose(100*competition_raw/competition_area, competition_score, abs_tol=1e-9)
        else:
            assert competition_score is None
        checks.append({"slide_key": key, "source_sha256": classification["source_sha256"],
                       "tiles_checked": len(tile_ids), "callable_tiles": callable_tiles,
                       "nuclei_checked": total_nuclei, "raw_model_stroma_nuclear_area_percent": actual,
                       "filtered_model_stroma_nuclear_area_percent_at_0_7": 100*threshold_area/stroma_area if stroma_area else None,
                       "unknown_fraction_of_stromal_nuclear_area_at_0_7": unknown_area/nuclear_area if nuclear_area else None,
                       "competition_model_stroma_nuclear_area_percent": competition_score,
                       "competition_filtered_percent_at_0_7": 100*competition_filtered/competition_area if competition_area else None,
                       "competition_unknown_fraction_at_0_7": competition_unknown/competition_nuclear if competition_nuclear else None,
                       "clinical_stil_percent": None, "artifact_and_arithmetic_checks": "pass"})
    return {"evidence_classification": "internal_qc", "validation_verdict": "validated_for_narrower_claim",
            "validated_claim": "source-bound sampled masks and independently reconstructed nuclear-area aggregation",
            "model_accuracy_validation": "not_established", "clinical_validation": "not_established",
            "slides_verified": len(checks), "bundle_files_verified": len(manifest["files"]), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expected-slides", type=int, default=9)
    args = parser.parse_args()
    result = verify(args.run, args.inputs, args.expected_slides)
    (args.run / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
