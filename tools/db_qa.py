"""Read-only SQLite integrity audit; optional explicit, consistent backup."""
import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def database_ready(result):
    """A diagnostic is not a pass unless every required invariant was checked."""
    return result.get('integrity_check') == ['ok'] and all(
        result.get(key) == 0 for key in (
            'foreign_key_violations', 'duplicate_company_keys',
            'orphan_sales_leads', 'profiles_without_owner',
        )
    )


def audit(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result={'database_bytes':path.stat().st_size,'integrity_check':[x[0] for x in db.execute('PRAGMA integrity_check')],
                'foreign_key_violations':len(db.execute('PRAGMA foreign_key_check').fetchall()),
                'journal_mode':db.execute('PRAGMA journal_mode').fetchone()[0],
                'counts':{name:db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('companies','user_accounts','sales_profiles','sales_profile_leads','sales_lead_history','commercial_archive','prospect_inbox') if name in tables}}
        result['duplicate_company_keys']=db.execute('SELECT COUNT(*) FROM (SELECT cnpj FROM companies GROUP BY cnpj HAVING COUNT(*)>1)').fetchone()[0]
        result['orphan_sales_leads']=db.execute('''SELECT COUNT(*) FROM sales_profile_leads s LEFT JOIN companies c ON c.cnpj=s.cnpj LEFT JOIN sales_profiles p ON p.id=s.profile_id WHERE c.cnpj IS NULL OR p.id IS NULL''').fetchone()[0]
        result['profiles_without_owner']=db.execute("SELECT COUNT(*) FROM sales_profiles WHERE TRIM(COALESCE(owner_id,''))='' ").fetchone()[0]
        result['cross_profile_active_companies']=db.execute("SELECT COUNT(*) FROM (SELECT cnpj FROM sales_profile_leads WHERE lead_status NOT IN ('convertido','descartado','concluido') GROUP BY cnpj HAVING COUNT(DISTINCT profile_id)>1)").fetchone()[0]
        result['query_plans']={}
        for name,query in [('history','SELECT * FROM sales_lead_history WHERE profile_id=? ORDER BY created_at DESC LIMIT 50'),('seller_leads','SELECT * FROM sales_profile_leads WHERE profile_id=? ORDER BY updated_at DESC LIMIT 60')]:
            result['query_plans'][name]=[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+query,('qa',))]
        start=time.perf_counter();db.execute('SELECT COUNT(*) FROM companies WHERE uf=?',('RS',)).fetchone()
        result['public_count_ms']=round((time.perf_counter()-start)*1000,2)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',default='data/radar.db');parser.add_argument('--backup');args=parser.parse_args()
    path=Path(args.db)
    if args.backup:
        target=Path(args.backup).resolve()
        if target.exists():raise SystemExit('Backup já existe; não será sobrescrito.')
        target.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(target)) as output:source.backup(output)
        print('Backup consistente criado: '+str(target))
    print(json.dumps(audit(path),ensure_ascii=False,indent=2))
