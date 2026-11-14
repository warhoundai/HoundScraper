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
