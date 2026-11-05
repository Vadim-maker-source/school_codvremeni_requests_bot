"""Reproducible HTTP smoke test and short load test; ALWAYS uses its own DB/server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import httpx
from contextlib import closing

BACKEND = Path(__file__).resolve().parents[1]
PAYLOAD = {'applicant_name':'Тестовый заявитель','contact':'test@example.invalid','group_id':1,'item_id':1,'description':'Не работает проектор — изолированная проверка'}


def session(base, role='operator'):
    client = httpx.Client(base_url=base, timeout=30)
    response = client.post('/api/auth/login',json={'login':role,'password':f'Isolated_{role}_456!'})
    response.raise_for_status()
    client.headers['X-CSRF-Token']=client.cookies['shkola_csrf']
    return client


def smoke(base):
    with closing(session(base)) as c, closing(session(base,'admin')) as a:
        t=c.post('/api/tickets',json=PAYLOAD);t.raise_for_status();t=t.json()
        assert c.get('/api/tickets',params={'q':t['number']}).json()['total']==1
        assert c.get(f"/api/tickets/{t['id']}").status_code==200
        for action,extra in [('take',{}),('assign',{'assignee_id':1}),('complete',{'comment':'Кабель заменён; работа восстановлена'})]:
            if action=='assign':
                assert c.post(f"/api/tickets/{t['id']}/actions",json={'action':action,'version':t['version']}|extra).status_code==403
            actor=a if action=='assign' else c
            response=actor.post(f"/api/tickets/{t['id']}/actions",json={'action':action,'version':t['version']}|extra)
            response.raise_for_status();t=response.json()
        detail=c.get(f"/api/tickets/{t['id']}").json()
        assert [h['action'] for h in detail['history']]==['create','take','assign','complete']
        assert a.get('/api/stats').json()['statuses']['completed']==1
        return {'result':'passed','steps':['create','list','detail','take','reassign','complete','history','stats'], 'health':c.get('/api/health').json()}


def benchmark(base, duration, clients):
    connections=[session(base) for _ in range(clients)]
    started=time.perf_counter();deadline=started+duration
    def worker(client):
        samples=[];cycles=0
        def measured(name,method,path,**kwargs):
            start=time.perf_counter()
            try:
                response=client.request(method,path,**kwargs)
                ok=response.status_code in (200,201)
                data=response.json() if ok else None
            except Exception:
                ok=False;data=None
            samples.append((name,time.perf_counter()-start,ok))
            return data
        try:
            while time.perf_counter()<deadline:
                ticket=measured('create','POST','/api/tickets',json=PAYLOAD)
                measured('list','GET','/api/tickets?page_size=15')
                if ticket:
                    changed=measured('status','POST',f"/api/tickets/{ticket['id']}/actions",json={'action':'take','version':ticket['version']})
                    if changed:cycles+=1
        finally:
            client.close()
        return samples,cycles
    with ThreadPoolExecutor(max_workers=clients) as pool:
        results=list(pool.map(worker,connections))
    elapsed=time.perf_counter()-started
    buckets=defaultdict(list)
    for samples,_ in results:
        for name,latency,ok in samples:buckets[name].append((latency,ok))
    measurements={}
    for name,samples in buckets.items():
        latencies=sorted(x[0]*1000 for x in samples)
        successes=sum(x[1] for x in samples)
        measurements[name]={'attempts':len(samples),'successes':successes,'error_fraction':1-successes/len(samples),
                            'mean_ms':round(statistics.mean(latencies),2),'p95_ms':round(latencies[math.ceil(len(latencies)*.95)-1],2),
                            'successful_ops_per_second':round(successes/elapsed,2)}
    cycles=sum(cycles for _,cycles in results)
    return {'elapsed_seconds':round(elapsed,3),'concurrent_clients':clients,'cycle':'create → list (15) → take in progress',
            'completed_cycles':cycles,'cycles_per_second':round(cycles/elapsed,2),
            'extrapolated_cycles_per_hour':round(cycles/elapsed*3600),'operations':measurements}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=15)
    parser.add_argument('--clients',type=int,default=4)
    parser.add_argument('--output',type=Path,default=BACKEND.parent/'work'/'performance.json')
    args=parser.parse_args()
    if not 1<=args.clients<=32 or not 1<=args.seconds<=3600:parser.error('Invalid duration or client count')
    with tempfile.TemporaryDirectory(prefix='requests-http-') as directory:
        folder=Path(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=os.environ|{'DATABASE_URL':f"sqlite:///{(folder/'load.db').as_posix()}",'ENVIRONMENT':'local','COOKIE_SECURE':'false',
                        'BOOTSTRAP_ADMIN_PASSWORD':'Isolated_admin_456!','BOOTSTRAP_OPERATOR_PASSWORD':'Isolated_operator_456!',
                        'LOGIN_MAX_ATTEMPTS':'10000','NOTIFICATIONS_ENABLED':'false'}
        initializer='from app.bootstrap import migrate,seed; from app.database import SessionLocal; migrate(); db=SessionLocal(); seed(db); db.commit(); db.close()'
        subprocess.run([sys.executable,'-c',initializer],cwd=BACKEND,env=env,check=True,capture_output=True)
        with (folder/'server.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=BACKEND,env=env,stdout=log,stderr=log)
            try:
                base=f'http://127.0.0.1:{port}'
                for _ in range(100):
                    if process.poll() is not None:raise RuntimeError('Isolated server exited: '+(folder/'server.log').read_text(encoding='utf-8'))
                    try:
                        if httpx.get(base+'/api/health',timeout=1).status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.2)
                else:raise RuntimeError('Isolated server did not become ready')
                report={'date_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'os':platform.platform(),
                        'cpu':platform.processor(),'logical_cpus':os.cpu_count(),'python':sys.version.split()[0],
                        'database':'SQLite, temporary local file, WAL, busy_timeout 15s, single uvicorn worker',
                        'http_smoke':smoke(base),'load':benchmark(base,args.seconds,args.clients),
                        'limitations':'Short local extrapolation only; no claim of hour-long stability or PostgreSQL performance.'}
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(report,ensure_ascii=False,indent=2))
            finally:
                if os.name == 'nt':
                    # The venv Python launcher has a child interpreter on Windows.
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                    process.wait(timeout=10)
                else:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
