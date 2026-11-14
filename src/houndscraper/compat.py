"""Explicit Firecrawl v2 subset. Unknown fields are errors, not silent no-ops."""
from fastapi import Request
from .errors import ScrapeError
from .models import Options,JobRequest
FIELDS={'formats','onlyMainContent','includeTags','excludeTags','maxAge','timeout'}
def options(value):
    opts={}
    mapping={'onlyMainContent':'only_main_content','includeTags':'include_selectors','excludeTags':'exclude_selectors','maxAge':'max_age'}
    for key,target in mapping.items():
        if key in value:opts[target]=value[key]
    if 'timeout' in value:opts['timeout_seconds']=value['timeout']/1000
    if 'formats' in value:
        if not all(isinstance(x,str) for x in value['formats']):raise ScrapeError('UNSUPPORTED_OPTION','Object formats are not supported by this adapter',422)
        opts['formats']=value['formats']
    return Options.model_validate(opts)
def document(result):return {**result.get('data',{}),'metadata':{**result.get('metadata',{}),'sourceURL':result['url'],'url':result.get('final_url',result['url']),'statusCode':result.get('status')},'warnings':result.get('warnings',[])}
def install(app,engine,store):
    prefix='/compat/firecrawl/v2'
    @app.post(prefix+'/scrape')
    async def scrape(request:Request):
        value=await request.json()
        if set(value)-FIELDS-{'url'}:raise ScrapeError('UNSUPPORTED_OPTION','Unknown Firecrawl options are rejected; see compatibility documentation',422)
        result=await engine.scrape(request.state.tenant,value.get('url'),options(value))
        return {'success':True,'data':document(result)}
    for kind,path in [('crawl','/crawl'),('batch','/batch/scrape'),('map','/map')]:
        def handler(k):
            async def create(request:Request):
                value=await request.json();allowed={'url','urls','limit','maxDiscoveryDepth','includePaths','excludePaths','scrapeOptions'}
                if set(value)-allowed:raise ScrapeError('UNSUPPORTED_OPTION','Unknown compatibility option',422)
                scrape_options=value.get('scrapeOptions',{})
                if set(scrape_options)-FIELDS:raise ScrapeError('UNSUPPORTED_OPTION','Unknown scrape option',422)
                seeds=value.get('urls') or [value.get('url')]
                if k=='map':
                    # Mapping is asynchronous in the native service; do not fabricate synchronous parity.
                    raise ScrapeError('UNSUPPORTED_OPTION','Synchronous map compatibility is not implemented; use POST /v1/map',422)
                job=JobRequest(kind=k,urls=seeds,max_pages=value.get('limit',1000),max_depth=value.get('maxDiscoveryDepth',10),include_paths=value.get('includePaths',[]),exclude_paths=value.get('excludePaths',[]),options=options(scrape_options))
                row=store.create(request.state.tenant,job,request.headers.get('idempotency-key'))
                return {'success':True,'id':row['id'],'url':prefix+('/crawl/' if k=='crawl' else '/batch/scrape/')+row['id']}
            return create
        app.add_api_route(prefix+path,handler(kind),methods=['POST'])
    for path in ('/crawl/{jid}','/batch/scrape/{jid}'):
        def status_handler():
            async def status(jid:str,request:Request):
                row=store.get(request.state.tenant,jid);data=store.results(request.state.tenant,jid,0,100)
                if len(data)==100:raise ScrapeError('NATIVE_PAGINATION_REQUIRED','Use the native cursor API for 100 or more results',422)
                return {'success':True,'status':'completed' if row['status']=='completed' else 'scraping' if row['status'] in ('queued','running') else row['status'],'completed':row['processed'],'total':row['processed']+row['inflight'],'data':[document(v['result']) for v in data if not v['result'].get('error')]}
            return status
        app.add_api_route(prefix+path,status_handler(),methods=['GET'])
        async def cancel(jid:str,request:Request):store.transition(request.state.tenant,jid,'cancel');return {'success':True,'status':'cancelled'}
        app.add_api_route(prefix+path,cancel,methods=['DELETE'])
