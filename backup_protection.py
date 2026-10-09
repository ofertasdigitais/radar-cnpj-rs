"""Consistent SQLite snapshots and verified secondary copies; never deletes backups."""
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
import admin_panel

_lock=threading.Lock()


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def status(db_path):
    path=Path(db_path).parent/'backup-status.json'
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {'state':'pending','message':'Nenhuma cópia automática conferida ainda.'}


def save_status(db_path,result):
    path=Path(db_path).parent/'backup-status.json';temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');os.replace(temporary,path)


def create(db_path,connect):
    if not _lock.acquire(blocking=False):raise ValueError('Um backup já está em andamento')
    db_path=Path(db_path)
    try:
        directory=db_path.parent/'admin-backups';directory.mkdir(parents=True,exist_ok=True)
        name='radar-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.sqlite'
        target=directory/name
        with connect() as source,closing(sqlite3.connect(target)) as destination:source.backup(destination)
        with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('A cópia requer revisão; banco original não alterado')
        result={'saved':True,'name':name,'url':'/api/admin/backups/'+name,'bytes':target.stat().st_size,
                'state':'local_only','created_at':datetime.now().isoformat(timespec='seconds'),
                'message':'Backup local íntegro. Configure a segunda cópia.','secondary_verified':False,'sha256':digest(target)}
        destination=admin_panel.get('backup_directory',db_path)
        if destination:
            try:
                folder=Path(destination).resolve();root=Path(__file__).resolve().parent
                if not Path(destination).is_absolute() or folder.is_relative_to(root):raise ValueError('Escolha uma pasta fora do projeto, nunca uma pasta pública')
                folder.mkdir(parents=True,exist_ok=True)
                secondary=folder/name
                if secondary.exists():raise ValueError('Arquivo de destino já existe; não será sobrescrito')
                partial=folder/(name+'.'+uuid.uuid4().hex+'.part')
                try:
                    with target.open('rb') as source,partial.open('xb') as output:shutil.copyfileobj(source,output,1024*1024)
                    if digest(partial)!=result['sha256']:raise ValueError('A segunda cópia não passou na verificação')
                    partial.rename(secondary)
                finally:
                    if partial.exists():partial.unlink()  # Only this operation's incomplete temporary copy.
                result.update(state='verified',secondary_verified=True,message='Backup e segunda cópia conferidos por SHA-256. Destino local não garante cópia fora do computador.')
            except (OSError,ValueError):
                result.update(state='secondary_failed',message='Backup local preservado, mas a segunda cópia falhou. Confira destino, acesso e espaço disponível.')
        save_status(db_path,result);return result
    finally:_lock.release()


def start_scheduler(db_path,connect):
    def loop():
        while True:
            try:
                if admin_panel.get('backup_daily',db_path):
                    last=status(db_path)
                    if str(last.get('created_at',''))[:10]!=datetime.now().date().isoformat():create(db_path,connect)
            except (OSError,sqlite3.Error,ValueError):
                try:save_status(db_path,{'state':'failed','message':'Backup automático falhou. Verifique disco e permissões. A base não foi substituída.'})
                except OSError:pass  # Disk failure must not silently kill future attempts.
            time.sleep(600)
    threading.Thread(target=loop,name='radar-backup-daily',daemon=True).start()
