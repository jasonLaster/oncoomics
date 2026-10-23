"""Exploratory ECTIL-TCGA fold-0 pilot on sampled H&E tiles; not clinical sTIL."""
import modal

app = modal.App('diana-stil-ectil-pilot')
volume = modal.Volume.from_name('diana-stil-pilot-20261021', create_if_missing=True)
raw_mount = modal.CloudBucketMount('diana-omics-raw-inputs-172630973301-us-east-1', key_prefix='diana/inbox/2026-10-21-h-and-e-slides/data/', secret=modal.Secret.from_name('onco-omics-use1'), read_only=True)
image = (modal.Image.debian_slim(python_version='3.11')
         .apt_install('libopenslide0', 'git')
         .pip_install('torch==2.5.1', 'torchvision==0.20.1', 'openslide-python==1.4.2',
                      'pillow==11.1.0', 'numpy==2.2.2', 'gdown==5.2.0')
         .run_commands('git clone https://github.com/NKI-AI/ectil.git /opt/ectil && cd /opt/ectil && git checkout da1145bfb413ace55d329b5ed7792d84fd9f53f5'))


@app.function(image=image, gpu='A10G', cpu=4, memory=16384, timeout=1800,
              volumes={'/pilot': volume, '/raw': raw_mount}, region='us-east', max_containers=1)
def run_pilot():
    import csv
    import hashlib
    import importlib.util
    import json
    import time
    import urllib.request
    from pathlib import Path
    import gdown
    import numpy as np
    import openslide
    import torch
    from torch import nn
    from torchvision import models, transforms

    torch.manual_seed(0)
    torch.set_num_threads(4)
    root = Path('/pilot/ectil-b3-5')
    root.mkdir(parents=True, exist_ok=True)
    def digest(path):
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8388608), b''):
                h.update(chunk)
        return h.hexdigest()
    def fetch(url, path):
        if not path.exists():
            urllib.request.urlretrieve(url, str(path)+'.partial')
            Path(str(path)+'.partial').rename(path)
        return digest(path)
    slide_path = root / 'BR B3-5 H&E.svs'
    import shutil
    shutil.copyfile('/raw/BR B3-5 H&E.svs', slide_path)
    sha = digest(slide_path)
    assert sha == 'b258d76a6d2bb0dd250244b67b618134d0b609c3db0bc4e823a873e7545d72e4'
    ckpt = root / 'epoch_065_step_858_weights_only.ckpt'
    csha = fetch('https://files.aiforoncology.nl/ectil/tcga/fold_0/epoch_065_step_858_weights_only.ckpt', ckpt)
    retccl = root / 'retccl_best_ckpt.pth'
    if not retccl.exists():
        gdown.download(id='1Sn0kYwkXp7eqdIPUTFtK_ilz5ThApOsn',output=str(retccl)+'.partial',quiet=False)
        Path(str(retccl)+'.partial').rename(retccl)
    rsha = digest(retccl)
    def load_module(name, filename):
        spec = importlib.util.spec_from_file_location(name, '/opt/ectil/ectil/models/components/'+filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    MeanMIL = load_module('mean_mil', 'mean_mil.py').MeanMIL
    GatedAttention = load_module('attention', 'attention.py').GatedAttention
    model = MeanMIL(post_encoder=nn.Sequential(nn.Identity(),nn.Identity(),nn.Linear(2048,512),nn.ReLU()),
                    classifier=nn.Sequential(nn.Identity(),nn.Identity(),nn.Linear(512,1),nn.Sigmoid()),
                    attention=GatedAttention(in_features=512,hidden_features=128))
    model.load_state_dict({k.removeprefix('net.'):v for k,v in torch.load(ckpt,map_location='cpu',weights_only=True).items()},strict=True)
    encoder = models.resnet50(weights=None)
    encoder.fc = nn.Identity()
    encoder.load_state_dict(torch.load(retccl,map_location='cpu',weights_only=True),strict=True)
    model.eval().cuda()
    encoder.eval().cuda()
    normalizer = transforms.Compose([transforms.ToTensor(),transforms.Normalize((.485,.456,.406),(.229,.224,.225))])
    manifest = dict(status='running',source_sha256=sha,ectil_commit='da1145bfb413ace55d329b5ed7792d84fd9f53f5',
                    checkpoint='ECTIL-TCGA fold_0 epoch_065_step_858',checkpoint_sha256=csha,
                    retccl_sha256=rsha,seed=0,started=time.time(),specimen_timepoint='unresolved',
                    endpoint='uncalibrated ECTIL prediction from sampled tissue tiles',
                    pathologist_score=None,clinical_stil_percent=None,
                    sampling='up to 128 fixed-seed tissue grid tiles; custom thumbnail nonwhite filter; not native DLUP foreground selection',
                    target_mpp=.5,tile_size=512)
    receipt = root/'run_manifest.json'
    receipt.write_text(json.dumps(manifest,indent=2))
    volume.commit()
    with openslide.OpenSlide(str(slide_path)) as slide:
        mpp_x=float(slide.properties['openslide.mpp-x'])
        mpp_y=float(slide.properties['openslide.mpp-y'])
        assert abs(mpp_x-mpp_y)/mpp_x < .01, 'anisotropic source needs explicit resampling'
        side=round(512*.5/mpp_x)
        thumb=slide.get_thumbnail((2048,2048)).convert('RGB')
        a=np.asarray(thumb)
        tissue=(a.min(2)<210) & ((a.max(2).astype(float)-a.min(2))>15)
        sx,sy=thumb.width/slide.dimensions[0],thumb.height/slide.dimensions[1]
        candidates=[]
        for y in range(0,slide.dimensions[1]-side+1,side):
            for x in range(0,slide.dimensions[0]-side+1,side):
                region=tissue[int(y*sy):max(int((y+side)*sy),int(y*sy)+1),int(x*sx):max(int((x+side)*sx),int(x*sx)+1)]
                if region.size and region.mean()>=.5:
                    candidates.append((x,y))
        assert candidates, 'no eligible tiles'
        rng=np.random.default_rng(0)
        chosen=sorted(rng.choice(len(candidates),min(128,len(candidates)),replace=False))
        coords=[candidates[i] for i in chosen]
        features=[]
        with torch.inference_mode():
            for start in range(0,len(coords),16):
                images=[normalizer(slide.read_region((x,y),0,(side,side)).convert('RGB').resize((512,512))) for x,y in coords[start:start+16]]
                features.append(encoder(torch.stack(images).cuda()).cpu())
                print('features',start+len(images),'of',len(coords),flush=True)
            features=torch.cat(features)
            prediction=model(features.unsqueeze(0).cuda())
            score=prediction['out'].item()
        torch.save(features,root/'retccl_features.pt')
        with (root/'tile_coordinates.csv').open('w') as f:
            writer=csv.writer(f);writer.writerow(['x_level0','y_level0','side_level0'])
            writer.writerows((x,y,side) for x,y in coords)
        manifest.update(status='completed_exploratory_sample',finished=time.time(),
                        uncalibrated_model_output_fraction=score,
                        n_candidate_tiles=len(candidates),n_analyzed_tiles=len(coords),
                        candidate_grid_coverage=len(coords)/len(candidates),mpp_x=mpp_x,mpp_y=mpp_y,
                        qc_flags=['pen_marks_visible_on_overview','tumor_boundary_unreviewed','timepoint_unresolved',
                                  'partial_slide','custom_foreground_selection','no_absolute_calibration'])
    receipt.write_text(json.dumps(manifest,indent=2))
    volume.commit()
    return manifest


@app.local_entrypoint()
def main():
    import json
    from pathlib import Path
    result=run_pilot.remote()
    output=Path('results/stil/20261021/ectil-pilot')
    output.mkdir(parents=True,exist_ok=True)
    (output/'run_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
