"""Retrieve review artifacts from completed Modal receipts and verify their hashes."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--model',choices=['mutils','ectil'],required=True)
    p.add_argument('--volume',default='diana-stil-pilot-20261021')
    p.add_argument('--include-masks',action='store_true')
    p.add_argument('--slide',action='append',help='Collect only the named slide; repeat for multiple slides.')
    args=p.parse_args();receipts=json.loads((args.run/(args.model+'_receipts.json')).read_text())
    verified=[];mutable_logs=[]
    for result in receipts:
        if args.slide and result['filename'] not in args.slide:continue
        if result['status'] not in ('completed','no_call'):continue
        name=Path(result['filename']).stem
        root=args.run/args.model/name;root.mkdir(parents=True,exist_ok=True)
        (root/'run_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
        for artifact in result['artifacts']:
            relative=Path(artifact['path'])
            assert not relative.is_absolute() and '..' not in relative.parts
            if 'LOGS' in relative.parts:
                # Upstream cumulative logs can be reused by later invocations
                # in a warm container. They are diagnostics, not frozen results.
                mutable_logs.append({'slide':result['filename'],'path':str(relative)})
                continue
            if relative.suffix not in ['.png','.csv','.json','.npz','.log'] and not (args.include_masks and relative.suffix=='.tif'):
                continue
            # Nucleus CSVs are retained on the volume; retrieve representative
            # review data and all ROI summaries rather than thousands of files.
            if 'nucleiMeta' in relative.parts or 'nucleiProps' in relative.parts:continue
            dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists() or sha256(dest)!=artifact['sha256']:
                remote='/'+args.run.name+'/'+args.model+'/'+name+'/'+relative.as_posix()
                temporary=dest.with_name(dest.name+'.part')
                subprocess.run(['modal','volume','get','--force',args.volume,remote,str(temporary)],check=True,stdout=subprocess.DEVNULL)
                assert temporary.stat().st_size==artifact['size'] and sha256(temporary)==artifact['sha256']
                temporary.replace(dest)
            assert dest.stat().st_size==artifact['size'] and sha256(dest)==artifact['sha256']
            verified.append({'slide':result['filename'],'path':str(dest),'sha256':artifact['sha256']})
        print('verified review artifacts',name,flush=True)
    (args.run/(args.model+'_download_verification.json')).write_text(json.dumps(verified,indent=2)+'\n')
    (args.run/(args.model+'_collection_policy.json')).write_text(json.dumps({
        'scope':'immutable review artifacts; remote full feature and cell records retained',
        'excluded_mutable_upstream_logs':mutable_logs,
        'verified_local_artifacts':len(verified)},indent=2)+'\n')


if __name__=='__main__':main()
