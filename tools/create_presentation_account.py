"""Provision an explicitly requested presentation account, never copy seller data.

Requires --apply and RADAR_PRESENTATION_PASSWORD. Only INSERTs are performed.
Existing usernames are never overwritten. Synthetic companies use UF ZZ/TESTE
so the shared Receita Federal search (UF RS) does not count them.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

ROOT=Path(__file__).resolve().parents[1]
BUSINESSES=[
 ('Aurora Café','Alimentação e hospedagem','5611203','Lanchonetes, casas de chá e similares','Porto Alegre'),
 ('Vértice Tecnologia','Tecnologia e comunicação','6201501','Desenvolvimento de programas sob encomenda','Caxias do Sul'),
 ('Horizonte Moda','Comércio','4781400','Comércio varejista de artigos do vestuário','Canoas'),
 ('Estação Fitness','Saúde','9313100','Atividades de condicionamento físico','Novo Hamburgo'),
 ('Jardim Pet','Serviços','9609208','Higiene e embelezamento de animais domésticos','São Leopoldo'),
 ('Nexo Contabilidade','Serviços profissionais','6920601','Atividades de contabilidade','Pelotas'),
 ('Sabor da Praça','Alimentação e hospedagem','5611201','Restaurantes e similares','Santa Maria'),
 ('Prisma Engenharia','Construção','7112000','Serviços de engenharia','Passo Fundo'),
 ('Vista Ótica','Comércio','4774100','Comércio varejista de artigos de óptica','Bento Gonçalves'),
 ('Atlas Logística','Transporte e logística','4930202','Transporte rodoviário de carga','Lajeado'),
 ('Linha Clara Design','Serviços profissionais','7410202','Design de interiores','Porto Alegre'),
 ('Ponto Verde Mercado','Comércio','4712100','Minimercados, mercearias e armazéns','Gravataí'),
 ('Essência Bem-Estar','Saúde','9602502','Atividades de estética e beleza','Caxias do Sul'),
 ('Foco Educação','Educação','8599604','Treinamento em desenvolvimento profissional','Canoas'),
 ('Cais Digital','Tecnologia e comunicação','6202300','Desenvolvimento de software customizável','Pelotas'),
 ('Trama Móveis','Comércio','4754701','Comércio varejista de móveis','Bento Gonçalves'),
 ('Rota Sul Turismo','Serviços','7911200','Agências de viagens','Santa Maria'),
 ('Vale Automação','Tecnologia e comunicação','6204000','Consultoria em tecnologia da informação','Lajeado'),
 ('Brisa Restaurante','Alimentação e hospedagem','5611201','Restaurantes e similares','Porto Alegre'),
 ('Lumina Consultoria','Serviços profissionais','7020400','Consultoria em gestão empresarial','Caxias do Sul'),
 ('Crescer Cursos','Educação','8599604','Treinamento em desenvolvimento profissional','Novo Hamburgo'),
 ('Pampa Soluções','Tecnologia e comunicação','6201501','Desenvolvimento de programas sob encomenda','Passo Fundo'),
 ('Doce Estação','Alimentação e hospedagem','5611203','Lanchonetes, casas de chá e similares','Gravataí'),
 ('Quinta Oficina','Serviços','4520001','Manutenção e reparação de veículos','São Leopoldo'),
]
STAGES=['novo']*4+['qualificado']*4+['contatado']*5+['negociacao']*5+['convertido']*4+['descartado','concluido']


def stamp(value):return value.isoformat(timespec='seconds')


def insert(db,table,values):
    names=','.join(values);marks=','.join('?' for _ in values)
    db.execute(f'INSERT INTO {table}({names}) VALUES({marks})',tuple(values.values()))


def other_data_digest(db,owner):
    """Check original commercial/account rows without displaying personal data."""
    digest=hashlib.sha256()
    for table,condition in (
        ('user_accounts','id<>?'),('sales_profiles',"COALESCE(owner_id,'')<>?"),
        ('sales_profile_leads','profile_id NOT IN (SELECT id FROM sales_profiles WHERE owner_id=?)'),
        ('sales_lead_history','profile_id NOT IN (SELECT id FROM sales_profiles WHERE owner_id=?)'),
        ('message_templates','owner_id<>?'),('account_company_state','account_id<>?'),
    ):
        digest.update(table.encode())
        for row in db.execute(f'SELECT * FROM {table} WHERE {condition} ORDER BY rowid',(owner,)):
            digest.update(json.dumps(tuple(row),ensure_ascii=False,default=str).encode())
    return digest.hexdigest()


def provision(database,password,backup_directory,now=None):
    if not isinstance(password,str) or len(password)<10:raise ValueError('Informe uma senha de pelo menos 10 caracteres')
    now=(now or datetime.now()).replace(microsecond=0)
    owner='conta-radar-demo-'+uuid.uuid4().hex[:12];profile='usuario-radar-demo-'+uuid.uuid4().hex[:12]
    with closing(sqlite3.connect(database,timeout=30)) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=30000')
        # Lock before backup and validation: existing work cannot race preservation checks.
        db.execute('BEGIN IMMEDIATE')
        try:
            if db.execute("SELECT 1 FROM user_accounts WHERE username='Radar' COLLATE NOCASE OR email='radar@presentation.invalid'").fetchone():
                raise ValueError('A conta Radar já existe. Nenhuma conta, senha ou lead foi sobrescrito.')
            before=other_data_digest(db,owner)
            backup_directory.mkdir(parents=True,exist_ok=True)
            backup=backup_directory/f'radar-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.sqlite'
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup não passou na integridade')
            salt=os.urandom(16);hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,260000).hex()
            insert(db,'user_accounts',dict(id=owner,name='Radar · Demonstração',username='Radar',email='radar@presentation.invalid',password_hash=hashed,password_salt=salt.hex(),role='vendedor',is_active=1,created_at=stamp(now),updated_at=stamp(now)))
            insert(db,'sales_profiles',dict(id=profile,owner_id=owner,name='Radar · Demonstração',role='Apresentação · dados fictícios',email='radar@presentation.invalid',initials='RD',color='#ec2255',created_at=stamp(now),updated_at=stamp(now)))
            won_values=[240000,580000,320000,760000];pipeline=[180000,450000,290000,680000,360000];history_count=0
            for i,(business,stage) in enumerate(zip(BUSINESSES,STAGES)):
                name,segment,cnae,description,city=business
                cnpj='999'+f'{uuid.uuid4().int%10**11:011d}'
                added=now-timedelta(days=2+i%12,hours=2)
                if stage=='convertido':added=now-timedelta(days=9+i-18,hours=2)
                first=None if stage=='novo' else added+timedelta(hours=4+i%8)
                closed=added+timedelta(days=7,hours=2) if stage=='convertido' else None
                closed_value=won_values[i-18] if stage=='convertido' else 0
                negotiated=closed_value if stage=='convertido' else pipeline[i-13] if stage=='negociacao' else 0
                offered=negotiated+20000 if negotiated else (120000+(i%5)*30000 if stage not in ('novo','descartado','concluido') else 0)
                final=closed or now-timedelta(hours=1+i%6)
                due=None if stage in ('convertido','descartado','concluido') else now+timedelta(days=(-2 if i in (5,8,14) else 0 if i in (6,9,15) else 1+i%4),hours=2)
                outcome='' if stage=='novo' else 'sem_interesse' if stage=='descartado' else 'oportunidade' if stage in ('negociacao','convertido') else 'retornar' if stage=='concluido' else 'respondeu' if i%2 else 'nao_respondeu'
                action='' if due is None else 'Apresentar proposta (simulação)' if stage=='negociacao' else 'Retomar contato (simulação)'
                campaign=['Comércio local','Serviços B2B','Expansão regional'][i%3]
                insert(db,'companies',dict(cnpj=cnpj,razao_social=name+' · FICTÍCIO',nome_fantasia=name+' (Demonstração)',situacao='TESTE',data_abertura=(added-timedelta(days=25)).date().isoformat(),cnae=cnae,cnae_descricao=description,segmento=segment,municipio=city,regiao='Demonstração',uf='ZZ',telefone='',email=f'demo{i+1}@presentation.invalid',porte='ME',mei=0,data_source='Demonstração fictícia · Radar'))
                insert(db,'sales_profile_leads',dict(profile_id=profile,cnpj=cnpj,added_at=stamp(added),updated_at=stamp(final),favorito=int(i in (5,13,16)),lead_status=stage,observacoes='SIMULAÇÃO: empresa e histórico fictícios para apresentação. Não realizar contato.',estrategia='Apresentar benefícios, validar necessidade e registrar o próximo passo (cenário fictício).',contact_outcome=outcome,next_action=action,next_action_at=stamp(due) if due else None,first_contact_at=stamp(first) if first else None,last_contact_at=stamp(final) if first else None,closed_at=stamp(closed) if closed else None,offered_value_cents=offered,negotiated_value_cents=negotiated,closed_value_cents=closed_value,whatsapp_status='pending',whatsapp_phone='',campaign=campaign,persona='Responsável comercial (simulação)',lead_origin='Apresentação fictícia',loss_reason='sem_interesse' if stage=='descartado' else ''))
                events=[('created','Lead fictício incluído','Cenário criado apenas para apresentação.',added,{})]
                if first:
                    events.append(('contact_recorded','Primeiro contato registrado (simulação)','Necessidades iniciais levantadas.',first,{'contact_outcome':{'before':'','after':'respondeu'}}))
                    events.append(('fields_updated','Qualificação registrada (simulação)','ICP e próximo passo definidos.',first+timedelta(hours=1),{'lead_status':{'before':'novo','after':'qualificado'}}))
                if negotiated:
                    events.append(('fields_updated','Proposta negociada (simulação)','Valores registrados em centavos.',added+timedelta(days=2),{'lead_status':{'before':'qualificado','after':'negociacao'},'negotiated_value_cents':{'before':0,'after':negotiated}}))
                events.append(('fields_updated','Etapa atual registrada (simulação)',action or 'Atendimento encerrado no cenário de demonstração.',final,{'lead_status':{'before':'negociacao' if negotiated else 'qualificado' if first else 'novo','after':stage},'contact_outcome':{'before':'respondeu' if first else '','after':outcome}}))
                for event,title,details,at,changes in events:
                    insert(db,'sales_lead_history',dict(profile_id=profile,cnpj=cnpj,event_type=event,title=title,details=details,created_at=stamp(at),changes_json=json.dumps(changes,ensure_ascii=False)));history_count+=1
            insert(db,'sales_monthly_targets',dict(profile_id=profile,month=now.strftime('%Y-%m'),revenue_cents=3000000,contacts=30,wins=6,updated_at=stamp(now)))
            insert(db,'message_templates',dict(id='demo-mensagem-'+uuid.uuid4().hex[:12],owner_id=owner,name='Apresentação fictícia',body='SIMULAÇÃO: Olá! Sou {vendedor}, do Radar. Gostaria de apresentar uma proposta para {empresa}.',is_default=1,created_at=stamp(now),updated_at=stamp(now)))
            if before!=other_data_digest(db,owner):raise ValueError('Dados de outras contas divergiram; operação será revertida')
            if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Relação inconsistente; operação será revertida')
            db.commit()
        except Exception:db.rollback();raise
    return dict(username='Radar',account_id=owner,profile_id=profile,leads=24,history_events=history_count,stages=dict(Counter(STAGES)),closed_cents=sum(won_values),pipeline_cents=sum(pipeline),other_accounts_unchanged=True,backup=str(backup))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,default=ROOT/'data'/'radar.db');parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if not args.apply:raise SystemExit('Use --apply para criar apenas a conta de apresentação autorizada.')
    password=os.environ.get('RADAR_PRESENTATION_PASSWORD','')
    print(json.dumps(provision(args.db.resolve(),password,args.db.resolve().parent/'admin-backups'),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
