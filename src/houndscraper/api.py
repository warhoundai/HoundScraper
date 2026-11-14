import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Request,Query
from fastapi.responses import JSONResponse,Response,StreamingResponse,FileResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from . import __version__
from .config import Settings
from .database import Store
from .engine import Engine
from .errors import ScrapeError
from .models import ScrapeRequest,JobRequest,Options,FORMATS
from .network import normalize_url,origin
from .worker import Worker

class SearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=2000)
    limit:int=Field(10,ge=1,le=100)
    scrape:bool=False
    options:Options=Field(default_factory=Options)

class ResumeRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    max_pages:int|None=Field(None,ge=1,le=1000000)
    max_seconds:int|None=Field(None,ge=1,le=86400)
    max_download_bytes:int|None=Field(None,ge=1024,le=107374182400)

def create_app(settings=None,*,store=None,engine=None,run_worker=True):
    cfg=(settings or Settings()).validate();db=store or Store(cfg.database);eng=engine or Engine(cfg,db);worker=Worker(eng)
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(worker.run()) if run_worker else None
        yield
        worker.stopping=True
        if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
        if store is None:db.close()
    app=FastAPI(title='HoundScraper',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=eng;app.state.store=db
    @app.middleware('http')
    async def authentication(request,call_next):
        try:
            if request.url.path not in ('/health','/','/sdk.mjs') and not request.url.path.startswith('/assets/'):
                request.state.tenant=cfg.tenant(request.headers.get('authorization',''))
                if request.method in ('POST','PUT','PATCH'):
                    body=bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body)>262144:raise ScrapeError('BODY_TOO_LARGE','JSON requests are limited to 256 KiB',413)
                    request._body=bytes(body)
            response=await call_next(request)
            response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"})
            return response
        except ScrapeError as e:return JSONResponse({'error':{'code':e.code,'message':e.message,'retryable':e.retryable}},status_code=e.status)
    @app.exception_handler(ScrapeError)
    async def known_error(request,e):return JSONResponse({'error':{'code':e.code,'message':e.message,'retryable':e.retryable}},status_code=e.status)
    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def validation(request,e):return JSONResponse({'error':{'code':'INVALID_REQUEST','message':'Request failed validation','fields':[{'location':v['loc'],'message':v['msg']} for v in e.errors()]}},status_code=422)
    @app.get('/health')
    async def health():
        with db.pool.connection() as c:c.execute('SELECT 1')
        return {'status':'ok','version':__version__}
    @app.get('/v1/openapi.json')
    async def openapi():return app.openapi()
    @app.get('/v1/capabilities')
    async def capabilities():return {'version':__version__,'formats':sorted(FORMATS),'core':['scrape','map','batch','crawl','jobs','events','credentials','artifacts','monitors'],'browser':bool(cfg.browser_endpoint),'ai_extraction':bool(cfg.provider_endpoint and cfg.provider_model),'search':bool(cfg.search_provider),'telemetry':False,'compatibility':'docs/compatibility.md'}
    @app.post('/v1/scrape')
    async def scrape(value:ScrapeRequest,request:Request):
        async with asyncio.timeout(value.options.browser_timeout_seconds+value.options.timeout_seconds+125):
            return await eng.scrape(request.state.tenant,value.url,value.options)
    from .automation import Automation
    automation=Automation(eng)
    @app.post('/v1/monitors',status_code=201)
    async def monitor_create(request:Request):
        raw=await request.json()
        if set(raw)-{'job','schedule','timezone'}:raise ScrapeError('INVALID_REQUEST','Unknown monitor option')
        job=JobRequest.model_validate(raw.get('job',{}))
        return automation.create_monitor(request.state.tenant,job,raw.get('schedule',''),raw.get('timezone','UTC'))
    @app.get('/v1/monitors')
    async def monitor_list(request:Request):
        with db.pool.connection() as c:rows=c.execute('SELECT * FROM hs_monitors WHERE tenant=%s ORDER BY id',(request.state.tenant,)).fetchall()
        return {'data':rows}
    @app.delete('/v1/monitors/{mid}',status_code=204)
    async def monitor_delete(mid:str,request:Request):
        with db.pool.connection() as c:c.execute('DELETE FROM hs_monitors WHERE id=%s AND tenant=%s',(mid,request.state.tenant))
        return Response(status_code=204)
    async def submit(value,request):
        if value.webhook and len(automation.key)<32:raise ScrapeError('WEBHOOK_NOT_CONFIGURED','Configure an independent webhook signing key',503)
        if value.kind=='extract' and 'json' not in value.options.formats:value.options.formats.append('json')
        if value.kind in ('search','agent'):
            found=await eng.providers.search(value.query,limit=min(value.max_pages,100));value.urls=[v['url'] for v in found['results']]
        if not value.urls:raise ScrapeError('INVALID_REQUEST','At least one seed URL is required')
        if value.kind=='agent':raise ScrapeError('CAPABILITY_UNAVAILABLE','Autonomous agent release is not enabled in the core release',501)
        if not value.options.respect_robots and not cfg.allow_robots_override:raise ScrapeError('POLICY_BLOCKED','Robots override requires operator configuration',403)
        row=db.create(request.state.tenant,value,request.headers.get('idempotency-key'))
        return JSONResponse(row,status_code=202)
    @app.post('/v1/jobs',status_code=202)
    async def jobs(value:JobRequest,request:Request):return await submit(value,request)
    for kind in ('batch','crawl','map','extract'):
        def endpoint(k):
            async def handler(value:JobRequest,request:Request):
                if value.kind!=k:raise ScrapeError('INVALID_REQUEST','Job kind must match the endpoint')
                return await submit(value,request)
            return handler
        app.add_api_route('/v1/'+kind,endpoint(kind),methods=['POST'],status_code=202,name=kind)
    @app.post('/v1/search')
    async def search(value:SearchRequest,request:Request):
        result=await eng.providers.search(value.query,value.limit)
        if value.scrape:
            job=JobRequest(kind='search',urls=[r['url'] for r in result['results']],query=value.query,options=value.options,max_pages=value.limit)
            result['job']=db.create(request.state.tenant,job,request.headers.get('idempotency-key'))
        return result
    @app.get('/v1/jobs')
    async def list_jobs(request:Request,cursor:str='',limit:int=Query(30,ge=1,le=100)):
        rows=db.list(request.state.tenant,cursor,limit);return {'data':rows,'next_cursor':rows[-1]['id'] if len(rows)==limit else None}
    @app.get('/v1/jobs/{jid}')
    async def get_job(jid:str,request:Request):return db.get(request.state.tenant,jid)
    @app.get('/v1/jobs/{jid}/results')
    async def results(jid:str,request:Request,cursor:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
        rows=db.results(request.state.tenant,jid,cursor,limit);return {'data':rows,'next_cursor':rows[-1]['id'] if len(rows)==limit else None}
    @app.post('/v1/jobs/{jid}/pause')
    async def pause(jid:str,request:Request):return db.transition(request.state.tenant,jid,'pause')
    @app.post('/v1/jobs/{jid}/cancel')
    async def cancel(jid:str,request:Request):return db.transition(request.state.tenant,jid,'cancel')
    @app.post('/v1/jobs/{jid}/resume')
    async def resume(jid:str,value:ResumeRequest,request:Request):return db.transition(request.state.tenant,jid,'resume',value.model_dump(exclude_none=True))
    @app.delete('/v1/jobs/{jid}',status_code=204)
    async def delete(jid:str,request:Request):
        row=db.get(request.state.tenant,jid)
        if row['status'] in ('running','queued') or row['inflight']:raise ScrapeError('JOB_ACTIVE','Cancel the job and wait for workers before deleting',409)
        with db.pool.connection() as c:c.execute('DELETE FROM hs_jobs WHERE id=%s AND tenant=%s',(jid,request.state.tenant))
        return Response(status_code=204)
    @app.get('/v1/jobs/{jid}/events')
    async def events(jid:str,request:Request,after:int=Query(0,ge=0)):
        tenant=request.state.tenant;db.get(tenant,jid)
        try:after=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError:raise ScrapeError('INVALID_CURSOR','Invalid event cursor')
        async def stream():
            cursor=after
            while not await request.is_disconnected():
                rows=db.events(tenant,jid,cursor)
                for row in rows:
                    cursor=row['id'];yield f"id: {cursor}\nevent: {row['kind']}\ndata: {json.dumps(row['value'])}\n\n"
                if not rows and db.get(tenant,jid)['status'] in ('completed','partial','cancelled'):break
                yield ': keepalive\n\n';await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream')
    @app.get('/v1/artifacts/{aid}')
    async def artifact(aid:str,request:Request):
        body,row=eng.artifacts.get(request.state.tenant,aid)
        return Response(body,media_type=row['mime'],headers={'ETag':'"'+row['sha256']+'"','Content-Disposition':'attachment; filename="'+aid+'"'})
    @app.put('/v1/credentials/{name}')
    async def credential(name:str,request:Request):
        value=await request.json()
        if set(value)!={'origin','headers'} or not isinstance(value['headers'],dict):raise ScrapeError('INVALID_PROFILE','Provide origin and headers')
        target=origin(value['origin']);eng.credentials.put(request.state.tenant,name,target,value['headers']);return {'name':name,'origin':target,'configured':True}
    @app.delete('/v1/credentials/{name}',status_code=204)
    async def delete_credential(name:str,request:Request):
        with db.pool.connection() as c:c.execute('DELETE FROM hs_credentials WHERE tenant=%s AND name=%s',(request.state.tenant,name))
        return Response(status_code=204)
    static=Path(__file__).with_name('static')
    @app.get('/')
    async def dashboard():return FileResponse(static/'index.html')
    from fastapi.staticfiles import StaticFiles
    if (static/'assets').exists():app.mount('/assets',StaticFiles(directory=static/'assets'),name='dashboard-assets')
    for name in ('sdk.mjs',):
        def serve(n):
            async def handler():return FileResponse(static/n)
            return handler
        app.add_api_route('/'+name,serve(name),methods=['GET'],include_in_schema=False)
    from .compat import install
    install(app,eng,db)
    return app
