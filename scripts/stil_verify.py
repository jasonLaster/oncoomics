"""Independent result-custody and aggregation checks, not clinical validation."""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--manifest',type=Path,default=Path('.runs/box-he-20261021/manifest.csv'))
    p.add_argument('--require-terminal',action='store_true')
    args=p.parse_args()
    inputs=list(csv.DictReader(args.manifest.open()))
    pins=json.loads((args.run/'models.lock.json').read_text())
    inspected=json.loads((args.run/'container_inspection.json').read_text())
    he={Path(r['relative_path']).name:r for r in inputs if r['stain']=='H&E'}
    checks=[]
    for model in ['mutils','ectil']:
        rows=json.loads((args.run/(model+'_receipts.json')).read_text())
        names=[r['filename'] for r in rows]
        assert len(names)==len(set(names)),'duplicate slide receipts'
        if args.require_terminal:assert set(names)==set(he),'missing or non-H&E slide receipt'
        for r in rows:
            assert r['filename'] in he and r['source_sha256']==he[r['filename']]['sha256']
            assert r.get('clinical_stil_percent') is None and r.get('pathologist_score') is None
            entry={'model':model,'slide':r['filename'],'execution_status':r['status'],
                   'source_binding':'pass','clinical_claim':'not_assigned'}
            root=args.run/model/Path(r['filename']).stem
            if r['status']=='no_call':
                assert r.get('no_call_reason'),'unexplained no-call'
                diag=r['review_diagnostics']
                assert diag['admitted_rois']==diag['roi_metadata_count']==0
                csvs=list(root.rglob('*_RoiLocs.csv'));assert len(csvs)==1
                rois=list(csv.DictReader(csvs[0].open()))
                assert len(rois)==diag['candidate_rois']>0
                assert all(int(row['model'])<0 for row in rois)
                assert not list(root.rglob('roiMeta/*.json'))
                entry['no_call_reason']=r['no_call_reason']
                entry['empty_native_admission']='independently_confirmed'
            elif r['status']=='completed' and model=='mutils':
                assert r['image']==pins['MuTILs']['image']
                assert r['weights_sha256']==pins['MuTILs']['fold1_sha256']
                assert r['runner_original_sha256']==r['runner_effective_sha256']==inspected['runner_sha256']
                s=r['native_summary'];assert s['meta']['slide_name']==Path(r['filename']).stem
                assert not s.get('error_messages')
                meta=[json.loads(f.read_text()) for f in root.rglob('roiMeta/*.json')]
                assert len(meta)==r['n_analyzed_rois']>0,'ROI artifact count mismatch'
                csvs=list(root.rglob('*_RoiLocs.csv'));assert len(csvs)==1
                native_rois={int(row['']):row for row in csv.DictReader(csvs[0].open()) if int(row['model'])>=0}
                assert {m['roi_id'] for m in meta}==set(native_rois),'admitted/processed ROI identity mismatch'
                for m in meta:
                    assert m['slide_name']==Path(r['filename']).stem
                    coords=native_rois[m['roi_id']]
                    for key,native in [('wsi_left','xmin'),('wsi_top','ymin'),('wsi_right','xmax'),('wsi_bottom','ymax')]:
                        assert m[key]==int(coords[native]),'ROI/source coordinate mismatch'
                numerator=sum(m['region_summary']['pixelCount_TILS'] for m in meta)
                denominator=sum(m['region_summary']['pixelCount_STROMA']+m['region_summary']['pixelCount_TILS'] for m in meta)
                assert denominator>0,'no stromal denominator'
                expected=numerator/denominator
                actual=s['metrics']['unweighted_global']['TILs2AnyStromaRatio']
                assert math.isclose(expected,actual,rel_tol=1e-9,abs_tol=1e-12),'ROI/global aggregation mismatch'
                entry.update(aggregation='pass',roi_count=len(meta),native_til_region_percent=actual*100)
            elif r['status']=='completed':
                assert r['code_commit']==pins['ECTIL']['code_commit']
                assert r['checkpoint_sha256']==pins['ECTIL']['checkpoint_sha256']
                assert r['retccl_sha256']==pins['ECTIL']['retccl_sha256']
                assert r['n_completed_tiles']==r['n_admitted_tiles']>0
                tiles=json.loads((root/'tile_metadata.json').read_text())
                assert len(tiles)==r['n_completed_tiles']
                assert [x['tile_index'] for x in tiles]==list(range(len(tiles)))
                arrays=np.load(root/'tile_predictions.npz')
                pred=arrays['predictions'];attention=arrays['attention']
                assert pred.shape==attention.shape and pred.size==len(tiles)
                assert np.isfinite(pred).all() and np.isfinite(attention).all()
                assert (pred>=0).all() and (pred<=1).all() and (attention>=0).all()
                assert math.isclose(float(attention.sum()),1.,abs_tol=1e-5)
                reconstructed=float((pred*attention).sum())
                assert math.isclose(reconstructed,r['uncalibrated_model_output_fraction'],abs_tol=1e-6)
                entry.update(aggregation='pass',tile_count=len(tiles),uncalibrated_prediction_percent=reconstructed*100)
            else:
                if args.require_terminal:raise AssertionError('unresolved execution failure: '+r['filename'])
                entry['aggregation']='not_checked'
            checks.append(entry)
    result={'evidence_level':'mechanical_and_custody_checks_only',
            'evidence_classification':'internal_qc',
            'validation_verdict':'validated_for_narrower_claim',
            'validated_claim':'source-bound saved outputs with independently reconstructed native aggregations',
            'clinical_validation':'not_established','model_results_checked':len(checks),
            'expected_model_dispositions':2*len(he),
            'all_expected_dispositions_present':len(checks)==2*len(he),
            'strict_terminal_check_required':args.require_terminal,'checks':checks}
    (args.run/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'}))


if __name__=='__main__':main()
