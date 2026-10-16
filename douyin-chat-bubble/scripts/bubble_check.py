"""Preflight a Douyin bubble manifest and render local nine-slice previews.

Requires Pillow. Does not upload, redraw artwork, or assert platform approval.
Coordinates are source pixels; rectangles use Pillow's right/bottom-exclusive
convention. panel_box describes the main body, excluding protruding ornaments.
"""
import argparse
import json
from pathlib import Path
import sys
from PIL import Image, ImageColor, ImageDraw, ImageFont


def luminance(rgb):
    channels=[v/255 for v in rgb[:3]]
    linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return .2126*linear[0]+.7152*linear[1]+.0722*linear[2]


def contrast(a,b):
    x,y=sorted((luminance(a),luminance(b)))
    return (y+.05)/(x+.05)


def nine_slice(image,cuts,size):
    l,t,r,b=cuts;w,h=image.size;tw,th=size
    if not (0<l<r<w and 0<t<b<h):raise ValueError('Cuts must be inside the source')
    if tw<l+w-r or th<t+h-b:raise ValueError('Target is smaller than its fixed edges')
    sx=[0,l,r,w];sy=[0,t,b,h]
    dx=[0,l,tw-w+r,tw];dy=[0,t,th-h+b,th]
    out=Image.new('RGBA',size)
    for y in range(3):
        for x in range(3):
            piece=image.crop((sx[x],sy[y],sx[x+1],sy[y+1]))
            target=(dx[x+1]-dx[x],dy[y+1]-dy[y])
            if piece.size!=target:piece=piece.resize(target,Image.Resampling.BILINEAR)
            out.paste(piece,(dx[x],dy[y]))
    for sb,db in [((0,0,l,t),(0,0,l,t)),((r,0,w,t),(tw-w+r,0,tw,t)),
                   ((0,b,l,h),(0,th-h+b,l,th)),((r,b,w,h),(tw-w+r,th-h+b,tw,th))]:
        if image.crop(sb).tobytes()!=out.crop(db).tobytes():
            raise AssertionError('A fixed corner changed under stretch')
    return out


def alpha_scan(image,threshold):
    w,h=image.size;a=image.getchannel('A');vertical=[];horizontal=[]
    # These are screenshot-informed sampling checks, not reverse-engineered
    # platform internals. Include neighboring pixels to avoid rounding luck.
    for center in (w//3,2*w//3):
        for x in range(max(0,center-1),min(w,center+2)):
            ys=[y for y in range(h) if a.getpixel((x,y))>=threshold]
            vertical.extend([min(ys),h-1-max(ys)] if ys else [h,h])
    for center in (h//3,2*h//3):
        for y in range(max(0,center-1),min(h,center+2)):
            xs=[x for x in range(w) if a.getpixel((x,y))>=threshold]
            horizontal.extend([min(xs),w-1-max(xs)] if xs else [w,w])
    return {'alpha_threshold':threshold,'vertical_max':max(vertical),
            'horizontal_max':max(horizontal),
            'conservative_local_pass':max(vertical)<=36 and max(horizontal)<=40}


def check_asset(path,art,manifest):
    errors=[];warnings=[]
    with Image.open(path) as original:
        image=original.convert('RGBA');fmt=original.format
    w,h=image.size
    if fmt!='PNG':errors.append('Static delivery must be PNG')
    if w>198 or h>162 or w%3 or h%3:errors.append('Invalid dimensions or divisibility by 3')
    if path.stat().st_size>2_000_000:errors.append('File exceeds conservative 2 MB limit')
    if image.getchannel('A').getextrema()==(255,255):warnings.append('No transparent exterior; inspect whether intended')
    if 'source_size' in manifest and manifest['source_size']!=[w,h]:errors.append('Manifest source_size does not match PNG')
    cuts=manifest['cuts'];cut_tuple=tuple(cuts[k] for k in ('left','top','right','bottom'))
    if not(0<cut_tuple[0]<cut_tuple[2]<w and 0<cut_tuple[1]<cut_tuple[3]<h):
        errors.append('Invalid cut coordinates')
    text=art.get('text_box',manifest['text_box']);x0,y0,x1,y1=text
    valid_text=0<=x0<x1<=w and 0<=y0<y1<=h
    if not valid_text:errors.append('Text box is outside PNG')
    report={'file':str(path),'size':[w,h],'bytes':path.stat().st_size,'text_box':text}
    if valid_text:
        region=image.crop(text)
        if region.getchannel('A').getextrema()[0]<250:errors.append('Text box contains transparent pixels')
        fg=ImageColor.getrgb(art['text_color'])
        rgb=region.convert('RGB')
        pixels=rgb.get_flattened_data() if hasattr(rgb,'get_flattened_data') else rgb.getdata()
        ratios=sorted(contrast(fg,p) for p in pixels)
        report['contrast_min']=round(ratios[0],3)
        report['contrast_p01']=round(ratios[int(len(ratios)*.01)],3)
        if ratios[0]<4.5:errors.append('Text/background minimum sampled contrast is below 4.5:1')
        if y1-y0<manifest.get('font_size',51):errors.append('Text box height is less than font size')
        protected=manifest.get('protected_box')
        if protected:
            px0,py0,px1,py1=protected
            if not (x0<=px0<px1<=x1 and y0<=py0<py1<=y1):errors.append('Protected box is not inside text box')
            if px1-px0<72 or py1-py0<72:warnings.append('Protected area is below the official 72x72 reference')
        panel=art.get('panel_box',manifest.get('panel_bounds'))
        if panel:
            l,t,r,b=panel;stroke=art.get('border_width',0)
            padding=[x0-l-stroke,y0-t-stroke,r-x1-stroke,b-y1-stroke]
            report['declared_inside_padding_LTRB']=padding
            if padding[0]<=24 or padding[2]<=24 or padding[1]<=18 or padding[3]<=18:
                errors.append('Declared inner text padding is insufficient')
    report['alpha_scans']=[alpha_scan(image,threshold) for threshold in (128,255)]
    if not all(s['conservative_local_pass'] for s in report['alpha_scans']):
        warnings.append('Screenshot-informed decoration spacing preflight failed; inspect artwork and runtime result')
    if not errors:
        for target in ((w,h),(w+417,h),(w+417,h+153)):
            nine_slice(image,cut_tuple,target)
        report['fixed_corners_preserved']=True
    report.update(errors=errors,warnings=warnings,local_pass=not errors)
    return report,image


def preview(image,art,manifest,font_path,destination):
    cuts=tuple(manifest['cuts'][k] for k in ('left','top','right','bottom'))
    font=ImageFont.truetype(str(font_path),manifest.get('font_size',51))
    small=ImageFont.truetype(str(font_path),21)
    w,h=image.size
    samples=[('短字','文！',(w,h)),('长句','今晚要不要一起看电影',(w+417,h)),
             ('多行','今晚一起看电影\n看完再去吃点东西\n明天见',(w+417,h+153))]
    row_heights=[size[1]+38 for _,_,size in samples]
    sheet=Image.new('RGB',(1440,sum(row_heights)+75),'#F5F5F7');d=ImageDraw.Draw(sheet)
    text_box=art.get('text_box',manifest['text_box'])
    for bg,xoff in (('#FFFFFF',25),('#1C1C1E',735)):
        d.rounded_rectangle((xoff,25,xoff+680,sheet.height-25),radius=16,fill=bg)
        y=42
        for tag,text,(tw,th) in samples:
            bubble=nine_slice(image,cuts,(tw,th));bd=ImageDraw.Draw(bubble)
            l,t,r,b=text_box;r+=tw-w;b+=th-h
            box=bd.multiline_textbbox((0,0),text,font=font,spacing=15)
            if box[2]-box[0]>r-l or box[3]-box[1]>b-t:
                raise ValueError(f'Sample does not fit text box: {tag}')
            pos=((l+r-box[2]+box[0])/2-box[0],(t+b-box[3]+box[1])/2-box[1])
            bd.multiline_text(pos,text,font=font,fill=art['text_color'],spacing=15,align='center')
            sheet.paste(bubble,(xoff+55,y),bubble)
            d.text((xoff+8,y),tag,font=small,fill='#888888')
            y+=th+38
    sheet.save(destination)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--font',type=Path,help='Chinese TTF/TTC path; enables preview PNGs')
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    result={'verification':'local only; no platform approval implied','assets':[]}
    for art in manifest['artworks']:
        path=args.manifest.parent/art['file']
        report,image=check_asset(path,art,manifest)
        if args.font and report['local_pass']:
            destination=args.out/(art['id']+'_preview.png')
            preview(image,art,manifest,args.font,destination)
            report['preview']=str(destination)
        result['assets'].append(report)
    target=args.out/'preflight.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if all(x['local_pass'] for x in result['assets']) else 1


if __name__=='__main__':sys.exit(main())
