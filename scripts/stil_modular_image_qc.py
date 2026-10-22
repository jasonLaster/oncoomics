"""Flag possible blue annotation artifacts for review without changing model results."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def inspect(inputs, run=None):
    source = json.loads((inputs / "tile_manifest.json").read_text())
    summaries = {}
    if run:
        bundle = json.loads((run / "bundle_manifest.json").read_text())
        for key in bundle["slide_keys"]:
            manifest = json.loads((run / key / "classification_manifest.json").read_text())
            summaries.update({t["tile_id"]: t for t in manifest["tiles"]})
        keys = set(bundle["slide_keys"])
    else:
        keys = {slide["slide_key"] for slide in source["slides"]}
    results = []
    for tile in source["tiles"]:
        if tile["slide_key"] not in keys:
            continue
        path = inputs / tile["image_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != tile["image_sha256"]:
            raise ValueError("input hash mismatch: " + tile["tile_id"])
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
        halo = tile["halo_pixels"]
        core = rgb[halo:halo+1024, halo:halo+1024]
        if core.shape != (1024, 1024, 3):
            raise ValueError("unexpected core shape")
        red, green, blue = core.transpose(2, 0, 1)
        fraction = float(((blue-red > 60) & (blue-green > 40) & (blue > 120)).mean())
        summary = summaries.get(tile["tile_id"], {})
        results.append({"tile_id": tile["tile_id"], "slide_key": tile["slide_key"],
                        "blue_marker_candidate_fraction": fraction,
                        "blue_marker_candidate": fraction >= .05,
                        "detected_nuclei": summary.get("classified_nuclei"),
                        "native_included": summary.get("included_in_exploratory_aggregate"),
                        "competition_included": summary.get("competition", {}).get("included_in_exploratory_aggregate")})
    flagged = [r for r in results if r["blue_marker_candidate"]]
    return {"evidence_classification": "internal_qc", "status": "image_review_required",
            "rule": "core fraction with B-R>60, B-G>40, B>120 is >=0.05; RGB on 0..255 scale",
            "rule_status": "post-run diagnostic inspired by visual artifact review; not validated artifact segmentation",
            "raw_results_changed": False, "automatic_exclusion_performed": False,
            "qc_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "tiles_checked": len(results), "blue_marker_candidate_tiles": len(flagged),
            "flagged_tiles_in_native_ratio": sum(r["native_included"] is True for r in flagged) if run else None,
            "flagged_tiles_in_competition_ratio": sum(r["competition_included"] is True for r in flagged) if run else None,
            "clinical_stil_percent": None, "tiles": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--run", type=Path, help="Optional collected run to join call status; omit for pre-inference image review")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.inputs, args.run)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "tiles"}, indent=2))


if __name__ == "__main__":
    main()
