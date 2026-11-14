# Security policy

Report vulnerabilities through GitHub private vulnerability reporting. Do not include credentials or customer content in public issues.

HoundScraper is for authorized content collection. The reference deployment is one trust domain, not a hardened adversarial multi-tenant hosting platform. Use separate containers or VMs, databases, storage, keys and browser workers for untrusted customers.

Core HTTP collection rejects private/reserved destinations, validates every DNS result, pins connections, checks redirects, enforces decoded byte limits and strips credentials across origins. Robots policy is separate from prompt-injection handling. Robots are respected by default; only operator configuration can enable overrides.

The optional browser worker accepts signed short-lived job grants, rejects replay, uses HoundBrowser's pinned-DNS proxy, blocks write requests, blocks cross-origin navigation and masks form fields in screenshots. No shell, host filesystem, CDP or arbitrary JavaScript execution endpoint is exposed. User-facing page content is untrusted data.

Use HTTPS for remote endpoints. Keep the dashboard behind your authentication/network boundary. API keys are server-side configuration; the dashboard keeps the key you enter only in page memory. Credential profiles are encrypted with Fernet using an external master key. Header credentials are scoped to one origin. Authenticated content is not cached. Credential redaction cannot guarantee absence of sensitive information in target-provided content; apply your data-handling policy.

The parser is an optional isolated process/container. It needs pre-provisioned models and must run without outbound network, with CPU/memory/tmpfs limits. The optional Docling profile is not part of the core release's verified feature set until its separate acceptance checks pass.

Webhooks are signed and public-destination-only. Receivers must verify HMAC, timestamp (five-minute tolerance) and event-ID deduplication. Delivery is at least once, not exactly once.
