import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from urllib.parse import urlencode
import app
import admin_panel
import commercial


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='radar-admin-test-')
        self.old_path=app.DB
        self.dbpatch=patch.object(app,'DB',Path(self.tmp.name)/'qa.sqlite');self.dbpatch.start()
        self.env=patch.dict(os.environ,{'RADAR_ADMIN_USER':'rootqa','RADAR_ADMIN_PASSWORD':'QARoot2026@','RADAR_SESSION_SECRET':'qa-session-'*4,'RADAR_ENV':''});self.env.start()
        app.init_db()
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookie=self.login('rootqa','QARoot2026@')
        status,data=self.request('GET','/api/admin/config',cookie=self.cookie)
        self.csrf=json.loads(data)['csrf'];self.assertEqual(status,200)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.env.stop();self.dbpatch.stop();admin_panel.configure(self.old_path);self.tmp.cleanup()

    def request(self,method,path,payload=None,cookie=None,token=True,origin=None):
        connection=HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Content-Type':'application/json'}
        if cookie:headers['Cookie']=cookie
        if token and hasattr(self,'csrf'):headers['X-Radar-CSRF']=self.csrf
        if origin:headers['Origin']=origin
        connection.request(method,path,json.dumps(payload) if payload is not None else None,headers)
        response=connection.getresponse();data=response.read();status=response.status;connection.close();return status,data

    def login(self,user,password):
        connection=HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST','/login',urlencode({'username':user,'password':password}),{'Content-Type':'application/x-www-form-urlencoded'})
        response=connection.getresponse();response.read();cookie=response.getheader('Set-Cookie');connection.close()
        self.assertEqual(response.status,303);return cookie.split(';')[0]

    def config(self):return json.loads(self.request('GET','/api/admin/config',cookie=self.cookie)[1])

    def save(self,values,revision=None):
        return self.request('POST','/api/admin/config',{'revision':self.config()['revision'] if revision is None else revision,'values':values},self.cookie)

    def create_seller(self):
        status,data=self.request('POST','/api/admin/accounts',dict(name='Vendedor QA',username='sellerqa',email='qa@example.invalid',role='vendedor',is_active=True,password='Seller2026@'),self.cookie)
        self.assertEqual(status,200);return json.loads(data)['id']

    def test_admin_requires_signed_session_and_csrf(self):
        self.assertEqual(self.request('GET','/api/admin/config',token=False)[0],401)
        self.assertEqual(self.request('POST','/api/admin/config',{'revision':0,'values':{'animations':False}},self.cookie,token=False)[0],403)
        self.assertEqual(self.request('POST','/api/admin/config',{'revision':0,'values':{'animations':False}},self.cookie,origin='https://evil.invalid')[0],403)
        self.create_seller();seller=self.login('sellerqa','Seller2026@')
        for path in ['/admin','/admin.html','/api/admin/config','/api/admin/state','/api/admin/export']:
            self.assertEqual(self.request('GET',path,cookie=seller)[0],403,path)
        self.assertEqual(self.request('POST','/api/admin/backup',{},seller)[0],403)

    def test_parameters_atomic_validated_conflict_and_runtime(self):
        original=self.config()
        self.assertEqual(self.save({'site_name':'Novo Radar','capture_runs_account':99})[0],400)
        self.assertEqual(self.config()['values']['site_name'],original['values']['site_name'])
        self.assertEqual(self.save({'unknown':True})[0],400)
        self.assertEqual(self.save({'animations':False,'max_columns':3,'contact_sla_hours':24,'test_leads':False,'capture_enabled':False})[0],200)
        self.assertEqual(self.save({'site_name':'stale'},revision=original['revision'])[0],409)
        runtime=json.loads(self.request('GET','/api/runtime',cookie=self.cookie)[1])
        self.assertFalse(runtime['serpro_visible']);self.assertEqual(runtime['max_columns'],3)
        self.assertNotIn('csrf',runtime);self.assertNotIn('base44_secret',runtime)
        with app.connect() as db:self.assertEqual(commercial.settings(db,'unknown')['contact_sla_hours'],24)
        with self.assertRaisesRegex(ValueError,'desativada'):app.DISCOVERY.start('owner','missing')
        self.assertEqual(self.request('POST','/api/team-leads/test',{},self.cookie)[0],403)
        self.assertFalse(app.MONITOR.start())

    @unittest.skipUnless(os.name=='nt','Windows DPAPI storage')
    def test_secrets_never_returned_or_exported(self):
        secret='not-for-browser-'+('x'*40)
        self.assertEqual(self.save({'base44_secret':secret,'base44_endpoint':'https://qa.base44.app/api/functions/radar'})[0],200)
        self.assertEqual(admin_panel.get('base44_secret',app.DB),secret)
        config=json.dumps(self.config());self.assertNotIn(secret,config)
        self.assertTrue(next(x for x in self.config()['fields'] if x['key']=='base44_secret')['configured'])
        exported=self.request('GET','/api/admin/export',cookie=self.cookie)[1].decode();self.assertNotIn('base44_secret',exported);self.assertNotIn(secret,exported)
        with app.connect() as db:
            raw=db.execute("SELECT value FROM admin_parameters WHERE key='base44_secret'").fetchone()[0]
            self.assertNotIn(secret,raw)
            self.assertNotIn(secret,json.dumps([dict(x) for x in db.execute('SELECT * FROM admin_audit')]))
        self.assertEqual(self.save({'base44_endpoint':'https://127.0.0.1/private'})[0],400)
        self.assertEqual(self.save({'base44_secret':''})[0],200);self.assertEqual(admin_panel.get('base44_secret',app.DB),'')

    def test_account_profile_and_deactivation(self):
        identifier=self.create_seller();seller=self.login('sellerqa','Seller2026@')
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sales_profiles WHERE owner_id=?',(identifier,)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT role FROM user_accounts WHERE id=?',(identifier,)).fetchone()[0],'vendedor')
        body=dict(id=identifier,name='Vendedor QA',username='sellerqa',email='qa@example.invalid',role='vendedor',is_active=False)
        self.assertEqual(self.request('POST','/api/admin/accounts',body,self.cookie)[0],200)
        self.assertEqual(self.request('GET','/api/team-profiles',cookie=seller)[0],401)
        with app.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sales_profiles WHERE owner_id=?',(identifier,)).fetchone()[0],1)

    def test_backup_integrity_audit_and_no_path_traversal(self):
        self.create_seller()
        self.assertEqual(self.request('POST','/api/admin/integrity',{},self.cookie)[0],200)
        status,data=self.request('POST','/api/admin/backup',{},self.cookie);self.assertEqual(status,200)
        backup=json.loads(data);target=app.DB.parent/'admin-backups'/backup['name']
        with closing(sqlite3.connect(target)) as db:self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
        status,raw=self.request('GET',backup['url'],cookie=self.cookie);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'SQLite format 3'))
        self.assertEqual(self.request('GET','/api/admin/backups/../../qa.sqlite',cookie=self.cookie)[0],404)
        state=json.loads(self.request('GET','/api/admin/state',cookie=self.cookie)[1])
        self.assertEqual(len(state['backups']),1);self.assertNotIn('password_hash',json.dumps(state));self.assertGreaterEqual(len(state['audit']),3)

    def test_password_reset_and_reactivation_revoke_old_sessions(self):
        identifier=self.create_seller();old_cookie=self.login('sellerqa','Seller2026@')
        body=dict(id=identifier,name='Vendedor QA',username='sellerqa',email='qa@example.invalid',role='vendedor',is_active=True,password='NewPassword2026@')
        self.assertEqual(self.request('POST','/api/admin/accounts',body,self.cookie)[0],200)
        self.assertEqual(self.request('GET','/api/team-profiles',cookie=old_cookie)[0],401)
        new_cookie=self.login('sellerqa','NewPassword2026@')
        self.assertEqual(self.request('GET','/api/team-profiles',cookie=new_cookie)[0],200)
        body.pop('password');body['is_active']=False
        self.assertEqual(self.request('POST','/api/admin/accounts',body,self.cookie)[0],200)
        body['is_active']=True
        self.assertEqual(self.request('POST','/api/admin/accounts',body,self.cookie)[0],200)
        self.assertEqual(self.request('GET','/api/team-profiles',cookie=new_cookie)[0],401)


if __name__=='__main__':unittest.main()
