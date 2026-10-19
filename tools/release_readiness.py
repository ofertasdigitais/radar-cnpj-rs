"""Read-only release gate. Never deploys, initializes the app or mutates databases."""
import argparse
import json
import os
import sqlite3
import subprocess
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
        for migration in sorted((ROOT/'cloudflare'/'migrations-current').glob('*.sql')):
            target.executescript(migration.read_text(encoding='utf-8'))
        gaps=[]
        for table, in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            actual={row[1] for row in source.execute('PRAGMA table_info('+table+')')}
            remote={row[1] for row in target.execute('PRAGMA table_info('+table+')')}
            if actual and not remote:gaps.append({'table':table,'issue':'missing_table'})
            elif actual-remote:gaps.append({'table':table,'issue':'missing_columns','columns':sorted(actual-remote)})
        return gaps


def cloudflare_checks():
    """Local preflight only: no account API, live DB writes, or deploy side effects."""
    config=json.loads((ROOT/'cloudflare/wrangler.jsonc').read_text(encoding='utf-8'))
    expected_db={'binding':'DB','database_name':'radar-cnpj-rs',
                 'database_id':'1f91e449-5b76-4daa-9989-afff59545456','migrations_dir':'migrations-current'}
    blockers=[]
    if config.get('name')!='radar-cnpj-rs' or config.get('account_id')!='4e340bbc4dc493ac0e2f86cc0594a225':
        blockers.append('Conta ou Worker diferente do destino Radar aprovado.')
    if config.get('d1_databases')!=[expected_db]: blockers.append('Binding D1 diferente do banco exclusivo Radar aprovado.')
    if config.get('main')!='src/worker-current.ts' or config.get('assets',{}).get('run_worker_first') is not True:
        blockers.append('Entrypoint atual ou proteção dos assets ausente.')
    if 'nodejs_compat' not in config.get('compatibility_flags',[]): blockers.append('Compatibilidade criptográfica ausente.')
    for path in ('src/sales.ts','src/admin-current.ts','src/discovery-current.ts','src/receita-current.ts','src/report-current.ts'):
        if not (ROOT/'cloudflare'/path).is_file(): blockers.append('Módulo atual ausente: '+path)
    if blockers: return blockers,[]
    npm='npm.cmd' if os.name=='nt' else 'npm'
    results=[]
    for command in ([npm,'run','check'],[npm,'test']):
        run=subprocess.run(command,cwd=ROOT/'cloudflare',capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        results.append({'command':' '.join(command),'exit_code':run.returncode})
        if run.returncode:
            blockers.append('Falha na validação: '+' '.join(command))
            print(run.stdout[-12000:]+run.stderr[-6000:])
    return blockers,results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,default=Path(os.environ.get('RADAR_DATA_DIR',str(ROOT/'data')))/'radar.db')
    parser.add_argument('--cloudflare',action='store_true');args=parser.parse_args()
    result=audit(args.db)
    result['local_integrity_ready']=database_ready(result)
    if args.cloudflare:
        result['cloudflare_schema_gaps']=cloudflare_gaps(args.db)
        blockers,checks=cloudflare_checks()
        if result['cloudflare_schema_gaps']: blockers.append('Esquema D1 não preserva todas as tabelas e colunas atuais.')
        if not result['local_integrity_ready']: blockers.append('Integridade do banco de origem não validada.')
        result['cloudflare_ready']=not blockers
        result['cloudflare_blockers']=blockers
        result['cloudflare_checks']=checks
        result['scope']='Preflight local. Plano, carga remota, segredos e URL precisam de verificação no lançamento.'
        result['cloudflare_limits']=['Crawlee e o índice OSM em disco não executam no Worker; captação usa Overpass público.','Backup Windows não executa no D1; usar exportação/Time Travel e ensaio isolado.','Receita mensal usa GitHub Actions público; exige dois segredos exclusivos do Radar e workflow ativo.']
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return (0 if result['cloudflare_ready'] else 2) if args.cloudflare else (0 if result['local_integrity_ready'] else 1)


if __name__=='__main__':raise SystemExit(main())
