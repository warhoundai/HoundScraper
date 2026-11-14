# API

All /v1 and /compat requests require `Authorization: Bearer <instance-key>`. GET /health and dashboard assets are public metadata/UI only. GET /v1/openapi.json returns the generated native OpenAPI specification.

- POST /v1/scrape: `{ "url": "https://example.com", "options": { "formats": ["markdown"], "render": "never" } }`.
- POST /v1/jobs: `{ "kind": "crawl", "urls": ["https://example.com"], "max_pages": 100, "max_depth": 3, "options": { "formats": ["markdown"] } }`. Returns 202 with job ID. Idempotency-Key is optional and tenant-scoped.
- GET /v1/jobs and /v1/jobs/{id}; GET /v1/jobs/{id}/results?cursor=0; GET /v1/jobs/{id}/events with Last-Event-ID for reconnection.
- POST /v1/jobs/{id}/pause, /cancel, /resume. Resume accepts optional max_pages, max_seconds and max_download_bytes.
- DELETE /v1/jobs/{id}: only inactive jobs with no in-flight work.
- GET /v1/artifacts/{id}: tenant-protected binary download with integrity ETag.
- PUT /v1/credentials/{name}: `{ "origin": "https://example.com", "headers": { "Authorization": "Bearer ..." } }`. DELETE removes the profile. Header secrets are never echoed.
- POST /v1/search: query, limit, optional scrape and native options. Requires a configured search provider.
- POST /v1/monitors: `{ "job": { "kind": "crawl", "urls": ["https://example.com"] }, "schedule": "0 * * * *", "timezone": "UTC" }`. GET /v1/monitors includes previous check differences; DELETE /v1/monitors/{id} removes a schedule.

Defaults: eight concurrent requests per process, one per origin, 1,000 pages/job, 10 link levels, 900 aggregate execution seconds/job, 32 MiB/resource, 1 GiB/job, seven-day retention. Operators and callers can configure documented bounds. No subscription quota, mandatory cloud or model account is included.

Target text is source material, never control-plane instructions. JSON extraction evidence is verified as verbatim source quotes; this is not a proof that every model interpretation is semantically correct.
