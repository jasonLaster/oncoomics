"""Read-only SVS custody/technical QC; never derives clinical sTIL scores."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import openslide
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--slides', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records, thumbnails = [], []
    for row in csv.DictReader(args.manifest.open()):
        path = args.slides / Path(row['relative_path']).name
        rec = dict(row, specimen_timepoint='unresolved', pathologist_score=None)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        rec['local_sha256'] = digest.hexdigest()
        rec['custody_pass'] = digest.hexdigest() == row['sha256'] and path.stat().st_size == int(row['size_bytes'])
        rec['he_eligible_by_manifest'] = row['stain'] == 'H&E'
        rec['scoring_status'] = 'not_run' if rec['he_eligible_by_manifest'] else 'excluded_non_he'
        try:
            with openslide.OpenSlide(str(path)) as slide:
                rec.update(dimensions=slide.dimensions, level_dimensions=slide.level_dimensions,
                           mpp_x=slide.properties.get('openslide.mpp-x'),
                           mpp_y=slide.properties.get('openslide.mpp-y'),
                           vendor=slide.properties.get('openslide.vendor'),
                           objective_power=slide.properties.get('openslide.objective-power'))
                # Tissue pyramid only. Never read label or macro associated images.
                thumbnail = slide.get_thumbnail((768, 768)).convert('RGB')
                pixels = np.asarray(thumbnail)
                rec['thumbnail_nonwhite_fraction'] = float((pixels.min(2) < 220).mean())
                rec['technical_read_status'] = 'passed'
                if rec['he_eligible_by_manifest']:
                    name = path.stem.replace(' ', '_').replace('&', 'and')
                    thumbnail.save(args.output / (name + '.png'))
                    cell = Image.new('RGB', (400, 440), 'white')
                    thumbnail.thumbnail((400, 400))
                    cell.paste(thumbnail, (0, 32))
                    ImageDraw.Draw(cell).text((8, 8), path.stem, fill='black')
                    thumbnails.append(cell)
        except Exception as exc:
            rec['technical_read_status'] = 'failed'
            rec['error'] = str(exc)
        records.append(rec)
        print(json.dumps({k:rec.get(k) for k in ['relative_path','custody_pass','he_eligible_by_manifest','dimensions','technical_read_status']}), flush=True)
    (args.output / 'input_qc.json').write_text(json.dumps(records, indent=2)+'\n')
    gallery = Image.new('RGB', (1600, 440*((len(thumbnails)+3)//4)), 'white')
    for i, thumbnail in enumerate(thumbnails):
        gallery.paste(thumbnail, ((i%4)*400, (i//4)*440))
    gallery.save(args.output / 'he_contact_sheet.png')


if __name__ == '__main__':
    main()
