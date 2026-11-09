FROM python:3.12-slim

# ffmpeg for merging/converting; deno is the JavaScript runtime yt-dlp needs for YouTube
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" || exit 1
# One worker on purpose: jobs are kept in memory. Threads handle concurrency.
CMD gunicorn -w 1 --threads 16 --timeout 0 -b 0.0.0.0:${PORT} server:app
