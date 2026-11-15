"""Opt-in downstream HoundSearch REST acceptance using the operator's Vertex test identity."""
import os,secrets,json
import pytest
pytestmark=pytest.mark.skipif(os.environ.get('HOUND_ECOSYSTEM_LIVE')!='1',reason='Explicit live downstream qualification only')
@pytest.mark.asyncio
async def test_downstream_answer_citation_usage_idempotency_and_tenant_isolation(tmp_path):
 import httpx
 from cryptography.fernet import Fernet
 from houndsearch.api import create_app
 from houndsearch.config import Settings
 from houndsearch.store import Store
 from houndsearch.engine import Engine
 url=os.environ['HOUNDSEARCH_TEST_DATABASE_URL']
 assert url.split('?',1)[0].endswith('/houndsearch_test'),'Isolated qualification database required'
 db=Store(url);key=secrets.token_urlsafe(32);other=secrets.token_urlsafe(32)
 cfg=Settings(database=url,keys={'qualification':key,'other':other},storage=str(tmp_path),encryption_key=Fernet.generate_key().decode())
 try:
  engine=Engine(cfg,db);cid=db.create_collection('qualification','Controlled evidence','public')['id']
  source='The warehouse opens at 09:00 UTC.'
  engine.index('qualification',cid,{'url':'https://fixture.example/warehouse','data':{'text':source},'metadata':{'title':'Warehouse'}})
  engine.profiles.put('qualification','vertex-test',{'kind':'vertex','project':os.environ['HOUNDSCRAPER_VERTEX_PROJECT'],'model':os.environ['HOUNDSCRAPER_GCP_MODEL'],'location':'global'})
  app=create_app(cfg,store=db,engine=engine,run_worker=False)
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://qualification.example',timeout=180) as client:
   headers={'Authorization':'Bearer '+key,'Idempotency-Key':'controlled-live-answer'}
   body={'query':'warehouse','collections':[cid],'model_profile':'vertex-test','max_output_tokens':1024,'budget':{'max_requests':8,'max_tokens':20000,'max_steps':1}}
   response=await client.post('/v1/answer',headers=headers,json=body)
   assert response.status_code==200,response.text
   answer=response.json();assert not answer['abstained'] and answer['claims'],answer
   assert any('09:00' in claim['citation']['quote'] for claim in answer['claims'])
   for claim in answer['claims']:
    citation=claim['citation'];assert source[citation['start']:citation['end']]==citation['quote']
   replay=await client.post('/v1/answer',headers=headers,json=body);assert replay.json()==answer
   denied=await client.get('/v1/jobs/'+answer['execution_id'],headers={'Authorization':'Bearer '+other});assert denied.status_code==404
  with db.pool.connection() as c:
   calls=c.execute("SELECT usage FROM hsearch_calls WHERE job=%s AND kind='model'",(answer['execution_id'],)).fetchall()
  assert len(calls)==1
  counters=calls[0]['usage']['provider_tokens'];assert counters['input_tokens']>0 and counters['output_tokens']>0
  assert answer['usage']['unresolved_reservations']==0 and answer['usage']['warhound_fee_usd']==0
  print(json.dumps({'downstream_answer_verified':True,'exact_citation_quotes_verified':True,'idempotent_replay_verified':True,'cross_tenant_denied':True,'model':os.environ['HOUNDSCRAPER_GCP_MODEL'],'provider_tokens':counters,'request_count':answer['usage']['requests']}))
 finally:db.close()
