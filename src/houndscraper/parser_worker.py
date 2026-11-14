"""Optional document worker. Deploy with no network and a bounded tmpfs."""
import asyncio
import hmac
import os
import tempfile
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
TYPES={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg','image/tiff':'.tiff','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'.docx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':'.xlsx','application/vnd.openxmlformats-officedocument.presentationml.presentation':'.pptx','text/csv':'.csv','text/html':'.html','application/epub+zip':'.epub','application/vnd.oasis.opendocument.text':'.odt'}
def create_parser_app():
    key=os.environ.get('HOUNDSCRAPER_PARSER_KEY','')
    if len(key)<32:raise ValueError('Configure a separate parser service key')
    app=FastAPI(docs_url=None,openapi_url=None,redoc_url=None);capacity=asyncio.Semaphore(1)
    @app.get('/health')
    async def health():return {'status':'ok'}
    @app.post('/parse')
    async def parse(request:Request):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+key):return JSONResponse({'error':'UNAUTHORIZED'},status_code=401)
        mime=request.headers.get('content-type','').split(';')[0]
        if mime not in TYPES:return JSONResponse({'error':'UNSUPPORTED_FORMAT'},status_code=415)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>33554432:return JSONResponse({'error':'TOO_LARGE'},status_code=413)
        if body[:2]==b'PK':
            import io,zipfile
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as z:
                    files=z.infolist()
                    if len(files)>10000 or sum(i.file_size for i in files)>268435456 or any(i.file_size>67108864 or i.flag_bits&1 for i in files):raise ValueError()
            except Exception:return JSONResponse({'error':'UNSAFE_ARCHIVE'},status_code=422)
        async with capacity:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/('document'+TYPES[mime]);path.write_bytes(body)
                process=await asyncio.create_subprocess_exec('python','-m','houndscraper.parser_process',str(path),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
                try:
                    out,_=await asyncio.wait_for(process.communicate(),120)
                    if process.returncode or len(out)>16777216:return JSONResponse({'error':'PARSING_FAILED'},status_code=422)
                    import json
                    return json.loads(out)
                except (TimeoutError,asyncio.CancelledError):
                    process.kill();await process.wait();raise
    return app
