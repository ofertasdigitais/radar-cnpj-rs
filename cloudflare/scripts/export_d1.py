#!/usr/bin/env python3
"""Exporta o SQLite local para lotes SQL compatíveis com Cloudflare D1.

Os arquivos gerados contêm dados privados e devem permanecer sob data/, que é
ignorada pelo Git. O modo gratuito usa uma quantidade limitada de empresas
para respeitar a franquia diária de linhas gravadas do D1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "radar.db"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "cloudflare-import"
DEFAULT_FREE_COMPANY_LIMIT = 9_000
ROWS_PER_FILE = 1_000
MODERN_TABLES = ('sales_lead_history', 'contact_suppression', 'commercial_archive',
                 'discovery_campaigns', 'help_articles', 'admin_config')

COMPANY_COLUMNS = (
    "id", "cnpj", "razao_social", "nome_fantasia", "situacao",
    "data_abertura", "cnae", "cnaes_secundarios", "segmento", "municipio",
    "regiao", "uf", "cep", "bairro", "logradouro", "numero", "telefone",
    "email", "porte", "mei", "cnae_descricao", "serpro_checked_at", "data_source",
)

# Perfis legados sem owner_id só podem ser migrados por mapeamento explícito.
LEGACY_SALES_PROFILE_ACCOUNT = {
    "suporte automahost": "suporte",
    "marcos": "marcos",
}


def sql_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def insert_statement(table: str, columns: Sequence[str], row: Sequence[Any]) -> str:
    names = ",".join(columns)
    values = ",".join(sql_value(value) for value in row)
    return f"INSERT OR REPLACE INTO {table}({names}) VALUES({values});"


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
    ).fetchone() is not None


def fetch_rows(connection: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in connection.execute(sql, params).fetchall()]


def write_sql_files(output: Path, prefix: str, statements: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    chunk: list[str] = []
    index = 0
    for statement in statements:
        chunk.append(statement)
        if len(chunk) >= ROWS_PER_FILE:
            path = output / f"{prefix}-{index:03d}.sql"
            path.write_text("\n".join(chunk) + "\n", encoding="utf-8")
            paths.append(path)
            chunk = []
            index += 1
    if chunk:
        path = output / f"{prefix}-{index:03d}.sql"
        path.write_text("\n".join(chunk) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def resolve_profile_owners(
    accounts: list[tuple[Any, ...]],
    profiles: list[tuple[Any, ...]],
) -> dict[str, str]:
    account_ids = {str(row[0]) for row in accounts}
    by_username = {str(row[2]).strip().casefold(): str(row[0]) for row in accounts}
    resolved: dict[str, str] = {}
    for row in profiles:
        profile_id, name, owner_id = str(row[0]), str(row[1]), row[-1]
        if owner_id:
            if str(owner_id) not in account_ids:
                raise RuntimeError(f"Perfil {profile_id} aponta para conta inexistente {owner_id}")
            resolved[profile_id] = str(owner_id)
            continue
        username = LEGACY_SALES_PROFILE_ACCOUNT.get(name.strip().casefold())
        if not username or username.casefold() not in by_username:
            raise RuntimeError(
                f"Perfil legado {profile_id!r} ({name!r}) sem conta inequívoca; "
                "adicione um mapeamento explícito em LEGACY_SALES_PROFILE_ACCOUNT."
            )
        resolved[profile_id] = by_username[username.casefold()]
    return resolved


def select_companies(
    connection: sqlite3.Connection,
    limit: int,
    required_cnpjs: set[str],
) -> list[tuple[Any, ...]]:
    columns = ",".join(COMPANY_COLUMNS)
    if limit > 0:
        rows = fetch_rows(
            connection,
            f"SELECT {columns} FROM companies ORDER BY data_abertura DESC,id DESC LIMIT ?",
            (limit,),
        )
    else:
        rows = fetch_rows(connection, f"SELECT {columns} FROM companies ORDER BY id")
    selected = {str(row[1]) for row in rows}
    missing = sorted(required_cnpjs - selected)
    for start in range(0, len(missing), 90):
        part = missing[start:start + 90]
        placeholders = ",".join("?" for _ in part)
        rows.extend(fetch_rows(
            connection,
            f"SELECT {columns} FROM companies WHERE cnpj IN ({placeholders}) ORDER BY id",
            part,
        ))
    found = {str(row[1]) for row in rows}
    absent = sorted(required_cnpjs - found)
    if absent:
        raise RuntimeError(f"CNPJs referenciados não existem em companies: {absent[:5]}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--company-limit",
        type=int,
        default=DEFAULT_FREE_COMPANY_LIMIT,
        help="Quantidade das empresas mais recentes; use 0 para exportar tudo.",
    )
    parser.add_argument("--output", type=Path, help="Diretório novo para os lotes gerados.")
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise SystemExit(f"Banco não encontrado: {database}")
    if args.company_limit < 0:
        raise SystemExit("--company-limit deve ser zero ou positivo")
    # This historical exporter drops modern fields, history and permissions.
    # Refuse before creating any files; a complete, tested migration is required.
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        unsupported = [name for name in MODERN_TABLES if table_exists(source, name)]
        if unsupported:
            raise SystemExit('Exportação legada bloqueada: esta base usa recursos modernos ('
                             + ', '.join(unsupported) + '). Execute tools/release_readiness.py '
                             '--cloudflare e prepare uma migração completa; nenhum lote foi gerado.')

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or (DEFAULT_OUTPUT_ROOT / f"seed-{stamp}")).resolve()
    if output.exists():
        raise SystemExit(f"O diretório de saída já existe: {output}")
    output.mkdir(parents=True)

    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError(f"PRAGMA quick_check falhou: {check}")

        accounts = fetch_rows(connection, "SELECT id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at,last_login_at FROM user_accounts ORDER BY id")
        if not accounts:
            raise RuntimeError("Nenhuma conta encontrada; a publicação sem contas seria inutilizável")

        sales_columns = table_columns(connection, "sales_profiles")
        owner_expression = "owner_id" if "owner_id" in sales_columns else "NULL AS owner_id"
        sales_profiles = fetch_rows(
            connection,
            f"SELECT id,name,role,email,initials,color,created_at,updated_at,{owner_expression} FROM sales_profiles ORDER BY id",
        )
        sales_owners = resolve_profile_owners(accounts, sales_profiles)

        required_cnpjs: set[str] = set()
        if table_exists(connection, "sales_profile_leads"):
            required_cnpjs.update(str(row[0]) for row in connection.execute("SELECT DISTINCT cnpj FROM sales_profile_leads"))
        if table_exists(connection, "profile_leads"):
            required_cnpjs.update(str(row[0]) for row in connection.execute("SELECT DISTINCT cnpj FROM profile_leads"))
        if table_exists(connection, "account_company_state"):
            required_cnpjs.update(str(row[0]) for row in connection.execute("SELECT DISTINCT cnpj FROM account_company_state"))

        companies = select_companies(connection, args.company_limit, required_cnpjs)
        exported_cnpjs = {str(row[1]) for row in companies}

        files: list[Path] = []
        files += write_sql_files(output, "010-accounts", (
            insert_statement("user_accounts", (
                "id", "name", "username", "email", "password_hash", "password_salt",
                "role", "is_active", "created_at", "updated_at", "last_login_at",
            ), row) for row in accounts
        ))
        files += write_sql_files(output, "020-companies", (
            insert_statement("companies", COMPANY_COLUMNS, row) for row in companies
        ))

        prospecting_columns = table_columns(connection, "prospecting_profiles")
        prospecting_owner = "owner_id" if "owner_id" in prospecting_columns else "NULL AS owner_id"
        prospecting = fetch_rows(
            connection,
            f"SELECT id,{prospecting_owner},name,description,filters_json,is_system,created_at,updated_at FROM prospecting_profiles ORDER BY id",
        )
        account_ids = {str(row[0]) for row in accounts}
        for row in prospecting:
            if not row[5] and (not row[1] or str(row[1]) not in account_ids):
                raise RuntimeError(f"Segmentação personalizada {row[0]!r} não possui owner_id válido")
        files += write_sql_files(output, "030-prospecting-profiles", (
            insert_statement("prospecting_profiles", (
                "id", "owner_id", "name", "description", "filters_json", "is_system", "created_at", "updated_at",
            ), row) for row in prospecting
        ))

        if table_exists(connection, "profile_leads"):
            profile_owner = {str(row[0]): str(row[1]) for row in prospecting if row[1]}
            profile_leads = fetch_rows(connection, "SELECT profile_id,cnpj,added_at FROM profile_leads ORDER BY profile_id,cnpj")
            converted_profile_leads = []
            for profile_id, cnpj, added_at in profile_leads:
                owner_id = profile_owner.get(str(profile_id))
                if not owner_id:
                    raise RuntimeError(f"Lead associado à segmentação sem dono: {profile_id}")
                if str(cnpj) not in exported_cnpjs:
                    raise RuntimeError(f"CNPJ {cnpj} de profile_leads não foi exportado")
                converted_profile_leads.append((owner_id, profile_id, cnpj, added_at))
            files += write_sql_files(output, "040-profile-leads", (
                insert_statement("profile_leads", ("owner_id", "profile_id", "cnpj", "added_at"), row)
                for row in converted_profile_leads
            ))

        converted_sales = [
            (row[0], sales_owners[str(row[0])], *row[1:8]) for row in sales_profiles
        ]
        files += write_sql_files(output, "050-sales-profiles", (
            insert_statement("sales_profiles", (
                "id", "owner_id", "name", "role", "email", "initials", "color", "created_at", "updated_at",
            ), row) for row in converted_sales
        ))

        sales_leads = fetch_rows(
            connection,
            "SELECT profile_id,cnpj,added_at,updated_at,favorito,lead_status,observacoes,estrategia FROM sales_profile_leads ORDER BY profile_id,cnpj",
        )
        converted_sales_leads = []
        for row in sales_leads:
            profile_id, cnpj = str(row[0]), str(row[1])
            if profile_id not in sales_owners:
                raise RuntimeError(f"Lead associado ao perfil comercial inexistente: {profile_id}")
            if cnpj not in exported_cnpjs:
                raise RuntimeError(f"CNPJ {cnpj} de sales_profile_leads não foi exportado")
            converted_sales_leads.append((sales_owners[profile_id], *row))
        files += write_sql_files(output, "060-sales-leads", (
            insert_statement("sales_profile_leads", (
                "owner_id", "profile_id", "cnpj", "added_at", "updated_at", "favorito",
                "lead_status", "observacoes", "estrategia",
            ), row) for row in converted_sales_leads
        ))

        state_rows: list[tuple[Any, ...]] = []
        if table_exists(connection, "account_company_state"):
            state_columns = table_columns(connection, "account_company_state")
            account_column = "owner_id" if "owner_id" in state_columns else "account_id"
            state_rows = fetch_rows(
                connection,
                f"SELECT {account_column},cnpj,lead_status,favorito,observacoes,updated_at FROM account_company_state ORDER BY {account_column},cnpj",
            )
            for owner_id, cnpj, *_ in state_rows:
                if str(owner_id) not in account_ids or str(cnpj) not in exported_cnpjs:
                    raise RuntimeError(f"Estado comercial órfão: conta={owner_id}, CNPJ={cnpj}")
            files += write_sql_files(output, "070-account-state", (
                insert_statement("account_company_state", (
                    "owner_id", "cnpj", "lead_status", "favorito", "observacoes", "updated_at",
                ), row) for row in state_rows
            ))

        catalog = fetch_rows(connection, "SELECT codigo,descricao FROM cnae_catalog ORDER BY codigo")
        company_counts = {
            str(row[0]): (str(row[1] or ""), int(row[2]))
            for row in connection.execute(
                "SELECT cnae,MAX(segmento),COUNT(*) FROM companies WHERE cnae<>'' GROUP BY cnae",
            )
        }
        converted_catalog = [
            (codigo, descricao, company_counts.get(str(codigo), ("", 0))[0], company_counts.get(str(codigo), ("", 0))[1])
            for codigo, descricao in catalog
        ]
        files += write_sql_files(output, "080-cnae-catalog", (
            insert_statement("cnae_catalog", ("codigo", "descricao", "segmento", "empresas"), row)
            for row in converted_catalog
        ))

        option_rows: list[tuple[str, str]] = []
        for kind, column in (("segmento", "segmento"), ("municipio", "municipio"), ("regiao", "regiao")):
            option_rows.extend(
                (kind, str(row[0]))
                for row in connection.execute(
                    f"SELECT DISTINCT {column} FROM companies WHERE {column} IS NOT NULL AND TRIM({column})<>'' ORDER BY {column}",
                )
            )
        files += write_sql_files(output, "090-filter-options", (
            insert_statement("filter_options", ("kind", "value"), row) for row in option_rows
        ))

        sync_meta = fetch_rows(connection, "SELECT key,value FROM sync_meta ORDER BY key")
        sync_meta.append(("cloudflare_seed_scope", "full" if args.company_limit == 0 else f"latest-{len(companies)}"))
        sync_meta.append(("cloudflare_seed_exported_at", datetime.now(timezone.utc).isoformat()))
        files += write_sql_files(output, "100-sync-meta", (
            insert_statement("sync_meta", ("key", "value"), row) for row in sync_meta
        ))

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "company_limit_requested": args.company_limit,
            "counts": {
                "companies": len(companies),
                "user_accounts": len(accounts),
                "prospecting_profiles": len(prospecting),
                "profile_leads": len(profile_leads) if table_exists(connection, "profile_leads") else 0,
                "sales_profiles": len(converted_sales),
                "sales_profile_leads": len(converted_sales_leads),
                "account_company_state": len(state_rows),
                "cnae_catalog": len(converted_catalog),
                "filter_options": len(option_rows),
            },
            "files": [
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in files
            ],
            "legacy_sales_profile_owners": sales_owners,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"output": str(output), **manifest["counts"]}, ensure_ascii=False))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
