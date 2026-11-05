"""Read-only verification through the running production Next.js same-origin proxy."""
import json
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
state=json.loads((root/'.local/processes.json').read_text(encoding='utf-8-sig'))
credentials=json.loads((root/'backend/data/local_credentials.json').read_text(encoding='utf-8'))
base=state['site'].replace('localhost','127.0.0.1')
with httpx.Client(base_url=base,timeout=15) as client:
    assert client.get('/').status_code==200
    assert client.get('/api/health').json()['status']=='ok'
    assert client.get('/api/tickets').status_code==401
    response=client.post('/api/auth/login',json=credentials['admin'])
    response.raise_for_status()
    assert 'password' not in response.text
    client.headers['X-CSRF-Token']=client.cookies['shkola_csrf']
    assert client.get('/api/auth/me').json()['role']=='admin'
    assert len(client.get('/api/categories').json())>=3
    assert client.get('/api/stats').status_code==200
    assert client.get('/api/tickets?page_size=1').status_code==200
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/me').status_code==401
print('Production website, same-origin proxy, cookies, authenticated reads and logout: passed')
