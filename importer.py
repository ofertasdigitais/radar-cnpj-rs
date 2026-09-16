import csv
import io
import re
import sqlite3
import unicodedata
from datetime import datetime


SEGMENTS = {
    "A": "Agropecuária", "B": "Indústrias extrativas", "C": "Indústria",
    "D": "Energia", "E": "Água e saneamento", "F": "Construção",
    "G": "Comércio", "H": "Transporte e logística", "I": "Alimentação e hospedagem",
    "J": "Tecnologia e comunicação", "K": "Finanças e seguros", "L": "Imobiliário",
    "M": "Serviços profissionais", "N": "Serviços administrativos", "O": "Administração pública",
    "P": "Educação", "Q": "Saúde", "R": "Cultura e lazer", "S": "Outros serviços",
    "T": "Serviços domésticos", "U": "Organismos internacionais",
}

# Divisões CNAE 2.0 para seções (intervalos inclusivos).
SECTION_RANGES = [(1,3,"A"),(5,9,"B"),(10,33,"C"),(35,35,"D"),(36,39,"E"),(41,43,"F"),
                  (45,47,"G"),(49,53,"H"),(55,56,"I"),(58,63,"J"),(64,66,"K"),(68,68,"L"),
                  (69,75,"M"),(77,82,"N"),(84,84,"O"),(85,85,"P"),(86,88,"Q"),(90,93,"R"),
                  (94,96,"S"),(97,97,"T"),(99,99,"U")]

REGIONS = {
    "porto alegre": "Metropolitana", "canoas": "Metropolitana", "gravatai": "Metropolitana",
    "gravataí": "Metropolitana", "viamao": "Metropolitana", "viamão": "Metropolitana",
    "novo hamburgo": "Vale do Sinos", "sao leopoldo": "Vale do Sinos", "são leopoldo": "Vale do Sinos",
    "caxias do sul": "Serra", "bento goncalves": "Serra", "bento gonçalves": "Serra",
    "pelotas": "Sul", "rio grande": "Sul", "santa maria": "Central", "passo fundo": "Norte",
    "erechim": "Norte", "lajeado": "Vale do Taquari", "santa cruz do sul": "Vale do Rio Pardo",
    "uruguaiana": "Fronteira Oeste", "bage": "Campanha", "bagé": "Campanha",
}


def clean_key(value):
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def digits(value): return re.sub(r"\D", "", value or "")
def cnpj_chars(value): return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def parse_date(value):
    value = (value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%d/%m/%Y"):
        try: return datetime.strptime(value, fmt).date().isoformat()
        except ValueError: pass
    return ""


def segment_for(cnae):
    number = digits(cnae)
    if len(number) < 2: return "Não classificado"
    division = int(number[:2])
    for start, end, section in SECTION_RANGES:
        if start <= division <= end: return SEGMENTS[section]
    return "Não classificado"


def region_for(city):
    key = (city or "").strip().lower()
    return REGIONS.get(key, "Demais regiões")


ALIASES = {
    "cnpj": ["cnpj"], "cnpj_basico": ["cnpj_basico"], "cnpj_ordem": ["cnpj_ordem"], "cnpj_dv": ["cnpj_dv"],
    "razao_social": ["razao_social", "nome_empresarial"], "nome_fantasia": ["nome_fantasia", "titulo_estabelecimento"],
    "situacao": ["situacao", "situacao_cadastral"], "data_abertura": ["data_abertura", "data_inicio_atividade", "inicio_atividade"],
    "cnae": ["cnae", "cnae_principal", "cnae_fiscal_principal"], "cnaes_secundarios": ["cnaes_secundarios", "cnae_fiscal_secundaria"],
    "cnae_descricao": ["cnae_descricao", "descricao_cnae", "atividade_economica", "descricao_atividade_economica"],
    "municipio": ["municipio", "cidade", "nome_municipio"], "uf": ["uf"], "cep": ["cep"], "bairro": ["bairro"],
    "logradouro": ["logradouro", "endereco"], "numero": ["numero"], "telefone": ["telefone", "ddd_telefone_1"],
    "email": ["email", "correio_eletronico"], "porte": ["porte", "porte_empresa"], "mei": ["mei", "opcao_mei", "opcao_simei"],
}


def pick(row, field):
    for name in ALIASES[field]:
        if name in row and row[name] is not None: return row[name].strip()
    return ""


def normalize(row):
    row = {clean_key(k): (v or "") for k, v in row.items()}
    cnpj = cnpj_chars(pick(row, "cnpj")) or cnpj_chars(pick(row,"cnpj_basico") + pick(row,"cnpj_ordem") + pick(row,"cnpj_dv"))
    if len(cnpj) != 14: return None
    uf = pick(row, "uf").upper()
    if uf and uf != "RS": return None
    cnae = digits(pick(row, "cnae"))
    city = pick(row, "municipio").title()
    sit = pick(row, "situacao")
    situation = {"2":"ATIVA", "02":"ATIVA", "3":"SUSPENSA", "03":"SUSPENSA", "4":"INAPTA", "04":"INAPTA", "8":"BAIXADA", "08":"BAIXADA", "1":"NULA", "01":"NULA"}.get(sit.upper(), sit.upper() or "ATIVA")
    mei_raw = pick(row, "mei").upper()
    return (cnpj, pick(row,"razao_social") or pick(row,"nome_fantasia") or "Sem razão social", pick(row,"nome_fantasia"),
            situation, parse_date(pick(row,"data_abertura")), cnae, pick(row,"cnae_descricao"), pick(row,"cnaes_secundarios"), segment_for(cnae),
            city, region_for(city), "RS", digits(pick(row,"cep")), pick(row,"bairro"), pick(row,"logradouro"),
            pick(row,"numero"), pick(row,"telefone"), pick(row,"email"), pick(row,"porte"), 1 if mei_raw in ("S","SIM","1","TRUE") else 0)


def import_csv_bytes(conn: sqlite3.Connection, content: bytes):
    try: text = content.decode("utf-8-sig")
    except UnicodeDecodeError: text = content.decode("latin-1")
    sample = text[:8192]
    try: dialect = csv.Sniffer().sniff(sample, delimiters=";,|")
    except csv.Error: dialect = csv.excel; dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames: raise ValueError("CSV sem cabeçalho")
    total = imported = ignored = 0
    has_description = "cnae_descricao" in {row[1] for row in conn.execute("PRAGMA table_info(companies)")}
    sql = """INSERT INTO companies (cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,cnae_descricao,cnaes_secundarios,segmento,municipio,regiao,uf,cep,bairro,logradouro,numero,telefone,email,porte,mei)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cnpj) DO UPDATE SET
             razao_social=excluded.razao_social,nome_fantasia=excluded.nome_fantasia,situacao=excluded.situacao,data_abertura=excluded.data_abertura,cnae=excluded.cnae,cnae_descricao=CASE WHEN excluded.cnae_descricao<>'' THEN excluded.cnae_descricao ELSE companies.cnae_descricao END,cnaes_secundarios=excluded.cnaes_secundarios,segmento=excluded.segmento,municipio=excluded.municipio,regiao=excluded.regiao,uf=excluded.uf,cep=excluded.cep,bairro=excluded.bairro,logradouro=excluded.logradouro,numero=excluded.numero,telefone=excluded.telefone,email=excluded.email,porte=excluded.porte,mei=excluded.mei"""
    if not has_description:
        sql = """INSERT INTO companies (cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,cnaes_secundarios,segmento,municipio,regiao,uf,cep,bairro,logradouro,numero,telefone,email,porte,mei)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cnpj) DO UPDATE SET
                 razao_social=excluded.razao_social,nome_fantasia=excluded.nome_fantasia,situacao=excluded.situacao,data_abertura=excluded.data_abertura,cnae=excluded.cnae,cnaes_secundarios=excluded.cnaes_secundarios,segmento=excluded.segmento,municipio=excluded.municipio,regiao=excluded.regiao,uf=excluded.uf,cep=excluded.cep,bairro=excluded.bairro,logradouro=excluded.logradouro,numero=excluded.numero,telefone=excluded.telefone,email=excluded.email,porte=excluded.porte,mei=excluded.mei"""
    for raw in reader:
        total += 1
        item = normalize(raw)
        if not item: ignored += 1; continue
        conn.execute(sql, item if has_description else item[:6] + item[7:]); imported += 1
    conn.commit()
    return {"lidos": total, "importados": imported, "ignorados": ignored}
