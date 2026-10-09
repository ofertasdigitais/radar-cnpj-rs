"""Persistent, validated admin parameters. No network calls or paid activation."""
import base64
import ctypes
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

FIELDS = {
 'site_name': dict(group='general', label='Nome do site', type='text', default='Radar CNPJ', max=80),
 'copyright': dict(group='general', label='Rodapé / copyright', type='text', default='© {ano} Radar CNPJ · Todos os direitos reservados.', max=180),
 'default_theme': dict(group='general', label='Tema inicial', type='select', default='dark', options={'dark':'Escuro','light':'Claro'}),
 'animations': dict(group='general', label='Animações e transições CSS', type='bool', default=True, help='Controla os efeitos da interface; não interrompe carregamentos ou gráficos em JavaScript.'),
 'max_columns': dict(group='general', label='Limite de colunas', type='int', default=10, min=1, max=10, help='A tela continua limitando as colunas à largura disponível.'),
 'registration': dict(group='general', label='Cadastro público de contas', type='select', default='inherit', options={'inherit':'Manter regra atual','off':'Desativado','on':'Permitido'}, help='Contas cadastradas publicamente sempre começam como vendedores.'),
 'test_leads': dict(group='general', label='Permitir criação de leads de teste', type='bool', default=True),
 'contact_sla_hours': dict(group='commercial', label='Prazo padrão do primeiro contato (horas)', type='int', default=48, min=1, max=720, help='Usado quando o responsável ainda não tem um prazo individual.'),
 'stalled_days': dict(group='commercial', label='Negociação parada após (dias)', type='int', default=7, min=1, max=365),
 'report_title': dict(group='commercial', label='Título padrão do relatório PDF', type='text', default='Relatório comercial', max=100),
 'report_footer': dict(group='commercial', label='Rodapé do relatório PDF', type='text', default='Uso interno · Dados privados do responsável', max=120),
 'capture_enabled': dict(group='capture', label='Permitir coleta OpenStreetMap', type='bool', default=True),
 'capture_osm_mode': dict(group='capture', label='Fonte gratuita OpenStreetMap', type='select', default='local', options={'local':'Índice local · sem depender do Overpass','overpass':'Overpass público · disponibilidade limitada'}, help='Local não faz consultas à API pública. Exige preparar o índice regional local.'),
 'osm_local_auto_update': dict(group='capture', label='Atualizar base OSM local semanalmente', type='bool', default=False, help='Baixa arquivo público da Região Sul (~406 MB) e reconstrói o índice local. Exige espaço em disco e servidor ligado; nenhuma assinatura.'),
 'capture_scheduler': dict(group='capture', label='Executar campanhas agendadas automaticamente', type='bool', default=True, env='RADAR_DISCOVERY_AUTO', help='Campanhas ativas com horários definidos ou frequência diária. Exige servidor ligado e respeita limites por conta e globais.'),
 'enrichment_enabled': dict(group='capture', label='Permitir enriquecimento Crawlee', type='bool', default=True, help='Só completa sites públicos quando também habilitado na campanha.'),
 'capture_runs_account': dict(group='capture', label='Rodadas por conta / 24 horas', type='int', default=6, min=1, max=6),
 'capture_runs_global': dict(group='capture', label='Rodadas totais / 24 horas', type='int', default=30, min=1, max=30),
 'capture_sites': dict(group='capture', label='Sites por rodada', type='int', default=10, min=1, max=10),
 'sync_scheduler': dict(group='system', label='Verificar atualização mensal da Receita', type='bool', default=True, env='RADAR_AUTO_SYNC', help='A desativação pausa novas verificações; não interrompe uma carga já iniciada.'),
 'backup_daily': dict(group='system', label='Backup automático diário', type='bool', default=True, help='Executado com o servidor ligado; não apaga backups antigos.'),
 'backup_directory': dict(group='system', label='Pasta da segunda cópia de backup', type='path', default='', max=500, help='Pasta absoluta fora do projeto. Pasta no mesmo disco não protege contra perda do computador. Para proteção externa, use pasta de rede ou sincronizada e confira a sincronização.'),
 'serpro_visible': dict(group='integrations', label='Mostrar monitor Serpro no Radar', type='bool', default=False, help='Visibilidade não ativa consultas. Serpro permanece bloqueado para evitar custos.'),
 'serpro_environment': dict(group='integrations', label='Ambiente Serpro', type='select', default='homologacao', env='RADAR_SERPRO_ENV', options={'homologacao':'Homologação','producao':'Produção'}),
 'serpro_daily_limit': dict(group='integrations', label='Limite técnico Serpro / dia', type='int', default=50, min=1, max=50, env='RADAR_SERPRO_DAILY_LIMIT', help='Este número é uma trava do Radar. NÃO representa uma franquia gratuita do Serpro.'),
 'base44_endpoint': dict(group='integrations', label='URL de recebimento do CRM Base44', type='url', default='', max=500, env='RADAR_BASE44_ENDPOINT', help='Somente HTTPS em domínio Base44. Salvar não envia leads nem ativa assinatura.'),
 'base44_secret': dict(group='integrations', label='Segredo compartilhado Base44', type='secret', default='', min=32, max=500, env='RADAR_BASE44_SECRET'),
 'serpro_key': dict(group='integrations', label='Serpro · Consumer Key', type='secret', default='', min=8, max=500, env='RADAR_SERPRO_CONSUMER_KEY'),
 'serpro_secret': dict(group='integrations', label='Serpro · Consumer Secret', type='secret', default='', min=8, max=500, env='RADAR_SERPRO_CONSUMER_SECRET'),
 'serpro_cpf': dict(group='integrations', label='Serpro · CPF responsável', type='secret', default='', min=11, max=11, env='RADAR_SERPRO_USER_CPF'),
}
_path = None
_cache = {}
_lock = threading.RLock()


def configure(path):
    global _path
    _path = Path(path)


def ensure_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS admin_parameters (
      key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS admin_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
      INSERT OR IGNORE INTO admin_revision VALUES(1,0);
      CREATE TABLE IF NOT EXISTS admin_session_revisions (
      username TEXT PRIMARY KEY COLLATE NOCASE, revision INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS admin_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
      detail TEXT NOT NULL, created_at TEXT NOT NULL);''')


def _protect(value, decrypt=False):
    # DPAPI binds ciphertext to the Windows user. Unix deployments must use env secrets.
    if os.name != 'nt':
        raise ValueError('Neste servidor, configure segredos pelas variáveis de ambiente; gravação protegida disponível somente no Windows.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError('Não foi possível proteger a chave no servidor.')
    try:
        data = ctypes.string_at(output.data, output.size)
        return data.decode('utf-8') if decrypt else base64.b64encode(data).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def _stored(path=None):
    target = Path(path or _path) if (path or _path) else None
    if not target or not target.is_file(): return {}
    key = str(target.resolve())
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic()-cached[0] < 1: return dict(cached[1])
        try:
            with closing(sqlite3.connect(target.as_uri()+'?mode=ro', uri=True)) as db:
                result = {k: json.loads(v) for k,v in db.execute('SELECT key,value FROM admin_parameters')}
        except sqlite3.Error: return {}
        _cache[key] = (time.monotonic(), result)
        return dict(result)


def get(key, db_path=None):
    spec = FIELDS[key]
    if spec['type'] == 'secret' and os.environ.get(spec.get('env','')):
        return os.environ[spec['env']].strip()
    stored = _stored(db_path)
    if key in stored:
        if spec['type'] == 'secret':
            try: return _protect(stored[key], decrypt=True) if stored[key] else ''
            except (ValueError, OSError): return ''
        return stored[key]
    raw = os.environ.get(spec.get('env',''))
    if raw is not None:
        try:
            if spec['type'] == 'bool': return raw.lower() not in {'0','false'}
            return validate(key, int(raw) if spec['type']=='int' else raw)
        except (ValueError, TypeError): pass
    return spec['default']


def validate(key, value):
    spec = FIELDS[key]; kind = spec['type']
    if kind == 'bool':
        if not isinstance(value, bool): raise ValueError(spec['label']+': opção inválida')
    elif kind == 'int':
        if isinstance(value,bool) or not isinstance(value,int) or not spec['min']<=value<=spec['max']:
            raise ValueError(f"{spec['label']}: {spec['min']} a {spec['max']}")
    elif not isinstance(value,str): raise ValueError(spec['label']+': texto inválido')
    else:
        value = value.strip()
        if len(value)>spec.get('max',500) or re.search(r'[\x00-\x1f]',value): raise ValueError(spec['label']+': tamanho ou caracteres inválidos')
        if kind == 'select' and value not in spec['options']: raise ValueError(spec['label']+': opção inválida')
        if kind == 'text' and not value: raise ValueError(spec['label']+': preencha o campo')
        if kind == 'path' and value and not Path(value).is_absolute(): raise ValueError('Informe o caminho absoluto da pasta de backup')
        if kind == 'secret' and value and len(value)<spec['min']: raise ValueError(spec['label']+f": mínimo de {spec['min']} caracteres")
        if key == 'serpro_cpf' and value and not re.fullmatch(r'\d{11}',value): raise ValueError('CPF: informe 11 dígitos')
        if kind == 'url' and value:
            try:
                parsed=urlsplit(value); host=(parsed.hostname or '').lower()
                valid=parsed.scheme=='https' and not parsed.username and not parsed.password and not parsed.fragment and not parsed.query and parsed.port in (None,443) and (host=='base44.app' or host.endswith('.base44.app') or host=='base44.com' or host.endswith('.base44.com'))
            except ValueError: valid=False
            if not valid: raise ValueError('Informe uma URL HTTPS Base44, sem senha, fragmento ou parâmetros.')
    return value


def revision(db): return db.execute('SELECT revision FROM admin_revision WHERE id=1').fetchone()[0]


def session_payload(db, username, payload):
    row=db.execute('SELECT revision FROM admin_session_revisions WHERE username=? COLLATE NOCASE',(username,)).fetchone()
    # Revision zero preserves sessions issued before the admin panel migration.
    return payload+'|revision:'+str(row[0]) if row and row[0] else payload


def revoke_sessions(db, username):
    db.execute('''INSERT INTO admin_session_revisions(username,revision) VALUES(?,1)
        ON CONFLICT(username) DO UPDATE SET revision=revision+1''',(username,))


def audit(db, actor, action, detail):
    db.execute('INSERT INTO admin_audit(actor,action,detail,created_at) VALUES(?,?,?,?)',
               (actor,action,detail,datetime.now().isoformat(timespec='seconds')))


def save(db, actor, payload, db_path=None):
    if not isinstance(payload,dict) or set(payload)-{'revision','values'}: raise ValueError('Parâmetros inválidos')
    values=payload.get('values')
    if not isinstance(values,dict) or not values or len(values)>len(FIELDS) or set(values)-set(FIELDS): raise ValueError('Campos de parâmetros inválidos')
    if type(payload.get('revision')) is not int: raise ValueError('Informe a revisão carregada')
    clean={key:validate(key,value) for key,value in values.items()}
    for key,value in list(clean.items()):
        if FIELDS[key]['type']=='secret':
            if os.environ.get(FIELDS[key]['env']): raise ValueError('Esta chave é gerenciada pelo ambiente do servidor.')
            if value: clean[key]=_protect(value)
    db.execute('BEGIN IMMEDIATE')
    if revision(db)!=payload['revision']: raise LookupError('Outra configuração foi salva. Atualize o painel antes de salvar.')
    timestamp=datetime.now().isoformat(timespec='seconds')
    for key,value in clean.items():
        db.execute('INSERT INTO admin_parameters VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',(key,json.dumps(value,ensure_ascii=False),timestamp))
    db.execute('UPDATE admin_revision SET revision=revision+1 WHERE id=1')
    audit(db,actor,'parameters.updated',', '.join(FIELDS[key]['label'] for key in clean))
    db.commit()
    with _lock: _cache.clear()
    return {'saved':True,'revision':revision(db)}


def snapshot(db, db_path):
    values={}; fields=[]
    for key,spec in FIELDS.items():
        field={'key':key,**{k:v for k,v in spec.items() if k not in {'env','default'}}}
        if spec['type']=='secret':
            field.update(configured=bool(get(key,db_path)),readonly=bool(os.environ.get(spec['env'])) or os.name!='nt',storage='environment' if os.environ.get(spec['env']) else 'DPAPI' if os.name=='nt' else 'environment-only')
        else: values[key]=get(key,db_path)
        fields.append(field)
    return {'revision':revision(db),'values':values,'fields':fields,'free_only':True,
            'base44_status':'Destino configurado; receptor e sincronização ainda não validados' if values['base44_endpoint'] else 'Não conectado',
            'serpro_status':'Oculto / consultas desativadas — custos não autorizados'}


def public_config(db_path):
    return {key:get(key,db_path) for key in ('site_name','copyright','default_theme','animations','max_columns','test_leads','serpro_visible')}


def export_config(db_path):
    return {'format':'radar-admin-parameters','version':1,
            'values':{key:get(key,db_path) for key,spec in FIELDS.items() if spec['type']!='secret'},
            'note':'Sem chaves, senhas ou dados de leads. Não é backup do banco.'}


def system_state(db, db_path):
    counts={name:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for name,table in
            [('companies','companies'),('accounts','user_accounts'),('profiles','sales_profiles'),('leads','sales_profile_leads'),('campaigns','discovery_campaigns')]}
    logs=[dict(row) for row in db.execute('SELECT * FROM admin_audit ORDER BY id DESC LIMIT 80')]
    accounts=[dict(row) for row in db.execute('''SELECT a.id,a.name,a.username,a.email,a.role,a.is_active,a.last_login_at,
      COUNT(DISTINCT p.id) profiles,COUNT(l.cnpj) leads FROM user_accounts a
      LEFT JOIN sales_profiles p ON p.owner_id=a.id LEFT JOIN sales_profile_leads l ON l.profile_id=p.id GROUP BY a.id ORDER BY a.name''')]
    profiles=[dict(row) for row in db.execute('''SELECT p.id,p.name,p.owner_id,c.contact_sla_hours,c.stalled_days FROM sales_profiles p
      LEFT JOIN commercial_settings c ON c.profile_id=p.id ORDER BY p.name''')]
    return {'counts':counts,'accounts':accounts,'profiles':profiles,'audit':logs,
            'db_bytes':Path(db_path).stat().st_size,'environment':'production' if os.environ.get('RADAR_ENV')=='production' else 'local',
            'secrets_storage':'Windows DPAPI (usuário do servidor)' if os.name=='nt' else 'Variáveis de ambiente',
            'session_protected':len(os.environ.get('RADAR_SESSION_SECRET',''))>=32,
            'backups':[{'name':p.name,'bytes':p.stat().st_size,'created_at':datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')} for p in sorted((Path(db_path).parent/'admin-backups').glob('radar-*.sqlite'),reverse=True)[:10]]}
