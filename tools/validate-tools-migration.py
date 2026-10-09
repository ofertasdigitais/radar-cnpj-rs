"""Validate additive migration on a consistent copy, never on the real database."""
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app

source_path=Path('data/radar.db').resolve()
with tempfile.TemporaryDirectory(prefix='radar-migration-') as directory:
    clone=Path(directory)/'copy.sqlite'
    with closing(sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)) as original,closing(sqlite3.connect(clone)) as target:
        original.backup(target)
    with closing(sqlite3.connect(clone)) as before:
        tables=['companies','user_accounts','sales_profiles','sales_profile_leads','sales_lead_history','commercial_settings']
        snapshot={table:before.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in tables}
    app.DB=clone;app.init_db()
    with app.connect() as after:
        checks={table:snapshot[table]==[tuple(row) for row in after.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables}
        checks['integrity']=after.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        checks['foreign_keys']=not after.execute('PRAGMA foreign_key_check').fetchall()
        checks['empty_private_inbox']=after.execute('SELECT COUNT(*) FROM prospect_inbox').fetchone()[0]==0
    print(json.dumps(checks,indent=2))
    if not all(checks.values()):raise SystemExit(1)
