"""Monitor diário e enriquecimento de CNPJs conhecidos pela API do Serpro.

A API Consulta CNPJ é uma consulta unitária: ela atualiza e valida um CNPJ já
conhecido. A descoberta de números novos pode ser conectada por um feed externo
em RADAR_DISCOVERY_URL; o monitor nunca apresenta essa validação como descoberta.
"""
import base64
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from importer import cnpj_chars, region_for, segment_for


SERPRO_ENDPOINTS = {
    "producao": {
        "token": "https://apigateway.conectagov.estaleiro.serpro.gov.br/oauth2/jwt-token",
        "company": "https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnpj-empresa/v2/empresa/",
    },
    "homologacao": {
        "token": "https://h-apigateway.conectagov.np.estaleiro.serpro.gov.br/oauth2/jwt-token",
        "company": "https://h-apigateway.conectagov.np.estaleiro.serpro.gov.br/api-cnpj-empresa/v2/empresa/",
    },
}


def _dig(data, *paths, default=""):
    """Retorna o primeiro caminho presente em respostas com versões diferentes."""
    for path in paths:
        value = data
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value not in (None, ""):
            return value
    return default


def _iso_date(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def normalize_company(payload):
    """Converte a resposta Serpro/Conecta para os campos internos do Radar."""
    root = payload.get("empresa") if isinstance(payload, dict) and isinstance(payload.get("empresa"), dict) else payload
    if not isinstance(root, dict):
        raise ValueError("Resposta da Serpro sem objeto de empresa")
    cnpj = cnpj_chars(str(_dig(root, "ni", "cnpj", "numeroInscricao", "estabelecimento.cnpj")))
    if len(cnpj) != 14:
        raise ValueError("Resposta da Serpro sem CNPJ válido")
    cnae_obj = _dig(root, "cnaePrincipal", "atividadeEconomicaPrincipal", default={})
    if not isinstance(cnae_obj, dict):
        cnae_obj = {}
    cnae = "".join(c for c in str(_dig(cnae_obj, "codigo", "code", default=cnae_obj if isinstance(cnae_obj, str) else "")) if c.isdigit())
    cnae_description = str(_dig(cnae_obj, "descricao", "description", default="")).strip()
    secondary = _dig(root, "cnaesSecundarias", "atividadesEconomicasSecundarias", default=[])
    if isinstance(secondary, list):
        secondary_codes = []
        for item in secondary:
            if isinstance(item, dict):
                secondary_codes.append(str(_dig(item, "codigo", "code", default="")))
            else:
                secondary_codes.append(str(item))
        secondary = ",".join(filter(None, secondary_codes))
    address = _dig(root, "endereco", "estabelecimento.endereco", default={})
    if not isinstance(address, dict):
        address = {}
    city = str(_dig(address, "municipio.descricao", "municipio.nome", "municipio", "cidade", default=_dig(root, "municipio", default=""))).strip().title()
    state = str(_dig(address, "uf", "siglaUf", default=_dig(root, "uf", default=""))).upper()
    phone = _dig(root, "telefone", "telefones.0.numero", default="")
    phones = root.get("telefones") if isinstance(root, dict) else None
    if not phone and isinstance(phones, list) and phones:
        first = phones[0]
        phone = _dig(first, "dddNumero", "numero", default=first if isinstance(first, str) else "")
    simei = _dig(root, "opcaoSimei", "simei", "optanteSimei", default=False)
    if isinstance(simei, dict):
        simei = _dig(simei, "optante", "indicador", default=False)
    situation = _dig(root, "situacaoCadastral.descricao", "situacaoCadastral", "situacao.descricao", "situacao", default="ATIVA")
    if isinstance(situation, dict):
        situation = _dig(situation, "descricao", "codigo", default="ATIVA")
    return {
        "cnpj": cnpj,
        "razao_social": str(_dig(root, "nomeEmpresarial", "razaoSocial", "nome", default="Sem razão social")).strip(),
        "nome_fantasia": str(_dig(root, "nomeFantasia", "tituloEstabelecimento", default="")).strip(),
        "situacao": str(situation).upper(),
        "data_abertura": _iso_date(_dig(root, "dataAbertura", "dataInicioAtividade", default="")),
        "cnae": cnae,
        "cnae_descricao": cnae_description,
        "cnaes_secundarios": str(secondary or ""),
        "segmento": segment_for(cnae),
        "municipio": city,
        "regiao": region_for(city),
        "uf": state,
        "cep": "".join(c for c in str(_dig(address, "cep", default="")) if c.isdigit()),
        "bairro": str(_dig(address, "bairro", default="")).strip(),
        "logradouro": " ".join(filter(None, [str(_dig(address, "tipoLogradouro", default="")).strip(), str(_dig(address, "logradouro", default="")).strip()])),
        "numero": str(_dig(address, "numero", default="")).strip(),
        "telefone": "".join(c for c in str(phone or "") if c.isdigit()),
        "email": str(_dig(root, "correioEletronico", "email", default="")).strip(),
        "porte": str(_dig(root, "porte.descricao", "porte", default="")).strip(),
        "mei": 1 if str(simei).strip().upper() in ("1", "S", "SIM", "TRUE") else 0,
    }


class SerproClient:
    def __init__(self):
        environment = os.environ.get("RADAR_SERPRO_ENV", "producao").strip().lower()
        if environment not in SERPRO_ENDPOINTS:
            environment = "producao"
        self.environment = environment
        self.key = os.environ.get("RADAR_SERPRO_CONSUMER_KEY", "").strip()
        self.secret = os.environ.get("RADAR_SERPRO_CONSUMER_SECRET", "").strip()
        self.user_cpf = "".join(c for c in os.environ.get("RADAR_SERPRO_USER_CPF", "") if c.isdigit())
        defaults = SERPRO_ENDPOINTS[environment]
        self.token_url = os.environ.get("RADAR_SERPRO_TOKEN_URL", defaults["token"]).strip()
        self.company_url = os.environ.get("RADAR_SERPRO_API_URL", defaults["company"]).strip().rstrip("/") + "/"
        self._token = ""
        self._expires_at = 0.0

    def missing(self):
        result = []
        if not self.key:
            result.append("Consumer Key")
        if not self.secret:
            result.append("Consumer Secret")
        if not self.user_cpf:
            result.append("CPF do usuário responsável")
        return result

    @property
    def configured(self):
        return not self.missing()

    def _access_token(self):
        if self._token and time.time() < self._expires_at - 30:
            return self._token
        auth = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        body = b"grant_type=client_credentials"
        request = urllib.request.Request(
            self.token_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "Radar-CNPJ-RS/2.0",
            },
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        token = data.get("access_token") or data.get("token")
        if not token:
            raise RuntimeError("A Serpro não retornou um token de acesso")
        self._token = token
        self._expires_at = time.time() + int(data.get("expires_in") or 300)
        return token

    def query(self, cnpj):
        if not self.configured:
            raise RuntimeError("Credenciais Serpro incompletas")
        identifier = cnpj_chars(cnpj)
        if len(identifier) != 14:
            raise ValueError("CNPJ inválido na fila de monitoramento")
        request = urllib.request.Request(
            self.company_url + identifier,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "x-cpf-usuario": self.user_cpf,
                "Accept": "application/json",
                "User-Agent": "Radar-CNPJ-RS/2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"Serpro respondeu HTTP {exc.code}: {detail[:300]}") from exc
        return normalize_company(payload)


class DailyMonitor:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.lock = threading.Lock()
        self.thread = None
        self.scheduler_thread = None
        self.state = {
            "status": "idle",
            "fase": "Aguardando a próxima rodada",
            "mensagem": "",
            "processados": 0,
            "atualizados": 0,
            "falhas": 0,
            "iniciado_em": None,
            "finalizado_em": None,
        }

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def snapshot(self):
        client = SerproClient()
        with self.lock:
            result = dict(self.state)
        with closing(self._connect()) as db:
            pending = db.execute("SELECT COUNT(*) FROM monitor_candidates WHERE status IN ('pendente','falha')").fetchone()[0]
            last = db.execute("SELECT * FROM monitor_runs ORDER BY id DESC LIMIT 1").fetchone()
            validated_today = db.execute("SELECT COUNT(*) FROM companies WHERE date(serpro_checked_at)=date('now','localtime')").fetchone()[0]
        result.update({
            "configurado": client.configured,
            "pendencias_configuracao": client.missing(),
            "ambiente": client.environment,
            "limite_diario": max(1, int(os.environ.get("RADAR_SERPRO_DAILY_LIMIT", "50"))),
            "janela_dias": max(1, int(os.environ.get("RADAR_SERPRO_MONITOR_DAYS", "30"))),
            "hora_execucao": max(0, min(23, int(os.environ.get("RADAR_SERPRO_DAILY_HOUR", "6")))),
            "fonte_descoberta_configurada": bool(os.environ.get("RADAR_DISCOVERY_URL", "").strip()),
            "fila": pending,
            "validados_hoje": validated_today,
            "ultima_execucao": dict(last) if last else None,
        })
        return result

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self):
        client = SerproClient()
        if not client.configured:
            self._set(status="configuration_required", fase="Configuração pendente", mensagem="Informe as credenciais contratadas da Serpro.")
            return False
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.state.update({"status": "starting", "fase": "Preparando a fila diária", "mensagem": "", "processados": 0, "atualizados": 0, "falhas": 0, "iniciado_em": datetime.now().isoformat(timespec="seconds"), "finalizado_em": None})
            self.thread = threading.Thread(target=self._run_safe, daemon=True, name="serpro-daily-monitor")
            self.thread.start()
            return True

    def _run_safe(self):
        try:
            self._run()
        except Exception as exc:
            self._set(status="error", fase="Falha no monitor diário", mensagem=str(exc), finalizado_em=datetime.now().isoformat(timespec="seconds"))

    def _discover(self):
        url = os.environ.get("RADAR_DISCOVERY_URL", "").strip()
        if not url:
            return 0
        headers = {"Accept": "application/json", "User-Agent": "Radar-CNPJ-RS/2.0"}
        token = os.environ.get("RADAR_DISCOVERY_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload.get("cnpjs", payload.get("items", [])) if isinstance(payload, dict) else payload
        if not isinstance(raw, list):
            raise RuntimeError("O feed de descoberta não retornou uma lista de CNPJs")
        added = 0
        with closing(self._connect()) as db:
            for entry in raw:
                value = entry.get("cnpj") if isinstance(entry, dict) else entry
                cnpj = cnpj_chars(str(value or ""))
                if len(cnpj) != 14:
                    continue
                cursor = db.execute("INSERT OR IGNORE INTO monitor_candidates(cnpj,source,status,discovered_at) VALUES(?,?,'pendente',?)", (cnpj, "feed automático", datetime.now().isoformat(timespec="seconds")))
                added += cursor.rowcount
            db.commit()
        return added

    def _upsert(self, db, item):
        if item.get("uf") and item["uf"] != "RS":
            return False
        columns = ("cnpj", "razao_social", "nome_fantasia", "situacao", "data_abertura", "cnae", "cnae_descricao", "cnaes_secundarios", "segmento", "municipio", "regiao", "uf", "cep", "bairro", "logradouro", "numero", "telefone", "email", "porte", "mei")
        values = [item.get(key, "") for key in columns]
        assignments = ",".join(f"{key}=CASE WHEN excluded.{key}<>'' THEN excluded.{key} ELSE companies.{key} END" for key in columns if key not in ("cnpj", "mei"))
        db.execute(
            f"INSERT INTO companies({','.join(columns)},serpro_checked_at,data_source) VALUES({','.join('?' for _ in columns)},?,'Serpro') "
            f"ON CONFLICT(cnpj) DO UPDATE SET {assignments},mei=excluded.mei,serpro_checked_at=excluded.serpro_checked_at,data_source='Serpro'",
            values + [datetime.now().isoformat(timespec="seconds")],
        )
        return True

    def _run(self):
        client = SerproClient()
        limit = max(1, int(os.environ.get("RADAR_SERPRO_DAILY_LIMIT", "50")))
        monitor_days = max(1, int(os.environ.get("RADAR_SERPRO_MONITOR_DAYS", "30")))
        discovered = self._discover()
        cutoff = (date.today() - timedelta(days=monitor_days)).isoformat()
        with closing(self._connect()) as db:
            candidates = [row[0] for row in db.execute("""
                SELECT cnpj FROM monitor_candidates WHERE status IN ('pendente','falha')
                UNION
                SELECT cnpj FROM companies
                WHERE uf='RS' AND data_abertura>=? AND (serpro_checked_at IS NULL OR date(serpro_checked_at)<date('now','localtime'))
                ORDER BY 1 LIMIT ?
            """, (cutoff, limit)).fetchall()]
            started_at = datetime.now().isoformat(timespec="seconds")
            run_id = db.execute("INSERT INTO monitor_runs(started_at,status,discovered,processed,updated,failed,message) VALUES(?,'executando',?,0,0,0,'')", (started_at, discovered)).lastrowid
            db.commit()
        processed = updated = failed = 0
        self._set(status="running", fase="Validando CNPJs na Serpro", mensagem=f"{len(candidates)} CNPJs na rodada")
        for cnpj in candidates:
            try:
                item = client.query(cnpj)
                with closing(self._connect()) as db:
                    changed = self._upsert(db, item)
                    db.execute("INSERT INTO monitor_candidates(cnpj,source,status,discovered_at,checked_at,last_error,attempts) VALUES(?,?,'validado',?,?, '',1) ON CONFLICT(cnpj) DO UPDATE SET status='validado',checked_at=excluded.checked_at,last_error='',attempts=monitor_candidates.attempts+1", (cnpj, "base oficial", started_at, datetime.now().isoformat(timespec="seconds")))
                    db.commit()
                updated += 1 if changed else 0
            except Exception as exc:
                failed += 1
                with closing(self._connect()) as db:
                    db.execute("INSERT INTO monitor_candidates(cnpj,source,status,discovered_at,checked_at,last_error,attempts) VALUES(?,?,'falha',?,?,?,1) ON CONFLICT(cnpj) DO UPDATE SET status='falha',checked_at=excluded.checked_at,last_error=excluded.last_error,attempts=monitor_candidates.attempts+1", (cnpj, "base oficial", started_at, datetime.now().isoformat(timespec="seconds"), str(exc)[:500]))
                    db.commit()
            processed += 1
            self._set(processados=processed, atualizados=updated, falhas=failed, mensagem=f"{processed} de {len(candidates)} consultados")
        finished = datetime.now().isoformat(timespec="seconds")
        status = "complete" if not failed else "partial"
        message = "Nenhum CNPJ precisava de revalidação hoje." if not candidates else f"{updated} registros atualizados; {failed} falhas."
        with closing(self._connect()) as db:
            db.execute("UPDATE monitor_runs SET finished_at=?,status=?,processed=?,updated=?,failed=?,message=? WHERE id=?", (finished, status, processed, updated, failed, message, run_id))
            db.commit()
        self._set(status=status, fase="Rodada diária concluída", mensagem=message, finalizado_em=finished)

    def start_scheduler(self, check_interval=300):
        with self.lock:
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                return False

            def loop():
                while True:
                    try:
                        client = SerproClient()
                        hour = max(0, min(23, int(os.environ.get("RADAR_SERPRO_DAILY_HOUR", "6"))))
                        with closing(self._connect()) as db:
                            row = db.execute("SELECT started_at FROM monitor_runs ORDER BY id DESC LIMIT 1").fetchone()
                        last_day = (row[0] or "")[:10] if row else ""
                        if client.configured and datetime.now().hour >= hour and last_day != date.today().isoformat():
                            self.start()
                    except Exception as exc:
                        self._set(status="error", fase="Falha no agendamento Serpro", mensagem=str(exc))
                    time.sleep(check_interval)

            self.scheduler_thread = threading.Thread(target=loop, daemon=True, name="serpro-monitor-scheduler")
            self.scheduler_thread.start()
            return True
