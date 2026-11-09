# inLoad

YouTube video & music downloader plus a batch video/audio converter, built by Meta Insider OCG.

- **Download**: paste a YouTube or YouTube Music link (or a playlist) and save it as video (MP4 / WEBM / MKV, 360p–4K) or music (MP3 / M4A / OPUS / WAV / FLAC, up to 320 kbps). Playlists let you tick the items you want and queue them all at once.
- **Convert**: drop many files at once and convert them all to MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, MP4, WEBM, MKV, MOV, AVI or GIF, with optional resizing and bitrate. Each file shows its own progress, and you can save all results as one ZIP.
- **Ads**: house ads for MEIOCG products and instApped appear in a rotating top banner, inline cards and a footer grid. Edit the list in `static/ads.js`.

## Stack

| Part | Tech |
|---|---|
| Backend | Python 3.12, Flask, yt-dlp, ffmpeg (`server.py`) |
| Frontend | Plain HTML/CSS/JS (`static/`) |
| Deploy | Docker (`Dockerfile`), Render blueprint (`render.yaml`) |

A backend server is required. Browsers can't download from YouTube directly, and conversion runs ffmpeg on the server. **Regular shared hosting (like DashNex) can't run it.** Use a Docker host such as Render, Railway, Fly.io or a VPS.

**Live address (for now): https://inload.castelmei.com.** It can move to a meiocg.org subdomain later.

## Run locally

```bash
# needs ffmpeg on PATH (and deno for YouTube: https://deno.com)
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
3. `render.yaml` already adds the custom domain `inload.castelmei.com`. Render shows the target hostname (like `inload.onrender.com`) under **Settings → Custom Domains**.
4. At the DNS provider for castelmei.com, add this record:

   | Type | Name | Value |
   |---|---|---|
   | CNAME | `inload` | `inload.onrender.com` (the hostname Render shows) |

   If the domain uses Cloudflare, set the record to **DNS only** (grey cloud) until Render shows the certificate as issued. Cloudflare's proxy also cuts off uploads over 100 MB.
5. Render issues the HTTPS certificate automatically once DNS resolves.

To move to another domain later, change `domains` in `render.yaml` and the `canonical` / `og:url` tags in `static/index.html`.

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
| `YTDLP_COOKIES` | — | Path to a Netscape `cookies.txt` file (see below) |
| `INLOAD_WORK_DIR` | system temp | Where temporary files are stored |

### "Sign in to confirm you're not a bot"

YouTube often blocks downloads from data-center servers. If that happens, export cookies from a browser that is signed in to a **throwaway** Google account (for example with the "Get cookies.txt LOCALLY" extension), upload the file to the server as a secret file, and set `YTDLP_COOKIES=/etc/secrets/cookies.txt`.

Keep yt-dlp current, because YouTube changes often: rebuild the image regularly (`pip install -U yt-dlp`).

## Notes

- Run gunicorn with **one worker** (`-w 1`, many threads). Jobs and the default rate-limit counters are kept in memory; a restart loses active job state. Do not scale to multiple instances until shared job storage/queue and Redis rate-limit storage are implemented.
- The API applies per-IP request limits and bounded active-job capacity. Tune limits to the selected host and monitor resource usage.
- Review [`docs/PRODUCTION.md`](docs/PRODUCTION.md) before deployment. It documents known limitations and release acceptance tests.
- Users should only download content they own or have permission to use.

## API

| Method | Path | Body / query |
|---|---|---|
| POST | `/api/info` | `{url}`: video details or playlist entries |
| POST | `/api/download` | `{url, mode: video\|audio, format, quality, title?}`: returns a job |
| POST | `/api/convert` | multipart `files[]`, `target`, `height`, `bitrate`: returns jobs |
| GET | `/api/jobs?ids=a,b` | job status and progress |
| GET | `/api/file/<id>` | download the finished file |
| GET | `/api/zip?ids=a,b` | ZIP of finished files |
| GET | `/api/health` | server status |
