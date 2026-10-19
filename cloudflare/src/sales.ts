/** Current Radar team, sales workflow, templates and commercial endpoints on D1. */
import { ApiError, bodyJson, headers, json, moneyCents, now, privateCompanyVisible, queryFirst, queryRows, requireProfile, type Env, type Principal, type Row } from './runtime';
import { commercialAnalytics, companyName, dateRange, leadRevision, LOSSES, operationsDashboard, OUTCOMES, safeDateTime, scoreCompany, STAGES, terminal, time, type Lead } from './sales-analytics';
import { commercialPdf } from './report-current';

// Explicit company projection keeps portfolio status/notes authoritative when the
// legacy companies table also contains columns with these names.
const companyColumns=['id','razao_social','nome_fantasia','situacao','data_abertura','cnae','cnaes_secundarios','segmento','municipio','regiao','uf','cep','bairro','logradouro','numero','telefone','email','porte','mei','cnae_descricao','serpro_checked_at','data_source'];
const companyProjection=companyColumns.map(k=>'c.'+k).join(',');
const joined=`SELECT spl.*,${companyProjection} FROM accessible_sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj`;
const mutableFields=['favorito','lead_status','observacoes','estrategia','contact_outcome','next_action','next_action_at','last_contact_at','first_contact_at','closed_at','offered_value_cents','negotiated_value_cents','closed_value_cents','whatsapp_status','whatsapp_phone','whatsapp_checked_at','campaign','persona','lead_origin','loss_reason'];
const s=(value:unknown)=>String(value??'');
const cleanCnpj=(value:unknown)=>s(value).toUpperCase().replace(/[^A-Z0-9]/g,'');
const id=(prefix:string)=>prefix+crypto.randomUUID().replace(/-/g,'').slice(0,12);
function stamp():string {return now().slice(0,19)+'.'+String(new Date().getUTCMilliseconds()).padStart(3,'0')+String(crypto.getRandomValues(new Uint32Array(1))[0]%1000).padStart(3,'0');}
function positiveInt(value:string|null,fallback:number,maximum=Number.MAX_SAFE_INTEGER):number {
  if(value===null||value==='')return fallback;if(!/^-?\d+$/.test(value))throw new ApiError(400,'Paginação inválida');
  const n=Number(value);if(!Number.isSafeInteger(n))throw new ApiError(400,'Paginação inválida');return Math.min(maximum,Math.max(1,n));
}
function validateIdentity(profile:string,cnpj:string):void {if(!profile||cnpj.length!==14)throw new ApiError(400,'Perfil ou CNPJ inválido');}
function owner(profile:Row,principal:Principal):string{return s(profile.owner_id)||principal.accountId;}
const scope=(principal:Principal,alias='p')=>({sql:`(?=1 OR ${alias}.owner_id=?)`,values:[principal.role==='admin'?1:0,principal.accountId]});
async function settings(db:D1Database,profile:string) {
  const saved=await queryFirst(db,'SELECT contact_sla_hours,stalled_days FROM commercial_settings WHERE profile_id=?',[profile]);
  if(saved)return {contact_sla_hours:Number(saved.contact_sla_hours),stalled_days:Number(saved.stalled_days)};
  const defaults=await queryRows(db,"SELECT key,value FROM admin_parameters WHERE key IN ('contact_sla_hours','stalled_days')");
  const result={contact_sla_hours:48,stalled_days:7};
  for(const row of defaults)try {const value=JSON.parse(s(row.value));if(Number.isInteger(value)&&value>0)result[row.key as keyof typeof result]=value;}catch {/* Invalid legacy settings fall back to documented defaults. */}
  return result;
}
async function parameter(db:D1Database,key:string,fallback:unknown):Promise<unknown> {
  const row=await queryFirst(db,'SELECT value FROM admin_parameters WHERE key=?',[key]);
  if(!row)return fallback;try{return JSON.parse(s(row.value));}catch{return fallback;}
}
async function suppressions(db:D1Database,selectedOwner:string):Promise<Map<string,string>> {
  return new Map((await queryRows(db,'SELECT cnpj,reason FROM contact_suppression WHERE owner_id=?',[selectedOwner])).map(x=>[s(x.cnpj),s(x.reason)]));
}
async function readLead(db:D1Database,profile:string,cnpj:string):Promise<Lead> {
  const row=await queryFirst<Lead>(db,joined+' WHERE spl.profile_id=? AND spl.cnpj=?',[profile,cnpj]);
  if(!row)throw new ApiError(404,'Lead não encontrado no painel deste responsável');return row;
}
async function portfolio(db:D1Database,profile:Row,principal:Principal) {
  const items=await queryRows<Lead>(db,joined+' WHERE spl.profile_id=? ORDER BY spl.updated_at DESC',[profile.id]);
  const blocked=await suppressions(db,owner(profile,principal));
  for(const item of items)item.do_not_contact=blocked.has(item.cnpj);
  return {items,blocked};
}
function present(lead:Lead,blocked:Map<string,string>):Row {
  const result:Row={...lead,profile_id:lead.profile_id,carteira_adicionado_em:lead.added_at,profile_updated_at:lead.updated_at};
  for(const key of mutableFields)result['profile_'+key]=lead[key];
  result.profile_whatsapp_status=lead.whatsapp_status||'pending';
  result.lead_score=scoreCompany(lead);result.profile_do_not_contact=blocked.has(lead.cnpj);result.profile_suppression_reason=blocked.get(lead.cnpj)||'';
  return result;
}
interface History {type:string;title:string;details?:string;changes?:Row}
function historyStatement(db:D1Database,profile:string,cnpj:string,event:History,at:string,guard='',guardValues:unknown[]=[]):D1PreparedStatement {
  const details=event.details||'';
  return db.prepare(`INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at,changes_json) SELECT ?,?,?,?,?,?,?${guard?' WHERE '+guard:''}`)
    .bind(profile,cnpj,event.type,event.title.slice(0,180),['contact_recorded','action_completed','lead_completed'].includes(event.type)?details:details.slice(0,1000),at,JSON.stringify(event.changes||{}),...guardValues);
}
function visibleMutation(principal:Principal,profile:Row):{sql:string;values:unknown[]} {
  const allowed=scope(principal);
  return {sql:`EXISTS (SELECT 1 FROM sales_profiles p JOIN companies c ON c.cnpj=sales_profile_leads.cnpj WHERE p.id=sales_profile_leads.profile_id AND p.owner_id IS ? AND ${allowed.sql} AND ${privateCompanyVisible('c','p.owner_id')})`,values:[profile.owner_id??null,...allowed.values]};
}
/** CAS, histories, and profile activity execute in a single D1 transaction. */
async function mutateLead(db:D1Database,principal:Principal,profile:Row,current:Lead,changes:Row,events:History[]=[],contact=false):Promise<void> {
  let at=typeof changes.updated_at==='string'?changes.updated_at:stamp();if(at===current.updated_at)at=at.slice(0,20)+String((Number(at.slice(20))+1)%1000000).padStart(6,'0');changes={...changes,updated_at:at};
  const diff:Row={};for(const [key,value] of Object.entries(changes))if(!['updated_at','whatsapp_checked_at'].includes(key)&&key in current&&current[key]!==value)diff[key]={before:current[key],after:value};
  const logged:History[]=Object.keys(diff).length?[{type:'fields_updated',title:'Campos da oportunidade atualizados',details:Object.keys(diff).join(', '),changes:diff},...events]:events;
  const permitted=visibleMutation(principal,profile),selectedOwner=owner(profile,principal);
  const condition=`profile_id=? AND cnpj=? AND updated_at=? AND ${permitted.sql}`+(contact?' AND NOT EXISTS (SELECT 1 FROM contact_suppression cs WHERE cs.owner_id=? AND cs.cnpj=sales_profile_leads.cnpj)':'');
  const updatedGuard='EXISTS (SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=? AND updated_at=?)';
  const result=await db.batch([
    db.prepare(`UPDATE sales_profile_leads SET ${Object.keys(changes).map(k=>k+'=?').join(',')} WHERE ${condition}`).bind(...Object.values(changes),profile.id,current.cnpj,current.updated_at,...permitted.values,...(contact?[selectedOwner]:[])),
    ...logged.map(event=>historyStatement(db,s(profile.id),current.cnpj,event,at,updatedGuard,[profile.id,current.cnpj,at])),
    db.prepare(`UPDATE sales_profiles SET updated_at=? WHERE id=? AND ${updatedGuard}`).bind(at,profile.id,profile.id,current.cnpj,at),
  ]);
  if(!result[0].meta.changes) {
    if(contact&&await queryFirst(db,'SELECT 1 FROM contact_suppression WHERE owner_id=? AND cnpj=?',[selectedOwner,current.cnpj]))throw new ApiError(403,'Contato bloqueado nesta conta. Revise a autorização antes de reativar.');
    throw new ApiError(409,'Lead alterado em outra sessão. Sua edição não foi sobrescrita: reabra a ficha para revisar os dados atuais.');
  }
}
function updateEvents(current:Lead,changes:Row):History[] {
  const events:History[]=[];const changed=(key:string)=>key in changes&&changes[key]!==current[key];
  if(changed('lead_status'))events.push({type:'stage_changed',title:'Etapa comercial alterada',details:`${STAGES[current.lead_status]||current.lead_status} → ${STAGES[s(changes.lead_status)]||changes.lead_status}`});
  if(changed('contact_outcome'))events.push({type:'contact_outcome',title:'Resultado do contato registrado',details:OUTCOMES[s(changes.contact_outcome)]});
  if(changed('whatsapp_status'))events.push({type:'whatsapp_status',title:'Verificação do WhatsApp atualizada',details:({pending:'Pendente',confirmed:'WhatsApp confirmado',not_found:'Não localizado no WhatsApp',invalid:'Telefone inválido'} as Record<string,string>)[s(changes.whatsapp_status)]});
  if(changed('next_action')||changed('next_action_at'))events.push({type:'next_action',title:'Próxima ação atualizada',details:(s(changes.next_action??current.next_action)||'Próxima ação atualizada')+((changes.next_action_at??current.next_action_at)?' · '+s(changes.next_action_at??current.next_action_at):'')});
  if(changed('observacoes')||changed('estrategia'))events.push({type:'notes_updated',title:'Anotações comerciais atualizadas',details:'Estratégia e contexto do lead foram salvos.'});
  if(['offered_value_cents','negotiated_value_cents','closed_value_cents'].some(changed))events.push({type:'financial_updated',title:'Valores da oportunidade atualizados',details:'Oferta, negociação e fechamento foram revisados.'});
  return events;
}
function leadChanges(payload:Row):Row {
  const changes:Row={};
  if('lead_status' in payload){if(!Object.hasOwn(STAGES,s(payload.lead_status)))throw new ApiError(400,'Etapa inválida');changes.lead_status=payload.lead_status;}
  if('favorito' in payload)changes.favorito=payload.favorito?1:0;
  for(const key of ['observacoes','estrategia'])if(key in payload)changes[key]=s(payload[key]).slice(0,4000);
  for(const key of ['campaign','persona','lead_origin','loss_reason'])if(key in payload)changes[key]=s(payload[key]).trim().slice(0,120);
  if('loss_reason' in changes&&!Object.hasOwn(LOSSES,s(changes.loss_reason)))throw new ApiError(400,'Motivo de perda inválido');
  if('contact_outcome' in payload){const outcome=s(payload.contact_outcome).trim();if(!Object.hasOwn(OUTCOMES,outcome))throw new ApiError(400,'Resultado do contato inválido');changes.contact_outcome=outcome;}
  if('next_action' in payload)changes.next_action=s(payload.next_action).trim().slice(0,240);
  if('next_action_at' in payload)changes.next_action_at=safeDateTime(payload.next_action_at);
  if('closed_at' in payload)changes.closed_at=safeDateTime(payload.closed_at);
  for(const key of ['offered_value_cents','negotiated_value_cents','closed_value_cents'])if(key in payload)changes[key]=moneyCents(payload[key]);
  if('whatsapp_status' in payload){const status=s(payload.whatsapp_status||'pending').trim().toLowerCase();if(!['pending','confirmed','not_found','invalid'].includes(status))throw new ApiError(400,'Situação do WhatsApp inválida');changes.whatsapp_status=status;changes.whatsapp_checked_at=status==='pending'?null:now();}
  if('whatsapp_phone' in payload){const phone=s(payload.whatsapp_phone).replace(/\D/g,'');if(phone&&![12,13].includes(phone.length))throw new ApiError(400,'Número normalizado do WhatsApp inválido');changes.whatsapp_phone=phone;}
  if(!Object.keys(changes).length)throw new ApiError(400,'Nenhuma alteração válida');return changes;
}

async function templates(request:Request,db:D1Database,principal:Principal,url:URL):Promise<Response> {
  const templateId=url.pathname.startsWith('/api/message-templates/')?decodeURIComponent(url.pathname.slice('/api/message-templates/'.length)):'';
  const selectedOwner=principal.accountId;
  if(request.method==='GET'&&!templateId) {
    const at=now();await db.batch([db.prepare(`INSERT INTO message_templates(id,owner_id,name,body,is_default,created_at,updated_at)
      SELECT ?,?,'Apresentação inicial',?,1,?,? WHERE NOT EXISTS (SELECT 1 FROM message_templates WHERE owner_id=?)`)
      .bind(id('mensagem-'),selectedOwner,'Olá! Tudo bem? Meu nome é {vendedor}. Encontrei a {empresa} e gostaria de conversar sobre uma oportunidade. Posso te explicar rapidamente?',at,at,selectedOwner)]);
    return json({items:await queryRows(db,'SELECT id,name,body,is_default,created_at,updated_at FROM message_templates WHERE owner_id=? ORDER BY is_default DESC,name COLLATE NOCASE',[selectedOwner])});
  }
  if(request.method==='DELETE'&&templateId) {
    const current=await queryFirst(db,'SELECT * FROM message_templates WHERE id=? AND owner_id=?',[templateId,selectedOwner]);if(!current)throw new ApiError(404,'Modelo de mensagem não encontrado');
    const results=await db.batch([
      db.prepare('DELETE FROM message_templates WHERE id=? AND owner_id=? AND (SELECT COUNT(*) FROM message_templates WHERE owner_id=?)>1').bind(templateId,selectedOwner,selectedOwner),
      db.prepare(`UPDATE message_templates SET is_default=1 WHERE id=(SELECT id FROM message_templates WHERE owner_id=? ORDER BY updated_at DESC,name COLLATE NOCASE LIMIT 1)
        AND NOT EXISTS (SELECT 1 FROM message_templates WHERE owner_id=? AND is_default=1)`).bind(selectedOwner,selectedOwner),
    ]);
    if(!results[0].meta.changes)throw new ApiError(400,'Mantenha ao menos um modelo de mensagem');return json({excluido:true});
  }
  if((request.method==='POST'&&!templateId)||(['PUT','PATCH'].includes(request.method)&&templateId)) {
    const payload=await bodyJson(request,16384),current=templateId?await queryFirst(db,'SELECT * FROM message_templates WHERE id=? AND owner_id=?',[templateId,selectedOwner]):null;
    if(templateId&&!current)throw new ApiError(404,'Modelo de mensagem não encontrado');
    const name=s(payload.name??current?.name).trim().slice(0,60),body=s(payload.body??current?.body).trim().slice(0,2000);
    if(!name)throw new ApiError(400,'Informe o nome do modelo');if(!body)throw new ApiError(400,'Informe a mensagem do modelo');
    const at=now(),identifier=templateId||id('mensagem-');
    const wantsDefault=Boolean(payload.is_default??current?.is_default)||Boolean(current?.is_default);
    const isDefault=wantsDefault?1:0;
    try {
      const results=await db.batch([
        ...(templateId?[db.prepare('UPDATE message_templates SET name=?,body=?,is_default=?,updated_at=? WHERE id=? AND owner_id=?').bind(name,body,isDefault,at,identifier,selectedOwner)]:[
          db.prepare('INSERT INTO message_templates(id,owner_id,name,body,is_default,created_at,updated_at) VALUES(?,?,?,?,CASE WHEN ?=1 OR NOT EXISTS(SELECT 1 FROM message_templates WHERE owner_id=?) THEN 1 ELSE 0 END,?,?)').bind(identifier,selectedOwner,name,body,isDefault,selectedOwner,at,at)]),
        db.prepare('UPDATE message_templates SET is_default=0 WHERE owner_id=? AND id<>? AND EXISTS(SELECT 1 FROM message_templates WHERE id=? AND owner_id=? AND is_default=1)').bind(selectedOwner,identifier,identifier,selectedOwner),
      ]);
      if(!results[0].meta.changes)throw new ApiError(404,'Modelo de mensagem não encontrado');
    }catch(error){if(/UNIQUE constraint failed/i.test(s(error)))throw new ApiError(409,'Já existe um modelo com este nome');throw error;}
    const saved=await queryFirst(db,'SELECT is_default FROM message_templates WHERE id=? AND owner_id=?',[identifier,selectedOwner]);
    return json({id:identifier,name,body,is_default:saved?.is_default??isDefault,...(!templateId?{created_at:at}:{}),updated_at:at},templateId?200:201);
  }
  throw new ApiError(405,'Método não permitido');
}

async function teamList(db:D1Database,principal:Principal,url:URL,csv=false):Promise<Response> {
  const p=url.searchParams,profileId=(p.get('profile_id')||'').trim();if(!profileId)throw new ApiError(400,'Selecione um perfil individual');
  const profile=await requireProfile(db,profileId,principal),view=p.get('view')==='favorites'?'favorites':'all',status=(p.get('status')||'').toLowerCase();
  if(status&&!Object.hasOwn(STAGES,status))throw new ApiError(400,'Etapa inválida');
  const focus=['all','overdue','today','no_action','uncontacted','negotiation','stalled'].includes(p.get('focus')||'')?p.get('focus')!:'all';
  const sort=['priority','deadline','recent','value'].includes(p.get('sort')||'')?p.get('sort')!:'priority';
  const search=(p.get('q')||'').trim().slice(0,120),page=positiveInt(p.get('page'),1),size=positiveInt(p.get('size'),24,100);
  const whatsapp=(p.get('whatsapp')||'').toLowerCase();if(whatsapp&&!['pending','confirmed','not_found','invalid'].includes(whatsapp))throw new ApiError(400,'Situação do WhatsApp inválida');
  const [from,to]=dateRange(p),where=['spl.profile_id=?'],values:unknown[]=[profileId];
  if(view==='favorites')where.push('spl.favorito=1');if(status){where.push('spl.lead_status=?');values.push(status);}
  if(whatsapp){where.push("COALESCE(NULLIF(spl.whatsapp_status,''),'pending')=?");values.push(whatsapp);}
  if(csv)where.push('NOT EXISTS (SELECT 1 FROM contact_suppression cs JOIN sales_profiles cp ON cp.owner_id=cs.owner_id WHERE cp.id=spl.profile_id AND cs.cnpj=spl.cnpj)');
  else {
    if(from||to){const dates=['h.profile_id=spl.profile_id','h.cnpj=spl.cnpj'];if(from){dates.push('date(h.created_at)>=?');values.push(from);}if(to){dates.push('date(h.created_at)<=?');values.push(to);}where.push('EXISTS(SELECT 1 FROM sales_lead_history h WHERE '+dates.join(' AND ')+')');}
    const active="spl.lead_status NOT IN ('convertido','descartado','concluido')";
    const at=now(),today=at.slice(0,10);
    if(focus==='overdue'){where.push('datetime(spl.next_action_at)<datetime(?) AND '+active);values.push(at);}
    else if(focus==='today'){where.push('date(spl.next_action_at)=? AND '+active);values.push(today);}
    else if(focus==='no_action')where.push("(spl.next_action_at IS NULL OR TRIM(COALESCE(spl.next_action,''))='') AND "+active);
    else if(focus==='uncontacted')where.push('spl.first_contact_at IS NULL AND '+active);
    else if(focus==='negotiation')where.push("spl.lead_status='negociacao'");
    else if(focus==='stalled'){where.push("spl.lead_status='negociacao' AND datetime(COALESCE(spl.last_contact_at,spl.updated_at))<datetime(?,?)");values.push(at,'-'+(await settings(db,profileId)).stalled_days+' days');}
    if(search){const digits=search.replace(/\D/g,''),term='%'+search.toLowerCase()+'%',parts=["LOWER(COALESCE(c.nome_fantasia,'')) LIKE ?","LOWER(COALESCE(c.razao_social,'')) LIKE ?",'c.cnpj LIKE ?'];values.push(term,term,'%'+(digits||search)+'%');
      if(digits&&!/[A-Za-zÀ-ÿ]/.test(search))for(const col of ['c.telefone','spl.whatsapp_phone']){let norm=`COALESCE(${col},'')`;for(const separator of [' ','+','-','(',')','.','/','\t','\u00a0'])norm=`REPLACE(${norm},'${separator}','')`;parts.push(norm+' LIKE ?');values.push('%'+digits+'%');}where.push('('+parts.join(' OR ')+')');}
  }
  const condition=where.join(' AND '),active="spl.lead_status NOT IN ('convertido','descartado','concluido')";
  const order:Record<string,string>={deadline:'CASE WHEN spl.next_action_at IS NULL THEN 1 ELSE 0 END,datetime(spl.next_action_at),spl.updated_at DESC',recent:'spl.updated_at DESC,c.data_abertura DESC,c.id DESC',value:'spl.negotiated_value_cents DESC,spl.offered_value_cents DESC,spl.updated_at DESC',
    priority:`CASE WHEN datetime(spl.next_action_at)<datetime(?) AND ${active} THEN 0 WHEN date(spl.next_action_at)=? AND ${active} THEN 1 WHEN spl.first_contact_at IS NULL AND ${active} THEN 2 WHEN spl.lead_status='negociacao' THEN 3 ELSE 4 END,spl.favorito DESC,spl.updated_at DESC`};
  const orderValues=sort==='priority'&&!csv?[now(),now().slice(0,10)]:[];
  const count=await queryFirst(db,`SELECT COUNT(*) AS total FROM accessible_sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj WHERE ${condition}`,values);
  const items=await queryRows<Lead>(db,joined+` WHERE ${condition} ORDER BY ${csv?'spl.favorito DESC,spl.updated_at DESC,c.data_abertura DESC':order[sort]}`+(csv?'':' LIMIT ? OFFSET ?'),[...values,...orderValues,...(csv?[]:[size,(page-1)*size])]);
  const blocked=await suppressions(db,owner(profile,principal)),presented=items.map(x=>present(x,blocked));
  if(csv)return csvResponse(profile,p,presented);
  return json({profile,items:presented,total:count?.total||0,page,size,view,status,focus,sort,q:search});
}
function csvResponse(profile:Row,p:URLSearchParams,items:Row[]):Response {
  const text=(key:string)=>(x:Row)=>x[key]??'';
  const whatsapp:Record<string,string>={pending:'Pendente',confirmed:'Confirmado',not_found:'Não localizado',invalid:'Inválido'};
  const fields:Record<string,[string,(row:Row)=>unknown]>={empresa:['Empresa',x=>x.nome_fantasia||x.razao_social||''],razao_social:['Razão social',text('razao_social')],cnpj:['CNPJ',text('cnpj')],telefone:['Telefone original',text('telefone')],
    whatsapp_phone:['Telefone WhatsApp',x=>x.profile_whatsapp_phone||x.telefone||''],whatsapp_status:['Situação WhatsApp',x=>whatsapp[s(x.profile_whatsapp_status)]||'Pendente'],email:['E-mail',text('email')],municipio:['Município',text('municipio')],regiao:['Região',text('regiao')],segmento:['Segmento',text('segmento')],
    cnae:['CNAE',text('cnae')],cnae_descricao:['Descrição do CNAE',text('cnae_descricao')],data_abertura:['Data de abertura',text('data_abertura')],situacao:['Situação cadastral',text('situacao')],potencial:['Potencial',text('lead_score')],favorito:['Favorito',x=>x.profile_favorito?'Sim':'Não'],
    etapa:['Etapa',x=>STAGES[s(x.profile_lead_status)]||s(x.profile_lead_status)],resultado:['Resultado do contato',x=>OUTCOMES[s(x.profile_contact_outcome)]||s(x.profile_contact_outcome)],proxima_acao:['Próxima ação',text('profile_next_action')],data_proxima_acao:['Data da próxima ação',text('profile_next_action_at')],
    valor_ofertado:['Valor ofertado',x=>Number(x.profile_offered_value_cents||0)/100],valor_negociado:['Valor negociado',x=>Number(x.profile_negotiated_value_cents||0)/100],valor_fechado:['Valor fechado',x=>Number(x.profile_closed_value_cents||0)/100],observacoes:['Observações',text('profile_observacoes')],estrategia:['Estratégia',text('profile_estrategia')],
    campanha:['Campanha / ICP',text('profile_campaign')],persona:['Cargo / persona',text('profile_persona')],origem:['Origem do lead',text('profile_lead_origin')],motivo_perda:['Motivo de perda',x=>LOSSES[s(x.profile_loss_reason)]||'Não informado']};
  const requested=(p.get('fields')||'').split(',').filter(x=>Object.hasOwn(fields,x)),selected=requested.length?requested:['empresa','cnpj','telefone','whatsapp_phone','whatsapp_status','email','municipio','segmento','etapa','resultado','proxima_acao','data_proxima_acao','valor_negociado','valor_fechado'];
  const delimiter=p.get('delimiter')==='comma'?',':';';
  const cell=(v:unknown)=>{let value=s(v);if(typeof v==='string'&&(/^[\t\r\n]/.test(value)||/^[\s\u0000-\u001f]*[=+\-@]/.test(value)))value="'"+value;return /["\n\r]/.test(value)||value.includes(delimiter)?'"'+value.replace(/"/g,'""')+'"':value;};
  const rows=[selected.map(k=>fields[k][0]).map(cell).join(delimiter),...items.map(x=>selected.map(k=>cell(fields[k][1](x))).join(delimiter))];
  const safe=(value:string)=>value.replace(/[^\p{L}\p{N} _-]/gu,'').trim();
  const name=safe(p.get('filename')||'').slice(0,80)||'radar-'+(safe(s(profile.name))||'perfil').toLowerCase().replace(/ /g,'-')+'-leads';
  // RFC 5987 supports accents without allowing header injection.
  return new Response('\ufeff'+rows.join('\n')+'\n',{headers:headers({'Content-Type':'text/csv; charset=utf-8','Content-Disposition':`attachment; filename="radar-leads.csv"; filename*=UTF-8''${encodeURIComponent(name+'.csv')}`,'Cache-Control':'no-store'})});
}

async function teamDashboard(db:D1Database,profile:Row,principal:Principal):Promise<Response> {
  const {items}=await portfolio(db,profile,principal),active=items.filter(x=>!terminal(x)),at=time(now())!,today=now().slice(0,10);
  const intervals=(field:'first_contact_at'|'closed_at',rows:Lead[])=>rows.flatMap(x=>{const a=time(x.added_at),b=time(x[field]);return a!==null&&b!==null&&b>=a?[(b-a)/86400000]:[];});
  const first=intervals('first_contact_at',items),closing=intervals('closed_at',items.filter(x=>x.lead_status==='convertido'));
  const average=(xs:number[])=>xs.length?Math.round(xs.reduce((a,b)=>a+b,0)/xs.length*10)/10:null;
  const contacted=items.filter(x=>x.first_contact_at).length;
  const summary={total:items.length,active:active.length,contacted,uncontacted:active.filter(x=>!x.first_contact_at).length,overdue:active.filter(x=>time(x.next_action_at)!==null&&time(x.next_action_at)!<at).length,
    due_today:active.filter(x=>x.next_action_at?.slice(0,10)===today).length,without_next_action:active.filter(x=>!x.next_action_at||!x.next_action.trim()).length,negotiation_count:items.filter(x=>x.lead_status==='negociacao').length,
    whatsapp_confirmed:items.filter(x=>x.whatsapp_status==='confirmed').length,whatsapp_not_found:items.filter(x=>x.whatsapp_status==='not_found').length,whatsapp_invalid:items.filter(x=>x.whatsapp_status==='invalid').length,whatsapp_pending:items.filter(x=>!x.whatsapp_status||x.whatsapp_status==='pending').length,
    offered_value_cents:active.reduce((a,x)=>a+x.offered_value_cents,0),negotiated_value_cents:active.reduce((a,x)=>a+x.negotiated_value_cents,0),closed_value_cents:items.filter(x=>x.lead_status==='convertido').reduce((a,x)=>a+x.closed_value_cents,0),avg_first_contact_days:average(first),avg_close_days:average(closing),contact_rate:Math.round(contacted*1000/(items.length||1))/10};
  const stages=Object.keys(STAGES).flatMap(key=>{const rows=items.filter(x=>x.lead_status===key);return rows.length?[{key,total:rows.length,negotiated_value_cents:rows.reduce((a,x)=>a+x.negotiated_value_cents,0),closed_value_cents:rows.reduce((a,x)=>a+x.closed_value_cents,0)}]:[];}).sort((a,b)=>b.total-a.total);
  const grouped=new Map<string,number>();for(const x of items){const key=x.contact_outcome||'nao_informado';grouped.set(key,(grouped.get(key)||0)+1);}
  return json({profile,summary,stages,outcomes:[...grouped].map(([key,total])=>({key,total})).sort((a,b)=>b.total-a.total)});
}

async function opsWrite(request:Request,db:D1Database,principal:Principal,path:string):Promise<Response> {
  const payload=await bodyJson(request,8192),profileId=s(payload.profile_id),profile=await requireProfile(db,profileId,principal),selectedOwner=owner(profile,principal);
  if(path==='/api/sales-ops/targets') {
    const month=s(payload.month);if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)||month.startsWith('0000'))throw new ApiError(400,'Mês inválido');
    const values=['revenue_cents','contacts','wins'].map(k=>payload[k]??0);if(values.some(v=>typeof v!=='number'||!Number.isInteger(v)||v<0||v>100000000000))throw new ApiError(400,'Metas devem ser números não negativos');
    const permitted=scope(principal);
    const result=await db.batch([db.prepare(`INSERT INTO sales_monthly_targets(profile_id,month,revenue_cents,contacts,wins,updated_at) SELECT ?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM sales_profiles p WHERE p.id=? AND ${permitted.sql}) ON CONFLICT(profile_id,month) DO UPDATE SET revenue_cents=excluded.revenue_cents,contacts=excluded.contacts,wins=excluded.wins,updated_at=excluded.updated_at`).bind(profileId,month,...values,now(),profileId,...permitted.values)]);
    if(!result[0].meta.changes)throw new ApiError(409,'Responsável alterado em outra sessão');
    return json({saved:true});
  }
  const cnpj=s(payload.cnpj),current=await readLead(db,profileId,cnpj),at=stamp();
  if(path==='/api/sales-ops/suppression') {
    const active=payload.blocked,reason=payload.reason??'';if(typeof active!=='boolean'||typeof reason!=='string'||reason.length>500)throw new ApiError(400,'Informe motivo de até 500 caracteres');
    if(active&&!reason.trim())throw new ApiError(400,'Informe o motivo do bloqueio');if(!active&&payload.confirm_restore!==true)throw new ApiError(400,'Confirme que tem autorização para retomar o contato');
    const permitted=scope(principal),guard=`EXISTS (SELECT 1 FROM accessible_sales_profile_leads a JOIN sales_profiles p ON p.id=a.profile_id WHERE a.profile_id=? AND a.cnpj=? AND ${permitted.sql})`,values=[profileId,cnpj,...permitted.values];
    const result=await db.batch([
      active?db.prepare(`INSERT INTO contact_suppression(owner_id,cnpj,reason,updated_at) SELECT ?,?,?,? WHERE ${guard} ON CONFLICT(owner_id,cnpj) DO UPDATE SET reason=excluded.reason,updated_at=excluded.updated_at`).bind(selectedOwner,cnpj,reason.trim(),at,...values):
        db.prepare(`DELETE FROM contact_suppression WHERE owner_id=? AND cnpj=? AND ${guard}`).bind(selectedOwner,cnpj,...values),
      historyStatement(db,profileId,cnpj,{type:'contact_permission',title:active?'Não contatar':'Contato reautorizado',details:reason.trim()},at,guard,values),
    ]);
    if(active&&!result[0].meta.changes)throw new ApiError(404,'Lead não encontrado');return json({saved:true,blocked:active});
  }
  if(path==='/api/sales-ops/contact'&&await queryFirst(db,'SELECT 1 FROM contact_suppression WHERE owner_id=? AND cnpj=?',[selectedOwner,cnpj]))throw new ApiError(403,'Contato bloqueado nesta conta. Revise a autorização antes de reativar.');
  const revision=await leadRevision(current);if(payload.revision!==revision)throw new ApiError(409,path.endsWith('/complete')?'Lead alterado em outra sessão. Atualize antes de concluir.':'Lead alterado em outra sessão. Atualize a agenda antes de salvar.');
  if(terminal(current))throw new ApiError(400,path.endsWith('/complete')?'Lead já encerrado. Reabra pela ficha se necessário.':'Atendimento encerrado. Reabra a oportunidade na ficha antes de registrar contato.');
  const action=payload.next_action??'',rawDue=payload.next_action_at??'',note=payload.notes??'';
  if(path==='/api/sales-ops/contact') {
    const outcome=s(payload.outcome);if(!outcome||!Object.hasOwn(OUTCOMES,outcome))throw new ApiError(400,'Selecione o resultado do contato');
    if(typeof action!=='string'||action.length>500||typeof note!=='string'||note.length>1000)throw new ApiError(400,'Próxima ação: até 500 caracteres. Nota: até 1000.');
    if(Boolean(action.trim())!==Boolean(rawDue))throw new ApiError(400,'Preencha a próxima ação e sua data, ou deixe ambos vazios.');
    const due=safeDateTime(rawDue,'seconds');if(due&&(Number(due.slice(0,4))<2000||Number(due.slice(0,4))>2100))throw new ApiError(400,'Data de retorno inválida');
    const changes:Row={contact_outcome:outcome,last_contact_at:at,first_contact_at:current.first_contact_at||at,next_action:action.trim(),next_action_at:due,updated_at:at};
    if(['novo','qualificado'].includes(current.lead_status))changes.lead_status='contatado';
    await mutateLead(db,principal,profile,current,changes,[{type:'contact_recorded',title:'Contato registrado',details:JSON.stringify({outcome,note,next_action:action,due:due||''})}],true);
    return json({saved:true,created_at:at});
  }
  if(path==='/api/sales-ops/complete') {
    const mode=payload.mode??'lead';if(!['action','lead'].includes(s(mode))||typeof note!=='string'||note.trim().length<2||note.trim().length>1000)throw new ApiError(400,'Descreva a ação realizada (2 a 1000 caracteres).');
    if(typeof action!=='string'||action.length>500||typeof rawDue!=='string')throw new ApiError(400,'Próxima ação inválida');
    if(mode==='lead'&&(action.trim()||rawDue))throw new ApiError(400,'Para dar baixa, deixe o próximo retorno vazio.');
    if(Boolean(action.trim())!==Boolean(rawDue))throw new ApiError(400,'Informe a próxima ação e sua data, ou deixe ambos vazios.');
    const due=safeDateTime(rawDue,'seconds');if(due&&(time(due)!<=time(now())!||Number(due.slice(0,4))>2100))throw new ApiError(400,'Escolha uma data futura para o novo retorno.');
    const changes:Row={next_action:action.trim(),next_action_at:due,updated_at:at};if(mode==='lead')changes.lead_status='concluido';
    await mutateLead(db,principal,profile,current,changes,[{type:mode==='lead'?'lead_completed':'action_completed',title:mode==='lead'?'Lead concluído · baixa':'Pendência concluída',details:JSON.stringify({note:note.trim(),completed_action:current.next_action,previous_due:current.next_action_at,next_action:action.trim(),due:due||''})}]);
    return json({saved:true,completed:mode,created_at:at});
  }
  throw new ApiError(404,'Rota não encontrada');
}

export async function handleSales(request:Request,env:Env,principal:Principal,url:URL):Promise<Response|undefined> {
  const path=url.pathname,method=request.method,db=env.DB,p=url.searchParams;
  if(path==='/api/message-templates'||path.startsWith('/api/message-templates/'))return templates(request,db,principal,url);
  if(path.startsWith('/api/sales-ops/')) {if(method!=='POST')throw new ApiError(405,'Método não permitido');return opsWrite(request,db,principal,path);}
  if(method==='GET') {
    if(path==='/api/team-profiles') {
      const allowed=scope(principal);
      return json({items:await queryRows(db,`SELECT p.*,COUNT(spl.cnpj) AS lead_count,COALESCE(SUM(CASE WHEN spl.favorito=1 THEN 1 ELSE 0 END),0) AS favorite_count,MAX(spl.updated_at) AS last_activity FROM sales_profiles p LEFT JOIN accessible_sales_profile_leads spl ON spl.profile_id=p.id WHERE ${allowed.sql} GROUP BY p.id ORDER BY p.name COLLATE NOCASE`,allowed.values),can_manage_team:principal.role==='admin'});
    }
    if(path==='/api/team-leads'||path==='/api/team-leads.csv')return teamList(db,principal,url,path.endsWith('.csv'));
    if(path==='/api/team-dashboard') {const profileId=(p.get('profile_id')||'').trim();if(!profileId)throw new ApiError(400,'Selecione um responsável');return teamDashboard(db,await requireProfile(db,profileId,principal),principal);}
    if(path==='/api/team-memberships') {
      const cnpj=cleanCnpj(p.get('cnpj'));if(cnpj.length!==14)throw new ApiError(400,'CNPJ inválido');const allowed=scope(principal);
      const columns=mutableFields.map(k=>['next_action_at','last_contact_at','first_contact_at','closed_at','whatsapp_checked_at'].includes(k)?`spl.${k}`:`COALESCE(spl.${k},${['favorito','offered_value_cents','negotiated_value_cents','closed_value_cents'].includes(k)?'0':k==='lead_status'?"'novo'":k==='whatsapp_status'?"'pending'":"''"}) AS ${k}`);
      return json({items:await queryRows(db,`SELECT p.id,p.name,p.role,p.email,p.initials,p.color,CASE WHEN spl.cnpj IS NULL THEN 0 ELSE 1 END AS selected,${columns.join(',')},spl.updated_at FROM sales_profiles p LEFT JOIN accessible_sales_profile_leads spl ON spl.profile_id=p.id AND spl.cnpj=? WHERE ${allowed.sql} ORDER BY p.name COLLATE NOCASE`,[cnpj,...allowed.values])});
    }
    if(path==='/api/team-lead-history'||path==='/api/team-activity') {
      const profileId=s(p.get('profile_id')),profile=await requireProfile(db,profileId,principal);
      if(path==='/api/team-lead-history'){const cnpj=cleanCnpj(p.get('cnpj'));validateIdentity(profileId,cnpj);await readLead(db,s(profile.id),cnpj);return json({items:await queryRows(db,'SELECT id,event_type,title,details,created_at,changes_json FROM sales_lead_history WHERE profile_id=? AND cnpj=? ORDER BY created_at DESC,id DESC LIMIT 100',[profileId,cnpj])});}
      const [from,to]=dateRange(p),page=positiveInt(p.get('page'),1),where=['h.profile_id=?','EXISTS(SELECT 1 FROM accessible_sales_profile_leads a WHERE a.profile_id=h.profile_id AND a.cnpj=h.cnpj)'],values:unknown[]=[profileId];
      if(from){where.push('date(h.created_at)>=?');values.push(from);}if(to){where.push('date(h.created_at)<=?');values.push(to);}const condition=where.join(' AND ');
      const total=await queryFirst(db,`SELECT COUNT(*) AS total FROM sales_lead_history h WHERE ${condition}`,values);
      return json({items:await queryRows(db,`SELECT h.*,c.nome_fantasia,c.razao_social FROM sales_lead_history h JOIN companies c ON c.cnpj=h.cnpj WHERE ${condition} ORDER BY h.created_at DESC,h.id DESC LIMIT 50 OFFSET ?`,[...values,(page-1)*50]),total:total?.total||0,page});
    }
    if(['/api/commercial','/api/commercial-report.pdf','/api/commercial-archive','/api/sales-ops'].includes(path)) {
      const profileId=s(p.get('profile_id')),profile=await requireProfile(db,profileId,principal);
      if(path==='/api/commercial-archive')return json({items:await queryRows(db,`SELECT a.* FROM commercial_archive a WHERE a.profile_id=? AND NOT EXISTS (SELECT 1 FROM companies c WHERE c.cnpj=a.cnpj AND NOT ${privateCompanyVisible('c','?')}) ORDER BY a.id DESC LIMIT 100`,[profileId,owner(profile,principal)])});
      const {items,blocked}=await portfolio(db,profile,principal);
      if(path==='/api/sales-ops') {
        const events=await queryRows(db,"SELECT h.cnpj,h.event_type,h.created_at FROM sales_lead_history h JOIN accessible_sales_profile_leads a ON a.profile_id=h.profile_id AND a.cnpj=h.cnpj WHERE h.profile_id=? AND h.event_type IN ('contact_recorded','contact_outcome') ORDER BY h.created_at",[profileId]);
        const goal=await queryFirst(db,'SELECT * FROM sales_monthly_targets WHERE profile_id=? AND month=?',[profileId,p.get('month')||now().slice(0,7)]);
        return json(await operationsDashboard(items,events,blocked,goal||undefined,p.get('from')||'',p.get('to')||'',p.get('month')||''));
      }
      const [start,end]=dateRange(p),data=commercialAnalytics(items,await settings(db,profileId),start,end,(p.get('campaign')||'').slice(0,120));
      if(path.endsWith('.pdf')) {
        if(data.summary.total>10000)throw new ApiError(413,'Restrinja o período ou campanha para até 10 mil leads');
        const branding:Row={};for(const key of ['site_name','report_title','report_footer'])branding[key]=await parameter(db,key,'');
        const pdf=await commercialPdf(env,url.origin,s(profile.name),data,branding);
        return new Response(Uint8Array.from(pdf).buffer,{headers:headers({'Content-Type':'application/pdf','Content-Disposition':'attachment; filename="radar-relatorio-comercial.pdf"','Cache-Control':'no-store','Content-Length':String(pdf.length)})});
      }
      const {items:_,...response}=data;return json(response);
    }
  }
  if(method==='POST') {
    if(path==='/api/team-profiles') {
      const payload=await bodyJson(request,16384),name=s(payload.name).trim().slice(0,80),role=s(payload.role??'Vendedor').trim().slice(0,80)||'Vendedor',email=s(payload.email).trim().slice(0,160);if(!name)throw new ApiError(400,'Informe o nome do perfil');
      const initials=name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase().slice(0,2)||'R',profileId=id('usuario-'),at=now();
      await db.batch([db.prepare('INSERT INTO sales_profiles(id,name,role,email,initials,color,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)').bind(profileId,name,role,email,initials,'#b82043',principal.accountId,at,at)]);
      return json({id:profileId,name,role,email,initials,color:'#b82043',lead_count:0,favorite_count:0},201);
    }
    if(path==='/api/commercial-settings') {
      const payload=await bodyJson(request,4096),profileId=s(payload.profile_id);await requireProfile(db,profileId,principal);
      const hours=Number(payload.contact_sla_hours??48),days=Number(payload.stalled_days??7);if(!Number.isInteger(hours)||hours<1||hours>720||!Number.isInteger(days)||days<1||days>365)throw new ApiError(400,'Prazo: 1 a 720 horas; negociação parada: 1 a 365 dias');
      const allowed=scope(principal);const result=await db.batch([db.prepare(`INSERT INTO commercial_settings(profile_id,contact_sla_hours,stalled_days) SELECT ?,?,? WHERE EXISTS(SELECT 1 FROM sales_profiles p WHERE p.id=? AND ${allowed.sql}) ON CONFLICT(profile_id) DO UPDATE SET contact_sla_hours=excluded.contact_sla_hours,stalled_days=excluded.stalled_days`).bind(profileId,hours,days,profileId,...allowed.values)]);if(!result[0].meta.changes)throw new ApiError(409,'Responsável alterado em outra sessão');return json({saved:true});
    }
    if(path==='/api/team-leads/test') {
      if(await parameter(db,'test_leads',true)===false)throw new ApiError(403,'Leads de teste desativados pelo administrador');
      const payload=await bodyJson(request,16384),profileId=s(payload.profile_id).trim(),name=s(payload.name).trim().slice(0,100),phone=s(payload.phone).replace(/\D/g,'');
      if(!profileId||!name)throw new ApiError(400,'Perfil e nome são obrigatórios');if(![10,11,12,13].includes(phone.length))throw new ApiError(400,'Informe um telefone brasileiro válido');
      const profile=await requireProfile(db,profileId,principal),cnpj='999'+String(BigInt('0x'+crypto.randomUUID().replace(/-/g,''))%100000000000n).padStart(11,'0'),at=now(),allowed=scope(principal),guard=`EXISTS(SELECT 1 FROM sales_profiles p WHERE p.id=? AND ${allowed.sql})`,values=[profileId,...allowed.values];
      const results=await db.batch([
        db.prepare(`INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,cnae_descricao,segmento,municipio,regiao,uf,telefone,porte,mei,data_source) SELECT ?,?,?,'TESTE',?,'0000000','Lead fictício para teste','Teste interno','Teste local','Demonstração','ZZ',?,'TESTE',0,'Lead de teste local' WHERE ${guard}`).bind(cnpj,name,name,now().slice(0,10),phone,...values),
        db.prepare('INSERT INTO private_companies(cnpj,owner_id) SELECT ?,? WHERE EXISTS(SELECT 1 FROM companies WHERE cnpj=?)').bind(cnpj,owner(profile,principal),cnpj),
        db.prepare(`INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,favorito) SELECT ?,?,?,?,1 WHERE ${guard} AND EXISTS(SELECT 1 FROM companies WHERE cnpj=?)`).bind(profileId,cnpj,at,at,...values,cnpj),
        historyStatement(db,profileId,cnpj,{type:'created',title:'Lead de teste incluído no painel',details:'Registro fictício local para validar o fluxo comercial.'},at,'EXISTS(SELECT 1 FROM accessible_sales_profile_leads WHERE profile_id=? AND cnpj=?)',[profileId,cnpj]),
        db.prepare('UPDATE sales_profiles SET updated_at=? WHERE id=? AND EXISTS(SELECT 1 FROM accessible_sales_profile_leads WHERE profile_id=? AND cnpj=?)').bind(at,profileId,profileId,cnpj),
      ]);if(!results[2].meta.changes)throw new ApiError(409,'Responsável alterado em outra sessão');
      return json({cnpj,profile_id:profileId,name,phone},201);
    }
    if(path==='/api/team-leads') {
      const payload=await bodyJson(request,32768),profileId=s(payload.profile_id).trim(),cnpj=cleanCnpj(payload.cnpj);validateIdentity(profileId,cnpj);
      const profile=await requireProfile(db,profileId,principal),available=await queryFirst(db,`SELECT 1 FROM companies c WHERE c.cnpj=? AND ${privateCompanyVisible('c','?')}`,[cnpj,owner(profile,principal)]);if(!available)throw new ApiError(404,'Empresa não encontrada');
      const duplicateSql="SELECT 1 FROM accessible_sales_profile_leads WHERE cnpj=? AND profile_id<>? AND lead_status NOT IN ('convertido','descartado','concluido') LIMIT 1";
      const current=await queryFirst(db,'SELECT 1 FROM accessible_sales_profile_leads WHERE profile_id=? AND cnpj=?',[profileId,cnpj]);
      const duplicate=payload.allow_duplicate!==true&&!current&&await queryFirst(db,duplicateSql,[cnpj,profileId]);
      if(duplicate)return json({erro:'Esta empresa já está em outro atendimento ativo. Confirme antes de duplicar a abordagem.',duplicate:true},409);
      const at=stamp(),allowed=scope(principal);
      const insert=await db.batch([
        db.prepare(`INSERT OR IGNORE INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) SELECT ?,?,?,? WHERE EXISTS(SELECT 1 FROM sales_profiles p JOIN companies c ON c.cnpj=? WHERE p.id=? AND ${allowed.sql} AND ${privateCompanyVisible('c','p.owner_id')}) AND (?=1 OR NOT EXISTS(${duplicateSql}))`).bind(profileId,cnpj,at,at,cnpj,profileId,...allowed.values,payload.allow_duplicate===true||!!current?1:0,cnpj,profileId),
        historyStatement(db,profileId,cnpj,{type:'created',title:'Lead incluído no painel'},at,'changes()=1'),
        db.prepare(`UPDATE sales_profile_leads SET updated_at=? WHERE profile_id=? AND cnpj=? AND ${visibleMutation(principal,profile).sql}`).bind(at,profileId,cnpj,...visibleMutation(principal,profile).values),
        db.prepare('UPDATE sales_profiles SET updated_at=? WHERE id=? AND EXISTS(SELECT 1 FROM accessible_sales_profile_leads WHERE profile_id=? AND cnpj=?)').bind(at,profileId,profileId,cnpj),
      ]);
      if(!insert[0].meta.changes&&!current) {if(await queryFirst(db,duplicateSql,[cnpj,profileId]))return json({erro:'Esta empresa já está em outro atendimento ativo. Confirme antes de duplicar a abordagem.',duplicate:true},409);throw new ApiError(409,'Lead alterado em outra sessão. Atualize antes de continuar.');}
      const count=await queryFirst(db,'SELECT COUNT(*) AS total FROM accessible_sales_profile_leads WHERE profile_id=?',[profileId]);
      return json({adicionado:!!insert[0].meta.changes,profile_id:profileId,cnpj,lead_count:count?.total||0},insert[0].meta.changes?201:200);
    }
    if(path==='/api/team-lead-events') {
      const payload=await bodyJson(request,16384),profileId=s(payload.profile_id).trim(),cnpj=cleanCnpj(payload.cnpj);if(!profileId||cnpj.length!==14||payload.event_type!=='whatsapp_opened')throw new ApiError(400,'Evento inválido');
      const profile=await requireProfile(db,profileId,principal);await readLead(db,profileId,cnpj);const selectedOwner=owner(profile,principal),at=now(),allowed=scope(principal);
      const result=await db.batch([historyStatement(db,profileId,cnpj,{type:'whatsapp_opened',title:'Link do WhatsApp aberto (contato não confirmado)',details:s(payload.details).trim()},at,`EXISTS(SELECT 1 FROM accessible_sales_profile_leads a JOIN sales_profiles p ON p.id=a.profile_id WHERE a.profile_id=? AND a.cnpj=? AND ${allowed.sql}) AND NOT EXISTS(SELECT 1 FROM contact_suppression WHERE owner_id=? AND cnpj=?)`,[profileId,cnpj,...allowed.values,selectedOwner,cnpj])]);
      if(!result[0].meta.changes)throw new ApiError(403,'Não contatar: esta empresa está bloqueada nesta conta.');return json({registrado:true,created_at:at},201);
    }
  }
  if(['PUT','PATCH'].includes(method)&&path==='/api/team-leads') {
    const payload=await bodyJson(request,65536),profileId=s(payload.profile_id).trim(),cnpj=cleanCnpj(payload.cnpj);validateIdentity(profileId,cnpj);
    const changes=leadChanges(payload),profile=await requireProfile(db,profileId,principal),current=await readLead(db,profileId,cnpj);
    if('expected_updated_at' in payload&&payload.expected_updated_at!==current.updated_at)throw new ApiError(409,'Lead alterado em outra sessão. Sua edição não foi sobrescrita: reabra a ficha para revisar os dados atuais.');
    const at=stamp();changes.updated_at=at;if(changes.contact_outcome&&changes.contact_outcome!==current.contact_outcome){changes.last_contact_at=at;changes.first_contact_at=current.first_contact_at||at;}
    if(changes.lead_status==='convertido'&&current.lead_status!=='convertido')changes.closed_at=changes.closed_at||at;
    else if('lead_status' in changes&&changes.lead_status!=='convertido'&&current.lead_status==='convertido'&&!('closed_at' in changes))changes.closed_at=null;
    await mutateLead(db,principal,profile,current,changes,updateEvents(current,changes));
    return json(present(await readLead(db,profileId,cnpj),await suppressions(db,owner(profile,principal))));
  }
  if(method==='DELETE') {
    if(path==='/api/team-leads') {
      const profileId=s(p.get('profile_id')).trim(),cnpj=cleanCnpj(p.get('cnpj'));validateIdentity(profileId,cnpj);const profile=await requireProfile(db,profileId,principal);
      const current=await queryFirst<Lead>(db,joined+' WHERE spl.profile_id=? AND spl.cnpj=?',[profileId,cnpj]);if(!current)return json({removido:false,profile_id:profileId,cnpj});
      const permitted=visibleMutation(principal,profile),condition=`profile_id=? AND cnpj=? AND updated_at=? AND ${permitted.sql}`,values=[profileId,cnpj,current.updated_at,...permitted.values];
      const results=await db.batch([
        db.prepare(`INSERT INTO commercial_archive(profile_id,cnpj,company_name,removed_at,events_json) SELECT ?,?,?,?,
          (SELECT COALESCE(json_group_array(json(event)),'[]') FROM (SELECT json_object('id',id,'profile_id',profile_id,'cnpj',cnpj,'event_type',event_type,'title',title,'details',details,'created_at',created_at,'changes_json',changes_json) AS event FROM sales_lead_history WHERE profile_id=? AND cnpj=? ORDER BY id))
          WHERE EXISTS(SELECT 1 FROM sales_profile_leads WHERE ${condition})`).bind(profileId,cnpj,companyName(current),now(),profileId,cnpj,...values),
        db.prepare(`DELETE FROM sales_profile_leads WHERE ${condition}`).bind(...values),
      ]);if(!results[1].meta.changes)throw new ApiError(409,'Lead alterado em outra sessão. Atualize antes de remover.');return json({removido:true,profile_id:profileId,cnpj});
    }
    if(path.startsWith('/api/team-profiles/')) {
      const profileId=decodeURIComponent(path.slice('/api/team-profiles/'.length));await requireProfile(db,profileId,principal);const allowed=scope(principal,'sales_profiles');
      await db.batch([db.prepare(`DELETE FROM sales_profiles WHERE id=? AND ${allowed.sql}`).bind(profileId,...allowed.values)]);return json({excluido:true});
    }
  }
  if(path.startsWith('/api/team-')||path.startsWith('/api/commercial'))throw new ApiError(405,'Método não permitido');
  return undefined;
}
