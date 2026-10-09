PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  cnpj TEXT NOT NULL UNIQUE,
  razao_social TEXT NOT NULL,
  nome_fantasia TEXT DEFAULT '',
  situacao TEXT DEFAULT '',
  data_abertura TEXT DEFAULT '',
  cnae TEXT DEFAULT '',
  cnaes_secundarios TEXT DEFAULT '',
  segmento TEXT DEFAULT '',
  municipio TEXT DEFAULT '',
  regiao TEXT DEFAULT '',
  uf TEXT DEFAULT 'RS',
  cep TEXT DEFAULT '',
  bairro TEXT DEFAULT '',
  logradouro TEXT DEFAULT '',
  numero TEXT DEFAULT '',
  telefone TEXT DEFAULT '',
  email TEXT DEFAULT '',
  porte TEXT DEFAULT '',
  mei INTEGER NOT NULL DEFAULT 0,
  cnae_descricao TEXT DEFAULT '',
  serpro_checked_at TEXT,
  data_source TEXT DEFAULT 'Receita Federal'
);

CREATE INDEX IF NOT EXISTS idx_companies_open ON companies(data_abertura DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(municipio, data_abertura DESC);
CREATE INDEX IF NOT EXISTS idx_companies_region ON companies(regiao, data_abertura DESC);
CREATE INDEX IF NOT EXISTS idx_companies_segment ON companies(segmento, data_abertura DESC);
CREATE INDEX IF NOT EXISTS idx_companies_cnae ON companies(cnae, data_abertura DESC);
CREATE INDEX IF NOT EXISTS idx_companies_mei_open ON companies(mei, data_abertura DESC);

CREATE TABLE IF NOT EXISTS user_accounts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  username TEXT NOT NULL COLLATE NOCASE UNIQUE,
  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'vendedor',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS account_company_state (
  owner_id TEXT NOT NULL,
  cnpj TEXT NOT NULL,
  lead_status TEXT NOT NULL DEFAULT 'novo',
  favorito INTEGER NOT NULL DEFAULT 0,
  observacoes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(owner_id, cnpj),
  FOREIGN KEY(owner_id) REFERENCES user_accounts(id) ON DELETE CASCADE,
  FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_account_state_stage ON account_company_state(owner_id, lead_status);
CREATE INDEX IF NOT EXISTS idx_account_state_favorite ON account_company_state(owner_id, favorito);

CREATE TABLE IF NOT EXISTS prospecting_profiles (
  id TEXT PRIMARY KEY,
  owner_id TEXT,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  filters_json TEXT NOT NULL DEFAULT '{}',
  is_system INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(owner_id) REFERENCES user_accounts(id) ON DELETE CASCADE,
  CHECK ((is_system = 1 AND owner_id IS NULL) OR (is_system = 0 AND owner_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_prospecting_profiles_owner ON prospecting_profiles(owner_id, is_system, name);

CREATE TABLE IF NOT EXISTS profile_leads (
  owner_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  cnpj TEXT NOT NULL,
  added_at TEXT NOT NULL,
  PRIMARY KEY(owner_id, profile_id, cnpj),
  FOREIGN KEY(owner_id) REFERENCES user_accounts(id) ON DELETE CASCADE,
  FOREIGN KEY(profile_id) REFERENCES prospecting_profiles(id) ON DELETE CASCADE,
  FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_profile_leads_owner_cnpj ON profile_leads(owner_id, cnpj);

CREATE TABLE IF NOT EXISTS sales_profiles (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'Vendedor',
  email TEXT NOT NULL DEFAULT '',
  initials TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL DEFAULT '#b82043',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(owner_id) REFERENCES user_accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sales_profiles_owner ON sales_profiles(owner_id, name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS sales_profile_leads (
  owner_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  cnpj TEXT NOT NULL,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  favorito INTEGER NOT NULL DEFAULT 0,
  lead_status TEXT NOT NULL DEFAULT 'novo',
  observacoes TEXT NOT NULL DEFAULT '',
  estrategia TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(owner_id, profile_id, cnpj),
  FOREIGN KEY(owner_id) REFERENCES user_accounts(id) ON DELETE CASCADE,
  FOREIGN KEY(profile_id) REFERENCES sales_profiles(id) ON DELETE CASCADE,
  FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sales_leads_owner_profile ON sales_profile_leads(owner_id, profile_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sales_leads_owner_cnpj ON sales_profile_leads(owner_id, cnpj);

CREATE TABLE IF NOT EXISTS cnae_catalog (
  codigo TEXT PRIMARY KEY,
  descricao TEXT NOT NULL DEFAULT '',
  segmento TEXT NOT NULL DEFAULT '',
  empresas INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS filter_options (
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY(kind, value)
);

CREATE TABLE IF NOT EXISTS sync_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO prospecting_profiles(id,owner_id,name,description,filters_json,is_system,created_at,updated_at) VALUES
  ('geral',NULL,'Visão geral','Todas as empresas da base oficial','{}',1,datetime('now'),datetime('now')),
  ('mei',NULL,'Novos MEIs','Aberturas de microempreendedores individuais','{"mei":"sim"}',1,datetime('now'),datetime('now')),
  ('contato',NULL,'Com contato','Empresas com telefone ou e-mail público','{"contato":"sim"}',1,datetime('now'),datetime('now')),
  ('alto',NULL,'Alto potencial','Empresas com indicador de acionabilidade igual ou superior a 80','{"score_min":"80"}',1,datetime('now'),datetime('now')),
  ('favoritos',NULL,'Favoritos','Empresas favoritas da conta autenticada','{"favorito":"sim"}',1,datetime('now'),datetime('now'));
