#!/usr/bin/env python3
"""No-token, one-attempt LTX-2.5 image-to-video with synced audio verification; synthetic image only."""
import os, json, time, pathlib, urllib.request, urllib.error, urllib.parse, struct, zlib, subprocess, re
BASE="https://chopperblu-ltx-2-5-demo.hf.space"
ROOT=pathlib.Path("ltx25probe"); ROOT.mkdir(exist_ok=True)
R={"engine":"LTX-2.5-Diffusers","requested_seconds":8,"resolution":"512x512","mode":"image-to-video","native_audio_required":True,"state":"not_started"}
def save(): (ROOT/"result.json").write_text(json.dumps(R,ensure_ascii=False,indent=2))
def request(url,data=None,headers=None,timeout=45):
    q=urllib.request.Request(url,data=data,headers={"User-Agent":"KolboCloudProof/1.0",**(headers or {})})
    try: return urllib.request.urlopen(q,timeout=timeout)
    except urllib.error.HTTPError as e:
        details=e.read(1000).decode("utf-8","replace")
        raise RuntimeError("HTTP_%s %s"%(e.code,details[:400])) from e
def png_write(path):
    width=height=512
    rows=[]
    for y in range(height):
        b=bytearray()
        for x in range(width):
            ball=(x-155)**2+(y-360)**2<62**2
            b.extend((233,116,47) if ball else ((90,155,95) if y>400 else (130,192,225)))
        rows.append(b"\0"+b)
    def chunk(t,b):return struct.pack(">I",len(b))+t+b+struct.pack(">I",zlib.crc32(t+b)&0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"".join(rows),5))+chunk(b"IEND",b""))
def upload(path):
    boundary="----KolboLTXProof2026"
    payload=("--%s\r\nContent-Disposition: form-data; name=\"files\"; filename=\"test.png\"\r\nContent-Type: image/png\r\n\r\n"%boundary).encode()+path.read_bytes()+("\r\n--%s--\r\n"%boundary).encode()
    with request(BASE+"/gradio_api/upload",payload,{"Content-Type":"multipart/form-data; boundary="+boundary},70) as response: arr=json.load(response)
    if not isinstance(arr,list) or not arr or not isinstance(arr[0],str) or not arr[0].startswith("/"):raise RuntimeError("BAD_IMAGE_UPLOAD")
    return {"path":arr[0],"orig_name":"test.png","mime_type":"image/png","meta":{"_type":"gradio.FileData"}}
def find_url(o):
    if isinstance(o,dict):
        for k in ("url","video_url"):
            v=o.get(k)
            if isinstance(v,str) and v.startswith("https://") and ".hf.space/" in v:return v
        for v in o.values():
            q=find_url(v)
            if q:return q
    if isinstance(o,list):
        for v in o:
            q=find_url(v)
            if q:return q
    return None
def collect(event_id):
    url=BASE+"/gradio_api/call/generate_video/"+urllib.parse.quote(event_id,safe="")
    event=""; buf=[]
    with request(url,headers={"Accept":"text/event-stream"},timeout=600) as stream:
        while True:
            line=stream.readline()
            if not line:break
            line=line.decode("utf-8","replace").rstrip("\r\n")
            if line.startswith("event:"): event=line[6:].strip()
            elif line.startswith("data:"):buf.append(line[5:].strip())
            elif not line:
                data="\n".join(buf);buf=[]
                if event=="error":raise RuntimeError("SSE_ERROR "+data[:500])
                if event=="complete":
                    response=json.loads(data)
                    uri=find_url(response)
                    if not uri:raise RuntimeError("COMPLETED_NO_VIDEO "+data[:500])
                    return uri
                if event=="progress":print("PROGRESS",data[:130],flush=True)
                event=""
    raise RuntimeError("SSE_ENDED_WITHOUT_VIDEO")
def inspect_video(path):
    """Reject near-silent audio despite existence of a valid AAC stream."""
    import array, math, statistics, sys
    info=json.loads(subprocess.check_output(
        ["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type","-of","json",str(path)],
        timeout=30
    ))
    duration=float(info.get("format",{}).get("duration",0))
    tracks=[v.get("codec_type") for v in info.get("streams",[])]
    report={"duration_seconds":duration,"tracks":tracks,"pass_duration":abs(duration-8)<.7,
            "pass_audible_audio":False,"audio_quality_mode":"continuous ambient/audio required"}
    if "audio" not in tracks:
        report["audio_failure"]="AUDIO_STREAM_MISSING"
        return report
    pcm=subprocess.check_output(
        ["ffmpeg","-v","error","-i",str(path),"-map","0:a:0","-ac","1","-ar","48000","-f","s16le","-"],
        timeout=120
    )
    samples=array.array("h");samples.frombytes(pcm)
    if sys.byteorder!="little": samples.byteswap()
    if not samples:
        report["audio_failure"]="AUDIO_EMPTY"
        return report
    rms=[]
    peak=0
    block=12000
    for offset in range(0,len(samples),block):
        x=samples[offset:offset+block]
        power=sum(int(v)*int(v) for v in x)/len(x)
        rms.append(20*math.log10(max(math.sqrt(power)/32768,1e-9)))
        peak=max(peak,max(abs(v) for v in x))
    median=statistics.median(rms)
    activity=sum(v>-40 for v in rms)/len(rms)
    peak_db=20*math.log10(max(peak/32768,1e-9))
    report.update({"audio_median_250ms_dbfs":round(median,1),
                   "audio_coverage_percent":round(activity*100,1),
                   "audio_peak_dbfs":round(peak_db,1)})
    report["pass_audible_audio"]=(median>=-34 and activity>=.80 and peak_db>=-18)
    if not report["pass_audible_audio"]:
        report["audio_failure"]="NEAR_SILENT_OR_INADEQUATE_AUDIO"
    return report

try:
    pic=ROOT/"reference.png";png_write(pic)
    R["state"]="upload";save()
    image=upload(pic)
    # LTX-2.5 Gradio /generate_video arguments read from the Space's public /gradio_api/info endpoint.
    data=["An orange ball rolls smoothly from left to right over a green meadow and bounces twice. Two soft bounce sounds and quiet natural ambience synchronized with action. No lettering, no words, no subtitles, no captions, no titles, no logos.",image,512,512,8,False,42,False,"conv"]
    R["state"]="submit";save()
    with request(BASE+"/gradio_api/call/generate_video",json.dumps({"data":data}).encode(),{"Content-Type":"application/json"},timeout=80) as res: resp=json.load(res)
    eid=resp.get("event_id")
    if not isinstance(eid,str) or not eid.replace("-","").replace("_","").isalnum():raise RuntimeError("MISSING_EVENT_ID "+str(resp)[:150])
    R["state"]="processing";R["job_created"]=True;save()
    url=collect(eid)
    R["state"]="download";save()
    host=urllib.parse.urlparse(url).hostname
    if not host or not (host.endswith(".hf.space") or host=="huggingface.co"): raise RuntimeError("MEDIA_HOST_NOT_TRUSTED")
    target=ROOT/"proof-8s-with-audio.mp4"
    with request(url,timeout=90) as stream, target.open("wb") as w:
        size=0
        while True:
            p=stream.read(65536)
            if not p:break
            size+=len(p)
            if size>120_000_000:raise RuntimeError("OUTPUT_TOO_LARGE")
            w.write(p)
    R["verification"]=inspect_video(target);v=R["verification"]
    R["state"]="PASS" if "video" in v["tracks"] and v["pass_duration"] and v["pass_audible_audio"] else "QUALITY_FAIL"
except Exception as exc:
    R["state"]="BLOCKED";R["reason"]=str(exc)[:650]
finally:
    save();print(json.dumps(R,ensure_ascii=False,indent=2),flush=True)
