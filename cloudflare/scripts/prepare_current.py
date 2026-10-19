"""Prepare a private migration snapshot; no network and no live DB writes.

An optional existing Windows bootstrap credential becomes a hashed D1 account.
No cleartext password is written or printed. Existing commercial ownership is kept.
"""
import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path
from export_current import export_current, identifier, literal

ROOT=Path(__file__).resolve().parents[2]


def bootstrap_statements(db,username,password):
    username=username.strip()
    if not username or not password: raise ValueError('Bootstrap credential is empty')
    row=db.execute('SELECT id FROM user_accounts WHERE username=? COLLATE NOCASE',(username,)).fetchone()
    owner=row[0] if row else 'admin:'+username.lower()
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,260000).hex()
    stamp=datetime.now().isoformat(timespec='seconds')
    if row:
        sql='UPDATE user_accounts SET role=\'admin\',is_active=1,password_salt='+literal(salt.hex())+',password_hash='+literal(digest)+',updated_at='+literal(stamp)+' WHERE id='+literal(owner)+';'
    else:
        sql='INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES('+','.join(map(literal,[owner,'Administrador Radar',username,'',digest,salt.hex(),'admin',1,stamp,stamp]))+');'
    return owner,sql


def existing_windows_credential(path):
    if os.name!='nt': raise ValueError('Windows credential import requires Windows')
    path=Path(path).resolve(strict=True)
    script="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $c=Import-Clixml -LiteralPath $env:RADAR_MIGRATION_CREDENTIAL; @{username=$c.UserName;password=$c.GetNetworkCredential().Password}|ConvertTo-Json -Compress"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command','-'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=15,env={**os.environ,'RADAR_MIGRATION_CREDENTIAL':str(path)})
    if result.returncode: raise ValueError('Could not decrypt existing administrator credential; no remote operation performed')
    value=json.loads(result.stdout)
    return value['username'],value['password']


def prepare(source,output,credential=None):
    report=export_current(source,output)
    output=Path(output)
    if credential:
        username,password=existing_windows_credential(credential)
        with closing(sqlite3.connect(output/'snapshot.sqlite')) as db:
            owner,sql=bootstrap_statements(db,username,password)
            existed=bool(db.execute('SELECT 1 FROM user_accounts WHERE id=?',(owner,)).fetchone())
        del password
        name='data-bootstrap-admin.sql'
        (output/name).write_text(sql+'\n',encoding='utf-8')
        report['data_files'].append(name)
        report['file_sha256'][name]=hashlib.sha256((output/name).read_bytes()).hexdigest()
        report['expected_remote_counts']=dict(report['counts'])
        report['expected_remote_counts']['user_accounts']+=0 if existed else 1
        report['bootstrap_account_added']=not existed
        report['bootstrap_account_id']=owner
    migration=ROOT/'cloudflare/migrations-current/0001_current.sql'
    # Remote migrations are applied separately. Never replay DDL over a live D1.
    data_only=output/'data-current.sql'
    with data_only.open('w',encoding='utf-8',newline='\n') as handle:
        for name in report['data_files']: handle.write((output/name).read_text(encoding='utf-8')+'\n')
    report['data_only_sha256']=hashlib.sha256(data_only.read_bytes()).hexdigest()
    combined=output/'import-current.sql'
    with combined.open('w',encoding='utf-8',newline='\n') as handle:
        handle.write(migration.read_text(encoding='utf-8')+'\n')
        for name in report['data_files']: handle.write((output/name).read_text(encoding='utf-8')+'\n')
    report['combined_file_sha256']=hashlib.sha256(combined.read_bytes()).hexdigest()
    report['migration_sha256']=hashlib.sha256(migration.read_bytes()).hexdigest()
    (output/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # A fresh cloud-only signing secret; never reuse the local session secret.
    secretfile=output/'cloudflare-secrets.json'
    secretfile.write_text(json.dumps({'SESSION_SECRET':secrets.token_urlsafe(48),'RECEITA_IMPORT_SECRET':secrets.token_urlsafe(48)}),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bootstrap-credential',type=Path)
    args=parser.parse_args();result=prepare(args.source,args.output,args.bootstrap_credential)
    print(json.dumps({'source_tables':len(result['counts']),'counts':result.get('expected_remote_counts',result['counts']),
        'snapshot_sha256':result['snapshot_sha256'],'combined_file_sha256':result['combined_file_sha256'],
        'bootstrap_account_added':result.get('bootstrap_account_added',False),'remote_operations':False},indent=2))
