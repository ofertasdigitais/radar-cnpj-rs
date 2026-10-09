"""Real local-index smoke test; all commercial writes use a temporary test DB."""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
import discovery
import local_osm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-web', action='store_true', help='Consulta também sites comerciais públicos, respeitando robots.txt.')
    parser.add_argument('--sites', type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    state = local_osm.status()
    if not state['ready']:
        raise RuntimeError('Prepare o índice OSM local antes de validar.')
    os.environ.update(RADAR_ADMIN_USER='', RADAR_ADMIN_PASSWORD='', RADAR_ENV='')
    temporary_root = ROOT / 'tmp'
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='capture-smoke-', dir=temporary_root) as folder:
        app.DB = Path(folder) / 'test.sqlite'
        app.init_db()
        with app.connect() as db:
            campaign = discovery.save_campaign(db, 'smoke-private', dict(
                name='Validação OSM real', city='Porto Alegre', category='restaurantes',
                frequency='manual', enrich_websites=args.live_web))
        def bounded_enrichment(rows):
            return discovery.enrich_sites([row for row in rows if row['row']['website']][:args.sites])
        manager = discovery.DiscoveryManager(app.connect, enricher=bounded_enrichment)
        identifier = manager.start('smoke-private', campaign)
        deadline = time.monotonic() + 300
        while manager.lock.locked():
            if time.monotonic() >= deadline:
                raise TimeoutError('Rodada excedeu o tempo de validação.')
            time.sleep(.1)
        with app.connect() as db:
            run = dict(db.execute('SELECT * FROM discovery_runs WHERE id=?', (identifier,)).fetchone())
            assert run['status'] in ('concluido', 'parcial'), run['message']
            assert run['found'] > 0 and run['added'] > 0
            assert discovery.snapshot(db, 'different-account')['total'] == 0
            assert db.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 0
            sources = [json.loads(row[0]) for row in db.execute('SELECT metadata_json FROM discovery_sources')]
            assert all(row.get('source_backend') == 'OSM local · Geofabrik' for row in sources)
            print(json.dumps(dict(index_records=state['count'], municipalities=len(state['cities']),
                found=run['found'], added=run['added'], websites_consulted=run['enriched'],
                live_web=args.live_web, result=run['status'],
                website_statuses={value: sum(row['enrichment_status'] == value for row in sources)
                                  for value in sorted({row['enrichment_status'] for row in sources})},
                private_accounts=True, official_companies_untouched=True), ensure_ascii=True))


if __name__ == '__main__':
    main()
