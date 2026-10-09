-- Persistent login budget: shared by Worker isolates, bounded 15-minute windows.
CREATE TABLE IF NOT EXISTS auth_attempts (
  key TEXT PRIMARY KEY,
  count INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_attempts_expiry ON auth_attempts(expires_at);
