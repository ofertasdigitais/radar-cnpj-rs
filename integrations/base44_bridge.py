"""Contrato de saída do Radar para uma função de integração hospedada no Base44.

Este módulo não é carregado pelo servidor Radar. A execução padrão apenas prepara
uma prévia local; a opção --send precisa ser solicitada explicitamente.
"""

import argparse
from contextlib import closing
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener
import admin_panel


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ.get('RADAR_DATA_DIR', str(ROOT / 'data'))) / 'radar.db'


def load_lead(db_path, account_id, profile_id, cnpj):
    """Lê somente um lead pertencente à conta e ao perfil informados."""
    if not account_id or not profile_id or len(cnpj) != 14 or not cnpj.isdigit():
        raise ValueError("Informe conta, perfil e CNPJ com 14 dígitos")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("""
            SELECT p.owner_id, p.id AS profile_id, p.name AS seller_name,
                   a.username AS seller_username, c.cnpj, c.razao_social,
                   c.nome_fantasia, c.telefone, c.email, c.municipio, c.uf,
                   c.segmento, c.cnae, c.cnae_descricao, c.situacao,
                   c.data_abertura, l.lead_status, l.contact_outcome,
                   l.next_action, l.next_action_at, l.last_contact_at,
                   l.first_contact_at, l.closed_at, l.offered_value_cents,
                   l.negotiated_value_cents, l.closed_value_cents,
                   l.whatsapp_phone, l.whatsapp_status, l.whatsapp_checked_at,
                   l.observacoes, l.estrategia, l.favorito, l.updated_at
            FROM sales_profile_leads l
            JOIN sales_profiles p ON p.id=l.profile_id
            JOIN user_accounts a ON a.id=p.owner_id
            JOIN companies c ON c.cnpj=l.cnpj
            WHERE p.owner_id=? AND p.id=? AND l.cnpj=? AND a.is_active=1
              AND NOT EXISTS (SELECT 1 FROM contact_suppression s
                              WHERE s.owner_id=p.owner_id AND s.cnpj=l.cnpj)
        """, (account_id, profile_id, cnpj)).fetchone()
    if row is None:
        raise LookupError("Lead indisponível: conta/perfil incorreto, conta inativa ou contato bloqueado")
    return dict(row)


def build_event(row):
    owner = str(row["owner_id"])
    profile = str(row["profile_id"])
    cnpj = str(row["cnpj"])
    external_id = f"radar:{owner}:{profile}:{cnpj}"
    return {
        "contract_version": 1,
        "event_type": "lead.upsert",
        "external_id": external_id,
        "source_updated_at": row["updated_at"],
        "owner": {"radar_account_id": owner, "radar_profile_id": profile,
                  "name": row["seller_name"], "username": row["seller_username"]},
        "company": {key: row[key] for key in (
            "cnpj", "razao_social", "nome_fantasia", "municipio", "uf",
            "segmento", "cnae", "cnae_descricao", "situacao", "data_abertura")},
        "contact": {key: row[key] for key in (
            "telefone", "email", "whatsapp_phone", "whatsapp_status", "whatsapp_checked_at")},
        "commercial": {key: row[key] for key in (
            "lead_status", "contact_outcome", "next_action", "next_action_at",
            "last_contact_at", "first_contact_at", "closed_at", "offered_value_cents",
            "negotiated_value_cents", "closed_value_cents", "observacoes", "estrategia", "favorito")},
    }


def encode_event(event):
    return json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def signed_headers(body, secret, timestamp):
    digest = hmac.new(secret.encode("utf-8"), str(timestamp).encode("ascii") + b"." + body,
                      hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json; charset=utf-8",
            "X-Radar-Timestamp": str(timestamp), "X-Radar-Signature": "sha256=" + digest}


def send_event(event, endpoint, secret):
    endpoint = admin_panel.validate('base44_endpoint', endpoint)
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Configure uma URL HTTPS válida para o destino Base44")
    if not secret or len(secret) < 32:
        raise ValueError("Configure RADAR_BASE44_SECRET com pelo menos 32 caracteres")
    body = encode_event(event)
    request = Request(endpoint, data=body, headers=signed_headers(body, secret, int(time.time())), method="POST")
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError('Redirecionamento do CRM recusado; configure o endpoint final')
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        payload = response.read(65_537)
        if len(payload)>65_536: raise ValueError('Resposta do CRM acima do limite')
        return response.status, payload.decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Prévia local do contrato Radar → Base44")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--cnpj", required=True)
    parser.add_argument("--send", action="store_true", help="Envia o lead real para o endpoint configurado")
    args = parser.parse_args()
    event = build_event(load_lead(args.db, args.account_id, args.profile_id, args.cnpj))
    if not args.send:
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return
    status, response = send_event(event, admin_panel.get('base44_endpoint',args.db),
                                  admin_panel.get('base44_secret',args.db))
    print(json.dumps({"http_status": status, "response": response}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, LookupError, sqlite3.Error, OSError) as error:
        print(f"Integração Base44: {error}", file=sys.stderr)
        sys.exit(1)
