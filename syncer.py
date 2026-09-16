"""Sincronização automática dos Dados Abertos do CNPJ com recorte para o RS."""
import base64
import csv
import json
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from contextlib import closing
from datetime import date, timedelta, datetime
from pathlib import Path
from xml.etree import ElementTree

from importer import region_for, segment_for

SHARE_TOKEN = "YggdBLfdninEJX9"
WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav"
FILES = "https://arquivos.receitafederal.gov.br/public.php/dav/files"
DAV_NS = {"d": "DAV:"}


def _auth():
    value = base64.b64encode(f"{SHARE_TOKEN}:".encode()).decode()
    return {"Authorization": f"Basic {value}", "User-Agent": "Radar-CNPJ-RS/1.0"}


def _propfind(path):
    request = urllib.request.Request(f"{WEBDAV}/{path.lstrip('/')}", headers={**_auth(), "Depth": "1"}, method="PROPFIND")
    with urllib.request.urlopen(request, timeout=90) as response:
        return ElementTree.fromstring(response.read())


def discover_catalog():
    root = _propfind("")
    months = []
    for item in root.findall("d:response", DAV_NS):
        href = urllib.parse.unquote(item.findtext("d:href", "", DAV_NS)).rstrip("/")
        name = href.rsplit("/", 1)[-1]
        try:
            datetime.strptime(name, "%Y-%m")
            months.append(name)
        except ValueError:
            pass
    if not months:
        raise RuntimeError("Nenhuma competência encontrada no repositório da Receita")
    month = sorted(months)[-1]
    listing = _propfind(month + "/")
    files = []
    for item in listing.findall("d:response", DAV_NS):
        href = urllib.parse.unquote(item.findtext("d:href", "", DAV_NS)).rstrip("/")
        name = href.rsplit("/", 1)[-1]
        if not name.lower().endswith(".zip"):
            continue
        length = item.findtext(".//d:getcontentlength", "0", DAV_NS)
        files.append({"name": name, "size": int(length or 0)})
    return {"competencia": month, "files": files}


class CNPJSync:
    def __init__(self, db_path, cache_dir):
        self.db_path = Path(db_path)
        self.cache_dir = Path(cache_dir)
        self.lock = threading.Lock()
        self.thread = None
        self.scheduler_thread = None
        self.state = {"status": "idle", "fase": "Aguardando", "progresso": 0, "mensagem": "", "competencia": None, "baixados": 0, "total_bytes": 0, "importados": 0, "iniciado_em": None, "finalizado_em": None}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self, days=120):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.state.update({"status":"starting","fase":"Consultando a Receita Federal","progresso":0,"mensagem":"","baixados":0,"total_bytes":0,"importados":0,"iniciado_em":datetime.now().isoformat(timespec="seconds"),"finalizado_em":None})
            self.thread = threading.Thread(target=self._run_safe, args=(days,), daemon=True, name="cnpj-sync")
            self.thread.start()
            return True

    def _run_safe(self, days):
        try:
            self._run(days)
        except Exception as exc:
            self._set(status="error", fase="Falha na sincronização", mensagem=str(exc), finalizado_em=datetime.now().isoformat(timespec="seconds"))

    def _download(self, month, info, index, count):
        month_cache = self.cache_dir / month
        month_cache.mkdir(parents=True, exist_ok=True)
        target = month_cache / info["name"]
        url = f"{FILES}/{SHARE_TOKEN}/{month}/{urllib.parse.quote(info['name'])}"
        self._set(fase=f"Baixando {info['name']}", progresso=round(index / max(count,1) * 70, 1))
        existing = target.stat().st_size if target.exists() else 0
        expected = info.get("size", 0)
        if expected and existing == expected:
            with self.lock: self.state["baixados"] += existing
            return target
        headers = _auth()
        if existing: headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(request, timeout=300)
        append = existing > 0 and response.status == 206
        if not append: existing = 0
        with self.lock: self.state["baixados"] += existing
        with response, target.open("ab" if append else "wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block: break
                output.write(block)
                with self.lock:
                    self.state["baixados"] += len(block)
                    if self.state["total_bytes"]:
                        self.state["progresso"] = round(min(70, self.state["baixados"] / self.state["total_bytes"] * 70), 1)
        return target

    @staticmethod
    def _rows_from_zip(path):
        archive = zipfile.ZipFile(path)
        names = [n for n in archive.namelist() if not n.endswith("/")]
        if not names: return
        with archive, archive.open(names[0]) as raw:
            import io
            with io.TextIOWrapper(raw, encoding="latin-1", errors="replace", newline="") as text:
                yield from csv.reader(text, delimiter=";", quotechar='"')

    def _run(self, days):
        catalog = discover_catalog()
        month, available = catalog["competencia"], {f["name"]:f for f in catalog["files"]}
        needed = (["Municipios.zip"] if "Municipios.zip" in available else []) + (["Cnaes.zip"] if "Cnaes.zip" in available else []) + sorted([n for n in available if n.startswith("Estabelecimentos")]) + sorted([n for n in available if n.startswith("Empresas")])
        if "Simples.zip" in available: needed.append("Simples.zip")
        total_bytes = sum(available[n]["size"] for n in needed)
        self._set(status="running", competencia=month, total_bytes=total_bytes, mensagem=f"Base oficial {month}")
        since = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
        establishments, basics = [], set()
        municipalities = {}
        cnae_catalog = {}

        establishment_files = [n for n in needed if n.startswith("Estabelecimentos")]
        company_files = [n for n in needed if n.startswith("Empresas")]
        file_index = 0
        if "Municipios.zip" in available:
            path = self._download(month, available["Municipios.zip"], file_index, len(needed)); file_index += 1
            self._set(fase="Carregando municípios")
            try:
                municipalities = {row[0]:row[1].title() for row in self._rows_from_zip(path) if len(row) >= 2}
            finally:
                path.unlink(missing_ok=True)
        if "Cnaes.zip" in available:
            path = self._download(month, available["Cnaes.zip"], file_index, len(needed)); file_index += 1
            self._set(fase="Carregando descrições oficiais dos CNAEs")
            try:
                cnae_catalog = {row[0]: row[1].strip() for row in self._rows_from_zip(path) if len(row) >= 2}
            finally:
                path.unlink(missing_ok=True)
        for name in establishment_files:
            path = self._download(month, available[name], file_index, len(needed)); file_index += 1
            self._set(fase=f"Filtrando RS em {name}")
            try:
                for row in self._rows_from_zip(path):
                    if len(row) < 28 or row[19].upper() != "RS" or row[10] < since: continue
                    basics.add(row[0]); establishments.append(row)
            finally:
                path.unlink(missing_ok=True)

        companies = {}
        for name in company_files:
            path = self._download(month, available[name], file_index, len(needed)); file_index += 1
            self._set(fase=f"Cruzando razões sociais em {name}")
            try:
                for row in self._rows_from_zip(path):
                    if len(row) >= 6 and row[0] in basics:
                        companies[row[0]] = {"razao":row[1], "porte":row[5]}
            finally:
                path.unlink(missing_ok=True)

        mei = set()
        if "Simples.zip" in available:
            path = self._download(month, available["Simples.zip"], file_index, len(needed)); file_index += 1
            self._set(fase="Identificando microempreendedores")
            try:
                for row in self._rows_from_zip(path):
                    if len(row) >= 5 and row[0] in basics and row[4].upper() == "S": mei.add(row[0])
            finally:
                path.unlink(missing_ok=True)

        self._set(fase="Atualizando o banco local", progresso=85)
        situation = {"01":"NULA","02":"ATIVA","03":"SUSPENSA","04":"INAPTA","08":"BAIXADA"}
        porte = {"00":"NÃO INFORMADO","01":"ME","03":"EPP","05":"DEMAIS"}
        records = []
        for row in establishments:
            company = companies.get(row[0], {})
            city = municipalities.get(row[20], row[20])
            records.append((row[0]+row[1]+row[2],company.get("razao") or row[4] or "Sem razão social",row[4],situation.get(row[5],row[5]),
                f"{row[10][:4]}-{row[10][4:6]}-{row[10][6:8]}" if len(row[10])==8 else "",row[11],cnae_catalog.get(row[11], ""),row[12],segment_for(row[11]),city,region_for(city),"RS",row[18],row[17],
                " ".join(filter(None,[row[13],row[14]])),row[15],row[21]+row[22] if row[22] else "",row[27],porte.get(company.get("porte",""),company.get("porte","")),1 if row[0] in mei else 0))

        sql="""INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,cnae_descricao,cnaes_secundarios,segmento,municipio,regiao,uf,cep,bairro,logradouro,numero,telefone,email,porte,mei)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cnpj) DO UPDATE SET razao_social=excluded.razao_social,nome_fantasia=excluded.nome_fantasia,situacao=excluded.situacao,data_abertura=excluded.data_abertura,cnae=excluded.cnae,cnae_descricao=CASE WHEN excluded.cnae_descricao<>'' THEN excluded.cnae_descricao ELSE companies.cnae_descricao END,cnaes_secundarios=excluded.cnaes_secundarios,segmento=excluded.segmento,municipio=excluded.municipio,regiao=excluded.regiao,uf=excluded.uf,cep=excluded.cep,bairro=excluded.bairro,logradouro=excluded.logradouro,numero=excluded.numero,telefone=excluded.telefone,email=excluded.email,porte=excluded.porte,mei=excluded.mei,data_source='Receita Federal'"""
        with closing(sqlite3.connect(self.db_path)) as db:
            existing_columns = {row[1] for row in db.execute("PRAGMA table_info(companies)")}
            if "cnae_descricao" not in existing_columns:
                db.execute("ALTER TABLE companies ADD COLUMN cnae_descricao TEXT DEFAULT ''")
            if "data_source" not in existing_columns:
                db.execute("ALTER TABLE companies ADD COLUMN data_source TEXT DEFAULT 'Receita Federal'")
            db.executemany(sql, records)
            db.execute("CREATE TABLE IF NOT EXISTS cnae_catalog(codigo TEXT PRIMARY KEY,descricao TEXT NOT NULL)")
            if cnae_catalog:
                db.executemany("INSERT OR REPLACE INTO cnae_catalog(codigo,descricao) VALUES(?,?)", cnae_catalog.items())
                db.execute("UPDATE companies SET cnae_descricao=COALESCE((SELECT descricao FROM cnae_catalog WHERE codigo=companies.cnae),cnae_descricao,'')")
            db.execute("CREATE TABLE IF NOT EXISTS sync_meta(key TEXT PRIMARY KEY,value TEXT)")
            db.execute("INSERT OR REPLACE INTO sync_meta VALUES('competencia',?)",(month,))
            db.execute("INSERT OR REPLACE INTO sync_meta VALUES('sincronizado_em',?)",(datetime.now().isoformat(timespec="seconds"),))
            if cnae_catalog:
                db.execute("INSERT OR REPLACE INTO sync_meta VALUES('cnae_catalog_competencia',?)",(month,))
            db.execute("DELETE FROM companies WHERE email LIKE '%@%.demo'")
            db.commit()
        self._set(status="complete",fase="Sincronização concluída",progresso=100,importados=len(records),finalizado_em=datetime.now().isoformat(timespec="seconds"),mensagem=f"{len(records):,} estabelecimentos recentes do RS atualizados")

    def schedule_if_needed(self):
        try:
            catalog = discover_catalog()
            remote_month = catalog["competencia"]
            with closing(sqlite3.connect(self.db_path)) as db:
                db.execute("CREATE TABLE IF NOT EXISTS sync_meta(key TEXT PRIMARY KEY,value TEXT)")
                row=db.execute("SELECT value FROM sync_meta WHERE key='competencia'").fetchone()
                cnae_row=db.execute("SELECT value FROM sync_meta WHERE key='cnae_catalog_competencia'").fetchone()
                db.commit()
            if not row or row[0] != remote_month:
                self.start()
            elif not cnae_row or cnae_row[0] != remote_month:
                available = {f["name"]: f for f in catalog["files"]}
                if "Cnaes.zip" in available:
                    self._refresh_cnae_catalog(remote_month, available["Cnaes.zip"])
        except Exception as exc:
            self._set(status="error",fase="Falha ao agendar",mensagem=str(exc))

    def _refresh_cnae_catalog(self, month, info):
        """Baixa somente a tabela pequena de CNAEs quando a base principal já está atualizada."""
        self._set(status="running", fase="Atualizando descrições dos CNAEs", progresso=5, total_bytes=info.get("size", 0), baixados=0, iniciado_em=datetime.now().isoformat(timespec="seconds"), finalizado_em=None)
        path = self._download(month, info, 0, 1)
        try:
            catalog = {row[0]: row[1].strip() for row in self._rows_from_zip(path) if len(row) >= 2}
        finally:
            path.unlink(missing_ok=True)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS cnae_catalog(codigo TEXT PRIMARY KEY,descricao TEXT NOT NULL)")
            db.executemany("INSERT OR REPLACE INTO cnae_catalog(codigo,descricao) VALUES(?,?)", catalog.items())
            db.execute("UPDATE companies SET cnae_descricao=COALESCE((SELECT descricao FROM cnae_catalog WHERE codigo=companies.cnae),cnae_descricao,'')")
            db.execute("CREATE TABLE IF NOT EXISTS sync_meta(key TEXT PRIMARY KEY,value TEXT)")
            db.execute("INSERT OR REPLACE INTO sync_meta VALUES('cnae_catalog_competencia',?)", (month,))
            db.commit()
        self._set(status="complete", fase="Descrições dos CNAEs atualizadas", progresso=100, importados=len(catalog), finalizado_em=datetime.now().isoformat(timespec="seconds"), mensagem=f"{len(catalog):,} atividades econômicas catalogadas")

    def start_scheduler(self, check_interval=3600):
        """Verifica periodicamente se a cópia oficial precisa ser atualizada."""
        with self.lock:
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                return False

            def loop():
                while True:
                    self.schedule_if_needed()
                    time.sleep(check_interval)

            self.scheduler_thread = threading.Thread(target=loop, daemon=True, name="cnpj-sync-scheduler")
            self.scheduler_thread.start()
            return True
