"""Account-private daily sales workflow; deterministic metrics, no external services."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs
import commercial


def ensure_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS contact_suppression (
      owner_id TEXT NOT NULL,cnpj TEXT NOT NULL,reason TEXT NOT NULL,updated_at TEXT NOT NULL,
      PRIMARY KEY(owner_id,cnpj),FOREIGN KEY(cnpj) REFERENCES companies(cnpj));
      CREATE TABLE IF NOT EXISTS sales_monthly_targets (
      profile_id TEXT NOT NULL REFERENCES sales_profiles(id) ON DELETE CASCADE,
      month TEXT NOT NULL,revenue_cents INTEGER NOT NULL DEFAULT 0,contacts INTEGER NOT NULL DEFAULT 0,
      wins INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(profile_id,month));
      CREATE INDEX IF NOT EXISTS idx_sales_closed_date ON sales_profile_leads(profile_id,closed_at);
    ''')


def revision(row):
    return hashlib.sha256(json.dumps(dict(row),sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def blocked(db,owner,cnpj):
    return db.execute('SELECT reason FROM contact_suppression WHERE owner_id=? AND cnpj=?',(owner,cnpj)).fetchone()


def decorate(db,owner,items):
    suppression={r['cnpj']:r['reason'] for r in db.execute('SELECT cnpj,reason FROM contact_suppression WHERE owner_id=?',(owner,))}
    for item in items:
        item['profile_do_not_contact']=item['cnpj'] in suppression
        item['profile_suppression_reason']=suppression.get(item['cnpj'],'')
    return items


def period(start='',end='',today=None):
    today=today or date.today()
    first=date.fromisoformat(start) if start else today.replace(day=1)
    last=date.fromisoformat(end) if end else today
    if first>last or (last-first).days>366:raise ValueError('Escolha um período de até 367 dias, com início antes do fim.')
    return first,last


def in_period(value,first,last):
    stamp=commercial.timestamp(value)
    return bool(stamp and first<=stamp.date()<=last)


def period_metrics(items,events,first,last):
    won=[x for x in items if x['lead_status']=='convertido' and in_period(x.get('closed_at'),first,last)]
    entries=[x for x in items if in_period(x.get('added_at'),first,last)]
    contacts=[x for x in events if x['event_type'] in ('contact_recorded','contact_outcome') and in_period(x['created_at'],first,last)]
    contacted={x['cnpj'] for x in contacts}
    revenue=sum(x.get('closed_value_cents') or 0 for x in won)
    return {'entries':len(entries),'wins':len(won),'closed_cents':revenue,'contacts':len(contacts),
            'contacted_leads':len(contacted),'ticket_cents':round(revenue/len(won)) if won else None,
            'cohort_conversion_pct':commercial.metrics(entries)['conversion_pct'],
            'wins_missing_date':sum(x['lead_status']=='convertido' and not commercial.timestamp(x.get('closed_at')) for x in items)}


def dashboard(db,profile,owner,start='',end='',month='',now=None):
    now=now or datetime.now();first,last=period(start,end,now.date());days=(last-first).days+1
    month=month or now.strftime('%Y-%m')
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):raise ValueError('Mês da meta inválido')
    items=commercial.rows(db,profile)
    events=[dict(r) for r in db.execute("SELECT h.cnpj,h.event_type,h.created_at FROM sales_lead_history h JOIN accessible_sales_profile_leads s ON s.profile_id=h.profile_id AND s.cnpj=h.cnpj WHERE h.profile_id=? AND h.event_type IN ('contact_recorded','contact_outcome') ORDER BY h.created_at",(profile,))]
    suppressed={r['cnpj']:r['reason'] for r in db.execute('SELECT cnpj,reason FROM contact_suppression WHERE owner_id=?',(owner,))}
    visible_ids={item['cnpj'] for item in items}
    suppressed={cnpj:reason for cnpj,reason in suppressed.items() if cnpj in visible_ids}
    agenda=[];counts={key:0 for key in ('overdue','today','week','later','unscheduled','blocked')}
    for x in items:
        if x['cnpj'] in suppressed:counts['blocked']+=1;continue
        if x['lead_status'] in ('convertido','descartado','concluido'):continue
        due=commercial.timestamp(x.get('next_action_at'))
        bucket='unscheduled' if not due else 'overdue' if due<now else 'today' if due.date()==now.date() else 'week' if due.date()<=now.date()+timedelta(days=7) else 'later'
        counts[bucket]+=1
        agenda.append({'cnpj':x['cnpj'],'company':x.get('nome_fantasia') or x['razao_social'],
          'stage':x['lead_status'],'outcome':x.get('contact_outcome') or '',
          'next_action':x.get('next_action') or '', 'due':x.get('next_action_at') or '',
          'phone':x.get('whatsapp_phone') or x.get('telefone') or '',
          'bucket':bucket,'revision':revision(x)})
    order={'overdue':0,'today':1,'week':2,'unscheduled':3,'later':4}
    agenda.sort(key=lambda x:(order[x['bucket']],x['due'] or '9999',x['cnpj']))
    goal=db.execute('SELECT * FROM sales_monthly_targets WHERE profile_id=? AND month=?',(profile,month)).fetchone()
    goal=dict(goal) if goal else dict(month=month,revenue_cents=0,contacts=0,wins=0)
    mfirst=date.fromisoformat(month+'-01');mlast=(mfirst.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
    actual=period_metrics(items,events,mfirst,mlast)
    trend=[{'date':(first+timedelta(days=i)).isoformat(),'entries':0,'contacts':0,'wins':0,'closed_cents':0} for i in range(days)]
    by_day={x['date']:x for x in trend}
    for item in items:
        entered=commercial.timestamp(item.get('added_at'));closed=commercial.timestamp(item.get('closed_at'))
        if entered and entered.date().isoformat() in by_day:by_day[entered.date().isoformat()]['entries']+=1
        if item['lead_status']=='convertido' and closed and closed.date().isoformat() in by_day:
            point=by_day[closed.date().isoformat()];point['wins']+=1;point['closed_cents']+=item.get('closed_value_cents') or 0
    for event in events:
        stamp=commercial.timestamp(event['created_at'])
        if stamp and stamp.date().isoformat() in by_day:by_day[stamp.date().isoformat()]['contacts']+=1
    return {'period':{'from':first.isoformat(),'to':last.isoformat(),'days':days},
      'current':period_metrics(items,events,first,last),
      'previous':period_metrics(items,events,first-timedelta(days=days),first-timedelta(days=1)),
      'previous_period':{'from':(first-timedelta(days=days)).isoformat(),'to':(first-timedelta(days=1)).isoformat()},
      'agenda':agenda,'agenda_total':len(agenda),'counts':counts,'targets':goal,'target_actual':actual,'trend':trend,
      'blocked_cnpjs':sorted(suppressed),
      'suppressed':[{'cnpj':x['cnpj'],'company':x.get('nome_fantasia') or x['razao_social'],'reason':suppressed[x['cnpj']]} for x in items if x['cnpj'] in suppressed],
      'definitions':{'entries':'Leads incluídos no período, pela data de entrada.',
        'closed':'Valores dos leads atualmente Convertidos, pela data de fechamento. Inclui leads que entraram antes do período.',
        'contacts':'Contatos registrados e mudanças de resultado no histórico. Abrir um link de WhatsApp não comprova contato.',
        'comparison':'Período anterior com a mesma quantidade de dias. Não é previsão.',
        'legacy':'Registros antigos sem datas não são reconstruídos; reaberturas não representam receita contábil nem estornos.'}}


def quick_contact(db,profile,owner,payload,now=None):
    stamp=(now or datetime.now()).isoformat(timespec='microseconds')
    cnpj=str(payload.get('cnpj',''))
    db.execute('BEGIN IMMEDIATE')
    row=db.execute('SELECT s.*,c.* FROM accessible_sales_profile_leads s JOIN companies c ON c.cnpj=s.cnpj WHERE s.profile_id=? AND s.cnpj=?',(profile,cnpj)).fetchone()
    if not row:raise LookupError('Lead não encontrado')
    if blocked(db,owner,cnpj):raise PermissionError('Contato bloqueado nesta conta. Revise a autorização antes de reativar.')
    if payload.get('revision')!=revision(row):raise FileExistsError('Lead alterado em outra sessão. Atualize a agenda antes de salvar.')
    outcome=payload.get('outcome','')
    if row['lead_status'] in ('convertido','descartado','concluido'):raise ValueError('Atendimento encerrado. Reabra a oportunidade na ficha antes de registrar contato.')
    if outcome not in {'nao_respondeu','respondeu','retornar','sem_interesse','numero_invalido','oportunidade'}:raise ValueError('Selecione o resultado do contato')
    action=payload.get('next_action','');due=payload.get('next_action_at','');notes=payload.get('notes','')
    if not isinstance(action,str) or len(action)>500 or not isinstance(notes,str) or len(notes)>1000:raise ValueError('Próxima ação: até 500 caracteres. Nota: até 1000.')
    if bool(action.strip())!=bool(due):raise ValueError('Preencha a próxima ação e sua data, ou deixe ambos vazios.')
    if due:
        parsed=commercial.timestamp(due)
        if not parsed or parsed.year<2000 or parsed.year>2100:raise ValueError('Data de retorno inválida')
        due=parsed.isoformat(timespec='seconds')
    changes={'contact_outcome':outcome,'last_contact_at':stamp,'first_contact_at':row['first_contact_at'] or stamp,
             'next_action':action.strip(),'next_action_at':due or None,'updated_at':stamp}
    if row['lead_status'] in ('novo','qualificado'):changes['lead_status']='contatado'
    commercial.log_changes(db,profile,cnpj,row,changes,stamp)
    db.execute('UPDATE sales_profile_leads SET '+','.join(key+'=?' for key in changes)+' WHERE profile_id=? AND cnpj=?',list(changes.values())+[profile,cnpj])
    db.execute("INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at) VALUES(?,?,'contact_recorded','Contato registrado',?,?)",(profile,cnpj,json.dumps({'outcome':outcome,'note':notes,'next_action':action,'due':due},ensure_ascii=False),stamp))
    db.execute('UPDATE sales_profiles SET updated_at=? WHERE id=?',(stamp,profile))
    return {'saved':True,'created_at':stamp}


def complete_action(db,profile,owner,payload):
    cnpj=str(payload.get('cnpj',''));mode=payload.get('mode','lead');note=payload.get('notes','')
    if mode not in ('action','lead') or not isinstance(note,str) or not 2<=len(note.strip())<=1000:
        raise ValueError('Descreva a ação realizada (2 a 1000 caracteres).')
    action=payload.get('next_action','');due=payload.get('next_action_at','')
    if not isinstance(action,str) or len(action)>500 or not isinstance(due,str):raise ValueError('Próxima ação inválida')
    if mode=='lead' and (action.strip() or due):raise ValueError('Para dar baixa, deixe o próximo retorno vazio.')
    if bool(action.strip())!=bool(due):raise ValueError('Informe a próxima ação e sua data, ou deixe ambos vazios.')
    if due:
        parsed=commercial.timestamp(due)
        if not parsed or parsed<=datetime.now() or parsed.year>2100:raise ValueError('Escolha uma data futura para o novo retorno.')
        due=parsed.isoformat(timespec='seconds')
    db.execute('BEGIN IMMEDIATE')
    row=db.execute('SELECT s.*,c.* FROM accessible_sales_profile_leads s JOIN companies c ON c.cnpj=s.cnpj WHERE s.profile_id=? AND s.cnpj=?',(profile,cnpj)).fetchone()
    if not row:raise LookupError('Lead não encontrado')
    if payload.get('revision')!=revision(row):raise FileExistsError('Lead alterado em outra sessão. Atualize antes de concluir.')
    if row['lead_status'] in ('convertido','descartado','concluido'):raise ValueError('Lead já encerrado. Reabra pela ficha se necessário.')
    stamp=datetime.now().isoformat(timespec='microseconds')
    changes={'next_action':action.strip(),'next_action_at':due or None,'updated_at':stamp}
    if mode=='lead':changes['lead_status']='concluido'
    commercial.log_changes(db,profile,cnpj,row,changes,stamp)
    db.execute('UPDATE sales_profile_leads SET '+','.join(k+'=?' for k in changes)+' WHERE profile_id=? AND cnpj=?',list(changes.values())+[profile,cnpj])
    details=json.dumps({'note':note.strip(),'completed_action':row['next_action'],'previous_due':row['next_action_at'],'next_action':action.strip(),'due':due},ensure_ascii=False)
    db.execute('INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at) VALUES(?,?,?,?,?,?)',(profile,cnpj,'lead_completed' if mode=='lead' else 'action_completed','Lead concluído · baixa' if mode=='lead' else 'Pendência concluída',details,stamp))
    db.execute('UPDATE sales_profiles SET updated_at=? WHERE id=?',(stamp,profile))
    return {'saved':True,'completed':mode,'created_at':stamp}


def handle(h,context,parsed,write=False):
    try:
        if write:
            length=int(h.headers.get('Content-Length','0'))
            if not 0<length<=8192:raise ValueError('Solicitação acima do limite permitido')
            payload=h.read_json_object(length)
            if not isinstance(payload,dict):raise ValueError('Solicitação inválida')
            profile=str(payload.get('profile_id',''))
        else:
            params=parse_qs(parsed.query);profile=params.get('profile_id',[''])[0]
        owner=h.session_owner_id()
        with context['connect']() as db:
            selected=h.owned_sales_profile(db,profile)
            if not selected:return h.send_json({'erro':'Responsável não encontrado para esta conta'},404)
            owner=selected['owner_id'] or owner  # Admin acts on the selected seller's account, not their own.
            if not write:return h.send_json(dashboard(db,profile,owner,params.get('from',[''])[0],params.get('to',[''])[0],params.get('month',[''])[0]))
            if parsed.path=='/api/sales-ops/contact':result=quick_contact(db,profile,owner,payload)
            elif parsed.path=='/api/sales-ops/complete':result=complete_action(db,profile,owner,payload)
            elif parsed.path=='/api/sales-ops/targets':
                month=payload.get('month','')
                if not isinstance(month,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):raise ValueError('Mês inválido')
                values=[payload.get(key,0) for key in ('revenue_cents','contacts','wins')]
                if any(type(v) is not int or not 0<=v<=100000000000 for v in values):raise ValueError('Metas devem ser números não negativos')
                db.execute('INSERT INTO sales_monthly_targets VALUES(?,?,?,?,?,?) ON CONFLICT(profile_id,month) DO UPDATE SET revenue_cents=excluded.revenue_cents,contacts=excluded.contacts,wins=excluded.wins,updated_at=excluded.updated_at',[profile,month]+values+[datetime.now().isoformat(timespec='seconds')]);result={'saved':True}
            elif parsed.path=='/api/sales-ops/suppression':
                cnpj=payload.get('cnpj');active=payload.get('blocked');reason=payload.get('reason','')
                if type(active) is not bool or not isinstance(reason,str) or len(reason)>500:raise ValueError('Informe motivo de até 500 caracteres')
                if not db.execute('SELECT 1 FROM accessible_sales_profile_leads WHERE profile_id=? AND cnpj=?',(profile,cnpj)).fetchone():raise LookupError('Lead não encontrado')
                if active and not reason.strip():raise ValueError('Informe o motivo do bloqueio')
                stamp=datetime.now().isoformat(timespec='microseconds')
                if active:db.execute('INSERT INTO contact_suppression VALUES(?,?,?,?) ON CONFLICT(owner_id,cnpj) DO UPDATE SET reason=excluded.reason,updated_at=excluded.updated_at',(owner,cnpj,reason.strip(),stamp))
                else:
                    if payload.get('confirm_restore') is not True:raise ValueError('Confirme que tem autorização para retomar o contato')
                    db.execute('DELETE FROM contact_suppression WHERE owner_id=? AND cnpj=?',(owner,cnpj))
                db.execute("INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at) VALUES(?,?,'contact_permission',?,?,?)",(profile,cnpj,'Não contatar' if active else 'Contato reautorizado',reason.strip(),stamp));result={'saved':True,'blocked':active}
            else:return h.send_error(404)
        return h.send_json(result)
    except FileExistsError as error:return h.send_json({'erro':str(error)},409)
    except PermissionError as error:return h.send_json({'erro':str(error)},403)
    except LookupError as error:return h.send_json({'erro':str(error)},404)
    except (ValueError,TypeError,OverflowError) as error:return h.send_json({'erro':str(error) or 'Dados inválidos'},400)
