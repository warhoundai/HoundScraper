import asyncio
import fnmatch
import random
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from .errors import ScrapeError
from .models import Options
from .network import normalize_url,origin

class Worker:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store;self.tasks=set();self.stopping=False
        from .automation import Automation
        self.automation=Automation(engine)
    def links(self,item,result):
        request=item['request'];depth=item['depth']+1
        if item['kind'] not in ('crawl','map') or depth>request['max_depth']:return []
        seeds={origin(u) for u in request['urls']};out=[]
        for link in result.get('discovered_links',[]):
            try:
                url=normalize_url(link['url']);path=urlsplit(url).path
                if origin(url) not in seeds:continue
                if request['include_paths'] and not any(fnmatch.fnmatch(path,p) for p in request['include_paths']):continue
                if any(fnmatch.fnmatch(path,p) for p in request['exclude_paths']):continue
                out.append((url,depth))
            except ScrapeError:pass
        return out
    async def process(self,item):
        start=time.monotonic();current=asyncio.current_task()
        async def heartbeat():
            while True:
                await asyncio.sleep(2)
                if not self.store.heartbeat(item,self.engine.settings.lease_seconds):
                    current.cancel();return
        watch=asyncio.create_task(heartbeat())
        try:
            options=Options.model_validate(item['request']['options'])
            remaining=item['request']['max_download_bytes']-item['bytes']
            options.max_bytes=min(options.max_bytes,remaining,item['allowed_bytes'])
            if item['kind']=='map':options.formats=['links'];options.render='never'
            seconds=max(.001,item['request']['max_seconds']-item['spent_ms']/1000)
            async with asyncio.timeout(seconds):
                if urlsplit(item['url']).path.endswith('.xml'):
                    if not await self.engine.network.allowed(item['url'],not options.respect_robots):raise ScrapeError('ROBOTS_DENIED','Sitemap excluded by robots.txt',403)
                    response=await self.engine.network.fetch(item['url'],max_bytes=options.max_bytes)
                    if b'<!DOCTYPE' in response.body.upper() or b'<!ENTITY' in response.body.upper():raise ScrapeError('UNSAFE_XML','XML external entities are forbidden')
                    root=ET.fromstring(response.body);links=[]
                    for node in root.iter():
                        if node.tag.split('}')[-1]=='loc' and node.text:
                            try:links.append({'url':normalize_url(node.text.strip())})
                            except ScrapeError:pass
                    result={'url':item['url'],'data':{'links':links},'discovered_links':links,'acquisition':'sitemap','complete':True,'usage':{'download_bytes':len(response.body)}}
                else:result=await self.engine.scrape(item['tenant'],item['url'],options)
            links=self.links(item,result)
            if item['depth']==0 and item['kind'] in ('crawl','map'):
                sitemap=origin(item['url'])+'/sitemap.xml'
                if sitemap!=item['url']:links.append((sitemap,item['depth']))
            self.store.finish(item,result,links,elapsed_ms=round((time.monotonic()-start)*1000))
        except asyncio.CancelledError:
            self.store.retry(item,0)
            raise
        except ScrapeError as e:
            if e.retryable and item['attempts']<3:self.store.retry(item,getattr(e,'retry_after',min(60,2**item['attempts']+random.random())))
            else:self.store.finish(item,{'url':item['url'],'error':{'code':e.code,'message':e.message},'complete':False},error=True,elapsed_ms=round((time.monotonic()-start)*1000))
        except TimeoutError:
            self.store.finish(item,{'url':item['url'],'error':{'code':'TIME_BUDGET','message':'Execution budget exhausted'},'complete':False},error=True,elapsed_ms=round((time.monotonic()-start)*1000))
        except Exception:
            self.store.finish(item,{'url':item['url'],'error':{'code':'PROCESSING_FAILED','message':'Page processing failed; inspect server diagnostics'},'complete':False},error=True)
        finally:
            watch.cancel();await asyncio.gather(watch,return_exceptions=True)
    async def run(self):
        self.store.recover();last_cleanup=0
        try:
            while not self.stopping:
                self.store.recover();self.store.settle()
                await self.automation.tick();await self.automation.deliver()
                if time.monotonic()-last_cleanup>3600:
                    self.store.expire(self.engine.settings.retention_days);self.engine.artifacts.expire(self.engine.settings.retention_days);last_cleanup=time.monotonic()
                while len(self.tasks)<self.engine.settings.workers:
                    item=self.store.claim(self.engine.settings.lease_seconds)
                    if not item:break
                    task=asyncio.create_task(self.process(item));self.tasks.add(task);task.add_done_callback(self.tasks.discard)
                await asyncio.sleep(.15 if self.tasks else .5)
        finally:
            for task in list(self.tasks):task.cancel()
            await asyncio.gather(*self.tasks,return_exceptions=True)
