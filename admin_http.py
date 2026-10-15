"""Admin-only HTTP actions; all writes require session + same-origin + CSRF."""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
import admin_panel as parameters
import security
import help_center
import recovery
import backup_protection


def csrf(handler):
    return hmac.new(security.session_secret().encode(),('admin-csrf:'+str(handler.session_username())).encode(),hashlib.sha256).hexdigest()


def guard(handler, write=False):
    if not handler.session_is_admin():
        handler.send_json({'erro':'Área exclusiva do administrador'},403);return False
    if write and not hmac.compare_digest(handler.headers.get('X-Radar-CSRF',''),csrf(handler)):
        handler.send_json({'erro':'Atualize o painel para renovar a proteção da sessão'},403);return False
    return True


def handle_get(h, context, path):
    if not guard(h):return
    connect=context['connect'];db_path=context['DB']
    if path in ('/admin','/admin/','/admin.html'):
        data=(context['STATIC']/'admin.html').read_bytes()
        h.send_response(200);h.send_header('Content-Type','text/html; charset=utf-8')
        h.send_header('Cache-Control','no-store');h.send_header('Content-Length',str(len(data)))
        h.security_headers();h.end_headers();h.wfile.write(data);return
    if path=='/api/admin/config':
        with connect() as db:result=parameters.snapshot(db,db_path)
        return h.send_json({**result,'csrf':csrf(h),'username':h.session_username()})
    if path=='/api/admin/state':
        with connect() as db:result=parameters.system_state(db,db_path)
        result['backup_protection']=backup_protection.status(db_path)
        discovery=context['discovery'];root=context['ROOT']
        result['local_osm'] = discovery.local_osm.status()
        result['osm_mode'] = parameters.get('capture_osm_mode')
        return h.send_json({**result,'sync':context['SYNC'].snapshot(),'collector_ready':bool(discovery.shutil.which('node') and (root/'collector/node_modules/@crawlee/basic').is_dir())})
    if path=='/api/admin/export':return h.send_json(parameters.export_config(db_path))
    if path=='/api/admin/help':
        with connect() as db:result=help_center.listing(db,True,True)
        return h.send_json(result)
    match=re.fullmatch(r'/api/admin/backups/(radar-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}\.sqlite)',path)
    if match:
        target=db_path.parent/'admin-backups'/match.group(1)
        if not target.is_file():return h.send_error(404)
        h.send_response(200);h.send_header('Content-Type','application/octet-stream')
        h.send_header('Content-Disposition',f'attachment; filename="{target.name}"')
        h.send_header('Cache-Control','no-store');h.send_header('Content-Length',str(target.stat().st_size))
        h.security_headers();h.end_headers()
        with target.open('rb') as source:
            while chunk:=source.read(128*1024):h.wfile.write(chunk)
        return
    return h.send_error(404)


def account_save(h,context,payload):
    if set(payload)-{'id','name','username','email','role','is_active','password'}:raise ValueError('Campos de conta inválidos')
    identifier=payload.get('id');name=str(payload.get('name','')).strip();username=str(payload.get('username','')).strip()
    email=str(payload.get('email','')).strip().lower();role=payload.get('role','vendedor');active=payload.get('is_active',True);password=payload.get('password','')
    if not 2<=len(name)<=100 or not context['USERNAME_PATTERN'].fullmatch(username):raise ValueError('Nome: 2 a 100 caracteres. Usuário: 3 a 40 letras, números, ponto, traço ou sublinhado.')
    if email and (len(email)>180 or not context['EMAIL_PATTERN'].fullmatch(email)):raise ValueError('E-mail inválido')
    if role not in {'admin','vendedor'} or not isinstance(active,bool):raise ValueError('Permissão ou situação inválida')
    if username.casefold()==os.environ.get('RADAR_ADMIN_USER','').casefold():raise ValueError('Este usuário é o administrador do servidor; não pode ser duplicado em outra conta.')
    if not isinstance(password,str) or len(password)>200:raise ValueError('Senha inválida')
    if password or not identifier:
        if len(password)<10 or not re.search(r'[A-Za-zÀ-ÿ]',password) or not re.search(r'\d',password):raise ValueError('Senha: pelo menos 10 caracteres, uma letra e um número')
        salt,digest=context['password_digest'](password)
    actor=h.session_username();bootstrap_actor=bool(h.session_identity() and h.session_identity()[1]);timestamp=datetime.now().isoformat(timespec='seconds')
    with context['connect']() as db:
        db.execute('BEGIN IMMEDIATE')
        if identifier:
            old=db.execute('SELECT * FROM user_accounts WHERE id=?',(identifier,)).fetchone()
            if not old:raise LookupError('Conta não encontrada')
            if not bootstrap_actor and old['username'].casefold()==actor.casefold() and (not active or role!='admin' or username.casefold()!=old['username'].casefold()):raise ValueError('Não é permitido desativar, renomear ou retirar a própria administração')
            admins=db.execute("SELECT COUNT(*) FROM user_accounts WHERE is_active=1 AND lower(role) IN ('admin','administrador','gestor')").fetchone()[0]
            if old['is_active'] and old['role'].lower() in {'admin','administrador','gestor'} and (not active or role!='admin') and admins<=1:raise ValueError('Mantenha pelo menos um administrador ativo')
            if email and db.execute('SELECT 1 FROM user_accounts WHERE email=? COLLATE NOCASE AND id<>?',(email,identifier)).fetchone():raise ValueError('E-mail já utilizado')
            db.execute('UPDATE user_accounts SET name=?,username=?,email=?,role=?,is_active=?,updated_at=? WHERE id=?',(name,username,email,role,int(active),timestamp,identifier))
            if password:db.execute('UPDATE user_accounts SET password_salt=?,password_hash=? WHERE id=?',(salt,digest,identifier))
            if password or username!=old['username'] or active!=bool(old['is_active']) or role!=old['role']:
                parameters.revoke_sessions(db,old['username'])
                if username.casefold()!=old['username'].casefold():parameters.revoke_sessions(db,username)
        else:
            if email and db.execute('SELECT 1 FROM user_accounts WHERE email=? COLLATE NOCASE',(email,)).fetchone():raise ValueError('E-mail já utilizado')
            identifier='conta-'+uuid.uuid4().hex
            db.execute('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(identifier,name,username,email,digest,salt,role,int(active),timestamp,timestamp))
            initials=''.join(part[0] for part in name.split()[:2]).upper()
            db.execute('INSERT INTO sales_profiles(id,name,role,email,initials,color,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',('usuario-'+uuid.uuid4().hex[:12],name,'Vendedor',email,initials,'#b82043',identifier,timestamp,timestamp))
        parameters.audit(db,actor,'account.updated' if payload.get('id') else 'account.created',f'Conta {username}; permissão {role}; ativa {active}'+('; senha redefinida' if password else ''))
    return {'saved':True,'id':identifier}


def handle_post(h,context,path):
    if not guard(h,write=True):return
    try:
        length=int(h.headers.get('Content-Length','0'))
        limit=65536 if path=='/api/admin/help' else 16384
        if not 0<length<=limit:raise ValueError('Solicitação administrativa acima do limite permitido')
        payload=h.read_json_object(length)
        if not isinstance(payload,dict):raise ValueError('Solicitação inválida')
        connect=context['connect'];db_path=context['DB'];actor=h.session_username()
        if path=='/api/admin/config':
            with connect() as db:result=parameters.save(db,actor,payload,db_path)
            return h.send_json(result)
        if path=='/api/admin/accounts':return h.send_json(account_save(h,context,payload))
        if path=='/api/admin/help':
            with connect() as db:result=help_center.save(db,actor,payload)
            return h.send_json(result)
        if path=='/api/admin/recovery-check':
            name=payload.get('name','')
            if not isinstance(name,str) or not re.fullmatch(r'radar-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}\.sqlite',name):raise ValueError('Selecione um backup da lista')
            result=recovery.rehearse(db_path.parent/'admin-backups'/name)
            with connect() as db:parameters.audit(db,actor,'database.recovery_checked','Backup '+name+('; aprovado' if result['ok'] else '; requer revisão'))
            return h.send_json(result)
        if path=='/api/admin/commercial':
            profile_id=payload.get('profile_id');hours=payload.get('contact_sla_hours');days=payload.get('stalled_days')
            inherit=hours is None and days is None
            if not inherit:parameters.validate('contact_sla_hours',hours);parameters.validate('stalled_days',days)
            with connect() as db:
                if not db.execute('SELECT 1 FROM sales_profiles WHERE id=?',(profile_id,)).fetchone():raise LookupError('Responsável não encontrado')
                if inherit:db.execute('DELETE FROM commercial_settings WHERE profile_id=?',(profile_id,))
                else:db.execute('INSERT INTO commercial_settings VALUES(?,?,?) ON CONFLICT(profile_id) DO UPDATE SET contact_sla_hours=excluded.contact_sla_hours,stalled_days=excluded.stalled_days',(profile_id,hours,days))
                parameters.audit(db,actor,'commercial.updated','Responsável '+profile_id+('; padrão geral' if inherit else f'; SLA {hours}h; negociação parada {days} dias'))
            return h.send_json({'saved':True})
        if path=='/api/admin/integrity':
            with connect() as db:
                result=[row[0] for row in db.execute('PRAGMA quick_check')];relations=len(db.execute('PRAGMA foreign_key_check').fetchall())
                parameters.audit(db,actor,'database.checked',f'Integridade: {"ok" if result==["ok"] else "requer revisão"}; vínculos inválidos: {relations}')
            return h.send_json({'ok':result==['ok'] and relations==0,'relations':relations,'message':'Banco íntegro' if result==['ok'] and not relations else 'Banco requer revisão. Nenhuma correção automática executada.'})
        if path=='/api/admin/backup':
            result=backup_protection.create(db_path,connect)
            with connect() as db:parameters.audit(db,actor,'database.backup','Backup criado: '+result['name']+'; '+result['state'])
            return h.send_json(result)
        return h.send_error(404)
    except LookupError as error:return h.send_json({'erro':str(error)},409)
    except sqlite3.IntegrityError:return h.send_json({'erro':'Usuário ou e-mail já utilizado; nenhuma alteração aplicada'},409)
    except (sqlite3.DatabaseError,OSError):return h.send_json({'erro':'Não foi possível verificar o banco ou backup. Nenhuma base foi substituída.'},400)
    except (ValueError,TypeError,AttributeError,UnicodeDecodeError) as error:return h.send_json({'erro':str(error) or 'Solicitação inválida'},400)
