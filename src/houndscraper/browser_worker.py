"""Isolated API worker using HoundBrowser's public pinned-DNS proxy."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlsplit
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from .network import normalize_url,origin
from .errors import ScrapeError

def sign(value,key):return hmac.new(key.encode(),json.dumps(value,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
def create_browser_app(key=None,proxy_factory=None):
    key=key or os.environ.get('HOUNDBROWSER_SERVICE_KEY','')
    if len(key)<32:raise ValueError('Configure an independent browser service key of at least 32 characters')
    if proxy_factory is None:
        from .browser_network import PublicProxy
        proxy_factory=PublicProxy
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);nonces={};capacity=asyncio.Semaphore(2)
    @app.exception_handler(ScrapeError)
    async def error(request,e):return JSONResponse({'error':e.code,'message':e.message},status_code=e.status)
    @app.get('/health')
    async def health():return {'status':'ok'}
    @app.post('/v1/browser/scrape')
    async def scrape(request:Request):
        raw=await request.body()
        if len(raw)>65536:raise ScrapeError('TOO_LARGE','Scope grant exceeds 64 KiB',413)
        value=json.loads(raw);signature=value.pop('signature','')
        if not hmac.compare_digest(signature,sign(value,key)):raise ScrapeError('INVALID_GRANT','Invalid scope grant',401)
        now=time.time();expires=value.get('expires',0);nonce=value.get('nonce','')
        for n,expiry in list(nonces.items()):
            if expiry<now:nonces.pop(n,None)
        if not nonce or nonce in nonces or not now<expires<=now+90:raise ScrapeError('INVALID_GRANT','Expired or replayed scope grant',401)
        nonces[nonce]=expires
        url=normalize_url(value['url']);target=origin(url);opts=value.get('options',{});viewport=opts.get('viewport',{})
        width,height=int(viewport.get('width',1280)),int(viewport.get('height',900))
        if not 200<=width<=3840 or not 200<=height<=2160:raise ScrapeError('INVALID_VIEWPORT','Viewport is outside the permitted range')
        headers=value.get('credential_headers',{})
        if any(k.lower() not in ('authorization','cookie','accept-language') for k in headers):raise ScrapeError('INVALID_HEADERS','Unsupported credential header')
        async with capacity:
            from playwright.async_api import async_playwright
            parent=asyncio.current_task()
            async def disconnected():
                while True:
                    await asyncio.sleep(.5)
                    if await request.is_disconnected():parent.cancel();return
            disconnect_watch=asyncio.create_task(disconnected())
            proxy=proxy_factory();browser=None;p=None
            original_connector=proxy.connector;downloaded=0;available=int(opts.get('max_bytes',33554432))
            class BudgetReader:
                def __init__(self,reader):self.reader=reader
                async def read(self,n=65536):
                    nonlocal available,downloaded
                    allowance=min(n,available)
                    if allowance<=0:raise ScrapeError('BYTE_BUDGET','Browser transport budget exhausted',413)
                    available-=allowance
                    data=await self.reader.read(allowance)
                    available+=allowance-len(data);downloaded+=len(data)
                    return data
            async def connector(*args,**kwargs):
                reader,writer=await original_connector(*args,**kwargs)
                return BudgetReader(reader),writer
            proxy.connector=connector;server=await proxy.start()
            try:
                async with asyncio.timeout(min(300,max(1,opts.get('browser_timeout_seconds',60)))):
                    p=await async_playwright().start()
                    browser=await p.chromium.launch(headless=True,**({'executable_path':os.environ['BROWSER_EXECUTABLE']} if os.environ.get('BROWSER_EXECUTABLE') else {}),proxy={'server':server},args=['--proxy-bypass-list=<-loopback>','--disable-quic','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],env={k:os.environ[k] for k in ('PATH','HOME','LANG','TZ','TMPDIR') if k in os.environ})
                    context=await browser.new_context(viewport={'width':width,'height':height},locale=opts.get('locale','en-US'),timezone_id=opts.get('timezone','UTC'),service_workers='block',accept_downloads=False)
                    async def guard(route):
                        r=route.request
                        try:
                            normalize_url(r.url)
                            if r.method not in ('GET','HEAD') or (r.is_navigation_request() and origin(r.url)!=target):return await route.abort()
                            clean={k:v for k,v in r.headers.items() if k.lower() not in ('authorization','cookie','proxy-authorization')}
                            if origin(r.url)==target and headers:return await route.continue_(headers={**clean,**{k.lower():v for k,v in headers.items()}})
                            if origin(r.url)!=target:return await route.continue_(headers=clean)
                            await route.continue_()
                        except Exception:await route.abort()
                    await context.route('**/*',guard)
                    page=await context.new_page();await page.goto(url,wait_until='domcontentloaded')
                    if opts.get('wait_selector'):await page.locator(opts['wait_selector']).first.wait_for(state='attached')
                    for action in opts.get('actions',[]):
                        kind=action.get('type');selector=action.get('selector','')
                        if kind=='click':await page.locator(selector).first.click()
                        elif kind=='scroll':await page.mouse.wheel(0,min(10000,max(-10000,int(action.get('pixels',800)))))
                        elif kind=='wait':await asyncio.sleep(min(5,max(0,float(action.get('seconds',1)))))
                        elif kind=='type':await page.locator(selector).first.fill(str(action.get('text',''))[:10000])
                        elif kind=='select':await page.locator(selector).first.select_option(str(action.get('value','')))
                        elif kind=='key' and action.get('key') in ('Enter','Tab','Escape','ArrowDown','ArrowUp','PageDown'):await page.keyboard.press(action['key'])
                        else:raise ScrapeError('UNSUPPORTED_ACTION','Only explicit read-oriented browser actions are supported',422)
                    html=await page.content()
                    if len(html.encode())>8388608:raise ScrapeError('SNAPSHOT_TOO_LARGE','Rendered HTML exceeds 8 MiB',413)
                    result={'url':page.url,'html':html,'download_bytes':downloaded}
                    if 'screenshot' in opts.get('formats',[]):result['screenshot']=base64.b64encode(await page.screenshot(mask=[page.locator('input,textarea')])).decode()
                    if 'branding' in opts.get('formats',[]):
                        result['branding']=await page.evaluate("""()=>{const body=getComputedStyle(document.body);return {title:document.title,fonts:[...new Set([...document.querySelectorAll('h1,h2,p,button')].slice(0,100).map(x=>getComputedStyle(x).fontFamily))],colors:[...new Set([...document.querySelectorAll('body,h1,h2,a,button')].slice(0,100).map(x=>getComputedStyle(x).color))],background:body.backgroundColor,source:'computed_styles'}}""")
                    return result
            finally:
                if browser:await browser.close()
                if p:await p.stop()
                await proxy.close()
                disconnect_watch.cancel();await asyncio.gather(disconnect_watch,return_exceptions=True)
    return app
