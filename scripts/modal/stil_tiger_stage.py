"""Stage public TIGER benchmark inputs onto a private Modal volume.

Copies only development-split wsitils slides (images + tissue masks), the score
file, license and the wsirois tissue-cells ROI annotations. Locked-test slides are
refused until a frozen pipeline is ready to be scored once.

  modal run scripts/modal/stil_tiger_stage.py --part wsitils-dev
  modal run scripts/modal/stil_tiger_stage.py --part rois
"""

import json
from pathlib import Path

import modal

BUCKET = "tiger-training"
app = modal.App("diana-stil-tiger-stage")
volume = modal.Volume.from_name("diana-stil-tiger-benchmark", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.11").pip_install("boto3==1.35.36")
SPLIT = Path(__file__).resolve().parents[2] / "manifests/stil_tiger_benchmark_split.json" if modal.is_local() else None


def _client():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    return boto3.client("s3", region_name="us-west-2", config=Config(signature_version=UNSIGNED, retries={"max_attempts": 10}))


@app.function(image=image, timeout=300)
def list_keys(prefix: str):
    s3 = _client()
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        out.extend({"key": o["Key"], "size": o["Size"]} for o in page.get("Contents", []))
    return out


@app.function(image=image, volumes={"/tiger": volume}, timeout=3600, cpu=2, memory=4096,
              region="us-west", max_containers=16)
def copy_batch(items: list):
    import hashlib
    s3 = _client()
    records = []
    for item in items:
        dest = Path("/tiger/source") / item["key"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not (dest.exists() and dest.stat().st_size == item["size"]):
            partial = dest.with_name(dest.name + ".partial")
            s3.download_file(BUCKET, item["key"], str(partial))
            partial.rename(dest)
        h = hashlib.sha256()
        with dest.open("rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(chunk)
        size = dest.stat().st_size
        if size != item["size"]:
            raise ValueError("size mismatch for " + item["key"])
        records.append({"key": item["key"], "size": size, "sha256": h.hexdigest()})
    volume.commit()
    return records


@app.function(image=image, volumes={"/tiger": volume}, timeout=300)
def write_manifest(name: str, records: list):
    path = Path("/tiger/manifests") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2) + "\n")
    volume.commit()
    return str(path)


@app.local_entrypoint()
def main(part: str = "wsitils-dev", out: str = "private/stil/benchmark-20261022/staging"):
    split = json.loads(SPLIT.read_text())
    dev = sorted(s["image_id"] for s in split["slides"] if s["split"] == "development")
    locked = {s["image_id"] for s in split["slides"] if s["split"] == "locked_test"}
    assert len(dev) == 40 and len(locked) == 42
    if part == "wsitils-dev":
        listing = {o["key"]: o for o in list_keys.remote("wsitils/")}
        wanted = ["wsitils/tiger-til-scores-wsitils.csv"]
        for image_id in dev:
            wanted += [f"wsitils/images/{image_id}.tif", f"wsitils/tissue-masks/{image_id}_tissue.tif"]
        items = [listing[k] for k in wanted]
        items += [o for o in list_keys.remote("license.txt") + list_keys.remote("data-structure.txt")]
        for item in items:
            stem = Path(item["key"]).stem.removesuffix("_tissue")
            assert stem not in locked, "refusing to stage a locked-test slide: " + item["key"]
        batches = [[i] for i in items]
        name = "wsitils_development.json"
    elif part == "rois":
        items = list_keys.remote("wsirois/roi-level-annotations/tissue-cells/")
        batches = [items[i:i + 100] for i in range(0, len(items), 100)]
        name = "wsirois_tissue_cells.json"
    else:
        raise SystemExit("unknown part " + part)
    records = []
    for result in copy_batch.map(batches, order_outputs=False):
        records.extend(result)
        print(len(records), "/", len(items), flush=True)
    records.sort(key=lambda r: r["key"])
    write_manifest.remote(name, records)
    local = Path(out)
    local.mkdir(parents=True, exist_ok=True)
    (local / name).write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"part": part, "files": len(records), "bytes": sum(r["size"] for r in records)}))
