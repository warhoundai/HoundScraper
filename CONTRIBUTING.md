# Contributing

Use Python 3.12 and Node 22. Install requirements-dev.lock and `pip install --no-deps -e .`. Start an isolated PostgreSQL database named houndscraper_test, set HOUNDSCRAPER_TEST_DATABASE_URL, install Playwright Chromium, and run `pytest -q` and `node --test sdk/js/*.test.mjs`.

Dashboard: `cd dashboard && npm ci && npm run typecheck && npm run build -- --outDir ../src/houndscraper/static --emptyOutDir`.

Keep changes focused, include controlled fixtures and meaningful failure tests, and describe actual verification. Do not add target credentials, customer pages or proprietary WarHound integrations. Contributions are Apache 2.0. Third-party source requires provenance and a compatible license.

Do not label planned features as available. Extend docs/capabilities.md when a feature passes end-to-end acceptance. Keep protocol changes backward compatible or document a versioned migration.
