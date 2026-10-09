import json
from datetime import datetime
import unittest
import app
import commercial
from tests import test_audit_auth as auth
from tools.create_presentation_account import provision,other_data_digest


class PresentationAccountTests(unittest.TestCase):
    setUp=auth.AuthBoundaryTests.setUp
    tearDown=auth.AuthBoundaryTests.tearDown
    request=auth.AuthBoundaryTests.request
    seed=auth.AuthBoundaryTests.seed

    def test_private_demo_coherent_metrics_and_original_accounts_preserved(self):
        self.seed('marcosqa')
        with app.connect() as db:
            db.execute("INSERT INTO sales_profiles(id,name,owner_id,created_at,updated_at) VALUES('private-marcos','Marcos QA','id-marcosqa','2026-10-01','2026-10-01')")
        report=provision(app.DB,'DemoTest2026@',app.DB.parent/'backups',datetime(2026,10,9,10,0))
        self.assertTrue(report['other_accounts_unchanged']);self.assertEqual(report['leads'],24)
        with app.connect() as db:
            data=commercial.analytics(db,report['profile_id'])
            self.assertEqual(data['summary']['total'],24);self.assertEqual(data['summary']['active'],18)
            self.assertEqual(data['summary']['closed_cents'],1900000);self.assertEqual(data['summary']['pipeline_cents'],1960000)
            self.assertEqual(data['summary']['conversion_pct'],16.7)
            self.assertTrue(all('FICTÍCIO' in row['razao_social'] for row in data['items']))
            self.assertTrue(all(not row['telefone'] for row in data['items']))
            self.assertTrue(all(row['closed_value_cents']<=row['negotiated_value_cents']<=row['offered_value_cents'] for row in data['items']))
        status,_,cookie=self.request('POST','/login',{'username':'Radar','password':'DemoTest2026@'})
        self.assertEqual(status,303);cookie=cookie.split(';')[0]
        profiles=json.loads(self.request('GET','/api/team-profiles',cookie=cookie)[1])['items']
        self.assertEqual([row['id'] for row in profiles],[report['profile_id']])
        self.assertEqual(self.request('GET','/api/team-leads?profile_id=private-marcos',cookie=cookie)[0],404)
        self.assertEqual(self.request('GET','/api/admin/config',cookie=cookie)[0],403)

    def test_reexecution_does_not_overwrite_account_password_or_records(self):
        report=provision(app.DB,'DemoTest2026@',app.DB.parent/'backups')
        with app.connect() as db:before=other_data_digest(db,'unrelated')
        with self.assertRaises(ValueError):provision(app.DB,'Different2026@',app.DB.parent/'backups')
        with app.connect() as db:self.assertEqual(before,other_data_digest(db,'unrelated'))


if __name__=='__main__':unittest.main()
