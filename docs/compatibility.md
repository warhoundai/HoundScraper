# Firecrawl v2 compatibility subset

Base URL: `https://your-instance/compat/firecrawl/v2`. Use your HoundScraper API key. This is not a promise that every Firecrawl SDK method works unchanged.

Implemented: POST /scrape; POST /crawl; POST /batch/scrape; GET and DELETE /crawl/{id} and /batch/scrape/{id}. Scrape supports string formats, onlyMainContent, includeTags, excludeTags, maxAge, and timeout. Crawl accepts url/urls, limit, maxDiscoveryDepth, includePaths, excludePaths and supported scrapeOptions.

Unknown fields and object formats return UNSUPPORTED_OPTION. Native map is asynchronous, so synchronous Firecrawl map compatibility is explicitly rejected. Search, agent, monitor, provider-specific options, cloud model names and compatibility result sets of 100 or more rows are not supported; use native APIs and cursor pagination.

Native APIs retain full provenance and error details. The compatibility projection does not invent billing credits or duplicate Firecrawl's proprietary behavior.
