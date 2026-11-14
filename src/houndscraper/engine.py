import asyncio
import base64
import datetime
import hashlib
import json
import time
import uuid
import xml.etree.ElementTree as ET
from .content import extract,thin_content
from .database import fingerprint
from .errors import ScrapeError
from .models import Options
from .network import Network,origin,normalize_url
from .providers import Providers
from .storage import Artifacts,Credentials

class Engine:
    def __init__(self,settings,store,network=None):
        self.settings=settings;self.store=store;self.network=network or Network(settings.workers)
        self.artifacts=Artifacts(store,settings.storage);self.credentials=Credentials(store,settings.encryption_key);self.providers=Providers(settings)
    async def scrape(self,tenant,url,options=None):
        options=options or Options();start=time.monotonic();url=normalize_url(url)
        if not options.respect_robots and not self.settings.allow_robots_override:raise ScrapeError('POLICY_BLOCKED','Robots override requires operator configuration',403)
        cachekey=fingerprint({'url':url,'options':options.model_dump(exclude={'max_age'})})
        if not options.credential_profile and not options.actions and options.max_age:
            cached=self.store.cache_get(tenant,cachekey,options.max_age)
            if cached:
                cached['cache']={'hit':True};cached['usage']={'download_bytes':0,'elapsed_ms':round((time.monotonic()-start)*1000),'provider_tokens':{}}
                return cached
        if not await self.network.allowed(url,not options.respect_robots):raise ScrapeError('ROBOTS_DENIED','robots.txt excludes this URL',403)
        headers=self.credentials.get(tenant,options.credential_profile,origin(url)) if options.credential_profile else {}
        response=await self.network.fetch(url,timeout=options.timeout_seconds,max_bytes=options.max_bytes,headers=headers,destination_check=lambda target:self.network.allowed(target,not options.respect_robots))
        if response.status in (429,503):
            e=ScrapeError('UPSTREAM_THROTTLED','Target requested a retry',429,True)
            try:e.retry_after=min(3600,max(1,int(response.headers.get('retry-after','5'))))
            except ValueError:e.retry_after=5
            raise e
        if response.status>=400:raise ScrapeError('UPSTREAM_HTTP_ERROR',f'Target returned HTTP {response.status}',502)
        mime=response.headers.get('content-type','application/octet-stream').split(';')[0]
        body=response.body;acquisition='http';artifacts=[];browser_bytes=0
        if mime not in ('text/html','application/xhtml+xml'):
            if mime in ('text/plain','text/markdown','text/csv','application/json','application/xml','text/xml'):
                text=body.decode('utf-8',errors='replace');output={f:text for f in options.formats if f in ('text','markdown','rawHtml')};internals={'links':[],'text':text,'metadata':{}};warnings=[]
            else:
                return await self.parse_document(tenant,body,mime,url,options)
        else:
            output,internals,warnings=extract(body,response.url,options)
            needs_render=options.render=='always' or options.actions or bool(set(options.formats)&{'screenshot','renderedHtml','branding'}) or (options.render=='auto' and thin_content(internals['text'],body.decode('utf-8',errors='replace')))
            if needs_render:
                if not self.settings.browser_endpoint:
                    raise ScrapeError('CAPABILITY_UNAVAILABLE','This page or output needs a configured HoundBrowser service',503)
                browser_options=options.model_copy(update={'max_bytes':max(0,options.max_bytes-len(body))})
                snapshot=await self.browser(tenant,response.url,browser_options)
                browser_bytes=snapshot.get('download_bytes',0)
                output,internals,warnings=extract(snapshot['html'].encode(),snapshot['url'],options,True)
                acquisition='browser';response.url=snapshot['url']
                if 'rawHtml' in options.formats:output['rawHtml']=body.decode('utf-8',errors='replace')
                if 'screenshot' in options.formats:
                    shot=base64.b64decode(snapshot['screenshot']);artifact=self.artifacts.put(tenant,shot,'image/png');artifacts.append(artifact);output['screenshot']=artifact
                if 'branding' in options.formats:output['branding']=snapshot.get('branding',{})
        llm_usage={}
        if set(options.formats)&{'json','summary'}:
            schema=options.json_schema
            if 'summary' in options.formats and 'json' not in options.formats:schema={'type':'object','properties':{'summary':{'type':'string'}},'required':['summary']}
            extracted=await self.providers.extract(internals['text'],response.url,schema,options.prompt)
            output['extraction']=extracted;llm_usage=extracted['usage']
            if 'json' in options.formats:output['json']=extracted['data']
            if 'summary' in options.formats:output['summary']=extracted['data'].get('summary') if isinstance(extracted['data'],dict) else None
        result={'url':url,'final_url':response.url,'status':response.status,'content_type':mime,'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'acquisition':acquisition,'sha256':hashlib.sha256(body).hexdigest(),'content_sha256':hashlib.sha256(internals['text'].encode()).hexdigest(),'data':output,'metadata':internals['metadata'],'discovered_links':internals['links'],'warnings':warnings,'complete':not any(w.startswith('Discovery truncated') for w in warnings),'cache':{'hit':False},'artifacts':artifacts,'usage':{'download_bytes':len(body)+browser_bytes,'elapsed_ms':round((time.monotonic()-start)*1000),**llm_usage}}
        if not internals['text'].strip():result['warnings'].append('No readable text was extracted');result['complete']=False
        if not options.credential_profile and not options.actions:self.store.cache_put(tenant,cachekey,result)
        return result
    async def browser(self,tenant,url,options):
        import httpx
        cfg=self.settings
        async with httpx.AsyncClient(base_url=cfg.browser_endpoint,headers={'authorization':'Bearer '+cfg.browser_key},timeout=options.browser_timeout_seconds,trust_env=False) as client:
            # A task grant is created by the operator-configured browser service, never a target page.
            from .browser_worker import sign
            grant={'url':url,'tenant':tenant,'options':options.model_dump(),'expires':time.time()+60,'nonce':uuid.uuid4().hex}
            if options.credential_profile:grant['credential_headers']=self.credentials.get(tenant,options.credential_profile,origin(url))
            grant['signature']=sign(grant,cfg.browser_key)
            r=await client.post('/v1/browser/scrape',json=grant)
            if r.status_code>=400:raise ScrapeError('BROWSER_FAILED','HoundBrowser rejected or could not complete the scrape',r.status_code if r.status_code<500 else 502)
            return r.json()
    async def parse_document(self,tenant,body,mime,url,options):
        import httpx,os
        endpoint=os.environ.get('HOUNDSCRAPER_PARSER_ENDPOINT')
        if not endpoint:raise ScrapeError('CAPABILITY_UNAVAILABLE','Enable the isolated document parser profile for this content type',503)
        async with httpx.AsyncClient(timeout=120,trust_env=False) as client:
            r=await client.post(endpoint.rstrip('/')+'/parse',content=body,headers={'content-type':mime,'authorization':'Bearer '+os.environ.get('HOUNDSCRAPER_PARSER_KEY','')})
        if r.status_code>=400:raise ScrapeError('PARSER_FAILED','Document parsing failed',422)
        data=r.json();artifact=self.artifacts.put(tenant,body,mime)
        return {'url':url,'final_url':url,'status':200,'content_type':mime,'acquisition':'document','sha256':hashlib.sha256(body).hexdigest(),'data':data,'metadata':{'pages':data.get('pages')},'discovered_links':[],'warnings':data.get('warnings',[]),'complete':data.get('complete',True),'cache':{'hit':False},'artifacts':[artifact],'usage':{'download_bytes':len(body)}}
