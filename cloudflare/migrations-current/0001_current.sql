-- Current Radar schema, copied from a consistent read-only source on 2026-10-16.
-- Immutable after deployment. New empty Radar D1 only; legacy migrations remain untouched.
-- No account data, passwords, secrets or mutable configuration in this DDL.
CREATE TABLE account_company_state (
          account_id TEXT NOT NULL, cnpj TEXT NOT NULL,
          lead_status TEXT NOT NULL DEFAULT 'novo', favorito INTEGER NOT NULL DEFAULT 0,
          observacoes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
          PRIMARY KEY(account_id, cnpj),
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );

CREATE TABLE admin_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
      detail TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE admin_parameters (
      key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE admin_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);

CREATE TABLE admin_session_revisions (
      username TEXT PRIMARY KEY COLLATE NOCASE, revision INTEGER NOT NULL DEFAULT 0);

CREATE TABLE cnae_catalog (
          codigo TEXT PRIMARY KEY, descricao TEXT NOT NULL
        );

CREATE TABLE commercial_archive (
        id INTEGER PRIMARY KEY AUTOINCREMENT,profile_id TEXT NOT NULL,cnpj TEXT NOT NULL,
        company_name TEXT NOT NULL,removed_at TEXT NOT NULL,events_json TEXT NOT NULL);

CREATE TABLE commercial_settings (
        profile_id TEXT PRIMARY KEY REFERENCES sales_profiles(id) ON DELETE CASCADE,
        contact_sla_hours INTEGER NOT NULL DEFAULT 48,
        stalled_days INTEGER NOT NULL DEFAULT 7);

CREATE TABLE companies (
          id INTEGER PRIMARY KEY, cnpj TEXT UNIQUE NOT NULL, razao_social TEXT NOT NULL,
          nome_fantasia TEXT, situacao TEXT, data_abertura TEXT, cnae TEXT, cnaes_secundarios TEXT,
          segmento TEXT, municipio TEXT, regiao TEXT, uf TEXT DEFAULT 'RS', cep TEXT, bairro TEXT,
          logradouro TEXT, numero TEXT, telefone TEXT, email TEXT, porte TEXT, mei INTEGER DEFAULT 0
        , lead_status TEXT DEFAULT 'novo', favorito INTEGER DEFAULT 0, observacoes TEXT DEFAULT '', cnae_descricao TEXT DEFAULT '', serpro_checked_at TEXT, data_source TEXT DEFAULT 'Receita Federal');

CREATE TABLE contact_suppression (
      owner_id TEXT NOT NULL,cnpj TEXT NOT NULL,reason TEXT NOT NULL,updated_at TEXT NOT NULL,
      PRIMARY KEY(owner_id,cnpj),FOREIGN KEY(cnpj) REFERENCES companies(cnpj));

CREATE TABLE discovery_cache (query_key TEXT PRIMARY KEY,elements_json TEXT NOT NULL,fetched_at TEXT NOT NULL,expires_at TEXT NOT NULL);

CREATE TABLE discovery_campaigns (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,name TEXT NOT NULL,city TEXT NOT NULL,category TEXT NOT NULL,
      frequency TEXT NOT NULL,active INTEGER NOT NULL,require_phone INTEGER NOT NULL,require_website INTEGER NOT NULL,
      enrich_websites INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,next_run_at TEXT, cursor_json TEXT NOT NULL DEFAULT '{}', times_json TEXT NOT NULL DEFAULT '[]', icp_label TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1);

CREATE TABLE discovery_notifications (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,run_id TEXT NOT NULL UNIQUE,campaign_id TEXT NOT NULL,
      added INTEGER NOT NULL,created_at TEXT NOT NULL,read_at TEXT,
      FOREIGN KEY(run_id) REFERENCES discovery_runs(id),FOREIGN KEY(campaign_id) REFERENCES discovery_campaigns(id));

CREATE TABLE discovery_preferences (owner_id TEXT PRIMARY KEY,notifications_enabled INTEGER NOT NULL DEFAULT 1);

CREATE TABLE discovery_recommendations (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,prospect_id TEXT NOT NULL,campaign_id TEXT NOT NULL,
      run_id TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
      revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,reviewed_at TEXT,
      UNIQUE(owner_id,prospect_id),FOREIGN KEY(prospect_id) REFERENCES prospect_inbox(id),
      FOREIGN KEY(campaign_id) REFERENCES discovery_campaigns(id),FOREIGN KEY(run_id) REFERENCES discovery_runs(id));

CREATE TABLE discovery_runs (
      id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,owner_id TEXT NOT NULL,status TEXT NOT NULL,
      found INTEGER NOT NULL DEFAULT 0,added INTEGER NOT NULL DEFAULT 0,duplicates INTEGER NOT NULL DEFAULT 0,
      enriched INTEGER NOT NULL DEFAULT 0,started_at TEXT NOT NULL,finished_at TEXT,message TEXT NOT NULL DEFAULT '', scheduled_for TEXT,
      FOREIGN KEY(campaign_id) REFERENCES discovery_campaigns(id));

CREATE TABLE discovery_sources (
      owner_id TEXT NOT NULL,source_key TEXT NOT NULL,prospect_id TEXT NOT NULL,metadata_json TEXT NOT NULL,last_seen_at TEXT NOT NULL,
      PRIMARY KEY(owner_id,source_key),FOREIGN KEY(prospect_id) REFERENCES prospect_inbox(id));

CREATE TABLE help_articles (
      id TEXT PRIMARY KEY,category TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,
      steps_json TEXT NOT NULL,action TEXT NOT NULL DEFAULT '',tags TEXT NOT NULL DEFAULT '',
      admin_only INTEGER NOT NULL DEFAULT 0,published INTEGER NOT NULL DEFAULT 1,
      revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);

CREATE TABLE help_feedback (
      article_id TEXT NOT NULL REFERENCES help_articles(id),owner_id TEXT NOT NULL,
      useful INTEGER NOT NULL CHECK(useful IN (0,1)),updated_at TEXT NOT NULL,
      PRIMARY KEY(article_id,owner_id));

CREATE TABLE help_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE message_templates (
          id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
          body TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );

CREATE TABLE monitor_candidates (
          cnpj TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT 'base oficial',
          status TEXT NOT NULL DEFAULT 'pendente', discovered_at TEXT NOT NULL,
          checked_at TEXT, last_error TEXT DEFAULT '', attempts INTEGER DEFAULT 0
        );

CREATE TABLE monitor_runs (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, discovered INTEGER DEFAULT 0, processed INTEGER DEFAULT 0,
          updated INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, message TEXT DEFAULT ''
        );

CREATE TABLE private_companies (
        cnpj TEXT PRIMARY KEY REFERENCES companies(cnpj) ON DELETE CASCADE,
        owner_id TEXT);

CREATE TABLE profile_leads (
          profile_id TEXT NOT NULL,
          cnpj TEXT NOT NULL,
          added_at TEXT NOT NULL,
          PRIMARY KEY(profile_id, cnpj),
          FOREIGN KEY(profile_id) REFERENCES prospecting_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );

CREATE TABLE prospect_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,prospect_id TEXT NOT NULL REFERENCES prospect_inbox(id),
      owner_id TEXT NOT NULL,event TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL);

CREATE TABLE prospect_inbox (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
      name TEXT NOT NULL,company TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',
      email TEXT NOT NULL DEFAULT '',city TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,
      campaign TEXT NOT NULL DEFAULT '',persona TEXT NOT NULL DEFAULT '',website TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',cnpj TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'novo',
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,UNIQUE(owner_id,fingerprint));

CREATE TABLE prospect_links (
      prospect_id TEXT NOT NULL REFERENCES prospect_inbox(id) ON DELETE CASCADE,
      profile_id TEXT NOT NULL,cnpj TEXT NOT NULL,owner_id TEXT NOT NULL,created_at TEXT NOT NULL,
      PRIMARY KEY(prospect_id,profile_id,cnpj),
      FOREIGN KEY(profile_id,cnpj) REFERENCES sales_profile_leads(profile_id,cnpj) ON DELETE CASCADE);

CREATE TABLE prospecting_profiles (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
          filters_json TEXT NOT NULL DEFAULT '{}', is_system INTEGER DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        , owner_id TEXT);

CREATE TABLE sales_lead_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, cnpj TEXT NOT NULL,
          event_type TEXT NOT NULL, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, changes_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(profile_id,cnpj) REFERENCES sales_profile_leads(profile_id,cnpj) ON DELETE CASCADE
        );

CREATE TABLE sales_monthly_targets (
      profile_id TEXT NOT NULL REFERENCES sales_profiles(id) ON DELETE CASCADE,
      month TEXT NOT NULL,revenue_cents INTEGER NOT NULL DEFAULT 0,contacts INTEGER NOT NULL DEFAULT 0,
      wins INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(profile_id,month));

CREATE TABLE sales_profile_leads (
          profile_id TEXT NOT NULL, cnpj TEXT NOT NULL, added_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, favorito INTEGER NOT NULL DEFAULT 0,
          lead_status TEXT NOT NULL DEFAULT 'novo', observacoes TEXT NOT NULL DEFAULT '',
          estrategia TEXT NOT NULL DEFAULT '', contact_outcome TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '', next_action_at TEXT, last_contact_at TEXT, first_contact_at TEXT, closed_at TEXT, offered_value_cents INTEGER NOT NULL DEFAULT 0, negotiated_value_cents INTEGER NOT NULL DEFAULT 0, closed_value_cents INTEGER NOT NULL DEFAULT 0, whatsapp_status TEXT NOT NULL DEFAULT 'pending', whatsapp_phone TEXT NOT NULL DEFAULT '', whatsapp_checked_at TEXT, campaign TEXT NOT NULL DEFAULT '', persona TEXT NOT NULL DEFAULT '', lead_origin TEXT NOT NULL DEFAULT '', loss_reason TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(profile_id, cnpj),
          FOREIGN KEY(profile_id) REFERENCES sales_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );

CREATE TABLE sales_profiles (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'Vendedor',
          email TEXT NOT NULL DEFAULT '', initials TEXT NOT NULL DEFAULT '',
          color TEXT NOT NULL DEFAULT '#b82043', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        , owner_id TEXT);

CREATE TABLE sync_meta(key TEXT PRIMARY KEY,value TEXT);

CREATE TABLE user_accounts (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          email TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'vendedor', is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
        );

CREATE INDEX idx_account_company_state_account
          ON account_company_state(account_id, updated_at DESC);

CREATE INDEX idx_account_company_state_account_stage
          ON account_company_state(account_id,lead_status);

CREATE INDEX idx_archive_profile ON commercial_archive(profile_id,removed_at DESC);

CREATE INDEX idx_city ON companies(municipio);

CREATE INDEX idx_cnae ON companies(cnae);

CREATE INDEX idx_discovery_due ON discovery_campaigns(active,next_run_at);

CREATE INDEX idx_discovery_owner ON discovery_runs(owner_id,started_at DESC);

CREATE UNIQUE INDEX idx_discovery_slot ON discovery_runs(campaign_id,scheduled_for) WHERE scheduled_for IS NOT NULL;

CREATE INDEX idx_history_profile_date ON sales_lead_history(profile_id,created_at DESC);

CREATE INDEX idx_lead_stage ON companies(lead_status);

CREATE INDEX idx_mei_open ON companies(mei,data_abertura DESC);

CREATE INDEX idx_message_templates_owner_default
          ON message_templates(owner_id, is_default DESC, updated_at DESC);

CREATE UNIQUE INDEX idx_message_templates_owner_name
          ON message_templates(owner_id, name COLLATE NOCASE);

CREATE INDEX idx_notifications_owner ON discovery_notifications(owner_id,created_at DESC);

CREATE INDEX idx_open ON companies(data_abertura DESC);

CREATE INDEX idx_profile_leads_added ON profile_leads(profile_id, added_at DESC);

CREATE INDEX idx_profile_leads_cnpj ON profile_leads(cnpj);

CREATE INDEX idx_prospect_owner_updated ON prospect_inbox(owner_id,updated_at DESC);

CREATE INDEX idx_prospecting_profiles_owner ON prospecting_profiles(owner_id,is_system);

CREATE INDEX idx_recommendations_owner ON discovery_recommendations(owner_id,status,created_at DESC);

CREATE INDEX idx_sales_closed_date ON sales_profile_leads(profile_id,closed_at);

CREATE INDEX idx_sales_lead_history_lead
          ON sales_lead_history(profile_id,cnpj,created_at DESC,id DESC);

CREATE INDEX idx_sales_profile_leads_cnpj ON sales_profile_leads(cnpj);

CREATE INDEX idx_sales_profile_leads_next_action ON sales_profile_leads(profile_id,next_action_at);

CREATE INDEX idx_sales_profile_leads_profile ON sales_profile_leads(profile_id, updated_at DESC);

CREATE INDEX idx_sales_profile_leads_stage ON sales_profile_leads(profile_id,lead_status);

CREATE INDEX idx_sales_profile_updated ON sales_profile_leads(profile_id,updated_at DESC);

CREATE INDEX idx_sales_profiles_owner ON sales_profiles(owner_id);

CREATE INDEX idx_user_accounts_email ON user_accounts(email COLLATE NOCASE);

CREATE VIEW accessible_sales_profile_leads AS
        SELECT s.* FROM sales_profile_leads s JOIN companies c ON c.cnpj=s.cnpj
        JOIN sales_profiles p ON p.id=s.profile_id WHERE (NOT ((COALESCE(c.uf,'')='ZZ' OR COALESCE(c.situacao,'')='TESTE') OR EXISTS (SELECT 1 FROM private_companies identity WHERE identity.cnpj=c.cnpj)) OR EXISTS (SELECT 1 FROM private_companies priv WHERE priv.cnpj=c.cnpj AND priv.owner_id=p.owner_id));


CREATE TABLE auth_attempts (key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires_at INTEGER NOT NULL);
CREATE INDEX idx_auth_attempts_expiry ON auth_attempts(expires_at);

