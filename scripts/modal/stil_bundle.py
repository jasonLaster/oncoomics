"""Collect an immutable completed-slide review bundle with per-file hashes."""
import modal

app=modal.App('diana-stil-review-collection')
volume=modal.Volume.from_name('diana-stil-pilot-20261021',create_if_missing=False)


@app.function(image=modal.Image.debian_slim(python_version='3.11'),
              volumes={'/pilot':volume},cpu=2,memory=4096,timeout=600)
def bundle(run_id:str,model:str,filename:str):
    import hashlib,json,re,tarfile
    from pathlib import Path
    assert model in ('mutils','ectil') and Path(filename).name==filename
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    root=Path('/pilot')/run_id/model/Path(filename).stem
    receipt=json.loads((root/'run_manifest.json').read_text())
    assert receipt['status']=='completed'
    selected=[]
    for a in receipt['artifacts']:
        relative=Path(a['path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        if any(p in relative.parts for p in ('LOGS','nucleiMeta','nucleiProps')):continue
        if relative.suffix not in ('.json','.png','.csv','.npz','.tif'):continue
        source=root/relative
        assert source.stat().st_size==a['size'] and digest(source)==a['sha256']
        selected.append((source,{'path':str(Path(model)/Path(filename).stem/relative),
                                 'sha256':a['sha256'],'size':a['size']}))
    slug=re.sub('[^a-zA-Z0-9]+','-',Path(filename).stem).strip('-')
    destination=Path('/pilot/exports')/run_id/(model+'-'+slug+'.tar')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(destination,'w') as archive:
        for source,a in selected:archive.add(source,arcname=a['path'],recursive=False)
    result={'filename':filename,'model':model,'source_sha256':receipt['source_sha256'],
            'remote_archive':str(destination.relative_to('/pilot')),
            'archive_sha256':digest(destination),'archive_size':destination.stat().st_size,
            'members':[a for _,a in selected]}
    destination.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
    volume.commit();return result


@app.local_entrypoint()
def main(run_id:str='full-20261021-v1',model:str='mutils',filename:str='BR F2-3 H&E_135434.svs'):
    import hashlib,json,shutil,subprocess,tarfile
    from pathlib import Path
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    root=Path('results/stil/20261021')/run_id
    receipt=next(r for r in json.loads((root/(model+'_receipts.json')).read_text()) if r['filename']==filename)
    assert receipt['status']=='completed'
    result=bundle.remote(run_id,model,filename)
    assert result['source_sha256']==receipt['source_sha256']
    cache=Path('.runs/stil-20261021/bundles')/Path(result['remote_archive']).name
    cache.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['modal','volume','get','--force','diana-stil-pilot-20261021',
                    '/'+result['remote_archive'],str(cache)],check=True)
    assert cache.stat().st_size==result['archive_size'] and digest(cache)==result['archive_sha256']
    indexed={a['path']:a for a in result['members']}
    expected={str(Path(model)/Path(filename).stem/a['path']):a for a in receipt['artifacts']}
    assert set(indexed).issubset(expected)
    with tarfile.open(cache) as archive:
        members=archive.getmembers()
        assert len(members)==len(indexed) and {m.name for m in members}==set(indexed)
        for member in members:
            assert member.isfile() and not member.issym() and not member.islnk()
            relative=Path(member.name)
            assert not relative.is_absolute() and '..' not in relative.parts
            spec=indexed[member.name];original=expected[member.name]
            assert spec['sha256']==original['sha256'] and member.size==spec['size']==original['size']
            destination=root/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name(destination.name+'.part')
            with archive.extractfile(member) as source,temporary.open('wb') as target:
                shutil.copyfileobj(source,target)
            assert digest(temporary)==original['sha256']
            temporary.replace(destination)
    (root/model/Path(filename).stem/'run_manifest.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (root/(model+'-'+Path(filename).stem+'-collection_bundle.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'filename':filename,'verified_bundle_members':len(indexed),
                      'archive_bytes':result['archive_size']}))
