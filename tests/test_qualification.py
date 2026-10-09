import json
import unittest
import app
import prospecting
from tests.test_commercial import CommercialTests


class QualificationTests(unittest.TestCase):
    setUp=CommercialTests.setUp
    tearDown=CommercialTests.tearDown
    request=CommercialTests.request

    def contact(self):
        self.assertEqual(self.request('POST','/api/prospects/import',{'rows':[dict(name='Contato externo',phone='51987654321',source='Indicação',campaign='QA qualificação')]})[0],201)
        return json.loads(self.request('GET','/api/prospects')[1])['items'][0]

    def test_qualify_idempotency_history_and_cnpj_fingerprint(self):
        item=self.contact();payload=dict(prospect_id=item['id'],profile_id='qa-a',cnpj='11222333000181')
        self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],201)
        self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],200)
        result=json.loads(self.request('GET','/api/prospects')[1]);contact=result['items'][0]
        self.assertEqual(result['summary']['linked'],1);self.assertEqual(contact['status'],'qualificado')
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT fingerprint FROM prospect_inbox').fetchone()[0],prospecting.fingerprint(contact))
            lead=dict(db.execute('SELECT * FROM sales_profile_leads').fetchone());self.assertEqual(lead['lead_status'],'qualificado');self.assertEqual(lead['campaign'],'QA qualificação')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sales_lead_history').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT telefone FROM companies").fetchone()[0],'51987654321')
        self.assertEqual(len(json.loads(self.request('GET','/api/prospects/history?id='+item['id'])[1])['items']),1)
        self.assertEqual(self.request('PUT','/api/prospects/'+item['id'],dict(notes='obsoleta',revision=item['revision']))[0],409)
        self.assertEqual(self.request('PUT','/api/prospects/'+item['id'],dict(notes='atual',revision=contact['revision']))[0],200)

    def test_ownership_missing_company_duplicate_and_preservation(self):
        item=self.contact();payload=dict(prospect_id=item['id'],profile_id='qa-b',cnpj='11222333000181')
        self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],404)
        payload.update(profile_id='qa-a',cnpj='00000000000000');self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],404)
        with app.connect() as db:db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,lead_status,observacoes) VALUES('qa-b','11222333000181','2026-01-01','2026-01-01','negociacao','Não alterar')")
        payload.update(cnpj='11222333000181');self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],409)
        payload.update(allow_duplicate=True);self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],201)
        with app.connect() as db:
            db.execute("UPDATE sales_profile_leads SET lead_status='negociacao',negotiated_value_cents=10000,observacoes='Não apagar' WHERE profile_id='qa-a'")
        self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],200)
        with app.connect() as db:
            lead=dict(db.execute("SELECT * FROM sales_profile_leads WHERE profile_id='qa-a'").fetchone());self.assertEqual(lead['observacoes'],'Não apagar');self.assertEqual(lead['negotiated_value_cents'],10000)
            db.execute("UPDATE prospect_inbox SET owner_id='foreign-account'")
        self.assertEqual(self.request('POST','/api/prospects/qualify',payload)[0],404)
        self.assertEqual(self.request('GET','/api/prospects/history?id='+item['id'])[0],404)

    def test_metric_definitions_and_missing_values(self):
        self.request('POST','/api/team-leads',dict(profile_id='qa-a',cnpj='11222333000181'))
        with app.connect() as db:db.execute("UPDATE sales_profile_leads SET lead_status='convertido',closed_value_cents=0")
        data=json.loads(self.request('GET','/api/commercial?profile_id=qa-a')[1])
        self.assertEqual(data['quality']['won_without_positive_value'],1)
        self.assertIsNone(data['summary']['avg_close_days']);self.assertEqual(data['summary']['closing_sample'],0)
        self.assertIn('não distinguem',data['metric_context']['money'])


del CommercialTests
