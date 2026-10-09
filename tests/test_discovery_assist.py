import json
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch
import app
import discovery
import admin_panel
from tests.test_discovery import DiscoveryTests,CAMPAIGN,ELEMENTS
from tests.test_admin_panel import AdminPanelTests

class FixedDateTime(datetime):
    value=datetime(2026,10,7,7,0)
    @classmethod
    def now(cls,*args,**kwargs): return cls.value

class AssistedDiscoveryTests(unittest.TestCase):
    setUp=DiscoveryTests.setUp
    tearDown=DiscoveryTests.tearDown
    request=DiscoveryTests.request

    def campaign(self,owner='local-default',**values):
        with app.connect() as db: return discovery.save_campaign(db,owner,{**CAMPAIGN,**values})

    def collect(self,manager,owner,identifier,scheduled_for=None):
        manager.last_start=0
        run_id=manager.start(owner,identifier,scheduled_for)
        deadline=time.monotonic()+4
        while manager.lock.locked() and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(manager.lock.locked())
        return run_id

    def test_slots_validation_future_and_no_missed_burst(self):
        for slots in ([],['25:00'],['08:00','08:00'],['08:00','08:30'],['01:00','03:00','05:00','07:00'],['8:00'],[None],'08:00'):
            with self.assertRaises(ValueError): discovery.validate({**CAMPAIGN,'frequency':'scheduled','times':slots})
        self.assertEqual(discovery.next_scheduled(['08:00','13:00','17:00'],datetime(2026,10,7,13,0)),'2026-10-07T17:00:00')
        self.assertEqual(discovery.next_scheduled(['08:00','13:00','17:00'],datetime(2026,10,7,20,0)),'2026-10-08T08:00:00')
        with patch.object(discovery,'datetime',FixedDateTime):
            FixedDateTime.value=datetime(2026,10,7,7,0)
            identifier=self.campaign(frequency='scheduled',icp_label='Restaurantes locais')
            with app.connect() as db: self.assertEqual(db.execute('SELECT next_run_at FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone()[0],'2026-10-07T08:00:00')
            manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
            # Missed morning and afternoon: at most one round now, then next future day.
            FixedDateTime.value=datetime(2026,10,7,20,0)
            run_id=manager.scheduler_tick()
            deadline=time.monotonic()+4
            while manager.lock.locked() and time.monotonic()<deadline:time.sleep(.01)
            with app.connect() as db:
                self.assertEqual(db.execute('SELECT scheduled_for FROM discovery_runs WHERE id=?',(run_id,)).fetchone()[0],'2026-10-07T08:00:00')
                self.assertEqual(db.execute('SELECT next_run_at FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone()[0],'2026-10-08T08:00:00')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM discovery_runs').fetchone()[0],1)
            manager.last_start=0;self.assertIsNone(manager.scheduler_tick())

    def test_manual_does_not_move_scheduled_slot_pause_and_revision(self):
        identifier=self.campaign(frequency='scheduled')
        with app.connect() as db:
            original=dict(db.execute('SELECT * FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone())
        manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
        self.collect(manager,'local-default',identifier)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT next_run_at FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone()[0],original['next_run_at'])
            discovery.save_campaign(db,'local-default',{**CAMPAIGN,'frequency':'scheduled','active':False,'revision':original['revision']},identifier)
        with app.connect() as db:
            self.assertIsNone(db.execute('SELECT next_run_at FROM discovery_campaigns WHERE id=?',(identifier,)).fetchone()[0])
            with self.assertRaises(discovery.CampaignConflict):discovery.save_campaign(db,'local-default',{**CAMPAIGN,'revision':original['revision']},identifier)
        manager.last_start=0
        with self.assertRaises(ValueError):manager.start('local-default',identifier)

    def test_deactivated_account_cannot_collect_or_receive_inflight_results(self):
        identifier=self.campaign(owner='disabled-owner',frequency='daily')
        with app.connect() as db:
            db.execute("INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,is_active,created_at,updated_at) VALUES('disabled-owner','QA','qa-disabled','qa@example.invalid','unused','unused',0,'2026-10-07','2026-10-07')")
            db.execute("UPDATE discovery_campaigns SET next_run_at='2020-01-01' WHERE id=?",(identifier,))
        manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
        self.assertIsNone(manager.scheduler_tick())
        with self.assertRaises(ValueError):manager.start('disabled-owner',identifier)
        with app.connect() as db:db.execute("UPDATE user_accounts SET is_active=1 WHERE id='disabled-owner'")
        def provider(*args):
            with app.connect() as db:db.execute("UPDATE user_accounts SET is_active=0 WHERE id='disabled-owner'")
            return ELEMENTS
        manager.provider=provider
        run_id=self.collect(manager,'disabled-owner',identifier)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM discovery_runs WHERE id=?',(run_id,)).fetchone()[0],'interrompido')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0],0)

    def test_recommendations_notification_dedup_and_no_official_leads(self):
        identifier=self.campaign(icp_label='Perfil informado')
        manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
        self.collect(manager,'local-default',identifier)
        with app.connect() as db:
            result=discovery.recommendations(db,'local-default',{})
            self.assertEqual(result['total'],1);item=result['items'][0]
            self.assertIn('Porto Alegre',item['reason']);self.assertIn('Perfil informado',item['reason'])
            self.assertEqual(discovery.notifications(db,'local-default')['unread'],1)
            self.assertEqual(discovery.notifications(db,'other')['unread'],0)
            self.assertEqual(discovery.recommendations(db,'other',{})['total'],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sales_profile_leads').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],0)
            discovery.review_recommendations(db,'local-default',{'status':'dismissed','items':[{'id':item['id'],'revision':1}]})
        self.collect(manager,'local-default',identifier)
        with app.connect() as db:
            self.assertEqual(discovery.recommendations(db,'local-default',{})['total'],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM discovery_recommendations').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM discovery_notifications').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0],1)

    def test_owner_scoped_atomic_review_conflicts_and_read_ack(self):
        identifier=self.campaign();manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
        self.collect(manager,'local-default',identifier)
        items=json.loads(self.request('GET','/api/discovery/recommendations')[1])['items'];item=items[0]
        payload={'status':'accepted','items':[{'id':item['id'],'revision':1},{'id':'foreign','revision':1}]}
        self.assertEqual(self.request('POST','/api/discovery/recommendations/review',payload)[0],404)
        self.assertEqual(json.loads(self.request('GET','/api/discovery/recommendations')[1])['total'],1)
        payload['items']=payload['items'][:1]
        self.assertEqual(self.request('POST','/api/discovery/recommendations/review',payload,{'Origin':'https://bad.invalid'})[0],403)
        self.assertEqual(self.request('POST','/api/discovery/recommendations/review',payload)[0],200)
        self.assertEqual(self.request('POST','/api/discovery/recommendations/review',payload)[0],409)
        self.assertEqual(json.loads(self.request('GET','/api/discovery/recommendations?status=accepted')[1])['total'],1)
        note=json.loads(self.request('GET','/api/discovery/notifications')[1])['items'][0]
        with app.connect() as db:discovery.update_notifications(db,'foreign',{'ids':[note['id']]})
        self.assertEqual(json.loads(self.request('GET','/api/discovery/notifications')[1])['unread'],1)
        self.assertEqual(self.request('POST','/api/discovery/notifications',{'ids':[note['id']]})[0],200)
        self.assertEqual(json.loads(self.request('GET','/api/discovery/notifications')[1])['unread'],0)
        with app.connect() as db:
            with self.assertRaises(LookupError):discovery.review_recommendations(db,'foreign',payload)

    def test_muting_keeps_recommendations_and_zero_results_no_notice(self):
        self.assertEqual(self.request('POST','/api/discovery/notifications',{'enabled':'yes'})[0],400)
        self.assertEqual(self.request('POST','/api/discovery/notifications',{'enabled':False})[0],200)
        identifier=self.campaign();manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
        self.collect(manager,'local-default',identifier)
        with app.connect() as db:
            self.assertEqual(discovery.recommendations(db,'local-default',{})['total'],1)
            self.assertEqual(discovery.notifications(db,'local-default')['items'],[])
            discovery.update_notifications(db,'local-default',{'enabled':True})
        other=self.campaign(city='Caxias do Sul')
        manager.provider=lambda *args:[]
        self.collect(manager,'local-default',other)
        with app.connect() as db:self.assertEqual(discovery.notifications(db,'local-default')['items'],[])

    def test_pause_during_collection_does_not_save(self):
        entered=threading.Event();finish=threading.Event()
        def provider(*args):entered.set();finish.wait(3);return ELEMENTS
        identifier=self.campaign();manager=discovery.DiscoveryManager(app.connect,provider=provider)
        run_id=manager.start('local-default',identifier);self.assertTrue(entered.wait(2))
        with app.connect() as db:discovery.save_campaign(db,'local-default',{**CAMPAIGN,'active':False},identifier)
        finish.set();deadline=time.monotonic()+4
        while manager.lock.locked() and time.monotonic()<deadline:time.sleep(.01)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM discovery_runs WHERE id=?',(run_id,)).fetchone()[0],'interrompido')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0],0)

    def test_scheduler_obeys_custom_quota_and_disabled_switch(self):
        identifier=self.campaign(frequency='scheduled');manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS)
        self.collect(manager,'local-default',identifier)
        with app.connect() as db:db.execute("UPDATE discovery_campaigns SET next_run_at='2026-01-01T08:00:00' WHERE id=?",(identifier,))
        original=admin_panel.get
        with patch.object(admin_panel,'get',side_effect=lambda key,*args:1 if key=='capture_runs_account' else original(key,*args)):
            manager.last_start=0;self.assertIsNone(manager.scheduler_tick())
            with self.assertRaises(ValueError):manager.start('local-default',identifier)
        with patch.object(admin_panel,'get',side_effect=lambda key,*args:False if key=='capture_scheduler' else original(key,*args)):
            self.assertIsNone(manager.scheduler_tick())

    def test_pagination_and_validation(self):
        identifier=self.campaign();manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:[dict(type='node',id=i,tags={'name':f'Loja {i}'}) for i in range(1,52)])
        self.collect(manager,'local-default',identifier)
        manager.provider=lambda *args:[dict(type='node',id=100,tags={'name':'Loja extra'})]
        self.collect(manager,'local-default',identifier)
        status,raw,_=self.request('GET','/api/discovery/recommendations?page=2');self.assertEqual(status,200);self.assertEqual(len(json.loads(raw)['items']),1)
        self.assertEqual(self.request('GET','/api/discovery/recommendations?status=invalid')[0],400)
        self.assertEqual(self.request('GET','/api/discovery/recommendations?page=abc')[0],400)
        for payload in ({'status':'accepted','items':[]},{'status':'pending','items':[{'id':'a','revision':1}]},{'status':'accepted','items':[{'id':'a','revision':True}]}):
            self.assertEqual(self.request('POST','/api/discovery/recommendations/review',payload)[0],400)

del DiscoveryTests

class AssistedPrivacyTests(unittest.TestCase):
    setUp=AdminPanelTests.setUp
    tearDown=AdminPanelTests.tearDown
    request=AdminPanelTests.request
    login=AdminPanelTests.login
    create_seller=AdminPanelTests.create_seller

    def test_signed_seller_cannot_read_or_review_another_account(self):
        seller_id=self.create_seller();seller=self.login('sellerqa','Seller2026@')
        with app.connect() as db:identifier=discovery.save_campaign(db,'private-owner',CAMPAIGN)
        manager=discovery.DiscoveryManager(app.connect,provider=lambda *args:ELEMENTS);manager.start('private-owner',identifier)
        deadline=time.monotonic()+4
        while manager.lock.locked() and time.monotonic()<deadline:time.sleep(.01)
        with app.connect() as db:item=discovery.recommendations(db,'private-owner',{})['items'][0]
        for path in ('/api/discovery/notifications','/api/discovery/recommendations'):
            self.assertEqual(self.request('GET',path,token=False)[0],401)
            self.assertEqual(json.loads(self.request('GET',path,cookie=seller)[1])['items'],[])
        payload={'status':'accepted','items':[{'id':item['id'],'revision':1}]}
        self.assertEqual(self.request('POST','/api/discovery/recommendations/review',payload,seller)[0],404)
        with app.connect() as db:self.assertEqual(discovery.recommendations(db,'private-owner',{})['total'],1)
        self.assertEqual(self.request('POST','/api/discovery/notifications',{'enabled':False},seller,origin='https://bad.invalid')[0],403)

del AdminPanelTests
