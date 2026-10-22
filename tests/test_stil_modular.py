"""Known-answer mask arithmetic and failure gates, not model-accuracy tests."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

from diana_omics.stil_modular import MASK_NAMES, STROMA_DEFINITION, prepare_review_queue, score_masks


@unittest.skipIf(np is None, "install the pathology extra for mask arithmetic tests")
class ModularStilTests(unittest.TestCase):
    def setUp(self):
        self.masks = {name: np.ones((4, 4), dtype=bool) for name in MASK_NAMES[:-1]}
        self.masks["exclusions"][:] = False
        self.masks["instances"] = np.array([[1, 1, 0, 0], [2, 2, 0, 0], [3, 3, 0, 0], [4, 4, 0, 0]], dtype=np.int32)
        self.cells = [
            {"instance_id": 1, "class_name": "Lymphocyte", "probability": .95},
            {"instance_id": 2, "class_name": "Plasma_cell", "probability": .95},
            {"instance_id": 3, "class_name": "Macrophage", "probability": .95},
            {"instance_id": 4, "class_name": "Lymphocyte", "probability": .3},
        ]
        grid = {"source_sha256": "a" * 64, "origin_level0_xy": [100, 200], "mpp_xy": [.5, .5], "shape_yx": [4, 4]}
        self.contract = {
            "scope": "roi", "grid": grid, "layer_grids": {key: copy.deepcopy(grid) for key in MASK_NAMES},
            "stain": "H&E", "specimen_type": "breast", "organ_head": "breast",
            "stroma_definition": STROMA_DEFINITION, "source_identity_verified": True,
            "annotation_reviewed": True, "annotation_reference": "synthetic-known-answer",
            "treatment_timepoint": "post_neoadjuvant", "scoring_protocol_reference": "synthetic-protocol",
            "probability_threshold": .8,
            "acceptance": {"min_stromal_area_um2": .25, "min_coverage_fraction": .9, "max_unknown_nuclear_area_fraction": .3},
        }

    def test_includes_plasma_cells_excludes_macrophages_and_rejected_cells(self):
        result = score_masks(self.masks, self.cells, self.contract)
        self.assertEqual(result["nuclear_area_proxy_percent"], 25)
        self.assertEqual(result["immune_nuclear_area_um2"], 1)
        self.assertEqual(result["assessed_stromal_area_um2"], 4)
        self.assertEqual(result["unknown_nuclear_area_percent_of_stroma"], 12.5)
        self.assertEqual(result["unknown_fraction_of_assessed_nuclear_area"], .25)
        self.assertIsNone(result["clinical_stil_percent"])

    def test_clips_nuclear_pixels_at_stromal_boundary_and_exclusions(self):
        self.masks["stroma"][:, 1] = False
        self.masks["exclusions"][0, 0] = True
        self.contract["acceptance"]["max_unknown_nuclear_area_fraction"] = .4
        result = score_masks(self.masks, self.cells, self.contract)
        self.assertEqual(result["assessed_stromal_area_um2"], 2.75)
        self.assertAlmostEqual(result["nuclear_area_proxy_percent"], 100 / 11)

    def test_coverage_measures_stromal_pixels_not_tile_count(self):
        self.masks["assessed_region"][3, :] = False
        result = score_masks(self.masks, self.cells, self.contract)
        self.assertEqual(result["eligible_stroma_coverage_fraction"], .75)
        self.assertIn("insufficient_eligible_stroma_coverage", result["no_call_reasons"])
        self.assertIsNone(result["nuclear_area_proxy_percent"])

    def test_unknowns_do_not_disappear_from_denominator(self):
        self.cells[0]["class_name"] = "Unknown"
        result = score_masks(self.masks, self.cells, self.contract)
        self.assertEqual(result["assessed_stromal_area_um2"], 4)
        self.assertEqual(result["unknown_fraction_of_assessed_nuclear_area"], .5)
        self.assertIn("excess_unresolved_nuclear_area", result["no_call_reasons"])
        self.assertIsNone(result["nuclear_area_proxy_percent"])

    def test_empty_stroma_is_no_call_not_zero(self):
        self.masks["stroma"][:] = False
        result = score_masks(self.masks, self.cells, self.contract)
        self.assertEqual(result["status"], "no_call")
        self.assertIsNone(result["nuclear_area_proxy_percent"])
        self.assertIsNone(result["unknown_nuclear_area_percent_of_stroma"])

    def test_rejects_source_coordinate_and_scale_mismatches(self):
        for key, value in (("source_sha256", "b" * 64), ("origin_level0_xy", [101, 200]), ("mpp_xy", [.25, .25])):
            contract = copy.deepcopy(self.contract)
            contract["layer_grids"]["stroma"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "coordinate/source mismatch"):
                score_masks(self.masks, self.cells, contract)

    def test_rejects_duplicate_missing_or_foreign_classification_ids(self):
        for cells in (self.cells + [self.cells[0]], self.cells[:-1], self.cells + [{"instance_id": 99, "class_name": "Stroma", "probability": .9}]):
            with self.subTest(cells=cells), self.assertRaises(ValueError):
                score_masks(self.masks, cells, self.contract)

    def test_nodal_and_unreviewed_inputs_do_not_receive_primary_breast_proxy(self):
        self.contract.update(specimen_type="axillary_sentinel_node", organ_head="lymph_node", annotation_reviewed=False)
        result = score_masks(self.masks, self.cells, self.contract)
        self.assertIsNone(result["nuclear_area_proxy_percent"])
        self.assertIn("unsupported_or_unconfirmed_specimen", result["no_call_reasons"])
        self.assertIn("missing_reviewed_eligibility_annotation", result["no_call_reasons"])

    def test_no_nuclei_is_not_reported_as_zero(self):
        self.masks["instances"][:] = 0
        result = score_masks(self.masks, [], self.contract)
        self.assertIn("no_assessable_nuclei_detected", result["no_call_reasons"])
        self.assertIsNone(result["nuclear_area_proxy_percent"])

    def test_acceptance_thresholds_are_required(self):
        self.contract["acceptance"].pop("min_coverage_fraction")
        with self.assertRaisesRegex(ValueError, "prespecified acceptance"):
            score_masks(self.masks, self.cells, self.contract)

    def test_cli_verifies_artifact_hashes_and_preserves_existing_outputs(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            artifacts = {}
            for name, mask in self.masks.items():
                path = directory / (name + ".npy")
                np.save(path, mask)
                artifacts[name] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            cells = directory / "cells.json"
            cells.write_text(json.dumps(self.cells))
            artifacts["cells"] = {"path": cells.name, "sha256": hashlib.sha256(cells.read_bytes()).hexdigest()}
            contract = directory / "contract.json"
            contract.write_text(json.dumps(dict(self.contract, artifacts=artifacts)))
            output = directory / "score.json"
            command = [sys.executable, str(root / "scripts/stil_modular_review.py"), "score", "--contract", str(contract), "--out", str(output)]
            env = dict(os.environ, PYTHONPATH=str(root / "src"))
            passed = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["nuclear_area_proxy_percent"], 25)
            original = output.read_bytes()
            repeated = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            cells.write_text("[]")
            command[-1] = str(directory / "tampered-score.json")
            rejected = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("classification hash mismatch", rejected.stderr)
            self.assertFalse((directory / "tampered-score.json").exists())

    def test_review_queue_separates_no_calls_and_nodes_without_new_scores(self):
        rows = [
            {"slide": "breast", "stain": "H&E", "source_sha256": "a" * 64, "candidate_tissue_group": "breast", "mutils_status": "no_call", "mutils_candidate_rois": 10, "mutils_admitted_rois": 0},
            {"slide": "node", "stain": "H&E", "source_sha256": "b" * 64, "candidate_tissue_group": "axillary_sentinel_node"},
            {"slide": "HER2", "stain": "HER2", "source_sha256": "c" * 64},
        ]
        protocol = {"components": {}, "validation": {"required_before_inference": [], "required_before_interpretation": [], "acceptance_thresholds_status": "not_prespecified"}}
        queue, readiness = prepare_review_queue(rows, protocol)
        self.assertEqual(len(queue), 2)
        self.assertIn("native_filter_no_call_recovery", queue[0]["review_reasons"])
        self.assertEqual(readiness["separate_nodal_review_slides"], 1)
        self.assertFalse(readiness["new_models_executed"])
        self.assertTrue(all(row["new_modular_score_percent"] is None for row in queue))


if __name__ == "__main__":
    unittest.main()
