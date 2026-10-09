#!/usr/bin/env python3
"""Public, one-shot LTX 2.3 Distilled 8s image-to-audio-video probe. No tokens, no user imagery."""
import json, pathlib, time, os, io, ssl, sys, struct, zlib, urllib.request, urllib.error, subprocess, math, wave
from urllib.parse import urlparse

BASE = 'https://lightricks-ltx-2-3.hf.space'
OUT = pathlib.Path('ltx23probe'); OUT.mkdir(exist_ok=True)
REPORT = {'engine':'LTX 2.3 Distilled','source':'synthetic image','requested_duration_s':8,'sound_required':True,'state':'not_started','timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

def persist(): (OUT/'probe.json').write_text(json.dumps(REPORT,indent=2,ensure_ascii=False))

def fetch(req, timeout=40):
    try: return urllib.request.urlopen(req,timeout=timeout)
    except urllib.error.HTTPError as e:
        body=e.read(2048).decode('utf8','replace')
        raise RuntimeError(f'HTTP_{e.code}: {body[:260]}') from e

def make_png(path):
    # Generated artwork only; no real person's image is uploaded.
    w,h=960,544; scan=[]
    for y in range(h):
        data=bytearray()
        for x in range(w):
            cx,cy=270,330
            in_ball=(x-cx)**2+(y-cy)**2<=85**2
            if in_ball: rgb=(239,110,36)
            elif y>385: rgb=(111,148,113)
            elif y>330: rgb=(180,192,160)
            else: rgb=(121+min(80,y//8),177+min(40,y//16),212)
            data.extend(rgb)
        scan.append(b'\x00'+bytes(data))
    def block(tag, data): return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+block(b'IHDR',struct.pack('>2I5B',w,h,8,2,0,0,0))+block(b'IDAT',zlib.compress(b''.join(scan),9))+block(b'IEND',b'')
    path.write_bytes(png)

def gradio_upload(path):
    boundary='----KolboProbeBoundary20261009'
    content=path.read_bytes()
    payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="probe.png"\r\nContent-Type: image/png\r\n\r\n').encode()+content+(f'\r\n--{boundary}--\r\n').encode()
    req=urllib.request.Request(BASE+'/gradio_api/upload',data=payload,method='POST',headers={'Content-Type':f'multipart/form-data; boundary={boundary}','User-Agent':'KolboCloudProbe/1.0'})
    with fetch(req,60) as r:
        a=json.load(r)
        if not isinstance(a,list) or not a or not isinstance(a[0],str) or not a[0].startswith('/'): raise ValueError('Gradio upload returned unexpected structure')
        return {'path':a[0],'orig_name':'probe.png','mime_type':'image/png','meta':{'_type':'gradio.FileData'}}

def find_video(obj):
    if isinstance(obj,dict):
        for k in ('url','video_url'):
            u=obj.get(k)
            if isinstance(u,str) and u.startswith('https:') and '.hf.space/' in u:return u
        for v in obj.values():
            got=find_video(v)
            if got:return got
    if isinstance(obj,list):
        for o in obj:
            got=find_video(o)
            if got:return got
    return None

def sse(url):
    req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'KolboCloudProbe/1.0'})
    with fetch(req,650) as r:
        event=''; lines=[]; count=0
        while True:
            raw=r.readline()
            if not raw:break
            line=raw.decode('utf8','replace').rstrip('\r\n')
            if line.startswith('event:'):event=line[6:].strip()
            elif line.startswith('data:'):lines.append(line[5:].strip())
            elif not line:
                content='\n'.join(lines);lines=[]
                if event=='error':raise RuntimeError('SSE_ERROR '+content[:400])
                if event=='complete':
                    data=json.loads(content)
                    url=find_video(data)
                    if not url: raise RuntimeError('SSE_COMPLETE_MISSING_VIDEO '+content[:300])
                    return url
                count+=1
                if count%15==0: print('SSE',count,event,flush=True)
                event=''
    raise RuntimeError('SSE_STREAM_ENDED_WITHOUT_COMPLETE')

def inspect(path):
    cmd=['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name','-of','json',str(path)]
    info=json.loads(subprocess.check_output(cmd,timeout=30))
    kinds=[s.get('codec_type') for s in info.get('streams',[])]
    duration=float(info.get('format',{}).get('duration',0))
    sound_measure=None
    if 'audio' in kinds:
        p=subprocess.run(['ffmpeg','-v','info','-i',str(path),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,timeout=90)
        import re
        m=re.search(r'mean_volume:\s*([-\d.]+) dB',p.stderr)
        if m:sound_measure=float(m.group(1))
    return {'duration_s':duration,'tracks':kinds,'audio_mean_db':sound_measure,'valid_duration':abs(duration-8)<0.8,'audible_track_detected':sound_measure is not None and sound_measure>-65}

try:
    make_png(OUT/'synthetic-test.png')
    REPORT['state']='uploading';persist()
    image=gradio_upload(OUT/'synthetic-test.png')
    data=[image,'A bright orange ball rolls from the left across a sunlit grassy meadow, then gently bounces twice. Natural synchronized audio: gentle grass rustle and two soft bounce thuds. No text, no title, no subtitles, no speech, no watermark.',8.0,False,42,False,544,960]
    REPORT['state']='submitting';persist()
    req=urllib.request.Request(BASE+'/gradio_api/call/generate_video',data=json.dumps({'data':data}).encode(),method='POST',headers={'Content-Type':'application/json','User-Agent':'KolboCloudProbe/1.0'})
    with fetch(req,65) as res: obj=json.load(res)
    ident=obj.get('event_id')
    if not isinstance(ident,str) or not ident.replace('-','').replace('_','').isalnum():raise RuntimeError('INVALID_EVENT_ID '+str(obj)[:200])
    REPORT['state']='processing';REPORT['job_created']=True;persist()
    url=sse(BASE+'/gradio_api/call/generate_video/'+ident)
    uri=urlparse(url)
    if uri.scheme!='https' or not uri.hostname.endswith('.hf.space'):raise RuntimeError('UNTRUSTED_VIDEO_URL')
    REPORT['state']='downloading';persist()
    req=urllib.request.Request(url,headers={'User-Agent':'KolboCloudProbe/1.0'})
    with fetch(req,90) as res, open(OUT/'synthetic-8s-audio.mp4','wb') as target:
        total=0
        while True:
            block=res.read(65536)
            if not block:break
            total+=len(block)
            if total>80*1024*1024:raise RuntimeError('OVERSIZED_MEDIA')
            target.write(block)
    REPORT['verification']=inspect(OUT/'synthetic-8s-audio.mp4')
    v=REPORT['verification'];REPORT['state']='pass' if v['valid_duration'] and v['audible_track_detected'] and 'video' in v['tracks'] else 'quality_failed'
except Exception as e:
    REPORT['state']='blocked';REPORT['reason']=str(e)[:600]
finally:
    persist(); print(json.dumps(REPORT,ensure_ascii=False,indent=2),flush=True)