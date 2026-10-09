import sqlite3
import unittest
from datetime import date
from importer import import_csv_bytes, segment_for
from app import filters, score_company

class ImportTests(unittest.TestCase):
    def test_segments(self):
        self.assertEqual(segment_for("6201501"), "Tecnologia e comunicação")
        self.assertEqual(segment_for("4711302"), "Comércio")

    def test_import_filters_rs(self):
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE companies(cnpj TEXT UNIQUE,razao_social TEXT,nome_fantasia TEXT,situacao TEXT,data_abertura TEXT,cnae TEXT,cnaes_secundarios TEXT,segmento TEXT,municipio TEXT,regiao TEXT,uf TEXT,cep TEXT,bairro TEXT,logradouro TEXT,numero TEXT,telefone TEXT,email TEXT,porte TEXT,mei INTEGER)")
        data="cnpj;razao_social;uf;data_abertura;cnae;municipio;mei\n12345678000190;Teste RS;RS;20260801;6201501;Porto Alegre;S\n12345678000191;Teste SC;SC;20260801;4711302;Florianopolis;N\n".encode()
        result=import_csv_bytes(db,data)
        self.assertEqual(result,{"lidos":2,"importados":1,"ignorados":1})
        row=db.execute("SELECT segmento,mei,data_abertura FROM companies").fetchone()
        self.assertEqual(row,("Tecnologia e comunicação",1,"2026-08-01"))

    def test_text_search_does_not_create_empty_cnpj_filter(self):
        where, values = filters({"q": ["Pampa"]})
        self.assertNotIn("cnpj LIKE", where)
        self.assertEqual(values, ["%Pampa%", "%Pampa%"])

    def test_new_stage_includes_legacy_empty_values(self):
        where, values = filters({"lead_status": ["novo"]})
        self.assertIn("COALESCE(NULLIF(lead_status,''),'novo') = ?", where)
        self.assertEqual(values, ["novo"])

    def test_mei_analytics_can_ignore_profile_and_workflow(self):
        where, values = filters(
            {"inicio": ["2026-08-01"], "mei": ["nao"], "lead_status": ["convertido"]},
            {"mei", "lead_status"},
        )
        self.assertIn("data_abertura >= ?", where)
        self.assertNotIn("mei = ?", where)
        self.assertNotIn("lead_status", where)
        self.assertEqual(values, ["2026-08-01"])

    def test_contact_profile_filters_actionable_companies(self):
        where, values = filters({"contato": ["sim"]})
        self.assertIn("COALESCE(email", where)
        self.assertIn("COALESCE(telefone", where)
        self.assertEqual(values, [1])

    def test_lead_score_rewards_recent_contactable_company(self):
        company={"email":"vendas@empresa.com","telefone":"5133334444","situacao":"ATIVA","nome_fantasia":"Empresa","mei":0,"data_abertura":date.today().isoformat()}
        self.assertEqual(score_company(company),100)

if __name__ == "__main__": unittest.main()
