"""Restore rehearsal into a disposable database. Never replaces the live file."""
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

def fingerprint(db,table):
    safe='"'+table.replace('"','""')+'"';digest=hashlib.sha256();count=0
    columns=[row[1] for row in db.execute('PRAGMA table_info('+safe+')')]
    order=','.join('"'+key.replace('"','""')+'"' for key in columns)
    for row in db.execute('SELECT * FROM '+safe+' ORDER BY '+order):
        digest.update(json.dumps(row,ensure_ascii=False,separators=(',',':'),default=lambda x:x.hex()).encode());digest.update(b'\n');count+=1
    return {'rows':count,'sha256':digest.hexdigest()}

def rehearse(path):
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('Backup não encontrado')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source:
        # Validate before copying; a backup with broken relations must not pass.
        source.execute('BEGIN')
        integrity=[r[0] for r in source.execute('PRAGMA quick_check')]
        if integrity!=['ok']:return {'ok':False,'message':'Backup corrompido; nenhuma base foi substituída.'}
        tables=[r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not {'companies','user_accounts','sales_profile_leads','sales_profiles'}.issubset(tables):raise ValueError('Arquivo não contém a estrutura do Radar')
        with tempfile.TemporaryDirectory(prefix='radar-recovery-') as directory:
            with closing(sqlite3.connect(Path(directory)/'restored.sqlite')) as restored:
                source.backup(restored)
                integrity=[r[0] for r in restored.execute('PRAGMA integrity_check')]
                relations=len(restored.execute('PRAGMA foreign_key_check').fetchall())
                comparison={table:fingerprint(source,table)==fingerprint(restored,table) for table in tables}
                counts={table:restored.execute('SELECT COUNT(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in ('companies','user_accounts','sales_profiles','sales_profile_leads','sales_lead_history','prospect_inbox','help_articles') if table in tables}
                ok=integrity==['ok'] and relations==0 and all(comparison.values())
    return {'ok':ok,'relations':relations,'tables_verified':len(comparison),'counts':counts,
            'message':'Recuperação ensaiada em cópia temporária: registros e integridade conferidos. Produção não alterada.' if ok else 'Backup requer revisão. Produção não alterada.'}
