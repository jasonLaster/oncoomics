"""The TIFF MPP adapter must add a description without changing any original byte."""

import struct
import tempfile
import unittest
from pathlib import Path

from diana_omics.tiff_mpp import IMAGE_DESCRIPTION, add_aperio_description, read_ifd0, resolution_mpp


def _tiny_tiff(path, x_res=(21896, 1), unit=3):
    """Little-endian classic TIFF: 2x2 RGB, one strip, resolution in pixels/cm."""
    pixels = bytes(range(12))
    entries = []
    data_offset = 8
    rational_offset = data_offset + len(pixels)
    ifd_offset = rational_offset + 16

    def short(code, value):
        return (code, 3, 1, struct.pack("<HH", value, 0))

    def long(code, value):
        return (code, 4, 1, struct.pack("<I", value))

    entries = [short(256, 2), short(257, 2), short(258, 8), short(259, 1), short(262, 2), long(273, data_offset),
               short(277, 3), long(278, 2), long(279, len(pixels)), (282, 5, 1, struct.pack("<I", rational_offset)),
               (283, 5, 1, struct.pack("<I", rational_offset + 8)), short(296, unit)]
    blob = b"II" + struct.pack("<HI", 42, ifd_offset) + pixels
    blob += struct.pack("<II", *x_res) + struct.pack("<II", *x_res)
    blob += struct.pack("<H", len(entries)) + b"".join(struct.pack("<HHI", c, t, n) + v for c, t, n, v in entries)
    blob += struct.pack("<I", 0)
    Path(path).write_bytes(blob)
    return blob


class TiffMppTests(unittest.TestCase):
    def test_description_added_and_original_bytes_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slide.tif"
            original = _tiny_tiff(path)
            with path.open("rb") as f:
                mpp = resolution_mpp(f)
            self.assertAlmostEqual(mpp[0], 10000 / 21896)
            add_aperio_description(path)
            updated = path.read_bytes()
            self.assertEqual(updated[:4], original[:4])
            self.assertEqual(updated[8:len(original)], original[8:])
            with path.open("rb") as f:
                _, _, offset, entries, next_ifd = read_ifd0(f)
                old = {e[0]: e for e in entries if e[0] != IMAGE_DESCRIPTION}
                desc = [e for e in entries if e[0] == IMAGE_DESCRIPTION][0]
                f.seek(struct.unpack("<I", desc[3])[0])
                text = f.read(desc[2]).rstrip(b"\0").decode()
            self.assertGreaterEqual(offset, len(original))
            self.assertEqual(next_ifd, 0)
            self.assertEqual([e[0] for e in entries], sorted(e[0] for e in entries))
            self.assertEqual(len(old), 12)
            self.assertTrue(text.startswith("Aperio"))
            self.assertIn("|MPP = 0.456704", text)
            with self.assertRaises(ValueError):
                add_aperio_description(path)


if __name__ == "__main__":
    unittest.main()
