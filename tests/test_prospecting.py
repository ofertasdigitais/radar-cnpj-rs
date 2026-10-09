import json
import unittest
from tests.test_commercial import CommercialTests


class ProspectTests(unittest.TestCase):
    setUp = CommercialTests.setUp
    tearDown = CommercialTests.tearDown
    request = CommercialTests.request
    def test_private_import_idempotency_and_edit(self):
        payload={'rows':[{'name':'Contato de indicação','phone':'51987654321','source':'Indicação'}]}
        status,raw=self.request('POST','/api/prospects/import',payload)
        self.assertEqual(status,201);self.assertEqual(json.loads(raw)['created'],1)
        self.assertEqual(json.loads(self.request('POST','/api/prospects/import',payload)[1])['duplicates'],1)
        item=json.loads(self.request('GET','/api/prospects')[1])['items'][0]
        self.assertEqual(self.request('PUT','/api/prospects/'+item['id'],{'status':'qualificado','notes':'Próxima conversa na feira'})[0],200)
        with __import__('app').connect() as db:
            db.execute("UPDATE prospect_inbox SET owner_id='foreign-account' WHERE id=?",(item['id'],))
        self.assertEqual(json.loads(self.request('GET','/api/prospects')[1])['total'],0)
        self.assertEqual(self.request('PUT','/api/prospects/'+item['id'],{'notes':'Não pode editar'})[0],404)

    def test_import_validation_atomic_and_never_touches_receita(self):
        self.assertEqual(self.request('POST','/api/prospects/import',{'rows':[{'name':'Bom'},{'name':'Ruim','website':'javascript:alert(1)'}]})[0],400)
        self.assertEqual(json.loads(self.request('GET','/api/prospects')[1])['total'],0)
        self.assertEqual(self.request('POST','/api/prospects/import',{'rows':[]})[0],400)
        self.assertEqual(self.request('POST','/api/prospects/import',{'rows':[{'name':'X'}]*501})[0],400)
        self.assertEqual(self.request('POST','/api/prospects/import',{'rows':[{'name':'Origem não RF','company':'Privada','cnpj':'11222333000181'}]})[0],201)
        with __import__('app').connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT razao_social FROM companies WHERE cnpj='11222333000181'").fetchone()[0],'Empresa QA <teste>')

del CommercialTests
