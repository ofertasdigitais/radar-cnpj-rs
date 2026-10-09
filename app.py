import base64
import csv
import hashlib
import hmac
import html
import io
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import time
import uuid
from http.cookies import SimpleCookie
from datetime import date, timedelta, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from syncer import CNPJSync
from serpro import DailyMonitor
import commercial
import sales_ops
import backup_protection
import prospecting
import discovery
import security
import admin_panel
import admin_http
import help_center

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR", ROOT / "data")).resolve()
DB = DATA_DIR / "radar.db"
STATIC = ROOT / "static"
admin_panel.configure(DB)
SYNC = CNPJSync(DB, DATA_DIR / "sync-cache")
MONITOR = DailyMonitor(DB)

PASSWORD_ITERATIONS = 260_000
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

CONTACT_OUTCOMES = {
    "": "Não informado", "nao_respondeu": "Não respondeu", "respondeu": "Respondeu",
    "retornar": "Pediu retorno", "sem_interesse": "Sem interesse",
    "numero_invalido": "Número inválido", "oportunidade": "Oportunidade aberta",
}
LEAD_STAGES = {
    "novo": "Novo", "qualificado": "Qualificado", "contatado": "Contatado",
    "negociacao": "Em negociação", "convertido": "Convertido", "descartado": "Descartado", "concluido": "Concluído",
}

LEAD_SCORE_SQL = """(
  CASE WHEN TRIM(COALESCE(email,''))<>'' THEN 20 ELSE 0 END +
  CASE WHEN TRIM(COALESCE(telefone,''))<>'' THEN 20 ELSE 0 END +
  CASE WHEN situacao='ATIVA' THEN 15 ELSE 0 END +
  CASE WHEN TRIM(COALESCE(nome_fantasia,''))<>'' THEN 10 ELSE 0 END +
  CASE WHEN COALESCE(mei,0)=0 THEN 10 ELSE 0 END +
  CASE
    WHEN julianday(date('now','localtime'))-julianday(data_abertura)<=30 THEN 25
    WHEN julianday(date('now','localtime'))-julianday(data_abertura)<=90 THEN 15
    WHEN julianday(date('now','localtime'))-julianday(data_abertura)<=365 THEN 5
    ELSE 0
  END
)"""

ACCOUNT_COMPANY_SOURCE = """(
  SELECT c.id,c.cnpj,c.razao_social,c.nome_fantasia,c.situacao,c.data_abertura,
    c.cnae,c.cnaes_secundarios,c.segmento,c.municipio,c.regiao,c.uf,c.cep,c.bairro,
    c.logradouro,c.numero,c.telefone,c.email,c.porte,c.mei,c.cnae_descricao,
    c.serpro_checked_at,c.data_source,
    COALESCE(acs.lead_status,'novo') AS lead_status,
    COALESCE(acs.favorito,0) AS favorito,
    COALESCE(acs.observacoes,'') AS observacoes
  FROM companies c
  LEFT JOIN account_company_state acs ON acs.cnpj=c.cnpj AND acs.account_id=?
) AS companies"""


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect():
    # A aplicação pode receber mais de um vendedor ao mesmo tempo. O timeout
    # evita falhas momentâneas quando uma gravação coincide com outra; o
    # busy_timeout mantém a espera dentro do SQLite em vez de perder a ação.
    conn = sqlite3.connect(DB, timeout=30, factory=DatabaseConnection)
    conn.row_factory = sqlite3.Row
    # Relações entre perfis e leads precisam ser íntegras e acompanhar a
    # exclusão de um perfil sem deixar registros órfãos.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    admin_panel.configure(DB)
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        # WAL permite que consultas e salvamentos de vendedores diferentes
        # avancem em paralelo sem bloquear a leitura do painel.
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
          id INTEGER PRIMARY KEY, cnpj TEXT UNIQUE NOT NULL, razao_social TEXT NOT NULL,
          nome_fantasia TEXT, situacao TEXT, data_abertura TEXT, cnae TEXT, cnaes_secundarios TEXT,
          segmento TEXT, municipio TEXT, regiao TEXT, uf TEXT DEFAULT 'RS', cep TEXT, bairro TEXT,
          logradouro TEXT, numero TEXT, telefone TEXT, email TEXT, porte TEXT, mei INTEGER DEFAULT 0,
          lead_status TEXT DEFAULT 'novo', favorito INTEGER DEFAULT 0, observacoes TEXT DEFAULT '',
          cnae_descricao TEXT DEFAULT '', serpro_checked_at TEXT, data_source TEXT DEFAULT 'Receita Federal'
        );
        CREATE INDEX IF NOT EXISTS idx_open ON companies(data_abertura DESC);
        CREATE INDEX IF NOT EXISTS idx_city ON companies(municipio);
        CREATE INDEX IF NOT EXISTS idx_cnae ON companies(cnae);
        CREATE INDEX IF NOT EXISTS idx_mei_open ON companies(mei,data_abertura DESC);
        CREATE TABLE IF NOT EXISTS cnae_catalog (
          codigo TEXT PRIMARY KEY, descricao TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prospecting_profiles (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
          filters_json TEXT NOT NULL DEFAULT '{}', is_system INTEGER DEFAULT 0,
          owner_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profile_leads (
          profile_id TEXT NOT NULL,
          cnpj TEXT NOT NULL,
          added_at TEXT NOT NULL,
          PRIMARY KEY(profile_id, cnpj),
          FOREIGN KEY(profile_id) REFERENCES prospecting_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_profile_leads_cnpj ON profile_leads(cnpj);
        CREATE INDEX IF NOT EXISTS idx_profile_leads_added ON profile_leads(profile_id, added_at DESC);
        /* Perfis individuais da equipe. Estes registros são distintos das
           segmentações salvas acima: cada pessoa tem sua própria carteira,
           etapa, favorito, observações e estratégia por lead. */
        CREATE TABLE IF NOT EXISTS sales_profiles (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'Vendedor',
          email TEXT NOT NULL DEFAULT '', initials TEXT NOT NULL DEFAULT '',
          color TEXT NOT NULL DEFAULT '#b82043', owner_id TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_profile_leads (
          profile_id TEXT NOT NULL, cnpj TEXT NOT NULL, added_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, favorito INTEGER NOT NULL DEFAULT 0,
          lead_status TEXT NOT NULL DEFAULT 'novo', observacoes TEXT NOT NULL DEFAULT '',
          estrategia TEXT NOT NULL DEFAULT '', contact_outcome TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '', next_action_at TEXT, last_contact_at TEXT,
          first_contact_at TEXT, closed_at TEXT,
          offered_value_cents INTEGER NOT NULL DEFAULT 0,
          negotiated_value_cents INTEGER NOT NULL DEFAULT 0,
          closed_value_cents INTEGER NOT NULL DEFAULT 0,
          whatsapp_status TEXT NOT NULL DEFAULT 'pending',
          whatsapp_phone TEXT NOT NULL DEFAULT '', whatsapp_checked_at TEXT,
          PRIMARY KEY(profile_id, cnpj),
          FOREIGN KEY(profile_id) REFERENCES sales_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sales_profile_leads_profile ON sales_profile_leads(profile_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sales_profile_leads_cnpj ON sales_profile_leads(cnpj);
        CREATE INDEX IF NOT EXISTS idx_sales_profile_leads_stage ON sales_profile_leads(profile_id,lead_status);
        CREATE INDEX IF NOT EXISTS idx_sales_profile_leads_next_action ON sales_profile_leads(profile_id,next_action_at);
        CREATE TABLE IF NOT EXISTS sales_lead_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, cnpj TEXT NOT NULL,
          event_type TEXT NOT NULL, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          FOREIGN KEY(profile_id,cnpj) REFERENCES sales_profile_leads(profile_id,cnpj) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sales_lead_history_lead
          ON sales_lead_history(profile_id,cnpj,created_at DESC,id DESC);
        CREATE TABLE IF NOT EXISTS monitor_candidates (
          cnpj TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT 'base oficial',
          status TEXT NOT NULL DEFAULT 'pendente', discovered_at TEXT NOT NULL,
          checked_at TEXT, last_error TEXT DEFAULT '', attempts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS monitor_runs (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, discovered INTEGER DEFAULT 0, processed INTEGER DEFAULT 0,
          updated INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, message TEXT DEFAULT ''
        );
        /* Contas de acesso ao Radar. Não se confundem com os perfis comerciais:
           a conta autentica a pessoa; o perfil organiza a carteira dela. */
        CREATE TABLE IF NOT EXISTS user_accounts (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          email TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'vendedor', is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_user_accounts_email ON user_accounts(email COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS account_company_state (
          account_id TEXT NOT NULL, cnpj TEXT NOT NULL,
          lead_status TEXT NOT NULL DEFAULT 'novo', favorito INTEGER NOT NULL DEFAULT 0,
          observacoes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
          PRIMARY KEY(account_id,cnpj),
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_account_company_state_account_stage
          ON account_company_state(account_id,lead_status);
        /* Modelos de abordagem do WhatsApp. O owner_id vem da conta
           autenticada; não é ligado ao perfil comercial da carteira. */
        CREATE TABLE IF NOT EXISTS message_templates (
          id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
          body TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_message_templates_owner_name
          ON message_templates(owner_id, name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_message_templates_owner_default
          ON message_templates(owner_id, is_default DESC, updated_at DESC);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(companies)")}
        for name, definition in (("lead_status", "TEXT DEFAULT 'novo'"), ("favorito", "INTEGER DEFAULT 0"), ("observacoes", "TEXT DEFAULT ''"), ("cnae_descricao", "TEXT DEFAULT ''"), ("serpro_checked_at", "TEXT"), ("data_source", "TEXT DEFAULT 'Receita Federal'")):
            if name not in columns:
                db.execute(f"ALTER TABLE companies ADD COLUMN {name} {definition}")
        db.execute("UPDATE companies SET lead_status='novo' WHERE lead_status IS NULL OR TRIM(lead_status)=''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_lead_stage ON companies(lead_status)")
        profile_columns = {row[1] for row in db.execute("PRAGMA table_info(prospecting_profiles)")}
        if "owner_id" not in profile_columns:
            db.execute("ALTER TABLE prospecting_profiles ADD COLUMN owner_id TEXT")
        team_profile_columns = {row[1] for row in db.execute("PRAGMA table_info(sales_profiles)")}
        if "owner_id" not in team_profile_columns:
            db.execute("ALTER TABLE sales_profiles ADD COLUMN owner_id TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS idx_prospecting_profiles_owner ON prospecting_profiles(owner_id,is_system)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sales_profiles_owner ON sales_profiles(owner_id)")
        sales_columns = {row[1] for row in db.execute("PRAGMA table_info(sales_profile_leads)")}
        for name, definition in (
            ("contact_outcome", "TEXT NOT NULL DEFAULT ''"),
            ("next_action", "TEXT NOT NULL DEFAULT ''"),
            ("next_action_at", "TEXT"),
            ("last_contact_at", "TEXT"),
            ("first_contact_at", "TEXT"),
            ("closed_at", "TEXT"),
            ("offered_value_cents", "INTEGER NOT NULL DEFAULT 0"),
            ("negotiated_value_cents", "INTEGER NOT NULL DEFAULT 0"),
            ("closed_value_cents", "INTEGER NOT NULL DEFAULT 0"),
            ("whatsapp_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("whatsapp_phone", "TEXT NOT NULL DEFAULT ''"),
            ("whatsapp_checked_at", "TEXT"),
        ):
            if name not in sales_columns:
                db.execute(f"ALTER TABLE sales_profile_leads ADD COLUMN {name} {definition}")
        db.execute("""UPDATE sales_profile_leads
            SET first_contact_at=COALESCE(last_contact_at,updated_at)
            WHERE first_contact_at IS NULL AND (
              last_contact_at IS NOT NULL OR TRIM(COALESCE(contact_outcome,''))<>'' OR
              lead_status IN ('contatado','negociacao','convertido')
            )""")
        db.execute("""UPDATE sales_profile_leads SET closed_at=updated_at
            WHERE closed_at IS NULL AND lead_status='convertido'""")
        # Legacy ownership requires an explicit administrator assignment.
        # Names/emails entered at registration are not verified identities.
        now = datetime.now().isoformat(timespec="seconds")
        system_profiles = (
            ("geral", "Visão geral", "Todos os novos negócios do recorte selecionado", {}),
            ("mei", "Novos MEIs", "Somente microempreendedores individuais", {"mei": "sim"}),
            ("contato", "Com contato", "Empresas com telefone ou correio eletrônico público", {"contato": "sim"}),
            ("alto", "Alto potencial", "Leads com índice de acionabilidade a partir de 80", {"score_min": "80"}),
            ("favoritos", "Favoritos", "Sua seleção comercial prioritária", {"favorito": "sim"}),
        )
        db.executemany("INSERT OR IGNORE INTO prospecting_profiles(id,name,description,filters_json,is_system,created_at,updated_at) VALUES(?,?,?,?,1,?,?)", [(key, name, description, json.dumps(values, ensure_ascii=False), now, now) for key, name, description, values in system_profiles])
        if os.environ.get("RADAR_DEMO_DATA", "0") == "1" and db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
            today = date.today()
            demo = [
                ("48900111000101","PAMPA SOFTWARE LTDA","Pampa Tech","ATIVA",today.isoformat(),"6201501","", "Tecnologia e comunicação","Porto Alegre","Metropolitana","RS","90000000","Centro Histórico","Rua dos Andradas","120","5130001000","contato@pampa.demo","ME",0),
                ("48900112000148","SERRA SABORES ALIMENTOS LTDA","Serra Sabores","ATIVA",(today-timedelta(days=3)).isoformat(),"1091102","", "Indústria","Caxias Do Sul","Serra","RS","95000000","Centro","Rua Sinimbu","45","5430002000","oi@serra.demo","ME",0),
                ("48900113000192","MARIANA COSTA SERVICOS","MC Design","ATIVA",(today-timedelta(days=7)).isoformat(),"7410202","", "Serviços profissionais","Pelotas","Sul","RS","96000000","Centro","Rua XV de Novembro","88","5330003000","mariana@demo","MEI",1),
                ("48900114000137","VALE LOG TRANSPORTES LTDA","Vale Log","ATIVA",(today-timedelta(days=16)).isoformat(),"4930202","", "Transporte e logística","Lajeado","Vale do Taquari","RS","95900000","Florestal","Av. Benjamin Constant","900","5130004000","comercial@valelog.demo","EPP",0),
                ("48900115000181","NORTE SAUDE INTEGRADA LTDA","Norte Saúde","ATIVA",(today-timedelta(days=31)).isoformat(),"8630503","", "Saúde","Passo Fundo","Norte","RS","99000000","Centro","Rua Morom","310","5430005000","agenda@nortesaude.demo","ME",0),
                ("48900116000126","FRONTEIRA COMERCIO DIGITAL LTDA","Fronteira Shop","ATIVA",(today-timedelta(days=60)).isoformat(),"4791201","", "Comércio","Uruguaiana","Fronteira Oeste","RS","97500000","Centro","Rua Santana","77","5530006000","vendas@fronteira.demo","ME",0)
            ]
            db.executemany("INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,cnaes_secundarios,segmento,municipio,regiao,uf,cep,bairro,logradouro,numero,telefone,email,porte,mei) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", demo)
        commercial.ensure_schema(db)
        sales_ops.ensure_schema(db)
        prospecting.ensure_schema(db)
        discovery.ensure_schema(db)
        admin_panel.ensure_schema(db)
        help_center.ensure_schema(db)
        db.execute("PRAGMA optimize")


def resolve_local_admin_credential():
    if os.environ.get('RADAR_ADMIN_USER') and os.environ.get('RADAR_ADMIN_PASSWORD'):
        return
    credential = DATA_DIR / '.radar-credential.xml'
    if os.name != 'nt' or not credential.is_file():
        return
    script = "$ErrorActionPreference='Stop'; $c=Import-Clixml -LiteralPath $env:RADAR_CRED_PATH; $c.UserName; $c.GetNetworkCredential().Password"
    try:
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command','-'],
            input=script, capture_output=True,text=True,timeout=10,
            env={**os.environ,'RADAR_CRED_PATH':str(credential)})
        lines = result.stdout.splitlines()
        if result.returncode or len(lines)!=2 or not all(lines):
            return
        os.environ.setdefault('RADAR_ADMIN_USER',lines[0])
        os.environ.setdefault('RADAR_ADMIN_PASSWORD',lines[1])
        secret = DATA_DIR / '.radar-session-secret'
        if not os.environ.get('RADAR_SESSION_SECRET') and secret.is_file():
            os.environ['RADAR_SESSION_SECRET']=secret.read_text(encoding='utf-8').strip()
    except (OSError, subprocess.SubprocessError):
        return


def password_digest(password, salt=None):
    """Gera um hash lento e salgado; a senha original nunca vai para o banco."""
    salt_bytes = os.urandom(16) if salt is None else bytes.fromhex(salt)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, PASSWORD_ITERATIONS)
    return salt_bytes.hex(), digest.hex()


def password_matches(password, salt, expected_digest):
    try:
        _, supplied_digest = password_digest(password, salt)
        return hmac.compare_digest(supplied_digest, expected_digest)
    except (TypeError, ValueError):
        return False


def activity_date_range(params):
    start = str(params.get('activity_from', [''])[0]).strip()
    end = str(params.get('activity_to', [''])[0]).strip()
    for value in (start, end):
        if value and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or date.fromisoformat(value).isoformat() != value):
            raise ValueError('Data inválida')
    if start and end and start > end:
        raise ValueError('A data inicial deve ser anterior à final')
    return start, end


def add_lead_history(db, profile_id, cnpj, event_type, title, details="", created_at=None):
    db.execute(
        """INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at)
           VALUES(?,?,?,?,?,?)""",
        (profile_id, cnpj, event_type, str(title)[:180], str(details)[:1000],
         created_at or datetime.now().isoformat(timespec="seconds")),
    )


def money_cents(value):
    """Converte valores do formulário em centavos sem armazenar ponto flutuante."""
    if isinstance(value, bool): raise ValueError("Valor financeiro inválido")
    if value in (None, ""):
        return 0
    if isinstance(value, int):
        if value < 0 or value > 10**14: raise ValueError("Valor financeiro fora do intervalo permitido")
        return value
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
        if not amount.is_finite() or amount < 0 or amount > Decimal('1000000000000'):
            raise ValueError("Valor financeiro fora do intervalo permitido")
        return int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Valor financeiro inválido")


def safe_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo: parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.isoformat(timespec="minutes")
    except ValueError:
        raise ValueError("Data e hora inválida")


def registration_enabled(request_host=""):
    choice=admin_panel.get('registration',DB)
    if choice!='inherit':return choice=='on'
    if security.production():
        return os.environ.get('RADAR_ALLOW_REGISTRATION', '0') == '1'
    host = str(request_host or "").split(":", 1)[0].strip("[]").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    return os.environ.get("RADAR_ALLOW_REGISTRATION", "1").strip().lower() not in {"0", "false", "nao", "não"}


def account_by_login(login):
    with connect() as db:
        return db.execute(
            """SELECT * FROM user_accounts
               WHERE is_active=1 AND (username=? COLLATE NOCASE OR email=? COLLATE NOCASE)
               LIMIT 1""",
            (login, login),
        ).fetchone()


def filters(params, exclude=(), owner_id=None):
    clauses = ["uf='RS'"]; values = []
    mappings = {"inicio":("data_abertura >= ?",None),"fim":("data_abertura <= ?",None),"municipio":("municipio = ?",None),"regiao":("regiao = ?",None),"segmento":("segmento = ?",None),"situacao":("situacao = ?",None),"mei":("mei = ?", lambda x: 1 if x == "sim" else 0),"contato":("CASE WHEN TRIM(COALESCE(email,''))<>'' OR TRIM(COALESCE(telefone,''))<>'' THEN 1 ELSE 0 END = ?",lambda x: 1 if x == "sim" else 0),"lead_status":("COALESCE(NULLIF(lead_status,''),'novo') = ?",None),"favorito":("favorito = ?",lambda x: 1 if x == "sim" else 0)}
    for key, (sql, convert) in mappings.items():
        if key in exclude: continue
        val = params.get(key, [""])[0]
        if val: clauses.append(sql); values.append(convert(val) if convert else val)
    cnae = ''.join(c for c in params.get("cnae", [""])[0] if c.isdigit())
    if "cnae" not in exclude:
        if cnae: clauses.append("cnae LIKE ?"); values.append(cnae + "%")
        elif params.get("cnae", [""])[0].strip():
            clauses.append("cnae_descricao LIKE ?"); values.append('%' + params['cnae'][0].strip() + '%')
    for key, negative in (("cnae_include", False), ("cnae_exclude", True)):
        codes = list(dict.fromkeys(re.sub(r'\D', '', code) for code in re.split(r'[,;\s]+', params.get(key, [''])[0])))
        codes = [code for code in codes if 2 <= len(code) <= 7][:40]
        if key not in exclude and codes:
            clauses.append(('NOT ' if negative else '') + '(' + ' OR '.join('COALESCE(cnae,\'\') LIKE ?' for _ in codes) + ')')
            values.extend(code + '%' for code in codes)
    for key, negative in (("name_terms", False), ("name_exclude", True)):
        terms = [term.strip()[:80] for term in params.get(key, [''])[0].split(',') if term.strip()][:12]
        if key not in exclude and terms:
            clauses.append(('NOT ' if negative else '') + '(' + ' OR '.join("(COALESCE(razao_social,'') LIKE ? OR COALESCE(nome_fantasia,'') LIKE ?)" for _ in terms) + ')')
            for term in terms: values.extend(['%' + term + '%', '%' + term + '%'])
    for key in ('porte', 'data_source'):
        value = params.get(key, [''])[0].strip()
        if key not in exclude and value:
            clauses.append(f"{key} = ?"); values.append(value[:180])
    for key, column in (('phone_available', 'telefone'), ('email_available', 'email')):
        value = params.get(key, [''])[0]
        if key not in exclude and value:
            clauses.append(f"TRIM(COALESCE({column},'')) {'<>' if value == 'sim' else '='} ''")
    work_stage = params.get('work_stage', [''])[0]
    if 'work_stage' not in exclude and work_stage:
        scope = "EXISTS (SELECT 1 FROM sales_profile_leads wl JOIN sales_profiles wp ON wp.id=wl.profile_id WHERE wp.owner_id=? AND wl.cnpj=companies.cnpj"
        if not owner_id:
            clauses.append('0=1')
        else:
            values.append(owner_id)
            if work_stage in LEAD_STAGES:
                scope += ' AND wl.lead_status=?'; values.append(work_stage)
            clauses.append(('NOT ' if work_stage == 'not_selected' else '') + scope + ')')
    if "score_min" not in exclude:
        try:
            score_min = max(0, min(100, int(params.get("score_min", [""])[0])))
        except (TypeError, ValueError):
            score_min = 0
        if score_min:
            clauses.append(f"{LEAD_SCORE_SQL} >= ?"); values.append(score_min)
    search = params.get("q", [""])[0].strip()
    if search:
        identifier_search = ''.join(c for c in search.upper() if c.isalnum())
        if any(c.isdigit() for c in identifier_search):
            clauses.append("(razao_social LIKE ? OR nome_fantasia LIKE ? OR cnpj LIKE ?)")
            values.extend([f"%{search}%", f"%{search}%", f"%{identifier_search}%"])
        else:
            clauses.append("(razao_social LIKE ? OR nome_fantasia LIKE ?)")
            values.extend([f"%{search}%", f"%{search}%"])
    return " AND ".join(clauses), values


def score_company(company):
    """Indicador transparente de completude/acionabilidade, não de intenção de compra."""
    score = 0
    if company.get("email"): score += 20
    if company.get("telefone"): score += 20
    if company.get("situacao") == "ATIVA": score += 15
    if company.get("nome_fantasia"): score += 10
    if not company.get("mei"): score += 10
    try:
        age = (date.today() - datetime.strptime(company.get("data_abertura") or "", "%Y-%m-%d").date()).days
        score += 25 if age <= 30 else 15 if age <= 90 else 5 if age <= 365 else 0
    except ValueError:
        pass
    return min(score, 100)


class Handler(BaseHTTPRequestHandler):
    server_version = 'Radar'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def guard_write(self):
        if not security.same_origin(self.headers):
            self.send_json({'erro':'Origem da requisição não permitida'},403); return False
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: length=-1
        if length<0 or length>2*1024*1024 or self.headers.get('Transfer-Encoding'):
            self.close_connection=True
            self.send_json({'erro':'Corpo da requisição inválido ou acima de 2 MB'},413);return False
        return True

    def session_token(self, username, *, bootstrap_admin=False):
        secret = security.session_secret()
        # Bind the authentication source, not just a user-controlled name.
        source = "bootstrap" if bootstrap_admin else "account"
        payload = f"{username}|{int(time.time()) + 12 * 3600}|{source}"
        with connect() as db:
            signed_payload = admin_panel.session_payload(db, username, payload)
        if bootstrap_admin:
            signed_payload += "|" + security.bootstrap_credential_stamp()
        signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}|{signature}".encode()).decode()

    def session_identity(self):
        secret = security.session_secret()
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie["radar_session"].value
            decoded = base64.urlsafe_b64decode(token.encode()).decode()
            parts = decoded.rsplit("|", 3)
            if len(parts) == 4 and parts[-2] in {"bootstrap", "account"}:
                username, expires, source, signature = parts
                if source not in {"bootstrap", "account"}: return None
                payload = f"{username}|{expires}|{source}"
            else:
                username, expires, signature = decoded.rsplit("|", 2)
                source = "legacy"
                payload = f"{username}|{expires}"
            with connect() as db:
                signed_payload = admin_panel.session_payload(db, username, payload)
            if source == "bootstrap":
                signed_payload += "|" + security.bootstrap_credential_stamp()
            expected = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
            if int(expires) <= time.time() or not hmac.compare_digest(signature, expected):
                return None
            admin = os.environ.get("RADAR_ADMIN_USER", "").strip()
            reserved = bool(admin and username.casefold() == admin.casefold())
            if source == "bootstrap":
                return (username, True) if reserved else None
            # Old reserved-name cookies cannot prove which credentials issued them.
            if reserved: return None
            with connect() as db:
                row = db.execute(
                    "SELECT username FROM user_accounts WHERE username=? COLLATE NOCASE AND is_active=1",
                    (username,),
                ).fetchone()
            return (row[0], False) if row else None
        except (KeyError, ValueError, UnicodeDecodeError,TypeError):
            return None

    def session_username(self):
        identity = self.session_identity()
        return identity[0] if identity else None

    def valid_session(self):
        return self.session_username() is not None

    def session_owner_id(self):
        """Chave estável para configurações privadas da conta autenticada."""
        username = self.session_username()
        if username:
            with connect() as db:
                row = db.execute(
                    "SELECT id FROM user_accounts WHERE username=? COLLATE NOCASE LIMIT 1",
                    (username,),
                ).fetchone()
            if row:
                return row[0]
            return "admin:" + username.strip().lower()
        # Mantém o modo local sem autenticação usado no desenvolvimento e nos testes.
        return "local-default"

    def session_is_admin(self):
        identity = self.session_identity()
        if not identity: return False
        username, bootstrap_admin = identity
        if bootstrap_admin: return True
        if username:
            with connect() as db:
                row = db.execute(
                    "SELECT role FROM user_accounts WHERE username=? COLLATE NOCASE AND is_active=1",
                    (username,),
                ).fetchone()
            return bool(row and str(row["role"] or "").strip().lower() in {"admin", "administrador", "gestor"})
        return False

    def sales_profile_scope(self, alias="p"):
        """Administrador gerencia a equipe; vendedor acessa somente a própria conta."""
        if self.session_is_admin():
            return "1=1", []
        return f"{alias}.owner_id=?", [self.session_owner_id()]

    def owned_sales_profile(self, db, profile_id):
        scope, values = self.sales_profile_scope("p")
        return db.execute(
            f"SELECT p.* FROM sales_profiles p WHERE p.id=? AND {scope}",
            [profile_id] + values,
        ).fetchone()

    def ensure_default_message_template(self, db, owner_id):
        row = db.execute(
            "SELECT id FROM message_templates WHERE owner_id=? LIMIT 1", (owner_id,)
        ).fetchone()
        if row:
            return
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            """INSERT INTO message_templates(id,owner_id,name,body,is_default,created_at,updated_at)
               VALUES(?,?,?,?,1,?,?)""",
            (
                "mensagem-" + uuid.uuid4().hex[:12], owner_id, "Apresentação inicial",
                "Olá! Tudo bem? Meu nome é {vendedor}. Encontrei a {empresa} e gostaria de conversar sobre uma oportunidade. Posso te explicar rapidamente?",
                now, now,
            ),
        )

    def render_auth_page(self, mode="login", error="", values=None, status=200):
        values = values or {}
        can_register = registration_enabled(self.headers.get("Host", ""))
        view = "register" if mode == "register" and can_register else "login"
        template = (STATIC / "login.html").read_text(encoding="utf-8")
        message = f'<div class="auth-alert" role="alert"><span>!</span><p>{html.escape(error)}</p></div>' if error else ""
        replacements = {
            '__SITE_NAME__':html.escape(admin_panel.get('site_name',DB),quote=True),
            '__COPYRIGHT__':html.escape(admin_panel.get('copyright',DB).replace('{ano}',str(date.today().year)),quote=True),
            "__AUTH_VIEW__": view,
            "__REGISTRATION_STATE__": "enabled" if can_register else "disabled",
            "<!--AUTH_ERROR-->": message,
            "__REGISTER_NAME__": html.escape(str(values.get("name", "")), quote=True),
            "__REGISTER_USERNAME__": html.escape(str(values.get("username", "")), quote=True),
            "__REGISTER_EMAIL__": html.escape(str(values.get("email", "")), quote=True),
        }
        for marker, replacement in replacements.items():
            template = template.replace(marker, replacement)
        data = template.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.security_headers(); self.end_headers(); self.wfile.write(data)

    def set_session_and_redirect(self, username, *, bootstrap_admin=False):
        secure = "; Secure" if security.production() or self.headers.get("X-Forwarded-Proto") == "https" or os.environ.get("RADAR_SECURE_COOKIES") == "1" else ""
        self.send_response(303); self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"radar_session={self.session_token(username, bootstrap_admin=bootstrap_admin)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200{secure}")
        self.security_headers(); self.end_headers()

    def require_auth(self):
        username = os.environ.get("RADAR_ADMIN_USER", "")
        password = os.environ.get("RADAR_ADMIN_PASSWORD", "")
        with connect() as db:
            has_accounts = bool(db.execute("SELECT 1 FROM user_accounts WHERE is_active=1 LIMIT 1").fetchone())
        if not security.production() and (not username or not password) and not has_accounts:
            return True
        if self.valid_session(): return True
        header = self.headers.get("Authorization", "")
        if not security.production() and username and password and header.startswith("Basic "):
            try:
                supplied = base64.b64decode(header[6:]).decode("utf-8")
                expected = f"{username}:{password}"
                if hmac.compare_digest(supplied, expected): return True
            except (ValueError, UnicodeDecodeError):
                pass
        if self.path.startswith("/api/"):
            return self.send_json({"erro":"Autenticação necessária"},401) or False
        self.send_response(303); self.send_header("Location", "/login")
        self.security_headers(); self.end_headers()
        return False

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=(), payment=()')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https://brasilapi.com.br; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if security.production(): self.send_header('Strict-Transport-Security','max-age=31536000')

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length",str(len(body)))
        self.security_headers(); self.end_headers(); self.wfile.write(body)

    def send_csv(self, text, filename):
        body = ("\ufeff" + text).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.security_headers(); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            try:
                with connect() as db: db.execute("SELECT 1").fetchone()
                return self.send_json({"status":"ok"})
            except sqlite3.Error: return self.send_json({"status":"error"},503)
        if parsed.path == "/login":
            if self.valid_session():
                self.send_response(303); self.send_header("Location", "/")
                self.security_headers(); self.end_headers(); return
            mode = parse_qs(parsed.query).get("mode", ["login"])[0]
            return self.render_auth_page(mode)
        if parsed.path in ("/style.css", "/visual.css", "/auth.js", "/icon.svg", "/react-login.css", "/react-login.js") or parsed.path.startswith("/fonts/"):
            if not security.safe_static_path(parsed.path): return self.send_error(404)
            try:
                path = (STATIC / parsed.path.lstrip("/")).resolve()
                path.relative_to(STATIC.resolve())
                data = path.read_bytes()
            except (FileNotFoundError, ValueError):
                return self.send_error(404)
            self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length",str(len(data))); self.security_headers(); self.end_headers(); self.wfile.write(data); return
        if parsed.path == "/logout":
            self.send_response(303); self.send_header("Location","/login")
            self.send_header("Set-Cookie","radar_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
            self.security_headers(); self.end_headers(); return
        if not self.require_auth(): return
        if parsed.path in ('/ajuda','/ajuda/'):
            self.send_response(303);self.send_header('Location','/#ajuda');self.security_headers();self.end_headers();return
        if parsed.path=='/api/help':
            with connect() as db:result=help_center.listing(db,self.session_is_admin(),owner=self.session_owner_id())
            return self.send_json(result)
        if parsed.path in ('/admin','/admin/','/admin.html') or parsed.path.startswith('/api/admin/'):
            return admin_http.handle_get(self,globals(),parsed.path)
        if parsed.path == '/api/sales-ops':
            return sales_ops.handle(self,globals(),parsed)
        if parsed.path=='/api/runtime':
            return self.send_json({**admin_panel.public_config(DB),'is_admin':self.session_is_admin()})
        if parsed.path == '/api/discovery':
            with connect() as db: result=discovery.snapshot(db,self.session_owner_id())
            return self.send_json(result)
        if parsed.path == '/api/discovery/recommendations':
            try:
                with connect() as db: result=discovery.recommendations(db,self.session_owner_id(),parse_qs(parsed.query))
                return self.send_json(result)
            except ValueError as error: return self.send_json({'erro':str(error)},400)
        if parsed.path == '/api/discovery/notifications':
            with connect() as db: result=discovery.notifications(db,self.session_owner_id())
            return self.send_json(result)
        if parsed.path == '/api/discovery/sources':
            with connect() as db:
                rows=db.execute('SELECT d.source_key,d.metadata_json,p.id,p.name,p.city,p.phone,p.email,p.website FROM discovery_sources d JOIN prospect_inbox p ON p.id=d.prospect_id WHERE d.owner_id=? ORDER BY d.last_seen_at DESC LIMIT 50',(self.session_owner_id(),)).fetchall()
                items=[{**dict(r),'metadata':json.loads(r['metadata_json'])} for r in rows]
                for item in items: item.pop('metadata_json',None)
            return self.send_json({'items':items})
        if parsed.path == "/api/companies":
            p = parse_qs(parsed.query); where, vals = filters(p, owner_id=self.session_owner_id())
            try:
                page = max(1, int(p.get("page",["1"])[0])); size = min(100, max(1,int(p.get("size",["20"])[0])))
            except ValueError:
                return self.send_json({'erro':'Paginação inválida'},400)
            source_values = [self.session_owner_id()]
            with connect() as db:
                total = db.execute(f"SELECT COUNT(*) FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where}", source_values + vals).fetchone()[0]
                rows = db.execute(f"SELECT * FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} ORDER BY favorito DESC, data_abertura DESC, id DESC LIMIT ? OFFSET ?", source_values + vals + [size,(page-1)*size]).fetchall()
            items = [dict(r) for r in rows]
            for item in items: item["lead_score"] = score_company(item)
            return self.send_json({"items":items,"total":total,"page":page,"size":size})
        if parsed.path == "/api/sync":
            state = SYNC.snapshot()
            with connect() as db:
                db.execute("CREATE TABLE IF NOT EXISTS sync_meta(key TEXT PRIMARY KEY,value TEXT)")
                state["local"] = {row[0]:row[1] for row in db.execute("SELECT key,value FROM sync_meta")}
            if state["status"] == "idle" and state["local"].get("competencia"):
                state.update(status="complete", fase="Base oficial atualizada", progresso=100,
                             competencia=state["local"]["competencia"],
                             mensagem=f"Competência {state['local']['competencia']} disponível")
            return self.send_json(state)
        if parsed.path == "/api/monitor":
            return self.send_json(MONITOR.snapshot())
        if parsed.path == "/api/profiles":
            owner_id = self.session_owner_id()
            with connect() as db:
                rows = db.execute("""SELECT * FROM prospecting_profiles
                    WHERE is_system=1 OR owner_id=? ORDER BY is_system DESC, created_at, name""", (owner_id,)).fetchall()
                profiles = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["filters"] = json.loads(item.pop("filters_json"))
                    except (json.JSONDecodeError, TypeError):
                        item["filters"] = {}
                        item.pop("filters_json", None)
                    where, values = filters({key: [str(value)] for key, value in item["filters"].items()}, owner_id=self.session_owner_id())
                    item["companies"] = db.execute(f"SELECT COUNT(*) FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where}", [owner_id] + values).fetchone()[0]
                    item["lead_count"] = db.execute("SELECT COUNT(*) FROM profile_leads WHERE profile_id=?", (item["id"],)).fetchone()[0]
                    profiles.append(item)
            return self.send_json({"items": profiles})
        if parsed.path == "/api/profile-leads":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            if not profile_id:
                return self.send_json({"erro": "Selecione um perfil"}, 400)
            try:
                page = max(1, int(params.get("page", ["1"])[0]))
                size = min(100, max(1, int(params.get("size", ["24"])[0])))
            except (TypeError, ValueError):
                return self.send_json({"erro": "Paginação inválida"}, 400)
            with connect() as db:
                profile = db.execute("""SELECT id,name,is_system FROM prospecting_profiles
                    WHERE id=? AND (is_system=1 OR owner_id=?)""", (profile_id, self.session_owner_id())).fetchone()
                if not profile:
                    return self.send_json({"erro": "Perfil não encontrado"}, 404)
                total = db.execute("SELECT COUNT(*) FROM profile_leads WHERE profile_id=?", (profile_id,)).fetchone()[0]
                rows = db.execute(f"""SELECT companies.*, pl.added_at AS carteira_adicionado_em
                    FROM profile_leads pl JOIN {ACCOUNT_COMPANY_SOURCE} ON companies.cnpj=pl.cnpj
                    WHERE pl.profile_id=?
                    ORDER BY companies.favorito DESC, companies.data_abertura DESC, pl.added_at DESC
                    LIMIT ? OFFSET ?""", (self.session_owner_id(), profile_id, size, (page - 1) * size)).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                item["lead_score"] = score_company(item)
            return self.send_json({"profile": dict(profile), "items": items, "total": total, "page": page, "size": size})
        if parsed.path == "/api/profile-memberships":
            cnpj = ''.join(c for c in str(parse_qs(parsed.query).get("cnpj", [""])[0]).upper() if c.isalnum())
            if len(cnpj) != 14:
                return self.send_json({"erro": "CNPJ inválido"}, 400)
            with connect() as db:
                rows = db.execute("""SELECT p.id,p.name,p.description, p.is_system,
                    CASE WHEN pl.cnpj IS NULL THEN 0 ELSE 1 END AS selected
                    FROM prospecting_profiles p
                    LEFT JOIN profile_leads pl ON pl.profile_id=p.id AND pl.cnpj=?
                    WHERE p.is_system=0 AND p.owner_id=? ORDER BY p.name""", (cnpj, self.session_owner_id())).fetchall()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path == "/api/message-templates":
            owner_id = self.session_owner_id()
            with connect() as db:
                self.ensure_default_message_template(db, owner_id)
                rows = db.execute(
                    """SELECT id,name,body,is_default,created_at,updated_at
                       FROM message_templates WHERE owner_id=?
                       ORDER BY is_default DESC, name COLLATE NOCASE""",
                    (owner_id,),
                ).fetchall()
                db.commit()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path in ('/api/commercial','/api/commercial-report.pdf'):
            params = parse_qs(parsed.query)
            profile_id = str(params.get('profile_id',[''])[0]).strip()
            try: start,end = activity_date_range(params)
            except ValueError: return self.send_json({'erro':'Período inválido'},400)
            with connect() as db:
                profile = self.owned_sales_profile(db,profile_id)
                if not profile: return self.send_json({'erro':'Área comercial não encontrada para esta conta'},404)
                data = commercial.analytics(db,profile_id,start,end,str(params.get('campaign',[''])[0])[:120])
            if parsed.path.endswith('.pdf'):
                if data['summary']['total'] > 10000: return self.send_json({'erro':'Restrinja o período ou campanha para até 10 mil leads'},413)
                try:
                    from reports import commercial_pdf
                    body = commercial_pdf(profile['name'],data,{key:admin_panel.get(key,DB) for key in ('site_name','report_title','report_footer')})
                except ImportError:
                    return self.send_json({'erro':'Instale as dependências de requirements.txt para gerar PDF'},503)
                self.send_response(200);self.send_header('Content-Type','application/pdf')
                self.send_header('Content-Disposition','attachment; filename="radar-relatorio-comercial.pdf"')
                self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
                self.security_headers();self.end_headers();self.wfile.write(body);return
            data.pop('items',None)
            return self.send_json(data)
        if parsed.path == '/api/commercial-archive':
            params = parse_qs(parsed.query);profile_id=str(params.get('profile_id',[''])[0])
            with connect() as db:
                if not self.owned_sales_profile(db,profile_id): return self.send_json({'erro':'Área não encontrada'},404)
                items=[dict(x) for x in db.execute('SELECT * FROM commercial_archive WHERE profile_id=? ORDER BY id DESC LIMIT 100',(profile_id,))]
            return self.send_json({'items':items})
        if parsed.path == '/api/prospects':
            params = parse_qs(parsed.query)
            try:
                page = max(1, int(params.get('page', ['1'])[0]))
            except ValueError: return self.send_json({'erro': 'Página inválida'}, 400)
            owner = self.session_owner_id(); clauses = ['owner_id=?']; values = [owner]
            status = params.get('status', [''])[0]
            if status:
                if status not in prospecting.STATUSES: return self.send_json({'erro':'Situação inválida'},400)
                clauses.append('status=?'); values.append(status)
            search = params.get('q', [''])[0][:180].strip()
            if search:
                clauses.append('(name LIKE ? OR company LIKE ? OR phone LIKE ? OR email LIKE ? OR campaign LIKE ?)')
                values.extend(['%'+search+'%'] * 5)
            where = ' AND '.join(clauses)
            with connect() as db:
                total = db.execute(f'SELECT COUNT(*) FROM prospect_inbox WHERE {where}', values).fetchone()[0]
                items = [dict(row) for row in db.execute(f'SELECT * FROM prospect_inbox WHERE {where} ORDER BY updated_at DESC,id LIMIT 50 OFFSET ?',values+[(page-1)*50])]
                for item in items:
                    item['linked']=db.execute('SELECT COUNT(*) FROM prospect_links WHERE prospect_id=? AND owner_id=?',(item['id'],owner)).fetchone()[0]
                    item['do_not_contact']=bool(db.execute('SELECT 1 FROM contact_suppression cs WHERE cs.owner_id=? AND (cs.cnpj=? OR EXISTS (SELECT 1 FROM prospect_links pl WHERE pl.prospect_id=? AND pl.owner_id=? AND pl.cnpj=cs.cnpj)) LIMIT 1',(owner,item['cnpj'],item['id'],owner)).fetchone())
                    source=db.execute('SELECT metadata_json FROM discovery_sources WHERE prospect_id=? AND owner_id=? ORDER BY last_seen_at DESC LIMIT 1',(item['id'],owner)).fetchone()
                    item['provenance']=json.loads(source[0]) if source else None
                overview=prospecting.summary(db,owner)
            return self.send_json({'items':items,'total':total,'page':page,'size':50,'summary':overview})
        if parsed.path=='/api/prospects/options':
            with connect() as db:
                profiles=[dict(r) for r in db.execute('SELECT id,name FROM sales_profiles WHERE owner_id=? ORDER BY name',(self.session_owner_id(),))]
            return self.send_json({'profiles':profiles})
        if parsed.path=='/api/prospects/company':
            cnpj=parse_qs(parsed.query).get('cnpj',[''])[0]
            if not re.fullmatch('[A-Z0-9]{14}',cnpj):return self.send_json({'erro':'CNPJ inválido'},400)
            with connect() as db:
                row=db.execute('SELECT cnpj,razao_social,nome_fantasia,municipio,situacao FROM companies WHERE cnpj=?',(cnpj,)).fetchone()
            return self.send_json({'item':dict(row) if row else None})
        if parsed.path=='/api/prospects/history':
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            with connect() as db:
                if not db.execute('SELECT 1 FROM prospect_inbox WHERE id=? AND owner_id=?',(identifier,self.session_owner_id())).fetchone():return self.send_json({'erro':'Contato não encontrado'},404)
                items=[dict(x) for x in db.execute('SELECT event,details,created_at FROM prospect_history WHERE prospect_id=? AND owner_id=? ORDER BY id DESC LIMIT 50',(identifier,self.session_owner_id()))]
            return self.send_json({'items':items})
        if parsed.path == "/api/team-profiles":
            scope, scope_values = self.sales_profile_scope("p")
            with connect() as db:
                rows = db.execute(f"""SELECT p.*, COUNT(spl.cnpj) AS lead_count,
                    COALESCE(SUM(CASE WHEN spl.favorito=1 THEN 1 ELSE 0 END),0) AS favorite_count,
                    MAX(spl.updated_at) AS last_activity
                    FROM sales_profiles p
                    LEFT JOIN sales_profile_leads spl ON spl.profile_id=p.id
                    WHERE {scope}
                    GROUP BY p.id ORDER BY p.name COLLATE NOCASE""", scope_values).fetchall()
            return self.send_json({"items": [dict(row) for row in rows], "can_manage_team": self.session_is_admin()})
        if parsed.path == "/api/team-dashboard":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            if not profile_id:
                return self.send_json({"erro": "Selecione um responsável"}, 400)
            with connect() as db:
                profile = self.owned_sales_profile(db, profile_id)
                if not profile:
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                summary = dict(db.execute("""SELECT COUNT(*) AS total,
                    SUM(CASE WHEN lead_status NOT IN ('convertido','descartado','concluido') THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN first_contact_at IS NOT NULL THEN 1 ELSE 0 END) AS contacted,
                    SUM(CASE WHEN first_contact_at IS NULL AND lead_status NOT IN ('convertido','descartado','concluido') THEN 1 ELSE 0 END) AS uncontacted,
                    SUM(CASE WHEN next_action_at IS NOT NULL AND datetime(next_action_at)<datetime('now','localtime') AND lead_status NOT IN ('convertido','descartado','concluido') THEN 1 ELSE 0 END) AS overdue,
                    SUM(CASE WHEN date(next_action_at)=date('now','localtime') AND lead_status NOT IN ('convertido','descartado','concluido') THEN 1 ELSE 0 END) AS due_today,
                    SUM(CASE WHEN (next_action_at IS NULL OR TRIM(COALESCE(next_action,''))='') AND lead_status NOT IN ('convertido','descartado','concluido') THEN 1 ELSE 0 END) AS without_next_action,
                    SUM(CASE WHEN lead_status='negociacao' THEN 1 ELSE 0 END) AS negotiation_count,
                    SUM(CASE WHEN whatsapp_status='confirmed' THEN 1 ELSE 0 END) AS whatsapp_confirmed,
                    SUM(CASE WHEN whatsapp_status='not_found' THEN 1 ELSE 0 END) AS whatsapp_not_found,
                    SUM(CASE WHEN whatsapp_status='invalid' THEN 1 ELSE 0 END) AS whatsapp_invalid,
                    SUM(CASE WHEN whatsapp_status='pending' OR TRIM(COALESCE(whatsapp_status,''))='' THEN 1 ELSE 0 END) AS whatsapp_pending,
                    COALESCE(SUM(CASE WHEN lead_status NOT IN ('convertido','descartado','concluido') THEN offered_value_cents ELSE 0 END),0) AS offered_value_cents,
                    COALESCE(SUM(CASE WHEN lead_status NOT IN ('convertido','descartado','concluido') THEN negotiated_value_cents ELSE 0 END),0) AS negotiated_value_cents,
                    COALESCE(SUM(CASE WHEN lead_status='convertido' THEN closed_value_cents ELSE 0 END),0) AS closed_value_cents,
                    ROUND(AVG(CASE WHEN first_contact_at>=added_at THEN julianday(first_contact_at)-julianday(added_at) END),1) AS avg_first_contact_days,
                    ROUND(AVG(CASE WHEN lead_status='convertido' AND closed_at>=added_at THEN julianday(closed_at)-julianday(added_at) END),1) AS avg_close_days
                    FROM sales_profile_leads WHERE profile_id=?""", (profile_id,)).fetchone())
                stages = [dict(row) for row in db.execute("""SELECT lead_status AS key,COUNT(*) AS total,
                    COALESCE(SUM(negotiated_value_cents),0) AS negotiated_value_cents,
                    COALESCE(SUM(closed_value_cents),0) AS closed_value_cents
                    FROM sales_profile_leads WHERE profile_id=? GROUP BY lead_status ORDER BY total DESC""", (profile_id,))]
                outcomes = [dict(row) for row in db.execute("""SELECT COALESCE(NULLIF(contact_outcome,''),'nao_informado') AS key,COUNT(*) AS total
                    FROM sales_profile_leads WHERE profile_id=? GROUP BY COALESCE(NULLIF(contact_outcome,''),'nao_informado') ORDER BY total DESC""", (profile_id,))]
            summary["contact_rate"] = round((summary.get("contacted") or 0) * 100 / (summary.get("total") or 1), 1)
            return self.send_json({"profile": dict(profile), "summary": summary, "stages": stages, "outcomes": outcomes})
        if parsed.path == "/api/team-leads":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            if not profile_id:
                return self.send_json({"erro": "Selecione um perfil individual"}, 400)
            view = str(params.get("view", ["all"])[0]).strip().lower()
            if view not in ("all", "favorites"):
                view = "all"
            status = str(params.get("status", [""])[0]).strip().lower()
            if status and status not in ("novo", "qualificado", "contatado", "negociacao", "convertido", "descartado", "concluido"):
                return self.send_json({"erro": "Etapa inválida"}, 400)
            focus = str(params.get("focus", ["all"])[0]).strip().lower()
            if focus not in ("all", "overdue", "today", "no_action", "uncontacted", "negotiation", "stalled"):
                focus = "all"
            sort = str(params.get("sort", ["priority"])[0]).strip().lower()
            if sort not in ("priority", "deadline", "recent", "value"):
                sort = "priority"
            search = str(params.get("q", [""])[0]).strip()[:120]
            try:
                page = max(1, int(params.get("page", ["1"])[0]))
                size = min(100, max(1, int(params.get("size", ["24"])[0])))
            except (TypeError, ValueError):
                return self.send_json({"erro": "Paginação inválida"}, 400)
            where = ["spl.profile_id=?"]
            values = [profile_id]
            try:
                activity_from, activity_to = activity_date_range(params)
            except ValueError:
                return self.send_json({"erro": "Período de atividade inválido"}, 400)
            if activity_from or activity_to:
                activity_where = ["h.profile_id=spl.profile_id", "h.cnpj=spl.cnpj"]
                if activity_from:
                    activity_where.append("date(h.created_at)>=?"); values.append(activity_from)
                if activity_to:
                    activity_where.append("date(h.created_at)<=?"); values.append(activity_to)
                where.append("EXISTS (SELECT 1 FROM sales_lead_history h WHERE " + " AND ".join(activity_where) + ")")
            whatsapp = str(params.get("whatsapp", [""])[0]).strip().lower()
            if whatsapp and whatsapp not in ("confirmed", "not_found", "invalid", "pending"):
                return self.send_json({"erro": "Situação do WhatsApp inválida"}, 400)
            if whatsapp:
                where.append("COALESCE(NULLIF(spl.whatsapp_status,''),'pending')=?"); values.append(whatsapp)
            if view == "favorites":
                where.append("spl.favorito=1")
            if status:
                where.append("spl.lead_status=?"); values.append(status)
            if focus == "overdue":
                where.append("spl.next_action_at IS NOT NULL AND datetime(spl.next_action_at)<datetime('now','localtime') AND spl.lead_status NOT IN ('convertido','descartado','concluido')")
            elif focus == "today":
                where.append("date(spl.next_action_at)=date('now','localtime') AND spl.lead_status NOT IN ('convertido','descartado','concluido')")
            elif focus == "no_action":
                where.append("(spl.next_action_at IS NULL OR TRIM(COALESCE(spl.next_action,''))='') AND spl.lead_status NOT IN ('convertido','descartado','concluido')")
            elif focus == "uncontacted":
                where.append("spl.first_contact_at IS NULL AND spl.lead_status NOT IN ('convertido','descartado','concluido')")
            elif focus == "negotiation":
                where.append("spl.lead_status='negociacao'")
            elif focus == "stalled":
                with connect() as config_db: stalled_days=commercial.settings(config_db,profile_id)['stalled_days']
                where.append("spl.lead_status='negociacao' AND datetime(COALESCE(spl.last_contact_at,spl.updated_at))<datetime('now','localtime',?)")
                values.append(f'-{stalled_days} days')
            if search:
                digits = ''.join(char for char in search if char.isdigit())
                term = f"%{search.lower()}%"
                where.append("(LOWER(COALESCE(c.nome_fantasia,'')) LIKE ? OR LOWER(COALESCE(c.razao_social,'')) LIKE ? OR c.cnpj LIKE ?)")
                values.extend([term, term, f"%{digits or search}%"])
                # Search public and seller-corrected phones without punctuation.
                if digits and not any(char.isalpha() for char in search):
                    phone_columns = []
                    for column in ("c.telefone", "spl.whatsapp_phone"):
                        normalized = f"COALESCE({column},'')"
                        for separator in (' ', '+', '-', '(', ')', '.', '/', '\t', '\u00a0'):
                            normalized = f"REPLACE({normalized},'{separator}','')"
                        phone_columns.append(f"{normalized} LIKE ?")
                    where[-1] = '(' + where[-1] + ' OR ' + ' OR '.join(phone_columns) + ')'
                    values.extend([f"%{digits}%", f"%{digits}%"])
            condition = " AND ".join(where)
            order_by = {
                "deadline": "CASE WHEN spl.next_action_at IS NULL THEN 1 ELSE 0 END, datetime(spl.next_action_at), spl.updated_at DESC",
                "recent": "spl.updated_at DESC, c.data_abertura DESC, c.id DESC",
                "value": "spl.negotiated_value_cents DESC, spl.offered_value_cents DESC, spl.updated_at DESC",
                "priority": "CASE WHEN spl.next_action_at IS NOT NULL AND datetime(spl.next_action_at)<datetime('now','localtime') AND spl.lead_status NOT IN ('convertido','descartado','concluido') THEN 0 WHEN date(spl.next_action_at)=date('now','localtime') AND spl.lead_status NOT IN ('convertido','descartado','concluido') THEN 1 WHEN spl.first_contact_at IS NULL AND spl.lead_status NOT IN ('convertido','descartado','concluido') THEN 2 WHEN spl.lead_status='negociacao' THEN 3 ELSE 4 END, spl.favorito DESC, spl.updated_at DESC",
            }[sort]
            with connect() as db:
                profile = self.owned_sales_profile(db, profile_id)
                if not profile:
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                total = db.execute(f"SELECT COUNT(*) FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj WHERE {condition}", values).fetchone()[0]
                rows = db.execute(f"""SELECT c.*, spl.profile_id, spl.added_at AS carteira_adicionado_em,
                    spl.updated_at AS profile_updated_at, spl.favorito AS profile_favorito,
                    spl.lead_status AS profile_lead_status, spl.observacoes AS profile_observacoes,
                    spl.estrategia AS profile_estrategia, spl.contact_outcome AS profile_contact_outcome,
                    spl.next_action AS profile_next_action, spl.next_action_at AS profile_next_action_at,
                    spl.last_contact_at AS profile_last_contact_at, spl.first_contact_at AS profile_first_contact_at,
                    spl.closed_at AS profile_closed_at, spl.offered_value_cents AS profile_offered_value_cents,
                    spl.negotiated_value_cents AS profile_negotiated_value_cents,
                    spl.closed_value_cents AS profile_closed_value_cents,
                    COALESCE(NULLIF(spl.whatsapp_status,''),'pending') AS profile_whatsapp_status,
                    spl.whatsapp_phone AS profile_whatsapp_phone,
                    spl.whatsapp_checked_at AS profile_whatsapp_checked_at,
                    spl.campaign AS profile_campaign,spl.persona AS profile_persona,
                    spl.lead_origin AS profile_lead_origin,spl.loss_reason AS profile_loss_reason
                    FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
                    WHERE {condition}
                    ORDER BY {order_by}
                    LIMIT ? OFFSET ?""", values + [size, (page - 1) * size]).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                item["lead_score"] = score_company(item)
            with connect() as privacy_db:
                sales_ops.decorate(privacy_db,profile['owner_id'] or self.session_owner_id(),items)
            return self.send_json({"profile": dict(profile), "items": items, "total": total, "page": page, "size": size, "view": view, "status": status, "focus": focus, "sort": sort, "q": search})
        if parsed.path == "/api/team-memberships":
            cnpj = ''.join(c for c in str(parse_qs(parsed.query).get("cnpj", [""])[0]).upper() if c.isalnum())
            if len(cnpj) != 14:
                return self.send_json({"erro": "CNPJ inválido"}, 400)
            scope, scope_values = self.sales_profile_scope("p")
            with connect() as db:
                rows = db.execute(f"""SELECT p.id,p.name,p.role,p.email,p.initials,p.color,
                    CASE WHEN spl.cnpj IS NULL THEN 0 ELSE 1 END AS selected,
                    COALESCE(spl.favorito,0) AS favorito, COALESCE(spl.lead_status,'novo') AS lead_status,
                    COALESCE(spl.observacoes,'') AS observacoes, COALESCE(spl.estrategia,'') AS estrategia,
                    COALESCE(spl.contact_outcome,'') AS contact_outcome,
                    COALESCE(spl.next_action,'') AS next_action, spl.next_action_at, spl.last_contact_at,
                    spl.first_contact_at, spl.closed_at,
                    COALESCE(spl.offered_value_cents,0) AS offered_value_cents,
                    COALESCE(spl.negotiated_value_cents,0) AS negotiated_value_cents,
                    COALESCE(spl.closed_value_cents,0) AS closed_value_cents,
                    COALESCE(spl.campaign,'') AS campaign,COALESCE(spl.persona,'') AS persona,
                    COALESCE(spl.lead_origin,'') AS lead_origin,COALESCE(spl.loss_reason,'') AS loss_reason,
                    COALESCE(NULLIF(spl.whatsapp_status,''),'pending') AS whatsapp_status,
                    COALESCE(spl.whatsapp_phone,'') AS whatsapp_phone,
                    spl.whatsapp_checked_at,
                    spl.updated_at
                    FROM sales_profiles p
                    LEFT JOIN sales_profile_leads spl ON spl.profile_id=p.id AND spl.cnpj=?
                    WHERE {scope} ORDER BY p.name COLLATE NOCASE""", [cnpj] + scope_values).fetchall()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path == "/api/team-activity":
            params = parse_qs(parsed.query)
            profile_id = str(params.get('profile_id', [''])[0]).strip()
            try:
                start, end = activity_date_range(params)
                page = max(1, int(params.get('page', ['1'])[0]))
            except ValueError:
                return self.send_json({"erro": "Período ou página inválidos"}, 400)
            clauses = ['h.profile_id=?']; values = [profile_id]
            if start:
                clauses.append('date(h.created_at)>=?'); values.append(start)
            if end:
                clauses.append('date(h.created_at)<=?'); values.append(end)
            condition = ' AND '.join(clauses)
            with connect() as db:
                if not self.owned_sales_profile(db, profile_id):
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                total = db.execute(f'SELECT COUNT(*) FROM sales_lead_history h WHERE {condition}', values).fetchone()[0]
                rows = db.execute(f'''SELECT h.*,c.nome_fantasia,c.razao_social FROM sales_lead_history h
                    JOIN companies c ON c.cnpj=h.cnpj WHERE {condition}
                    ORDER BY h.created_at DESC,h.id DESC LIMIT 50 OFFSET ?''', values + [(page-1)*50]).fetchall()
            return self.send_json({"items": [dict(row) for row in rows], "total": total, "page": page})
        if parsed.path == "/api/team-lead-history":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            cnpj = ''.join(c for c in str(params.get("cnpj", [""])[0]).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            with connect() as db:
                if not self.owned_sales_profile(db, profile_id) or not db.execute("SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj)).fetchone():
                    return self.send_json({"erro": "Lead não encontrado no painel deste responsável"}, 404)
                rows = db.execute("""SELECT id,event_type,title,details,created_at,changes_json
                    FROM sales_lead_history WHERE profile_id=? AND cnpj=?
                    ORDER BY created_at DESC,id DESC LIMIT 100""", (profile_id, cnpj)).fetchall()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path == "/api/team-leads.csv":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            if not profile_id:
                return self.send_json({"erro": "Selecione um perfil individual"}, 400)
            view = str(params.get("view", ["all"])[0]).strip().lower()
            if view not in ("all", "favorites"):
                view = "all"
            status = str(params.get("status", [""])[0]).strip().lower()
            if status and status not in ("novo", "qualificado", "contatado", "negociacao", "convertido", "descartado", "concluido"):
                return self.send_json({"erro": "Etapa inválida"}, 400)
            where = ["spl.profile_id=?", "NOT EXISTS (SELECT 1 FROM contact_suppression cs JOIN sales_profiles cp ON cp.owner_id=cs.owner_id WHERE cp.id=spl.profile_id AND cs.cnpj=spl.cnpj)"]; values = [profile_id]
            if view == "favorites": where.append("spl.favorito=1")
            if status: where.append("spl.lead_status=?"); values.append(status)
            whatsapp = str(params.get("whatsapp", [""])[0]).strip().lower()
            if whatsapp:
                if whatsapp not in ("pending", "confirmed", "not_found", "invalid"):
                    return self.send_json({"erro": "Situação do WhatsApp inválida"}, 400)
                where.append("COALESCE(NULLIF(spl.whatsapp_status,''),'pending')=?"); values.append(whatsapp)
            condition = " AND ".join(where)
            with connect() as db:
                profile = self.owned_sales_profile(db, profile_id)
                if not profile:
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                rows = db.execute(f"""SELECT c.*, spl.favorito AS profile_favorito,
                    spl.lead_status AS profile_lead_status, spl.observacoes AS profile_observacoes,
                    spl.estrategia AS profile_estrategia, spl.contact_outcome AS profile_contact_outcome,
                    spl.next_action AS profile_next_action, spl.next_action_at AS profile_next_action_at,
                    spl.last_contact_at AS profile_last_contact_at, spl.first_contact_at AS profile_first_contact_at,
                    spl.closed_at AS profile_closed_at, spl.offered_value_cents AS profile_offered_value_cents,
                    spl.negotiated_value_cents AS profile_negotiated_value_cents, spl.closed_value_cents AS profile_closed_value_cents,
                    COALESCE(NULLIF(spl.whatsapp_status,''),'pending') AS profile_whatsapp_status,
                    spl.whatsapp_phone AS profile_whatsapp_phone, spl.whatsapp_checked_at AS profile_whatsapp_checked_at,
                    spl.campaign AS profile_campaign, spl.persona AS profile_persona,
                    spl.lead_origin AS profile_lead_origin, spl.loss_reason AS profile_loss_reason
                    FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
                    WHERE {condition} ORDER BY spl.favorito DESC, spl.updated_at DESC, c.data_abertura DESC""", values).fetchall()
            output = io.StringIO(newline="")
            delimiter = "," if str(params.get("delimiter", ["semicolon"])[0]).lower() == "comma" else ";"
            writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
            whatsapp_labels = {"pending":"Pendente", "confirmed":"Confirmado", "not_found":"Não localizado", "invalid":"Inválido"}
            field_map = {
                "empresa": ("Empresa", lambda x: x.get("nome_fantasia") or x.get("razao_social") or ""),
                "razao_social": ("Razão social", lambda x: x.get("razao_social", "")), "cnpj": ("CNPJ", lambda x: x.get("cnpj", "")),
                "telefone": ("Telefone original", lambda x: x.get("telefone", "")), "whatsapp_phone": ("Telefone WhatsApp", lambda x: x.get("profile_whatsapp_phone") or x.get("telefone", "")),
                "whatsapp_status": ("Situação WhatsApp", lambda x: whatsapp_labels.get(x.get("profile_whatsapp_status", "pending"), "Pendente")),
                "email": ("E-mail", lambda x: x.get("email", "")), "municipio": ("Município", lambda x: x.get("municipio", "")),
                "regiao": ("Região", lambda x: x.get("regiao", "")), "segmento": ("Segmento", lambda x: x.get("segmento", "")),
                "cnae": ("CNAE", lambda x: x.get("cnae", "")), "cnae_descricao": ("Descrição do CNAE", lambda x: x.get("cnae_descricao", "")),
                "data_abertura": ("Data de abertura", lambda x: x.get("data_abertura", "")), "situacao": ("Situação cadastral", lambda x: x.get("situacao", "")),
                "potencial": ("Potencial", lambda x: x.get("lead_score", 0)), "favorito": ("Favorito", lambda x: "Sim" if x.get("profile_favorito") else "Não"),
                "etapa": ("Etapa", lambda x: LEAD_STAGES.get(x.get("profile_lead_status", "novo"), x.get("profile_lead_status", "novo"))),
                "resultado": ("Resultado do contato", lambda x: CONTACT_OUTCOMES.get(x.get("profile_contact_outcome", ""), x.get("profile_contact_outcome", ""))),
                "proxima_acao": ("Próxima ação", lambda x: x.get("profile_next_action", "")), "data_proxima_acao": ("Data da próxima ação", lambda x: x.get("profile_next_action_at", "")),
                "valor_ofertado": ("Valor ofertado", lambda x: (x.get("profile_offered_value_cents") or 0)/100), "valor_negociado": ("Valor negociado", lambda x: (x.get("profile_negotiated_value_cents") or 0)/100),
                "valor_fechado": ("Valor fechado", lambda x: (x.get("profile_closed_value_cents") or 0)/100), "observacoes": ("Observações", lambda x: x.get("profile_observacoes", "")),
                "estrategia": ("Estratégia", lambda x: x.get("profile_estrategia", "")),
                "campanha": ("Campanha / ICP", lambda x: x.get("profile_campaign", "")),
                "persona": ("Cargo / persona", lambda x: x.get("profile_persona", "")),
                "origem": ("Origem do lead", lambda x: x.get("profile_lead_origin", "")),
                "motivo_perda": ("Motivo de perda", lambda x: commercial.LOSS_REASONS.get(x.get("profile_loss_reason", ""), "Não informado")),
            }
            default_fields = ["empresa","cnpj","telefone","whatsapp_phone","whatsapp_status","email","municipio","segmento","etapa","resultado","proxima_acao","data_proxima_acao","valor_negociado","valor_fechado"]
            requested_fields = [field for field in str(params.get("fields", [""])[0]).split(",") if field in field_map]
            selected_fields = requested_fields or default_fields
            writer.writerow([field_map[field][0] for field in selected_fields])
            for row in rows:
                item = dict(row); item["lead_score"] = score_company(item)
                writer.writerow([security.csv_cell(field_map[field][1](item)) for field in selected_fields])
            safe_name = "".join(ch for ch in str(profile["name"]) if ch.isalnum() or ch in " -_").strip() or "perfil"
            requested_name = "".join(ch for ch in str(params.get("filename", [""])[0]) if ch.isalnum() or ch in " -_").strip()[:80]
            file_name = requested_name or f"radar-{safe_name.lower().replace(' ', '-')}-leads"
            return self.send_csv(output.getvalue(), file_name + ".csv")
        if parsed.path == "/api/stats":
            p=parse_qs(parsed.query); where,vals=filters(p, owner_id=self.session_owner_id())
            mei_where,mei_vals=filters(p, {"mei","lead_status","favorito"}, owner_id=self.session_owner_id())
            owner_id = self.session_owner_id()
            state_vals = [owner_id] + vals
            mei_state_vals = [owner_id] + mei_vals
            with connect() as db:
                summary=dict(db.execute(f"""SELECT COUNT(*) total, COALESCE(SUM(mei),0) meis,
                    COUNT(DISTINCT municipio) municipios, COUNT(DISTINCT segmento) segmentos,
                    COALESCE(SUM(CASE WHEN email<>'' OR telefone<>'' THEN 1 ELSE 0 END),0) com_contato,
                    MAX(data_abertura) ultima_data FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where}""",state_vals).fetchone())
                groups=[dict(r) for r in db.execute(f"SELECT segmento label,COUNT(*) value FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} GROUP BY segmento ORDER BY value DESC LIMIT 6",state_vals)]
                cnaes=[dict(r) for r in db.execute(f"SELECT cnae label,MAX(cnae_descricao) description,segmento category,COUNT(*) value FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} AND cnae<>'' GROUP BY cnae,segmento ORDER BY value DESC,cnae LIMIT 8",state_vals)]
                cities=[dict(r) for r in db.execute(f"SELECT municipio label,COUNT(*) value FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} GROUP BY municipio ORDER BY value DESC, municipio LIMIT 5",state_vals)]
                timeline=[dict(r) for r in db.execute(f"SELECT substr(data_abertura,1,7) label,COUNT(*) value FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} AND data_abertura<>'' GROUP BY substr(data_abertura,1,7) ORDER BY label",state_vals)]
                pipeline=[dict(r) for r in db.execute(f"SELECT COALESCE(NULLIF(lead_status,''),'novo') label,COUNT(*) value FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} GROUP BY COALESCE(NULLIF(lead_status,''),'novo')",state_vals)]
                favorites=db.execute(f"SELECT COUNT(*) FROM {ACCOUNT_COMPANY_SOURCE} WHERE {where} AND favorito=1",state_vals).fetchone()[0]
                mei_summary=dict(db.execute(f"""SELECT COUNT(*) total, COUNT(DISTINCT cnae) cnaes,
                    COUNT(DISTINCT municipio) municipios, MAX(data_abertura) ultima_data
                    FROM {ACCOUNT_COMPANY_SOURCE} WHERE {mei_where} AND mei=1""",mei_state_vals).fetchone())
                mei_cnaes=[dict(r) for r in db.execute(f"""SELECT cnae label,MAX(cnae_descricao) description,segmento category,COUNT(*) value
                    FROM {ACCOUNT_COMPANY_SOURCE} WHERE {mei_where} AND mei=1 AND cnae<>''
                    GROUP BY cnae,segmento ORDER BY value DESC,cnae LIMIT 10""",mei_state_vals)]
                mei_groups=[dict(r) for r in db.execute(f"""SELECT segmento label,COUNT(*) value
                    FROM {ACCOUNT_COMPANY_SOURCE} WHERE {mei_where} AND mei=1 AND segmento<>''
                    GROUP BY segmento ORDER BY value DESC,segmento LIMIT 6""",mei_state_vals)]
                mei_cities=[dict(r) for r in db.execute(f"""SELECT municipio label,COUNT(*) value
                    FROM {ACCOUNT_COMPANY_SOURCE} WHERE {mei_where} AND mei=1 AND municipio<>''
                    GROUP BY municipio ORDER BY value DESC,municipio LIMIT 5""",mei_state_vals)]
                mei_timeline=[dict(r) for r in db.execute(f"""SELECT substr(data_abertura,1,7) label,COUNT(*) value
                    FROM {ACCOUNT_COMPANY_SOURCE} WHERE {mei_where} AND mei=1 AND data_abertura<>''
                    GROUP BY substr(data_abertura,1,7) ORDER BY label""",mei_state_vals)]
                summary["base_ultima_data"] = db.execute("SELECT MAX(data_abertura) FROM companies WHERE uf='RS'").fetchone()[0]
                options={k:[r[0] for r in db.execute(f"SELECT DISTINCT {k} FROM companies WHERE {k}<>'' ORDER BY {k}")] for k in ("municipio","regiao","segmento","porte","data_source")}
                options["cnaes"] = [dict(r) for r in db.execute("SELECT cnae codigo,MAX(cnae_descricao) descricao,MAX(segmento) segmento,COUNT(*) empresas FROM companies WHERE cnae<>'' GROUP BY cnae ORDER BY empresas DESC,cnae")]
                opportunity_where, opportunity_vals = filters(p, {"score_min", "lead_status", "favorito"}, owner_id=self.session_owner_id())
                high_clause = f"{opportunity_where} AND {LEAD_SCORE_SQL}>=80"
                opportunity_state_vals = [owner_id] + opportunity_vals
                high_total = db.execute(f"SELECT COUNT(*) FROM {ACCOUNT_COMPANY_SOURCE} WHERE {high_clause}", opportunity_state_vals).fetchone()[0]
                high_contact = db.execute(f"SELECT COUNT(*) FROM {ACCOUNT_COMPANY_SOURCE} WHERE {high_clause} AND (TRIM(COALESCE(email,''))<>'' OR TRIM(COALESCE(telefone,''))<>'')", opportunity_state_vals).fetchone()[0]
                high_mei = db.execute(f"SELECT COUNT(*) FROM {ACCOUNT_COMPANY_SOURCE} WHERE {high_clause} AND mei=1", opportunity_state_vals).fetchone()[0]
                high_rows = db.execute(f"SELECT * FROM {ACCOUNT_COMPANY_SOURCE} WHERE {high_clause} ORDER BY {LEAD_SCORE_SQL} DESC,data_abertura DESC,id DESC LIMIT 8", opportunity_state_vals).fetchall()
                high_items = [dict(row) for row in high_rows]
                for item in high_items:
                    item["lead_score"] = score_company(item)
            return self.send_json({"summary":summary,"groups":groups,"cnaes":cnaes,"cities":cities,"timeline":timeline,
                "pipeline":pipeline,"favorites":favorites,"options":options,"mei_summary":mei_summary,
                "mei_cnaes":mei_cnaes,"mei_groups":mei_groups,"mei_cities":mei_cities,"mei_timeline":mei_timeline,
                "opportunities":{"total":high_total,"with_contact":high_contact,"mei":high_mei,"items":high_items}})
        if parsed.path != '/' and not security.safe_static_path(parsed.path): return self.send_error(404)
        path = STATIC / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        try:
            path=path.resolve(); path.relative_to(STATIC.resolve()); data=path.read_bytes()
        except (FileNotFoundError, ValueError): return self.send_error(404)
        self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length",str(len(data))); self.security_headers(); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        if not self.guard_write(): return
        if self.path == "/login":
            length=min(int(self.headers.get("Content-Length","0")),4096)
            form=parse_qs(self.rfile.read(length).decode("utf-8",errors="replace"))
            username=form.get("username",[""])[0].strip(); password=form.get("password",[""])[0]
            expected_user=os.environ.get("RADAR_ADMIN_USER","").strip(); expected_password=os.environ.get("RADAR_ADMIN_PASSWORD","")
            account = account_by_login(username) if username else None
            reserved_account = bool(account and expected_user and account["username"].casefold() == expected_user.casefold())
            known_principal = bool(account or expected_user and username.casefold()==expected_user.casefold())
            # Shared tunnel sockets may limit unknown-name spray, never lock all
            # known users out. Their strict canonical-account budget is below.
            if not known_principal and not security.LOGIN_EDGE_LIMITER.allowed(self.client_address[0]):
                return self.render_auth_page('login','Muitas tentativas. Aguarde e tente novamente.',status=429)
            principal = ('bootstrap:' + expected_user.casefold()) if (expected_user and username.casefold()==expected_user.casefold() or reserved_account) else ('account:' + str(account['id']) if account else 'unknown:' + username.casefold())
            limiter_key = 'login:' + principal
            if not security.LOGIN_LIMITER.allowed(limiter_key):
                return self.render_auth_page('login','Muitas tentativas para este acesso. Aguarde 15 minutos.',status=429)
            if expected_user and hmac.compare_digest(username.encode(),expected_user.encode()) and hmac.compare_digest(password.encode(),expected_password.encode()):
                security.LOGIN_LIMITER.clear(limiter_key)
                return self.set_session_and_redirect(expected_user, bootstrap_admin=True)
            if account and not reserved_account and not (expected_user and username.casefold()==expected_user.casefold()) and password_matches(password, account["password_salt"], account["password_hash"]):
                with connect() as db:
                    db.execute("UPDATE user_accounts SET last_login_at=?,updated_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), account["id"]))
                    db.commit()
                security.LOGIN_LIMITER.clear(limiter_key)
                return self.set_session_and_redirect(account["username"])
            return self.render_auth_page("login", "Usuário, e-mail ou senha incorretos.", status=401)
        if self.path == "/register":
            if not security.LOGIN_LIMITER.allowed('register:'+self.client_address[0]):
                return self.render_auth_page('login','Muitas tentativas de cadastro. Aguarde e tente novamente.',status=429)
            if not registration_enabled(self.headers.get("Host", "")):
                return self.render_auth_page("login", "A criação de contas está desativada neste ambiente.", status=403)
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
            name = form.get("name", [""])[0].strip()[:100]
            username = form.get("username", [""])[0].strip()[:40]
            email = form.get("email", [""])[0].strip().lower()[:160]
            password = form.get("password", [""])[0]
            confirm = form.get("confirm_password", [""])[0]
            invite_code = form.get("invite_code", [""])[0]
            values = {"name": name, "username": username, "email": email}
            expected_code = os.environ.get("RADAR_REGISTRATION_CODE", "").strip()
            error = ""
            if len(name) < 2:
                error = "Informe seu nome completo."
            elif not USERNAME_PATTERN.fullmatch(username):
                error = "O usuário deve ter de 3 a 40 caracteres: letras, números, ponto, traço ou sublinhado."
            elif username.casefold() == os.environ.get("RADAR_ADMIN_USER", "").strip().casefold():
                error = "Este nome de usuário é reservado. Escolha outro."
            elif not EMAIL_PATTERN.fullmatch(email):
                error = "Informe um endereço de e-mail válido."
            elif len(password) < 10 or not re.search(r"[A-Za-zÀ-ÿ]", password) or not re.search(r"\d", password):
                error = "Crie uma senha com pelo menos 10 caracteres, uma letra e um número."
            elif password != confirm:
                error = "As senhas informadas não coincidem."
            elif expected_code and not hmac.compare_digest(invite_code, expected_code):
                error = "O código de convite é inválido."
            if error:
                return self.render_auth_page("register", error, values, 400)
            now = datetime.now().isoformat(timespec="seconds")
            salt, digest = password_digest(password)
            try:
                with connect() as db:
                    if db.execute("SELECT 1 FROM user_accounts WHERE email=? COLLATE NOCASE", (email,)).fetchone():
                        return self.render_auth_page("register", "Já existe uma conta com este e-mail.", values, 409)
                    account_id = "conta-" + uuid.uuid4().hex
                    db.execute(
                        """INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,'vendedor',1,?,?)""",
                        (account_id, name, username, email, digest, salt, now, now),
                    )
                    initials = "".join(part[0] for part in name.split()[:2]).upper()[:2] or "R"
                    db.execute(
                        """INSERT INTO sales_profiles(id,name,role,email,initials,color,owner_id,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        ("usuario-" + uuid.uuid4().hex[:12], name, "Vendedor", email, initials, "#b82043", account_id, now, now),
                    )
                    db.commit()
            except sqlite3.IntegrityError:
                return self.render_auth_page("register", "Este nome de usuário já está em uso.", values, 409)
            return self.set_session_and_redirect(username)
        if not self.require_auth(): return
        if self.path.startswith('/api/admin/'):
            return admin_http.handle_post(self,globals(),self.path)
        if self.path.startswith('/api/sales-ops/'):
            return sales_ops.handle(self,globals(),urlparse(self.path),write=True)
        if self.path=='/api/help/feedback':
            try:
                payload=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length','0')),2048)))
                if not isinstance(payload,dict) or type(payload.get('useful')) is not bool or not isinstance(payload.get('id'),str):raise ValueError('Resposta inválida')
                with connect() as db:
                    item=db.execute('SELECT admin_only FROM help_articles WHERE id=? AND published=1',(payload.get('id'),)).fetchone()
                    if not item or item[0] and not self.session_is_admin():return self.send_json({'erro':'Artigo não encontrado'},404)
                    db.execute('''INSERT INTO help_feedback VALUES(?,?,?,?) ON CONFLICT(article_id,owner_id)
                       DO UPDATE SET useful=excluded.useful,updated_at=excluded.updated_at''',(payload['id'],self.session_owner_id(),int(payload['useful']),datetime.now().isoformat(timespec='seconds')))
                return self.send_json({'saved':True})
            except (ValueError,TypeError):return self.send_json({'erro':'Resposta inválida'},400)
        if self.path=='/api/prospects/qualify':
            try:
                payload=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length','0')),4096)))
                with connect() as db:result=prospecting.qualify(db,self.session_owner_id(),payload)
                return self.send_json(result,201 if result['created'] else 200)
            except FileExistsError as error:return self.send_json({'erro':str(error),'duplicate':True},409)
            except sqlite3.IntegrityError:return self.send_json({'erro':'Já existe um contato com os mesmos dados. Nenhum registro foi alterado.'},409)
            except LookupError as error:return self.send_json({'erro':str(error)},404)
            except (ValueError,TypeError) as error:return self.send_json({'erro':str(error)},400)
        if self.path == "/api/sync":
            if security.production() and not self.session_is_admin(): return self.send_json({'erro':'Operação restrita ao administrador'},403)
            started = SYNC.start()
            return self.send_json({"iniciado":started,**SYNC.snapshot()},202 if started else 200)
        if self.path in ('/api/discovery/recommendations/review','/api/discovery/notifications'):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384: return self.send_json({'erro':'Seleção excede o limite'},413)
                payload=json.loads(self.rfile.read(length))
                with connect() as db:
                    handler=discovery.review_recommendations if self.path.endswith('/review') else discovery.update_notifications
                    result=handler(db,self.session_owner_id(),payload)
                return self.send_json(result)
            except discovery.CampaignConflict as error: return self.send_json({'erro':str(error)},409)
            except LookupError as error: return self.send_json({'erro':str(error)},404)
            except (ValueError,TypeError,AttributeError,UnicodeDecodeError) as error: return self.send_json({'erro':str(error) or 'Seleção inválida'},400)
        if self.path == '/api/discovery/campaigns' or re.fullmatch(r'/api/discovery/campaigns/[a-f0-9]{32}/run',self.path):
            try:
                owner=self.session_owner_id()
                if self.path.endswith('/run'):
                    run_id=DISCOVERY.start(owner,self.path.split('/')[4])
                    return self.send_json({'id':run_id,'status':'executando'},202)
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192: return self.send_json({'erro':'Campanha excede o limite'},413)
                payload=json.loads(self.rfile.read(length))
                with connect() as db: identifier=discovery.save_campaign(db,owner,payload)
                return self.send_json({'id':identifier},201)
            except discovery.CampaignConflict as error: return self.send_json({'erro':str(error)},409)
            except LookupError: return self.send_json({'erro':'Campanha não encontrada'},404)
            except (ValueError,TypeError,AttributeError,UnicodeDecodeError) as error: return self.send_json({'erro':str(error) or 'Campanha inválida'},400)
        if self.path == '/api/prospects/import':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=2*1024*1024: return self.send_json({'erro':'Arquivo excede 2 MB'},413)
                payload=json.loads(self.rfile.read(length))
                with connect() as db:
                    result=prospecting.import_rows(db,self.session_owner_id(),payload.get('rows'))
            except (ValueError,TypeError,AttributeError,UnicodeDecodeError) as error:
                return self.send_json({'erro':str(error) or 'Arquivo inválido'},400)
            return self.send_json(result,201)
        if self.path == '/api/commercial-settings':
            try:
                payload=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length','0')),4096)))
                profile_id=str(payload.get('profile_id',''))
                hours=int(payload.get('contact_sla_hours',48));days=int(payload.get('stalled_days',7))
                if not 1<=hours<=720 or not 1<=days<=365: raise ValueError()
            except (ValueError,TypeError,AttributeError): return self.send_json({'erro':'Prazo de contato: 1 a 720 horas; negociação parada: 1 a 365 dias'},400)
            with connect() as db:
                if not self.owned_sales_profile(db,profile_id): return self.send_json({'erro':'Área não encontrada'},404)
                db.execute('INSERT INTO commercial_settings(profile_id,contact_sla_hours,stalled_days) VALUES(?,?,?) ON CONFLICT(profile_id) DO UPDATE SET contact_sla_hours=excluded.contact_sla_hours,stalled_days=excluded.stalled_days',(profile_id,hours,days))
            return self.send_json({'saved':True})
        if self.path == "/api/monitor":
            if security.production() and not self.session_is_admin(): return self.send_json({'erro':'Operação restrita ao administrador'},403)
            started = MONITOR.start()
            snapshot = MONITOR.snapshot()
            status = 202 if started else (409 if not snapshot["configurado"] else 200)
            return self.send_json({"iniciado": started, **snapshot}, status)
        if self.path == "/api/message-templates":
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            name = str(payload.get("name", "")).strip()[:60]
            body = str(payload.get("body", "")).strip()[:2000]
            if not name:
                return self.send_json({"erro": "Informe o nome do modelo"}, 400)
            if not body:
                return self.send_json({"erro": "Informe a mensagem do modelo"}, 400)
            owner_id = self.session_owner_id()
            template_id = "mensagem-" + uuid.uuid4().hex[:12]
            now = datetime.now().isoformat(timespec="seconds")
            try:
                with connect() as db:
                    has_template = db.execute(
                        "SELECT 1 FROM message_templates WHERE owner_id=? LIMIT 1", (owner_id,)
                    ).fetchone()
                    is_default = 1 if payload.get("is_default") or not has_template else 0
                    if is_default:
                        db.execute("UPDATE message_templates SET is_default=0 WHERE owner_id=?", (owner_id,))
                    db.execute(
                        """INSERT INTO message_templates(id,owner_id,name,body,is_default,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (template_id, owner_id, name, body, is_default, now, now),
                    )
                    db.commit()
            except sqlite3.IntegrityError:
                return self.send_json({"erro": "Já existe um modelo com este nome"}, 409)
            return self.send_json({"id": template_id, "name": name, "body": body, "is_default": is_default, "created_at": now, "updated_at": now}, 201)
        if self.path == "/api/team-profiles":
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            name = str(payload.get("name", "")).strip()[:80]
            role = str(payload.get("role", "Vendedor")).strip()[:80] or "Vendedor"
            email = str(payload.get("email", "")).strip()[:160]
            if not name:
                return self.send_json({"erro": "Informe o nome do perfil"}, 400)
            initials = "".join(part[0] for part in name.split()[:2]).upper()[:2] or "R"
            profile_id = "usuario-" + uuid.uuid4().hex[:12]
            now = datetime.now().isoformat(timespec="seconds")
            owner_id = self.session_owner_id()
            with connect() as db:
                db.execute("INSERT INTO sales_profiles(id,name,role,email,initials,color,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (profile_id, name, role, email, initials, "#b82043", owner_id, now, now))
                db.commit()
            return self.send_json({"id": profile_id, "name": name, "role": role, "email": email, "initials": initials, "color": "#b82043", "lead_count": 0, "favorite_count": 0}, 201)
        if self.path == "/api/team-leads/test":
            if not admin_panel.get('test_leads',DB):return self.send_json({'erro':'Leads de teste desativados pelo administrador'},403)
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            profile_id = str(payload.get("profile_id", "")).strip()
            name = str(payload.get("name", "")).strip()[:100]
            phone = ''.join(c for c in str(payload.get("phone", "")) if c.isdigit())
            if not profile_id or not name:
                return self.send_json({"erro": "Perfil e nome são obrigatórios"}, 400)
            if len(phone) not in (10, 11, 12, 13):
                return self.send_json({"erro": "Informe um telefone brasileiro válido"}, 400)
            now = datetime.now().isoformat(timespec="seconds")
            cnpj = "999" + f"{uuid.uuid4().int % 10**11:011d}"
            with connect() as db:
                if not self.owned_sales_profile(db, profile_id):
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                db.execute("""INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,cnae_descricao,segmento,municipio,regiao,uf,telefone,porte,mei,data_source)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (cnpj, name, name, "TESTE", date.today().isoformat(), "0000000", "Lead fictício para teste", "Teste interno", "Teste local", "Demonstração", "ZZ", phone, "TESTE", 0, "Lead de teste local"))
                db.execute("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,favorito) VALUES(?,?,?,?,1)", (profile_id, cnpj, now, now))
                add_lead_history(db, profile_id, cnpj, "created", "Lead de teste incluído no painel", "Registro fictício local para validar o fluxo comercial.", now)
                db.execute("UPDATE sales_profiles SET updated_at=? WHERE id=?", (now, profile_id))
                db.commit()
            return self.send_json({"cnpj": cnpj, "profile_id": profile_id, "name": name, "phone": phone}, 201)
        if self.path == "/api/team-leads":
            length = min(int(self.headers.get("Content-Length", "0")), 32 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            profile_id = str(payload.get("profile_id", "")).strip()
            cnpj = ''.join(c for c in str(payload.get("cnpj", "")).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            with connect() as db:
                if not self.owned_sales_profile(db, profile_id):
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                if not db.execute("SELECT 1 FROM companies WHERE cnpj=?", (cnpj,)).fetchone():
                    return self.send_json({"erro": "Empresa não encontrada"}, 404)
                db.execute('BEGIN IMMEDIATE')
                other = db.execute("SELECT 1 FROM sales_profile_leads WHERE cnpj=? AND profile_id<>? AND lead_status NOT IN ('convertido','descartado','concluido') LIMIT 1",(cnpj,profile_id)).fetchone()
                already = db.execute('SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=?',(profile_id,cnpj)).fetchone()
                if other and not already and payload.get('allow_duplicate') is not True:
                    return self.send_json({'erro':'Esta empresa já está em outro atendimento ativo. Confirme antes de duplicar a abordagem.','duplicate':True},409)
                now = datetime.now().isoformat(timespec="seconds")
                cursor = db.execute("INSERT OR IGNORE INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES(?,?,?,?)", (profile_id, cnpj, now, now))
                if cursor.rowcount:
                    add_lead_history(db, profile_id, cnpj, "created", "Lead incluído no painel", "", now)
                if not cursor.rowcount:
                    db.execute("UPDATE sales_profile_leads SET updated_at=? WHERE profile_id=? AND cnpj=?", (now, profile_id, cnpj))
                db.execute("UPDATE sales_profiles SET updated_at=? WHERE id=?", (now, profile_id))
                db.commit()
                count = db.execute("SELECT COUNT(*) FROM sales_profile_leads WHERE profile_id=?", (profile_id,)).fetchone()[0]
            return self.send_json({"adicionado": bool(cursor.rowcount), "profile_id": profile_id, "cnpj": cnpj, "lead_count": count}, 201 if cursor.rowcount else 200)
        if self.path == "/api/team-lead-events":
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            profile_id = str(payload.get("profile_id", "")).strip()
            cnpj = ''.join(c for c in str(payload.get("cnpj", "")).upper() if c.isalnum())
            event_type = str(payload.get("event_type", "")).strip()
            if not profile_id or len(cnpj) != 14 or event_type != "whatsapp_opened":
                return self.send_json({"erro": "Evento inválido"}, 400)
            details = str(payload.get("details", "")).strip()[:1000]
            with connect() as db:
                if not self.owned_sales_profile(db, profile_id) or not db.execute("SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj)).fetchone():
                    return self.send_json({"erro": "Lead não encontrado no painel deste responsável"}, 404)
                now = datetime.now().isoformat(timespec="seconds")
                selected_profile=self.owned_sales_profile(db,profile_id)
                if sales_ops.blocked(db,selected_profile['owner_id'] or self.session_owner_id(),cnpj):
                    return self.send_json({'erro':'Não contatar: esta empresa está bloqueada nesta conta.'},403)
                add_lead_history(db, profile_id, cnpj, event_type, "Link do WhatsApp aberto (contato não confirmado)", details, now)
                # Opening a link is not proof that a contact/message happened.
                db.commit()
            return self.send_json({"registrado": True, "created_at": now}, 201)
        if self.path == "/api/profiles":
            length = min(int(self.headers.get("Content-Length", "0")), 64 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            name = str(payload.get("name", "")).strip()[:60]
            description = str(payload.get("description", "")).strip()[:180]
            raw_filters = payload.get("filters", {})
            if not name:
                return self.send_json({"erro": "Informe o nome do perfil"}, 400)
            if not isinstance(raw_filters, dict):
                return self.send_json({"erro": "Filtros do perfil inválidos"}, 400)
            valid_fields = {"q", "inicio", "fim", "segmento", "cnae", "municipio", "regiao", "situacao", "mei", "contato", "lead_status", "favorito", "score_min", "cnae_include", "cnae_exclude", "name_terms", "name_exclude", "porte", "data_source", "phone_available", "email_available", "work_stage"}
            clean_filters = {key: str(value)[:1000] for key, value in raw_filters.items() if key in valid_fields and str(value).strip()}
            profile_id = "perfil-" + uuid.uuid4().hex[:12]
            now = datetime.now().isoformat(timespec="seconds")
            with connect() as db:
                db.execute("INSERT INTO prospecting_profiles(id,name,description,filters_json,is_system,owner_id,created_at,updated_at) VALUES(?,?,?,?,0,?,?,?)", (profile_id, name, description, json.dumps(clean_filters, ensure_ascii=False), self.session_owner_id(), now, now))
                db.commit()
            return self.send_json({"id": profile_id, "name": name, "description": description, "filters": clean_filters, "is_system": 0, "companies": 0, "lead_count": 0}, 201)
        if self.path == "/api/profile-leads":
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            profile_id = str(payload.get("profile_id", "")).strip()
            cnpj = ''.join(c for c in str(payload.get("cnpj", "")).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            with connect() as db:
                profile = db.execute("""SELECT id,name,is_system FROM prospecting_profiles
                    WHERE id=? AND owner_id=?""", (profile_id, self.session_owner_id())).fetchone()
                if not profile:
                    return self.send_json({"erro": "Perfil não encontrado"}, 404)
                if profile["is_system"]:
                    return self.send_json({"erro": "Escolha um perfil personalizado para montar uma lista"}, 400)
                company = db.execute("SELECT cnpj FROM companies WHERE cnpj=?", (cnpj,)).fetchone()
                if not company:
                    return self.send_json({"erro": "Empresa não encontrada"}, 404)
                now = datetime.now().isoformat(timespec="seconds")
                cursor = db.execute("INSERT OR IGNORE INTO profile_leads(profile_id,cnpj,added_at) VALUES(?,?,?)", (profile_id, cnpj, now))
                db.commit()
                added = bool(cursor.rowcount)
                count = db.execute("SELECT COUNT(*) FROM profile_leads WHERE profile_id=?", (profile_id,)).fetchone()[0]
            return self.send_json({"adicionado": added, "profile_id": profile_id, "cnpj": cnpj, "lead_count": count}, 201 if added else 200)
        return self.send_error(404)

    def do_PUT(self):
        if not self.guard_write(): return
        if not self.require_auth(): return
        match=re.fullmatch(r'/api/discovery/campaigns/([a-f0-9]{32})',self.path)
        if match:
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192: return self.send_json({'erro':'Campanha excede o limite'},413)
                payload=json.loads(self.rfile.read(length))
                with connect() as db: identifier=discovery.save_campaign(db,self.session_owner_id(),payload,match.group(1))
                return self.send_json({'id':identifier})
            except discovery.CampaignConflict as error: return self.send_json({'erro':str(error)},409)
            except LookupError: return self.send_json({'erro':'Campanha não encontrada'},404)
            except (ValueError,TypeError,AttributeError,UnicodeDecodeError) as error: return self.send_json({'erro':str(error) or 'Campanha inválida'},400)
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/prospects/'):
            contact_id=parsed.path.rsplit('/',1)[-1];owner=self.session_owner_id()
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384: return self.send_json({'erro':'Contato excede o limite'},413)
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict): raise ValueError('Contato inválido')
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    old=db.execute('SELECT * FROM prospect_inbox WHERE id=? AND owner_id=?',(contact_id,owner)).fetchone()
                    if not old:return self.send_json({'erro':'Contato não encontrado'},404)
                    if 'revision' in payload and payload['revision']!=old['revision']:return self.send_json({'erro':'Contato alterado em outra sessão. Atualize a lista antes de salvar.'},409)
                    row=prospecting.validate({**dict(old),**payload})
                    columns=list(row);new_key=prospecting.fingerprint(row)
                    duplicate=db.execute('SELECT id FROM prospect_inbox WHERE owner_id=? AND fingerprint=? AND id<>?',(owner,new_key,contact_id)).fetchone()
                    if duplicate:return self.send_json({'erro':'Já existe um contato igual nesta conta'},409)
                    stamp=datetime.now().isoformat(timespec='seconds')
                    db.execute(f"UPDATE prospect_inbox SET {','.join(k+'=?' for k in columns)},fingerprint=?,updated_at=?,revision=revision+1 WHERE id=? AND owner_id=?",[row[k] for k in columns]+[new_key,stamp,contact_id,owner])
                    changed=', '.join(key for key in row if row[key]!=old[key])
                    if changed:db.execute("INSERT INTO prospect_history(prospect_id,owner_id,event,details,created_at) VALUES(?,?,'updated',?,?)",(contact_id,owner,changed,stamp))
            except (ValueError,TypeError,UnicodeDecodeError) as error:return self.send_json({'erro':str(error)},400)
            return self.send_json({'ok':True})
        if parsed.path.startswith("/api/message-templates/"):
            template_id = parsed.path.rsplit("/", 1)[-1]
            length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            owner_id = self.session_owner_id()
            with connect() as db:
                current = db.execute(
                    "SELECT * FROM message_templates WHERE id=? AND owner_id=?",
                    (template_id, owner_id),
                ).fetchone()
                if not current:
                    return self.send_json({"erro": "Modelo de mensagem não encontrado"}, 404)
                name = str(payload.get("name", current["name"])).strip()[:60]
                body = str(payload.get("body", current["body"])).strip()[:2000]
                if not name:
                    return self.send_json({"erro": "Informe o nome do modelo"}, 400)
                if not body:
                    return self.send_json({"erro": "Informe a mensagem do modelo"}, 400)
                is_default = 1 if payload.get("is_default", current["is_default"]) else 0
                if is_default:
                    db.execute("UPDATE message_templates SET is_default=0 WHERE owner_id=?", (owner_id,))
                elif current["is_default"]:
                    # Sempre deve existir um modelo padrão para o clique direto.
                    is_default = 1
                now = datetime.now().isoformat(timespec="seconds")
                try:
                    db.execute(
                        """UPDATE message_templates SET name=?,body=?,is_default=?,updated_at=?
                           WHERE id=? AND owner_id=?""",
                        (name, body, is_default, now, template_id, owner_id),
                    )
                    db.commit()
                except sqlite3.IntegrityError:
                    return self.send_json({"erro": "Já existe um modelo com este nome"}, 409)
            return self.send_json({"id": template_id, "name": name, "body": body, "is_default": is_default, "updated_at": now})
        if parsed.path == "/api/team-leads":
            length = min(int(self.headers.get("Content-Length", "0")), 64 * 1024)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"erro": "JSON inválido"}, 400)
            profile_id = str(payload.get("profile_id", "")).strip()
            cnpj = ''.join(c for c in str(payload.get("cnpj", "")).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            allowed = {}
            if "lead_status" in payload:
                if payload["lead_status"] not in ("novo", "qualificado", "contatado", "negociacao", "convertido", "descartado", "concluido"):
                    return self.send_json({"erro": "Etapa inválida"}, 400)
                allowed["lead_status"] = payload["lead_status"]
            if "favorito" in payload: allowed["favorito"] = 1 if payload["favorito"] else 0
            if "observacoes" in payload: allowed["observacoes"] = str(payload["observacoes"])[:4000]
            if "estrategia" in payload: allowed["estrategia"] = str(payload["estrategia"])[:4000]
            for key in ('campaign','persona','lead_origin','loss_reason'):
                if key in payload: allowed[key]=str(payload[key] or '').strip()[:120]
            if 'loss_reason' in allowed and allowed['loss_reason'] not in commercial.LOSS_REASONS:
                return self.send_json({'erro':'Motivo de perda inválido'},400)
            if "contact_outcome" in payload:
                outcome = str(payload["contact_outcome"]).strip()
                if outcome not in CONTACT_OUTCOMES:
                    return self.send_json({"erro": "Resultado do contato inválido"}, 400)
                allowed["contact_outcome"] = outcome
            if "next_action" in payload:
                allowed["next_action"] = str(payload["next_action"]).strip()[:240]
            if "next_action_at" in payload:
                raw_next_action_at = str(payload["next_action_at"] or "").strip()
                if raw_next_action_at:
                    try:
                        raw_next_action_at = safe_datetime(raw_next_action_at)
                    except ValueError:
                        return self.send_json({"erro": "Data da próxima ação inválida"}, 400)
                allowed["next_action_at"] = raw_next_action_at or None
            for key in ("offered_value_cents", "negotiated_value_cents", "closed_value_cents"):
                if key in payload:
                    try:
                        allowed[key] = money_cents(payload[key])
                    except ValueError as error:
                        return self.send_json({"erro": str(error)}, 400)
            if "closed_at" in payload:
                try:
                    allowed["closed_at"] = safe_datetime(payload["closed_at"])
                except ValueError as error:
                    return self.send_json({"erro": str(error)}, 400)
            if "whatsapp_status" in payload:
                whatsapp_status = str(payload["whatsapp_status"] or "pending").strip().lower()
                if whatsapp_status not in ("pending", "confirmed", "not_found", "invalid"):
                    return self.send_json({"erro": "Situação do WhatsApp inválida"}, 400)
                allowed["whatsapp_status"] = whatsapp_status
                allowed["whatsapp_checked_at"] = datetime.now().isoformat(timespec="seconds") if whatsapp_status != "pending" else None
            if "whatsapp_phone" in payload:
                whatsapp_phone = ''.join(char for char in str(payload["whatsapp_phone"] or "") if char.isdigit())
                if whatsapp_phone and len(whatsapp_phone) not in (12, 13):
                    return self.send_json({"erro": "Número normalizado do WhatsApp inválido"}, 400)
                allowed["whatsapp_phone"] = whatsapp_phone
            if not allowed:
                return self.send_json({"erro": "Nenhuma alteração válida"}, 400)
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if not self.owned_sales_profile(db, profile_id):
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                current = db.execute("SELECT * FROM sales_profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj)).fetchone()
                if not current:
                    return self.send_json({"erro": "Inclua o lead no painel antes de editar"}, 404)
                if 'expected_updated_at' in payload and payload['expected_updated_at'] != current['updated_at']:
                    return self.send_json({'erro':'Lead alterado em outra sessão. Sua edição não foi sobrescrita: reabra a ficha para revisar os dados atuais.'},409)
                now = datetime.now().isoformat(timespec="microseconds")
                if allowed.get("contact_outcome") and allowed.get("contact_outcome") != current["contact_outcome"]:
                    allowed["last_contact_at"] = now
                    allowed["first_contact_at"] = current["first_contact_at"] or now
                if allowed.get("lead_status") == "convertido" and allowed.get("lead_status") != current["lead_status"]:
                    allowed["closed_at"] = allowed.get("closed_at") or now
                elif "lead_status" in allowed and allowed["lead_status"] != "convertido" and current["lead_status"] == "convertido" and "closed_at" not in allowed:
                    allowed["closed_at"] = None
                allowed["updated_at"] = now
                commercial.log_changes(db,profile_id,cnpj,current,allowed,now)
                assignments = ",".join(f"{key}=?" for key in allowed)
                db.execute(f"UPDATE sales_profile_leads SET {assignments} WHERE profile_id=? AND cnpj=?", list(allowed.values()) + [profile_id, cnpj])
                db.execute("UPDATE sales_profiles SET updated_at=? WHERE id=?", (allowed["updated_at"], profile_id))
                if "lead_status" in allowed and allowed["lead_status"] != current["lead_status"]:
                    add_lead_history(db, profile_id, cnpj, "stage_changed", "Etapa comercial alterada", f"{LEAD_STAGES.get(current['lead_status'], current['lead_status'])} → {LEAD_STAGES.get(allowed['lead_status'], allowed['lead_status'])}", now)
                if "contact_outcome" in allowed and allowed["contact_outcome"] != current["contact_outcome"]:
                    add_lead_history(db, profile_id, cnpj, "contact_outcome", "Resultado do contato registrado", CONTACT_OUTCOMES.get(allowed["contact_outcome"], allowed["contact_outcome"]), now)
                if "whatsapp_status" in allowed and allowed["whatsapp_status"] != current["whatsapp_status"]:
                    whatsapp_labels = {"pending":"Pendente", "confirmed":"WhatsApp confirmado", "not_found":"Não localizado no WhatsApp", "invalid":"Telefone inválido"}
                    add_lead_history(db, profile_id, cnpj, "whatsapp_status", "Verificação do WhatsApp atualizada", whatsapp_labels[allowed["whatsapp_status"]], now)
                if (("next_action" in allowed and allowed["next_action"] != current["next_action"]) or
                    ("next_action_at" in allowed and allowed["next_action_at"] != current["next_action_at"])):
                    action_details = allowed.get("next_action", current["next_action"]) or "Próxima ação atualizada"
                    action_at = allowed.get("next_action_at", current["next_action_at"])
                    if action_at:
                        action_details += f" · {action_at}"
                    add_lead_history(db, profile_id, cnpj, "next_action", "Próxima ação atualizada", action_details, now)
                if (("observacoes" in allowed and allowed["observacoes"] != current["observacoes"]) or
                    ("estrategia" in allowed and allowed["estrategia"] != current["estrategia"])):
                    add_lead_history(db, profile_id, cnpj, "notes_updated", "Anotações comerciais atualizadas", "Estratégia e contexto do lead foram salvos.", now)
                financial_keys = ("offered_value_cents", "negotiated_value_cents", "closed_value_cents")
                if any(key in allowed and allowed[key] != current[key] for key in financial_keys):
                    add_lead_history(db, profile_id, cnpj, "financial_updated", "Valores da oportunidade atualizados", "Oferta, negociação e fechamento foram revisados.", now)
                db.commit()
                row = db.execute("""SELECT c.*, spl.profile_id, spl.updated_at AS profile_updated_at,
                    spl.favorito AS profile_favorito, spl.lead_status AS profile_lead_status,
                    spl.observacoes AS profile_observacoes, spl.estrategia AS profile_estrategia,
                    spl.contact_outcome AS profile_contact_outcome, spl.next_action AS profile_next_action,
                    spl.next_action_at AS profile_next_action_at, spl.last_contact_at AS profile_last_contact_at,
                    spl.first_contact_at AS profile_first_contact_at, spl.closed_at AS profile_closed_at,
                    spl.offered_value_cents AS profile_offered_value_cents,
                    spl.negotiated_value_cents AS profile_negotiated_value_cents,
                    spl.closed_value_cents AS profile_closed_value_cents,
                    COALESCE(NULLIF(spl.whatsapp_status,''),'pending') AS profile_whatsapp_status,
                    spl.whatsapp_phone AS profile_whatsapp_phone,
                    spl.whatsapp_checked_at AS profile_whatsapp_checked_at
                    FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
                    WHERE spl.profile_id=? AND spl.cnpj=?""", (profile_id, cnpj)).fetchone()
            result = dict(row); result["lead_score"] = score_company(result)
            return self.send_json(result)
        if not parsed.path.startswith("/api/leads/"): return self.send_error(404)
        cnpj = ''.join(c for c in parsed.path.rsplit('/',1)[-1].upper() if c.isalnum())
        if len(cnpj) != 14: return self.send_json({"erro":"CNPJ inválido"},400)
        length = min(int(self.headers.get("Content-Length","0")), 64 * 1024)
        try: payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError: return self.send_json({"erro":"JSON inválido"},400)
        allowed = {}
        if "lead_status" in payload:
            if payload["lead_status"] not in ("novo","qualificado","contatado","negociacao","convertido","descartado","concluido"):
                return self.send_json({"erro":"Etapa inválida"},400)
            allowed["lead_status"] = payload["lead_status"]
        if "favorito" in payload: allowed["favorito"] = 1 if payload["favorito"] else 0
        if "observacoes" in payload: allowed["observacoes"] = str(payload["observacoes"])[:4000]
        if not allowed: return self.send_json({"erro":"Nenhuma alteração válida"},400)
        owner_id = self.session_owner_id()
        with connect() as db:
            if not db.execute("SELECT 1 FROM companies WHERE cnpj=?", (cnpj,)).fetchone():
                return self.send_json({"erro":"Empresa não encontrada"},404)
            current = db.execute("""SELECT lead_status,favorito,observacoes FROM account_company_state
                WHERE account_id=? AND cnpj=?""", (owner_id, cnpj)).fetchone()
            state = {"lead_status": "novo", "favorito": 0, "observacoes": ""}
            if current:
                state.update(dict(current))
            state.update(allowed)
            now = datetime.now().isoformat(timespec="seconds")
            db.execute("""INSERT INTO account_company_state(account_id,cnpj,lead_status,favorito,observacoes,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,cnpj) DO UPDATE SET
                lead_status=excluded.lead_status,favorito=excluded.favorito,
                observacoes=excluded.observacoes,updated_at=excluded.updated_at""",
                (owner_id, cnpj, state["lead_status"], state["favorito"], state["observacoes"], now))
            result=dict(db.execute(f"SELECT * FROM {ACCOUNT_COMPANY_SOURCE} WHERE cnpj=?", (owner_id, cnpj)).fetchone())
            db.commit()
        result["lead_score"] = score_company(result)
        return self.send_json(result)

    def do_DELETE(self):
        if not self.guard_write(): return
        if not self.require_auth(): return
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/message-templates/"):
            template_id = parsed.path.rsplit("/", 1)[-1]
            owner_id = self.session_owner_id()
            with connect() as db:
                current = db.execute(
                    "SELECT is_default FROM message_templates WHERE id=? AND owner_id=?",
                    (template_id, owner_id),
                ).fetchone()
                if not current:
                    return self.send_json({"erro": "Modelo de mensagem não encontrado"}, 404)
                total = db.execute(
                    "SELECT COUNT(*) FROM message_templates WHERE owner_id=?", (owner_id,)
                ).fetchone()[0]
                if total <= 1:
                    return self.send_json({"erro": "Mantenha ao menos um modelo de mensagem"}, 400)
                db.execute(
                    "DELETE FROM message_templates WHERE id=? AND owner_id=?",
                    (template_id, owner_id),
                )
                if current["is_default"]:
                    replacement = db.execute(
                        """SELECT id FROM message_templates WHERE owner_id=?
                           ORDER BY updated_at DESC, name COLLATE NOCASE LIMIT 1""",
                        (owner_id,),
                    ).fetchone()
                    db.execute(
                        "UPDATE message_templates SET is_default=1 WHERE id=? AND owner_id=?",
                        (replacement["id"], owner_id),
                    )
                db.commit()
            return self.send_json({"excluido": True})
        if parsed.path == "/api/team-leads":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            cnpj = ''.join(c for c in str(params.get("cnpj", [""])[0]).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            with connect() as db:
                if not self.owned_sales_profile(db, profile_id):
                    return self.send_json({"erro": "Área comercial não encontrada para esta conta"}, 404)
                commercial.archive_lead(db,profile_id,cnpj)
                cursor = db.execute("DELETE FROM sales_profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj))
                db.commit()
            return self.send_json({"removido": bool(cursor.rowcount), "profile_id": profile_id, "cnpj": cnpj})
        if parsed.path.startswith("/api/team-profiles/"):
            profile_id = parsed.path.rsplit("/", 1)[-1]
            with connect() as db:
                row = self.owned_sales_profile(db, profile_id)
                if not row:
                    return self.send_json({"erro": "Perfil individual não encontrado para esta conta"}, 404)
                db.execute("DELETE FROM sales_profiles WHERE id=?", (profile_id,))
                db.commit()
            return self.send_json({"excluido": True})
        if parsed.path == "/api/profile-leads":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            cnpj = ''.join(c for c in str(params.get("cnpj", [""])[0]).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            with connect() as db:
                if not db.execute("SELECT 1 FROM prospecting_profiles WHERE id=? AND owner_id=?", (profile_id, self.session_owner_id())).fetchone():
                    return self.send_json({"erro": "Perfil não encontrado para esta conta"}, 404)
                cursor = db.execute("DELETE FROM profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj))
                db.commit()
            return self.send_json({"removido": bool(cursor.rowcount), "profile_id": profile_id, "cnpj": cnpj})
        if not parsed.path.startswith("/api/profiles/"):
            return self.send_error(404)
        profile_id = parsed.path.rsplit("/", 1)[-1]
        with connect() as db:
            row = db.execute("""SELECT is_system FROM prospecting_profiles
                WHERE id=? AND (is_system=1 OR owner_id=?)""", (profile_id, self.session_owner_id())).fetchone()
            if not row:
                return self.send_json({"erro": "Perfil não encontrado"}, 404)
            if row[0]:
                return self.send_json({"erro": "Perfis do sistema não podem ser excluídos"}, 400)
            db.execute("DELETE FROM prospecting_profiles WHERE id=?", (profile_id,))
            db.commit()
        return self.send_json({"excluido": True})

    def log_message(self, fmt, *args): print(f"[{self.log_date_time_string()}] {fmt % args}")


DISCOVERY = discovery.DiscoveryManager(lambda: connect())

if __name__ == "__main__":
    resolve_local_admin_credential()
    security.session_secret()
    if (DATA_DIR/'.radar-credential.xml').is_file() and not (os.environ.get('RADAR_ADMIN_USER') and os.environ.get('RADAR_ADMIN_PASSWORD')):
        raise SystemExit('Credencial local indisponível; inicialização cancelada por segurança.')
    init_db(); port=int(os.environ.get("PORT",os.environ.get("RADAR_PORT","8000"))); host=os.environ.get("RADAR_HOST","127.0.0.1")
    if host not in {'127.0.0.1','localhost','::1'} and not security.production():
        raise SystemExit('Listener público exige RADAR_ENV=production e configuração segura.')
    SYNC.start_scheduler()
    # Serpro stays off: saving parameters never authorizes a paid consultation.
    DISCOVERY.start_scheduler()
    discovery.start_local_scheduler()
    backup_protection.start_scheduler(DB,connect)
    print(f"Radar CNPJ RS disponível em http://{host}:{port}")
    ThreadingHTTPServer((host,port),Handler).serve_forever()
