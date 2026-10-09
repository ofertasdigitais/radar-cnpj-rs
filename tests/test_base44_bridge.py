import hashlib
import hmac
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from integrations.base44_bridge import build_event, encode_event, load_lead, signed_headers


class Base44BridgeTests(unittest.TestCase):
    def test_account_and_profile_scope_and_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "radar.db"
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript("""
                    CREATE TABLE user_accounts(id TEXT,username TEXT,is_active INTEGER);
                    CREATE TABLE sales_profiles(id TEXT,owner_id TEXT,name TEXT);
                    CREATE TABLE contact_suppression(owner_id TEXT,cnpj TEXT,reason TEXT,updated_at TEXT);
                    CREATE TABLE companies(cnpj TEXT,razao_social TEXT,nome_fantasia TEXT,telefone TEXT,email TEXT,
                        municipio TEXT,uf TEXT,segmento TEXT,cnae TEXT,cnae_descricao TEXT,situacao TEXT,data_abertura TEXT);
                    CREATE TABLE sales_profile_leads(profile_id TEXT,cnpj TEXT,lead_status TEXT,contact_outcome TEXT,
                        next_action TEXT,next_action_at TEXT,last_contact_at TEXT,first_contact_at TEXT,closed_at TEXT,
                        offered_value_cents INTEGER,negotiated_value_cents INTEGER,closed_value_cents INTEGER,
                        whatsapp_phone TEXT,whatsapp_status TEXT,whatsapp_checked_at TEXT,observacoes TEXT,
                        estrategia TEXT,favorito INTEGER,updated_at TEXT);
                    INSERT INTO user_accounts VALUES('conta-a','marcos',1),('conta-b','outro',1);
                    INSERT INTO sales_profiles VALUES('perfil-a','conta-a','Marcos'),('perfil-b','conta-b','Outro');
                    INSERT INTO companies VALUES('11222333000181','Empresa teste','','51999999999','a@example.com',
                        'Porto Alegre','RS','Comércio','4711302','','ATIVA','2026-09-01');
                    INSERT INTO sales_profile_leads VALUES('perfil-a','11222333000181','qualificado','oportunidade',
                        'Ligar','2026-10-04',NULL,NULL,NULL,150000,120000,0,'5551999999999','confirmed',NULL,
                        'Nota A','Estratégia A',1,'2026-10-02T10:00:00');
                """)
                db.commit()
            row = load_lead(db_path, "conta-a", "perfil-a", "11222333000181")
            event = build_event(row)
            self.assertEqual(event["external_id"], "radar:conta-a:perfil-a:11222333000181")
            self.assertEqual(event["commercial"]["negotiated_value_cents"], 120000)
            self.assertEqual(event["contact"]["whatsapp_status"], "confirmed")
            for account, profile in (("conta-b", "perfil-a"), ("conta-a", "perfil-b")):
                with self.assertRaises(LookupError):
                    load_lead(db_path, account, profile, "11222333000181")
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("INSERT INTO contact_suppression VALUES('conta-b','11222333000181','Outro dono','2026-10-09')")
                db.commit()
            self.assertEqual(load_lead(db_path, "conta-a", "perfil-a", "11222333000181")["cnpj"], "11222333000181")
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("INSERT INTO contact_suppression VALUES('conta-a','11222333000181','Não contatar','2026-10-09')")
                db.commit()
            with self.assertRaises(LookupError):
                load_lead(db_path, "conta-a", "perfil-a", "11222333000181")

    def test_signature_covers_timestamp_and_exact_body(self):
        body = encode_event({"company": {"name": "São José"}})
        headers = signed_headers(body, "x" * 32, 123)
        expected = hmac.new(b"x" * 32, b"123." + body, hashlib.sha256).hexdigest()
        self.assertEqual(headers["X-Radar-Signature"], "sha256=" + expected)
        self.assertNotEqual(headers["X-Radar-Signature"], signed_headers(body, "x" * 32, 124)["X-Radar-Signature"])


if __name__ == "__main__":
    unittest.main()
