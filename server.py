"""
inLoad — YouTube video & music downloader + batch media converter.

Backend: Flask + yt-dlp + ffmpeg.
Run locally:  pip install -r requirements.txt && python server.py
Production:   gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT server:app
              (keep ONE worker: jobs live in this process's memory)
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

try:
    import yt_dlp  # type: ignore
except ImportError:  # converter still works without it
    yt_dlp = None

# --------------------------------------------------------------------------- #
# Config (environment variables)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
WORK_DIR = Path(os.environ.get("INLOAD_WORK_DIR", tempfile.gettempdir())) / "inload"
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "1024"))
JOB_TTL_MIN = int(os.environ.get("JOB_TTL_MIN", "60"))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_JOBS", "3"))
MAX_VIDEO_HEIGHT = int(os.environ.get("MAX_VIDEO_HEIGHT", "2160"))
COOKIES_FILE = os.environ.get("YTDLP_COOKIES", "").strip() or None
ALLOWED_HOSTS = [
    h.strip().lower()
    for h in os.environ.get(
        "ALLOWED_HOSTS", "youtube.com,youtu.be,music.youtube.com,youtube-nocookie.com"
    ).split(",")
    if h.strip()
]

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# --------------------------------------------------------------------------- #
# Format tables
# --------------------------------------------------------------------------- #
VIDEO_TARGETS = {"mp4", "webm", "mkv", "mov", "avi", "gif"}
AUDIO_TARGETS = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "opus"}
DL_VIDEO_CONTAINERS = {"mp4", "webm", "mkv"}
DL_AUDIO_FORMATS = {"mp3", "m4a", "opus", "wav", "flac"}
BITRATES = {"320", "256", "192", "160", "128", "96"}
HEIGHTS = {"keep", "2160", "1440", "1080", "720", "480", "360"}

# --------------------------------------------------------------------------- #
# Job store
# --------------------------------------------------------------------------- #
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
SLOTS = threading.Semaphore(MAX_PARALLEL)


def new_job(kind: str, label: str) -> dict:
    jid = uuid.uuid4().hex[:16]
    job = {
        "id": jid,
        "kind": kind,
        "label": label,
        "status": "queued",  # queued | running | done | error
        "progress": 0.0,
        "message": "Waiting in queue…",
        "filename": None,
        "size": None,
        "path": None,
        "dir": str(WORK_DIR / jid),
        "created": time.time(),
    }
    Path(job["dir"]).mkdir(parents=True, exist_ok=True)
    with JOBS_LOCK:
        JOBS[jid] = job
    return job


def update(job: dict, **kw) -> None:
    with JOBS_LOCK:
        job.update(kw)


def public(job: dict) -> dict:
    return {k: job[k] for k in ("id", "kind", "label", "status", "progress", "message", "filename", "size")}


def run_job(job: dict, fn, *args) -> None:
    def runner():
        with SLOTS:
            update(job, status="running", message="Starting…")
            try:
                fn(job, *args)
            except Exception as exc:  # noqa: BLE001
                update(job, status="error", message=friendly_error(exc))

    threading.Thread(target=runner, daemon=True).start()


def friendly_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
    msg = msg.replace("ERROR: ", "")
    low = msg.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return "YouTube asked for a sign-in check on this server. The admin needs to add cookies (see README)."
    if "private video" in low:
        return "This video is private."
    if "video unavailable" in low:
        return "This video is unavailable."
    if "age" in low and "restrict" in low:
        return "This video is age-restricted."
    return (msg[:300] + "…") if len(msg) > 300 else (msg or "Something went wrong.")


def cleanup_loop() -> None:
    while True:
        time.sleep(300)
        cutoff = time.time() - JOB_TTL_MIN * 60
        with JOBS_LOCK:
            stale = [j for j in JOBS.values() if j["created"] < cutoff and j["status"] != "running"]
            for j in stale:
                JOBS.pop(j["id"], None)
        for j in stale:
            shutil.rmtree(j["dir"], ignore_errors=True)


threading.Thread(target=cleanup_loop, daemon=True).start()

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
SAFE_RE = re.compile(r"[^\w\-. ()\[\]&,']+", re.UNICODE)


def safe_name(name: str, fallback: str = "file") -> str:
    name = SAFE_RE.sub("_", name).strip(" ._")
    return (name[:150] or fallback)


def host_allowed(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if "*" in ALLOWED_HOSTS:
        return True
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def ydl_base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        opts["cookiefile"] = COOKIES_FILE
    return opts


def need_ytdlp():
    if yt_dlp is None:
        abort(503, description="yt-dlp is not installed on the server.")


def probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return 0.0


def has_video_stream(path: str) -> bool:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=codec_type:stream_disposition=attached_pic",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60,
        ).stdout
        streams = json.loads(out or "{}").get("streams", [])
        return any(not s.get("disposition", {}).get("attached_pic") for s in streams)
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Routes — static
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC_DIR, name)


@app.get("/api/health")
def health():
    return jsonify(
        ok=True,
        ytdlp=getattr(getattr(yt_dlp, "version", None), "__version__", None) if yt_dlp else None,
        ffmpeg=shutil.which("ffmpeg") is not None,
        max_upload_mb=MAX_UPLOAD_MB,
    )


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(503)
def json_error(err):
    code = getattr(err, "code", 500)
    desc = getattr(err, "description", str(err))
    if code == 413:
        desc = f"File too large. Max upload is {MAX_UPLOAD_MB} MB."
    if request.path.startswith("/api/"):
        return jsonify(error=desc), code
    return desc, code


# --------------------------------------------------------------------------- #
# Routes — YouTube info
# --------------------------------------------------------------------------- #
@app.post("/api/info")
def info():
    need_ytdlp()
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not url:
        abort(400, description="Paste a YouTube link first.")
    if not host_allowed(url):
        abort(400, description="Only YouTube and YouTube Music links are supported.")

    opts = ydl_base_opts() | {"skip_download": True, "extract_flat": "in_playlist", "noplaylist": False}
    # A watch?v=…&list=… link: treat as the single video
    if "v=" in url or "youtu.be/" in url or "/shorts/" in url:
        opts["noplaylist"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        abort(400, description=friendly_error(exc))

    if data.get("_type") == "playlist" or data.get("entries"):
        entries = []
        for e in (data.get("entries") or [])[:200]:
            if not e:
                continue
            vid = e.get("id")
            entries.append({
                "title": e.get("title") or vid,
                "url": e.get("url") if str(e.get("url", "")).startswith("http")
                else f"https://www.youtube.com/watch?v={vid}",
                "duration": e.get("duration"),
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else None,
            })
        return jsonify(type="playlist", title=data.get("title"), uploader=data.get("uploader"),
                       count=len(entries), entries=entries)

    heights = sorted(
        {f.get("height") for f in data.get("formats", []) if f.get("height") and f.get("vcodec") != "none"},
        reverse=True,
    )
    return jsonify(
        type="video",
        id=data.get("id"),
        title=data.get("title"),
        uploader=data.get("uploader") or data.get("channel"),
        duration=data.get("duration"),
        thumbnail=data.get("thumbnail"),
        url=data.get("webpage_url") or url,
        heights=[h for h in heights if h <= MAX_VIDEO_HEIGHT],
    )


# --------------------------------------------------------------------------- #
# Routes — YouTube download
# --------------------------------------------------------------------------- #
@app.post("/api/download")
def download():
    need_ytdlp()
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    mode = body.get("mode", "video")
    fmt = str(body.get("format", "mp4")).lower()
    quality = str(body.get("quality", "1080"))
    title = str(body.get("title") or url)[:200]

    if not host_allowed(url):
        abort(400, description="Only YouTube and YouTube Music links are supported.")
    if mode == "video" and fmt not in DL_VIDEO_CONTAINERS:
        abort(400, description="Unsupported video format.")
    if mode == "audio" and fmt not in DL_AUDIO_FORMATS:
        abort(400, description="Unsupported audio format.")
    if mode not in ("video", "audio"):
        abort(400, description="Unknown mode.")

    job = new_job("download", title)
    run_job(job, _do_download, url, mode, fmt, quality)
    return jsonify(public(job)), 202


def _do_download(job: dict, url: str, mode: str, fmt: str, quality: str) -> None:
    outdir = Path(job["dir"])

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            # video+audio are 2 separate downloads; scale to 0–90 %
            update(job, progress=round(min(pct, 100) * 0.9, 1),
                   message=f"Downloading… {d.get('_speed_str', '').strip()}".strip())
        elif d.get("status") == "finished":
            update(job, progress=90, message="Processing…")

    def pp_hook(d):
        if d.get("status") == "started":
            name = d.get("postprocessor", "")
            label = {"Merger": "Merging video + audio…", "ExtractAudio": f"Converting to {fmt.upper()}…",
                     "FFmpegVideoRemuxer": "Finalizing…"}.get(name, "Processing…")
            update(job, progress=max(job["progress"], 92), message=label)

    opts = ydl_base_opts() | {
        "outtmpl": str(outdir / "%(title).150B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "overwrites": True,
    }

    if mode == "video":
        h = min(int(quality) if quality.isdigit() else 1080, MAX_VIDEO_HEIGHT)
        if fmt == "mp4":
            opts["format"] = (
                f"bv*[height<={h}][vcodec^=avc1]+ba[ext=m4a]/"
                f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
                f"bv*[height<={h}]+ba/b[height<={h}]/b"
            )
        elif fmt == "webm":
            opts["format"] = f"bv*[height<={h}][ext=webm]+ba[ext=webm]/bv*[height<={h}]+ba/b[height<={h}]/b"
        else:
            opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/b"
        opts["merge_output_format"] = fmt
        opts["postprocessors"] = [{"key": "FFmpegVideoRemuxer", "preferedformat": fmt}]
    else:
        br = quality if quality in BITRATES else "192"
        opts["format"] = "ba/b"
        pps = [{"key": "FFmpegExtractAudio", "preferredcodec": fmt, "preferredquality": br}]
        pps.append({"key": "FFmpegMetadata", "add_metadata": True})
        opts["postprocessors"] = pps

    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(url, download=True)

    path = None
    for rd in data.get("requested_downloads") or []:
        if rd.get("filepath") and Path(rd["filepath"]).exists():
            path = rd["filepath"]
    if not path:
        files = sorted(outdir.glob(f"*.{fmt}"), key=lambda p: p.stat().st_size, reverse=True)
        files = files or sorted((p for p in outdir.iterdir() if p.is_file()),
                                key=lambda p: p.stat().st_size, reverse=True)
        if not files:
            raise RuntimeError("Download finished but no file was produced.")
        path = str(files[0])

    name = safe_name(f"{data.get('title') or 'download'}.{Path(path).suffix.lstrip('.')}")
    update(job, status="done", progress=100, message="Ready", path=path,
           filename=name, size=Path(path).stat().st_size, label=data.get("title") or job["label"])


# --------------------------------------------------------------------------- #
# Routes — converter
# --------------------------------------------------------------------------- #
@app.post("/api/convert")
def convert():
    files = request.files.getlist("files")
    target = request.form.get("target", "").lower()
    height = request.form.get("height", "keep")
    bitrate = request.form.get("bitrate", "192")

    if not files:
        abort(400, description="Add at least one file.")
    if target not in VIDEO_TARGETS | AUDIO_TARGETS:
        abort(400, description="Pick an output format.")
    if height not in HEIGHTS:
        height = "keep"
    if bitrate not in BITRATES:
        bitrate = "192"

    jobs = []
    for f in files:
        original = f.filename or "file"
        job = new_job("convert", original)
        src = Path(job["dir"]) / ("src_" + safe_name(original))
        f.save(src)
        run_job(job, _do_convert, str(src), original, target, height, bitrate)
        jobs.append(public(job))
    return jsonify(jobs=jobs), 202


def build_ffmpeg_args(target: str, height: str, bitrate: str, src_has_video: bool) -> list[str]:
    br = f"{bitrate}k"
    scale = [] if height == "keep" else ["-vf", f"scale=-2:'min({height},ih)'"]

    if target in AUDIO_TARGETS or (target in VIDEO_TARGETS and not src_has_video and target != "gif"):
        # audio-only targets, or audio file → video container (keep audio only)
        a = {
            "mp3": ["-c:a", "libmp3lame", "-b:a", br],
            "m4a": ["-c:a", "aac", "-b:a", br],
            "aac": ["-c:a", "aac", "-b:a", br, "-f", "adts"],
            "wav": ["-c:a", "pcm_s16le"],
            "flac": ["-c:a", "flac"],
            "ogg": ["-c:a", "libvorbis", "-b:a", br],
            "opus": ["-c:a", "libopus", "-b:a", br],
        }
        if target in a:
            return ["-vn", "-map_metadata", "0", *a[target]]
        if target == "webm":
            return ["-vn", "-c:a", "libopus", "-b:a", br]
        if target == "avi":
            return ["-vn", "-c:a", "libmp3lame", "-b:a", br]
        return ["-vn", "-c:a", "aac", "-b:a", br]

    if target == "gif":
        h = "480" if height == "keep" else height
        return ["-an", "-vf",
                f"fps=12,scale=-2:'min({h},ih)':flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "-loop", "0"]

    h264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    v = {
        "mp4": [*h264, "-c:a", "aac", "-b:a", br, "-movflags", "+faststart"],
        "mov": [*h264, "-c:a", "aac", "-b:a", br, "-movflags", "+faststart"],
        "mkv": [*h264, "-c:a", "aac", "-b:a", br],
        "webm": ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-deadline", "realtime",
                 "-cpu-used", "8", "-row-mt", "1", "-c:a", "libopus", "-b:a", br],
        "avi": ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-b:a", br],
    }[target]
    return ["-map", "0:v:0?", "-map", "0:a?", *scale, *v]


def _do_convert(job: dict, src: str, original: str, target: str, height: str, bitrate: str) -> None:
    duration = probe_duration(src)
    vid = has_video_stream(src)
    if target == "gif" and not vid:
        raise RuntimeError("This file has no video to turn into a GIF.")

    stem = safe_name(Path(original).stem, "converted")
    out_name = f"{stem}.{target}"
    out = str(Path(job["dir"]) / out_name)
    if os.path.abspath(out) == os.path.abspath(src):
        out = str(Path(job["dir"]) / f"{stem}_converted.{target}")
        out_name = Path(out).name

    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", src,
           *build_ffmpeg_args(target, height, bitrate, vid),
           "-progress", "pipe:1", "-nostats", out]
    update(job, message=f"Converting to {target.upper()}…")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    err_tail: list[str] = []

    def read_err():
        for line in proc.stderr:  # type: ignore[union-attr]
            err_tail.append(line)
            if len(err_tail) > 30:
                err_tail.pop(0)

    t = threading.Thread(target=read_err, daemon=True)
    t.start()

    for line in proc.stdout:  # type: ignore[union-attr]
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if duration > 0:
                update(job, progress=round(min(us / 1_000_000 / duration * 100, 99), 1))
    proc.wait()
    t.join(timeout=2)

    if proc.returncode != 0 or not Path(out).exists():
        last = next((ln.strip() for ln in reversed(err_tail) if ln.strip()), "ffmpeg failed")
        raise RuntimeError(f"Conversion failed: {last}")

    try:
        os.remove(src)
    except OSError:
        pass
    update(job, status="done", progress=100, message="Ready", path=out,
           filename=out_name, size=Path(out).stat().st_size)


# --------------------------------------------------------------------------- #
# Routes — jobs & files
# --------------------------------------------------------------------------- #
@app.get("/api/jobs")
def jobs_status():
    ids = [i for i in request.args.get("ids", "").split(",") if i]
    with JOBS_LOCK:
        out = [public(JOBS[i]) for i in ids if i in JOBS]
    return jsonify(jobs=out)


@app.get("/api/file/<jid>")
def get_file(jid):
    with JOBS_LOCK:
        job = JOBS.get(jid)
    if not job or job["status"] != "done" or not job["path"] or not Path(job["path"]).exists():
        abort(404, description="File not found or expired.")
    return send_file(job["path"], as_attachment=True, download_name=job["filename"])


@app.get("/api/zip")
def get_zip():
    ids = [i for i in request.args.get("ids", "").split(",") if i][:200]
    with JOBS_LOCK:
        ready = [JOBS[i] for i in ids if i in JOBS and JOBS[i]["status"] == "done"]
    if not ready:
        abort(404, description="No finished files to zip.")
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for j in ready:
            name = j["filename"]
            base, ext = os.path.splitext(name)
            n = 1
            while name in used:
                n += 1
                name = f"{base} ({n}){ext}"
            used.add(name)
            z.write(j["path"], arcname=name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"inLoad-{time.strftime('%Y%m%d-%H%M%S')}.zip")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
