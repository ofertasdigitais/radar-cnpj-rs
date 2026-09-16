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
                self.assertEqual(fresh.execute("SELECT lead_status,favorito,observacoes FROM companies").fetchone(), ('contatado', 1, 'Retornar amanhã às 14h'))
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
                    'observacoes': 'Retornar na sexta-feira',
                    'estrategia': 'Apresentar plano anual por telefone'
                }).encode(), method='PUT', headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    saved = json.load(response)
                    self.assertEqual(saved['profile_favorito'], 1)
                    self.assertEqual(saved['profile_lead_status'], 'qualificado')

                with urlopen(base + '/api/team-leads?profile_id=' + profile['id'] + '&view=favorites') as response:
                    portfolio = json.load(response)
                    self.assertEqual(portfolio['total'], 1)
                    self.assertEqual(portfolio['items'][0]['profile_estrategia'], 'Apresentar plano anual por telefone')

                with urlopen(base + '/api/team-leads.csv?profile_id=' + profile['id'] + '&view=favorites') as response:
                    exported = response.read()
                    self.assertTrue(exported.startswith(b'\xef\xbb\xbf'))
                    self.assertIn('Lead persistente', exported.decode('utf-8-sig'))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            app.init_db()
            with closing(sqlite3.connect(app.DB)) as fresh:
                seller = fresh.execute("SELECT name,role,email FROM sales_profiles WHERE id=?", (profile['id'],)).fetchone()
                self.assertEqual(seller, ('Ana Vendas', 'Executiva comercial', 'ana@example.com'))
                lead = fresh.execute("""SELECT favorito,lead_status,observacoes,estrategia
                    FROM sales_profile_leads WHERE profile_id=? AND cnpj=?""", (profile['id'], '98765432000110')).fetchone()
                self.assertEqual(lead, (1, 'qualificado', 'Retornar na sexta-feira', 'Apresentar plano anual por telefone'))
