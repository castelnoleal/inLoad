# inLoad

A free, independently operated video and audio downloader and batch media converter.

- **Download**: paste a YouTube or YouTube Music link (or a playlist) and save it as video (MP4 / WEBM / MKV, 360p–4K) or music (MP3 / M4A / OPUS / WAV / FLAC, up to 320 kbps). Playlists let you tick the items you want and queue them all at once.
- **Convert**: drop many files at once and convert them all to MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, MP4, WEBM, MKV, MOV, AVI or GIF, with optional resizing and bitrate. Each file shows its own progress, and you can save all results as one ZIP.

## Stack

| Part | Tech |
|---|---|
| Backend | Python 3.12, Flask, yt-dlp, ffmpeg (`server.py`) |
| Frontend | Plain HTML/CSS/JS (`static/`) |
| Deploy | Docker (`Dockerfile`), Render blueprint (`render.yaml`) |

A backend server is required. Browsers can't download from YouTube directly, and conversion runs ffmpeg on the server. **Regular shared hosting (like DashNex) can't run it.** Use a Docker host such as Render, Railway, Fly.io or a VPS.

**Custom domain: not selected yet.** Until an independent domain is acquired, use the host's assigned `onrender.com` address for private testing. The application has no dependency on instApped accounts, billing, licenses, APIs or hosting. Its eventual custom domain can be attached independently.

## Run locally

```bash
pip install -r requirements.txt
python server.py            # http://localhost:8080
```

or with Docker:

```bash
docker build -t inload .
docker run -p 8080:8080 inload
```

## Deploy on Render

1. Push this repo to GitHub.
2. On Render, go to **New → Blueprint** and pick the repo. It reads `render.yaml`.
3. Do not add a custom domain in this stage. Render will assign a service hostname for testing. Attach the separately acquired inLoad domain only after the service passes acceptance tests.
4. When the independent inLoad domain is acquired, add its CNAME record at that domain's DNS provider:

   | Type | Name | Value |
   |---|---|---|
   | CNAME | The host label chosen on your independent domain | The exact target hostname shown by Render |

   If using Cloudflare, keep the record **DNS only** (grey cloud) during initial domain verification and large-upload testing. Cloudflare's standard proxied upload limit can prevent uploads above 100 MB.
5. For testing, verify the Render-assigned service hostname plus `/api/health`.

Do not change DNS or deploy a live service as part of reviewing this branch. Complete the release checklist in `docs/PRODUCTION.md` first.

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `MAX_UPLOAD_MB` | `1024` | Max size of one converter upload request |
| `MAX_PARALLEL_JOBS` | `3` | Downloads and conversions running at the same time |
| `MAX_QUEUED_JOBS` | `12` | Maximum additional jobs waiting for a worker |
| `MAX_FILES_PER_REQUEST` | `20` | Maximum files in one conversion request |
| `MAX_DOWNLOAD_MB` | `2048` | Maximum downloaded media file size in MB |
| `RATELIMIT_STORAGE_URI` | `memory://` | Rate-limit storage; use Redis before scaling beyond one instance |
| `JOB_TTL_MIN` | `60` | Minutes before finished files are deleted |
| `MAX_VIDEO_HEIGHT` | `2160` | Highest video resolution offered |
| `ALLOWED_HOSTS` | YouTube domains | Sites that can be downloaded from (`*` = any site yt-dlp supports) |
| `YTDLP_COOKIES` | — | Path to a Netscape `cookies.txt` file |
| `INLOAD_WORK_DIR` | system temp | Where temporary files are stored |

### "Sign in to confirm you're not a bot"

YouTube often blocks downloads from data-center servers. If that happens, export cookies from a browser that is signed in to a **throwaway** Google account, store the file as a server secret, and set `YTDLP_COOKIES` to its path. Restrict access and rotate/remove the file when no longer needed.

Keep yt-dlp current, because YouTube changes often: rebuild the image regularly.

## Notes

- Run gunicorn with **one worker** (many threads). Jobs and the default rate-limit counters are kept in memory; a restart loses active job state. Do not scale to multiple instances until shared job storage/queue and Redis rate-limit storage are implemented.
- The API applies per-IP request limits and bounded active-job capacity. Tune limits to the selected host and monitor resource usage.
- Review [`docs/PRODUCTION.md`](docs/PRODUCTION.md) before deployment. It documents known limitations and release acceptance tests.
- Users should only download content they own or have permission to use.

## API

| Method | Path | Body / query |
|---|---|---|
| POST | `/api/info` | `{url}`: video details or playlist entries |
| POST | `/api/download` | `{url, mode: video|audio, format, quality, title?}`: returns a job |
| POST | `/api/convert` | multipart `files[]`, `target`, `height`, `bitrate`: returns jobs |
| GET | `/api/jobs?ids=a,b` | job status and progress |
| GET | `/api/file/<id>` | download the finished file |
| GET | `/api/zip?ids=a,b` | ZIP of finished files |
| GET | `/api/health` | server status |
