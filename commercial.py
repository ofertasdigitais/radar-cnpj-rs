"""Private commercial analytics. No outbound integrations or CRM transport."""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import admin_panel

LOSS_REASONS = {'': 'Não informado', 'preco': 'Preço', 'sem_interesse': 'Sem interesse',
                'sem_orcamento': 'Sem orçamento', 'concorrente': 'Concorrente',
                'sem_resposta': 'Sem resposta', 'fora_icp': 'Fora do ICP', 'outro': 'Outro'}


def ensure_schema(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(sales_profile_leads)')}
    for key in ('campaign', 'persona', 'lead_origin', 'loss_reason'):
        if key not in columns:
            db.execute(f"ALTER TABLE sales_profile_leads ADD COLUMN {key} TEXT NOT NULL DEFAULT ''")
    history = {row[1] for row in db.execute('PRAGMA table_info(sales_lead_history)')}
    if 'changes_json' not in history:
        db.execute("ALTER TABLE sales_lead_history ADD COLUMN changes_json TEXT NOT NULL DEFAULT '{}'")
    db.executescript('''CREATE TABLE IF NOT EXISTS commercial_settings (
        profile_id TEXT PRIMARY KEY REFERENCES sales_profiles(id) ON DELETE CASCADE,
        contact_sla_hours INTEGER NOT NULL DEFAULT 48,
        stalled_days INTEGER NOT NULL DEFAULT 7);
        CREATE INDEX IF NOT EXISTS idx_history_profile_date ON sales_lead_history(profile_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sales_profile_updated ON sales_profile_leads(profile_id,updated_at DESC);
        CREATE TABLE IF NOT EXISTS commercial_archive (
        id INTEGER PRIMARY KEY AUTOINCREMENT,profile_id TEXT NOT NULL,cnpj TEXT NOT NULL,
        company_name TEXT NOT NULL,removed_at TEXT NOT NULL,events_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_archive_profile ON commercial_archive(profile_id,removed_at DESC);
    ''')


def settings(db, profile_id):
    row = db.execute('SELECT contact_sla_hours,stalled_days FROM commercial_settings WHERE profile_id=?', (profile_id,)).fetchone()
    path=db.execute('PRAGMA database_list').fetchone()[2]
    return dict(row) if row else {key:admin_panel.get(key,path or None) for key in ('contact_sla_hours','stalled_days')}


def rows(db, profile_id):
    return [dict(row) for row in db.execute('''SELECT s.*,c.* FROM sales_profile_leads s
        JOIN companies c ON c.cnpj=s.cnpj WHERE s.profile_id=? ORDER BY s.updated_at DESC''', (profile_id,))]


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value)) if value else None
        return parsed.astimezone().replace(tzinfo=None) if parsed and parsed.tzinfo else parsed
    except (ValueError, TypeError):
        return None


def phone_quality(value):
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('55') and len(digits) in (12, 13):
        digits = digits[2:]
    valid = len(digits) in (10, 11) and digits[:2] not in ('00', '10', '20') and digits[0:1] not in ('0',)
    valid = valid and len(set(digits)) > 2 and (len(digits) != 11 or digits[2] == '9')
    return {'format_valid': bool(valid), 'mobile': bool(valid and len(digits) == 11),
            'normalized': '55' + digits if valid else '',
            'note': 'Formato plausível; existência no WhatsApp depende de confirmação humana.' if valid else 'Telefone incompleto ou formato improvável.'}


def metrics(items, now=None):
    now = now or datetime.now()
    active = [x for x in items if x['lead_status'] not in ('convertido', 'descartado', 'concluido') and not x.get('do_not_contact')]
    won = [x for x in items if x['lead_status'] == 'convertido']
    contacted = [x for x in items if x.get('first_contact_at')]
    first = [(timestamp(x['first_contact_at'])-timestamp(x['added_at'])).total_seconds()/3600
             for x in contacted if timestamp(x['first_contact_at']) and timestamp(x['added_at'])
             and timestamp(x['first_contact_at']) >= timestamp(x['added_at'])]
    closing = [(timestamp(x['closed_at'])-timestamp(x['added_at'])).total_seconds()/86400
               for x in won if timestamp(x.get('closed_at')) and timestamp(x.get('added_at'))
               and timestamp(x['closed_at']) >= timestamp(x['added_at'])]
    return {'total': len(items), 'active': len(active), 'contacted': len(contacted), 'won': len(won),
            'conversion_pct': round(100*len(won)/len(items), 1) if items else 0,
            'offered_cents': sum(x.get('offered_value_cents',0) for x in active),
            'pipeline_cents': sum(x.get('negotiated_value_cents',0) for x in active),
            'closed_cents': sum(x.get('closed_value_cents',0) for x in won),
            'avg_first_contact_hours': round(sum(first)/len(first),1) if first else None,
            'avg_close_days': round(sum(closing)/len(closing),1) if closing else None,
            'first_contact_sample':len(first),'closing_sample':len(closing),
            'overdue': sum(bool(timestamp(x.get('next_action_at')) and timestamp(x['next_action_at']) < now) for x in active)}


def analytics(db, profile_id, start='', end='', campaign=''):
    config = settings(db, profile_id)
    items = rows(db, profile_id)
    suppressed={r[0] for r in db.execute('SELECT cs.cnpj FROM contact_suppression cs JOIN sales_profiles p ON p.owner_id=cs.owner_id WHERE p.id=?',(profile_id,))}
    for item in items:item['do_not_contact']=item['cnpj'] in suppressed
    # Cohort by date of entry, not current edit date; labels document denominator.
    if start: items = [x for x in items if x['added_at'][:10] >= start]
    if end: items = [x for x in items if x['added_at'][:10] <= end]
    if campaign: items = [x for x in items if x.get('campaign') == campaign]
    now = datetime.now()
    active = [x for x in items if x['lead_status'] not in ('convertido','descartado','concluido') and not x.get('do_not_contact')]
    queue = []
    for x in active:
        due = timestamp(x.get('next_action_at')); entered = timestamp(x['added_at'])
        touched = timestamp(x.get('last_contact_at') or x['updated_at'])
        reasons = []
        if due and due < now: reasons.append('Retorno vencido')
        elif due and due.date() == now.date(): reasons.append('Contato de hoje')
        if not x.get('first_contact_at'):
            reasons.append('Primeiro contato fora do prazo' if entered and now-entered > timedelta(hours=config['contact_sla_hours']) else 'Primeiro contato')
        if x['lead_status'] == 'negociacao' and touched and now-touched > timedelta(days=config['stalled_days']): reasons.append('Negociação parada')
        if not due or not str(x.get('next_action','')).strip(): reasons.append('Definir próxima ação')
        if reasons:
            queue.append({'cnpj': x['cnpj'], 'company': x.get('nome_fantasia') or x['razao_social'],
                          'reasons': reasons, 'stage': x['lead_status'], 'due': x.get('next_action_at'),
                          'phone': x.get('whatsapp_phone') or x.get('telefone'),
                          'priority': (100 if 'Retorno vencido' in reasons else 0)+(50 if 'Negociação parada' in reasons else 0)+(30 if 'Primeiro contato fora do prazo' in reasons else 0)})
    queue.sort(key=lambda x: (-x['priority'], x.get('due') or '9999', x['cnpj']))
    breakdown = {}
    for field in ('segmento', 'campaign', 'persona', 'lead_origin'):
        groups = defaultdict(list)
        for item in items: groups[item.get(field) or 'Não informado'].append(item)
        breakdown[field] = [{'label': name, **metrics(group)} for name, group in sorted(groups.items(), key=lambda pair: -len(pair[1]))]
    loss = Counter(x.get('loss_reason') or '' for x in items if x['lead_status']=='descartado')
    quality = {'invalid_phone': sum(not phone_quality(x.get('whatsapp_phone') or x.get('telefone'))['format_valid'] for x in items),
               'whatsapp_confirmed': sum(x.get('whatsapp_status')=='confirmed' for x in items),
               'whatsapp_pending': sum(x.get('whatsapp_status') in ('pending','',None) for x in items),
               'missing_followup': sum(not x.get('next_action_at') or not str(x.get('next_action','')).strip() for x in active),
               'missing_loss_reason': sum(not x.get('loss_reason') for x in items if x['lead_status']=='descartado'),
               'unvalidated_public_data': sum(not x.get('serpro_checked_at') for x in items),
               'won_without_positive_value':sum(not x.get('closed_value_cents') for x in items if x['lead_status']=='convertido'),
               'active_without_positive_offer':sum(not x.get('offered_value_cents') for x in active)}
    return {'summary': metrics(items), 'settings': config, 'queue': queue, 'breakdown': breakdown,
            'stages': [{'key': key, 'label': label, 'total': sum(x['lead_status']==key for x in items)}
                       for key,label in [('novo','Novo'),('qualificado','Qualificado'),('contatado','Contatado'),('negociacao','Em negociação'),('convertido','Convertido'),('descartado','Descartado'),('concluido','Concluído')]],
            'loss_reasons': [{'label': LOSS_REASONS.get(key,key), 'total': value} for key,value in loss.items()],
            'quality': quality, 'items': items, 'period': {'from': start,'to': end,'campaign': campaign,'basis':'Data de entrada no painel'},
            'metric_context':{'conversion':'Convertidos / todos os leads deste recorte de entrada. Sem leads, 0% não indica desempenho.',
               'money':'Pipeline soma negociados de leads ativos; receita soma valores fechados dos Convertidos. Campos antigos usam zero como padrão: não distinguem valor não preenchido de fechamento sem receita.',
               'time':'Médias só usam datas válidas, posteriores à entrada. Sem amostra, aparece —; não zero dias.',
               'stages':'Estoque atual por etapa, não retenção histórica. Contatos externos não vinculados ficam fora deste funil.'},
            'generated_at': now.isoformat(timespec='seconds')}


def log_changes(db, profile_id, cnpj, current, changes, now):
    excluded = {'updated_at','whatsapp_checked_at'}
    diff = {key: {'before': current[key], 'after': value} for key,value in changes.items()
            if key not in excluded and key in current.keys() and current[key] != value}
    if diff:
        db.execute('''INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at,changes_json)
            VALUES(?,?,'fields_updated','Campos da oportunidade atualizados',?,?,?)''',
            (profile_id,cnpj,', '.join(diff),now,json.dumps(diff,ensure_ascii=False)))


def archive_lead(db, profile_id, cnpj):
    row = db.execute('SELECT nome_fantasia,razao_social FROM companies WHERE cnpj=?', (cnpj,)).fetchone()
    events = [dict(x) for x in db.execute('SELECT * FROM sales_lead_history WHERE profile_id=? AND cnpj=? ORDER BY id', (profile_id,cnpj))]
    if row:
        db.execute('INSERT INTO commercial_archive(profile_id,cnpj,company_name,removed_at,events_json) VALUES(?,?,?,?,?)',
                   (profile_id,cnpj,row['nome_fantasia'] or row['razao_social'],datetime.now().isoformat(timespec='seconds'),json.dumps(events,ensure_ascii=False)))
