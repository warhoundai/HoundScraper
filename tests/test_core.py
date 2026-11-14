import asyncio
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import httpx
import pytest
from houndscraper.api import create_app
from houndscraper.content import extract
from houndscraper.database import fingerprint
from houndscraper.engine import Engine
from houndscraper.errors import ScrapeError
from houndscraper.models import Options,JobRequest
from houndscraper.network import Network,PublicResolver,Response,normalize_url
from houndscraper.worker import Worker

HTML=b'''<html lang="en"><head><title>Fixture</title><script type="application/ld+json">{"@type":"Product","name":"Hound"}</script></head><body><nav>noise</nav><main><h1>Read me</h1><p>Verified fixture content with enough useful words to avoid a browser fallback. This page is controlled by the test suite and contains real evidence.</p><pre><code>print(42)</code></pre><table><tr><th>Name</th><th>Value</th></tr><tr><td>Count</td><td>42</td></tr></table><a href="/next">Next</a><script>alert(1)</script></main></body></html>'''
class FixtureNetwork:
    def __init__(self):self.calls=0;self.allowed_calls=0
    async def allowed(self,*args):self.allowed_calls+=1;return True
    async def fetch(self,url,**kwargs):
        self.calls+=1
        if url.endswith('sitemap.xml'):return Response(url,200,{'content-type':'application/xml'},b'<urlset><url><loc>https://fixture.example/next</loc></url></urlset>',.01)
        return Response(url,200,{'content-type':'text/html'},HTML,.01)

@pytest.mark.parametrize('url',['http://127.0.0.1','http://[::1]','http://169.254.169.254','https://user:pass@example.com','file:///etc/passwd','http://10.1.2.3','http://2130706433','http://example.com:8080','https://a.local','http://[::ffff:127.0.0.1]'])
def test_private_destinations_rejected(url):
    with pytest.raises(ScrapeError):normalize_url(url)
def test_url_normalization():assert normalize_url('https://EXAMPLE.com:443/a#b')=='https://example.com/a'
def test_deterministic_extraction():
    out,internal,warnings=extract(HTML,'https://fixture.example/',Options(formats=['markdown','tables','jsonld','product','links']))
    assert '# Read me' in out['markdown'] and 'print(42)' in out['markdown']
    assert 'noise' not in out['markdown'] and 'alert' not in out['markdown']
    assert out['tables'][0][1]==['Count','42'] and out['product']['name']=='Hound'
    assert out['links'][0]['url']=='https://fixture.example/next'
@pytest.mark.asyncio
async def test_resolver_rejects_mixed_public_private():
    loop=asyncio.get_running_loop()
    with patch.object(loop,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',80)),(2,1,6,'',('127.0.0.1',80))]):
        with pytest.raises(ScrapeError):await PublicResolver().resolve('example.com',80)

def test_idempotency_and_tenant_isolation(store):
    value=JobRequest(kind='batch',urls=['https://fixture.example/'])
    first=store.create('alpha',value,'one');assert store.create('alpha',value,'one')['id']==first['id']
    with pytest.raises(ScrapeError):store.create('alpha',JobRequest(kind='batch',urls=['https://fixture.example/next']),'one')
    with pytest.raises(ScrapeError):store.get('beta',first['id'])
    assert store.create('beta',value,'one')['id']!=first['id']

def test_concurrent_claims_do_not_exceed_page_budget(store):
    job=store.create('alpha',JobRequest(kind='batch',urls=[f'https://fixture.example/{i}' for i in range(10)],max_pages=2))
    with ThreadPoolExecutor(max_workers=8) as pool:claims=list(pool.map(lambda _:store.claim(),range(8)))
    claimed=[c for c in claims if c]
    # SKIP LOCKED may return no work while another claimant holds the job row.
    # It promises nonblocking claims and a ceiling, not simultaneous saturation.
    assert 1<=len(claimed)<=2
    while (next_item:=store.claim()) is not None:claimed.append(next_item)
    assert len(claimed)==2
    assert store.get('alpha',job['id'])['inflight']==2

def test_leases_recover_and_old_worker_cannot_commit(store):
    job=store.create('alpha',JobRequest(kind='batch',urls=['https://fixture.example/']))
    old=store.claim(-1);assert store.recover()==1;new=store.claim()
    assert not store.finish(old,{'data':'old'})
    assert store.finish(new,{'data':'new'})
    store.settle();assert store.get('alpha',job['id'])['status']=='completed'
    assert store.results('alpha',job['id'])[0]['result']['data']=='new'

def test_pause_cancel_and_budget_resume(store):
    job=store.create('alpha',JobRequest(kind='batch',urls=['https://fixture.example/a','https://fixture.example/b'],max_pages=1))
    item=store.claim();store.transition('alpha',job['id'],'pause');assert not store.finish(item,{'data':'discard'})
    assert store.claim() is None
    store.transition('alpha',job['id'],'resume');item=store.claim();store.finish(item,{'data':'first'});store.settle()
    assert store.get('alpha',job['id'])['status']=='partial'
    store.transition('alpha',job['id'],'resume',{'max_pages':2});item=store.claim();store.finish(item,{'data':'second'});store.settle()
    assert store.get('alpha',job['id'])['status']=='completed'

@pytest.mark.asyncio
async def test_real_engine_cache_and_credential_isolation(store,settings):
    network=FixtureNetwork();engine=Engine(settings,store,network)
    one=await engine.scrape('alpha','https://fixture.example/',Options(render='never'))
    two=await engine.scrape('alpha','https://fixture.example/',Options(render='never'))
    assert one['sha256']==hashlib.sha256(HTML).hexdigest() and two['cache']['hit']
    assert network.calls==1
    await engine.scrape('beta','https://fixture.example/',Options(render='never'));assert network.calls==2
    engine.credentials.put('alpha','login','https://fixture.example',{'Cookie':'session=synthetic'})
    with store.pool.connection() as c:assert 'synthetic' not in c.execute('SELECT ciphertext FROM hs_credentials').fetchone()['ciphertext']
    with pytest.raises(ScrapeError):engine.credentials.get('beta','login','https://fixture.example')
    with pytest.raises(ScrapeError):engine.credentials.get('alpha','login','https://other.example')
    for _ in range(2):await engine.scrape('alpha','https://fixture.example/',Options(render='never',credential_profile='login'))
    assert network.calls==4

@pytest.mark.asyncio
async def test_worker_crawl_checkpoint_and_dedup(store,settings):
    engine=Engine(settings,store,FixtureNetwork());worker=Worker(engine)
    job=store.create('alpha',JobRequest(kind='crawl',urls=['https://fixture.example/'],max_pages=10,options=Options(render='never')))
    for _ in range(10):
        item=store.claim()
        if not item:break
        await worker.process(item);store.settle()
    row=store.get('alpha',job['id']);assert row['status']=='completed' and row['processed']==3
    assert len(store.results('alpha',job['id']))==3

@pytest.mark.asyncio
async def test_api_auth_schema_jobs_artifacts(store,settings):
    engine=Engine(settings,store,FixtureNetwork());app=create_app(settings,store=store,engine=engine,run_worker=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://instance.example') as c:
        assert (await c.get('/v1/jobs')).status_code==401
        assert (await c.get('/')).status_code==200
        headers={'Authorization':'Bearer '+'a'*40}
        r=await c.post('/v1/scrape',headers=headers,json={'url':'https://fixture.example/','options':{'render':'never'}})
        assert r.status_code==200 and '# Read me' in r.json()['data']['markdown']
        assert (await c.post('/v1/scrape',headers=headers,json={'url':'http://127.0.0.1'})).status_code==403
        assert (await c.post('/v1/scrape',headers=headers,json={'url':'https://fixture.example','options':{'unknown':1}})).status_code==422
        r=await c.post('/v1/jobs',headers=headers,json={'kind':'batch','urls':['https://fixture.example/']});assert r.status_code==202
        jid=r.json()['id'];assert (await c.get('/v1/jobs/'+jid,headers={'Authorization':'Bearer '+'b'*40})).status_code==404
        artifact=engine.artifacts.put('alpha',b'evidence','text/plain')
        assert (await c.get(artifact['url'],headers=headers)).content==b'evidence'
        assert (await c.get(artifact['url'],headers={'Authorization':'Bearer '+'b'*40})).status_code==404

@pytest.mark.asyncio
async def test_real_http_download_decoding_redirect_and_cancel():
    import socket
    from aiohttp import web
    class LocalFixtureResolver:
        async def resolve(self,host,port=0,family=0):return [{'hostname':host,'host':'127.0.0.1','port':fixture_port,'family':socket.AF_INET,'proto':0,'flags':0}]
        async def close(self):pass
    app=web.Application();app.router.add_get('/page',lambda r:web.Response(body=HTML,content_type='text/html'))
    app.router.add_get('/redirect',lambda r:web.HTTPFound('/page'))
    app.router.add_get('/big',lambda r:web.Response(body=b'x'*10000))
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();fixture_port=site._server.sockets[0].getsockname()[1]
    try:
        n=Network(resolver=LocalFixtureResolver());r=await n.fetch('http://fixture.example/redirect');assert r.body==HTML and r.url.endswith('/page')
        with pytest.raises(ScrapeError):await n.fetch('http://fixture.example/big',max_bytes=1024)
    finally:await runner.cleanup()

def test_concurrent_byte_reservations(store):
    store.create('alpha',JobRequest(kind='batch',urls=[f'https://fixture.example/{i}' for i in range(5)],max_download_bytes=2048,options=Options(max_bytes=2048)))
    with ThreadPoolExecutor(max_workers=5) as pool:items=list(pool.map(lambda _:store.claim(),range(5)))
    claimed=[i for i in items if i];assert len(claimed)==1 and claimed[0]['allowed_bytes']==2048
    store.finish(claimed[0],{'usage':{'download_bytes':1024}})
    item=store.claim();assert item['allowed_bytes']==1024
    store.finish(item,{'usage':{'download_bytes':1024}});store.settle()
    assert store.claim() is None

@pytest.mark.asyncio
async def test_compatibility_rejects_unknown_options(store,settings):
    app=create_app(settings,store=store,engine=Engine(settings,store,FixtureNetwork()),run_worker=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://instance.example',headers={'Authorization':'Bearer '+'a'*40}) as c:
        r=await c.post('/compat/firecrawl/v2/scrape',json={'url':'https://fixture.example/','formats':['markdown']})
        assert r.status_code==200 and r.json()['success'] and '# Read me' in r.json()['data']['markdown']
        r=await c.post('/compat/firecrawl/v2/scrape',json={'url':'https://fixture.example/','stealth':True})
        assert r.status_code==422 and r.json()['error']['code']=='UNSUPPORTED_OPTION'

@pytest.mark.asyncio
async def test_model_extraction_rejects_fabricated_quotes(settings):
    from houndscraper.providers import Providers
    settings.provider_endpoint='https://model.example/v1';settings.provider_model='fixture'
    response=httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'data':{'name':'fake'},'evidence':[{'path':'name','quote':'not in source','url':'https://fixture.example/'}]})}}]})
    with patch('httpx.AsyncClient.post',return_value=response):
        with pytest.raises(ScrapeError) as error:await Providers(settings).extract('Actual source content','https://fixture.example/')
    assert error.value.code=='EXTRACTION_UNVERIFIED'

@pytest.mark.asyncio
async def test_real_browser_render_and_grant_replay():
    import os,socket
    from aiohttp import web
    from houndscraper.browser_worker import create_browser_app,sign
    from houndscraper.browser_network import PublicProxy
    os.environ.setdefault('BROWSER_EXECUTABLE','/usr/bin/chromium')
    async def page(request):return web.Response(text='<html><head><title>Browser fixture</title></head><body><main id="result">Loading</main><script>document.querySelector("#result").textContent="Rendered evidence"</script><input type="password" value="synthetic-secret"></body></html>',content_type='text/html')
    webapp=web.Application();webapp.router.add_get('/',page);runner=web.AppRunner(webapp);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
    async def resolver(host,unused):return ['127.0.0.1']
    async def connector(ip,unused):return await asyncio.open_connection(ip,port)
    key='c'*40;app=create_browser_app(key,lambda:PublicProxy(resolver=resolver,connector=connector))
    grant={'url':'http://fixture.example/','tenant':'alpha','options':{'formats':['screenshot','branding'],'wait_selector':'#result'},'expires':time.time()+60,'nonce':'fixture-one'};grant['signature']=sign(grant,key)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://browser.example') as c:
            response=await c.post('/v1/browser/scrape',json=grant);assert response.status_code==200,response.text
            value=response.json();assert 'Rendered evidence' in value['html'];assert value['screenshot'] and value['branding']['title']=='Browser fixture'
            assert (await c.post('/v1/browser/scrape',json=grant)).status_code==401
            bad={**grant,'nonce':'modified'};assert (await c.post('/v1/browser/scrape',json=bad)).status_code==401
    finally:await runner.cleanup()

@pytest.mark.asyncio
async def test_monitor_diff_and_webhook_signature(store,settings,monkeypatch):
    from houndscraper.automation import Automation
    monkeypatch.setenv('HOUNDSCRAPER_WEBHOOK_KEY','w'*40)
    engine=Engine(settings,store,FixtureNetwork());automation=Automation(engine)
    monitor=automation.create_monitor('alpha',JobRequest(kind='batch',urls=['https://fixture.example/'],webhook='https://callback.example/'),'*/5 * * * *')
    with store.pool.connection() as c:c.execute('UPDATE hs_monitors SET next_run=0 WHERE id=%s',(monitor['id'],))
    await automation.tick();item=store.claim();assert item
    store.finish(item,{'url':item['url'],'content_sha256':'digest','complete':True});store.settle();await automation.tick()
    with store.pool.connection() as c:
        m=c.execute('SELECT previous FROM hs_monitors WHERE id=%s',(monitor['id'],)).fetchone()['previous']
        assert m['changes'][0]['status']=='new'
    sent={}
    async def fetch(url,**kwargs):sent.update(kwargs);return Response(url,204,{},b'',.01)
    engine.network.fetch=fetch;await automation.deliver()
    import hmac
    body=sent['body'];headers=sent['headers'];expected=hmac.new(('w'*40).encode(),(headers['X-Hound-Timestamp']+'.'+headers['X-Hound-Event']+'.').encode()+body,hashlib.sha256).hexdigest()
    assert headers['X-Hound-Signature']=='sha256='+expected
    with store.pool.connection() as c:assert c.execute('SELECT state FROM hs_outbox').fetchone()['state']=='delivered'

@pytest.mark.parametrize('value',[{'json_schema':{'$ref':'http://127.0.0.1/secret'}},{'include_selectors':['[invalid']},{'attributes':[{'selector':'main'}]},{'viewport':{'width':100000,'height':900}}])
def test_unsafe_or_invalid_options_fail_before_execution(value):
    with pytest.raises(ValueError):Options.model_validate(value)

def test_full_content_preserves_navigation_when_requested():
    out,_,_=extract(HTML,'https://fixture.example/',Options(formats=['text'],only_main_content=False))
    assert 'noise' in out['text']
