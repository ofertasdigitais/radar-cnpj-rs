"""Historical D1 export must never silently omit the functional Radar's data."""
import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


class ReleaseGateTests(unittest.TestCase):
    def test_modern_database_refused_before_output_creation(self):
        script = Path(__file__).resolve().parents[1] / 'cloudflare/scripts/export_d1.py'
        spec = importlib.util.spec_from_file_location('radar_legacy_export', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'qa.sqlite'
            output = Path(directory) / 'export'
            with closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE contact_suppression(owner_id TEXT,cnpj TEXT)')
                db.commit()
            original = database.read_bytes()
            with patch('sys.argv', [str(script), '--database', str(database), '--output', str(output)]):
                with self.assertRaisesRegex(SystemExit, 'Exportação legada bloqueada'):
                    module.main()
            self.assertFalse(output.exists())
            self.assertEqual(database.read_bytes(), original)
