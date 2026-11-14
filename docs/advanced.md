# Advanced development branch

This branch adds features beyond the stable v0.1.0 release. Unit/fixture verification and live qualification are reported separately. Do not assume a configured provider or downloaded model was tested merely because its adapter exists.

## Models

Set HOUNDSCRAPER_LLM_PROVIDER=openai|gemini|vertex and HOUNDSCRAPER_LLM_MODEL to an available model you have access to. No fallback model is silently chosen. OpenAI-compatible endpoints additionally need HOUNDSCRAPER_LLM_ENDPOINT and optional HOUNDSCRAPER_LLM_KEY. Native Gemini uses HOUNDSCRAPER_LLM_KEY via a header, never a URL query. Vertex uses application default credentials with HOUNDSCRAPER_VERTEX_PROJECT and optional HOUNDSCRAPER_VERTEX_LOCATION (global by default); install the vertex extra. No service-account private key is bundled.

OpenAI completion token totals already include reasoning tokens; Gemini counters combine candidate and thinking tokens. Raw provider counters are retained. Dollar costs remain unknown unless independently established pricing is configured; no fabricated cost or billing wallet is included. For a local non-reasoning endpoint supporting only max_tokens, explicitly set HOUNDSCRAPER_LLM_OUTPUT_CONTROL=max_tokens; default max_completion_tokens preserves modern reasoning-model output ceilings. Qualify the provider's enforcement before relying on strict resource accounting.

## Agents

POST /v1/agent accepts a native JobRequest with kind=agent, query (the task), optional seed urls and options.json_schema. The configured model can select scrape, map, optional search, optional browse, or finish. Page material cannot add tools, change API credentials or grant write access. Authenticated profiles disable external search. Every tool observation and pending action is checkpointed; crashes reuse cached observations rather than automatically repeating paid planning calls. Source text, hashes, actual usage and verified field-level quotes accompany the synthesis.

Defaults are 40 planner steps, 200,000 provider-token ceiling units, the job's page/byte/time budgets, and 2,048 output tokens per model call. Token ceiling units are conservative input UTF-8 bytes plus protocol overhead and maximum output, not measured token usage. Uncertain calls retain their reservation. Actual counters are shown separately. Resume supports higher max_agent_steps/max_provider_tokens and existing job budgets. A schema-valid answer without a verbatim quote for every non-null scalar is rejected. Quote validation does not establish that the model's interpretation is semantically correct.

## S3-compatible storage

Install the s3 extra and set HOUNDSCRAPER_STORAGE=s3://bucket/private-prefix. Credentials use the standard AWS SDK chain (prefer workload identity/IAM roles); HOUNDSCRAPER_S3_ENDPOINT configures a self-hosted endpoint such as MinIO. Object names are server-generated and tenant-scoped. Writes request AES256 server-side encryption; downloads verify the saved SHA-256. The adapter never gives models bucket credentials or presigned URLs. Local filesystem storage remains the default.

## Monitoring and notifications

PUT /v1/notification-profiles/{name} accepts kind=email plus recipients, or kind=slack plus an official incoming webhook URL. Profiles are encrypted using the external credential-encryption key and are referenced by name from a monitor's notifications list. SMTP uses operator-configured HOUNDSCRAPER_SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_USER, SMTP_PASSWORD and SMTP_SSL variables (all prefixed HOUNDSCRAPER_); TLS is mandatory. Outbound notifications are at least once, bounded, retried, and separately visible through GET /v1/deliveries. PATCH /v1/monitors/{id} with active=false pauses future scheduling; an active check can be cancelled through its job ID.

## Documents and media

Enable the parser container and explicitly provision model files with scripts/provision-parser-models.sh in a network-enabled provisioning environment after reviewing upstream model licenses. Mount the resulting /models volume read-only for the runtime. The runtime uses HF_HUB_OFFLINE and DOCLING_ARTIFACTS_PATH; remote Docling services are disabled. PDF layout/OCR, Office and media use killable subprocesses with CPU/file/deadline limits. Upload documents to POST /v1/parse/upload using the document MIME type, or supply a URL to /v1/parse.

Audio/video is bounded to 32 MiB and 300 seconds. ffprobe verifies duration; ffmpeg allows only local file/pipe protocols and creates bounded mono PCM for the offline Whisper tiny model. Missing models fail rather than invent transcripts. Page formats audio, video and captions expose actual media references; caption text is downloaded with public-network policy and the same remaining byte budget. No DRM or paywall bypass is provided.

## Shared scheduling and migrations

PostgreSQL now enforces a global HTTP slot pool and one active request per origin across worker processes. Origin crawl delay and Retry-After are shared. Expired leases recover and stale releases cannot clear a newer owner's lease. Use identical concurrency configuration across a cluster. Browser pools remain separately bounded per isolated worker deployment. Startup DDL is serialized with a database advisory transaction lock; migrations are additive. Stop old worker versions before upgrading an initial 0.x installation and back up database/artifacts first.

## Keyless Vertex qualification setup

Where the connector cannot create service accounts, run `python scripts/configure-vertex-identity.py --project=YOUR_PROJECT` using your own authenticated gcloud CLI. The script creates no keys, binds only endpoint prediction and service usage, restricts GitHub federation to the exact repository and owner IDs and trusted branches, and refuses to reuse unexpectedly broader roles/providers. Save its printed identifiers as GitHub Actions variables with the same names, then run the Vertex qualification workflow on the advanced branch. These identifiers are not credentials. A skipped workflow is not a successful live model test.

The parser model profile has real PDF/layout, scanned OCR and Office fixtures. Audio language may be set with options.media_language (or media_language query for uploads); it is not silently forced to English. Parser stdout is a JSON-only protocol; backend diagnostics do not enter transcript data.

## Measured usage and execution budgets

Every worker model call, including extraction across parallel pages, retries and agent synthesis, reserves tokens atomically in PostgreSQL before contacting the provider. Lost responses retain their conservative reservation. Valid usage counters replace estimates; invalid JSON still records returned usage. Reasoning tokens are included in Gemini output usage and OpenAI completion usage. A provider overrun pauses the job. Resume retains prior usage rather than resetting spending.

Optional max_cost_usd requires HOUNDSCRAPER_PRICING_JSON with provider, model, input_usd_per_million, output_usd_per_million, optional cached_input_usd_per_million, source (HTTPS) and checked_at. Rates must cover the configured model's entire enabled context range; use the highest applicable rate if pricing is tiered. Costs are calculated from configured rates, not a claim about the provider's invoice or promotional credits. No guessed default prices are shipped. Dollar budgets cover model tokens, not separately billed search/proxy/storage services. Synchronous scrape has one output-bounded model call; use a job for a cumulative token or dollar budget.

Whisper tiny is a low-resource speech model, not a guarantee of verbatim accuracy. The synthetic speech fixture exposed an incorrect phrase despite correctly hearing the numeric amount. Human-speech qualification uses an integrity-pinned public-domain JFK excerpt from upstream Whisper, with an explicit word-error threshold. Transcripts remain machine-generated source interpretations and should be reviewed before consequential use.

## Backup and recovery qualification

`scripts/verify-backup.py` dumps only the synthetic houndscraper_test database from an explicitly named local PostgreSQL container, restores into a fresh disposable database, compares all 14 application tables by canonical row fingerprints, and removes the restored copy. A real PostgreSQL 17 round trip passed. This does not replace an operator's production backup policy: back up the PostgreSQL database, the artifact volume/bucket, and the separately protected encryption/signing keys together; restore with workers stopped and validate artifacts before resuming jobs. Never rotate the encryption key by discarding the old one.
