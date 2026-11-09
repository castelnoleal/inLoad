# inLoad production rollout checklist

inLoad is a free, independently branded product. It does not use instApped subscriptions, license keys, customer accounts, billing APIs, or hosting. Its eventual custom domain is managed independently; until then use the host-assigned service URL for testing. Do not configure a custom domain or DNS as part of this review.

This document describes the staged release process. A successful GitHub build is not proof that Render, DNS, SSL, YouTube extraction, or large-file transfers work in production.

## Before deployment

- [ ] Review this branch and merge only after CI passes.
- [ ] Confirm the Render service, region, plan, disk/storage behavior, and outbound bandwidth are appropriate for media workloads.
- [ ] Keep a single Render instance while job state is in process memory. Do not scale horizontally until jobs and rate limits use shared durable services.
- [ ] Configure Cloudflare DNS for the Render-provided hostname. Use DNS-only mode for large uploads unless the chosen proxy/upload architecture explicitly supports the required request size.
- [ ] Confirm the custom domain and HTTPS certificate in Render before announcing the service.
- [ ] Keep ALLOWED_HOSTS restricted to approved media hosts. Never set it to * on a public deployment without a separate SSRF-safe fetch architecture.
- [ ] Set realistic upload, download, parallel-job, queued-job, and file-count limits for the selected instance.
- [ ] Configure RATELIMIT_STORAGE_URI to managed Redis before using multiple instances. The default in-memory limiter resets on restart and is not shared across instances.
- [ ] If YouTube requires cookies, use a dedicated throwaway account, store the cookie file as a secret file, restrict access, and rotate/remove it when no longer needed.
- [ ] Publish a privacy notice and terms that identify the operator, explain temporary processing and deletion, describe logging, and provide a contact method. Do not publish placeholder legal text as final policy.

## Release acceptance

- [ ] /api/health returns HTTP 200 and reports FFmpeg availability.
- [ ] Test a permitted short video download and verify the resulting file plays.
- [ ] Test audio extraction and playlist handling.
- [ ] Test conversion for representative audio and video inputs.
- [ ] Test ZIP export with multiple completed jobs.
- [ ] Test upload rejection, queue-full responses, rate limiting, and expired job links.
- [ ] Restart the service and confirm expected behavior. Current jobs are intentionally in-memory and are lost on restart; this limitation must be communicated until durable job storage is implemented.
- [ ] Inspect Render logs, CPU, memory, disk, bandwidth, and error rates during a controlled load test.

## Known limitations in this release candidate

- Job metadata and rate-limit counters are in process memory; restarts clear them.
- Files are stored on the service filesystem and are temporary. Confirm the host's filesystem lifecycle and capacity before launch.
- There is no user account system or per-user ownership model. Public job IDs are unguessable tokens, not authentication.
- The built-in rate limiter uses memory storage by default and is intended only for the current single-instance topology.
- Media extraction depends on upstream YouTube behavior and may fail due to bot checks, format changes, regional restrictions, or content permissions.
- The application is intended for content users own or are authorized to download. Operators must review applicable platform terms and local law.
