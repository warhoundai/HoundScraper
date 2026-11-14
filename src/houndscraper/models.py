from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .network import normalize_url

FORMATS = {'markdown','text','html','rawHtml','renderedHtml','rawBase64','links','images','metadata','tables','jsonld','attributes','screenshot','json','summary','product','branding','audio','video','captions'}
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

    @field_validator('include_selectors','exclude_selectors')
    @classmethod
    def valid_selectors(cls, values):
        import soupsieve
        for value in values:
            if len(value)>500:raise ValueError('Selector exceeds 500 characters')
            try:soupsieve.compile(value)
            except Exception:raise ValueError('Invalid CSS selector')
        return values

    @field_validator('attributes')
    @classmethod
    def valid_attributes(cls, values):
        import soupsieve
        for value in values:
            if set(value)!={'selector','attribute'} or len(value['selector'])>500 or len(value['attribute'])>100:raise ValueError('Attributes require bounded selector and attribute fields')
            try:soupsieve.compile(value['selector'])
            except Exception:raise ValueError('Invalid attribute selector')
        return values

    @field_validator('viewport')
    @classmethod
    def valid_viewport(cls, value):
        if set(value)!={'width','height'} or any(type(v) is not int for v in value.values()) or not 200<=value['width']<=3840 or not 200<=value['height']<=2160:raise ValueError('Use a bounded width/height viewport')
        return value

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
    max_agent_steps: int = Field(40,ge=1,le=500)
    max_provider_tokens: int = Field(200000,ge=1024,le=10000000)
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
