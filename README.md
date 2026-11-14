<div align="center">

# HoundScraper

### Web data. Under your control.

Clean content, persistent crawls, and inspectable sources for AI agents.

[Documentation](https://ops.warhoundai.com/docs/houndscraper) · [API](docs/api.md) · [Self-hosting](docs/deployment.md) · [Capabilities](docs/capabilities.md) · [Security](SECURITY.md)

[![Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-white)](LICENSE)

</div>

HoundScraper is independently implemented web data infrastructure. Fetch a page as Markdown, preserve code and tables, discover URLs, or run a persistent crawl with results you can trace back to their source. Core collection requires no model provider, WarHound account or subscription.

```text
Your agent / application
          ↓ HTTP · Python · JavaScript · CLI · MCP
HoundScraper → PostgreSQL jobs and checkpoints
          ↓              ↓                    ↓
      HTTP fetch    optional browser     optional parser / AI
          ↓
Content · metadata · hashes · evidence · usage
```

## Why HoundScraper?

- **Fast path first.** HTTP collection without an inference call; render only when needed.
- **Work that survives a restart.** PostgreSQL leases, deduplicated frontiers, idempotent jobs and resumable budgets.
- **Traceable output.** Original response hash, final URL, timestamps, acquisition method, artifacts and explicit partial results.
- **Your infrastructure.** Docker Compose, a React dashboard, SDKs, CLI and MCP stdio; provider keys are optional.
- **Explicit boundaries.** Public-only pinned-DNS networking, origin-bound encrypted credentials and separate execution workers.

## Start locally

```sh
git clone https://github.com/warhoundai/HoundScraper.git
cd HoundScraper
python scripts/configure.py
docker compose up --build -d
```

Open http://127.0.0.1:8081. Read your locally generated instance key from .env and enter it in the dashboard. The key remains in page memory. Keep .env private. Enable HTTPS and access controls before exposing the instance remotely.

Install the Python client from this checkout (registry publication is not implied):

```sh
pip install -e .
export HOUNDSCRAPER_API_KEY='your-local-instance-key'
houndscraper scrape https://example.com --format markdown
```

```python
import os
from houndscraper.client import Client

with Client(api_key=os.environ['HOUNDSCRAPER_API_KEY']) as scraper:
    page = scraper.scrape('https://example.com', formats=['markdown', 'tables'])
    print(page['data']['markdown'])
    job = scraper.submit('crawl', ['https://example.com'], max_pages=100)
    status = scraper.wait(job['id'])
    for page in scraper.results(job['id']):
        print(page['url'], page.get('sha256'), page.get('error'))
```

JavaScript source client: `sdk/js/index.mjs`; types are included. Call `new HoundScraper({baseUrl, apiKey})`, then `scrape`, `submit`, `wait` and `results`.

## Connect an AI agent

Configure your MCP client to run `houndscraper mcp` with HOUNDSCRAPER_ENDPOINT and HOUNDSCRAPER_API_KEY in its environment. Tools read pages, submit jobs, inspect results and cancel work. Credentials are never included in tool arguments or page content.

## What ships today?

This is an initial **0.1.0** release, not a claim of complete Firecrawl parity. Core scraping, persistent jobs, clients and the dashboard are implemented. Optional browser rendering has a real Chromium fixture suite. AI/search require configured providers; document/OCR qualification, native Gemini/Vertex, media, S3 and autonomous agents remain staged work. The [capability matrix](docs/capabilities.md) and [roadmap](docs/roadmap.md) state the boundary explicitly.

The [Firecrawl v2 adapter](docs/compatibility.md) supports a documented subset and rejects unsupported options. No Firecrawl implementation or proprietary WarHound backend is included.

## Develop and contribute

See [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/architecture.md), [dependency inventory](docs/dependencies.json), and [third-party notices](THIRD_PARTY_NOTICES.md). Report vulnerabilities privately through the repository’s security reporting feature.
