"""Auth regression checks against an isolated database, never the live Radar."""
import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import app
import admin_panel
import security


class AuthBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='radar-audit-auth-')
        self.old_db = app.DB
        self.patches = [
            patch.object(app, 'DB', Path(self.directory.name) / 'qa.sqlite'),
            patch.dict(os.environ, {'RADAR_ADMIN_USER': 'rootqa',
                'RADAR_ADMIN_PASSWORD': 'BootstrapQA2026@',
                'RADAR_SESSION_SECRET': 'isolated-audit-secret-' * 3,
                'RADAR_ALLOW_REGISTRATION': '1', 'RADAR_REGISTRATION_CODE': '', 'RADAR_ENV': ''}),
            patch.object(security, 'LOGIN_LIMITER', security.AttemptLimiter()),
            patch.object(security, 'LOGIN_EDGE_LIMITER', security.AttemptLimiter(maximum=1000)),
        ]
        for item in self.patches: item.start()
        app.init_db()
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        for item in reversed(self.patches): item.stop()
        admin_panel.configure(self.old_db)
        self.directory.cleanup()

    def request(self, method, path, form=None, cookie=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if cookie: headers['Cookie'] = cookie
        connection.request(method, path, urlencode(form) if form else None, headers)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheader('Set-Cookie')
        connection.close()
        return result

    def register(self, username):
        return self.request('POST', '/register', {'name': 'Teste isolado', 'username': username,
            'email': username.strip().lower() + '@example.invalid', 'password': 'SellerQA2026@',
            'confirm_password': 'SellerQA2026@'})

    def seed(self, username, role='vendedor'):
        salt, digest = app.password_digest('SellerQA2026@')
        with app.connect() as db:
            db.execute('''INSERT INTO user_accounts
                (id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,1,'2026-10-07','2026-10-07')''',
                ('id-' + username, 'Teste isolado', username, username + '@example.invalid', digest, salt, role))

    def test_reserved_registration_case_and_spaces_are_rejected_without_writes(self):
        for name in ['rootqa', 'RoOtQA', ' rootqa ']:
            status, body, cookie = self.register(name)
            self.assertEqual(status, 400)
            self.assertIn('reservado', body.decode())
            self.assertIsNone(cookie)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM user_accounts').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sales_profiles').fetchone()[0], 0)

    def test_login_polish_stylesheet_is_public_without_exposing_app_data(self):
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('GET', '/radar-polish.css?v=3')
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn('text/css', response.getheader('Content-Type'))
        self.assertIn(b'discovery-bell', body)
        self.assertEqual(response.getheader('X-Content-Type-Options'), 'nosniff')
        connection.close()
        self.assertEqual(self.request('GET', '/api/team-profiles')[0], 401)
        self.assertEqual(self.request('GET', '/admin')[0], 303)

    def test_existing_collision_cannot_login_by_username_case_or_email(self):
        self.seed('rootqa')
        for login in ['rootqa', 'RoOtQA', 'rootqa@example.invalid']:
            status, _, cookie = self.request('POST', '/login', {'username': login, 'password': 'SellerQA2026@'})
            self.assertEqual(status, 401); self.assertIsNone(cookie)
        status, _, cookie = self.request('POST', '/login', {'username': 'rootqa', 'password': 'BootstrapQA2026@'})
        self.assertEqual(status, 303)
        self.assertEqual(self.request('GET', '/api/admin/config', cookie=cookie.split(';')[0])[0], 200)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM user_accounts').fetchone()[0], 1)

    def legacy_cookie(self, username):
        payload = f'{username}|{int(time.time()) + 3600}'
        signature = hmac.new(security.session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
        return 'radar_session=' + base64.urlsafe_b64encode(f'{payload}|{signature}'.encode()).decode()

    def test_ambiguous_legacy_admin_cookie_rejected_normal_seller_preserved(self):
        self.seed('rootqa'); self.seed('sellerqa')
        self.assertEqual(self.request('GET', '/api/admin/config', cookie=self.legacy_cookie('rootqa'))[0], 401)
        cookie = self.legacy_cookie('sellerqa')
        self.assertEqual(self.request('GET', '/api/companies?size=1', cookie=cookie)[0], 200)
        self.assertEqual(self.request('GET', '/api/admin/config', cookie=cookie)[0], 403)

    def test_active_database_admin_and_seller_keep_their_roles(self):
        for name, role, expected in [('sellerqa', 'vendedor', 403), ('managerqa', 'gestor', 200)]:
            self.seed(name, role)
            status, _, cookie = self.request('POST', '/login', {'username': name + '@example.invalid', 'password': 'SellerQA2026@'})
            self.assertEqual(status, 303)
            cookie = cookie.split(';')[0]
            self.assertEqual(self.request('GET', '/api/admin/config', cookie=cookie)[0], expected)
            with app.connect() as db: admin_panel.revoke_sessions(db, name)
            self.assertEqual(self.request('GET', '/api/companies', cookie=cookie)[0], 401)

    def test_bootstrap_pipe_name_and_password_reset_revoke_sessions(self):
        with patch.dict(os.environ, {'RADAR_ADMIN_USER': 'ops|admin'}):
            status, _, cookie = self.request('POST', '/login', {'username':'ops|admin','password':'BootstrapQA2026@'})
            self.assertEqual(status, 303)
            cookie = cookie.split(';')[0]
            self.assertEqual(self.request('GET','/api/admin/config',cookie=cookie)[0],200)
            with patch.dict(os.environ, {'RADAR_ADMIN_PASSWORD':'NewBootstrapQA2026@'}):
                self.assertEqual(self.request('GET','/api/admin/config',cookie=cookie)[0],401)

    def test_aliases_share_attempt_budget_other_account_cannot_clear_it(self):
        self.seed('sellerqa'); self.seed('otherqa')
        for i in range(8):
            alias = 'SeLlErQa' if i%2 else 'sellerqa@example.invalid'
            self.assertEqual(self.request('POST','/login',{'username':alias,'password':'bad'})[0],401)
        self.assertEqual(self.request('POST','/login',{'username':'otherqa','password':'SellerQA2026@'})[0],303)
        self.assertEqual(self.request('POST','/login',{'username':'sellerqa','password':'SellerQA2026@'})[0],429)
        self.assertEqual(self.request('POST','/login',{'username':'rootqa','password':'BootstrapQA2026@'})[0],303)

    def test_unverified_name_never_adopts_ownerless_profile(self):
        self.seed('sellerqa')
        with app.connect() as db:
            db.execute("INSERT INTO sales_profiles(id,name,email,created_at,updated_at) VALUES('legacy','Teste isolado','sellerqa@example.invalid','2026-10-07','2026-10-07')")
        app.init_db()
        with app.connect() as db:
            self.assertIsNone(db.execute("SELECT owner_id FROM sales_profiles WHERE id='legacy'").fetchone()[0])

    def test_bootstrap_admin_can_repair_collision_without_replacing_account(self):
        self.seed('rootqa')
        _, _, cookie = self.request('POST','/login',{'username':'rootqa','password':'BootstrapQA2026@'})
        cookie = cookie.split(';')[0]
        csrf=json.loads(self.request('GET','/api/admin/config',cookie=cookie)[1])['csrf']
        connection=HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST','/api/admin/accounts',json.dumps({'id':'id-rootqa','name':'Teste isolado',
            'username':'repairedqa','email':'rootqa@example.invalid','role':'vendedor','is_active':True}),
            {'Content-Type':'application/json','Cookie':cookie,'X-Radar-CSRF':csrf})
        response=connection.getresponse();body=response.read();connection.close()
        self.assertEqual(response.status,200,body)
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT username FROM user_accounts WHERE id='id-rootqa'").fetchone()[0],'repairedqa')

    def test_csv_neutralizes_text_not_numbers(self):
        for text in ['=SUM(1,2)',' +cmd','\t=HYPERLINK("bad")','\rabc','\nabc','\ufeff@cmd',' -5']:
            self.assertEqual(security.csv_cell(text),"'"+text)
        for value in ['Empresa normal','51999999999',12,-12,12.50,None]:
            self.assertEqual(security.csv_cell(value),value)

    def test_bootstrap_email_alias_cannot_clear_budget_using_seller_password(self):
        self.seed('sellerqa')
        with app.connect() as db:db.execute("UPDATE user_accounts SET email='admin@example.invalid' WHERE username='sellerqa'")
        with patch.dict(os.environ,{'RADAR_ADMIN_USER':'admin@example.invalid'}):
            for _ in range(7):
                self.assertEqual(self.request('POST','/login',{'username':'admin@example.invalid','password':'bad'})[0],401)
            self.assertEqual(self.request('POST','/login',{'username':'admin@example.invalid','password':'SellerQA2026@'})[0],401)
            self.assertEqual(self.request('POST','/login',{'username':'admin@example.invalid','password':'BootstrapQA2026@'})[0],429)
            self.assertEqual(self.request('POST','/login',{'username':'sellerqa','password':'SellerQA2026@'})[0],303)

    def test_unknown_name_spray_never_locks_known_tunnel_users(self):
        self.seed('sellerqa')
        with patch.object(security,'LOGIN_EDGE_LIMITER',security.AttemptLimiter(maximum=1)):
            self.assertEqual(self.request('POST','/login',{'username':'unknown1','password':'bad'})[0],401)
            self.assertEqual(self.request('POST','/login',{'username':'unknown2','password':'bad'})[0],429)
            self.assertEqual(self.request('POST','/login',{'username':'sellerqa','password':'SellerQA2026@'})[0],303)


if __name__ == '__main__': unittest.main()
