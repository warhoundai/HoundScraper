"""Deterministic HTML extraction; original source is kept distinct from generated text."""
import base64
import hashlib
import json
import re
from bs4 import BeautifulSoup
from markdownify import markdownify
from .network import normalize_url

def extract(body,url,options,rendered=False):
    soup=BeautifulSoup(body,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    language=soup.html.get('lang') if soup.html else None
    links=[];images=[];discovery_truncated=False
    for tag,attribute,output in [('a','href',links),('img','src',images)]:
        seen=set()
        for el in soup.find_all(tag,limit=1001):
            if len(output)>=1000:discovery_truncated=True;break
            try:
                target=normalize_url(el.get(attribute,''),url)
                if target not in seen:
                    seen.add(target);output.append({'url':target,'text':el.get_text(' ',strip=True) if tag=='a' else el.get('alt','')})
            except Exception:continue
    media={'audio':[],'video':[],'captions':[]}
    for kind in ('audio','video'):
        for element in soup.find_all(kind,limit=100):
            for node in [element,*element.find_all('source')]:
                if not node.get('src'):continue
                try:media[kind].append({'url':normalize_url(node['src'],url),'content_type':node.get('type')})
                except Exception:pass
            for node in element.find_all('track',limit=20):
                if node.get('kind') not in ('captions','subtitles') or not node.get('src'):continue
                try:media['captions'].append({'url':normalize_url(node['src'],url),'language':node.get('srclang'),'label':node.get('label')})
                except Exception:pass
    ld=[]
    for el in soup.select('script[type="application/ld+json"]'):
        try:ld.append(json.loads(el.get_text()))
        except (ValueError,TypeError):pass
    metadata={'title':title,'language':language}
    for el in soup.find_all('meta'):
        key=el.get('name') or el.get('property')
        if key and el.get('content'):metadata[key]=el['content']
    canonical=soup.find('link',rel='canonical')
    if canonical:
        try:metadata['canonical']=normalize_url(canonical.get('href',''),url)
        except Exception:pass
    attrs=[]
    for item in options.attributes:
        selector,attribute=item.get('selector',''),item.get('attribute','')
        attrs.append({'selector':selector,'attribute':attribute,'values':[el.get(attribute) for el in soup.select(selector)]})
    for selector in options.exclude_selectors:
        for node in soup.select(selector):node.decompose()
    if options.include_selectors:
        selected='\n'.join(str(node) for selector in options.include_selectors for node in soup.select(selector))
        root=BeautifulSoup(selected,'html.parser')
    elif options.only_main_content:root=soup.find('main') or soup.find('article') or soup.body or soup
    else:root=soup.body or soup
    for node in root.select('script,style,noscript,template'+(',nav,footer' if options.only_main_content and not options.include_selectors else '')):
        node.decompose()
    html=str(root);text=root.get_text('\n',strip=True)
    md=markdownify(html,heading_style='ATX',bullets='-').strip()
    tables=[[[cell.get_text(' ',strip=True) for cell in row.find_all(['th','td'])] for row in table.find_all('tr')] for table in root.find_all('table')]
    product=next((v for item in ld for v in (item if isinstance(item,list) else [item]) if isinstance(v,dict) and 'Product' in str(v.get('@type',''))),None)
    candidates={'markdown':md,'text':text,'html':html,'rawHtml':body.decode('utf-8',errors='replace') if isinstance(body,bytes) else body,'renderedHtml':(body.decode('utf-8',errors='replace') if isinstance(body,bytes) else body) if rendered else None,'rawBase64':base64.b64encode(body if isinstance(body,bytes) else body.encode()).decode(),'links':links,'images':images,'metadata':metadata,'tables':tables,'jsonld':ld,'attributes':attrs,'product':product}
    candidates.update(media)
    outputs={k:v for k,v in candidates.items() if k in options.formats}
    warnings=['Discovery truncated at 1,000 links/images per page'] if discovery_truncated else []
    if 'product' in options.formats and product is None:warnings.append('No Product structured data found; no product facts were invented')
    if 'renderedHtml' in options.formats and not rendered:warnings.append('Rendered HTML requires browser rendering')
    return outputs,{'text':text,'markdown':md,'metadata':metadata,'links':links,'images':images,'jsonld':ld},warnings

def thin_content(text,html):
    return len(text.strip())<120 and any(x in html.lower() for x in ['<script','id="root"','id="app"','enable javascript'])
