import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
import app
import recovery
from tests.test_admin_panel import AdminPanelTests


class HelpRecoveryTests(unittest.TestCase):
    setUp=AdminPanelTests.setUp
    tearDown=AdminPanelTests.tearDown
    request=AdminPanelTests.request
    login=AdminPanelTests.login
    create_seller=AdminPanelTests.create_seller

    def test_help_permissions_publication_revision_plain_text_and_feedback(self):
        self.assertEqual(self.request('GET','/api/help',token=False)[0],401)
        self.create_seller();seller=self.login('sellerqa','Seller2026@')
        data=json.loads(self.request('GET','/api/help',cookie=seller)[1])
        self.assertGreaterEqual(len(data['items']),18)
        self.assertFalse(any(x['admin_only'] for x in data['items']))
        payload=dict(id='qa-help',revision=0,title='Pergunta QA <script>nada()</script>',summary='Resumo QA',category='inicio',steps=['Passo único.'],action='empresas',tags='QA',published=False,admin_only=False)
        self.assertEqual(self.request('POST','/api/admin/help',payload,seller)[0],403)
        self.assertEqual(self.request('POST','/api/admin/help',payload,self.cookie,token=False)[0],403)
        self.assertEqual(self.request('POST','/api/admin/help',payload,self.cookie)[0],200)
        self.assertNotIn('qa-help',[x['id'] for x in json.loads(self.request('GET','/api/help',cookie=seller)[1])['items']])
        payload.update(revision=1,published=True)
        self.assertEqual(self.request('POST','/api/admin/help',payload,self.cookie)[0],200)
        self.assertEqual(self.request('POST','/api/admin/help',payload,self.cookie)[0],409)
        data=json.loads(self.request('GET','/api/help',cookie=seller)[1]);article=next(x for x in data['items'] if x['id']=='qa-help')
        self.assertIn('<script>',article['title']) # React renders plain text, not HTML.
        for useful in (True,False):self.assertEqual(self.request('POST','/api/help/feedback',dict(id='qa-help',useful=useful),seller)[0],200)
        admin=json.loads(self.request('GET','/api/admin/help',cookie=self.cookie)[1]);article=next(x for x in admin['items'] if x['id']=='qa-help')
        self.assertEqual(article['feedback'],{'0':1});self.assertNotIn('owner_id',json.dumps(article))
        self.assertEqual(self.request('POST','/api/help/feedback',dict(id='backup',useful=True),seller)[0],404)
        self.assertEqual(self.request('POST','/api/help/feedback',dict(id=[],useful=True),seller)[0],400)
        payload.update(revision=2,category='admin',admin_only=False)
        self.assertEqual(self.request('POST','/api/admin/help',payload,self.cookie)[0],400)
        payload.update(category=[],admin_only=True)
        self.assertEqual(self.request('POST','/api/admin/help',payload,self.cookie)[0],400)
        # Seed never overwrites edited guides, including drafts.
        app.init_db()
        with app.connect() as db:self.assertEqual(db.execute("SELECT revision FROM help_articles WHERE id='qa-help'").fetchone()[0],2)

    def test_recovery_checks_copy_without_changing_live_or_backup(self):
        status,raw=self.request('POST','/api/admin/backup',{},self.cookie);self.assertEqual(status,200)
        filename=json.loads(raw)['name'];target=app.DB.parent/'admin-backups'/filename
        before=hashlib.sha256(target.read_bytes()).hexdigest();mtime=target.stat().st_mtime_ns
        with app.connect() as db:counts=tuple(db.execute('SELECT (SELECT COUNT(*) FROM user_accounts),(SELECT COUNT(*) FROM sales_profile_leads)').fetchone())
        status,raw=self.request('POST','/api/admin/recovery-check',dict(name=filename),self.cookie);self.assertEqual(status,200)
        result=json.loads(raw);self.assertTrue(result['ok']);self.assertEqual(result['relations'],0);self.assertGreater(result['tables_verified'],20)
        self.assertEqual(before,hashlib.sha256(target.read_bytes()).hexdigest());self.assertEqual(mtime,target.stat().st_mtime_ns)
        with app.connect() as db:self.assertEqual(counts,tuple(db.execute('SELECT (SELECT COUNT(*) FROM user_accounts),(SELECT COUNT(*) FROM sales_profile_leads)').fetchone()))
        self.assertEqual(self.request('POST','/api/admin/recovery-check',dict(name='../radar.db'),self.cookie)[0],400)
        # Deliberately corrupt only a disposable fixture, never the application database.
        broken=target.parent/'radar-20000101-000000-deadbeef.sqlite';broken.write_bytes(b'not a database')
        self.assertEqual(self.request('POST','/api/admin/recovery-check',dict(name=broken.name),self.cookie)[0],400)


del AdminPanelTests
