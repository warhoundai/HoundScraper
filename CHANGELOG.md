# Changelog

## 0.2.0rc1

Advanced preview: native Gemini and Vertex adapters, durable bounded agent planning and synthesis, aggregate model-token and configured-dollar reservations across parallel extraction/retries, S3 artifact storage, shared cluster origin pacing, offline parser model provisioning and media controls, encrypted email/Slack notifications, monitor lifecycle controls, database-outage recovery, and advanced dashboard operations.

Qualification is feature-specific: real Chromium, PostgreSQL and AWS S3 tests pass. Native Vertex live acceptance requires a dedicated keyless identity; the connector cannot create it. Speech quality is model-dependent. This preview is not full Firecrawl parity or a v1.0 production guarantee. See docs/advanced.md and docs/capabilities.md.

## 0.1.0

Initial independently implemented core release: public-only HTTP collection, deterministic content formats, PostgreSQL-backed crawl/batch/map jobs, checkpoint recovery, page and byte reservations, encrypted origin-bound credentials, artifact integrity, Python/JavaScript clients, MCP stdio adapter, React dashboard, and an explicit Firecrawl v2 subset.

Includes separately configured browser rendering with signed replay-protected scope grants and recurring monitor/webhook primitives. Advanced integrations and release gates are documented in docs/capabilities.md. This initial 0.x release is not a claim of complete Firecrawl feature parity or hostile multi-tenant isolation.
