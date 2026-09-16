import csv
import io
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from syncer import CNPJSync


def make_zip(path, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", quotechar='"')
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dados.csv", stream.getvalue().encode("latin-1"))


class SyntheticSyncTests(unittest.TestCase):
    def test_official_tables_are_joined_and_filtered_for_rs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); db_path = root / "test.db"
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("""CREATE TABLE companies(id INTEGER PRIMARY KEY,cnpj TEXT UNIQUE,razao_social TEXT,nome_fantasia TEXT,situacao TEXT,data_abertura TEXT,cnae TEXT,cnaes_secundarios TEXT,segmento TEXT,municipio TEXT,regiao TEXT,uf TEXT,cep TEXT,bairro TEXT,logradouro TEXT,numero TEXT,telefone TEXT,email TEXT,porte TEXT,mei INTEGER,lead_status TEXT DEFAULT 'novo',favorito INTEGER DEFAULT 0,observacoes TEXT DEFAULT '')""")
                db.commit()
            establishment = [""] * 30
            establishment[0:3] = ["12345678", "0001", "90"]
            establishment[4:6] = ["Empresa Teste", "02"]
            establishment[10:13] = [date.today().strftime("%Y%m%d"), "6201501", ""]
            establishment[13:21] = ["RUA", "DOS TESTES", "10", "", "CENTRO", "90000000", "RS", "8801"]
            establishment[21:23] = ["51", "33334444"]
            establishment[27] = "vendas@teste.com"
            files = {
                "Municipios.zip": [["8801", "PORTO ALEGRE"]],
                "Estabelecimentos0.zip": [establishment],
                "Empresas0.zip": [["12345678", "EMPRESA TESTE LTDA", "2062", "49", "10000,00", "01", ""]],
                "Simples.zip": [["12345678", "S", "", "", "S", "", ""]],
            }
            paths = {}
            for name, rows in files.items():
                paths[name] = root / name; make_zip(paths[name], rows)
            catalog = {"competencia":"2026-08", "files":[{"name":name,"size":path.stat().st_size} for name,path in paths.items()]}
            sync = CNPJSync(db_path, root / "cache")
            sync._download = lambda month, info, index, count: paths[info["name"]]
            with patch("syncer.discover_catalog", return_value=catalog): sync._run(120)
            with closing(sqlite3.connect(db_path)) as db:
                row = db.execute("SELECT razao_social,municipio,regiao,mei,cnae FROM companies").fetchone()
            self.assertEqual(row, ("EMPRESA TESTE LTDA", "Porto Alegre", "Metropolitana", 1, "6201501"))
            self.assertEqual(sync.snapshot()["status"], "complete")


if __name__ == "__main__": unittest.main()
