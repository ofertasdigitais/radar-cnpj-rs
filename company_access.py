"""Private test contacts stay private; official Receita records remain shared."""

PRIVATE_MARKER = "(COALESCE({a}.uf,'')='ZZ' OR COALESCE({a}.situacao,'')='TESTE')"


def visible(company_alias, owner_expression):
    marker = f"({PRIVATE_MARKER.format(a=company_alias)} OR EXISTS (SELECT 1 FROM private_companies identity WHERE identity.cnpj={company_alias}.cnpj))"
    return f"(NOT {marker} OR EXISTS (SELECT 1 FROM private_companies priv WHERE priv.cnpj={company_alias}.cnpj AND priv.owner_id={owner_expression}))"


def profile_visible(cnpj_expression, profile_expression):
    return f"EXISTS (SELECT 1 FROM companies pc JOIN sales_profiles pp ON pp.id={profile_expression} WHERE pc.cnpj={cnpj_expression} AND {visible('pc', 'pp.owner_id')})"


def available(db, cnpj, owner):
    return bool(db.execute(f"SELECT 1 FROM companies c WHERE c.cnpj=? AND {visible('c', '?')}", (cnpj, owner)).fetchone())


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS private_companies (
        cnpj TEXT PRIMARY KEY REFERENCES companies(cnpj) ON DELETE CASCADE,
        owner_id TEXT)''')
    # Only a single existing owner is evidence of ownership. Ambiguous or
    # ownerless legacy records stay preserved but unavailable to sellers.
    db.execute(f'''INSERT OR IGNORE INTO private_companies(cnpj,owner_id)
        SELECT c.cnpj,CASE WHEN COUNT(DISTINCT p.owner_id)=1 THEN MIN(p.owner_id) END
        FROM companies c LEFT JOIN sales_profile_leads s ON s.cnpj=c.cnpj
        LEFT JOIN sales_profiles p ON p.id=s.profile_id
        WHERE {PRIVATE_MARKER.format(a='c')} GROUP BY c.cnpj''')
    db.execute(f'''CREATE VIEW IF NOT EXISTS accessible_sales_profile_leads AS
        SELECT s.* FROM sales_profile_leads s JOIN companies c ON c.cnpj=s.cnpj
        JOIN sales_profiles p ON p.id=s.profile_id WHERE {visible('c', 'p.owner_id')}''')
