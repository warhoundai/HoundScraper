# Architecture

The API authenticates a tenant before accepting JSON. Engine requests pass URL policy, robots policy, tenant cache and a DNS-pinned HTTP fetcher. The default path makes no model calls. Browser-required operations go through a separate signed-grant API; document content goes to the optional isolated parser service.

PostgreSQL holds jobs, URL frontiers, leases, results, append-only events, caches, artifact metadata, encrypted credential profiles, monitor schedules and a webhook outbox. SKIP LOCKED avoids duplicate claims. Page and worst-case decoded-byte reservations are taken atomically across worker claims; unused download reservations are released at settlement. A stale lease cannot commit after recovery.

Worker interruption preserves the frontier. Reads can retry up to three times with backoff; browser writes are not supported. HTTP 429/503 observes Retry-After. Results with errors or remaining work are partial, never fabricated successes. Budgets can be increased on resume. CPU/browser/provider time is bounded per operation; aggregate elapsed usage is conservative and is not a monetary wallet.

Run one embedded worker process for the reference deployment. Separate workers share durable job reservations, but per-origin HTTP pacing is per process in this initial release. Do not claim cluster-wide pacing or use unrestricted horizontal scaling until a shared origin scheduler is implemented.

The reference stores artifacts in a dedicated private local volume with SHA-256 verification. S3 storage is planned, not silently substituted. Retention defaults to seven days. Webhook deliveries are at least once, signed, retried and never redirected.
