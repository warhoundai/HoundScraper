# Capability and release status

| Capability | Status in 0.1.0 |
|---|---|
| HTTP scraping; Markdown/text/HTML/links/images/tables/JSON-LD/metadata/attributes | Implemented and fixture-tested |
| Sitemap traversal; crawl/map/batch; page budgets; persistent frontier; leases; pause/cancel/resume | Implemented and PostgreSQL-tested |
| Tenant isolation, encrypted credentials, scoped caches, artifact integrity | Implemented and tested |
| Python/JavaScript SDKs, CLI, MCP stdio, React dashboard | Implemented; see verification report for exact checks |
| Browser rendering, screenshots, computed branding and read-oriented actions | Optional separate worker; real Chromium fixture-tested |
| JSON extraction and summaries | Optional OpenAI-compatible provider; schema and verbatim-source quote checks; provider fixtures tested; no live paid-provider claim |
| Exa/Brave/SearXNG search | Optional configured provider adapters; require provider-specific live acceptance before declaring production support |
| Scheduled content monitoring and signed webhook delivery | Implemented; controlled PostgreSQL fixture-tested |
| Docling document/OCR worker | Experimental profile; not yet model/container acceptance-tested |
| Agent orchestration, native Gemini/Vertex, media transcription, S3 storage | Planned subsequent stages; not implemented in 0.1.0 |
| Paid hosted API, accounts, billing, proprietary data collections, managed proxy network | Not bundled |

All local core features work without paid keys. Optional features fail explicitly when unconfigured. This table is a delivery boundary, not a promise that every target can be accessed.

## 0.2.0rc1 preview

The stable-release table above describes v0.1.0. The advanced preview adds:

| Capability | Qualification |
|---|---|
| Native Gemini/Vertex/OpenAI-compatible structured adapters | Response/usage fixtures pass; live Vertex awaits dedicated keyless identity setup |
| Durable agent planning, cross-source synthesis and bounded tool selection | Controlled planner/database fixtures; no claim of universal agent accuracy |
| Shared model-token and configured-dollar reservations | Real PostgreSQL concurrency, exhaustion/resume, unknown-response and overrun tests |
| S3 artifacts | Live AWS encrypted put/get/delete and denied access outside test prefix |
| Shared origin pacing and global request slots | PostgreSQL concurrency, stale leases and Retry-After fixtures |
| Offline PDF text/layout and scanned OCR; DOCX | Real Docling model qualification passes |
| Audio | Integrity-pinned human-speech fixture passes a ≤20% word-error threshold with offline Whisper tiny; synthetic speech exposed errors |
| XLSX/PPTX/CSV | Adapters and dedicated parser qualification fixtures; inspect latest CI before relying on a format |
| EPUB/ODT | Independent text-oriented archive fixtures; chapter order and unsafe XML checks; no page-layout reconstruction |
| Email/Slack notifications | Encrypted profile and TLS/mocked-delivery tests; no live recipient delivery claimed |
| Dashboard advanced jobs and monitor controls | Real HTTP flows in Chromium at desktop/mobile sizes; zero axe violations in tested views |
| Backup/restore | Real PostgreSQL 17 dump/restore of 14 fixture tables with matching row fingerprints |

Search provider acceptance, broader quality/performance corpus, operational chaos testing and all v1.0 gates remain outstanding. This preview is not the completion of every accepted roadmap stage. Operator configuration and separate credentials are required for optional services. See [advanced configuration](advanced.md).
