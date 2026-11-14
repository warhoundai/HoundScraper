"""Optional document worker. Deploy with no network and a bounded tmpfs."""
import asyncio
import hmac
import os
import tempfile
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
TYPES={'audio/wav':'.wav','audio/x-wav':'.wav','audio/mpeg':'.mp3','audio/flac':'.flac','audio/ogg':'.ogg','audio/mp4':'.m4a','video/mp4':'.mp4','application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg','image/tiff':'.tiff','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'.docx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':'.xlsx','application/vnd.openxmlformats-officedocument.presentationml.presentation':'.pptx','text/csv':'.csv','text/html':'.html','application/epub+zip':'.epub','application/vnd.oasis.opendocument.text':'.odt'}
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
                if mime.startswith(('audio/','video/')):
                    probe=await asyncio.create_subprocess_exec('ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration','-of','json',str(path),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
                    try:output,_=await asyncio.wait_for(probe.communicate(),15)
                    except BaseException:
                        probe.kill();await probe.wait();raise
                    import json
                    try:duration=float(json.loads(output)['format']['duration'])
                    except Exception:return JSONResponse({'error':'MEDIA_DURATION_UNKNOWN'},status_code=422)
                    if not 0<duration<=300:return JSONResponse({'error':'MEDIA_DURATION_LIMIT','max_seconds':300},status_code=413)
                    wav=Path(directory)/'bounded-audio.wav'
                    convert=await asyncio.create_subprocess_exec('ffmpeg','-v','error','-protocol_whitelist','file,pipe','-i',str(path),'-t','300','-ac','1','-ar','16000',str(wav),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
                    try:await asyncio.wait_for(convert.wait(),30)
                    except BaseException:
                        convert.kill();await convert.wait();raise
                    if convert.returncode:return JSONResponse({'error':'MEDIA_DECODE_FAILED'},status_code=422)
                    path=wav
                process=await asyncio.create_subprocess_exec('python','-m','houndscraper.parser_process',str(path),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
                parent=asyncio.current_task()
                async def disconnected():
                    while True:
                        await asyncio.sleep(.5)
                        if await request.is_disconnected():parent.cancel();return
                watch=asyncio.create_task(disconnected())
                try:
                    out,_=await asyncio.wait_for(process.communicate(),120)
                    if process.returncode or len(out)>16777216:return JSONResponse({'error':'PARSING_FAILED'},status_code=422)
                    import json
                    return json.loads(out)
                except (TimeoutError,asyncio.CancelledError):
                    process.kill();await process.wait();raise
                finally:
                    watch.cancel();await asyncio.gather(watch,return_exceptions=True)
    return app
