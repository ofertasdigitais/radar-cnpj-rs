"""Security regressions use disposable SQLite and loopback HTTP only."""
import json
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

import app
import security
import test_audit_auth


class SecurityRegressionTests(unittest.TestCase):
    setUp = test_audit_auth.AuthBoundaryTests.setUp
    tearDown = test_audit_auth.AuthBoundaryTests.tearDown
    request = test_audit_auth.AuthBoundaryTests.request
    seed = test_audit_auth.AuthBoundaryTests.seed
    legacy_cookie = test_audit_auth.AuthBoundaryTests.legacy_cookie

    def login(self, name, password='SellerQA2026@'):
        status, _, cookie = self.request('POST', '/login', {'username': name, 'password': password})
        self.assertEqual(status, 303)
        return cookie.split(';')[0]

    def json_request(self, method, path, payload, cookie):
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        connection.request(method, path, body, {'Content-Type': 'application/json', 'Cookie': cookie})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def sellers(self):
        for name in ('aliceqa', 'bobqa'):
            self.seed(name)
            with app.connect() as db:
                db.execute("INSERT INTO sales_profiles(id,name,owner_id,created_at,updated_at) VALUES(?,?,?,'2026-10-01','2026-10-01')", (name, name, 'id-' + name))
        return self.login('aliceqa'), self.login('bobqa')

    def test_logout_revokes_copied_account_bootstrap_and_legacy_cookies(self):
        alice, bob = self.sellers()
        for make_cookie in (lambda: self.legacy_cookie('aliceqa'), lambda: self.login('aliceqa'), lambda: self.login('rootqa', 'BootstrapQA2026@')):
            cookie = make_cookie()
            self.assertEqual(self.request('GET', '/api/team-profiles', cookie=cookie)[0], 200)
            self.assertEqual(self.request('GET', '/logout', cookie=cookie)[0], 303)
            self.assertEqual(self.request('GET', '/api/team-profiles', cookie=cookie)[0], 401)
            self.assertEqual(self.request('GET', '/api/team-profiles', cookie=bob)[0], 200)
        self.assertEqual(self.request('GET', '/api/team-profiles', cookie=self.login('aliceqa'))[0], 200)

    def test_fake_contact_cannot_be_linked_or_read_by_another_seller(self):
        alice, bob = self.sellers()
        status, body = self.json_request('POST', '/api/team-leads/test', {'profile_id': 'aliceqa', 'name': 'Private QA', 'phone': '51987654321'}, alice)
        self.assertEqual(status, 201, body)
        cnpj = json.loads(body)['cnpj']
        status, body = self.json_request('POST', '/api/profiles', {'name': 'QA segment'}, bob)
        self.assertEqual(status, 201)
        segment = json.loads(body)['id']
        for path, payload in [('/api/team-leads', {'profile_id': 'bobqa', 'cnpj': cnpj, 'allow_duplicate': True}), ('/api/profile-leads', {'profile_id': segment, 'cnpj': cnpj})]:
            self.assertEqual(self.json_request('POST', path, payload, bob)[0], 404)
        self.assertEqual(self.json_request('PUT', '/api/leads/' + cnpj, {'favorito': True}, bob)[0], 404)
        body = self.request('GET', '/api/prospects/company?cnpj=' + cnpj, cookie=bob)[1]
        self.assertIsNone(json.loads(body)['item'])
        # Historical links must not remain a bypass after migration.
        with app.connect() as db:
            db.execute("INSERT INTO profile_leads VALUES(?,?, '2026-10-01')", (segment, cnpj))
            db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES('bobqa',?,'2026-10-01','2026-10-01')", (cnpj,))
            db.execute("INSERT INTO commercial_archive(profile_id,cnpj,company_name,removed_at,events_json) VALUES('bobqa',?,'Private QA','2026-10-01','51987654321')", (cnpj,))
        for path in ('/api/profile-leads?profile_id=' + segment, '/api/team-leads?profile_id=bobqa', '/api/commercial?profile_id=bobqa', '/api/sales-ops?profile_id=bobqa', '/api/team-leads.csv?profile_id=bobqa', '/api/commercial-archive?profile_id=bobqa'):
            status, body, _ = self.request('GET', path, cookie=bob)
            self.assertEqual(status, 200, body)
            self.assertNotIn(b'Private QA', body)
            self.assertNotIn(b'51987654321', body)
        self.assertIn(b'Private QA', self.request('GET', '/api/team-leads?profile_id=aliceqa', cookie=alice)[1])
        with app.connect() as db:
            db.execute("UPDATE companies SET uf='RS',situacao='ATIVA' WHERE cnpj=?",(cnpj,))
        self.assertNotIn(b'Private QA', self.request('GET','/api/team-leads?profile_id=bobqa',cookie=bob)[1])
        self.assertIsNone(json.loads(self.request('GET','/api/prospects/company?cnpj='+cnpj,cookie=bob)[1])['item'])
        self.assertNotIn(b'Private QA', self.request('GET','/api/companies?inicio=1900-01-01',cookie=bob)[1])
        self.assertNotIn(b'Teste interno', self.request('GET','/api/stats',cookie=bob)[1])
        with app.connect() as db:
            db.execute("INSERT INTO companies(cnpj,razao_social,uf,situacao) VALUES('11222333000181','Public RF QA','RS','ATIVA')")
        self.assertEqual(self.json_request('POST', '/api/team-leads', {'profile_id': 'bobqa', 'cnpj': '11222333000181'}, bob)[0], 201)

    def test_legacy_private_markers_migration_and_metadata_do_not_leak(self):
        alice, bob = self.sellers()
        with app.connect() as db:
            db.execute("INSERT INTO companies(cnpj,razao_social,uf,situacao,municipio,segmento,cnae,cnae_descricao) VALUES('99900000000001','Private marker QA','RS','TESTE','Private City QA','Private Segment QA','0000001','Private CNAE QA')")
            db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES('aliceqa','99900000000001','2026-10-01','2026-10-01')")
            db.execute("INSERT INTO companies(cnpj,razao_social,uf,situacao) VALUES('99900000000002','Ambiguous QA','ZZ','TESTE')")
            for profile in ('aliceqa','bobqa'):
                db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES(?,'99900000000002','2026-10-01','2026-10-01')", (profile,))
        app.init_db()
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT owner_id FROM private_companies WHERE cnpj='99900000000001'").fetchone()[0], 'id-aliceqa')
            self.assertIsNone(db.execute("SELECT owner_id FROM private_companies WHERE cnpj='99900000000002'").fetchone()[0])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sales_profile_leads").fetchone()[0], 3)
        for cookie in (alice,bob):
            self.assertNotIn(b'Ambiguous QA', self.request('GET', '/api/team-leads?profile_id=' + ('aliceqa' if cookie==alice else 'bobqa'), cookie=cookie)[1])
        self.assertIn(b'Private marker QA', self.request('GET', '/api/team-leads?profile_id=aliceqa', cookie=alice)[1])
        self.assertNotIn(b'Private', self.request('GET', '/api/stats', cookie=bob)[1])
        self.assertIsNone(json.loads(self.request('GET', '/api/prospects/company?cnpj=99900000000001', cookie=bob)[1])['item'])

    def test_host_and_api_budgets_reject_abuse_preserve_normal_requests(self):
        alice, _ = self.sellers()
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('GET','/login',headers={'Host':'attacker.invalid'})
        response=connection.getresponse();response.read();connection.close()
        self.assertEqual(response.status,403)
        self.server.api_reads=security.AttemptLimiter(maximum=1,window=60)
        self.assertEqual(self.request('GET','/api/team-profiles',cookie=alice)[0],200)
        self.assertEqual(self.request('GET','/api/team-profiles',cookie=alice)[0],429)
        # A completed response can precede the handler's final slot release.
        # Use a fresh server, rather than racing handlers from the rate test.
        with app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler) as limited:
            for _ in range(32):self.assertTrue(limited.slots.acquire(blocking=False))
            worker = threading.Thread(target=limited.serve_forever, daemon=True)
            worker.start()
            try:
                connection = HTTPConnection('127.0.0.1', limited.server_port)
                connection.request('GET', '/healthz')
                response = connection.getresponse(); response.read(); connection.close()
                self.assertEqual(response.status, 503)
                for _ in range(32):limited.slots.release()
                connection = HTTPConnection('127.0.0.1', limited.server_port)
                connection.request('GET', '/healthz')
                response = connection.getresponse(); response.read(); connection.close()
                self.assertEqual(response.status, 200)
            finally:
                limited.shutdown(); worker.join()

    def test_json_object_boundary_rejects_other_roots_and_invalid_utf8(self):
        alice, _ = self.sellers()
        routes = [('POST', p) for p in ('/api/team-profiles', '/api/message-templates', '/api/team-leads', '/api/profiles', '/api/profile-leads', '/api/team-leads/test', '/api/team-lead-events', '/api/prospects/qualify', '/api/commercial-settings', '/api/sales-ops/contact')]
        routes += [('PUT', '/api/team-leads'), ('PUT', '/api/message-templates/unknown'), ('PUT', '/api/leads/11222333000181')]
        for method, path in routes:
            for payload in (None, [], [1], True, 7, 'text', b'{"bad":"\xff"}'):
                with self.subTest(method=method, path=path, payload=payload):
                    self.assertEqual(self.json_request(method, path, payload, alice)[0], 400)
        self.assertEqual(self.json_request('POST', '/api/message-templates', {'name': 'Valid QA', 'body': 'Hello'}, alice)[0], 201)
        self.assertEqual(self.json_request('POST', '/api/message-templates', b'{"name":"QA","body":"' + b'x' * 17000 + b'"}', alice)[0], 413)

    def test_global_jobs_are_admin_only_even_in_local_mode(self):
        alice, _ = self.sellers()
        with patch.object(app.SYNC, 'start', return_value=False) as sync, patch.object(app.MONITOR, 'start', return_value=False) as monitor:
            for path in ('/api/sync', '/api/monitor'):
                self.assertEqual(self.json_request('POST', path, {}, alice)[0], 403)
            sync.assert_not_called()
            monitor.assert_not_called()
