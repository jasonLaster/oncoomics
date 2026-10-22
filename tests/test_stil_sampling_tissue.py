"""Synthetic known-answer tests for artifact-aware sampling, multi-class labels and QC gates."""

import unittest

try:
    import numpy as np
    import PIL  # noqa: F401
    import scipy  # noqa: F401
except ImportError:
    np = None

if np is not None:
    from diana_omics import stil_sampling as sampling
    from diana_omics import stil_tissue as tissue

GLASS, PINK, PURPLE, BLUE_INK, GREEN_INK, BLACK_INK = (
    (250, 250, 250), (225, 160, 200), (110, 80, 160), (80, 120, 220), (60, 160, 120), (40, 40, 45))


@unittest.skipIf(np is None, "install numpy, scipy and pillow for sampling tests")
class SamplingTests(unittest.TestCase):
    def slide(self):
        """A 200x200 map at 8 um/pixel: tissue block, a fat lobule, a blue ink stroke on glass."""
        rgb = np.full((200, 200, 3), GLASS, np.uint8)
        rgb[40:160, 20:120] = PINK
        rgb[60:100, 30:60] = GLASS  # fat lumen inside tissue
        rgb[120:140, 40:80] = PURPLE  # lymphoid aggregate, must stay tissue
        rgb[30:170, 150:156] = BLUE_INK  # handwriting off tissue
        return rgb

    def test_marker_rule_separates_ink_from_hematoxylin(self):
        pixels = np.array([[BLUE_INK, GREEN_INK, BLACK_INK, PURPLE, PINK, GLASS]], np.uint8)
        self.assertEqual(sampling.ink_pixels(pixels).tolist(), [[True, True, True, False, False, False]])

    def test_class_map_marks_ink_fat_and_keeps_lymphoid_tissue(self):
        classes = sampling.class_map(self.slide(), 8.)
        self.assertEqual(classes[100, 153], sampling.CLASS_INK)
        self.assertEqual(classes[100, 145], sampling.CLASS_INK)  # dilation margin around handwriting
        self.assertEqual(classes[80, 45], sampling.CLASS_WHITE)
        self.assertEqual(classes[130, 60], sampling.CLASS_TISSUE)
        self.assertEqual(classes[5, 5], sampling.CLASS_BACKGROUND)

    def test_external_mask_can_only_veto_tissue(self):
        rgb = self.slide()
        external = np.zeros((200, 200), bool)
        external[:, :70] = True
        classes = sampling.class_map(rgb, 8., external)
        self.assertEqual(classes[130, 100], sampling.CLASS_BACKGROUND)
        self.assertEqual(classes[130, 60], sampling.CLASS_TISSUE)
        with self.assertRaises(ValueError):
            sampling.class_map(rgb, 8., external[:10])

    def test_grid_excludes_ink_fat_and_off_tissue(self):
        classes = sampling.class_map(self.slide(), 8.)
        # Downsample 16: one 1024-pixel cell is a 64-pixel map block; halo 64 -> 4 map pixels.
        rows = sampling.grid_candidates(classes, 16, (3200, 3200), tile=320, halo=16)
        reasons = {tuple(r["origin_level0_xy"]): r["exclusion_reasons"] for r in rows}
        self.assertEqual(reasons[(1600, 1920)], [])  # inside pink tissue, row 120-140
        self.assertIn("ink", reasons[(2240, 1600)])
        self.assertIn("fat_or_white", reasons[(640, 960)])
        self.assertTrue(all(not r["eligible"] for r in rows if r["ink_fraction_halo"] > 0))

    def test_roi_polygon_restricts_cells(self):
        classes = sampling.class_map(self.slide(), 8.)
        polygons = sampling.load_roi_polygons({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[1280, 1600], [1920, 1600], [1920, 2560], [1280, 2560], [1280, 1600]]]}}]})
        roi = sampling.polygon_mask(polygons, classes.shape, 16)
        rows = sampling.grid_candidates(classes, 16, (3200, 3200), tile=320, halo=16, roi=roi)
        eligible = [tuple(r["origin_level0_xy"]) for r in rows if r["eligible"]]
        self.assertTrue(eligible)
        self.assertTrue(all(1280 <= x < 1920 and 1600 <= y < 2560 for x, y in eligible))
        self.assertTrue(any("outside_roi" in r["exclusion_reasons"] for r in rows))

    def test_roi_rejects_holes_and_unknown_documents(self):
        with self.assertRaises(ValueError):
            sampling.load_roi_polygons({"type": "Polygon", "coordinates": [[[0, 0], [9, 0], [9, 9]], [[1, 1], [2, 1], [2, 2]]]})
        with self.assertRaises(ValueError):
            sampling.load_roi_polygons({"type": "Point", "coordinates": [0, 0]})
        self.assertEqual(sampling.load_roi_polygons({"polygons": [[[0, 0], [1, 0], [1, 1]]]}), [[[0, 0], [1, 0], [1, 1]]])

    def test_selection_modes(self):
        cells = [{"origin_level0_xy": [x * 1024, y * 1024], "eligible": (x + y) % 5 != 0}
                 for x in range(10) for y in range(10)]
        eligible = [c for c in cells if c["eligible"]]
        self.assertEqual(len(sampling.select(cells, "exhaustive")), len(eligible))
        spread = sampling.select(cells, "spread", 12)
        self.assertEqual(len(spread), 12)
        self.assertEqual(spread, sampling.select(cells, "spread", 12))  # deterministic
        dense = sampling.select(cells, "dense", stride=2)
        self.assertTrue(all((c["origin_level0_xy"][0] // 1024) % 2 == 0 and (c["origin_level0_xy"][1] // 1024) % 2 == 0 for c in dense))
        self.assertTrue(all(c["eligible"] for c in dense))
        with self.assertRaises(ValueError):
            sampling.select(cells, "random")

    def test_tile_pixel_qc_flags_ink_and_fat(self):
        tile = np.full((160, 160, 3), PINK, np.uint8)
        self.assertFalse(sampling.tile_pixel_qc(tile, 16)["ink_tile"])
        tile[10:30, 10:30] = BLUE_INK  # 1.6% of the halo tile; threshold 0.5%
        self.assertTrue(sampling.tile_pixel_qc(tile, 16)["ink_tile"])
        hazy_fat = np.full((160, 160, 3), (228, 224, 232), np.uint8)
        qc = sampling.tile_pixel_qc(hazy_fat, 16)
        self.assertTrue(qc["off_tissue_tile"])
        self.assertGreater(qc["core_lumen_fraction"], .8)


@unittest.skipIf(np is None, "install numpy for tissue-label tests")
class TissueTests(unittest.TestCase):
    def probabilities(self, shape=(4, 4)):
        return {name: np.zeros(shape, np.float32) for name in tissue.LABELS.values() if name != "artifact"}

    def test_argmax_with_background_glass_and_artifact(self):
        p = self.probabilities()
        p["stroma"][:, :2] = .6
        p["immune_infiltrate"][:, 2] = .7
        p["tumor"][:, 3] = .4
        p["background"][:, 3] = .4  # exact tie -> background (earlier class)
        glass = np.zeros((4, 4), bool)
        glass[0, 0] = True
        artifact = np.zeros((4, 4), bool)
        artifact[3, 0] = True
        labels = tissue.label_map(p, glass, artifact)
        self.assertEqual(labels[1].tolist(), [tissue.STROMA, tissue.STROMA, tissue.IMMUNE, tissue.BACKGROUND])
        self.assertEqual(labels[0, 0], tissue.BACKGROUND)
        self.assertEqual(labels[3, 0], tissue.ARTIFACT)
        p["fat"][0, 0] = np.nan
        with self.assertRaises(ValueError):
            tissue.label_map(p)

    def test_assessable_stroma_includes_immune_infiltrate(self):
        labels = np.array([[tissue.STROMA, tissue.IMMUNE, tissue.TUMOR, tissue.FAT],
                           [tissue.STROMA, tissue.IMMUNE, tissue.NECROSIS, tissue.ARTIFACT]], np.uint8)
        instances = np.array([[0, 1, 2, 0], [0, 1, 2, 3]], np.int32)
        cells = [{"instance_id": 1, "class_name": "Lymphocyte"}, {"instance_id": 2, "class_name": "Lymphocyte"},
                 {"instance_id": 3, "class_name": "tumor"}]
        m = tissue.tile_metrics(labels, instances, cells)
        self.assertEqual(m["assessable_stroma_pixels"], 4)
        self.assertEqual(m["tissue_pixels"], 7)
        self.assertEqual(m["immune_nuclear_pixels_in_assessable"], 2)
        self.assertEqual((m["immune_nuclei"], m["immune_nuclei_in_assessable"], m["tumor_nuclei"]), (2, 1, 1))
        with self.assertRaises(ValueError):
            tissue.tile_metrics(labels, instances, cells[:2])

    def test_aggregate_sums_before_dividing_and_gates(self):
        tiles = [
            {"label_pixels": {n: 0 for n in tissue.LABELS.values()} | {"tumor": 10}, "tissue_pixels": 100,
             "assessable_stroma_pixels": 80, "immune_nuclear_pixels_in_assessable": 8, "immune_nuclei": 10,
             "immune_nuclei_in_assessable": 9, "tumor_nuclei": 1, "classified_nuclei": 20, "nuclei": 20},
            {"label_pixels": {n: 0 for n in tissue.LABELS.values()}, "tissue_pixels": 100,
             "assessable_stroma_pixels": 20, "immune_nuclear_pixels_in_assessable": 0, "immune_nuclei": 0,
             "immune_nuclei_in_assessable": 0, "tumor_nuclei": 1, "classified_nuclei": 20, "nuclei": 21},
        ]
        s = tissue.aggregate(tiles, .25)
        self.assertAlmostEqual(s["assessable_stroma_immune_nuclear_area_percent"], 8.)
        self.assertAlmostEqual(s["immune_in_assessable_fraction"], .9)
        self.assertAlmostEqual(s["tumor_mask_fraction"], .05)
        self.assertAlmostEqual(s["tumor_nucleus_fraction"], .05)
        gates = tissue.evaluate_gates(s, "breast", [])
        self.assertTrue(gates["pass"])
        self.assertTrue(tissue.evaluate_gates(s, "breast", ["t1"])["c_ink_and_off_tissue_tiles"]["flag"])
        low = dict(s, immune_in_assessable_fraction=.6)
        self.assertTrue(tissue.evaluate_gates(low, "breast_margin", [])["a_immune_in_assessable_stroma"]["flag"])
        self.assertFalse(tissue.evaluate_gates(low, "axillary_sentinel_node", [])["a_immune_in_assessable_stroma"]["flag"])
        self.assertTrue(tissue.evaluate_gates(dict(s, tumor_mask_fraction=.6), "breast", [])["b_tumor_mask_vs_nuclei"]["flag"])
        self.assertTrue(tissue.evaluate_gates(dict(s, tumor_mask_fraction=.2), "breast", [])["b_tumor_mask_vs_nuclei"]["flag"])
        self.assertFalse(tissue.tumor_disagreement(.02, .001))
        self.assertTrue(tissue.evaluate_gates(dict(s, tumor_nucleus_fraction=None), "breast", [])["b_tumor_mask_vs_nuclei"]["flag"])


if __name__ == "__main__":
    unittest.main()
