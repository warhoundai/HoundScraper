from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .network import normalize_url

FORMATS = {'markdown','text','html','rawHtml','renderedHtml','rawBase64','links','images','metadata','tables','jsonld','attributes','screenshot','json','summary','product','branding'}
class Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    formats: list[str] = Field(default_factory=lambda: ['markdown'], min_length=1, max_length=20)
    only_main_content: bool = True
    include_selectors: list[str] = Field(default_factory=list, max_length=30)
    exclude_selectors: list[str] = Field(default_factory=list, max_length=30)
    attributes: list[dict[str,str]] = Field(default_factory=list, max_length=30)
    render: Literal['auto','never','always'] = 'auto'
    timeout_seconds: float = Field(15, ge=1, le=120)
    browser_timeout_seconds: float = Field(60, ge=1, le=300)
    max_bytes: int = Field(33554432, ge=1024, le=268435456)
    max_age: int = Field(300, ge=0, le=86400)
    respect_robots: bool = True
    credential_profile: str | None = Field(None, max_length=100)
    json_schema: dict | None = None
    prompt: str | None = Field(None, max_length=10000)
    actions: list[dict] = Field(default_factory=list, max_length=40)
    viewport: dict = Field(default_factory=lambda: {'width':1280,'height':900})
    locale: str = 'en-US'
    timezone: str = 'UTC'
    wait_selector: str | None = Field(None, max_length=500)

    @field_validator('json_schema')
    @classmethod
    def safe_schema(cls, schema):
        def visit(value,depth=0):
            if depth>30:raise ValueError('Schema nesting exceeds 30 levels')
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('$ref','$dynamicRef','$recursiveRef') and (not isinstance(item,str) or not item.startswith('#')):raise ValueError('Remote schema references are forbidden')
                    visit(item,depth+1)
            elif isinstance(value,list):
                for item in value:visit(item,depth+1)
        if schema is not None:visit(schema)
        return schema

    @field_validator('formats')
    @classmethod
    def formats_known(cls, values):
        if not set(values) <= FORMATS:
            raise ValueError('Unsupported output format')
        return list(dict.fromkeys(values))

class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str
    options: Options = Field(default_factory=Options)
    @field_validator('url')
    @classmethod
    def valid_url(cls, v): return normalize_url(v)

class JobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['batch','crawl','map','extract','search','agent','parse']
    urls: list[str] = Field(default_factory=list, max_length=10000)
    options: Options = Field(default_factory=Options)
    max_pages: int = Field(1000, ge=1, le=1000000)
    max_depth: int = Field(10, ge=0, le=100)
    max_seconds: int = Field(900, ge=1, le=86400)
    max_download_bytes: int = Field(1073741824, ge=1024, le=107374182400)
    include_paths: list[str] = Field(default_factory=list, max_length=30)
    exclude_paths: list[str] = Field(default_factory=list, max_length=30)
    query: str | None = Field(None, max_length=2000)
    webhook: str | None = None
    @field_validator('urls')
    @classmethod
    def valid_urls(cls, values): return list(dict.fromkeys(normalize_url(v) for v in values))
    @field_validator('webhook')
    @classmethod
    def valid_webhook(cls, value): return normalize_url(value) if value else None

    @field_validator('options')
    @classmethod
    def enforce_read_options(cls, value): return value
