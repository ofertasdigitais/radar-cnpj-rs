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
import time
import uuid
from http.cookies import SimpleCookie
from datetime import date, timedelta, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from syncer import CNPJSync
from serpro import DailyMonitor

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR", ROOT / "data")).resolve()
DB = DATA_DIR / "radar.db"
STATIC = ROOT / "static"
SYNC = CNPJSync(DB, DATA_DIR / "sync-cache")
MONITOR = DailyMonitor(DB)

PASSWORD_ITERATIONS = 260_000
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

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
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
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
          color TEXT NOT NULL DEFAULT '#b82043', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_profile_leads (
          profile_id TEXT NOT NULL, cnpj TEXT NOT NULL, added_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, favorito INTEGER NOT NULL DEFAULT 0,
          lead_status TEXT NOT NULL DEFAULT 'novo', observacoes TEXT NOT NULL DEFAULT '',
          estrategia TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(profile_id, cnpj),
          FOREIGN KEY(profile_id) REFERENCES sales_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(cnpj) REFERENCES companies(cnpj) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sales_profile_leads_profile ON sales_profile_leads(profile_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sales_profile_leads_cnpj ON sales_profile_leads(cnpj);
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
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(companies)")}
        for name, definition in (("lead_status", "TEXT DEFAULT 'novo'"), ("favorito", "INTEGER DEFAULT 0"), ("observacoes", "TEXT DEFAULT ''"), ("cnae_descricao", "TEXT DEFAULT ''"), ("serpro_checked_at", "TEXT"), ("data_source", "TEXT DEFAULT 'Receita Federal'")):
            if name not in columns:
                db.execute(f"ALTER TABLE companies ADD COLUMN {name} {definition}")
        db.execute("UPDATE companies SET lead_status='novo' WHERE lead_status IS NULL OR TRIM(lead_status)=''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_lead_stage ON companies(lead_status)")
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
        db.execute("PRAGMA optimize")


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


def registration_enabled():
    return os.environ.get("RADAR_ALLOW_REGISTRATION", "1").strip().lower() not in {"0", "false", "nao", "não"}


def account_by_login(login):
    with connect() as db:
        return db.execute(
            """SELECT * FROM user_accounts
               WHERE is_active=1 AND (username=? COLLATE NOCASE OR email=? COLLATE NOCASE)
               LIMIT 1""",
            (login, login),
        ).fetchone()


def filters(params, exclude=()):
    clauses = ["uf='RS'"]; values = []
    mappings = {"inicio":("data_abertura >= ?",None),"fim":("data_abertura <= ?",None),"municipio":("municipio = ?",None),"regiao":("regiao = ?",None),"segmento":("segmento = ?",None),"situacao":("situacao = ?",None),"mei":("mei = ?", lambda x: 1 if x == "sim" else 0),"contato":("CASE WHEN TRIM(COALESCE(email,''))<>'' OR TRIM(COALESCE(telefone,''))<>'' THEN 1 ELSE 0 END = ?",lambda x: 1 if x == "sim" else 0),"lead_status":("COALESCE(NULLIF(lead_status,''),'novo') = ?",None),"favorito":("favorito = ?",lambda x: 1 if x == "sim" else 0)}
    for key, (sql, convert) in mappings.items():
        if key in exclude: continue
        val = params.get(key, [""])[0]
        if val: clauses.append(sql); values.append(convert(val) if convert else val)
    cnae = ''.join(c for c in params.get("cnae", [""])[0] if c.isdigit())
    if cnae: clauses.append("cnae LIKE ?"); values.append(cnae + "%")
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
    def session_token(self, username):
        secret = os.environ.get("RADAR_SESSION_SECRET", os.environ.get("RADAR_ADMIN_PASSWORD", "local"))
        payload = f"{username}|{int(time.time()) + 12 * 3600}"
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}|{signature}".encode()).decode()

    def session_username(self):
        secret = os.environ.get("RADAR_SESSION_SECRET", os.environ.get("RADAR_ADMIN_PASSWORD", "local"))
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie["radar_session"].value
            username, expires, signature = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
            payload = f"{username}|{expires}"
            expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if int(expires) <= time.time() or not hmac.compare_digest(signature, expected):
                return None
            admin = os.environ.get("RADAR_ADMIN_USER", "")
            if admin and hmac.compare_digest(username.lower(), admin.lower()):
                return username
            with connect() as db:
                row = db.execute(
                    "SELECT username FROM user_accounts WHERE username=? COLLATE NOCASE AND is_active=1",
                    (username,),
                ).fetchone()
            return row[0] if row else None
        except (KeyError, ValueError, UnicodeDecodeError):
            return None

    def valid_session(self):
        return self.session_username() is not None

    def render_auth_page(self, mode="login", error="", values=None, status=200):
        values = values or {}
        view = "register" if mode == "register" and registration_enabled() else "login"
        template = (STATIC / "login.html").read_text(encoding="utf-8")
        message = f'<div class="auth-alert" role="alert"><span>!</span><p>{html.escape(error)}</p></div>' if error else ""
        replacements = {
            "__AUTH_VIEW__": view,
            "__REGISTRATION_STATE__": "enabled" if registration_enabled() else "disabled",
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

    def set_session_and_redirect(self, username):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" or os.environ.get("RADAR_SECURE_COOKIES") == "1" else ""
        self.send_response(303); self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"radar_session={self.session_token(username)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200{secure}")
        self.security_headers(); self.end_headers()

    def require_auth(self):
        username = os.environ.get("RADAR_ADMIN_USER", "")
        password = os.environ.get("RADAR_ADMIN_PASSWORD", "")
        with connect() as db:
            has_accounts = bool(db.execute("SELECT 1 FROM user_accounts WHERE is_active=1 LIMIT 1").fetchone())
        if (not username or not password) and not has_accounts:
            return True
        if self.valid_session(): return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
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
        if parsed.path in ("/style.css", "/visual.css", "/auth.js", "/icon.svg") or parsed.path.startswith("/fonts/"):
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
        if parsed.path == "/api/companies":
            p = parse_qs(parsed.query); where, vals = filters(p)
            page = max(1, int(p.get("page",["1"])[0])); size = min(100, max(1,int(p.get("size",["20"])[0])))
            with connect() as db:
                total = db.execute(f"SELECT COUNT(*) FROM companies WHERE {where}",vals).fetchone()[0]
                rows = db.execute(f"SELECT * FROM companies WHERE {where} ORDER BY favorito DESC, data_abertura DESC, id DESC LIMIT ? OFFSET ?", vals+[size,(page-1)*size]).fetchall()
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
            with connect() as db:
                rows = db.execute("SELECT * FROM prospecting_profiles ORDER BY is_system DESC, created_at, name").fetchall()
                profiles = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["filters"] = json.loads(item.pop("filters_json"))
                    except (json.JSONDecodeError, TypeError):
                        item["filters"] = {}
                        item.pop("filters_json", None)
                    where, values = filters({key: [str(value)] for key, value in item["filters"].items()})
                    item["companies"] = db.execute(f"SELECT COUNT(*) FROM companies WHERE {where}", values).fetchone()[0]
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
                profile = db.execute("SELECT id,name,is_system FROM prospecting_profiles WHERE id=?", (profile_id,)).fetchone()
                if not profile:
                    return self.send_json({"erro": "Perfil não encontrado"}, 404)
                total = db.execute("SELECT COUNT(*) FROM profile_leads WHERE profile_id=?", (profile_id,)).fetchone()[0]
                rows = db.execute(f"""SELECT c.*, pl.added_at AS carteira_adicionado_em
                    FROM profile_leads pl JOIN companies c ON c.cnpj=pl.cnpj
                    WHERE pl.profile_id=?
                    ORDER BY c.favorito DESC, c.data_abertura DESC, pl.added_at DESC
                    LIMIT ? OFFSET ?""", (profile_id, size, (page - 1) * size)).fetchall()
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
                    WHERE p.is_system=0 ORDER BY p.name""", (cnpj,)).fetchall()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path == "/api/team-profiles":
            with connect() as db:
                rows = db.execute("""SELECT p.*, COUNT(spl.cnpj) AS lead_count,
                    COALESCE(SUM(CASE WHEN spl.favorito=1 THEN 1 ELSE 0 END),0) AS favorite_count,
                    MAX(spl.updated_at) AS last_activity
                    FROM sales_profiles p
                    LEFT JOIN sales_profile_leads spl ON spl.profile_id=p.id
                    GROUP BY p.id ORDER BY p.name COLLATE NOCASE""").fetchall()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path == "/api/team-leads":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            if not profile_id:
                return self.send_json({"erro": "Selecione um perfil individual"}, 400)
            view = str(params.get("view", ["all"])[0]).strip().lower()
            if view not in ("all", "favorites"):
                view = "all"
            status = str(params.get("status", [""])[0]).strip().lower()
            if status and status not in ("novo", "qualificado", "contatado", "negociacao", "convertido", "descartado"):
                return self.send_json({"erro": "Etapa inválida"}, 400)
            try:
                page = max(1, int(params.get("page", ["1"])[0]))
                size = min(100, max(1, int(params.get("size", ["24"])[0])))
            except (TypeError, ValueError):
                return self.send_json({"erro": "Paginação inválida"}, 400)
            where = ["spl.profile_id=?"]
            values = [profile_id]
            if view == "favorites":
                where.append("spl.favorito=1")
            if status:
                where.append("spl.lead_status=?"); values.append(status)
            condition = " AND ".join(where)
            with connect() as db:
                profile = db.execute("SELECT * FROM sales_profiles WHERE id=?", (profile_id,)).fetchone()
                if not profile:
                    return self.send_json({"erro": "Perfil individual não encontrado"}, 404)
                total = db.execute(f"SELECT COUNT(*) FROM sales_profile_leads spl WHERE {condition}", values).fetchone()[0]
                rows = db.execute(f"""SELECT c.*, spl.profile_id, spl.added_at AS carteira_adicionado_em,
                    spl.updated_at AS profile_updated_at, spl.favorito AS profile_favorito,
                    spl.lead_status AS profile_lead_status, spl.observacoes AS profile_observacoes,
                    spl.estrategia AS profile_estrategia
                    FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
                    WHERE {condition}
                    ORDER BY spl.favorito DESC, spl.updated_at DESC, c.data_abertura DESC, c.id DESC
                    LIMIT ? OFFSET ?""", values + [size, (page - 1) * size]).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                item["lead_score"] = score_company(item)
            return self.send_json({"profile": dict(profile), "items": items, "total": total, "page": page, "size": size, "view": view, "status": status})
        if parsed.path == "/api/team-memberships":
            cnpj = ''.join(c for c in str(parse_qs(parsed.query).get("cnpj", [""])[0]).upper() if c.isalnum())
            if len(cnpj) != 14:
                return self.send_json({"erro": "CNPJ inválido"}, 400)
            with connect() as db:
                rows = db.execute("""SELECT p.id,p.name,p.role,p.email,p.initials,p.color,
                    CASE WHEN spl.cnpj IS NULL THEN 0 ELSE 1 END AS selected,
                    COALESCE(spl.favorito,0) AS favorito, COALESCE(spl.lead_status,'novo') AS lead_status,
                    COALESCE(spl.observacoes,'') AS observacoes, COALESCE(spl.estrategia,'') AS estrategia,
                    spl.updated_at
                    FROM sales_profiles p
                    LEFT JOIN sales_profile_leads spl ON spl.profile_id=p.id AND spl.cnpj=?
                    ORDER BY p.name COLLATE NOCASE""", (cnpj,)).fetchall()
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
            if status and status not in ("novo", "qualificado", "contatado", "negociacao", "convertido", "descartado"):
                return self.send_json({"erro": "Etapa inválida"}, 400)
            where = ["spl.profile_id=?"]; values = [profile_id]
            if view == "favorites": where.append("spl.favorito=1")
            if status: where.append("spl.lead_status=?"); values.append(status)
            condition = " AND ".join(where)
            with connect() as db:
                profile = db.execute("SELECT name FROM sales_profiles WHERE id=?", (profile_id,)).fetchone()
                if not profile:
                    return self.send_json({"erro": "Perfil individual não encontrado"}, 404)
                rows = db.execute(f"""SELECT c.*, spl.favorito AS profile_favorito,
                    spl.lead_status AS profile_lead_status, spl.observacoes AS profile_observacoes,
                    spl.estrategia AS profile_estrategia
                    FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
                    WHERE {condition} ORDER BY spl.favorito DESC, spl.updated_at DESC, c.data_abertura DESC""", values).fetchall()
            output = io.StringIO(newline="")
            writer = csv.writer(output, delimiter=";", lineterminator="\n")
            columns = ["Empresa", "CNPJ", "Data de abertura", "CNAE", "Descrição do CNAE", "Segmento", "Município", "Região", "Situação", "Telefone", "E-mail", "Potencial", "Favorito", "Etapa", "Observações", "Estratégia"]
            writer.writerow(columns)
            for row in rows:
                item = dict(row); item["lead_score"] = score_company(item)
                writer.writerow([item.get("nome_fantasia") or item.get("razao_social") or "", item.get("cnpj", ""), item.get("data_abertura", ""), item.get("cnae", ""), item.get("cnae_descricao", ""), item.get("segmento", ""), item.get("municipio", ""), item.get("regiao", ""), item.get("situacao", ""), item.get("telefone", ""), item.get("email", ""), item["lead_score"], "Sim" if item.get("profile_favorito") else "Não", item.get("profile_lead_status", "novo"), item.get("profile_observacoes", ""), item.get("profile_estrategia", "")])
            safe_name = "".join(ch for ch in str(profile["name"]) if ch.isalnum() or ch in " -_").strip() or "perfil"
            return self.send_csv(output.getvalue(), f"radar-{safe_name.lower().replace(' ', '-')}-leads.csv")
        if parsed.path == "/api/stats":
            p=parse_qs(parsed.query); where,vals=filters(p)
            mei_where,mei_vals=filters(p, {"mei","lead_status","favorito"})
            with connect() as db:
                summary=dict(db.execute(f"""SELECT COUNT(*) total, COALESCE(SUM(mei),0) meis,
                    COUNT(DISTINCT municipio) municipios, COUNT(DISTINCT segmento) segmentos,
                    COALESCE(SUM(CASE WHEN email<>'' OR telefone<>'' THEN 1 ELSE 0 END),0) com_contato,
                    MAX(data_abertura) ultima_data FROM companies WHERE {where}""",vals).fetchone())
                groups=[dict(r) for r in db.execute(f"SELECT segmento label,COUNT(*) value FROM companies WHERE {where} GROUP BY segmento ORDER BY value DESC LIMIT 6",vals)]
                cnaes=[dict(r) for r in db.execute(f"SELECT cnae label,MAX(cnae_descricao) description,segmento category,COUNT(*) value FROM companies WHERE {where} AND cnae<>'' GROUP BY cnae,segmento ORDER BY value DESC,cnae LIMIT 8",vals)]
                cities=[dict(r) for r in db.execute(f"SELECT municipio label,COUNT(*) value FROM companies WHERE {where} GROUP BY municipio ORDER BY value DESC, municipio LIMIT 5",vals)]
                timeline=[dict(r) for r in db.execute(f"SELECT substr(data_abertura,1,7) label,COUNT(*) value FROM companies WHERE {where} AND data_abertura<>'' GROUP BY substr(data_abertura,1,7) ORDER BY label",vals)]
                pipeline=[dict(r) for r in db.execute(f"SELECT COALESCE(NULLIF(lead_status,''),'novo') label,COUNT(*) value FROM companies WHERE {where} GROUP BY COALESCE(NULLIF(lead_status,''),'novo')",vals)]
                favorites=db.execute(f"SELECT COUNT(*) FROM companies WHERE {where} AND favorito=1",vals).fetchone()[0]
                mei_summary=dict(db.execute(f"""SELECT COUNT(*) total, COUNT(DISTINCT cnae) cnaes,
                    COUNT(DISTINCT municipio) municipios, MAX(data_abertura) ultima_data
                    FROM companies WHERE {mei_where} AND mei=1""",mei_vals).fetchone())
                mei_cnaes=[dict(r) for r in db.execute(f"""SELECT cnae label,MAX(cnae_descricao) description,segmento category,COUNT(*) value
                    FROM companies WHERE {mei_where} AND mei=1 AND cnae<>''
                    GROUP BY cnae,segmento ORDER BY value DESC,cnae LIMIT 10""",mei_vals)]
                mei_groups=[dict(r) for r in db.execute(f"""SELECT segmento label,COUNT(*) value
                    FROM companies WHERE {mei_where} AND mei=1 AND segmento<>''
                    GROUP BY segmento ORDER BY value DESC,segmento LIMIT 6""",mei_vals)]
                mei_cities=[dict(r) for r in db.execute(f"""SELECT municipio label,COUNT(*) value
                    FROM companies WHERE {mei_where} AND mei=1 AND municipio<>''
                    GROUP BY municipio ORDER BY value DESC,municipio LIMIT 5""",mei_vals)]
                mei_timeline=[dict(r) for r in db.execute(f"""SELECT substr(data_abertura,1,7) label,COUNT(*) value
                    FROM companies WHERE {mei_where} AND mei=1 AND data_abertura<>''
                    GROUP BY substr(data_abertura,1,7) ORDER BY label""",mei_vals)]
                summary["base_ultima_data"] = db.execute("SELECT MAX(data_abertura) FROM companies WHERE uf='RS'").fetchone()[0]
                options={k:[r[0] for r in db.execute(f"SELECT DISTINCT {k} FROM companies WHERE {k}<>'' ORDER BY {k}")] for k in ("municipio","regiao","segmento")}
                options["cnaes"] = [dict(r) for r in db.execute("SELECT cnae codigo,MAX(cnae_descricao) descricao,MAX(segmento) segmento,COUNT(*) empresas FROM companies WHERE cnae<>'' GROUP BY cnae ORDER BY empresas DESC,cnae")]
                opportunity_where, opportunity_vals = filters(p, {"score_min", "lead_status", "favorito"})
                high_clause = f"{opportunity_where} AND {LEAD_SCORE_SQL}>=80"
                high_total = db.execute(f"SELECT COUNT(*) FROM companies WHERE {high_clause}", opportunity_vals).fetchone()[0]
                high_contact = db.execute(f"SELECT COUNT(*) FROM companies WHERE {high_clause} AND (TRIM(COALESCE(email,''))<>'' OR TRIM(COALESCE(telefone,''))<>'')", opportunity_vals).fetchone()[0]
                high_mei = db.execute(f"SELECT COUNT(*) FROM companies WHERE {high_clause} AND mei=1", opportunity_vals).fetchone()[0]
                high_rows = db.execute(f"SELECT * FROM companies WHERE {high_clause} ORDER BY {LEAD_SCORE_SQL} DESC,data_abertura DESC,id DESC LIMIT 8", opportunity_vals).fetchall()
                high_items = [dict(row) for row in high_rows]
                for item in high_items:
                    item["lead_score"] = score_company(item)
            return self.send_json({"summary":summary,"groups":groups,"cnaes":cnaes,"cities":cities,"timeline":timeline,
                "pipeline":pipeline,"favorites":favorites,"options":options,"mei_summary":mei_summary,
                "mei_cnaes":mei_cnaes,"mei_groups":mei_groups,"mei_cities":mei_cities,"mei_timeline":mei_timeline,
                "opportunities":{"total":high_total,"with_contact":high_contact,"mei":high_mei,"items":high_items}})
        path = STATIC / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        try:
            path=path.resolve(); path.relative_to(STATIC.resolve()); data=path.read_bytes()
        except (FileNotFoundError, ValueError): return self.send_error(404)
        self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length",str(len(data))); self.security_headers(); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        if self.path == "/login":
            length=min(int(self.headers.get("Content-Length","0")),4096)
            form=parse_qs(self.rfile.read(length).decode("utf-8",errors="replace"))
            username=form.get("username",[""])[0].strip(); password=form.get("password",[""])[0]
            expected_user=os.environ.get("RADAR_ADMIN_USER",""); expected_password=os.environ.get("RADAR_ADMIN_PASSWORD","")
            if expected_user and hmac.compare_digest(username,expected_user) and hmac.compare_digest(password,expected_password):
                return self.set_session_and_redirect(expected_user)
            account = account_by_login(username) if username else None
            if account and password_matches(password, account["password_salt"], account["password_hash"]):
                with connect() as db:
                    db.execute("UPDATE user_accounts SET last_login_at=?,updated_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), account["id"]))
                    db.commit()
                return self.set_session_and_redirect(account["username"])
            return self.render_auth_page("login", "Usuário, e-mail ou senha incorretos.", status=401)
        if self.path == "/register":
            if not registration_enabled():
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
                    db.execute(
                        """INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,'vendedor',1,?,?)""",
                        ("conta-" + uuid.uuid4().hex, name, username, email, digest, salt, now, now),
                    )
                    db.commit()
            except sqlite3.IntegrityError:
                return self.render_auth_page("register", "Este nome de usuário já está em uso.", values, 409)
            return self.set_session_and_redirect(username)
        if not self.require_auth(): return
        if self.path == "/api/sync":
            started = SYNC.start()
            return self.send_json({"iniciado":started,**SYNC.snapshot()},202 if started else 200)
        if self.path == "/api/monitor":
            started = MONITOR.start()
            snapshot = MONITOR.snapshot()
            status = 202 if started else (409 if not snapshot["configurado"] else 200)
            return self.send_json({"iniciado": started, **snapshot}, status)
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
            with connect() as db:
                db.execute("INSERT INTO sales_profiles(id,name,role,email,initials,color,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (profile_id, name, role, email, initials, "#b82043", now, now))
                db.commit()
            return self.send_json({"id": profile_id, "name": name, "role": role, "email": email, "initials": initials, "color": "#b82043", "lead_count": 0, "favorite_count": 0}, 201)
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
                if not db.execute("SELECT 1 FROM sales_profiles WHERE id=?", (profile_id,)).fetchone():
                    return self.send_json({"erro": "Perfil individual não encontrado"}, 404)
                if not db.execute("SELECT 1 FROM companies WHERE cnpj=?", (cnpj,)).fetchone():
                    return self.send_json({"erro": "Empresa não encontrada"}, 404)
                now = datetime.now().isoformat(timespec="seconds")
                cursor = db.execute("INSERT OR IGNORE INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES(?,?,?,?)", (profile_id, cnpj, now, now))
                if not cursor.rowcount:
                    db.execute("UPDATE sales_profile_leads SET updated_at=? WHERE profile_id=? AND cnpj=?", (now, profile_id, cnpj))
                db.execute("UPDATE sales_profiles SET updated_at=? WHERE id=?", (now, profile_id))
                db.commit()
                count = db.execute("SELECT COUNT(*) FROM sales_profile_leads WHERE profile_id=?", (profile_id,)).fetchone()[0]
            return self.send_json({"adicionado": bool(cursor.rowcount), "profile_id": profile_id, "cnpj": cnpj, "lead_count": count}, 201 if cursor.rowcount else 200)
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
            valid_fields = {"q", "inicio", "fim", "segmento", "cnae", "municipio", "regiao", "situacao", "mei", "contato", "lead_status", "favorito", "score_min"}
            clean_filters = {key: str(value)[:180] for key, value in raw_filters.items() if key in valid_fields and str(value).strip()}
            profile_id = "perfil-" + uuid.uuid4().hex[:12]
            now = datetime.now().isoformat(timespec="seconds")
            with connect() as db:
                db.execute("INSERT INTO prospecting_profiles(id,name,description,filters_json,is_system,created_at,updated_at) VALUES(?,?,?,?,0,?,?)", (profile_id, name, description, json.dumps(clean_filters, ensure_ascii=False), now, now))
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
                profile = db.execute("SELECT id,name,is_system FROM prospecting_profiles WHERE id=?", (profile_id,)).fetchone()
                if not profile:
                    return self.send_json({"erro": "Perfil não encontrado"}, 404)
                if profile["is_system"]:
                    return self.send_json({"erro": "Escolha um perfil personalizado para montar uma carteira"}, 400)
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
        if not self.require_auth(): return
        parsed = urlparse(self.path)
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
                if payload["lead_status"] not in ("novo", "qualificado", "contatado", "negociacao", "convertido", "descartado"):
                    return self.send_json({"erro": "Etapa inválida"}, 400)
                allowed["lead_status"] = payload["lead_status"]
            if "favorito" in payload: allowed["favorito"] = 1 if payload["favorito"] else 0
            if "observacoes" in payload: allowed["observacoes"] = str(payload["observacoes"])[:4000]
            if "estrategia" in payload: allowed["estrategia"] = str(payload["estrategia"])[:4000]
            if not allowed:
                return self.send_json({"erro": "Nenhuma alteração válida"}, 400)
            with connect() as db:
                if not db.execute("SELECT 1 FROM sales_profiles WHERE id=?", (profile_id,)).fetchone():
                    return self.send_json({"erro": "Perfil individual não encontrado"}, 404)
                if not db.execute("SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj)).fetchone():
                    return self.send_json({"erro": "Adicione o lead à carteira antes de editar"}, 404)
                allowed["updated_at"] = datetime.now().isoformat(timespec="seconds")
                assignments = ",".join(f"{key}=?" for key in allowed)
                db.execute(f"UPDATE sales_profile_leads SET {assignments} WHERE profile_id=? AND cnpj=?", list(allowed.values()) + [profile_id, cnpj])
                db.execute("UPDATE sales_profiles SET updated_at=? WHERE id=?", (allowed["updated_at"], profile_id))
                db.commit()
                row = db.execute("""SELECT c.*, spl.profile_id, spl.updated_at AS profile_updated_at,
                    spl.favorito AS profile_favorito, spl.lead_status AS profile_lead_status,
                    spl.observacoes AS profile_observacoes, spl.estrategia AS profile_estrategia
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
            if payload["lead_status"] not in ("novo","qualificado","contatado","negociacao","convertido","descartado"):
                return self.send_json({"erro":"Etapa inválida"},400)
            allowed["lead_status"] = payload["lead_status"]
        if "favorito" in payload: allowed["favorito"] = 1 if payload["favorito"] else 0
        if "observacoes" in payload: allowed["observacoes"] = str(payload["observacoes"])[:4000]
        if not allowed: return self.send_json({"erro":"Nenhuma alteração válida"},400)
        assignments = ",".join(f"{key}=?" for key in allowed)
        with connect() as db:
            cursor=db.execute(f"UPDATE companies SET {assignments} WHERE cnpj=?",list(allowed.values())+[cnpj]);db.commit()
            if not cursor.rowcount: return self.send_json({"erro":"Empresa não encontrada"},404)
            result=dict(db.execute("SELECT * FROM companies WHERE cnpj=?",(cnpj,)).fetchone())
        result["lead_score"] = score_company(result)
        return self.send_json(result)

    def do_DELETE(self):
        if not self.require_auth(): return
        parsed = urlparse(self.path)
        if parsed.path == "/api/team-leads":
            params = parse_qs(parsed.query)
            profile_id = str(params.get("profile_id", [""])[0]).strip()
            cnpj = ''.join(c for c in str(params.get("cnpj", [""])[0]).upper() if c.isalnum())
            if not profile_id or len(cnpj) != 14:
                return self.send_json({"erro": "Perfil ou CNPJ inválido"}, 400)
            with connect() as db:
                cursor = db.execute("DELETE FROM sales_profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj))
                db.commit()
            return self.send_json({"removido": bool(cursor.rowcount), "profile_id": profile_id, "cnpj": cnpj})
        if parsed.path.startswith("/api/team-profiles/"):
            profile_id = parsed.path.rsplit("/", 1)[-1]
            with connect() as db:
                row = db.execute("SELECT id FROM sales_profiles WHERE id=?", (profile_id,)).fetchone()
                if not row:
                    return self.send_json({"erro": "Perfil individual não encontrado"}, 404)
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
                cursor = db.execute("DELETE FROM profile_leads WHERE profile_id=? AND cnpj=?", (profile_id, cnpj))
                db.commit()
            return self.send_json({"removido": bool(cursor.rowcount), "profile_id": profile_id, "cnpj": cnpj})
        if not parsed.path.startswith("/api/profiles/"):
            return self.send_error(404)
        profile_id = parsed.path.rsplit("/", 1)[-1]
        with connect() as db:
            row = db.execute("SELECT is_system FROM prospecting_profiles WHERE id=?", (profile_id,)).fetchone()
            if not row:
                return self.send_json({"erro": "Perfil não encontrado"}, 404)
            if row[0]:
                return self.send_json({"erro": "Perfis do sistema não podem ser excluídos"}, 400)
            db.execute("DELETE FROM prospecting_profiles WHERE id=?", (profile_id,))
            db.commit()
        return self.send_json({"excluido": True})

    def log_message(self, fmt, *args): print(f"[{self.log_date_time_string()}] {fmt % args}")


if __name__ == "__main__":
    init_db(); port=int(os.environ.get("PORT",os.environ.get("RADAR_PORT","8000"))); host=os.environ.get("RADAR_HOST","127.0.0.1")
    if os.environ.get("RADAR_AUTO_SYNC","1") != "0": SYNC.start_scheduler()
    if os.environ.get("RADAR_SERPRO_AUTO_MONITOR", "1") != "0": MONITOR.start_scheduler()
    print(f"Radar CNPJ RS disponível em http://{host}:{port}")
    ThreadingHTTPServer((host,port),Handler).serve_forever()
