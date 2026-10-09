"""Bounded, account-private OSM discovery and optional public-site enrichment."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
import prospecting
import admin_panel
import local_osm

ROOT = Path(__file__).resolve().parent
OVERPASS_URL = 'https://overpass.private.coffee/api/interpreter'
OVERPASS_FALLBACK = 'https://overpass-api.de/api/interpreter'
CATEGORIES = {
 'restaurantes': ('Restaurantes', [('amenity','restaurant')]),
 'fast-food': ('Lanchonetes e fast-food', [('amenity','fast_food')]),
 'cafeterias': ('Cafeterias', [('amenity','cafe')]),
 'padarias': ('Padarias', [('shop','bakery')]),
 'mercados': ('Mercados e supermercados', [('shop','supermarket'),('shop','convenience')]),
 'bares': ('Bares e pubs', [('amenity','bar'),('amenity','pub')]),
 'hospedagem': ('Hotéis e pousadas', [('tourism','hotel'),('tourism','guest_house')]),
 'moda': ('Roupas e calçados', [('shop','clothes'),('shop','shoes')]),
 'beleza': ('Salões e beleza', [('shop','hairdresser'),('shop','beauty')]),
 'farmacias': ('Farmácias', [('amenity','pharmacy')]),
 'clinicas': ('Clínicas e consultórios', [('amenity','clinic'),('amenity','doctors')]),
 'dentistas': ('Dentistas', [('amenity','dentist')]),
 'academias': ('Academias', [('leisure','fitness_centre')]),
 'pets': ('Pet shops e veterinários', [('shop','pet'),('amenity','veterinary')]),
 'auto': ('Oficinas e autopeças', [('shop','car_repair'),('shop','car_parts')]),
 'postos': ('Postos de combustível', [('amenity','fuel')]),
 'construcao': ('Materiais de construção', [('shop','doityourself'),('shop','hardware')]),
 'moveis': ('Móveis e decoração', [('shop','furniture'),('shop','interior_decoration')]),
 'tecnologia': ('Informática e eletrônicos', [('shop','computer'),('shop','electronics')]),
 'educacao': ('Escolas e cursos', [('amenity','school'),('amenity','language_school')]),
 'servicos': ('Serviços profissionais', [('office','company'),('office','consulting')]),
 'contabilidade': ('Escritórios de contabilidade', [('office','accountant')]),
 'imobiliarias': ('Imobiliárias', [('office','estate_agent')]),
 'industria': ('Instalações industriais', [('man_made','works')]),
 'agro': ('Lojas agropecuárias', [('shop','agrarian')]),
}

def now(): return datetime.now().isoformat(timespec='seconds')

DEFAULT_TIMES = ['08:00', '13:00', '17:00']

class CampaignConflict(RuntimeError): pass

def next_scheduled(times, reference=None):
    """Next future wall-clock slot. Missed slots never produce a catch-up burst."""
    reference = reference or datetime.now()
    for offset in (0, 1):
        day = (reference + timedelta(days=offset)).date()
        for value in sorted(times):
            candidate = datetime.combine(day, datetime.strptime(value, '%H:%M').time())
            if candidate > reference:
                return candidate.isoformat(timespec='seconds')
    raise ValueError('Informe pelo menos um horário')

def ensure_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS discovery_campaigns (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,name TEXT NOT NULL,city TEXT NOT NULL,category TEXT NOT NULL,
      frequency TEXT NOT NULL,active INTEGER NOT NULL,require_phone INTEGER NOT NULL,require_website INTEGER NOT NULL,
      enrich_websites INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,next_run_at TEXT);
      CREATE INDEX IF NOT EXISTS idx_discovery_due ON discovery_campaigns(active,next_run_at);
      CREATE TABLE IF NOT EXISTS discovery_runs (
      id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,owner_id TEXT NOT NULL,status TEXT NOT NULL,
      found INTEGER NOT NULL DEFAULT 0,added INTEGER NOT NULL DEFAULT 0,duplicates INTEGER NOT NULL DEFAULT 0,
      enriched INTEGER NOT NULL DEFAULT 0,started_at TEXT NOT NULL,finished_at TEXT,message TEXT NOT NULL DEFAULT '',
      FOREIGN KEY(campaign_id) REFERENCES discovery_campaigns(id));
      CREATE INDEX IF NOT EXISTS idx_discovery_owner ON discovery_runs(owner_id,started_at DESC);
      CREATE TABLE IF NOT EXISTS discovery_sources (
      owner_id TEXT NOT NULL,source_key TEXT NOT NULL,prospect_id TEXT NOT NULL,metadata_json TEXT NOT NULL,last_seen_at TEXT NOT NULL,
      PRIMARY KEY(owner_id,source_key),FOREIGN KEY(prospect_id) REFERENCES prospect_inbox(id));
      CREATE TABLE IF NOT EXISTS discovery_cache (query_key TEXT PRIMARY KEY,elements_json TEXT NOT NULL,fetched_at TEXT NOT NULL,expires_at TEXT NOT NULL);''')
    if 'cursor_json' not in {r[1] for r in db.execute('PRAGMA table_info(discovery_campaigns)')}:
        db.execute("ALTER TABLE discovery_campaigns ADD COLUMN cursor_json TEXT NOT NULL DEFAULT '{}'")
    columns={r[1] for r in db.execute('PRAGMA table_info(discovery_campaigns)')}
    for name,definition in [('times_json',"TEXT NOT NULL DEFAULT '[]'"),('icp_label',"TEXT NOT NULL DEFAULT ''"),('revision','INTEGER NOT NULL DEFAULT 1')]:
        if name not in columns: db.execute(f'ALTER TABLE discovery_campaigns ADD COLUMN {name} {definition}')
    if 'scheduled_for' not in {r[1] for r in db.execute('PRAGMA table_info(discovery_runs)')}:
        db.execute('ALTER TABLE discovery_runs ADD COLUMN scheduled_for TEXT')
    db.executescript('''CREATE UNIQUE INDEX IF NOT EXISTS idx_discovery_slot ON discovery_runs(campaign_id,scheduled_for) WHERE scheduled_for IS NOT NULL;
      CREATE TABLE IF NOT EXISTS discovery_recommendations (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,prospect_id TEXT NOT NULL,campaign_id TEXT NOT NULL,
      run_id TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
      revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,reviewed_at TEXT,
      UNIQUE(owner_id,prospect_id),FOREIGN KEY(prospect_id) REFERENCES prospect_inbox(id),
      FOREIGN KEY(campaign_id) REFERENCES discovery_campaigns(id),FOREIGN KEY(run_id) REFERENCES discovery_runs(id));
      CREATE INDEX IF NOT EXISTS idx_recommendations_owner ON discovery_recommendations(owner_id,status,created_at DESC);
      CREATE TABLE IF NOT EXISTS discovery_notifications (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,run_id TEXT NOT NULL UNIQUE,campaign_id TEXT NOT NULL,
      added INTEGER NOT NULL,created_at TEXT NOT NULL,read_at TEXT,
      FOREIGN KEY(run_id) REFERENCES discovery_runs(id),FOREIGN KEY(campaign_id) REFERENCES discovery_campaigns(id));
      CREATE INDEX IF NOT EXISTS idx_notifications_owner ON discovery_notifications(owner_id,created_at DESC);
      CREATE TABLE IF NOT EXISTS discovery_preferences (owner_id TEXT PRIMARY KEY,notifications_enabled INTEGER NOT NULL DEFAULT 1);''')

def validate(raw):
    if not isinstance(raw,dict): raise ValueError('Campanha inválida')
    name=raw.get('name','');city=raw.get('city','');category=raw.get('category','')
    if not isinstance(name,str) or not 2<=len(name.strip())<=100: raise ValueError('Nome: 2 a 100 caracteres')
    if not isinstance(city,str) or not re.fullmatch(r"[\wÀ-ÿ .'-]{2,100}",city.strip()) or '_' in city: raise ValueError('Informe o município do RS')
    if category not in CATEGORIES: raise ValueError('Categoria não suportada')
    frequency=raw.get('frequency','manual')
    if frequency not in ('manual','daily','scheduled'): raise ValueError('Frequência inválida')
    result=dict(name=name.strip(),city=city.strip(),category=category,frequency=frequency)
    times=raw.get('times',DEFAULT_TIMES if frequency=='scheduled' else [])
    if not isinstance(times,list) or len(times)>3 or any(not isinstance(v,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v) for v in times):
        raise ValueError('Use até três horários no formato HH:MM')
    if len(times)!=len(set(times)) or (frequency=='scheduled' and not times): raise ValueError('Escolha de um a três horários diferentes')
    times=sorted(times)
    if any((datetime.strptime(b,'%H:%M')-datetime.strptime(a,'%H:%M')).total_seconds()<3600 for a,b in zip(times,times[1:])):
        raise ValueError('Deixe pelo menos uma hora entre as rodadas')
    icp=raw.get('icp_label','')
    if not isinstance(icp,str) or len(icp)>120 or any(ord(c)<32 for c in icp): raise ValueError('Perfil comercial: até 120 caracteres')
    result.update(times_json=json.dumps(times),icp_label=icp.strip())
    for key,default in [('active',True),('require_phone',False),('require_website',False),('enrich_websites',False)]:
        value=raw.get(key,default)
        if not isinstance(value,(bool,int)) or value not in (0,1): raise ValueError('Opção inválida: '+key)
        result[key]=int(value)
    return result

def save_campaign(db,owner,raw,campaign_id=None):
    values=validate(raw);timestamp=now()
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    if campaign_id:
        old=db.execute('SELECT * FROM discovery_campaigns WHERE id=? AND owner_id=?',(campaign_id,owner)).fetchone()
        if not old: raise LookupError('Campanha não encontrada')
        if 'revision' in raw and (type(raw['revision']) is not int or raw['revision']!=old['revision']): raise CampaignConflict('Campanha alterada em outra sessão. Atualize antes de salvar.')
        schedule_changed=old['frequency']!=values['frequency'] or old['times_json']!=values['times_json'] or old['active']!=values['active']
        next_run=old['next_run_at'] or timestamp
        if values['frequency']=='scheduled' and schedule_changed: next_run=next_scheduled(json.loads(values['times_json']))
        if values['frequency']=='manual' or not values['active']: next_run=None
        db.execute('UPDATE discovery_campaigns SET '+','.join(k+'=?' for k in values)+',updated_at=?,next_run_at=?,revision=revision+1 WHERE id=? AND owner_id=?',list(values.values())+[timestamp,next_run,campaign_id,owner])
        if old['city']!=values['city'] or old['category']!=values['category']:
            db.execute("UPDATE discovery_campaigns SET cursor_json='{}' WHERE id=?",(campaign_id,))
    else:
        if db.execute('SELECT COUNT(*) FROM discovery_campaigns WHERE owner_id=?',(owner,)).fetchone()[0]>=30: raise ValueError('Limite de 30 campanhas por conta')
        campaign_id=uuid.uuid4().hex
        next_run=(next_scheduled(json.loads(values['times_json'])) if values['frequency']=='scheduled' else timestamp if values['frequency']=='daily' else None) if values['active'] else None
        db.execute('INSERT INTO discovery_campaigns(id,owner_id,'+','.join(values)+',created_at,updated_at,next_run_at) VALUES('+','.join('?' for _ in range(len(values)+5))+')',[campaign_id,owner]+list(values.values())+[timestamp,timestamp,next_run])
    return campaign_id

def snapshot(db,owner):
    campaigns=[dict(r) for r in db.execute('SELECT * FROM discovery_campaigns WHERE owner_id=? ORDER BY created_at DESC',(owner,))]
    for campaign in campaigns: campaign['times']=json.loads(campaign.pop('times_json'))
    runs=[dict(r) for r in db.execute('SELECT * FROM discovery_runs WHERE owner_id=? ORDER BY started_at DESC LIMIT 30',(owner,))]
    total=db.execute('SELECT COUNT(*) FROM discovery_sources WHERE owner_id=?',(owner,)).fetchone()[0]
    return {'campaigns':campaigns,'runs':runs,'total':total,'categories':[{'id':k,'label':v[0]} for k,v in CATEGORIES.items()],
            'limits':{'per_run':50,'runs_per_day':admin_panel.get('capture_runs_account'),'websites_per_run':admin_panel.get('capture_sites')},'enabled':admin_panel.get('capture_enabled'),'collector_ready':bool(shutil.which('node') and (ROOT/'collector/node_modules/@crawlee/basic').is_dir()),
            'osm_mode':admin_panel.get('capture_osm_mode'),'local_osm':local_osm.status(),
            'scheduler_enabled':admin_panel.get('capture_scheduler'),'server_time':now(),
            'pending_recommendations':db.execute("SELECT COUNT(*) FROM discovery_recommendations WHERE owner_id=? AND status='pending'",(owner,)).fetchone()[0]}

def query(city,category,cursors=None):
    if category not in CATEGORIES: raise ValueError('Categoria não suportada')
    plain=''.join(c for c in unicodedata.normalize('NFD',city) if not unicodedata.combining(c)).casefold()
    groups={'a':'[aáàâãä]','e':'[eéèêë]','i':'[iíìîï]','o':'[oóòôõö]','u':'[uúùûü]','c':'[cç]'}
    city=json.dumps('^'+''.join(groups.get(c,re.escape(c)) for c in plain)+'$',ensure_ascii=False)
    cursors=cursors or {}
    selectors=''.join(f'{kind}[{json.dumps(k)}={json.dumps(v)}](area.city)(if:id()>{max(0,int(cursors.get(kind,0)))});' for kind in ('node','way','relation') for k,v in CATEGORIES[category][1])
    return '[out:json][timeout:25];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.state;area["name"~'+city+',i]["admin_level"="8"](area.state)->.city;('+selectors+');out center tags 51;'

def fetch_osm(city,category,cursors=None):
    body=urlencode({'data':query(city,category,cursors)}).encode()
    for index,endpoint in enumerate((OVERPASS_URL,OVERPASS_FALLBACK)):
        request=Request(endpoint,data=body,headers={'User-Agent':'RadarCNPJ/1.0 public-business-discovery','Content-Type':'application/x-www-form-urlencoded'},method='POST')
        try:
            with urlopen(request,timeout=35) as response:
                content=response.read(4*1024*1024+1)
                if len(content)>4*1024*1024:raise ValueError('Resposta acima do limite seguro')
                data=json.loads(content)
            if not isinstance(data,dict) or 'remark' in data or not isinstance(data.get('elements'),list):raise ValueError('Consulta OSM incompleta')
            return data['elements']
        except HTTPError as error:
            # Do not evade rate limits or repeat invalid requests on other instances.
            error.close()
            if error.code==429 or error.code<500:raise ValueError('OSM recusou a consulta; aguarde antes de tentar novamente.') from None
        except (URLError,TimeoutError,OSError,ValueError):
            pass
        if index:raise ValueError('As fontes públicas OSM estão indisponíveis. Nenhum contato foi importado; tente novamente mais tarde.')

def clean(value,limit): return re.sub(r'[\x00-\x1f]', ' ',str(value or '')).strip()[:limit]

def fetch_source(city,category,cursors=None):
    if admin_panel.get('capture_osm_mode')=='local':
        return local_osm.fetch(city,category,cursors)
    return fetch_osm(city,category,cursors)

def start_local_scheduler():
    local_osm.start_scheduler()

def records(elements,campaign):
    output=[]
    for element in elements[:50]:
        tags=element.get('tags',{});kind=element.get('type');identifier=element.get('id')
        if kind not in ('node','way','relation') or not isinstance(identifier,int) or not isinstance(tags,dict): continue
        name=clean(tags.get('name') or tags.get('brand'),180)
        if not name: continue
        phone=clean(tags.get('contact:phone') or tags.get('phone'),32)
        website=clean(tags.get('contact:website') or tags.get('website'),300)
        if website:
            if '://' not in website: website='https://'+website
            try:
                url=urlsplit(website)
                if url.scheme not in ('http','https') or not url.hostname or url.username or url.password: website=''
            except ValueError: website=''
        email=clean(tags.get('contact:email') or tags.get('email'),180)
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): email=''
        if campaign['require_phone'] and not phone or campaign['require_website'] and not website: continue
        source_key=f'{kind}/{identifier}'
        row=dict(name=name,company=name,phone=phone,email=email,city=campaign['city'],source='OpenStreetMap',campaign=campaign['name'],website=website,notes='',cnpj='',persona='')
        metadata={'source_url':'https://www.openstreetmap.org/'+source_key,'collected_at':now(),'category':CATEGORIES[campaign['category']][0],
                  'address':clean(' '.join(str(tags.get(k,'') or '') for k in ['addr:street','addr:housenumber','addr:suburb']),300),'attribution':'© OpenStreetMap contributors · ODbL',
                  'enrichment_status':'não solicitado','pages':[],'socials':[]}
        output.append({'key':source_key,'row':row,'metadata':metadata})
        if len(output)>=50: break
    return output

def enrich_sites(rows):
    node=shutil.which('node')
    if not node or not (ROOT/'collector/node_modules/@crawlee/basic').is_dir(): raise RuntimeError('Coletor Node indisponível')
    seeds=[{'id':r['key'],'website':r['row']['website']} for r in rows if r['row']['website']][:admin_panel.get('capture_sites')]
    if not seeds: return 0
    # Do not pass API credentials, application cookies or account environment to the collector.
    env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','COMSPEC','PATHEXT'}}
    process=subprocess.run([node,str(ROOT/'collector/enrich.mjs')],input=json.dumps({'seeds':seeds}),capture_output=True,text=True,encoding='utf-8',cwd=ROOT/'collector',env=env,timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if process.returncode or len(process.stdout)>200000: raise RuntimeError('Coletor indisponível')
    results=json.loads(process.stdout).get('results',[]);by_key={r['key']:r for r in rows};count=0
    for result in results:
        item=by_key.get(result.get('id'))
        if not item: continue
        row=item['row'];item['metadata'].update(enrichment_status=result.get('status'),pages=result.get('pages',[])[:3],socials=result.get('socials',[])[:5],observed_cnpj=result.get('cnpj',''))
        # Only fill missing contacts. CNPJ from a website is not a validated RF identity.
        if not row['phone'] and result.get('phones'): row['phone']=clean(result['phones'][0],32)
        if not row['email'] and result.get('emails'): row['email']=clean(result['emails'][0],180)
        if result.get('status')=='consultado': count+=1
    return count

def store_records(db,owner,rows,campaign=None,run_id=None):
    added=duplicates=0;timestamp=now()
    for item in rows:
        old=db.execute('SELECT prospect_id FROM discovery_sources WHERE owner_id=? AND source_key=?',(owner,item['key'])).fetchone()
        if old:
            duplicates+=1
            db.execute('UPDATE discovery_sources SET metadata_json=?,last_seen_at=? WHERE owner_id=? AND source_key=?',(json.dumps(item['metadata'],ensure_ascii=False),timestamp,owner,item['key']))
            continue  # Never overwrite a seller's edits, notes, status or contact choices.
        row=prospecting.validate(item['row']);fp=prospecting.fingerprint(row)
        existing=db.execute('SELECT id FROM prospect_inbox WHERE owner_id=? AND fingerprint=?',(owner,fp)).fetchone()
        identifier=existing['id'] if existing else uuid.uuid4().hex
        if not existing:
            db.execute('INSERT INTO prospect_inbox(id,owner_id,fingerprint,'+','.join(row)+',created_at,updated_at) VALUES('+','.join('?' for _ in range(len(row)+5))+')',[identifier,owner,fp]+list(row.values())+[timestamp,timestamp]);added+=1
        else: duplicates+=1
        db.execute('INSERT INTO discovery_sources VALUES(?,?,?,?,?)',(owner,item['key'],identifier,json.dumps(item['metadata'],ensure_ascii=False),timestamp))
        if not existing and campaign and run_id:
            reason=campaign['city']+' · '+CATEGORIES[campaign['category']][0]
            if campaign.get('icp_label'): reason+=' · Perfil definido por você: '+campaign['icp_label']
            reason+=' · '+('Telefone público disponível' if row['phone'] else 'Sem telefone publicado')
            reason+=' · '+('E-mail público disponível' if row['email'] else 'Sem e-mail publicado')
            db.execute('INSERT OR IGNORE INTO discovery_recommendations(id,owner_id,prospect_id,campaign_id,run_id,reason,created_at) VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex,owner,identifier,campaign['id'],run_id,reason,timestamp))
    return added,duplicates

def recommendations(db,owner,params):
    status=params.get('status',['pending'])[0]
    if status not in ('pending','accepted','dismissed'): raise ValueError('Situação inválida')
    try: page=max(1,int(params.get('page',['1'])[0]))
    except (TypeError,ValueError): raise ValueError('Página inválida') from None
    where='r.owner_id=? AND r.status=?';values=[owner,status]
    total=db.execute('SELECT COUNT(*) FROM discovery_recommendations r WHERE '+where,values).fetchone()[0]
    page=min(page,max(1,(total+49)//50))
    rows=db.execute('''SELECT r.*,p.name,p.city,p.phone,p.email,p.website,p.cnpj,c.name AS campaign
      FROM discovery_recommendations r JOIN prospect_inbox p ON p.id=r.prospect_id AND p.owner_id=r.owner_id
      JOIN discovery_campaigns c ON c.id=r.campaign_id WHERE '''+where+' ORDER BY r.created_at DESC,r.id LIMIT 50 OFFSET ?',values+[(page-1)*50]).fetchall()
    return {'items':[dict(r) for r in rows],'total':total,'page':page,'size':50,
            'counts':{r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM discovery_recommendations WHERE owner_id=? GROUP BY status',(owner,))}}

def review_recommendations(db,owner,raw):
    if not isinstance(raw,dict) or raw.get('status') not in ('accepted','dismissed'): raise ValueError('Escolha selecionar ou descartar')
    items=raw.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=50: raise ValueError('Selecione de 1 a 50 recomendações')
    if any(not isinstance(i,dict) or not isinstance(i.get('id'),str) or type(i.get('revision')) is not int for i in items): raise ValueError('Seleção inválida')
    if len({i['id'] for i in items})!=len(items): raise ValueError('Seleção duplicada')
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    # Validate the entire batch before changing anything.
    for item in items:
        old=db.execute('SELECT * FROM discovery_recommendations WHERE id=? AND owner_id=?',(item['id'],owner)).fetchone()
        if not old: raise LookupError('Recomendação não encontrada nesta conta')
        if old['revision']!=item['revision']: raise CampaignConflict('Recomendação alterada em outra sessão. Atualize a lista.')
        if old['status']!='pending': raise CampaignConflict('Esta recomendação já foi analisada. Atualize a lista.')
    for item in items:
        db.execute('UPDATE discovery_recommendations SET status=?,revision=revision+1,reviewed_at=? WHERE id=? AND owner_id=?',(raw['status'],now(),item['id'],owner))
    return {'updated':len(items),'status':raw['status']}

def notifications(db,owner):
    pref=db.execute('SELECT notifications_enabled FROM discovery_preferences WHERE owner_id=?',(owner,)).fetchone()
    enabled=bool(pref[0]) if pref else True
    rows=db.execute('''SELECT n.*,c.name AS campaign FROM discovery_notifications n JOIN discovery_campaigns c ON c.id=n.campaign_id
      WHERE n.owner_id=? ORDER BY (n.read_at IS NULL) DESC,n.created_at DESC,n.id LIMIT 30''',(owner,)).fetchall()
    unread=db.execute('SELECT COUNT(*) FROM discovery_notifications WHERE owner_id=? AND read_at IS NULL',(owner,)).fetchone()[0]
    return {'items':[dict(r) for r in rows],'unread':unread,'enabled':enabled}

def update_notifications(db,owner,raw):
    if not isinstance(raw,dict): raise ValueError('Notificação inválida')
    if set(raw)=={'enabled'} and type(raw['enabled']) is bool:
        db.execute('INSERT INTO discovery_preferences VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET notifications_enabled=excluded.notifications_enabled',(owner,int(raw['enabled'])))
        return {'enabled':raw['enabled']}
    ids=raw.get('ids')
    if set(raw)!={'ids'} or not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(i,str) for i in ids): raise ValueError('Notificações inválidas')
    db.execute('UPDATE discovery_notifications SET read_at=COALESCE(read_at,?) WHERE owner_id=? AND id IN ('+','.join('?' for _ in ids)+')',[now(),owner]+ids)
    return {'ok':True}

class DiscoveryManager:
    def __init__(self,connect,provider=None,enricher=enrich_sites):
        self.connect=connect;self.provider=provider or fetch_source;self.enricher=enricher;self.lock=threading.Lock();self.last_start=0;self.scheduler_started=False

    def start(self,owner,campaign_id,scheduled_for=None):
        if not admin_panel.get('capture_enabled'):raise ValueError('Captação desativada pelo administrador')
        if not self.lock.acquire(blocking=False): raise ValueError('Outra campanha está em execução; aguarde a conclusão')
        try:
            if time.monotonic()-self.last_start<60: raise ValueError('Aguarde um minuto entre consultas')
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                campaign=db.execute('SELECT * FROM discovery_campaigns WHERE id=? AND owner_id=?',(campaign_id,owner)).fetchone()
                if not campaign: raise LookupError('Campanha não encontrada')
                account=db.execute('SELECT is_active FROM user_accounts WHERE id=?',(owner,)).fetchone()
                if account and not account['is_active']: raise ValueError('Conta desativada; campanha não iniciada')
                if not campaign['active']: raise ValueError('Campanha pausada')
                if scheduled_for and (not admin_panel.get('capture_scheduler') or campaign['frequency']=='manual' or campaign['next_run_at']!=scheduled_for or scheduled_for>now()):
                    raise ValueError('Agendamento alterado; coleta não iniciada')
                cutoff=(datetime.now()-timedelta(hours=24)).isoformat(timespec='seconds')
                if db.execute('SELECT COUNT(*) FROM discovery_runs WHERE started_at>=?',(cutoff,)).fetchone()[0]>=admin_panel.get('capture_runs_global'): raise ValueError('Limite global de rodadas nas últimas 24 horas; aguarde')
                if db.execute('SELECT COUNT(*) FROM discovery_runs WHERE owner_id=? AND started_at>=?',(owner,cutoff)).fetchone()[0]>=admin_panel.get('capture_runs_account'): raise ValueError('Limite de rodadas por conta nas últimas 24 horas')
                run_id=uuid.uuid4().hex
                db.execute('INSERT INTO discovery_runs(id,campaign_id,owner_id,status,started_at,scheduled_for) VALUES(?,?,?,?,?,?)',(run_id,campaign_id,owner,'executando',now(),scheduled_for))
                if campaign['frequency']=='daily': next_run=(datetime.now()+timedelta(days=1)).isoformat(timespec='seconds')
                elif campaign['frequency']=='scheduled' and scheduled_for: next_run=next_scheduled(json.loads(campaign['times_json']))
                else: next_run=campaign['next_run_at']
                db.execute('UPDATE discovery_campaigns SET next_run_at=? WHERE id=?',(next_run,campaign_id))
                db.commit()
            self.last_start=time.monotonic()
            threading.Thread(target=self.execute,args=(dict(campaign),run_id),daemon=True,name='radar-discovery').start()
            return run_id
        except Exception:
            self.lock.release();raise

    def execute(self,campaign,run_id):
        try:
            cursors=json.loads(campaign.get('cursor_json') or '{}')
            source_state=local_osm.status() if self.provider is fetch_source and admin_panel.get('capture_osm_mode')=='local' else None
            source_token=('local:'+source_state['version']) if source_state else ('overpass' if self.provider is fetch_source else '')
            if source_token and cursors.get('_source')!=source_token: cursors={}
            key=query(campaign['city'],campaign['category'],cursors)
            if source_token: key=source_token+'|'+key
            with self.connect() as db: cached=db.execute('SELECT * FROM discovery_cache WHERE query_key=? AND expires_at>?',(key,now())).fetchone()
            fetched_at=cached['fetched_at'] if cached else now()
            if source_state and source_state['ready']: fetched_at=source_state['built_at']
            elements=json.loads(cached['elements_json']) if cached else self.provider(campaign['city'],campaign['category'],cursors)
            rows=records(elements,campaign)
            for item in rows:
                item['metadata']['collected_at']=fetched_at
                if source_state: item['metadata'].update(source_backend='OSM local · Geofabrik',dataset_version=source_state['version'])
            enriched=0;warning=''
            if campaign['enrich_websites'] and admin_panel.get('enrichment_enabled'):
                try: enriched=self.enricher(rows)
                except Exception: warning=' Contatos do mapa preservados; enriquecimento dos sites indisponível nesta rodada.'
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT active,revision FROM discovery_campaigns WHERE id=?',(campaign['id'],)).fetchone()
                account=db.execute('SELECT is_active FROM user_accounts WHERE id=?',(campaign['owner_id'],)).fetchone()
                if not current or not current['active'] or current['revision']!=campaign['revision'] or account and not account['is_active']:
                    db.execute("UPDATE discovery_runs SET status='interrompido',finished_at=?,message='Campanha pausada, editada ou conta desativada durante a coleta. Nenhum contato desta rodada foi gravado.' WHERE id=?",(now(),run_id))
                    return
                if not cached:
                    db.execute('INSERT INTO discovery_cache VALUES(?,?,?,?) ON CONFLICT(query_key) DO UPDATE SET elements_json=excluded.elements_json,fetched_at=excluded.fetched_at,expires_at=excluded.expires_at',(key,json.dumps(elements[:51],ensure_ascii=False),fetched_at,(datetime.now()+timedelta(hours=24)).isoformat(timespec='seconds')))
                added,duplicates=store_records(db,campaign['owner_id'],rows,campaign,run_id)
                fresh=db.execute('SELECT COUNT(*) FROM discovery_recommendations WHERE run_id=?',(run_id,)).fetchone()[0]
                pref=db.execute('SELECT notifications_enabled FROM discovery_preferences WHERE owner_id=?',(campaign['owner_id'],)).fetchone()
                if fresh and (not pref or pref[0]):
                    db.execute('INSERT INTO discovery_notifications VALUES(?,?,?,?,?,?,NULL)',(uuid.uuid4().hex,campaign['owner_id'],run_id,campaign['id'],fresh,now()))
                next_cursor=dict(cursors)
                for element in elements[:50]:
                    kind=element.get('type');identifier=element.get('id')
                    if kind in ('node','way','relation') and isinstance(identifier,int): next_cursor[kind]=max(next_cursor.get(kind,0),identifier)
                if len(elements)<51: next_cursor={}
                if source_token: next_cursor['_source']=source_token
                # An edit during a running job must not overwrite the new segment's cursor.
                db.execute('UPDATE discovery_campaigns SET cursor_json=? WHERE id=? AND city=? AND category=?',(json.dumps(next_cursor),campaign['id'],campaign['city'],campaign['category']))
                message=f'{len(rows)} estabelecimentos com dados públicos encontrados. Conferência comercial necessária.'+(' Consulta do mapa reutilizada do cache público de 24 horas.' if cached else '')+warning
                if source_state: message+=' Índice OSM local; não foi usada a API Overpass.'+(' Base com mais de 7 dias; atualização recomendada.' if source_state['stale'] else '')
                db.execute('UPDATE discovery_runs SET status=?,found=?,added=?,duplicates=?,enriched=?,finished_at=?,message=? WHERE id=?',('parcial' if warning else 'concluido',len(rows),added,duplicates,enriched,now(),message,run_id));db.commit()
        except Exception:
            with self.connect() as db:
                db.execute("UPDATE discovery_runs SET status='falhou',finished_at=?,message=? WHERE id=?",(now(),'Fonte pública indisponível ou resposta incompleta. Nenhum contato desta rodada foi gravado; tente novamente mais tarde.',run_id));db.commit()
        finally: self.lock.release()

    def scheduler_tick(self):
        if not admin_panel.get('capture_enabled') or not admin_panel.get('capture_scheduler'): return
        with self.connect() as db:
            cutoff=(datetime.now()-timedelta(hours=24)).isoformat(timespec='seconds')
            due=db.execute("SELECT c.id,c.owner_id,c.next_run_at FROM discovery_campaigns c WHERE active=1 AND NOT EXISTS (SELECT 1 FROM user_accounts a WHERE a.id=c.owner_id AND a.is_active=0) AND frequency IN ('daily','scheduled') AND next_run_at<=? AND (SELECT COUNT(*) FROM discovery_runs r WHERE r.owner_id=c.owner_id AND r.started_at>=?)<? ORDER BY next_run_at LIMIT 1",(now(),cutoff,admin_panel.get('capture_runs_account'))).fetchone()
        if due: return self.start(due['owner_id'],due['id'],scheduled_for=due['next_run_at'])

    def start_scheduler(self):
        if self.scheduler_started: return
        self.scheduler_started=True
        with self.connect() as db:
            db.execute("UPDATE discovery_runs SET status='interrompido',finished_at=?,message='Servidor reiniciado; rodada não concluída.' WHERE status='executando'",(now(),));db.commit()
        def loop():
            while True:
                try:
                    self.scheduler_tick()
                except (ValueError,LookupError,sqlite3.Error): pass
                time.sleep(60)
        threading.Thread(target=loop,daemon=True,name='radar-discovery-scheduler').start()
