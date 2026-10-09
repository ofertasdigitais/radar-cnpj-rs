"""Read-only route and data checks. No app initialization, campaigns or writes."""
import json
import os
import sys
import sqlite3
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from tools.db_qa import audit, database_ready

EXPECTED_ROUTES = {
    '/api/admin/state': 200, '/api/help': 200, '/api/admin/help': 200,
    '/ajuda': 303, '/help-center.css': 200, '/react-help.js': 200,
    '/prospect-qualification.js': 200, '/api/prospects': 200,
    'anonymous_help': 401,
}


def route_failures(routes):
    return [path for path, status in EXPECTED_ROUTES.items() if routes.get(path) != status]

def run():
    app.resolve_local_admin_credential()
    username=os.environ.get('RADAR_ADMIN_USER');password=os.environ.get('RADAR_ADMIN_PASSWORD')
    if not username or not password:raise RuntimeError('Credencial local indisponível; nenhuma alteração executada')
    connection=HTTPConnection('127.0.0.1',8000,timeout=30)
    connection.request('POST','/login',urlencode(dict(username=username,password=password)),{'Content-Type':'application/x-www-form-urlencoded'})
    response=connection.getresponse();response.read()
    if response.status!=303:raise RuntimeError('Não foi possível autenticar o administrador local')
    cookie=response.getheader('Set-Cookie').split(';')[0];connection.close()
    routes={};details={}
    for path in ['/api/admin/state','/api/help','/api/admin/help','/ajuda','/help-center.css','/react-help.js','/prospect-qualification.js','/api/prospects']:
        connection=HTTPConnection('127.0.0.1',8000,timeout=30);connection.request('GET',path,headers={'Cookie':cookie});response=connection.getresponse();body=response.read();routes[path]=response.status;connection.close()
        if path=='/api/admin/state' and response.status==200:
            state=json.loads(body);details['counts']=state['counts'];details['sync']={key:state.get('sync',{}).get(key) for key in ('status','fase')}
        if path=='/api/help' and response.status==200:details['guides']=len(json.loads(body)['items'])
    connection=HTTPConnection('127.0.0.1',8000,timeout=30);connection.request('GET','/api/help');response=connection.getresponse();response.read();routes['anonymous_help']=response.status;connection.close()
    with closing(sqlite3.connect(app.DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        details['active_campaigns']=db.execute('SELECT COUNT(*) FROM discovery_campaigns WHERE active=1').fetchone()[0]
        details['running_campaigns']=db.execute("SELECT COUNT(*) FROM discovery_runs WHERE status='executando'").fetchone()[0]
    database=audit(app.DB)
    failures=route_failures(routes)
    ready=not failures and database_ready(database) and details.get('guides',0)>0
    print(json.dumps({'passed':ready,'failed_routes':failures,'routes':routes,'details':details,'database':database},ensure_ascii=False,indent=2))
    return 0 if ready else 1

if __name__=='__main__':raise SystemExit(run())
