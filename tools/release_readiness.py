"""Read-only release gate. Never deploys, initializes the app or mutates databases."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from db_qa import audit, database_ready

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=('user_accounts','sales_profiles','sales_profile_leads','sales_lead_history',
          'account_company_state','message_templates','contact_suppression','commercial_archive',
          'discovery_campaigns','discovery_runs','discovery_recommendations','discovery_notifications',
          'prospect_inbox','help_articles','admin_config')


def cloudflare_gaps(database):
    with closing(sqlite3.connect(':memory:')) as target, closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        for migration in sorted((ROOT/'cloudflare'/'migrations').glob('*.sql')):
            target.executescript(migration.read_text(encoding='utf-8'))
        gaps=[]
        for table in REQUIRED:
            actual={row[1] for row in source.execute('PRAGMA table_info('+table+')')}
            remote={row[1] for row in target.execute('PRAGMA table_info('+table+')')}
            if actual and not remote:gaps.append({'table':table,'issue':'missing_table'})
            elif actual-remote:gaps.append({'table':table,'issue':'missing_columns','columns':sorted(actual-remote)})
        return gaps


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,default=Path(os.environ.get('RADAR_DATA_DIR',str(ROOT/'data')))/'radar.db')
    parser.add_argument('--cloudflare',action='store_true');args=parser.parse_args()
    result=audit(args.db)
    result['local_integrity_ready']=database_ready(result)
    if args.cloudflare:
        result['cloudflare_schema_gaps']=cloudflare_gaps(args.db)
        # Schema parity alone cannot prove route, runtime, owner or scheduler parity.
        result['cloudflare_ready']=False
        result['cloudflare_blockers']=['API/admin/FAQ/BI/captação e exportador modernos precisam de paridade funcional e testes de migração.','Crawlee e índice OSM local precisam de coletor externo; não são transferidos ao Worker por copiar assets.','Conta, D1 de destino, segredo e orçamento não foram validados.']
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if args.cloudflare else (0 if result['local_integrity_ready'] else 1)


if __name__=='__main__':raise SystemExit(main())
