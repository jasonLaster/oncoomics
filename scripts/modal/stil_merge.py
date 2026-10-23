"""Check disjoint native ROI work and prepare the original runner to resume.

This does not compute or average slide scores. The original pinned runner must
reconstruct the final slide summary and mask after the checked merge.
"""
import modal

app=modal.App('diana-stil-roi-custody')
volume=modal.Volume.from_name('diana-stil-pilot-20261021',create_if_missing=False)


@app.function(image=modal.Image.debian_slim(python_version='3.11'),
              volumes={'/pilot':volume},timeout=900,cpu=2,memory=2048)
def audit_or_merge(base_run:str,shard_run:str,filename:str,merge:bool=False):
    import csv,hashlib,json,re,shutil,time
    from pathlib import Path
    assert Path(filename).name==filename
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    def records(root):
        return {json.loads(f.read_text())['roi_id']:f for f in root.glob('roiMeta/*.json')}
    def rid(path):return int(re.search(r'_roi-(\d+)_',path.name).group(1))
    stem=Path(filename).stem
    shard_runs=shard_run.split(',')
    assert len(shard_runs)==len(set(shard_runs)) and base_run not in shard_runs
    roots=[Path('/pilot')/run/'mutils'/stem for run in [base_run]+shard_runs]
    receipts=[json.loads((p/'run_manifest.json').read_text()) for p in roots]
    assert len({r['source_sha256'] for r in receipts})==1
    assert len({r['weights_sha256'] for r in receipts})==1
    outputs=[p/'output/perSlideResults'/stem for p in roots]
    csv_path=outputs[0]/(stem+'_RoiLocs.csv')
    assert all(digest(csv_path)==r['original_roi_csv_sha256'] for r in receipts[1:])
    native={int(r['']):r for r in csv.DictReader(csv_path.open()) if int(r['model'])>=0}
    meta=[records(p) for p in outputs]
    union=set().union(*(set(m) for m in meta))
    helper_assigned=set().union(*(set(r['roi_subset_ids']) for r in receipts[1:]))
    base_exclusive=set(native)-helper_assigned
    assert union.issubset(native),'unexpected ROI identity'
    controls_passed=all(set(r['roi_control_ids']).issubset(set(meta[0])&set(m))
                        for r,m in zip(receipts[1:],meta[1:]))
    checked=[]
    for roi in sorted(union):
        present=[i for i,m in enumerate(meta) if roi in m]
        if len(present)<2:continue
        for subdir in ('roiMeta','roiMasks','nucleiMeta'):
            files=[list((outputs[i]/subdir).glob(f'*_roi-{roi}_*')) for i in present]
            assert all(len(f)==1 for f in files),'overlap artifact not fully written'
            assert len({f[0].name for f in files})==1 and len({digest(f[0]) for f in files})==1,'overlap differs: '+str(roi)+' '+subdir
        checked.append(roi)
    result={'source_sha256':receipts[0]['source_sha256'],'weights_sha256':receipts[0]['weights_sha256'],
            'original_roi_csv_sha256':digest(csv_path),'expected_rois':len(native),
            'base_processed':len(meta[0]),'shard_processed':[len(m) for m in meta[1:]],'union_processed':len(union),
            'base_exclusive_remaining':len(base_exclusive-set(meta[0])),
            'missing_roi_ids':sorted(set(native)-union),'controls_passed':controls_passed,
            'byte_identical_overlap_ids':checked,'base_run':base_run,'shard_runs':shard_runs,
            'shard_statuses':[r['status'] for r in receipts[1:]],'timestamp_utc':time.time()}
    if not merge:return result
    assert all(r['status']=='completed' for r in receipts[1:]) and controls_passed
    assert union==set(native),'cannot merge an incomplete ROI union'
    assert not (outputs[0]/(stem+'.tif')).exists(),'original mask already exists; inspect before merging'
    copies=[]
    # Preflight every copy before changing the original output tree.
    queued={}
    for output in outputs[1:]:
        for subdir in ('roiMeta','roiMasks','nucleiMeta'):
            for source in sorted((output/subdir).glob('*')):
                if not source.is_file():continue
                roi=rid(source);assert roi in native
                destination=outputs[0]/subdir/source.name
                if destination.exists():assert digest(destination)==digest(source),'existing artifact differs'
                elif destination in queued:assert digest(queued[destination])==digest(source)
                else:queued[destination]=source
    copies=[(source,destination) for destination,source in queued.items()]
    for source,destination in copies:
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_name(destination.name+'.part')
        shutil.copyfile(source,temporary)
        assert digest(source)==digest(temporary)
        temporary.replace(destination)
    assert set(records(outputs[0]))==set(native)
    if (roots[0]/'inference.log').exists():
        shutil.copyfile(roots[0]/'inference.log',roots[0]/'inference-first-pass.log')
    result.update(merge_status='prepared_for_native_resume',copied_artifacts=len(copies),
                  aggregation='not performed here; original native runner must resume')
    (roots[0]/'shard_merge.json').write_text(json.dumps(result,indent=2)+'\n')
    volume.commit()
    return result


@app.local_entrypoint()
def main(base_run:str='full-20261021-v1',shard_run:str='full-20261021-v1-f2-upper,full-20261021-v1-f2-tail',
         filename:str='BR F2-3 H&E_135434.svs',merge:bool=False):
    import json
    from pathlib import Path
    result=audit_or_merge.remote(base_run,shard_run,filename,merge)
    destination=Path('results/stil/20261021')/base_run
    destination.mkdir(parents=True,exist_ok=True)
    (destination/('shard_merge.json' if merge else 'shard_audit.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('missing_roi_ids','byte_identical_overlap_ids')}))
