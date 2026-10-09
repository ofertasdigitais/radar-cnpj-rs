import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import app
import admin_panel
import backup_protection
import recovery
import sales_ops
import test_commercial
import test_admin_panel


class SalesOpsTests(unittest.TestCase):
    setUp=test_commercial.CommercialTests.setUp
    tearDown=test_commercial.CommercialTests.tearDown
    request=test_commercial.CommercialTests.request
    add=test_commercial.CommercialTests.add

    def data(self):
        status,raw=self.request('GET','/api/sales-ops?profile_id=qa-a')
        self.assertEqual(status,200)
        return json.loads(raw)

    def contact(self,**changes):
        payload={'profile_id':'qa-a','cnpj':'11222333000181','revision':self.data()['agenda'][0]['revision'],
                 'outcome':'respondeu','next_action':'Enviar proposta','next_action_at':'2026-12-01T12:00','notes':'Nota QA'}
        return self.request('POST','/api/sales-ops/contact',{**payload,**changes})

    def test_contact_dates_history_and_stale_edit(self):
        self.add();old=self.data()['agenda'][0]['revision']
        self.assertEqual(self.contact()[0],200)
        self.assertEqual(self.contact(revision=old)[0],409)
        with app.connect() as db:
            row=db.execute('SELECT * FROM sales_profile_leads').fetchone()
            self.assertEqual(row['lead_status'],'contatado');self.assertTrue(row['first_contact_at'])
            events=db.execute("SELECT details FROM sales_lead_history WHERE event_type='contact_recorded'").fetchall()
            self.assertEqual(len(events),1);self.assertEqual(json.loads(events[0][0])['note'],'Nota QA')

    def test_whatsapp_open_does_not_record_actual_contact(self):
        self.add()
        self.assertEqual(self.request('POST','/api/team-lead-events',{'profile_id':'qa-a','cnpj':'11222333000181','event_type':'whatsapp_opened'})[0],201)
        with app.connect() as db:self.assertIsNone(db.execute('SELECT first_contact_at FROM sales_profile_leads').fetchone()[0])
        self.assertEqual(self.data()['current']['contacts'],0)

    def test_repeated_actual_contacts_count_once_per_save(self):
        self.add();self.assertEqual(self.contact()[0],200);self.assertEqual(self.contact()[0],200)
        self.assertEqual(self.data()['current']['contacts'],2)
        self.assertEqual(self.data()['current']['contacted_leads'],1)

    def test_suppression_scope_csv_and_reauthorization(self):
        self.add()
        self.request('POST','/api/prospects/import',{'rows':[{'name':'Contato QA','company':'Empresa QA','cnpj':'11222333000181','source':'Teste','phone':'51987654321'}]})
        payload={'profile_id':'qa-a','cnpj':'11222333000181','blocked':True,'reason':'Pediu para não receber contato'}
        self.assertEqual(self.request('POST','/api/sales-ops/suppression',payload)[0],200)
        self.assertEqual(self.data()['agenda'],[])
        self.assertEqual(self.request('POST','/api/team-lead-events',{'profile_id':'qa-a','cnpj':payload['cnpj'],'event_type':'whatsapp_opened'})[0],403)
        _,raw=self.request('GET','/api/team-leads.csv?profile_id=qa-a');self.assertNotIn('Empresa QA',raw.decode())
        _,raw=self.request('GET','/api/team-leads?profile_id=qa-a');self.assertTrue(json.loads(raw)['items'][0]['profile_do_not_contact'])
        _,raw=self.request('GET','/api/prospects');self.assertTrue(json.loads(raw)['items'][0]['do_not_contact'])
        with app.connect() as db:
            self.assertIsNone(sales_ops.blocked(db,'foreign-account',payload['cnpj']))
            self.assertIsNotNone(sales_ops.blocked(db,'local-default',payload['cnpj']))
        restore={**payload,'blocked':False}
        self.assertEqual(self.request('POST','/api/sales-ops/suppression',restore)[0],400)
        self.assertEqual(self.request('POST','/api/sales-ops/suppression',{**restore,'confirm_restore':True})[0],200)
        self.assertEqual(len(self.data()['agenda']),1)

    def test_cross_account_access_and_invalid_input(self):
        self.add()
        self.assertEqual(self.request('GET','/api/sales-ops?profile_id=qa-b')[0],404)
        for route in ('contact','targets','suppression'):
            self.assertEqual(self.request('POST','/api/sales-ops/'+route,{'profile_id':'qa-b'})[0],404)
        for changes in ({'outcome':'invalid'},{'next_action_at':''},{'next_action':''},{'next_action_at':'nope'},{'notes':'x'*1001}):
            self.assertEqual(self.contact(**changes)[0],400)
        for query in ('from=2026-02-30','from=2026-10-07&to=2026-10-01','from=2020-01-01&to=2026-10-07'):
            self.assertEqual(self.request('GET','/api/sales-ops?profile_id=qa-a&'+query)[0],400)

    def test_monthly_targets_validation_and_persistence(self):
        body={'profile_id':'qa-a','month':'2026-10','revenue_cents':125055,'contacts':10,'wins':2}
        self.assertEqual(self.request('POST','/api/sales-ops/targets',body)[0],200)
        self.assertEqual(self.data()['targets']['revenue_cents'],125055)
        for value in (-1,True,'12',1.5):
            self.assertEqual(self.request('POST','/api/sales-ops/targets',{**body,'contacts':value})[0],400)

    def test_concurrent_quick_saves_do_not_overwrite(self):
        self.add();revision=self.data()['agenda'][0]['revision']
        body={'profile_id':'qa-a','cnpj':'11222333000181','revision':revision,'outcome':'respondeu'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda _:self.request('POST','/api/sales-ops/contact',body)[0],range(2)))
        self.assertEqual(sorted(statuses),[200,409])

    def test_closing_period_not_entry_cohort_and_previous_period(self):
        self.add()
        with app.connect() as db:
            db.execute("UPDATE sales_profile_leads SET added_at='2026-08-01',lead_status='convertido',closed_at='2026-10-07',closed_value_cents=250050")
            result=sales_ops.dashboard(db,'qa-a','local-default','2026-10-01','2026-10-07','2026-10',datetime(2026,10,7))
        self.assertEqual(result['current']['entries'],0);self.assertEqual(result['current']['wins'],1)
        self.assertEqual(result['current']['closed_cents'],250050)
        self.assertEqual(result['previous_period'],{'from':'2026-09-24','to':'2026-09-30'})
        self.assertEqual(sum(x['closed_cents'] for x in result['trend']),250050)

    def test_full_editor_rejects_stale_session_without_losing_current_data(self):
        self.add()
        _,raw=self.request('GET','/api/team-memberships?cnpj=11222333000181')
        version=next(x for x in json.loads(raw)['items'] if x['id']=='qa-a')['updated_at']
        payload={'profile_id':'qa-a','cnpj':'11222333000181','expected_updated_at':version,'observacoes':'Primeira sessão'}
        self.assertEqual(self.request('PUT','/api/team-leads',payload)[0],200)
        self.assertEqual(self.request('PUT','/api/team-leads',{**payload,'observacoes':'Sessão desatualizada'})[0],409)
        with app.connect() as db:self.assertEqual(db.execute('SELECT observacoes FROM sales_profile_leads').fetchone()[0],'Primeira sessão')

    def test_large_agenda_query_is_complete(self):
        with app.connect() as db:
            rows=[(str(99000000000000+i),'QA '+str(i)) for i in range(10000)]
            db.executemany("INSERT INTO companies(cnpj,razao_social) VALUES(?,?)",rows)
            db.executemany("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES('qa-a',?,'2026-10-01','2026-10-01')",[(x[0],) for x in rows])
        started=time.perf_counter()
        with app.connect() as db:result=sales_ops.dashboard(db,'qa-a','local-default','2026-10-01','2026-10-07')
        self.assertEqual(len(result['agenda']),10000)
        elapsed=time.perf_counter()-started
        print(f'\nQA 10.000 leads: agenda + métricas em {elapsed:.3f}s (base temporária).')
        self.assertLess(elapsed,12)


class ManagedAccountTests(unittest.TestCase):
    setUp=test_admin_panel.AdminPanelTests.setUp
    tearDown=test_admin_panel.AdminPanelTests.tearDown
    request=test_admin_panel.AdminPanelTests.request
    login=test_admin_panel.AdminPanelTests.login
    create_seller=test_admin_panel.AdminPanelTests.create_seller

    def test_admin_block_applies_to_managed_seller_not_admin_account(self):
        owner=self.create_seller();seller=self.login('sellerqa','Seller2026@')
        with app.connect() as db:
            profile=db.execute('SELECT id FROM sales_profiles WHERE owner_id=?',(owner,)).fetchone()[0]
            db.execute("INSERT INTO companies(cnpj,razao_social) VALUES('11222333000181','Managed QA')")
            db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES(?,'11222333000181','2026-01-01','2026-01-01')",(profile,))
        self.assertEqual(self.request('POST','/api/sales-ops/suppression',{'profile_id':profile,'cnpj':'11222333000181','blocked':True,'reason':'Pedido ao gestor'},self.cookie)[0],200)
        with app.connect() as db:self.assertIsNotNone(sales_ops.blocked(db,owner,'11222333000181'))
        for cookie in (seller,self.cookie):
            _,raw=self.request('GET','/api/sales-ops?profile_id='+profile,cookie=cookie)
            self.assertEqual(json.loads(raw)['counts']['blocked'],1)
            _,raw=self.request('GET','/api/team-leads?profile_id='+profile,cookie=cookie)
            self.assertTrue(json.loads(raw)['items'][0]['profile_do_not_contact'])
            _,raw=self.request('GET','/api/team-leads.csv?profile_id='+profile,cookie=cookie)
            self.assertNotIn('Managed QA',raw.decode())
            self.assertEqual(self.request('POST','/api/team-lead-events',{'profile_id':profile,'cnpj':'11222333000181','event_type':'whatsapp_opened'},cookie)[0],403)


class BackupProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db_path=Path(self.tmp.name)/'radar.db'
        self.dbpatch=patch.object(app,'DB',self.db_path);self.dbpatch.start()
        self.env=patch.dict('os.environ',{'RADAR_ADMIN_USER':'','RADAR_ADMIN_PASSWORD':''});self.env.start();app.init_db()

    def tearDown(self):
        self.env.stop();self.dbpatch.stop();self.tmp.cleanup()

    def destination(self,value):
        with app.connect() as db:admin_panel.save(db,'qa',{'revision':admin_panel.revision(db),'values':{'backup_directory':str(value)}},self.db_path)

    def test_verified_secondary_and_restore_rehearsal(self):
        folder=Path(self.tmp.name)/'second';self.destination(folder)
        result=backup_protection.create(self.db_path,app.connect)
        self.assertTrue(result['secondary_verified']);self.assertEqual(result['state'],'verified')
        primary=self.db_path.parent/'admin-backups'/result['name']
        self.assertEqual(backup_protection.digest(primary),backup_protection.digest(folder/result['name']))
        self.assertTrue(recovery.rehearse(primary)['ok'])

    def test_forbidden_project_destination_keeps_primary(self):
        self.destination(Path(app.__file__).parent/'static')
        result=backup_protection.create(self.db_path,app.connect)
        self.assertEqual(result['state'],'secondary_failed')
        self.assertTrue((self.db_path.parent/'admin-backups'/result['name']).is_file())

    def test_copy_failure_preserves_verified_primary(self):
        self.destination(Path(self.tmp.name)/'second')
        with patch.object(backup_protection.shutil,'copyfileobj',side_effect=OSError('Disk full')):
            result=backup_protection.create(self.db_path,app.connect)
        self.assertEqual(result['state'],'secondary_failed')
        self.assertTrue(recovery.rehearse(self.db_path.parent/'admin-backups'/result['name'])['ok'])
        self.assertFalse(list((Path(self.tmp.name)/'second').glob('*.part')))

    def test_daily_scheduler_runs_only_when_due_and_enabled(self):
        today=datetime.now().date().isoformat()
        for enabled,last,expected in ((True,today,0),(True,'2000-01-01',1),(False,'2000-01-01',0)):
            with patch.object(backup_protection.threading,'Thread') as thread,patch.object(backup_protection.admin_panel,'get',return_value=enabled),patch.object(backup_protection,'status',return_value={'created_at':last}),patch.object(backup_protection,'create') as create,patch.object(backup_protection.time,'sleep',side_effect=StopIteration):
                backup_protection.start_scheduler(self.db_path,app.connect)
                with self.assertRaises(StopIteration):thread.call_args.kwargs['target']()
                self.assertEqual(create.call_count,expected)


if __name__=='__main__':unittest.main()
