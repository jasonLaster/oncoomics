"""Resumable, source-bound native MuTILs and ECTIL research batch."""
import modal

app = modal.App('diana-stil-full-20261021')
volume = modal.Volume.from_name('diana-stil-pilot-20261021', create_if_missing=False)
raw = modal.CloudBucketMount(
    'diana-omics-raw-inputs-172630973301-us-east-1',
    key_prefix='diana/inbox/2026-10-21-h-and-e-slides/data/',
    secret=modal.Secret.from_name('onco-omics-use1'), read_only=True)
MUTILS_IMAGE = 'szolgyen/mutils@sha256:01c1a04b603a12ca2621ed8e32ebe22ec36137d0cf2be2bf03c7474053bf64b3'
mutils_image = modal.Image.from_registry(MUTILS_IMAGE, add_python='3.11')
ectil_image = (modal.Image.debian_slim(python_version='3.11')
    .apt_install('libopenslide0', 'libvips-dev', 'git', 'build-essential')
    .pip_install('torch==2.5.1', 'torchvision==0.20.1', 'openslide-python==1.4.2',
                 'pillow==11.1.0', 'numpy==1.26.4', 'scipy==1.14.1',
                 'scikit-image==0.24.0', 'dlup==0.3.23', 'pyvips==2.2.3')
    .run_commands('git clone https://github.com/NKI-AI/ectil.git /opt/ectil && cd /opt/ectil && git checkout da1145bfb413ace55d329b5ed7792d84fd9f53f5'))


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


@app.function(image=mutils_image, volumes={'/pilot':volume}, timeout=300)
def verify_assets(model:str='both'):
    import shutil
    from pathlib import Path
    root=Path('/pilot/models');root.mkdir(exist_ok=True)
    name='mutils_06022021_fold1.pt'
    if not (root/name).exists() and Path('/pilot/mutils-b3-5',name).exists():
        shutil.copyfile(Path('/pilot/mutils-b3-5',name),root/name)
    expected={
        name:'c0386961eb71d6ab1bbedf9623faa6d10a9cf29d036d86df9b917b501162c448',
        'epoch_065_step_858_weights_only.ckpt':'a6fe681c735598b30ac199af9271a93eaf7a2b0861f43cfada2c645bc65f0534',
        'retccl_best_ckpt.pth':'931956f31d3f1a3f6047f3172b9e59ee3460d29f7c0c2bb219cbc8e9207795ff'}
    result={}
    for filename,digest in expected.items():
        if model=='mutils' and filename!=name:continue
        if model=='ectil' and filename==name:continue
        assert (root/filename).is_file(),'model asset not provisioned: '+filename
        actual=sha256(root/filename);assert actual==digest,'model checksum mismatch: '+filename
        result[filename]={'sha256':actual,'bytes':(root/filename).stat().st_size}
    volume.commit();return result


@app.function(image=mutils_image, volumes={'/pilot':volume}, timeout=120)
def inspect_mutils():
    import json
    import subprocess
    from pathlib import Path
    root=Path('/home/MuTILs_Panoptic')
    p=root/'mutils_panoptic/MuTILsWSIRunner.py'
    code=p.read_text()
    result={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'runner_sha256':sha256(p), 'runner_code':code,
            'config_code':(root/'configs/MuTILsWSIRunConfigs.py').read_text(),
            'roi_csv':Path('/pilot/mutils-b3-5/output/perSlideResults/BR B3-5 H&E/BR B3-5 H&E_RoiLocs.csv').read_text()}
    return result


@app.function(image=mutils_image, volumes={'/pilot':volume}, timeout=300)
def diagnose_mutils(run_id:str):
    import csv,json
    from pathlib import Path
    results=[]
    for root in sorted((Path('/pilot')/run_id/'mutils').glob('*')):
        if not root.is_dir():continue
        summaries=list(root.glob('output*/perSlideResults/*/*.json'))
        row={'slide':root.name}
        csvs=list(root.glob('output*/perSlideResults/*/*_RoiLocs.csv'))
        if csvs:
            records=list(csv.DictReader(csvs[-1].open()))
            row.update(candidate_rois=len(records),admitted_rois=sum(int(x['model'])>=0 for x in records))
        if summaries:
            try:row['native_summary']=json.loads(summaries[-1].read_text())
            except json.JSONDecodeError:row['summary_state']='incomplete'
        row['roi_metadata_count']=len(list(root.glob('output*/perSlideResults/*/roiMeta/*.json')))
        if row.get('admitted_rois')==0 and row['roi_metadata_count']==0:
            paths=[p for p in root.rglob('*') if p.is_file() and
                   p.name!='run_manifest.json' and p.suffix in ('.json','.csv','.png','.log')]
            row['diagnostic_artifacts']=[{'path':str(p.relative_to(root)),
                'size':p.stat().st_size,'sha256':sha256(p)} for p in paths]
        results.append(row)
    return results


@app.function(image=mutils_image, gpu='A10G', cpu=4, memory=24576, timeout=7200,
              volumes={'/pilot':volume,'/raw':raw}, region='us-east', max_containers=2)
def run_mutils(row:dict, run_id:str):
    import json, os, subprocess, time, traceback
    from pathlib import Path
    assert row['stain']=='H&E' and Path(row['filename']).name==row['filename']
    root=Path('/pilot')/run_id/'mutils'/Path(row['filename']).stem
    root.mkdir(parents=True,exist_ok=True)
    receipt=root/'run_manifest.json'
    if receipt.exists():
        old=json.loads(receipt.read_text())
        if old.get('status')=='completed' and old['source_sha256']==row['sha256']:
            return old
    manifest={'model':'MuTILs fold1','filename':row['filename'],'status':'running',
              'source_sha256':row['sha256'],'started':time.time(),'clinical_stil_percent':None,
              'pathologist_score':None,'specimen_timepoint':'unresolved','image':MUTILS_IMAGE}
    try:
        slide=Path('/raw')/row['filename']
        assert sha256(slide)==row['sha256'],'source hash mismatch'
        weights=Path('/pilot/models/mutils_06022021_fold1.pt')
        assert sha256(weights)=='c0386961eb71d6ab1bbedf9623faa6d10a9cf29d036d86df9b917b501162c448'
        inputs=Path('/tmp/stil-input')/slide.stem;inputs.mkdir(parents=True,exist_ok=True)
        link=inputs/slide.name
        if not link.exists():link.symlink_to(slide)
        outputs=root/'output';outputs.mkdir(exist_ok=True)
        config=dict(slides_path=str(inputs),base_savedir=str(outputs),
                    model_paths={'mutils_06022021-fold1':str(weights)},
                    topk_rois=None,topk_salient_rois=None,
                    N_preprocesses=1,N_postprocesses=1,independent_tile_assignment=True,
                    save_wsi_mask=True,save_annotations=False,
                    save_nuclei_meta=True,save_nuclei_props=False)
        code_root=Path('/home/MuTILs_Panoptic')
        runner=code_root/'mutils_panoptic/MuTILsWSIRunner.py'
        original=runner.read_text()
        if row.get('roi_shard_start') is not None:
            import csv
            source_rois=Path('/pilot')/row['base_run_id']/'mutils'/slide.stem/'output/perSlideResults'/slide.stem/(slide.stem+'_RoiLocs.csv')
            with source_rois.open() as f:
                reader=csv.DictReader(f);fields=reader.fieldnames;roi_rows=list(reader)
            controls={0,1}
            selected=[int(r['']) for r in roi_rows if int(r['model'])>=0 and
                      ((int(r[''])>=row['roi_shard_start'] and
                        (row.get('roi_shard_end') is None or int(r[''])<row['roi_shard_end'])) or
                       int(r['']) in controls)]
            assert controls.issubset(set(selected))
            destination=outputs/'perSlideResults'/slide.stem/(slide.stem+'_RoiLocs.csv')
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open('w') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
                for r in roi_rows:
                    r['model']='0' if int(r['']) in selected else '-1'
                    writer.writerow(r)
            # Retain the native per-ROI masks for a checked merge. Inference,
            # postprocessing and native summaries are otherwise unchanged.
            cleanup='shutil.rmtree(opj(self._savedir, "roiMasks"))'
            assert original.count(cleanup)==1
            runner.write_text(original.replace(cleanup,'pass  # retain native ROI masks for checked merge'))
            manifest.update(roi_shard_start=row['roi_shard_start'],roi_shard_end=row.get('roi_shard_end'),base_run_id=row['base_run_id'],
                            roi_control_ids=sorted(controls),roi_subset_ids=selected,
                            original_roi_csv_sha256=sha256(source_rois),roi_mask_retention_patch=True)
        # Record both original and effective code, including any artifact-retention change.
        manifest.update(config=config,runner_original_sha256=__import__('hashlib').sha256(original.encode()).hexdigest(),
                        runner_effective_sha256=sha256(runner),model_assignment_patch=False,
                        weights_sha256=sha256(weights),runner_original_code=original)
        if (root/'shard_merge.json').exists():
            provenance=json.loads((root/'shard_merge.json').read_text())
            assert provenance['source_sha256']==row['sha256'] and provenance['controls_passed']
            manifest['roi_merge_provenance']=provenance
        (code_root/'configs/MuTILsWSIRunConfigs.yaml').write_text(json.dumps(config))
        receipt.write_text(json.dumps(manifest,indent=2));volume.commit()
        env=dict(os.environ,PYTHONPATH='/home:/home/MuTILs_Panoptic:/home/MuTILs_Panoptic/histolab/src',
                 OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',PYTHONHASHSEED='0')
        with (root/'inference.log').open('w') as log:
            process=subprocess.Popen(['/home/venv/bin/python',str(runner)],cwd='/home',env=env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.time()+6900
            while process.poll() is None:
                if time.time()>deadline:
                    process.kill();process.wait();raise TimeoutError('MuTILs slide deadline exceeded')
                time.sleep(15)
                volume.commit()
        summaries=[p for p in outputs.rglob('*.json') if p.name==slide.stem+'.json']
        assert process.returncode==0 and len(summaries)==1,'missing native slide summary or failed process'
        summary=json.loads(summaries[0].read_text())
        n=summary['metrics']['weighted_by_rois']['n_rois']
        assert n>0 and not summary.get('error_messages'),'no regions or upstream errors'
        import csv
        roi_path=next(outputs.rglob(slide.stem+'_RoiLocs.csv'))
        roi_rows=list(csv.DictReader(roi_path.open()))
        admitted=sum(int(r['model'])>=0 for r in roi_rows)
        manifest.update(status='completed',native_summary=summary,finished=time.time(),
                        n_analyzed_rois=n,n_candidate_rois=len(roi_rows),n_admitted_rois=admitted,
                        all_admitted_rois_processed=n==admitted,eligible_tumor_coverage='unknown',
                        coverage_definition='all ROIs admitted by native tissue/RAG filters; not all tissue pixels',
                        artifacts=[{'path':str(p.relative_to(root)),'size':p.stat().st_size,'sha256':sha256(p)}
                                   for p in outputs.rglob('*') if p.is_file()])
    except Exception:
        manifest.update(status='failed',error=traceback.format_exc(),finished=time.time())
    receipt.write_text(json.dumps(manifest,indent=2));volume.commit()
    print(row['filename'],manifest['status'],manifest.get('n_analyzed_rois'),flush=True)
    # Source snapshot remains on volume, not repeated through the transport.
    return {k:v for k,v in manifest.items() if k!='runner_original_code'}


@app.function(image=ectil_image,gpu='A10G',cpu=4,memory=16384,timeout=7200,
              volumes={'/pilot':volume,'/raw':raw},region='us-east',max_containers=2)
def run_ectil(row:dict,run_id:str):
    import csv, importlib.util, json, time, traceback
    from pathlib import Path
    import numpy as np
    import torch
    from torch import nn
    from torchvision import models,transforms
    from dlup import SlideImage
    from dlup.data.dataset import TiledROIsSlideImageDataset
    from dlup.tiling import GridOrder,TilingMode
    from PIL import Image
    assert row['stain']=='H&E' and Path(row['filename']).name==row['filename']
    root=Path('/pilot')/run_id/'ectil'/Path(row['filename']).stem
    root.mkdir(parents=True,exist_ok=True);receipt=root/'run_manifest.json'
    if receipt.exists():
        old=json.loads(receipt.read_text())
        if old.get('status')=='completed' and old['source_sha256']==row['sha256']:return old
    manifest={'model':'ECTIL-TCGA fold0','filename':row['filename'],'status':'running',
              'source_sha256':row['sha256'],'started':time.time(),'clinical_stil_percent':None,
              'pathologist_score':None,'specimen_timepoint':'unresolved',
              'code_commit':'da1145bfb413ace55d329b5ed7792d84fd9f53f5',
              'endpoint':'uncalibrated regression prediction over native FESI-admitted tiles'}
    try:
        torch.manual_seed(0);torch.set_num_threads(4)
        ckpt=Path('/pilot/models/epoch_065_step_858_weights_only.ckpt')
        retccl=Path('/pilot/models/retccl_best_ckpt.pth')
        assert sha256(ckpt)=='a6fe681c735598b30ac199af9271a93eaf7a2b0861f43cfada2c645bc65f0534'
        assert sha256(retccl)=='931956f31d3f1a3f6047f3172b9e59ee3460d29f7c0c2bb219cbc8e9207795ff'
        source=Path('/raw')/row['filename'];assert sha256(source)==row['sha256']
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
        prefix='/opt/ectil/ectil/'
        MeanMIL=load('mean_mil',prefix+'models/components/mean_mil.py').MeanMIL
        GatedAttention=load('attention',prefix+'models/components/attention.py').GatedAttention
        background=load('background',prefix+'utils/background.py')
        net=MeanMIL(post_encoder=nn.Sequential(nn.Identity(),nn.Identity(),nn.Linear(2048,512),nn.ReLU()),
                    classifier=nn.Sequential(nn.Identity(),nn.Identity(),nn.Linear(512,1),nn.Sigmoid()),
                    attention=GatedAttention(in_features=512,hidden_features=128))
        net.load_state_dict({k.removeprefix('net.'):v for k,v in torch.load(ckpt,map_location='cpu',weights_only=True).items()},strict=True)
        encoder=models.resnet50(weights=None);encoder.fc=nn.Identity()
        encoder.load_state_dict(torch.load(retccl,map_location='cpu',weights_only=True),strict=True)
        encoder.eval().cuda();net.eval().cuda()
        transform=transforms.Compose([transforms.ToTensor(),transforms.Normalize((.485,.456,.406),(.229,.224,.225))])
        slide=SlideImage.from_file_path(source)
        mask_path=root/'native_fesi_mask.png'
        prior=json.loads(receipt.read_text()) if receipt.exists() else {}
        if mask_path.exists() and prior.get('source_sha256')==row['sha256']:
            mask=(np.asarray(Image.open(mask_path))>0).astype('uint8')
        else:
            mask=background.get_mask(slide,background.AvailableMaskFunctions.fesi)
            Image.fromarray(mask*255).save(mask_path)
        dataset=TiledROIsSlideImageDataset.from_standard_tiling(path=source,mpp=.5,tile_size=(512,512),
                    tile_overlap=(0,0),tile_mode=TilingMode.skip,grid_order=GridOrder.C,crop=False,
                    mask=mask,mask_threshold=.1,limit_bounds=True)
        count=len(dataset);assert count>0,'empty native foreground selection'
        manifest.update(n_admitted_tiles=count,target_mpp=.5,tile_size=512,
                        preprocessing='native ECTIL FESI and DLUP0.3.23 standard tiling, mask threshold 0.1, limit_bounds=True',
                        checkpoint_sha256=sha256(ckpt),retccl_sha256=sha256(retccl),n_completed_tiles=0)
        receipt.write_text(json.dumps(manifest,indent=2));volume.commit()
        feats=[];metadata=[]
        with torch.inference_mode():
            for start in range(0,count,32):
                samples=[dataset[i] for i in range(start,min(start+32,count))]
                images=torch.stack([transform(x['image'].convert('RGB')) for x in samples]).cuda()
                feats.append(encoder(images).cpu())
                for i,sample in enumerate(samples):
                    metadata.append({'tile_index':start+i,**{k:(v.tolist() if hasattr(v,'tolist') else str(v)) for k,v in sample.items() if k!='image'}})
                if start%512==0:
                    manifest['n_completed_tiles']=start+len(samples)
                    receipt.write_text(json.dumps(manifest,indent=2));volume.commit()
                    print(row['filename'],manifest['n_completed_tiles'],'/',count,flush=True)
            features=torch.cat(feats)
            pred=net(features.unsqueeze(0).cuda())
        torch.save(features,root/'retccl_features.pt')
        (root/'tile_metadata.json').write_text(json.dumps(metadata))
        np.savez_compressed(root/'tile_predictions.npz',predictions=pred['meta']['out_per_instance'].cpu().numpy(),
                            attention=pred['meta']['attention_weights'].cpu().numpy())
        manifest.update(status='completed',finished=time.time(),n_completed_tiles=count,
                        uncalibrated_model_output_fraction=pred['out'].item(),
                        analyzed_fraction_of_admitted_tiles=1.,absolute_calibration='not established')
        manifest['artifacts']=[{'path':str(p.relative_to(root)),'size':p.stat().st_size,'sha256':sha256(p)}
                               for p in root.iterdir() if p.is_file() and p!=receipt]
    except Exception:
        manifest.update(status='failed',error=traceback.format_exc(),finished=time.time())
    receipt.write_text(json.dumps(manifest,indent=2));volume.commit()
    print(row['filename'],manifest['status'],flush=True)
    return manifest


@app.local_entrypoint()
def main(mode:str='inspect',run_id:str='full-20261021-v1',model:str='both',first_only:bool=False,skip_first:bool=False,
         only_slide:str='',roi_shard_start:int=-1,roi_shard_end:int=-1,base_run_id:str='full-20261021-v1'):
    import csv,json
    from pathlib import Path
    output=Path('results/stil/20261021')/run_id;output.mkdir(parents=True,exist_ok=True)
    if mode=='inspect':
        result=inspect_mutils.remote()
        (output/'container_inspection.json').write_text(json.dumps(result,indent=2)+'\n')
        print(result['commit'],result['runner_sha256']);return
    if mode=='assets':
        result=verify_assets.remote(model)
        (output/'assets_verified.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result));return
    if mode=='diagnose':
        result=diagnose_mutils.remote(run_id)
        (output/'mutils_diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
        path=output/'mutils_receipts.json'
        if path.exists():
            receipts=json.loads(path.read_text());by_slide={r['slide']:r for r in result}
            for r in receipts:
                diag=by_slide.get(Path(r['filename']).stem,{})
                r['review_diagnostics']=diag
                if r['status']=='failed' and diag.get('admitted_rois')==0 and diag.get('roi_metadata_count')==0:
                    r['execution_status']='native_summary_failed_after_empty_admission'
                    r['status']='no_call'
                    r['no_call_reason']='native_foreground_filter_admitted_no_regions'
                if r['status']=='no_call' and diag.get('diagnostic_artifacts'):
                    r['artifacts']=diag['diagnostic_artifacts']
            path.write_text(json.dumps(receipts,indent=2)+'\n')
        print(json.dumps([{k:v for k,v in r.items() if k!='native_summary'} for r in result]));return
    rows=[dict(r,filename=Path(r['relative_path']).name) for r in csv.DictReader(open('.runs/box-he-20261021/manifest.csv')) if r['stain']=='H&E']
    if first_only:rows=rows[:1]
    elif skip_first:rows=rows[1:]
    if only_slide:rows=[r for r in rows if r['filename']==only_slide]
    assert rows,'no requested H&E slides'
    if roi_shard_start>=0:
        assert model=='mutils' and len(rows)==1 and run_id!=base_run_id
        rows=[dict(r,roi_shard_start=roi_shard_start,roi_shard_end=roi_shard_end if roi_shard_end>=0 else None,base_run_id=base_run_id) for r in rows]
    functions={'mutils':run_mutils,'ectil':run_ectil}
    assets=verify_assets.remote(model)
    (output/'assets_verified.json').write_text(json.dumps(assets,indent=2)+'\n')
    for name in (functions if model=='both' else [model]):
        results=[]
        for result in functions[name].map(rows,[run_id]*len(rows),order_outputs=False):
            receipt_path=output/(name+'_receipts.json')
            existing=json.loads(receipt_path.read_text()) if receipt_path.exists() else []
            merged={x['filename']:x for x in existing}
            merged[result['filename']]=result
            results=list(merged.values())
            receipt_path.write_text(json.dumps(results,indent=2)+'\n')
        print(name,len(results),'terminal results')
