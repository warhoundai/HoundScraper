"""Live native-adapter qualification with a controlled source and bounded completion."""
import asyncio,json,os
from houndscraper.config import Settings
from houndscraper.providers import Providers
async def main():
    cfg=Settings(provider_kind='vertex',provider_model=os.environ['HOUNDSCRAPER_GCP_MODEL'])
    result=await Providers(cfg).extract('The invoice total is 42 dollars.','https://fixture.example/invoice',{'type':'object','properties':{'invoice_total':{'type':'integer'}},'required':['invoice_total'],'additionalProperties':False},'Extract invoice_total as an integer. Quote the source number as evidence at /invoice_total.')
    assert result['data']['invoice_total']==42
    usage=result['usage'];assert isinstance(usage['provider_tokens']['input_tokens'],int) and usage['provider_tokens']['input_tokens']>0
    assert isinstance(usage['provider_tokens']['output_tokens'],int) and usage['provider_tokens']['output_tokens']>0
    print(json.dumps({'native_vertex_verified':True,'model':usage['model'],'actual_usage':usage['provider_tokens'],'verification':result['verification']}))
asyncio.run(main())
