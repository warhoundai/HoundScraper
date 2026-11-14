"""Controlled dashboard fixture server; never used by production entry points."""
import json,os,secrets,tempfile
from pathlib import Path
from houndscraper.config import Settings
from houndscraper.database import Store
from houndscraper.engine import Engine
from houndscraper.network import Response
from houndscraper.api import create_app
import uvicorn
class FixtureNetwork:
    async def allowed(self,*args):return True
    async def fetch(self,url,**kwargs):return Response(url,200,{'content-type':'text/html'},b'<html><title>Dashboard fixture</title><main><h1>Evidence from controlled fixture</h1><p>This known page validates the real dashboard, HTTP client, API authentication, deterministic extraction, and rendering of a source result without making uncontrolled target requests.</p></main></html>',.01)
if __name__=='__main__':
    key=secrets.token_urlsafe(32);path=Path('/tmp/houndscraper-dashboard-test-key');fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:f.write(key)
    cfg=Settings(database=os.environ['HOUNDSCRAPER_TEST_DATABASE_URL'],keys={'dashboard':key},storage=tempfile.mkdtemp(prefix='houndscraper-dashboard-'))
    db=Store(cfg.database);uvicorn.run(create_app(cfg,store=db,engine=Engine(cfg,db,FixtureNetwork())),host='127.0.0.1',port=8089,access_log=False)
