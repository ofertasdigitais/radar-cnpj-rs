"""Dedicated admin QA server; temporary SQLite, never the live Radar database."""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from tools.qa_preview import seed

if __name__=='__main__':
    os.environ.update(RADAR_ENV='',RADAR_ADMIN_USER='qa-admin',RADAR_ADMIN_PASSWORD='QAAdmin2026@',RADAR_SESSION_SECRET='isolated-admin-qa-session-secret-2026')
    with tempfile.TemporaryDirectory(prefix='radar-admin-browser-') as directory:
        app.DB=Path(directory)/'qa.sqlite';seed()
        app.SYNC.db_path=app.DB;app.MONITOR.db_path=app.DB
        server=app.ThreadingHTTPServer(('127.0.0.1',18001),app.Handler)
        print('Admin QA isolado: http://127.0.0.1:18001/admin',flush=True)
        try:server.serve_forever()
        finally:server.server_close()
