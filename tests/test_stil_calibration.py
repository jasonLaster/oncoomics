"""Known-answer tests for the monotone endpoint mappings."""

import math
import unittest

from diana_omics.stil_calibration import cross_fit, fit_isotonic, fit_log_logit, predict


class LogLogitTests(unittest.TestCase):
    def test_recovers_exact_relationship(self):
        a, b, c = -3.0, 0.8, 10.0
        x = [5, 20, 80, 300, 1000, 3000]
        r = [100 / (1 + math.exp(-(a + b * math.log(v + c)))) for v in x]
        m = fit_log_logit(x, r, offset=c)
        self.assertAlmostEqual(m["a"], a, places=6)
        self.assertAlmostEqual(m["b"], b, places=6)
        for p, q in zip(predict(m, x), r):
            self.assertAlmostEqual(p, q, places=6)

    def test_negative_slope_is_clamped_to_constant(self):
        m = fit_log_logit([1, 10, 100], [50, 20, 5], offset=0.01)
        self.assertEqual(m["b"], 0.0)
        preds = predict(m, [1, 1000])
        self.assertAlmostEqual(preds[0], preds[1])


class IsotonicTests(unittest.TestCase):
    def test_pools_violators_and_interpolates(self):
        m = fit_isotonic([1, 2, 3, 4], [10, 30, 20, 40])
        self.assertEqual(predict(m, [1, 2, 3, 4]), [10, 25, 25, 40])
        self.assertEqual(predict(m, [0, 3.5, 9]), [10, 32.5, 40])

    def test_ties_are_averaged(self):
        m = fit_isotonic([1, 1, 2], [0, 10, 20])
        self.assertEqual(predict(m, [1, 2]), [5, 20])


class CrossFitTests(unittest.TestCase):
    def test_each_prediction_excludes_its_own_fold(self):
        ids = ["a", "b", "c", "d"]
        x = [1, 2, 3, 4]
        r = [0, 0, 100, 100]
        folds = [0, 1, 0, 1]
        oof, fitted = cross_fit(ids, x, r, folds, "isotonic")
        # Fold 0 holds a and c; it is predicted from b (x=2, r=0) and d (x=4, r=100).
        self.assertEqual(oof["a"], 0)
        self.assertEqual(oof["c"], 50)
        self.assertEqual(sorted(fitted), [0, 1])


if __name__ == "__main__":
    unittest.main()
