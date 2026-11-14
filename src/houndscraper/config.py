import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from .errors import ScrapeError

@dataclass
class Settings:
    database: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_DATABASE_URL', ''))
    keys: dict = field(default_factory=lambda: json.loads(os.environ.get('HOUNDSCRAPER_API_KEYS', '{}')))
    storage: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_STORAGE', './data'))
    encryption_key: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_ENCRYPTION_KEY', ''))
    workers: int = 8
    lease_seconds: int = 120
    retention_days: int = 7
    allow_robots_override: bool = False
    browser_endpoint: str = field(default_factory=lambda: os.environ.get('HOUNDBROWSER_ENDPOINT', ''))
    browser_key: str = field(default_factory=lambda: os.environ.get('HOUNDBROWSER_SERVICE_KEY', ''))
    provider_endpoint: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_LLM_ENDPOINT', ''))
    provider_key: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_LLM_KEY', ''))
    provider_model: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_LLM_MODEL', ''))
    search_provider: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_SEARCH_PROVIDER', ''))
    search_key: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_SEARCH_KEY', ''))
    search_endpoint: str = field(default_factory=lambda: os.environ.get('HOUNDSCRAPER_SEARCH_ENDPOINT', ''))

    def validate(self):
        if not self.database or not self.keys or any(not isinstance(v, str) or len(v) < 32 for v in self.keys.values()):
            raise ValueError('Configure PostgreSQL and independent tenant API keys of at least 32 characters')
        if self.workers < 1 or self.workers > 64:
            raise ValueError('Worker concurrency must be 1–64')
        return self

    def tenant(self, authorization):
        candidate = hashlib.sha256(authorization.removeprefix('Bearer ').encode()).digest()
        found = None
        for tenant, key in self.keys.items():
            if hmac.compare_digest(candidate, hashlib.sha256(key.encode()).digest()):
                found = tenant
        if not authorization.startswith('Bearer ') or found is None:
            raise ScrapeError('UNAUTHORIZED', 'A valid API key is required', 401)
        return found
