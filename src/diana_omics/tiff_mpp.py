"""Metadata-only TIFF adapter: expose physical pixel size to OpenSlide 3.4.

TIGER slides are generic tiled TIFFs whose resolution tags carry the pixel size,
which OpenSlide 3.4's generic-TIFF reader does not report as `openslide.mpp-x`.
`add_aperio_description` appends a copy of IFD 0 with an Aperio-style
ImageDescription (MPP from the file's own XResolution/YResolution) and points
the header at it. All original bytes, including every tile, are kept unchanged.
"""

import struct

ASCII = 2
IMAGE_DESCRIPTION = 270
X_RESOLUTION, Y_RESOLUTION, RESOLUTION_UNIT = 282, 283, 296
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}


def _header(f):
    f.seek(0)
    head = f.read(16)
    order = {b"II": "<", b"MM": ">"}[head[:2]]
    magic = struct.unpack(order + "H", head[2:4])[0]
    if magic == 42:
        return order, False, struct.unpack(order + "I", head[4:8])[0]
    if magic == 43:
        return order, True, struct.unpack(order + "Q", head[8:16])[0]
    raise ValueError("not a TIFF")


def read_ifd0(f):
    order, big, offset = _header(f)
    f.seek(offset)
    if big:
        n = struct.unpack(order + "Q", f.read(8))[0]
        raw = [f.read(20) for _ in range(n)]
        next_ifd = struct.unpack(order + "Q", f.read(8))[0]
        entries = [(*struct.unpack(order + "HHQ", r[:12]), r[12:]) for r in raw]
    else:
        n = struct.unpack(order + "H", f.read(2))[0]
        raw = [f.read(12) for _ in range(n)]
        next_ifd = struct.unpack(order + "I", f.read(4))[0]
        entries = [(*struct.unpack(order + "HHI", r[:8]), r[8:]) for r in raw]
    return order, big, offset, entries, next_ifd


def _rational(f, order, big, entry):
    code, dtype, count, value = entry
    assert dtype == 5 and count == 1, "resolution must be one RATIONAL"
    if big:  # an 8-byte rational fits in the BigTIFF value field
        num, den = struct.unpack(order + "II", value[:8])
    else:
        f.seek(struct.unpack(order + "I", value[:4])[0])
        num, den = struct.unpack(order + "II", f.read(8))
    return num / den


def resolution_mpp(f):
    order, big, _, entries, _ = read_ifd0(f)
    tags = {e[0]: e for e in entries}
    unit = struct.unpack(order + "H", tags[RESOLUTION_UNIT][3][:2])[0] if RESOLUTION_UNIT in tags else 2
    per_um = {2: 25400.0, 3: 10000.0}[unit]  # inch or centimeter
    return (per_um / _rational(f, order, big, tags[X_RESOLUTION]), per_um / _rational(f, order, big, tags[Y_RESOLUTION]))


def add_aperio_description(path, app_mag=20):
    """Append an ImageDescription-bearing IFD 0 in place. Returns (mpp_x, mpp_y)."""
    with open(path, "r+b") as f:
        order, big, _, entries, next_ifd = read_ifd0(f)
        if any(e[0] == IMAGE_DESCRIPTION for e in entries):
            raise ValueError("IFD 0 already has an ImageDescription")
        mpp_x, mpp_y = resolution_mpp(f)
        if abs(mpp_x - mpp_y) / mpp_x > .01:
            raise ValueError("anisotropic pixels")
        desc = f"Aperio Image Library v0.0.0 (TIGER metadata adapter)\n|AppMag = {app_mag}|MPP = {mpp_x:.6f}".encode() + b"\0"
        f.seek(0, 2)
        if f.tell() % 2:
            f.write(b"\0")
        desc_offset = f.tell()
        f.write(desc)
        if f.tell() % 2:
            f.write(b"\0")
        value_width = 8 if big else 4
        packed = struct.pack(order + ("Q" if big else "I"), desc_offset)
        new = sorted(entries + [(IMAGE_DESCRIPTION, ASCII, len(desc), packed.ljust(value_width, b"\0"))], key=lambda e: e[0])
        ifd_offset = f.tell()
        if big:
            if ifd_offset >= 2 ** 64:
                raise ValueError("offset overflow")
            blob = struct.pack(order + "Q", len(new)) + b"".join(struct.pack(order + "HHQ", c, t, n) + v for c, t, n, v in new)
            blob += struct.pack(order + "Q", next_ifd)
        else:
            if ifd_offset + 2 + 12 * len(new) + 4 >= 2 ** 32:
                raise ValueError("classic TIFF offset overflow; convert to BigTIFF first")
            blob = struct.pack(order + "H", len(new)) + b"".join(struct.pack(order + "HHI", c, t, n) + v for c, t, n, v in new)
            blob += struct.pack(order + "I", next_ifd)
        f.write(blob)
        if big:
            f.seek(8)
            f.write(struct.pack(order + "Q", ifd_offset))
        else:
            f.seek(4)
            f.write(struct.pack(order + "I", ifd_offset))
    return mpp_x, mpp_y
