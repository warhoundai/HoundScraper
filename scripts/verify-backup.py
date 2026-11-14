"""Restore only the isolated fixture database into a disposable Docker database.

Never reads production databases. Set HOUNDSCRAPER_TEST_PG_CONTAINER to a local
PostgreSQL container with the synthetic houndscraper_test database.
"""
import hashlib,json,os,subprocess,uuid
container=os.environ['HOUNDSCRAPER_TEST_PG_CONTAINER']
if not container or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in container):raise ValueError('Invalid test container name')
restored='houndscraper_restore_'+uuid.uuid4().hex

def run(*command,input=None):
    result=subprocess.run(['docker','exec','-i','-u','postgres',container,*command],input=input,capture_output=True)
    if result.returncode:raise RuntimeError('Fixture backup/restore command failed: '+command[0])
    return result.stdout

def fingerprint(database):
    tables=run('psql','-At','-d',database,'-c',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").decode().splitlines()
    digest=hashlib.sha256()
    for table in tables:
        if not table.startswith('hs_') or not all(c.isalnum() or c=='_' for c in table):raise RuntimeError('Unexpected fixture table')
        rows=run('psql','-At','-d',database,'-c',f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY row_to_json(t)::text')
        digest.update(table.encode()+b'\0'+rows)
    return {'tables':len(tables),'sha256':digest.hexdigest()}

backup=run('pg_dump','--no-owner','--no-privileges','-Fc','houndscraper_test')
before=fingerprint('houndscraper_test')
try:
    run('createdb',restored)
    run('pg_restore','--no-owner','--no-privileges','-d',restored,input=backup)
    after=fingerprint(restored)
    assert before==after, 'Restored fixture data differs'
    print(json.dumps({'verified':True,'tables':after['tables'],'snapshot_bytes':len(backup),'restored_fingerprint':after['sha256']}))
finally:
    run('dropdb','--if-exists',restored)
