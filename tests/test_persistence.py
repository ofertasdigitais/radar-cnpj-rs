import json
from contextlib import closing
import sqlite3
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import app


class PersistenceTests(unittest.TestCase):
    def test_sales_wallet_is_isolated_between_registered_accounts(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'radar.db'), patch.dict('os.environ', {'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': '', 'RADAR_ALLOW_REGISTRATION': '1'}):
            app.init_db()
            with app.connect() as db:
                db.execute("""INSERT INTO companies(cnpj,razao_social,nome_fantasia,uf,situacao,telefone)
                    VALUES('11222333000181','Empresa privada A','Oportunidade A','RS','ATIVA','(51) 99999-9999')""")
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = ('127.0.0.1', server.server_port)

            def register(name, username, email):
                connection = HTTPConnection(*base)
                body = urlencode({'name': name, 'username': username, 'email': email, 'password': 'SenhaSegura2026', 'confirm_password': 'SenhaSegura2026'})
                connection.request('POST', '/register', body, {'Content-Type': 'application/x-www-form-urlencoded'})
                response = connection.getresponse(); self.assertEqual(response.status, 303)
                cookie = response.getheader('Set-Cookie').split(';', 1)[0]
                response.read(); connection.close(); return cookie

            def request(method, path, cookie, payload=None):
                connection = HTTPConnection(*base)
                body = json.dumps(payload).encode() if payload is not None else None
                headers = {'Cookie': cookie, **({'Content-Type': 'application/json'} if body else {})}
                connection.request(method, path, body, headers)
                response = connection.getresponse(); raw = response.read(); status = response.status
                connection.close(); return status, raw

            try:
                cookie_a = register('Vendedor A', 'vendedor.a', 'vendedor.a@example.com')
                cookie_b = register('Vendedor B', 'vendedor.b', 'vendedor.b@example.com')
                status, raw = request('GET', '/api/team-profiles', cookie_a)
                self.assertEqual(status, 200)
                profile_a = json.loads(raw)['items'][0]['id']
                status, raw = request('POST', '/api/team-leads', cookie_a, {'profile_id': profile_a, 'cnpj': '11222333000181'})
                self.assertEqual(status, 201)
                # Formatted, unformatted and partial phones search only this seller's leads.
                for phone in ('(51) 99999-9999', '51999999999', '99999-9999'):
                    path = '/api/team-leads?' + urlencode({'profile_id': profile_a, 'q': phone})
                    status, raw = request('GET', path, cookie_a)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(raw)['total'], 1)
                    status, _ = request('GET', path, cookie_b)
                    self.assertEqual(status, 404)
                with app.connect() as db:
                    db.execute("UPDATE sales_profile_leads SET whatsapp_phone='55 (11) 98888-7777' WHERE profile_id=?", (profile_a,))
                for phone, expected in (('11988887777', 1), ('(11) 98888-7777', 1), ('123456789', 0), ('Oportunidade A', 1)):
                    status, raw = request('GET', '/api/team-leads?' + urlencode({'profile_id': profile_a, 'q': phone}), cookie_a)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(raw)['total'], expected)
                status, raw = request('PUT', '/api/team-leads', cookie_a, {
                    'profile_id': profile_a, 'cnpj': '11222333000181', 'lead_status': 'negociacao',
                    'contact_outcome': 'oportunidade', 'offered_value_cents': '1500,00',
                    'negotiated_value_cents': '1200,00', 'next_action': 'Enviar contrato'
                })
                self.assertEqual(status, 200)
                saved = json.loads(raw)
                self.assertEqual(saved['profile_offered_value_cents'], 150000)
                self.assertEqual(saved['profile_negotiated_value_cents'], 120000)
                with app.connect() as db:
                    db.execute('DELETE FROM sales_lead_history WHERE profile_id=?', (profile_a,))
                    app.add_lead_history(db, profile_a, '11222333000181', 'stage_changed', 'Etapa alterada na sexta', 'Novo → Contatado', '2026-10-02T15:30:00')
                    app.add_lead_history(db, profile_a, '11222333000181', 'notes_updated', 'Atualizado na segunda', 'Novo contexto', '2026-10-05T09:00:00')
                period = urlencode({'profile_id': profile_a, 'activity_from': '2026-10-02', 'activity_to': '2026-10-02'})
                status, raw = request('GET', '/api/team-leads?' + period, cookie_a)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw)['total'], 1)
                status, raw = request('GET', '/api/team-activity?' + period, cookie_a)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw)['total'], 1)
                self.assertEqual(json.loads(raw)['items'][0]['title'], 'Etapa alterada na sexta')
                status, _ = request('GET', '/api/team-activity?' + period, cookie_b)
                self.assertEqual(status, 404)
                for route in ('/api/team-leads?', '/api/team-activity?'):
                    status, raw = request('GET', route + urlencode({'profile_id': profile_a, 'activity_from': '2026-10-03', 'activity_to': '2026-10-04'}), cookie_a)
                    self.assertEqual(json.loads(raw)['total'], 0)
                    for start, end in (('2026-02-30', ''), ('2026-10-05', '2026-10-02')):
                        status, _ = request('GET', route + urlencode({'profile_id': profile_a, 'activity_from': start, 'activity_to': end}), cookie_a)
                        self.assertEqual(status, 400)
                status, _ = request('PUT', '/api/leads/11222333000181', cookie_a, {
                    'lead_status': 'contatado', 'favorito': True, 'observacoes': 'Privado da conta A'
                })
                self.assertEqual(status, 200)
                status, raw = request('GET', '/api/companies?q=11222333000181&size=5', cookie_b)
                self.assertEqual(status, 200)
                company_b = json.loads(raw)['items'][0]
                self.assertEqual(company_b['lead_status'], 'novo')
                self.assertEqual(company_b['favorito'], 0)
                self.assertEqual(company_b['observacoes'], '')
                status, raw = request('GET', '/api/companies?q=11222333000181&size=5', cookie_a)
                company_a = json.loads(raw)['items'][0]
                self.assertEqual(company_a['lead_status'], 'contatado')
                self.assertEqual(company_a['favorito'], 1)
                self.assertEqual(company_a['observacoes'], 'Privado da conta A')

                for method, path, payload in (
                    ('GET', '/api/team-leads?profile_id=' + profile_a, None),
                    ('GET', '/api/team-dashboard?profile_id=' + profile_a, None),
                    ('GET', '/api/team-lead-history?profile_id=' + profile_a + '&cnpj=11222333000181', None),
                    ('GET', '/api/team-leads.csv?profile_id=' + profile_a, None),
                    ('PUT', '/api/team-leads', {'profile_id': profile_a, 'cnpj': '11222333000181', 'lead_status': 'convertido'}),
                    ('DELETE', '/api/team-leads?profile_id=' + profile_a + '&cnpj=11222333000181', None),
                ):
                    status, _ = request(method, path, cookie_b, payload)
                    self.assertEqual(status, 404, (method, path, status))

                status, raw = request('GET', '/api/team-profiles', cookie_b)
                visible_b = json.loads(raw)['items']
                self.assertEqual(len(visible_b), 1)
                self.assertNotEqual(visible_b[0]['id'], profile_a)
                status, raw = request('GET', '/api/team-dashboard?profile_id=' + profile_a, cookie_a)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw)['summary']['negotiated_value_cents'], 120000)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_whatsapp_message_templates_are_persistent_and_account_private(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'radar.db'), patch.dict('os.environ', {'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': '', 'RADAR_ALLOW_REGISTRATION': '1'}):
            app.init_db()
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = '127.0.0.1', server.server_port

            def register(name, username, email):
                connection = HTTPConnection(*base)
                body = urlencode({'name': name, 'username': username, 'email': email, 'password': 'SenhaSegura2026', 'confirm_password': 'SenhaSegura2026'})
                connection.request('POST', '/register', body, {'Content-Type': 'application/x-www-form-urlencoded'})
                response = connection.getresponse()
                self.assertEqual(response.status, 303)
                cookie = response.getheader('Set-Cookie').split(';', 1)[0]
                response.read(); connection.close()
                return cookie

            def request_json(method, path, cookie, payload=None):
                connection = HTTPConnection(*base)
                body = json.dumps(payload).encode() if payload is not None else None
                headers = {'Cookie': cookie}
                if body is not None:
                    headers['Content-Type'] = 'application/json'
                connection.request(method, path, body, headers)
                response = connection.getresponse()
                data = json.loads(response.read().decode())
                status = response.status
                connection.close()
                return status, data

            try:
                cookie_a = register('Conta A', 'conta.a', 'a@example.com')
                status, initial_a = request_json('GET', '/api/message-templates', cookie_a)
                self.assertEqual(status, 200)
                self.assertEqual(len(initial_a['items']), 1)
                self.assertEqual(initial_a['items'][0]['is_default'], 1)

                status, created = request_json('POST', '/api/message-templates', cookie_a, {
                    'name': 'Oferta mensal',
                    'body': 'Olá {empresa}, falo com você de {cidade}.',
                    'is_default': True,
                })
                self.assertEqual(status, 201)
                self.assertEqual(created['is_default'], 1)

                cookie_b = register('Conta B', 'conta.b', 'b@example.com')
                status, templates_b = request_json('GET', '/api/message-templates', cookie_b)
                self.assertEqual(status, 200)
                self.assertNotIn('Oferta mensal', [item['name'] for item in templates_b['items']])

                status, updated = request_json('PUT', '/api/message-templates/' + created['id'], cookie_a, {
                    'name': 'Oferta principal',
                    'body': 'Olá {empresa}! Meu nome é {vendedor}.',
                    'is_default': True,
                })
                self.assertEqual(status, 200)
                self.assertEqual(updated['name'], 'Oferta principal')

                app.init_db()
                status, persisted = request_json('GET', '/api/message-templates', cookie_a)
                self.assertEqual(status, 200)
                self.assertIn('Oferta principal', [item['name'] for item in persisted['items']])
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_registered_account_is_hashed_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'radar.db'), patch.dict('os.environ', {'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': '', 'RADAR_ALLOW_REGISTRATION': '1'}):
            app.init_db()

            def start_server():
                server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                return server, thread

            server, thread = start_server()
            try:
                connection = HTTPConnection('127.0.0.1', server.server_port)
                registration = urlencode({
                    'name': 'Ana Comercial', 'username': 'ana.vendas',
                    'email': 'ana@example.com', 'password': 'SenhaSegura2026',
                    'confirm_password': 'SenhaSegura2026',
                })
                connection.request('POST', '/register', registration, {'Content-Type': 'application/x-www-form-urlencoded'})
                response = connection.getresponse()
                self.assertEqual(response.status, 303)
                self.assertIn('radar_session=', response.getheader('Set-Cookie'))
                response.read(); connection.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()

            with closing(sqlite3.connect(app.DB)) as db:
                account = db.execute("SELECT username,email,password_hash,password_salt FROM user_accounts").fetchone()
                self.assertEqual(account[:2], ('ana.vendas', 'ana@example.com'))
                self.assertNotIn('SenhaSegura2026', account[2])
                self.assertTrue(app.password_matches('SenhaSegura2026', account[3], account[2]))

            app.init_db()
            server, thread = start_server()
            try:
                connection = HTTPConnection('127.0.0.1', server.server_port)
                login = urlencode({'username': 'ana@example.com', 'password': 'SenhaSegura2026'})
                connection.request('POST', '/login', login, {'Content-Type': 'application/x-www-form-urlencoded'})
                response = connection.getresponse()
                self.assertEqual(response.status, 303)
                cookie = response.getheader('Set-Cookie').split(';', 1)[0]
                response.read(); connection.close()

                connection = HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/api/companies?size=1', headers={'Cookie': cookie})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read(); connection.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_seller_changes_and_profiles_survive_server_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'radar.db'), patch.dict('os.environ', {'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': ''}):
            app.init_db()
            with app.connect() as db:
                db.execute("INSERT INTO companies(cnpj,razao_social) VALUES('12345678000190','Teste isolado')")
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = 'http://127.0.0.1:' + str(server.server_port)
                payload = {'lead_status': 'contatado', 'favorito': 1, 'observacoes': 'Retornar amanhã às 14h'}
                request = Request(base + '/api/leads/12345678000190', data=json.dumps(payload).encode(), method='PUT', headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                request = Request(base + '/api/profiles', data=json.dumps({'name': 'MEIs da equipe', 'filters': {'mei': 'sim', 'cnae': '7319002'}}).encode(), headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 201)
                    profile = json.load(response)
                request = Request(base + '/api/profile-leads', data=json.dumps({'profile_id': profile['id'], 'cnpj': '12345678000190'}).encode(), method='POST', headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 201)
                with urlopen(base + '/api/profile-leads?profile_id=' + profile['id']) as response:
                    wallet = json.load(response)
                    self.assertEqual(wallet['total'], 1)
                    self.assertEqual(wallet['items'][0]['cnpj'], '12345678000190')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            app.init_db()
            with closing(sqlite3.connect(app.DB)) as fresh:
                self.assertEqual(fresh.execute("""SELECT lead_status,favorito,observacoes FROM account_company_state
                    WHERE account_id='local-default' AND cnpj='12345678000190'""").fetchone(), ('contatado', 1, 'Retornar amanhã às 14h'))
                filters = fresh.execute("SELECT filters_json FROM prospecting_profiles WHERE name='MEIs da equipe'").fetchone()[0]
                self.assertEqual(json.loads(filters), {'mei': 'sim', 'cnae': '7319002'})
                membership = fresh.execute("SELECT profile_id,cnpj FROM profile_leads").fetchone()
                self.assertEqual(membership, (profile['id'], '12345678000190'))

    def test_individual_profile_workspace_survives_server_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'radar.db'), patch.dict('os.environ', {'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': ''}):
            app.init_db()
            with app.connect() as db:
                db.execute("""INSERT INTO companies(
                    cnpj,razao_social,nome_fantasia,data_abertura,cnae,cnae_descricao,
                    segmento,municipio,uf,situacao,telefone,email
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    '98765432000110', 'Empresa da carteira', 'Lead persistente', '2026-09-14',
                    '7319002', 'Promoção de vendas', 'Serviços profissionais', 'Porto Alegre',
                    'RS', 'ATIVA', '51999999999', 'lead@example.com'
                ))
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = 'http://127.0.0.1:' + str(server.server_port)
                request = Request(base + '/api/team-profiles', data=json.dumps({
                    'name': 'Ana Vendas', 'role': 'Executiva comercial', 'email': 'ana@example.com'
                }).encode(), headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 201)
                    profile = json.load(response)

                request = Request(base + '/api/team-leads', data=json.dumps({
                    'profile_id': profile['id'], 'cnpj': '98765432000110'
                }).encode(), headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 201)

                request = Request(base + '/api/team-leads', data=json.dumps({
                    'profile_id': profile['id'], 'cnpj': '98765432000110',
                    'favorito': True, 'lead_status': 'qualificado',
                    'contact_outcome': 'retornar',
                    'next_action': 'Enviar proposta comercial',
                    'next_action_at': '2026-09-30T10:30',
                    'whatsapp_status': 'confirmed',
                    'whatsapp_phone': '5551999999999',
                    'observacoes': 'Retornar na sexta-feira',
                    'estrategia': 'Apresentar plano anual por telefone'
                }).encode(), method='PUT', headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    saved = json.load(response)
                    self.assertEqual(saved['profile_favorito'], 1)
                    self.assertEqual(saved['profile_lead_status'], 'qualificado')
                    self.assertEqual(saved['profile_contact_outcome'], 'retornar')
                    self.assertEqual(saved['profile_next_action'], 'Enviar proposta comercial')
                    self.assertEqual(saved['profile_whatsapp_status'], 'confirmed')

                with urlopen(base + '/api/team-leads?profile_id=' + profile['id'] + '&view=favorites') as response:
                    portfolio = json.load(response)
                    self.assertEqual(portfolio['total'], 1)
                    self.assertEqual(portfolio['items'][0]['profile_estrategia'], 'Apresentar plano anual por telefone')
                    self.assertEqual(portfolio['items'][0]['profile_next_action_at'], '2026-09-30T10:30')
                    self.assertEqual(portfolio['items'][0]['profile_whatsapp_status'], 'confirmed')

                with urlopen(base + '/api/team-leads?profile_id=' + profile['id'] + '&whatsapp=confirmed') as response:
                    self.assertEqual(json.load(response)['total'], 1)

                with urlopen(base + '/api/team-leads?profile_id=' + profile['id'] + '&q=Lead%20persistente&sort=deadline') as response:
                    filtered = json.load(response)
                    self.assertEqual(filtered['total'], 1)
                    self.assertEqual(filtered['q'], 'Lead persistente')
                    self.assertEqual(filtered['sort'], 'deadline')

                with urlopen(base + '/api/team-leads?profile_id=' + profile['id'] + '&focus=negotiation') as response:
                    self.assertEqual(json.load(response)['total'], 0)

                with urlopen(base + '/api/team-dashboard?profile_id=' + profile['id']) as response:
                    summary = json.load(response)['summary']
                    self.assertEqual(summary['active'], 1)
                    self.assertEqual(summary['uncontacted'], 0)
                    self.assertEqual(summary['without_next_action'], 0)
                    self.assertEqual(summary['whatsapp_confirmed'], 1)

                with urlopen(base + '/api/team-lead-history?profile_id=' + profile['id'] + '&cnpj=98765432000110') as response:
                    history = json.load(response)['items']
                    self.assertTrue(any(item['event_type'] == 'created' for item in history))
                    self.assertTrue(any(item['event_type'] == 'contact_outcome' for item in history))
                    self.assertTrue(any(item['event_type'] == 'next_action' for item in history))

                with urlopen(base + '/api/team-leads.csv?profile_id=' + profile['id'] + '&view=favorites') as response:
                    exported = response.read()
                    self.assertTrue(exported.startswith(b'\xef\xbb\xbf'))
                    self.assertIn('Lead persistente', exported.decode('utf-8-sig'))
                with urlopen(base + '/api/team-leads.csv?profile_id=' + profile['id'] + '&fields=empresa,whatsapp_phone,whatsapp_status&delimiter=comma&filename=crm-teste') as response:
                    configured = response.read().decode('utf-8-sig')
                    self.assertTrue(configured.startswith('Empresa,Telefone WhatsApp,Situação WhatsApp'))
                    self.assertIn('5551999999999', configured)
                    self.assertIn('Confirmado', configured)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            app.init_db()
            with closing(sqlite3.connect(app.DB)) as fresh:
                seller = fresh.execute("SELECT name,role,email FROM sales_profiles WHERE id=?", (profile['id'],)).fetchone()
                self.assertEqual(seller, ('Ana Vendas', 'Executiva comercial', 'ana@example.com'))
                lead = fresh.execute("""SELECT favorito,lead_status,observacoes,estrategia,contact_outcome,next_action,next_action_at
                    FROM sales_profile_leads WHERE profile_id=? AND cnpj=?""", (profile['id'], '98765432000110')).fetchone()
                self.assertEqual(lead, (1, 'qualificado', 'Retornar na sexta-feira', 'Apresentar plano anual por telefone', 'retornar', 'Enviar proposta comercial', '2026-09-30T10:30'))
                history_count = fresh.execute("SELECT COUNT(*) FROM sales_lead_history WHERE profile_id=? AND cnpj=?", (profile['id'], '98765432000110')).fetchone()[0]
                self.assertGreaterEqual(history_count, 4)
