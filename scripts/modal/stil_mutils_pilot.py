"""Bounded exploratory MuTILs pilot; immutable upstream image and weights revision."""
import modal

app = modal.App('diana-stil-mutils-pilot')
volume = modal.Volume.from_name('diana-stil-pilot-20261021', create_if_missing=True)
raw_mount = modal.CloudBucketMount('diana-omics-raw-inputs-172630973301-us-east-1', key_prefix='diana/inbox/2026-10-21-h-and-e-slides/data/', secret=modal.Secret.from_name('onco-omics-use1'), read_only=True)
image = modal.Image.from_registry(
    'szolgyen/mutils@sha256:01c1a04b603a12ca2621ed8e32ebe22ec36137d0cf2be2bf03c7474053bf64b3',
    add_python='3.11',
)


@app.function(image=image, gpu='A10G', cpu=4, memory=16384, timeout=2400,
              volumes={'/pilot': volume, '/raw': raw_mount}, region='us-east', max_containers=1)
def run_pilot():
    import hashlib
    import json
    import os
    import subprocess
    import time
    import urllib.request
    from pathlib import Path

    root = Path('/pilot/mutils-b3-5')
    root.mkdir(parents=True, exist_ok=True)
    inputs = root / 'input'
    inputs.mkdir(exist_ok=True)
    outputs = root / 'output'
    outputs.mkdir(exist_ok=True)
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
    slide = inputs / 'BR B3-5 H&E.svs'
    import shutil
    shutil.copyfile('/raw/BR B3-5 H&E.svs', slide)
    sha = digest(slide)
    assert sha == 'b258d76a6d2bb0dd250244b67b618134d0b609c3db0bc4e823a873e7545d72e4'
    weights = root / 'mutils_06022021_fold1.pt'
    wsha = fetch('https://huggingface.co/mutils-panoptic/mutils/resolve/60730e8baba6ba5adf2f3db84e55c0edbd5c1d12/mutils_06022021_fold1.pt', weights)
    config = dict(slides_path=str(inputs), base_savedir=str(outputs),
                  model_paths={'mutils_06022021-fold1': str(weights)},
                  topk_rois=16, topk_salient_rois=4, topk_rois_sampling_mode='stratified',
                  N_preprocesses=1, N_postprocesses=1, independent_tile_assignment=False,
                  save_wsi_mask=True, save_annotations=False,
                  save_nuclei_meta=True, save_nuclei_props=True)
    # JSON is valid YAML. The image's code and config are pinned by its digest.
    config_path = Path('/home/MuTILs_Panoptic/configs/MuTILsWSIRunConfigs.yaml')
    config_path.write_text(json.dumps(config, indent=2))
    code_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd='/home/MuTILs_Panoptic',text=True).strip()
    manifest = dict(status='running', source_sha256=sha, weights_sha256=wsha,
                    weights_revision='60730e8baba6ba5adf2f3db84e55c0edbd5c1d12',
                    image='szolgyen/mutils@sha256:01c1a04b603a12ca2621ed8e32ebe22ec36137d0cf2be2bf03c7474053bf64b3',
                    container_code_commit=code_commit, config=config, started=time.time(),
                    interpretation='exploratory partial-slide model outputs; no pathologist sTIL reference',
                    specimen_timepoint='unresolved', pathologist_score=None)
    receipt = root / 'run_manifest.json'
    receipt.write_text(json.dumps(manifest, indent=2))
    volume.commit()
    env = dict(os.environ, PYTHONPATH='/home:/home/MuTILs_Panoptic:/home/MuTILs_Panoptic/histolab/src',
               OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', PYTHONHASHSEED='0')
    with (root / 'inference.log').open('w') as log:
        result = subprocess.run(['/home/venv/bin/python','/home/MuTILs_Panoptic/mutils_panoptic/MuTILsWSIRunner.py'],
                                cwd='/home',env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
    files = [dict(path=str(p.relative_to(root)),size=p.stat().st_size,sha256=digest(p))
             for p in outputs.rglob('*') if p.is_file()]
    manifest.update(status='process_finished' if result.returncode == 0 else 'failed',
                    returncode=result.returncode,finished=time.time(),artifacts=files)
    receipt.write_text(json.dumps(manifest,indent=2))
    volume.commit()
    print((root / 'inference.log').read_text()[-12000:])
    return manifest


@app.local_entrypoint()
def main():
    import json
    from pathlib import Path
    result = run_pilot.remote()
    output = Path('results/stil/20261021/mutils-pilot')
    output.mkdir(parents=True, exist_ok=True)
    (output/'run_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
