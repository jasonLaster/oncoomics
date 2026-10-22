"""Known-answer tests for the TIGER sTIL benchmark split and metric arithmetic."""

import json
import math
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

from diana_omics.stil_benchmark import (
    agreement,
    bland_altman,
    bootstrap_ci,
    categorical,
    icc_absolute_single,
    lins_ccc,
    make_split,
    match_points,
    per_band,
    pitfall_flags,
    pooled_detection,
    roi_source,
    score_band,
    select_component_rois,
    slide_source,
    spearman,
    tissue_component_dice,
)

SPLIT = Path(__file__).resolve().parents[1] / "manifests/stil_tiger_benchmark_split.json"


def _rows():
    rows = []
    for i, score in enumerate([0, 1, 3, 5, 7, 10, 15, 20, 35, 40, 60, 70, 80, 95] * 3):
        rows.append({"image-id": f"{100 + i}{'S' if i % 2 else 'B'}" if i % 3 else f"TC_S01_P{i:06d}_C0001_B101",
                     "tils-score": str(score), "comment": ""})
    return rows


class SplitTests(unittest.TestCase):
    def test_bands_and_sources(self):
        self.assertEqual([score_band(v) for v in (0, 4, 4.5, 5, 9, 10, 29, 30, 59, 60, 95)],
                         ["0-4", "0-4", "0-4", "5-9", "5-9", "10-29", "10-29", "30-59", "30-59", "60+", "60+"])
        self.assertEqual(slide_source("104S"), "numeric_SB")
        self.assertEqual(slide_source("TC_S01_P000004_C0001_B103"), "TC")
        with self.assertRaises(ValueError):
            slide_source("TCGA-A1-A0SK")
        self.assertEqual(pitfall_flags("many immune cells surrounding DCIS"), ["dcis"])
        self.assertIn("necrosis", pitfall_flags("immune cells around fatnecrosis = pitfall"))

    def test_split_is_deterministic_stratified_and_exact(self):
        rows = _rows()
        a = make_split(rows, seed=7, n_dev=20, n_folds=5)
        b = make_split(list(reversed(rows)), seed=7, n_dev=20, n_folds=5)
        self.assertEqual(a, b)
        dev = [s for s in a["slides"] if s["split"] == "development"]
        self.assertEqual(len(dev), 20)
        self.assertTrue(all(s["dev_fold"] is None for s in a["slides"] if s["split"] == "locked_test"))
        for stratum in a["strata"]:
            self.assertLessEqual(abs(stratum["development"] - stratum["n"] * 20 / len(rows)), 1)
        sizes = [sum(s["dev_fold"] == f for s in dev) for f in range(5)]
        self.assertEqual(sizes, [4] * 5)
        self.assertNotEqual(a, make_split(rows, seed=8, n_dev=20, n_folds=5))

    def test_committed_split_is_frozen_and_complete(self):
        split = json.loads(SPLIT.read_text())
        self.assertEqual(split["seed"], 20261022)
        self.assertEqual(len(split["slides"]), 82)
        counts = {k: sum(s["split"] == k for s in split["slides"]) for k in ("development", "locked_test")}
        self.assertEqual(counts, {"development": 40, "locked_test": 42})
        self.assertEqual(sorted({s["dev_fold"] for s in split["slides"] if s["split"] == "development"}), list(range(5)))
        self.assertNotIn("tils-score", json.dumps(split))


class AgreementTests(unittest.TestCase):
    def test_perfect_agreement(self):
        x = [0, 5, 10, 30, 60, 90]
        out = agreement(x, x)
        self.assertEqual(out["mae_pp"], 0)
        self.assertAlmostEqual(out["lins_ccc"], 1)
        self.assertAlmostEqual(out["icc_a1"], 1)
        self.assertAlmostEqual(out["spearman"], 1)
        self.assertEqual([c["accuracy"] for c in out["categorical"]], [1, 1])

    def test_constant_offset_penalizes_agreement_not_correlation(self):
        x = [0, 10, 20, 30, 40]
        y = [v + 10 for v in x]
        self.assertAlmostEqual(spearman(x, y), 1)
        # CCC = 2*var / (2*var + bias^2) with population var 200, bias 10.
        self.assertAlmostEqual(lins_ccc(x, y), 400 / 500)
        ba = bland_altman(x, y)
        self.assertAlmostEqual(ba["bias"], 10)
        self.assertAlmostEqual(ba["sd_diff"], 0)

    def test_icc_matches_shrout_fleiss_reference(self):
        # Two raters; ICC(A,1) computed independently from ANOVA mean squares:
        # SSR=11.125, SSC=1.125, SSE=0.125 -> MSR=11.125/3, MSC=1.125, MSE=0.125/3;
        # ICC = (MSR-MSE) / (MSR + MSE + 2*(MSC-MSE)/4) = 3.666667/4.291667
        x = [1, 2, 3, 4]
        y = [1.5, 3.0, 3.5, 5.0]
        msr, msc, mse = 11.125 / 3, 1.125, 0.125 / 3
        self.assertAlmostEqual(icc_absolute_single(x, y), (msr - mse) / (msr + mse + 2 * (msc - mse) / 4))
        self.assertAlmostEqual(icc_absolute_single(x, y), 0.854369, places=6)

    def test_categorical_kappa(self):
        out = categorical([0, 0, 50, 50], [0, 50, 50, 0], 30)
        self.assertEqual((out["tp"], out["tn"], out["fp"], out["fn"]), (1, 1, 1, 1))
        self.assertAlmostEqual(out["cohen_kappa"], 0)

    def test_bootstrap_and_bands(self):
        x = [0, 2, 5, 8, 12, 25, 40, 70]
        y = [1, 2, 7, 6, 15, 20, 30, 50]
        lo, hi = bootstrap_ci(x, y, lambda a, b: sum(abs(p - q) for p, q in zip(a, b)) / len(a), reps=200, seed=1)
        mae = agreement(x, y)["mae_pp"]
        self.assertLessEqual(lo, mae)
        self.assertGreaterEqual(hi, mae)
        bands = {b["band"]: b for b in per_band([{"reference": a, "prediction": b} for a, b in zip(x, y)])}
        self.assertEqual(bands["60+"]["bias"], -20)
        self.assertEqual(bands["0-4"]["n"], 2)


class ComponentTests(unittest.TestCase):
    @unittest.skipIf(np is None, "numpy required")
    def test_dice_ignores_unannotated_pixels(self):
        ref = np.array([[2, 2, 1, 0], [6, 1, 1, 0]])
        pred = np.array([[2, 2, 2, 2], [2, 1, 1, 2]])
        out = tissue_component_dice(pred, ref)
        self.assertEqual(out["annotated_pixels"], 6)
        # Stroma: ref {(0,0),(0,1),(1,0)}; pred in valid {(0,0),(0,1),(0,2),(1,0)} -> 2*3/(3+4)
        self.assertAlmostEqual(out["stroma"]["dice"], 6 / 7)
        self.assertAlmostEqual(out["tumor"]["dice"], 2 * 2 / (2 + 3))

    def test_point_matching_is_one_to_one(self):
        ref = [(0, 0), (10, 0)]
        pred = [(1, 0), (2, 0), (30, 30)]
        out = match_points(pred, ref, max_distance=4)
        self.assertEqual((out["tp"], out["fp"], out["fn"]), (1, 2, 1))
        pooled = pooled_detection([out, match_points([], [(0, 0)], 4)])
        self.assertEqual((pooled["tp"], pooled["fn"]), (1, 2))
        self.assertTrue(math.isclose(pooled["recall"], 1 / 3))


class RoiSelectionTests(unittest.TestCase):
    def test_selection_keeps_all_rumc_jb_and_samples_tcga(self):
        names = ["./images/TCGA-A1-A0SK-01Z_[1, 2, 3, 4].png"] * 5 + ["./images/TC_S01_P000001_C0001_B101_[0, 0, 9, 9].png",
                                                                      "./images/100B_[0, 0, 9, 9].png"]
        coco = {"images": [{"id": i, "file_name": n, "width": 10, "height": 10} for i, n in enumerate(names)],
                "annotations": [{"image_id": 5, "bbox": [2, 2, 16, 16]}]}
        rois = select_component_rois(coco, seed=1, n_tcga=2)
        self.assertEqual([r["source"] for r in rois].count("TCGA"), 2)
        self.assertEqual({r["source"] for r in rois}, {"TCGA", "RUMC", "JB"})
        self.assertEqual([r for r in rois if r["image_id"] == 5][0]["box_centers"], [[10, 10]])
        self.assertEqual(rois, select_component_rois(coco, seed=1, n_tcga=2))
        self.assertEqual(roi_source("228B_[1, 2, 3, 4].png"), "JB")


if __name__ == "__main__":
    unittest.main()
