import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('current_export', ROOT/'cloudflare/scripts/export_current.py')
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class CurrentExportTests(unittest.TestCase):
    def test_consistent_snapshot_round_trip_all_tables_and_sequences(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory/'source.db'
            with closing(sqlite3.connect(source)) as db:
                db.executescript('CREATE TABLE companies(cnpj TEXT PRIMARY KEY,name TEXT);'
                    'CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,cnpj TEXT REFERENCES companies(cnpj),body TEXT);')
                db.execute('INSERT INTO companies VALUES(?,?)', ('123', "Lojas d'Água\nTeste"))
                db.execute('INSERT INTO events(cnpj,body) VALUES(?,?)', ('123','ação'))
                db.execute('INSERT INTO events(id,cnpj,body) VALUES(20,?,?)', ('123','removido'))
                db.execute('DELETE FROM events WHERE id=20')
                db.commit()
            manifest = exporter.export_current(source, directory/'output', chunk_rows=1)
            self.assertEqual(manifest['counts'], {'companies':1,'events':1})
            with closing(sqlite3.connect(':memory:')) as restored:
                for part in ['schema.sql', *manifest['data_files']]:
                    restored.executescript((directory/'output'/part).read_text(encoding='utf-8'))
                self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(restored.execute('SELECT name FROM companies').fetchone()[0], "Lojas d'Água\nTeste")
                restored.execute("INSERT INTO events(cnpj,body) VALUES('123','novo')")
                self.assertEqual(restored.execute('SELECT MAX(id) FROM events').fetchone()[0], 21)
            self.assertEqual(json.loads((directory/'output/manifest.json').read_text())['counts'],manifest['counts'])

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            with closing(sqlite3.connect(directory/'source.db')) as db: db.execute('CREATE TABLE sample(id INTEGER)')
            exporter.export_current(directory/'source.db',directory/'output')
            with self.assertRaises(FileExistsError): exporter.export_current(directory/'source.db',directory/'output')

    def test_current_schema_contains_all_live_contract_tables_and_private_view(self):
        with closing(sqlite3.connect(':memory:')) as target:
            for migration in sorted((ROOT/'cloudflare/migrations-current').glob('*.sql')):
                target.executescript(migration.read_text(encoding='utf-8'))
            self.assertEqual(len(target.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()),38)
            self.assertIsNotNone(target.execute("SELECT sql FROM sqlite_master WHERE name='accessible_sales_profile_leads'").fetchone())
            columns={r[1] for r in target.execute('PRAGMA table_info(sales_profile_leads)')}
            self.assertIn('closed_value_cents',columns)
            self.assertIn('loss_reason',columns)
