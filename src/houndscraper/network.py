"""Pinned public DNS, bounded decoding, redirect checks, and cancellable HTTP."""
import asyncio
import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import aiohttp
from .errors import ScrapeError

def normalize_url(value, base=None):
    from urllib.parse import urljoin
    if not isinstance(value,str) or len(value)>8192:
        raise ScrapeError('INVALID_URL','Expected a public HTTP(S) URL')
    try:
        u=urlsplit(urljoin(base,value) if base else value)
        host=(u.hostname or '').rstrip('.').lower().encode('idna').decode()
        if u.scheme not in ('http','https') or not host or u.username or u.password or u.port not in (None,80,443):
            raise ValueError()
        if host=='localhost' or host.endswith(('.localhost','.local','.internal','.test','.invalid')):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global: raise ValueError()
        except ValueError as e:
            if ':' in host or host.replace('.','').isdigit(): raise e
        if ':' in host:host='['+host+']'
        port=u.port
        authority=host+(f':{port}' if port and port != (443 if u.scheme=='https' else 80) else '')
        return urlunsplit((u.scheme,authority,u.path or '/',u.query,''))
    except (ValueError,UnicodeError):
        raise ScrapeError('DESTINATION_BLOCKED','Only public HTTP(S) destinations on standard ports are allowed',403)

def origin(value):
    u=urlsplit(normalize_url(value));return f'{u.scheme}://{u.netloc}'

class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        rows=await asyncio.get_running_loop().getaddrinfo(host,port,type=socket.SOCK_STREAM,family=family)
        if not rows or any(not ipaddress.ip_address(row[4][0]).is_global for row in rows):
            raise ScrapeError('DNS_BLOCKED','DNS resolved to a non-public destination',403)
        return [{'hostname':host,'host':row[4][0],'port':port,'family':row[0],'proto':0,'flags':0} for row in rows]
    async def close(self):pass

@dataclass
class Response:
    url:str
    status:int
    headers:dict
    body:bytes
    elapsed:float

class Network:
    def __init__(self, concurrency=8, resolver=None):
        self.global_limit=asyncio.Semaphore(concurrency)
        self.hosts={}
        self.resolver=resolver or PublicResolver()
        self.robots={}
    async def fetch(self,url,*,timeout=15,max_bytes=33554432,headers=None,method='GET',body=None,destination_check=None):
        url=normalize_url(url);start=time.monotonic();original_origin=origin(url)
        connector=aiohttp.TCPConnector(resolver=self.resolver,use_dns_cache=False,limit=8)
        request_headers={'User-Agent':'HoundScraper/0.1 (+https://github.com/warhoundai/HoundScraper)','Accept':'*/*',**(headers or {})}
        async with aiohttp.ClientSession(connector=connector,timeout=aiohttp.ClientTimeout(total=timeout),trust_env=False) as session:
            for redirect in range(6):
                if destination_check and not await destination_check(url):raise ScrapeError('ROBOTS_DENIED','Redirect destination is excluded by robots.txt',403)
                host=self.hosts.setdefault(origin(url),asyncio.Semaphore(1))
                async with self.global_limit,host:
                    remaining=timeout-(time.monotonic()-start)
                    if remaining<=0:raise ScrapeError('TIMEOUT','Request timed out',408,True)
                    try:
                        async with session.request(method,url,headers=request_headers,data=body,allow_redirects=False,timeout=aiohttp.ClientTimeout(total=remaining)) as r:
                            if r.status in (301,302,303,307,308):
                                if redirect==5 or method not in ('GET','HEAD'):raise ScrapeError('REDIRECT_BLOCKED','Redirect limit or unsafe method',403)
                                next_url=normalize_url(r.headers.get('Location',''),url)
                                if origin(next_url)!=original_origin:request_headers={k:v for k,v in request_headers.items() if k.lower() not in ('authorization','cookie','proxy-authorization')}
                                url=next_url;continue
                            chunks=[];count=0
                            async for chunk in r.content.iter_chunked(65536):
                                count+=len(chunk)
                                if count>max_bytes:raise ScrapeError('RESPONSE_TOO_LARGE','Decoded response exceeds the byte budget',413)
                                chunks.append(chunk)
                            return Response(str(r.url),r.status,{k.lower():v for k,v in r.headers.items()},b''.join(chunks),time.monotonic()-start)
                    except (aiohttp.ClientError,asyncio.TimeoutError) as e:
                        raise ScrapeError('FETCH_FAILED','Network request failed or timed out',502,True) from e
        raise ScrapeError('REDIRECT_BLOCKED','Too many redirects',403)
    async def allowed(self,url,override=False):
        if override:return True
        key=origin(url);cached=self.robots.get(key)
        if not cached or cached[0]<time.monotonic():
            response=await self.fetch(key+'/robots.txt',max_bytes=131072)
            if response.status==404:lines=[]
            elif response.status in (401,403):return False
            elif response.status>=400:raise ScrapeError('ROBOTS_UNAVAILABLE','robots.txt could not be checked',503,True)
            else:lines=response.body.decode('utf-8',errors='replace').splitlines()
            parser=RobotFileParser();parser.parse(lines);cached=(time.monotonic()+300,parser);self.robots[key]=cached
        return cached[1].can_fetch('HoundScraper',url)

def response_hash(body):return hashlib.sha256(body).hexdigest()
