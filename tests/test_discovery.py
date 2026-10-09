import json
import os
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
import app
import discovery
import security
from urllib.error import HTTPError
CAMPAIGN=dict(name='Restaurantes QA',city='Porto Alegre',category='restaurantes',frequency='manual',active=True,enrich_websites=False)
ELEMENTS=[dict(type='node',id=123,tags={'name':'Loja QA','phone':'51987654321','website':'example.com'})]

class DiscoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.dbpatch=patch.object(app,'DB',Path(self.tmp.name)/'test.sqlite');self.dbpatch.start()
  self.env=patch.dict(os.environ,{'RADAR_ENV':'','RADAR_ADMIN_USER':'','RADAR_ADMIN_PASSWORD':''});self.env.start();app.init_db()
  self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.env.stop();self.dbpatch.stop();self.tmp.cleanup()
 def request(self,method,path,payload=None,headers=None):
  connection=HTTPConnection('127.0.0.1',self.server.server_port);connection.request(method,path,json.dumps(payload) if payload is not None else None,headers or {'Content-Type':'application/json'})
  response=connection.getresponse();data=response.read();status=response.status;result=dict(response.getheaders());connection.close();return status,data,result
 def test_campaign_scope_dedup_preserves_seller(self):
  status,raw,_=self.request('POST','/api/discovery/campaigns',CAMPAIGN);self.assertEqual(status,201);identifier=json.loads(raw)['id']
  with app.connect() as db:
   other=discovery.save_campaign(db,'other',CAMPAIGN)
   campaign=dict(db.execute('SELECT * FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone())
   rows=discovery.records(ELEMENTS,{**campaign});self.assertEqual(discovery.store_records(db,'local-default',rows),(1,0))
   db.execute("UPDATE prospect_inbox SET notes='Preservar',status='qualificado'")
   self.assertEqual(discovery.store_records(db,'local-default',rows),(0,1))
   row=db.execute('SELECT * FROM prospect_inbox').fetchone();self.assertEqual(row['notes'],'Preservar');self.assertEqual(row['status'],'qualificado')
  self.assertEqual(self.request('PUT','/api/discovery/campaigns/'+other,CAMPAIGN)[0],404)
  status,raw,_=self.request('GET','/api/discovery');self.assertEqual(len(json.loads(raw)['campaigns']),1)
  status,raw,_=self.request('GET','/api/discovery/sources');self.assertEqual(json.loads(raw)['items'][0]['metadata']['source_url'],'https://www.openstreetmap.org/node/123')
 def test_manager_async_and_limit(self):
  with app.connect() as db: identifier=discovery.save_campaign(db,'owner',CAMPAIGN)
  manager=discovery.DiscoveryManager(app.connect,provider=lambda city,category,cursors:ELEMENTS);run=manager.start('owner',identifier)
  deadline=time.monotonic()+3
  while manager.lock.locked() and time.monotonic()<deadline: time.sleep(.02)
  self.assertFalse(manager.lock.locked())
  with app.connect() as db:
   row=db.execute('SELECT * FROM discovery_runs WHERE id=?',(run,)).fetchone();self.assertEqual(row['status'],'concluido');self.assertEqual(row['added'],1)
  with self.assertRaises(ValueError): manager.start('owner',identifier)
  manager.last_start=0
  with self.assertRaises(LookupError): manager.start('foreign',identifier)
 def test_validation_origin_headers_static_production(self):
  for values in ({'category':'arbitrary'},{'city':'Porto Alegre"];out;'}, {'frequency':'second'},{'enrich_websites':'yes'}):
   self.assertEqual(self.request('POST','/api/discovery/campaigns',{**CAMPAIGN,**values})[0],400)
  self.assertEqual(self.request('POST','/api/discovery/campaigns',CAMPAIGN,{'Origin':'https://attacker.invalid'})[0],403)
  for path in ('/.env','/app.py','/react-login.js.map','/fonts/../../.env'):self.assertEqual(self.request('GET',path)[0],404)
  status,_,headers=self.request('GET','/login');self.assertEqual(status,200);self.assertIn("script-src 'self'",headers['Content-Security-Policy']);self.assertNotIn('Python',headers.get('Server',''))
  with patch.dict(os.environ,{'RADAR_ENV':'production','RADAR_SESSION_SECRET':'a'*40}):
   self.assertFalse(app.registration_enabled('localhost'));self.assertEqual(self.request('GET','/api/discovery')[0],401);self.assertEqual(self.request('POST','/register',{})[0],403)
  with patch.dict(os.environ,{'RADAR_ENV':'production','RADAR_SESSION_SECRET':''}):
   with self.assertRaises(RuntimeError):security.session_secret()
 def test_query_scopes_to_rs_and_record_filters(self):
  query=discovery.query('Porto Alegre','restaurantes');self.assertIn('BR-RS',query);self.assertIn('"restaurant"',query)
  self.assertEqual(discovery.records([dict(type='node',id=1,tags={'name':'Sem telefone'})],{**CAMPAIGN,'require_phone':True,'require_website':False}),[])
 def test_public_source_fallback_and_rate_limit_respect(self):
  from unittest.mock import MagicMock
  response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'elements':ELEMENTS}).encode()
  with patch.object(discovery,'urlopen',side_effect=[TimeoutError(),response]) as transport:
   self.assertEqual(discovery.fetch_osm('Porto Alegre','restaurantes'),ELEMENTS);self.assertEqual(transport.call_count,2)
  with patch.object(discovery,'urlopen',side_effect=HTTPError('https://example.invalid',429,'limit',{},None)) as transport:
   with self.assertRaises(ValueError):discovery.fetch_osm('Porto Alegre','restaurantes')
   self.assertEqual(transport.call_count,1)
 def test_cursor_paging_cache_and_failed_run_rollback(self):
  with app.connect() as db: identifier=discovery.save_campaign(db,'owner',CAMPAIGN)
  calls=[]
  def provider(city,category,cursors):
   calls.append(cursors);return [dict(type='node',id=i,tags={'name':'Empresa '+str(i)}) for i in range(1,52)]
  manager=discovery.DiscoveryManager(app.connect,provider=provider)
  def wait():
   deadline=time.monotonic()+3
   while manager.lock.locked() and time.monotonic()<deadline: time.sleep(.02)
   self.assertFalse(manager.lock.locked())
  manager.start('owner',identifier);wait()
  with app.connect() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0],50)
   self.assertEqual(json.loads(db.execute('SELECT cursor_json FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone()[0]),{'node':50})
   another=discovery.save_campaign(db,'second-owner',CAMPAIGN)
  manager.last_start=0;manager.start('second-owner',another);wait();self.assertEqual(len(calls),1)
  manager.last_start=0
  manager.provider=lambda *args:(_ for _ in ()).throw(RuntimeError('Private transport error'))
  run=manager.start('owner',identifier);wait()
  with app.connect() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox WHERE owner_id=?',('owner',)).fetchone()[0],50)
   self.assertEqual(db.execute('SELECT status FROM discovery_runs WHERE id=?',(run,)).fetchone()[0],'falhou')
   self.assertNotIn('Private transport',db.execute('SELECT message FROM discovery_runs WHERE id=?',(run,)).fetchone()[0])

if __name__=='__main__':unittest.main()
