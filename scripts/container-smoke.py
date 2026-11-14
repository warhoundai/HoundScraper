"""Real PostgreSQL-backed HTTP smoke; ephemeral credentials never enter source or logs."""
import json,os,secrets,subprocess,tempfile,time,urllib.request
name='houndscraper-ci-'+secrets.token_hex(4);key=secrets.token_urlsafe(32)
with tempfile.NamedTemporaryFile(mode='w') as env:
    env.write('HOUNDSCRAPER_DATABASE_URL=postgresql://postgres:container-test-only@127.0.0.1:5432/houndscraper\nHOUNDSCRAPER_API_KEYS='+json.dumps({'test':key})+'\n');env.flush()
    try:
        subprocess.run(['docker','run','-d','--name',name,'--network','host','--env-file',env.name,'houndscraper:test'],check=True,capture_output=True)
        for _ in range(60):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=2) as r:assert json.load(r)['status']=='ok'
                break
            except Exception:time.sleep(1)
        else:raise RuntimeError('Container did not become healthy')
        request=urllib.request.Request('http://127.0.0.1:8081/v1/capabilities',headers={'Authorization':'Bearer '+key})
        with urllib.request.urlopen(request,timeout=5) as r:assert 'scrape' in json.load(r)['core']
        uid=subprocess.check_output(['docker','exec',name,'id','-u'],text=True).strip();assert uid=='10001'
        print('Real PostgreSQL, authenticated API and non-root container verified')
    finally:subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
