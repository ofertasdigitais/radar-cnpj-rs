import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import discovery
import local_osm


def fixture(path, count=3):
    nodes = ''.join(f'<node id="{i+100}" lat="-30.05" lon="-51.2"><tag k="name" v="Loja {i}"/><tag k="amenity" v="restaurant"/><tag k="website" v="https://example.com"/></node>' for i in range(count))
    path.write_text('''<osm version="0.6" generator="radar-isolated-test">
      <node id="1" lat="-30.2" lon="-51.3"/><node id="2" lat="-30.2" lon="-51.1"/>
      <node id="3" lat="-30.0" lon="-51.1"/><node id="4" lat="-30.0" lon="-51.3"/>
      <node id="5" lat="-30.2" lon="-50.9"/><node id="6" lat="-30.0" lon="-50.9"/>
      <node id="11" lat="-30.12" lon="-51.25"/><node id="12" lat="-30.12" lon="-51.22"/>
      <node id="13" lat="-30.10" lon="-51.22"/><node id="14" lat="-30.10" lon="-51.25"/>
      ''' + nodes + '''
      <node id="500" lat="-30.05" lon="-51.0"><tag k="name" v="Endereço enganoso"/><tag k="amenity" v="restaurant"/><tag k="addr:city" v="Porto Alegre"/></node>
      <node id="501" lat="-27.0" lon="-51.2"><tag k="name" v="Fora do RS"/><tag k="amenity" v="restaurant"/><tag k="addr:city" v="Porto Alegre"/></node>
      <node id="502" lat="-30.05" lon="-51.1"><tag k="name" v="Na divisa"/><tag k="amenity" v="restaurant"/></node>
      <way id="1001"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
      <way id="1002"><nd ref="2"/><nd ref="5"/><nd ref="6"/><nd ref="3"/><nd ref="2"/></way>
      <way id="1100"><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
        <tag k="name" v="Café QA"/><tag k="amenity" v="cafe"/></way>
      <relation id="2001"><member type="way" ref="1001" role="outer"/><tag k="type" v="boundary"/>
        <tag k="boundary" v="administrative"/><tag k="admin_level" v="8"/><tag k="IBGE:GEOCODIGO" v="4314902"/><tag k="name" v="Porto Alegre"/></relation>
      <relation id="2002"><member type="way" ref="1002" role="outer"/><tag k="type" v="boundary"/>
        <tag k="boundary" v="administrative"/><tag k="admin_level" v="8"/><tag k="ref:IBGE" v="4318705"/><tag k="name" v="Cidade Vizinha"/></relation>
      </osm>''', encoding='utf-8')


class LocalOsmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'catalog'
        self.source = self.root / 'fixture.osm'
        fixture(self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        return local_osm.update(directory=self.directory, source_file=self.source, minimum_cities=2)

    def test_real_osmium_geometry_and_city_not_postal_text(self):
        meta = self.prepare()
        self.assertEqual(meta['cities'], 2)
        self.assertEqual(meta['stats']['ambiguous'], 1)
        self.assertEqual(meta['stats']['unassigned'], 1)
        state = local_osm.status(self.directory)
        self.assertTrue(state['ready'])
        self.assertTrue(state['free'])
        self.assertEqual(state['count'], 5)
        rows = local_osm.fetch('PORTO ALEGRE', 'restaurantes', directory=self.directory)
        self.assertEqual([r['id'] for r in rows], [100, 101, 102])
        neighbor = local_osm.fetch('Cidade Vizinha', 'restaurantes', directory=self.directory)
        self.assertEqual([r['id'] for r in neighbor], [500])
        cafes = local_osm.fetch('Porto Alegre', 'cafeterias', directory=self.directory)
        self.assertEqual(cafes[0]['type'], 'way')
        self.assertEqual(cafes[0]['id'], 1100)
        self.assertEqual(local_osm.city_key(' São  Sebastião '), 'sao sebastiao')
        with self.assertRaises(ValueError):
            local_osm.fetch('Cidade inexistente', 'restaurantes', directory=self.directory)

    def test_cursor_all_records_no_skip_and_category(self):
        fixture(self.source, count=75)
        self.prepare()
        page = local_osm.fetch('Porto Alegre', 'restaurantes', directory=self.directory)
        self.assertEqual(len(page), 51)
        second = local_osm.fetch('Porto Alegre', 'restaurantes', {'node': page[49]['id']}, directory=self.directory)
        self.assertEqual(len(second), 25)
        self.assertEqual(len({r['id'] for r in page[:50] + second}), 75)
        self.assertEqual(local_osm.fetch('Porto Alegre', 'dentistas', directory=self.directory), [])

    def test_failure_preserves_catalog_and_foreign_file(self):
        self.prepare()
        pointer = (self.directory / 'CURRENT.json').read_bytes()
        original = self.source.read_bytes()
        with patch.object(local_osm, 'build_index', side_effect=ValueError('invalid source')):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertEqual(pointer, (self.directory / 'CURRENT.json').read_bytes())
        self.assertEqual(original, self.source.read_bytes())
        self.assertTrue(local_osm.status(self.directory)['ready'])
        self.assertEqual(local_osm.status(self.directory)['update']['status'], 'falhou')
        self.assertFalse(list(self.directory.glob('staging-*')))

    def test_insufficient_boundaries_never_published(self):
        with self.assertRaises(ValueError):
            local_osm.update(directory=self.directory, source_file=self.source, minimum_cities=3)
        self.assertFalse((self.directory / 'CURRENT.json').exists())

    def test_pointer_path_traversal_readonly_and_lock(self):
        self.prepare()
        path, _ = local_osm._catalog(self.directory)
        with local_osm.readonly(path) as db, self.assertRaises(sqlite3.OperationalError):
            db.execute('DELETE FROM cities')
        with local_osm.update_lock(self.directory):
            with self.assertRaises(RuntimeError):
                self.prepare()
        local_osm._atomic_json(self.directory / 'CURRENT.json', {'schema': 1, 'file': '../radar.db'})
        self.assertFalse(local_osm.status(self.directory)['ready'])
        with self.assertRaises(ValueError):
            local_osm.fetch('Porto Alegre', 'restaurantes', directory=self.directory)

    def test_download_partial_limits_and_external_redirect(self):
        class Response(io.BytesIO):
            headers = {'Content-Length': '20'}
        target = self.root / 'partial.pbf'
        with self.assertRaises(ValueError):
            local_osm.download(target, opener=lambda *a, **k: Response(b'incomplete'))
        self.assertFalse(target.exists())
        with self.assertRaises(ValueError):
            local_osm.download(target, opener=lambda *a, **k: Response(b'data'), max_bytes=5)
        self.assertFalse(target.exists())
        with self.assertRaises(ValueError):
            local_osm.FixedSourceRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/')

    def test_local_provider_never_uses_overpass_even_when_unavailable(self):
        with patch.object(discovery.admin_panel, 'get', return_value='local'), patch.object(discovery, 'fetch_osm') as remote:
            with patch.object(local_osm, 'fetch', return_value=['local']):
                self.assertEqual(discovery.fetch_source('Porto Alegre', 'restaurantes'), ['local'])
            with patch.object(local_osm, 'fetch', side_effect=ValueError('not ready')):
                with self.assertRaises(ValueError):
                    discovery.fetch_source('Porto Alegre', 'restaurantes')
            remote.assert_not_called()

    def test_default_campaign_full_pipeline_private_and_preserves_edits(self):
        self.prepare()
        with patch.object(app, 'DB', self.root / 'app.sqlite'), patch.dict(os.environ, {'RADAR_ENV': '', 'RADAR_ADMIN_USER': '', 'RADAR_ADMIN_PASSWORD': ''}):
            app.init_db()
            with app.connect() as db:
                campaign = discovery.save_campaign(db, 'seller-A', dict(name='Restaurantes locais', city='Porto Alegre', category='restaurantes', frequency='manual', enrich_websites=True))
            manager = discovery.DiscoveryManager(app.connect, enricher=lambda rows: 0)
            original_fetch = local_osm.fetch
            with patch.object(local_osm, 'status', return_value=local_osm.status(self.directory)), patch.object(local_osm, 'fetch', side_effect=lambda *a: original_fetch(*a, directory=self.directory)), patch.object(discovery, 'fetch_osm') as remote:
                def run():
                    manager.last_start = 0
                    identifier = manager.start('seller-A', campaign)
                    deadline = time.monotonic() + 5
                    while manager.lock.locked() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertFalse(manager.lock.locked())
                    return identifier
                first = run()
                with app.connect() as db:
                    self.assertEqual(db.execute('SELECT status FROM discovery_runs WHERE id=?', (first,)).fetchone()[0], 'concluido')
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0], 3)
                    self.assertEqual(discovery.snapshot(db, 'seller-B')['total'], 0)
                    db.execute("UPDATE prospect_inbox SET notes='NOTA DO VENDEDOR'")
                run()
                with app.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0], 3)
                    self.assertEqual(db.execute('SELECT notes FROM prospect_inbox LIMIT 1').fetchone()[0], 'NOTA DO VENDEDOR')
                    sources = json.loads(db.execute('SELECT metadata_json FROM discovery_sources LIMIT 1').fetchone()[0])
                    self.assertEqual(sources['source_backend'], 'OSM local · Geofabrik')
                remote.assert_not_called()



if __name__ == '__main__':
    unittest.main()
