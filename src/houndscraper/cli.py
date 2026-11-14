import argparse
import json
import os
from .client import Client

def main():
    p=argparse.ArgumentParser(prog='houndscraper');sub=p.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--host',default='127.0.0.1');serve.add_argument('--port',type=int,default=8081);serve.add_argument('--no-worker',action='store_true')
    sub.add_parser('worker');sub.add_parser('mcp')
    scrape=sub.add_parser('scrape');scrape.add_argument('url');scrape.add_argument('--format',action='append',dest='formats')
    for kind in ('crawl','map','batch'):
        cmd=sub.add_parser(kind);cmd.add_argument('urls',nargs='+');cmd.add_argument('--max-pages',type=int,default=1000);cmd.add_argument('--wait',action='store_true')
    agent=sub.add_parser('agent');agent.add_argument('prompt');agent.add_argument('--url',action='append',default=[]);agent.add_argument('--max-steps',type=int,default=40);agent.add_argument('--max-provider-tokens',type=int,default=200000);agent.add_argument('--wait',action='store_true')
    job=sub.add_parser('job');job.add_argument('id')
    for action in ('pause','resume','cancel','results'):
        cmd=sub.add_parser(action);cmd.add_argument('id')
    args=p.parse_args()
    if args.command=='serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(run_worker=not args.no_worker),host=args.host,port=args.port);return
    if args.command=='worker':
        import asyncio
        from .config import Settings
        from .database import Store
        from .engine import Engine
        from .worker import Worker
        cfg=Settings().validate();db=Store(cfg.database)
        try:asyncio.run(Worker(Engine(cfg,db)).run())
        finally:db.close()
        return
    if args.command=='mcp':
        from .mcp import main as mcp_main
        mcp_main();return
    with Client(os.environ.get('HOUNDSCRAPER_ENDPOINT','http://127.0.0.1:8081'),api_key=os.environ.get('HOUNDSCRAPER_API_KEY','')) as c:
        if args.command=='scrape':result=c.scrape(args.url,formats=args.formats or ['markdown'])
        elif args.command=='agent':
            result=c.submit('agent',args.url,query=args.prompt,max_agent_steps=args.max_steps,max_provider_tokens=args.max_provider_tokens)
            if args.wait:result=c.wait(result['id'])
        elif args.command in ('crawl','map','batch'):
            result=c.submit(args.command,args.urls,max_pages=args.max_pages)
            if args.wait:result=c.wait(result['id'])
        elif args.command=='job':result=c.job(args.id)
        elif args.command=='results':
            for item in c.results(args.id):print(json.dumps(item,ensure_ascii=False))
            return
        else:result=c.transition(args.id,args.command)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
