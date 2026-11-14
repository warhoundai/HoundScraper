"""Costs from explicit operator rates and measured tokens; never invented invoices."""
from decimal import Decimal,ROUND_CEILING,InvalidOperation
from .errors import ScrapeError
NANO=Decimal(1000000000)
def rates(settings):
    p=settings.pricing
    if not p or p.get('provider')!=settings.provider_kind or p.get('model')!=settings.provider_model:return None
    needed=('input_usd_per_million','output_usd_per_million','source','checked_at')
    if any(k not in p for k in needed) or not str(p['source']).startswith('https://'):raise ScrapeError('PRICING_INVALID','Pricing needs rates, HTTPS provenance and a verification date',503)
    for key in ('input_usd_per_million','output_usd_per_million','cached_input_usd_per_million'):
        if key in p:
            try:value=Decimal(str(p[key]))
            except (InvalidOperation,ValueError):raise ScrapeError('PRICING_INVALID','Rates must be finite and nonnegative',503)
            if not value.is_finite() or value<0:raise ScrapeError('PRICING_INVALID','Rates must be finite and nonnegative',503)
    return p

def nano_cost(input_tokens,output_tokens,p,cached_tokens=0):
    if cached_tokens and 'cached_input_usd_per_million' not in p:return None
    value=(Decimal(input_tokens-cached_tokens)*Decimal(str(p['input_usd_per_million']))+Decimal(output_tokens)*Decimal(str(p['output_usd_per_million']))+Decimal(cached_tokens)*Decimal(str(p.get('cached_input_usd_per_million',0))))/Decimal(1000000)
    return int((value*NANO).to_integral_value(rounding=ROUND_CEILING))
def reserve_cost(settings,input_ceiling,output_ceiling):
    p=rates(settings)
    if not p:raise ScrapeError('PRICING_UNAVAILABLE','A dollar budget requires explicitly configured model rates and provenance',503)
    worst=dict(p);worst['input_usd_per_million']=max(Decimal(str(p['input_usd_per_million'])),Decimal(str(p.get('cached_input_usd_per_million',0))))
    return nano_cost(input_ceiling,output_ceiling,worst)
def measured_cost(settings,counters):
    p=rates(settings)
    if not p or any(not isinstance(counters.get(k),int) or counters[k]<0 for k in ('input_tokens','output_tokens')):return None
    cached=counters.get('cached_input_tokens',0)
    if type(cached) is not int or not 0<=cached<=counters['input_tokens']:return None
    return nano_cost(counters['input_tokens'],counters['output_tokens'],p,counters.get('cached_input_tokens',0))
