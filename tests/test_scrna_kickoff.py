import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from diana_omics.scrna_kickoff import (
    file_record,
    find_10x_matrix_dir,
    require_relative_object,
    require_run_id,
    require_sha256,
    safe_extract_tar,
)


class ScrnaKickoffTest(unittest.TestCase):
    def test_identifiers_and_hashes_are_strict(self):
        self.assertEqual(require_run_id("pbmc3k-20260903T220000Z"), "pbmc3k-20260903T220000Z")
        self.assertEqual(require_relative_object("fixture/input.tar.gz"), "fixture/input.tar.gz")
        self.assertEqual(require_sha256("a" * 64), "a" * 64)

        for invalid in ("", "../run", "/absolute", "space is not allowed"):
            with self.subTest(run_id=invalid), self.assertRaises(ValueError):
                require_run_id(invalid)
        for invalid in ("", "../input.tar.gz", "/input.tar.gz", "directory/"):
            with self.subTest(object_key=invalid), self.assertRaises(ValueError):
                require_relative_object(invalid)
        for invalid in ("", "A" * 64, "f" * 63, "not-a-hash"):
            with self.subTest(digest=invalid), self.assertRaises(ValueError):
                require_sha256(invalid)

    def test_safe_extract_finds_legacy_10x_bundle_and_records_hash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "matrix.tar.gz"
            with tarfile.open(archive_path, mode="w:gz") as archive:
                for name, payload in (
                    ("filtered/hg19/matrix.mtx", b"matrix"),
                    ("filtered/hg19/barcodes.tsv", b"barcode"),
                    ("filtered/hg19/genes.tsv", b"gene"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))

            output = root / "output"
            extracted = safe_extract_tar(archive_path, output)
            matrix_dir = find_10x_matrix_dir(extracted)
            record = file_record(matrix_dir / "matrix.mtx", output)

            self.assertEqual(matrix_dir.relative_to(output.resolve()).as_posix(), "filtered/hg19")
            self.assertEqual(record["path"], "filtered/hg19/matrix.mtx")
            self.assertEqual(record["bytes"], 6)
            self.assertEqual(len(record["sha256"]), 64)

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "unsafe.tar"
            with tarfile.open(archive_path, mode="w") as archive:
                payload = b"escape"
                info = tarfile.TarInfo("../escape.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            with self.assertRaisesRegex(ValueError, "escapes the extraction root"):
                safe_extract_tar(archive_path, root / "output")


if __name__ == "__main__":
    unittest.main()
