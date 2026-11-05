"""Browser integration test on an isolated API, SQLite DB and Next.js dist directory."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx

ROOT=Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is not None:return
    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    else:process.terminate()
    process.wait(timeout=15)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='requests-browser-') as directory:
        folder=Path(directory);api_port=free_port();web_port=free_port()
        base=f'http://127.0.0.1:{web_port}'
        env=os.environ|{'DATABASE_URL':f"sqlite:///{(folder/'browser.db').as_posix()}",'ENVIRONMENT':'local','COOKIE_SECURE':'false',
            'BOOTSTRAP_ADMIN_PASSWORD':'Isolated_admin_456!','BOOTSTRAP_OPERATOR_PASSWORD':'Isolated_operator_456!',
            'ALLOWED_ORIGINS':base,'API_INTERNAL_URL':f'http://127.0.0.1:{api_port}',
            'TELEGRAM_BOT_USERNAME':'offline_test_bot','TELEGRAM_BOT_TOKEN':'offline-test-only','NEXT_DIST_DIR':'.next-e2e','TEST_SITE':base,'NOTIFICATIONS_ENABLED':'false'}
        initializer='from app.bootstrap import migrate,seed; from app.auth import hasher; from app.models import Staff; from app.database import SessionLocal; migrate(); db=SessionLocal(); seed(db); db.add(Staff(name="Дежурный сотрудник",login="colleague",role="operator",password_hash=hasher.hash("Isolated_colleague_456!"))); db.commit(); db.close()'
        subprocess.run([sys.executable,'-c',initializer],cwd=ROOT/'backend',env=env,check=True,capture_output=True)
        with (ROOT/'work'/'browser-servers.log').open('w',encoding='utf-8') as log:
            api=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(api_port),'--no-access-log'],cwd=ROOT/'backend',env=env,stdout=log,stderr=log)
            web=subprocess.Popen(['node',str(ROOT/'node_modules/next/dist/bin/next'),'dev','--hostname','127.0.0.1','--port',str(web_port)],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    if api.poll() is not None or web.poll() is not None:raise RuntimeError('Test server exited; see work/browser-servers.log')
                    try:
                        if httpx.get(base+'/api/health',timeout=5).status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.3)
                else:raise RuntimeError('Test frontend did not become ready')
                subprocess.run(['node','scripts/browser-check.mjs'],cwd=ROOT,env=env,check=True)
            finally:
                stop(web);stop(api)


if __name__=='__main__':main()
