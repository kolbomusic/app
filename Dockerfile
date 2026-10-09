FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/kolbo
COPY kolbo-cloud-v1.4.1.zip.b64 /tmp/source.b64
COPY kolbo-cloud-v1.4.1.zip.sha256 /tmp/source.sha256
RUN python - <<'PY'
import base64,hashlib,pathlib,zipfile
data=base64.b64decode(pathlib.Path('/tmp/source.b64').read_text().strip(),validate=True)
assert hashlib.sha256(data).hexdigest()==pathlib.Path('/tmp/source.sha256').read_text().strip(),'Source checksum mismatch'
path=pathlib.Path('/tmp/source.zip');path.write_bytes(data)
with zipfile.ZipFile(path) as arc:
    assert arc.testzip() is None,'Corrupt archive'
    for entry in arc.infolist():
        target=pathlib.PurePosixPath(entry.filename)
        assert not target.is_absolute() and '..' not in target.parts
    arc.extractall('/srv/kolbo')
PY
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["uvicorn","kolbo_cloud.service:app","--host","0.0.0.0","--port","7860","--workers","1"]
