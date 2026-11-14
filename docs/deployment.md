# Self-hosting

1. Install Docker Engine and Compose v2.
2. Clone this repository and run `python scripts/configure.py`. It creates a non-overwriting, mode-0600 .env with independent random database, API, encryption and worker keys. Never commit this file.
3. Run `docker compose up --build -d`. The API/dashboard binds only to `127.0.0.1:8081`. PostgreSQL has no published port.
4. Open the dashboard and enter the local instance key from .env, or set HOUNDSCRAPER_API_KEY in your shell and use the CLI. Never paste keys into model prompts.
5. Verify /health and an authenticated /v1/scrape request. Health verifies database reachability; successful page collection verifies outbound DNS/TLS/content processing.

For remote access, place an authenticated HTTPS reverse proxy in front of the API, restrict network access and preserve the database/artifact volumes. Back up PostgreSQL and artifacts together. Keep the external encryption key separately; changing it without re-encryption makes stored credential profiles unreadable.

Optional browser: set HOUNDBROWSER_ENDPOINT=http://browser:8082 in .env and start `docker compose --profile browser up --build -d`. The worker uses its own signed grants and public-only HoundBrowser proxy. It exposes no host shell or arbitrary evaluation API. Keep the worker private; one deployment per trust domain. The browser image installs Chromium and requires more disk/RAM than core HTTP collection.

Optional parser: set HOUNDSCRAPER_PARSER_ENDPOINT=http://parser:8083 and enable the parser profile. Docling model files must be provisioned into parser-models before enabling offline mode. This integration is experimental until the document/model acceptance suite is completed; the core release does not claim verified OCR support. The parser container has no internet egress.

Optional AI: configure HOUNDSCRAPER_LLM_ENDPOINT (OpenAI-compatible API root ending in /v1), HOUNDSCRAPER_LLM_MODEL and optional HOUNDSCRAPER_LLM_KEY. A local Ollama OpenAI-compatible endpoint can be used. The provider is never silently selected or substituted. Model data transfer is opt-in configuration. Usage reports preserve provider token counters; no unverified dollar cost is invented.

Optional search: HOUNDSCRAPER_SEARCH_PROVIDER=exa|brave|searxng and its key or operator-controlled SearXNG endpoint. Search provider infrastructure/licenses are separate from this Apache-2.0 project.

Webhook receiver verification: HMAC-SHA256(key, timestamp + '.' + eventId + '.' + exactBody). Compare against X-Hound-Signature after removing sha256=. Verify X-Hound-Timestamp within five minutes and deduplicate X-Hound-Event. The signing key is HOUNDSCRAPER_WEBHOOK_KEY; it is distinct from API and encryption keys.

The default reference deployment has one API/embedded worker process. Shared PostgreSQL queue reservations support recovery, but global per-origin pacing across independent worker processes is a later release gate. Do not advertise this reference as a hostile multi-tenant SaaS deployment.
