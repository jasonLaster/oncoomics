"""Collect an immutable modular research archive from a private Modal volume."""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import modal


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", required=True)
    parser.add_argument("--receipt", required=True, help="Volume-relative archive receipt path")
    parser.add_argument("--out", type=Path, required=True, help="New local directory")
    args = parser.parse_args()
    volume = modal.Volume.from_name(args.volume, create_if_missing=False)
    receipt = json.loads(b"".join(volume.read_file(args.receipt)))
    remote = PurePosixPath(receipt["path"])
    if remote.parts[:2] != ("/", "data"):
        raise ValueError("expected mounted /data archive path")
    args.out.mkdir(parents=True, exist_ok=False)
    archive_path = args.out / "results.zip.part"
    with archive_path.open("wb") as stream:
        for chunk in volume.read_file("/" + str(remote.relative_to("/data"))):
            stream.write(chunk)
    if archive_path.stat().st_size != receipt["bytes"] or digest(archive_path) != receipt["sha256"]:
        raise ValueError("archive checksum or size mismatch; partial download retained")
    archive_path = archive_path.rename(args.out / "results.zip")
    (args.out / "archive_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("bundle_manifest.json"))
        entries = {row["path"]: row for row in manifest["files"]}
        expected = set(entries) | {"bundle_manifest.json"}
        if len(entries) != len(manifest["files"]) or len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
            raise ValueError("archive members differ from manifest")
        for name in archive.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe archive member")
            target = args.out.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            if name in entries and (target.stat().st_size != entries[name]["bytes"] or digest(target) != entries[name]["sha256"]):
                raise ValueError("artifact mismatch: " + name)
    result = {"archive_sha256_verified": receipt["sha256"], "artifacts_verified": len(entries),
              "run_id": manifest["run_id"], "clinical_validation": "not_established"}
    (args.out / "collection_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
