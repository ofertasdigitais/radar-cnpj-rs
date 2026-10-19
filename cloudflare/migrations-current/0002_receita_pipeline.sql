-- Additive ledger for the Radar-only Receita import endpoint. No customer data or secrets.
CREATE TABLE sync_import_runs (
  id TEXT PRIMARY KEY,
  competencia TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'full' CHECK(mode IN ('full','catalog')),
  status TEXT NOT NULL CHECK(status IN ('loading','receiving','complete','failed','expired')),
  active_lock INTEGER UNIQUE CHECK(active_lock IS NULL OR active_lock=1),
  expected_rows INTEGER CHECK(expected_rows IS NULL OR expected_rows BETWEEN 0 AND 1000000),
  received_rows INTEGER NOT NULL DEFAULT 0,
  applied_rows INTEGER NOT NULL DEFAULT 0,
  next_sequence INTEGER NOT NULL DEFAULT 0,
  last_cnpj TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT 'Carregando fonte oficial',
  progress REAL NOT NULL DEFAULT 0,
  error_code TEXT NOT NULL DEFAULT '',
  catalog_sha256 TEXT,
  catalog_count INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX idx_sync_import_recent ON sync_import_runs(started_at DESC);
CREATE TABLE sync_import_batches (
  run_id TEXT NOT NULL REFERENCES sync_import_runs(id),
  sequence INTEGER NOT NULL CHECK(sequence BETWEEN 0 AND 10000),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  row_count INTEGER NOT NULL CHECK(row_count BETWEEN 1 AND 500),
  applied_rows INTEGER NOT NULL,
  first_cnpj TEXT NOT NULL,
  last_cnpj TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(run_id,sequence)
);
