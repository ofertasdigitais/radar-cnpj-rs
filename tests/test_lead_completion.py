import json
import unittest
import app
import test_sales_ops


class CompletionTests(unittest.TestCase):
    setUp=test_sales_ops.SalesOpsTests.setUp
    tearDown=test_sales_ops.SalesOpsTests.tearDown
    request=test_sales_ops.SalesOpsTests.request
    add=test_sales_ops.SalesOpsTests.add
    data=test_sales_ops.SalesOpsTests.data

    def complete(self, **changes):
        payload=dict(profile_id='qa-a',cnpj='11222333000181',revision=self.data()['agenda'][0]['revision'],mode='lead',notes='Ação realizada e atendimento finalizado')
        return self.request('POST','/api/sales-ops/complete',{**payload,**changes})

    def test_close_removes_overdue_and_active_without_fake_sale_or_contact(self):
        self.add()
        with app.connect() as db:db.execute("UPDATE sales_profile_leads SET next_action='Retornar',next_action_at='2020-01-01'")
        old=self.data()['agenda'][0]['revision']
        self.assertEqual(self.complete()[0],200)
        self.assertEqual(self.data()['agenda'],[])
        _,raw=self.request('GET','/api/team-leads?profile_id=qa-a&focus=overdue')
        self.assertEqual(json.loads(raw)['total'],0)
        _,raw=self.request('GET','/api/team-leads?profile_id=qa-a&status=concluido')
        self.assertEqual(json.loads(raw)['total'],1)
        self.assertEqual(self.data()['current']['contacts'],0)
        self.assertEqual(self.data()['current']['wins'],0)
        with app.connect() as db:
            lead=db.execute('SELECT * FROM sales_profile_leads').fetchone()
            self.assertEqual(lead['lead_status'],'concluido');self.assertIsNone(lead['next_action_at'])
            self.assertIn('Retornar',db.execute("SELECT details FROM sales_lead_history WHERE event_type='lead_completed'").fetchone()[0])
        self.assertEqual(self.request('POST','/api/sales-ops/complete',dict(profile_id='qa-a',cnpj='11222333000181',revision=old,notes='Duplicado'))[0],409)

    def test_only_action_can_schedule_new_return_and_reopen_closed_lead(self):
        self.add()
        self.assertEqual(self.complete(mode='action',next_action='Nova proposta',next_action_at='2099-12-01T12:00')[0],200)
        self.assertEqual(self.data()['agenda'][0]['next_action'],'Nova proposta')
        self.assertEqual(self.complete()[0],200)
        _,raw=self.request('GET','/api/team-memberships?cnpj=11222333000181')
        row=next(x for x in json.loads(raw)['items'] if x['id']=='qa-a')
        self.assertEqual(self.request('PUT','/api/team-leads',dict(profile_id='qa-a',cnpj='11222333000181',expected_updated_at=row['updated_at'],lead_status='novo'))[0],200)
        self.assertEqual(len(self.data()['agenda']),1)

    def test_completion_validation_and_account_scope(self):
        self.add()
        for changes in ({'notes':''},{'notes':'x'*1001},{'mode':'bad'},{'mode':'action','next_action':'Sem data'},{'mode':'action','next_action':'Retorno','next_action_at':'2020-01-01'},{'mode':'lead','next_action':'Não permitido'}):
            self.assertEqual(self.complete(**changes)[0],400)
        self.assertEqual(self.complete(profile_id='qa-b')[0],404)
        self.assertEqual(len(self.data()['agenda']),1)


if __name__=='__main__':unittest.main()
