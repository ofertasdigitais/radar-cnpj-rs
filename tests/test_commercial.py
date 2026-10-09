import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import app
import commercial
from reports import commercial_pdf


class CommercialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(app, 'DB', Path(self.directory.name) / 'radar.db')
        self.env_patch = patch.dict(os.environ, {'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': ''})
        self.db_patch.start(); self.env_patch.start(); app.init_db()
        with app.connect() as db:
            for profile,owner in [('qa-a','local-default'),('qa-b','foreign-account')]:
                db.execute("INSERT INTO sales_profiles(id,name,role,email,owner_id,created_at,updated_at) VALUES(?,?, '', '', ?,?,?)", (profile,profile,owner,'2026-01-01','2026-01-01'))
            db.execute("INSERT INTO companies(cnpj,razao_social,uf,situacao,telefone,segmento) VALUES('11222333000181','Empresa QA <teste>','RS','ATIVA','51987654321','Comércio')")
        self.server = app.ThreadingHTTPServer(('127.0.0.1',0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.env_patch.stop(); self.db_patch.stop(); self.directory.cleanup()

    def request(self, method, path, payload=None):
        connection = HTTPConnection('127.0.0.1',self.server.server_port)
        body = json.dumps(payload) if payload is not None else None
        connection.request(method,path,body,{'Content-Type':'application/json'})
        response = connection.getresponse(); status=response.status; data=response.read(); connection.close()
        return status,data

    def add(self):
        self.assertEqual(self.request('POST','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181'})[0],201)

    def test_metadata_diff_csv_archive_and_ownership(self):
        self.add()
        status,_=self.request('PUT','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181','campaign':'Outubro','persona':'Dono','lead_origin':'Receita','loss_reason':'preco','lead_status':'descartado','negotiated_value_cents':'1250,55'})
        self.assertEqual(status,200)
        status,raw=self.request('GET','/api/team-leads?profile_id=qa-a')
        item=json.loads(raw)['items'][0]
        self.assertEqual(item['profile_campaign'],'Outubro')
        self.assertEqual(item['profile_negotiated_value_cents'],125055)
        _,raw=self.request('GET','/api/commercial?profile_id=qa-a')
        commercial_data=json.loads(raw)
        self.assertEqual(commercial_data['summary']['active'],0)
        self.assertEqual(commercial_data['summary']['pipeline_cents'],0)
        self.assertEqual(commercial_data['queue'],[])
        self.assertEqual(commercial_data['loss_reasons'],[{'label':'Preço','total':1}])
        _,raw=self.request('GET','/api/team-lead-history?profile_id=qa-a&cnpj=11222333000181')
        diff=next(json.loads(x['changes_json']) for x in json.loads(raw)['items'] if x['event_type']=='fields_updated')
        self.assertEqual(diff['campaign'],{'before':'','after':'Outubro'})
        _,raw=self.request('GET','/api/team-leads.csv?profile_id=qa-a&fields=campanha,persona,origem,motivo_perda')
        self.assertIn('Outubro;Dono;Receita;Preço',raw.decode('utf-8-sig'))
        self.assertEqual(self.request('DELETE','/api/team-leads?profile_id=qa-a&cnpj=11222333000181')[0],200)
        _,raw=self.request('GET','/api/commercial-archive?profile_id=qa-a')
        self.assertIn('Outubro',json.loads(raw)['items'][0]['events_json'])
        for route in ('/api/commercial','/api/commercial-report.pdf','/api/commercial-archive'):
            self.assertEqual(self.request('GET',route+'?profile_id=qa-b')[0],404)
        self.assertEqual(self.request('POST','/api/commercial-settings',{'profile_id':'qa-b','contact_sla_hours':24,'stalled_days':3})[0],404)

    def test_settings_validation_and_pdf(self):
        self.add()
        for hours,days in ((0,2),(24,0),(721,2),(2,366),('bad',2)):
            self.assertEqual(self.request('POST','/api/commercial-settings',{'profile_id':'qa-a','contact_sla_hours':hours,'stalled_days':days})[0],400)
        self.assertEqual(self.request('POST','/api/commercial-settings',{'profile_id':'qa-a','contact_sla_hours':24,'stalled_days':3})[0],200)
        _,raw=self.request('GET','/api/commercial?profile_id=qa-a')
        data=json.loads(raw)
        self.assertEqual(data['settings'],{'contact_sla_hours':24,'stalled_days':3})
        self.assertNotIn('items',data)
        self.assertEqual(data['summary']['total'],1)
        status,pdf=self.request('GET','/api/commercial-report.pdf?profile_id=qa-a')
        self.assertEqual(status,200); self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertEqual(self.request('GET','/api/commercial?profile_id=qa-a&activity_from=2026-02-30')[0],400)

    def test_duplicate_warning_is_private_and_can_be_confirmed(self):
        with app.connect() as db:
            db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES('qa-b','11222333000181','2026-01-01','2026-01-01')")
        status,raw=self.request('POST','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181'})
        self.assertEqual(status,409); self.assertNotIn('qa-b',raw.decode())
        self.assertEqual(self.request('POST','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181','allow_duplicate':True})[0],201)
        self.assertEqual(self.request('POST','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181'})[0],200)

    def test_bad_values_and_pagination_are_client_errors(self):
        self.add()
        for amount in ('NaN','Infinity','-2',1e100,'texto',True):
            self.assertEqual(self.request('PUT','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181','closed_value_cents':amount})[0],400)
        self.assertEqual(self.request('PUT','/api/team-leads',{'profile_id':'qa-a','cnpj':'11222333000181','loss_reason':'inexistente'})[0],400)
        self.assertEqual(self.request('GET','/api/companies?page=oops')[0],400)

    def test_metrics_do_not_count_lost_or_active_values_as_revenue(self):
        def item(stage,amount):
            return {'lead_status':stage,'added_at':'2026-01-01','first_contact_at':'2026-01-02','closed_at':'2026-01-04','offered_value_cents':10000,'negotiated_value_cents':9000,'closed_value_cents':amount}
        data=commercial.metrics([item('negociacao',123),item('convertido',8000),item('descartado',999999)],datetime(2026,10,1))
        self.assertEqual(data['closed_cents'],8000); self.assertEqual(data['pipeline_cents'],9000)
        self.assertEqual(data['avg_close_days'],3); self.assertEqual(data['conversion_pct'],33.3)
        self.assertFalse(commercial.phone_quality('11111111111')['format_valid'])
        self.assertTrue(commercial.phone_quality('55 (51) 98765-4321')['format_valid'])
        self.assertIsNone(commercial.timestamp('invalid'))
        self.assertIsNone(commercial.timestamp(''))
        self.assertIsNone(commercial.timestamp(None))
        self.assertIsNone(commercial.timestamp('2026-02-30'))
        self.assertIsNone(commercial.timestamp('2026-10-05T10:00+99:00'))
        self.assertIsNone(commercial.timestamp('now'))
        self.assertIsNone(commercial.timestamp('0'))
        self.assertIsNone(commercial.timestamp(0))
        self.assertIsNone(commercial.timestamp({}))
        self.assertIsNone(commercial.timestamp([]))
        self.assertIsNone(commercial.timestamp(True))
        self.assertIsNone(commercial.timestamp(False))
        self.assertIsNone(commercial.timestamp(2026))
        self.assertIsNone(commercial.timestamp('2026-13-01'))
        self.assertIsNone(commercial.timestamp('2026-00-01'))
        self.assertIsNone(commercial.timestamp('2026-01-00'))
        self.assertIsNone(commercial.timestamp('2026-01-32'))
        self.assertIsNone(commercial.timestamp('2026-01-01T25:00'))
        self.assertIsNone(commercial.timestamp('2026-01-01T10:61'))
        self.assertIsNone(commercial.timestamp('2026-01-01T10:00:61'))
        self.assertIsNone(commercial.timestamp('2026-01-01T10:00Zbad'))
        self.assertIsNone(commercial.timestamp('2026-01-01T'))
        self.assertIsNone(commercial.timestamp('2026'))
        self.assertIsNone(commercial.timestamp('not a date'))
        self.assertIsNone(commercial.timestamp('2026-10-05T10:00:00+bad'))
        self.assertIsNone(commercial.timestamp('2026-10-05T10:00:00-99:00'))
        self.assertIsNotNone(commercial.timestamp('2026-10-05T10:00-03:00'))


if __name__=='__main__': unittest.main()
