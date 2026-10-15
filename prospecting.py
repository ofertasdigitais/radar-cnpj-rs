"""Private contacts from seller-controlled sources, never mixed into Receita data."""
import hashlib
import re
import uuid
import company_access
from datetime import datetime
from urllib.parse import urlparse

FIELDS = {'name': 180, 'company': 180, 'phone': 32, 'email': 180, 'city': 100,
          'source': 120, 'campaign': 120, 'persona': 120, 'website': 300, 'notes': 4000, 'cnpj': 14}
STATUSES = ('novo', 'contatado', 'qualificado', 'descartado')


def ensure_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS prospect_inbox (
      id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
      name TEXT NOT NULL,company TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',
      email TEXT NOT NULL DEFAULT '',city TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,
      campaign TEXT NOT NULL DEFAULT '',persona TEXT NOT NULL DEFAULT '',website TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',cnpj TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'novo',
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(owner_id,fingerprint));
      CREATE INDEX IF NOT EXISTS idx_prospect_owner_updated ON prospect_inbox(owner_id,updated_at DESC);
      CREATE TABLE IF NOT EXISTS prospect_links (
      prospect_id TEXT NOT NULL REFERENCES prospect_inbox(id) ON DELETE CASCADE,
      profile_id TEXT NOT NULL,cnpj TEXT NOT NULL,owner_id TEXT NOT NULL,created_at TEXT NOT NULL,
      PRIMARY KEY(prospect_id,profile_id,cnpj),
      FOREIGN KEY(profile_id,cnpj) REFERENCES sales_profile_leads(profile_id,cnpj) ON DELETE CASCADE);
      CREATE TABLE IF NOT EXISTS prospect_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,prospect_id TEXT NOT NULL REFERENCES prospect_inbox(id),
      owner_id TEXT NOT NULL,event TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL);
    ''')
    if 'revision' not in {r[1] for r in db.execute('PRAGMA table_info(prospect_inbox)')}:
        db.execute('ALTER TABLE prospect_inbox ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')


def summary(db,owner):
    statuses={r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM prospect_inbox WHERE owner_id=? GROUP BY status',(owner,))}
    linked=db.execute('SELECT COUNT(DISTINCT prospect_id) FROM prospect_links WHERE owner_id=?',(owner,)).fetchone()[0]
    return {'total':sum(statuses.values()),'statuses':statuses,'linked':linked,'not_linked':sum(statuses.values())-linked,
            'basis':'Contatos externos da conta, todos os períodos. Somente vínculos entram no funil oficial.'}


def qualify(db,owner,payload):
    if not isinstance(payload,dict) or set(payload)-{'prospect_id','profile_id','cnpj','allow_duplicate'}:raise ValueError('Encaminhamento inválido')
    identifier=payload.get('prospect_id');profile=payload.get('profile_id');cnpj=payload.get('cnpj','')
    if not all(isinstance(x,str) for x in (identifier,profile,cnpj)) or not re.fullmatch('[A-Z0-9]{14}',cnpj):raise ValueError('Informe o contato, responsável e CNPJ sem pontuação')
    db.execute('BEGIN IMMEDIATE')
    contact=db.execute('SELECT * FROM prospect_inbox WHERE id=? AND owner_id=?',(identifier,owner)).fetchone()
    if not contact or not db.execute('SELECT 1 FROM sales_profiles WHERE id=? AND owner_id=?',(profile,owner)).fetchone():raise LookupError('Contato ou responsável não encontrado nesta conta')
    if not company_access.available(db,cnpj,owner):raise LookupError('CNPJ não encontrado na base disponível. O contato externo foi preservado.')
    already=db.execute('SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=?',(profile,cnpj)).fetchone()
    other=db.execute("SELECT 1 FROM sales_profile_leads WHERE cnpj=? AND profile_id<>? AND lead_status NOT IN ('convertido','descartado')",(cnpj,profile)).fetchone()
    if other and not already and payload.get('allow_duplicate') is not True:raise FileExistsError('Empresa em outro atendimento ativo. Confirme a duplicação da abordagem.')
    stamp=datetime.now().isoformat(timespec='seconds');created=not bool(already)
    if created:
        notes='Contato externo: '+contact['name']+'\nTelefone declarado: '+contact['phone']+'\nE-mail declarado: '+contact['email']+'\n'+contact['notes']
        db.execute('''INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,lead_status,observacoes,campaign,persona,lead_origin)
         VALUES(?,?,?,?,'qualificado',?,?,?,?)''',(profile,cnpj,stamp,stamp,notes[:5000],contact['campaign'],contact['persona'],contact['source']))
    link=db.execute('INSERT OR IGNORE INTO prospect_links VALUES(?,?,?,?,?)',(identifier,profile,cnpj,owner,stamp))
    if link.rowcount:
        db.execute("INSERT INTO prospect_history(prospect_id,owner_id,event,details,created_at) VALUES(?,?,'linked',?,?)",(identifier,owner,'Encaminhado ao painel: '+cnpj,stamp))
        db.execute('''INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at)
          VALUES(?,?,'external_linked','Contato externo vinculado',?,?)''',(profile,cnpj,'Origem: '+contact['source']+'; campanha: '+contact['campaign'],stamp))
        updated=dict(contact);updated['cnpj']=cnpj
        db.execute("UPDATE prospect_inbox SET status='qualificado',cnpj=?,fingerprint=?,updated_at=?,revision=revision+1 WHERE id=? AND owner_id=?",(cnpj,fingerprint(updated),stamp,identifier,owner))
        db.execute('UPDATE sales_profiles SET updated_at=? WHERE id=?',(stamp,profile))
    return {'created':created,'linked':bool(link.rowcount),'profile_id':profile,'cnpj':cnpj,
            'message':'Contato encaminhado; atendimento anterior preservado.' if not created else 'Lead qualificado incluído no painel.'}


def validate(raw):
    if not isinstance(raw, dict): raise ValueError('Contato inválido')
    row = {}
    for key, limit in FIELDS.items():
        value = raw.get(key, '')
        if not isinstance(value, str): raise ValueError(f'Campo {key} precisa ser texto')
        value = value.strip()
        if len(value) > limit: raise ValueError(f'Campo {key} excede {limit} caracteres')
        if any(ord(char) < 32 and char not in '\n\r\t' for char in value): raise ValueError(f'Campo {key} contém caracteres inválidos')
        row[key] = value
    if not row['name']: row['name'] = row['company']
    if not row['name']: raise ValueError('Informe nome ou empresa')
    if row['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', row['email']): raise ValueError('E-mail inválido')
    if row['cnpj'] and not re.fullmatch(r'[A-Z0-9]{14}', row['cnpj']): raise ValueError('CNPJ precisa ter 14 caracteres, sem pontuação')
    if row['website']:
        parsed = urlparse(row['website'])
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Site precisa ser uma URL http/https, sem credenciais')
    row['source'] = row['source'] or 'Importação CSV'
    row['status'] = raw.get('status', 'novo')
    if row['status'] not in STATUSES: raise ValueError('Situação inválida')
    return row


def fingerprint(row):
    # Same business/contact can return from another source; no silent overwrites.
    key = '|'.join([row['name'].casefold(), row['company'].casefold(),
                    re.sub(r'\D', '', row['phone']), row['email'].casefold(), row['cnpj']])
    return hashlib.sha256(key.encode()).hexdigest()


def import_rows(db, owner_id, raw_rows):
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= 500:
        raise ValueError('Importe de 1 a 500 contatos por arquivo')
    rows = []
    for number, raw in enumerate(raw_rows, 1):
        try: rows.append(validate(raw))
        except ValueError as error: raise ValueError(f'Linha {number}: {error}') from error
    now = datetime.now().isoformat(timespec='seconds'); created = 0
    db.execute('BEGIN IMMEDIATE')
    for row in rows:
        fields = list(row)
        cursor = db.execute(f'''INSERT INTO prospect_inbox(id,owner_id,fingerprint,{','.join(fields)},created_at,updated_at)
            VALUES({','.join('?' for _ in range(len(fields)+5))}) ON CONFLICT(owner_id,fingerprint) DO NOTHING''',
            [uuid.uuid4().hex, owner_id, fingerprint(row)] + [row[k] for k in fields] + [now, now])
        created += cursor.rowcount
    return {'created': created, 'duplicates': len(rows)-created, 'total_received': len(rows)}
