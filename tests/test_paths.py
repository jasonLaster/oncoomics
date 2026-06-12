import importlib
import os
import tempfile
import unittest
from pathlib import Path


class PathsTest(unittest.TestCase):
    def test_root_can_be_overridden_from_environment(self):
        from diana_omics import paths

        original_root = paths.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.environ["DIANA_OMICS_ROOT"] = tmp
                importlib.reload(paths)
                self.assertEqual(paths.ROOT, Path(tmp).resolve())
                self.assertEqual(paths.path_from_root("results/example.json"), Path(tmp).resolve() / "results/example.json")
            finally:
                os.environ.pop("DIANA_OMICS_ROOT", None)
                importlib.reload(paths)
                self.assertEqual(paths.ROOT, original_root)


if __name__ == "__main__":
    unittest.main()
