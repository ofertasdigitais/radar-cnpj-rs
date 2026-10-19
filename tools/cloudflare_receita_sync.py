"""Receita -> ephemeral GitHub SQLite -> Radar-only authenticated, idempotent batches.

No Cloudflare account token, local user database, uploaded artifact, or paid API is used.
The existing syncer keeps the same 120-day RS scope and deletes each national ZIP
after parsing. Real execution is deliberately restricted to GitHub Actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import syncer  # noqa: E402 -- the existing official-source importer, not app.py

FIELDS = ("cnpj", "razao_social", "nome_fantasia", "situacao", "data_abertura", "cnae",
          "cnae_descricao", "cnaes_secundarios", "segmento", "municipio", "regiao", "uf",
          "cep", "bairro", "logradouro", "numero", "telefone", "email", "porte", "mei")
LIMITS = dict(zip(FIELDS, (14, 300, 300, 20, 10, 7, 1000, 6000, 120, 120, 120, 2,
                         8, 300, 500, 60, 60, 300, 60, 1)))
MAX_BODY = 2 * 1024 * 1024
MAX_RESPONSE = 128 * 1024


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def digest(rows):
    return hashlib.sha256(encoded(rows)).hexdigest()


def target_url(raw):
    """Only the production Radar Worker; credentials can never follow a redirect."""
    try:
        url = urllib.parse.urlsplit(raw)
        valid = (url.scheme == "https" and not url.username and not url.password
                 and url.port in (None, 443) and not url.query and not url.fragment
                 and url.path in ("", "/")
                 and re.fullmatch(r"radar-cnpj-rs(?:-current)?\.[a-z0-9-]+\.workers\.dev", url.hostname or ""))
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("RADAR_WORKERS_URL deve apontar para o Worker HTTPS do Radar")
    return raw.rstrip("/") + "/api/internal/receita"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirecionamento de rede recusado")


class RadarClient:
    def __init__(self, url, secret):
        self.url = target_url(url)
        if not re.fullmatch(r"[-A-Za-z0-9_]{48,256}", secret):
            raise RuntimeError("Segredo exclusivo de importação ausente ou inválido")
        self.secret = secret
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, action, **payload):
        body = encoded({"action": action, **payload})
        if len(body) > MAX_BODY:
            raise RuntimeError("Lote acima do limite de 2 MiB")
        for attempt in range(4):
            request = urllib.request.Request(self.url, data=body, method="POST", headers={
                "Authorization": "Bearer " + self.secret, "Content-Type": "application/json",
                "User-Agent": "Radar-Receita-GitHub/1.0", "Accept": "application/json"})
            try:
                with self.opener.open(request, timeout=90) as response:
                    content = response.read(MAX_RESPONSE + 1)
                    if len(content) > MAX_RESPONSE:
                        raise RuntimeError("Resposta do Radar acima do limite")
                    result = json.loads(content)
                    if not isinstance(result, dict):
                        raise RuntimeError("Resposta inválida do Radar")
                    return result
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()  # Never print server response bodies, records, URLs, or tokens.
                if status not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError(f"Radar recusou a operação {action} (HTTP {status})") from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 3:
                    raise RuntimeError("Radar indisponível durante a importação") from None
            time.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError("Operação não concluída")


def official_open(request, maximum=None):
    url = urllib.parse.urlsplit(request.full_url)
    if url.scheme != "https" or url.hostname != "arquivos.receitafederal.gov.br" or url.port not in (None, 443):
        raise RuntimeError("Origem oficial inválida")
    response = urllib.request.build_opener(NoRedirect()).open(request, timeout=120)
    if maximum is not None and int(response.headers.get("Content-Length") or 0) > maximum:
        response.close()
        raise RuntimeError("Arquivo oficial acima do limite")
    return response


def bounded_propfind(path):
    if path and not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])/", path):
        raise RuntimeError("Caminho do catálogo oficial inválido")
    request = urllib.request.Request(f"{syncer.WEBDAV}/{path}", method="PROPFIND",
                                     headers={**syncer._auth(), "Depth": "1"})
    with official_open(request, 4 * 1024 * 1024) as response:
        content = response.read(4 * 1024 * 1024 + 1)
    if len(content) > 4 * 1024 * 1024 or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise RuntimeError("Catálogo oficial inválido ou acima do limite")
    return ElementTree.fromstring(content)


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", str(catalog.get("competencia", ""))):
        raise RuntimeError("Competência oficial inválida")
    files = catalog.get("files")
    if not isinstance(files, list) or len(files) > 100:
        raise RuntimeError("Lista de arquivos oficiais inválida")
    selected = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise RuntimeError("Arquivo oficial inválido")
        name, size = item["name"], item.get("size")
        if not re.fullmatch(r"(?:Municipios|Cnaes|Simples|Estabelecimentos\d+|Empresas\d+)\.zip", name):
            continue
        if name in selected or not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= 6 * 1024 ** 3:
            raise RuntimeError("Tamanho ou duplicação de arquivo oficial inválido")
        selected[name] = {"name": name, "size": size}
    if not all(name in selected for name in ("Municipios.zip", "Cnaes.zip", "Simples.zip")):
        raise RuntimeError("Catálogo mensal ainda incompleto")
    for prefix in ("Estabelecimentos", "Empresas"):
        parts = sorted(int(name[len(prefix):-4]) for name in selected if name.startswith(prefix))
        if len(parts) < 10 or parts != list(range(len(parts))):
            raise RuntimeError("Partições nacionais ainda incompletas")
    if sum(item["size"] for item in selected.values()) > 100 * 1024 ** 3:
        raise RuntimeError("Volume oficial acima do limite")
    return {"competencia": catalog["competencia"], "files": list(selected.values())}


def initialize_temporary_db(path):
    # This schema is created only beneath TemporaryDirectory; no app/user DB is opened.
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE companies(id INTEGER PRIMARY KEY,cnpj TEXT UNIQUE," +
                   ",".join(field + (" INTEGER" if field == "mei" else " TEXT") for field in FIELDS if field != "cnpj") +
                   ",data_source TEXT DEFAULT 'Receita Federal')")


class RunnerSync(syncer.CNPJSync):
    def __init__(self, db_path, cache, client, run_id, deadline):
        super().__init__(db_path, cache)
        self.client, self.run_id, self.deadline = client, run_id, deadline
        self.last_heartbeat = 0.0

    def heartbeat(self, force=False):
        current = time.monotonic()
        if current > self.deadline:
            raise RuntimeError("Prazo seguro da carga oficial excedido")
        if not force and current - self.last_heartbeat < 60:
            return
        self.last_heartbeat = current
        phase = str(self.state.get("fase", ""))
        key = "download" if phase.startswith("Baixando") else "parse" if "Filtrando" in phase else "join" if "Cruzando" in phase else "ready" if "Atualizando" in phase else "catalog"
        self.client.call("status", run_id=self.run_id, phase=key,
                         progress=max(0, min(85, float(self.state.get("progresso", 0)))))

    def _set(self, **values):
        super()._set(**values)
        self.heartbeat()

    def _download(self, month, info, index, count):
        self._set(fase="Baixando arquivo oficial", progresso=min(70, index / max(count, 1) * 70))
        target = self.cache_dir / info["name"]  # validated basename; one ZIP at a time
        expected = info["size"]
        if shutil.disk_usage(self.cache_dir).free < expected + 512 * 1024 * 1024:
            raise RuntimeError("Espaço temporário insuficiente para o próximo ZIP")
        request = urllib.request.Request(f"{syncer.FILES}/{syncer.SHARE_TOKEN}/{month}/{urllib.parse.quote(info['name'])}", headers=syncer._auth())
        received = 0
        with official_open(request, expected) as response, target.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                received += len(block)
                if received > expected:
                    raise RuntimeError("Arquivo oficial excedeu o tamanho declarado")
                output.write(block)
                self.heartbeat()
        if received != expected:
            raise RuntimeError("Download oficial incompleto")
        return target

    def _rows_from_zip(self, path):
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 10 or any(entry.file_size > 80 * 1024 ** 3 or entry.flag_bits & 1 for entry in entries):
                raise RuntimeError("ZIP oficial inválido ou acima do limite")
        for index, row in enumerate(syncer.CNPJSync._rows_from_zip(path)):
            if index % 10000 == 0:
                self.heartbeat()
            yield row


def normalize_record(record):
    result = {}
    for key in FIELDS:
        value = record[key]
        if key == "mei":
            if value not in (0, 1):
                raise RuntimeError("Opção MEI inválida na carga temporária")
            result[key] = int(value)
        else:
            if not isinstance(value, str) or len(value) > LIMITS[key] or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
                raise RuntimeError("Campo oficial inválido na carga temporária")
            result[key] = value
    if result["uf"] != "RS" or not re.fullmatch(r"[A-Z0-9]{14}", result["cnpj"]):
        raise RuntimeError("Estabelecimento fora do recorte oficial do RS")
    return result


def record_batches(db):
    batch = []
    size = 2  # JSON array delimiters
    # Reserve envelope space: per-request sequence/hash/run ID add fewer than 512 bytes.
    for row in db.execute("SELECT " + ",".join(FIELDS) + " FROM companies ORDER BY cnpj"):
        record = normalize_record(row)
        addition = len(encoded(record)) + (1 if batch else 0)
        if batch and (len(batch) == 500 or size + addition > MAX_BODY - 2048):
            yield batch
            batch = []
            size = 2
            addition = len(encoded(record))
        batch.append(record)
        size += addition
    if batch:
        yield batch


def execute_pipeline(client, run_id):
    cloud = client.call("status")
    if cloud.get("enabled") is False:
        print("Verificação automática pausada no Radar.", flush=True)
        return
    with patch.object(syncer, "_propfind", bounded_propfind):
        catalog = validate_catalog(syncer.discover_catalog())
    month = catalog["competencia"]
    if str(cloud.get("competencia") or "") > month:
        raise RuntimeError("A fonte oficial está atrás da competência publicada")
    if cloud.get("competencia") == month and cloud.get("cnae_catalog_competencia") == month:
        print("Base oficial e catálogo CNAE já estão na competência disponível.", flush=True)
        return
    mode = "catalog" if cloud.get("competencia") == month else "full"
    started = False
    try:
        client.call("start", run_id=run_id, competencia=month, mode=mode)
        started = True
        print("Nova competência oficial detectada; preparando carga temporária.", flush=True)
        with tempfile.TemporaryDirectory(prefix="radar-receita-", dir=os.environ.get("RUNNER_TEMP")) as folder:
            root = Path(folder)
            database = root / "official-rs.sqlite"
            cache = root / "zip"
            cache.mkdir()
            initialize_temporary_db(database)
            importer = RunnerSync(database, cache, client, run_id, time.monotonic() + 335 * 60)
            # Freeze the validated monthly manifest for the unchanged importer. No second
            # month discovery can switch its source between acquiring the lock and upload.
            with patch.object(syncer, "discover_catalog", return_value=catalog):
                if mode == "catalog":
                    info = next(item for item in catalog["files"] if item["name"] == "Cnaes.zip")
                    importer._refresh_cnae_catalog(month, info)
                else:
                    importer._run(120)
            with closing(sqlite3.connect(database)) as db:
                db.row_factory = sqlite3.Row
                cnaes = [dict(row) for row in db.execute("SELECT codigo,descricao FROM cnae_catalog ORDER BY codigo")]
                if not 1000 <= len(cnaes) <= 2000 or len(encoded(cnaes)) > 512 * 1024:
                    raise RuntimeError("Catálogo CNAE oficial incompleto ou acima do limite")
                expected = db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] if mode == "full" else 0
                if mode == "full" and not 1 <= expected <= 1000000:
                    raise RuntimeError("Quantidade oficial de estabelecimentos fora do limite")
                client.call("start", run_id=run_id, competencia=month, mode=mode, expected_rows=expected)
                count = received = 0
                if mode == "full":
                    for records in record_batches(db):
                        if time.monotonic() > importer.deadline:
                            raise RuntimeError("Prazo seguro da carga oficial excedido")
                        result = client.call("batch", run_id=run_id, sequence=count, sha256=digest(records), rows=records)
                        if result.get("received") != len(records):
                            raise RuntimeError("Contagem do lote não confirmada pelo Radar")
                        count += 1
                        received += len(records)
                if received != expected:
                    raise RuntimeError("Contagem final diverge da carga temporária")
                result = client.call("finalize", run_id=run_id, expected_batches=count,
                                     catalog=cnaes, catalog_sha256=digest(cnaes))
                if result.get("complete") is not True or result.get("competencia") != month:
                    raise RuntimeError("Publicação da competência não confirmada")
                print(f"Carga oficial concluída: {received} estabelecimentos; {len(cnaes)} CNAEs.", flush=True)
    except BaseException:
        if started:
            try:
                client.call("fail", run_id=run_id)
            except Exception:
                pass  # The six-hour server lease also releases an abandoned job.
        raise


def self_test():
    import csv
    import io
    import unittest

    class PipelineTests(unittest.TestCase):
        def test_destination_and_canonical_hash(self):
            self.assertEqual(target_url("https://radar-cnpj-rs.example.workers.dev"), "https://radar-cnpj-rs.example.workers.dev/api/internal/receita")
            for invalid in ("http://radar-cnpj-rs.example.workers.dev", "https://starker.example.workers.dev", "https://radar-cnpj-rs.example.workers.dev@evil.test", "https://radar-cnpj-rs.example.workers.dev/other"):
                with self.assertRaises(RuntimeError):
                    target_url(invalid)
            self.assertEqual(digest([{"b": "São Paulo", "a": 1}]), hashlib.sha256('[{"a":1,"b":"São Paulo"}]'.encode()).hexdigest())

        def test_temp_database_and_batch_bounds(self):
            with tempfile.TemporaryDirectory(prefix="radar-receita-test-") as folder:
                path = Path(folder) / "temporary.sqlite"
                initialize_temporary_db(path)
                with closing(sqlite3.connect(path)) as db, db:
                    db.row_factory = sqlite3.Row
                    rows = []
                    for index in range(501):
                        row = {key: "" for key in FIELDS}
                        row.update(cnpj=f"{index:014}", razao_social="Estabelecimento sintético", situacao="ATIVA", cnae="6201501", uf="RS", mei=0)
                        rows.append(tuple(row[key] for key in FIELDS))
                    db.executemany("INSERT INTO companies(" + ",".join(FIELDS) + ") VALUES(" + ",".join("?" for _ in FIELDS) + ")", rows)
                    batches = list(record_batches(db))
                    self.assertEqual([len(batch) for batch in batches], [500, 1])
                    self.assertTrue(all(len(encoded(batch)) < MAX_BODY - 2048 for batch in batches))

        def test_current_month_never_downloads(self):
            class Client:
                def call(self, action, **payload):
                    if action != "status":
                        raise AssertionError("Unexpected mutation")
                    return {"competencia": "2026-10", "cnae_catalog_competencia": "2026-10"}
            files = [{"name": name, "size": 1} for name in ["Municipios.zip", "Cnaes.zip", "Simples.zip"] + [f"{prefix}{i}.zip" for prefix in ("Estabelecimentos", "Empresas") for i in range(10)]]
            with patch.object(syncer, "discover_catalog", return_value={"competencia": "2026-10", "files": files}), patch.object(syncer.CNPJSync, "_run", side_effect=AssertionError("Download forbidden")):
                execute_pipeline(Client(), "123-1")

        def test_complete_pipeline_with_synthetic_zips_only(self):
            calls = []

            class Client:
                def call(client, action, **payload):
                    calls.append((action, payload))
                    if action == "status":
                        return {"competencia": "2026-09", "cnae_catalog_competencia": "2026-09"}
                    if action == "batch":
                        self.assertEqual(payload["sequence"], 0)
                        self.assertEqual(payload["sha256"], digest(payload["rows"]))
                        self.assertEqual(len(payload["rows"]), 1)
                        self.assertEqual(payload["rows"][0]["mei"], 1)
                        self.assertEqual(payload["rows"][0]["cnpj"], "12345678000190")
                        return {"received": 1}
                    if action == "finalize":
                        self.assertEqual(payload["expected_batches"], 1)
                        self.assertEqual(len(payload["catalog"]), 1001)
                        self.assertEqual(payload["catalog_sha256"], digest(payload["catalog"]))
                        return {"complete": True, "competencia": "2026-10"}
                    return {}

            with tempfile.TemporaryDirectory(prefix="radar-receita-source-test-") as folder:
                root = Path(folder)
                establishment = [""] * 30
                establishment[0:3] = ["12345678", "0001", "90"]
                establishment[4:6] = ["Loja sintética", "02"]
                establishment[10:13] = [syncer.date.today().strftime("%Y%m%d"), "6201501", ""]
                establishment[17:21] = ["CENTRO", "90000000", "RS", "8801"]
                files = {"Municipios.zip": [["8801", "PORTO ALEGRE"]],
                         "Cnaes.zip": [[f"{i:07}", "Atividade sintética"] for i in range(1000)] + [["6201501", "Descrição sintética"]],
                         "Simples.zip": [["12345678", "S", "", "", "S"]]}
                for prefix in ("Estabelecimentos", "Empresas"):
                    for index in range(10):
                        files[f"{prefix}{index}.zip"] = []
                files["Estabelecimentos0.zip"] = [establishment]
                files["Empresas0.zip"] = [["12345678", "LOJA SINTÉTICA LTDA", "2062", "49", "10000,00", "01"]]
                manifest = []
                paths = {}
                for name, rows in files.items():
                    stream = io.StringIO(newline="")
                    csv.writer(stream, delimiter=";").writerows(rows)
                    path = root / name
                    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr("dados.csv", stream.getvalue().encode("latin-1"))
                    paths[name] = path
                    manifest.append({"name": name, "size": path.stat().st_size})
                with patch.object(syncer, "discover_catalog", return_value={"competencia": "2026-10", "files": manifest}), patch.object(RunnerSync, "_download", lambda worker, month, info, index, count: paths[info["name"]]):
                    execute_pipeline(Client(), "123-1")
                self.assertTrue(all(not path.exists() for path in paths.values()))
                starts = [payload for action, payload in calls if action == "start"]
                self.assertNotIn("expected_rows", starts[0])
                self.assertEqual(starts[1]["expected_rows"], 1)
                self.assertEqual(calls[-1][0], "finalize")

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(PipelineTests))
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Only mocked tests; no network or user database")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    try:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("A carga real deve executar somente no runner temporário do GitHub Actions")
        run_id = os.environ.get("GITHUB_RUN_ID", "") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "")
        if not re.fullmatch(r"[0-9]{1,20}-[1-9][0-9]{0,3}", run_id):
            raise RuntimeError("Identificador de execução GitHub inválido")
        client = RadarClient(os.environ.get("RADAR_WORKERS_URL", ""), os.environ.get("RADAR_RECEITA_IMPORT_SECRET", ""))
        execute_pipeline(client, run_id)
        return 0
    except Exception:
        # Do not expose HTTP bodies, contact rows, database paths, secrets or tracebacks
        # in a public repository's logs. Server-side status retains a safe failure state.
        print("Atualização oficial não concluída. Consulte o estado da sincronização no Radar; a competência anterior foi preservada.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
