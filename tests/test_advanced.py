import io,json
from unittest.mock import patch
import httpx,pytest
from houndscraper.models import JobRequest,Options
from houndscraper.engine import Engine
from houndscraper.providers import Providers
from houndscraper.storage_backends import S3Backend
from houndscraper.worker import Worker
from houndscraper.errors import ScrapeError
from test_core import FixtureNetwork

@pytest.mark.asyncio
async def test_gemini_counts_reasoning_tokens_and_uses_header_key(settings):
    settings.provider_kind='gemini';settings.provider_model='configured-model';settings.provider_key='synthetic-gemini-key';calls=[]
    async def post(client,url,**kwargs):
        calls.append((url,kwargs));return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':json.dumps({'value':42})}]}}],'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'thoughtsTokenCount':10},'modelVersion':'actual-configured-model'})
    with patch.object(httpx.AsyncClient,'post',post):value,usage=await Providers(settings).complete([{'role':'system','content':'Rules'},{'role':'user','content':'Source'}])
    assert value=={'value':42} and usage['provider_tokens']['output_tokens']==30 and usage['provider_tokens']['reasoning_tokens']==10
    assert calls[0][1]['headers']['x-goog-api-key']=='synthetic-gemini-key' and 'synthetic-gemini-key' not in calls[0][0]
    assert calls[0][1]['json']['generationConfig']['maxOutputTokens']==2048

@pytest.mark.asyncio
async def test_extraction_requires_evidence_for_every_field(settings):
    settings.provider_model='fixture'
    async def complete(*args,**kwargs):return {'data':{'known':'yes','invented':'no'},'evidence':[{'path':'/known','quote':'Known yes','url':'https://fixture.example/'}]},{}
    p=Providers(settings);p.complete=complete
    with pytest.raises(ScrapeError) as error:await p.extract('Known yes','https://fixture.example/')
    assert error.value.code=='EXTRACTION_UNVERIFIED'

class FakeS3:
    def __init__(self):self.objects={};self.puts=[]
    def put_object(self,**kwargs):self.puts.append(kwargs);self.objects[(kwargs['Bucket'],kwargs['Key'])]=kwargs['Body']
    def get_object(self,**kwargs):return {'Body':io.BytesIO(self.objects[(kwargs['Bucket'],kwargs['Key'])])}
    def delete_object(self,**kwargs):del self.objects[(kwargs['Bucket'],kwargs['Key'])]
def test_s3_backend_private_keys_encryption_and_roundtrip():
    client=FakeS3();b=S3Backend('s3://private-fixture/artifacts',client);b.put('tenant/object',b'evidence','text/plain')
    assert client.puts[0]['ServerSideEncryption']=='AES256' and b.get('tenant/object',100)==b'evidence'
    assert client.puts[0]['Key']=='artifacts/tenant/object';b.delete('tenant/object');assert not client.objects

@pytest.mark.asyncio
async def test_agent_selects_tools_synthesizes_grounded_data_and_checkpoints(store,settings):
    settings.provider_model='fixture';engine=Engine(settings,store,FixtureNetwork());actions=iter([{'action':'scrape','url':'https://fixture.example/'},{'action':'finish'}]);calls=[]
    async def complete(messages,max_output_tokens=2048):calls.append(messages);return next(actions),{'provider_tokens':{'input_tokens':20,'output_tokens':10}}
    async def synthesize(sources,schema=None,prompt=None):
        assert sources[0]['url']=='https://fixture.example/';return {'data':{'count':42},'evidence':[{'path':'/count','quote':'42','url':sources[0]['url']}],'verification':'source_quotes_verified','usage':{'provider_tokens':{'input_tokens':10,'output_tokens':10}}}
    engine.providers.complete=complete;engine.providers.extract_many=synthesize
    job=store.create('alpha',JobRequest(kind='agent',urls=['https://fixture.example/'],query='Find count',max_pages=3,max_download_bytes=4096))
    item=store.claim();assert item['allowed_bytes']==4096
    await Worker(engine).process(item);store.settle();row=store.get('alpha',job['id']);assert row['status']=='completed'
    results=store.results('alpha',job['id']);result=next(r['result'] for r in results if r['result'].get('kind')=='agent_synthesis')
    assert result['data']['count']==42 and result['agent_usage']['steps']==2
    assert result['agent_usage']['token_ceiling_used']<200000 and len(calls)==2
    with store.pool.connection() as c:state=c.execute('SELECT state FROM hs_agent_state WHERE job=%s',(job['id'],)).fetchone()['state']
    assert state['sources']['https://fixture.example/']['sha256'] and state['download_ceiling_used']<=4096

@pytest.mark.asyncio
async def test_agent_token_budget_prevents_provider_call(store,settings):
    from houndscraper.agent import Agent
    settings.provider_model='fixture';engine=Engine(settings,store,FixtureNetwork());called=False
    async def complete(*args,**kwargs):
        nonlocal called;called=True;return {},{}
    engine.providers.complete=complete
    job=store.create('alpha',JobRequest(kind='agent',query='Collect facts',max_provider_tokens=1024))
    item=store.claim()
    with pytest.raises(ScrapeError) as error:await Agent(engine).run(item)
    assert error.value.code=='PROVIDER_TOKEN_BUDGET' and not called

def test_encrypted_notification_profiles_and_tls_email(store,settings,monkeypatch):
    from houndscraper.notifications import Notifications
    engine=Engine(settings,store,FixtureNetwork());n=Notifications(engine)
    n.put('alpha','alerts',{'kind':'email','recipients':['fixture@example.com']})
    with store.pool.connection() as c:assert 'fixture@example.com' not in c.execute('SELECT ciphertext FROM hs_notification_profiles').fetchone()['ciphertext']
    with pytest.raises(ScrapeError):n.get('beta','alerts')
    with pytest.raises(ScrapeError):n.put('alpha','bad',{'kind':'email','recipients':['bad@example.com\nBcc: injected@example.com']})
    monkeypatch.setenv('HOUNDSCRAPER_SMTP_HOST','smtp.fixture.example');monkeypatch.setenv('HOUNDSCRAPER_SMTP_FROM','no-reply@example.com')
    from unittest.mock import MagicMock
    smtp=MagicMock();smtp.__enter__.return_value=smtp
    with patch('smtplib.SMTP',return_value=smtp):n.email(['fixture@example.com'],{'event':'changed'})
    assert smtp.starttls.called and smtp.send_message.called

def test_cluster_network_limits_pacing_and_stale_release(store):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as pool:leases=list(pool.map(lambda i:store.acquire_network(f'https://host{i}.example',4,30),range(10)))
    active=[x for x in leases if x];assert len(active)==4
    assert store.acquire_network(active[0]['origin'],4,30) is None
    old=active[0];store.release_network(old)
    newer=store.acquire_network(old['origin'],4,30);assert newer
    store.release_network(old)
    assert store.acquire_network(newer['origin'],4,30) is None
    store.release_network(newer,30)
    assert store.acquire_network(newer['origin'],4,30) is None
    for lease in active[1:]:store.release_network(lease)

def test_media_discovery_reports_sources_without_inventing_transcripts():
    from houndscraper.content import extract
    html=b'<main><video src="/clip.mp4"><track kind="captions" src="/captions.vtt" srclang="en"></video><audio src="/audio.mp3"></audio></main>'
    value,_,_=extract(html,'https://fixture.example/',Options(formats=['video','audio','captions']))
    assert value['video'][0]['url']=='https://fixture.example/clip.mp4'
    assert value['captions'][0]['url']=='https://fixture.example/captions.vtt' and 'text' not in value['captions'][0]

@pytest.mark.asyncio
async def test_profile_secrets_are_removed_before_model_extraction(store,settings):
    from houndscraper.network import Response
    network=FixtureNetwork()
    async def fetch(url,**kwargs):return Response(url,200,{'content-type':'text/html'},b'<main>Document reflects synthetic-profile-secret. This controlled source has enough meaningful text for extraction without browser fallback. A known credential must not enter model context.</main>',.1)
    network.fetch=fetch;engine=Engine(settings,store,network);engine.credentials.put('alpha','login','https://fixture.example',{'Authorization':'Bearer synthetic-profile-secret'})
    seen=[]
    async def extraction(text,*args,**kwargs):seen.append(text);return {'data':{},'evidence':[],'usage':{}}
    engine.providers.extract=extraction
    await engine.scrape('alpha','https://fixture.example/',Options(formats=['json'],render='never',credential_profile='login'))
    assert 'synthetic-profile-secret' not in seen[0] and '[REDACTED]' in seen[0]
