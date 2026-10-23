"""Render source-aligned research review images without reading slide labels/macros."""
import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np
import openslide
import tifffile
import zarr
from PIL import Image,ImageDraw


REGION_COLORS=np.array([[255,255,255],[225,65,65],[75,165,80],[40,80,230],
                       [190,140,105],[230,180,30],[130,35,35],[130,130,130],[255,255,255]],dtype=np.uint8)
NUCLEUS_COLORS=np.array([[255,255,255],[225,65,65],[75,165,80],[220,145,30],
                        [40,80,230],[30,180,210],[190,140,105],[130,130,130],[165,80,180],[255,255,255]],dtype=np.uint8)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--slides',type=Path,default=Path('/Users/jasonlaster/Downloads'))
    args=p.parse_args();out=args.run/'review_images';out.mkdir(exist_ok=True)
    index=[]
    for model in ('mutils','ectil'):
        path=args.run/(model+'_receipts.json')
        if not path.exists():continue
        for receipt in json.loads(path.read_text()):
            if receipt['status']!='completed':continue
            filename=receipt['filename'];stem=Path(filename).stem
            root=args.run/model/stem
            slug=re.sub('[^a-zA-Z0-9]+','-',stem).strip('-')
            with openslide.OpenSlide(str(args.slides/filename)) as slide:
                if model=='ectil':
                    f=root/'native_fesi_mask.png'
                    if not f.exists():continue
                    mask=Image.open(f).convert('L');mask.thumbnail((1500,1500),Image.Resampling.NEAREST)
                    source=slide.get_thumbnail(mask.size).convert('RGB').resize(mask.size)
                    rgb=np.asarray(source,dtype=float);region=np.asarray(mask)>0
                    rgb[region]=rgb[region]*.7+np.array([225,65,65])*.3
                    overlay=Image.fromarray(rgb.astype('uint8'))
                    canvas=Image.new('RGB',(source.width,source.height+55),'white')
                    canvas.paste(overlay,(0,55));d=ImageDraw.Draw(canvas)
                    d.text((10,8),filename+' | Native ECTIL foreground admission',fill='black')
                    d.text((10,27),'Red overlay is foreground, not tumor or eligible stroma. Clinical sTIL has not been assigned.',fill='black')
                    dest=out/(slug+'-ectil-foreground.png');canvas.save(dest)
                    index.append({'slide':filename,'image':str(dest.relative_to(args.run)),'source_sha256':receipt['source_sha256']})
                else:
                    masks=list(root.rglob('*.tif'));csvs=list(root.rglob('*_RoiLocs.csv'))
                    if not masks or not csvs:continue
                    rois={int(r['']):r for r in csv.DictReader(csvs[0].open())}
                    metas=[]
                    metadata_files=list(root.rglob('roiMeta/*.json'))
                    if len(metadata_files)!=receipt['n_analyzed_rois']:
                        print('review panel pending complete artifact collection:',filename,flush=True)
                        (out/(slug+'-mutils-examples.png')).unlink(missing_ok=True)
                        continue
                    for f in metadata_files:
                        doc=json.loads(f.read_text())
                        match=re.search(r'_roi-(\d+)_',f.name)
                        if match:metas.append((int(match[1]),doc['metrics']['TILs2AnyStromaRatio']))
                    if not metas:continue
                    if len(metas)!=receipt['n_analyzed_rois']:
                        print('review panel pending complete artifact collection:',filename,flush=True)
                        (out/(slug+'-mutils-examples.png')).unlink(missing_ok=True)
                        continue
                    metas.sort(key=lambda x:x[1]);chosen=[metas[i] for i in sorted(set([0,len(metas)//2,len(metas)-1]))]
                    canvas=Image.new('RGB',(1200,455*len(chosen)+90),'white');d=ImageDraw.Draw(canvas)
                    d.text((10,8),filename+' | Three example regions ordered by native TIL-region ratio',fill='black')
                    d.text((10,27),'Research predictions only. Region/cell colors use separate class definitions.',fill='black')
                    d.text((10,46),'Tissue: predicted tumor red; stroma green; TIL-rich regions blue; normal brown; junk yellow; white/excluded white.',fill='black')
                    d.text((10,65),'Nuclei: tumor red; stromal green/orange; TIL blue; active-TIL class cyan; ambiguous purple; background white.',fill='black')
                    with tifffile.TiffFile(masks[0]) as t:
                        a=zarr.open(t.aszarr(series=0,level=0),mode='r')
                        sf=float(receipt['native_summary']['meta']['base_mpp'])/.5
                        for i,(rid,value) in enumerate(chosen):
                            r=rois[rid];x,y=int(r['xmin']),int(r['ymin']);w,h=int(r['xmax'])-x,int(r['ymax'])-y
                            rgb=slide.read_region((x,y),0,(w,h)).convert('RGB').resize((1024,1024))
                            xx,yy=int(x*sf),int(y*sf);mask=np.asarray(a[yy:yy+1024,xx:xx+1024,:])
                            imgs=[rgb,Image.fromarray(REGION_COLORS[mask[...,0]]),Image.fromarray(NUCLEUS_COLORS[mask[...,1]])]
                            d.text((10,90+i*455),f'ROI {rid}: native TIL-region/stroma ratio {value*100:.3f}% | Source H&E / tissue predictions / nucleus predictions',fill='black')
                            for j,img in enumerate(imgs):
                                img=img.resize((390,390),Image.Resampling.LANCZOS if j==0 else Image.Resampling.NEAREST)
                                canvas.paste(img,(j*400,120+i*455))
                    dest=out/(slug+'-mutils-examples.png');canvas.save(dest)
                    index.append({'slide':filename,'image':str(dest.relative_to(args.run)),'source_sha256':receipt['source_sha256']})
    (out/'index.json').write_text(json.dumps(index,indent=2)+'\n')
    print('rendered',len(index),'review images')


if __name__=='__main__':main()
