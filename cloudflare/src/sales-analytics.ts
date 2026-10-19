/** Deterministic commercial metrics over the selected seller's visible portfolio. */
import { ApiError, now, type Row } from './runtime';

export const STAGES: Record<string,string> = {novo:'Novo',qualificado:'Qualificado',contatado:'Contatado',negociacao:'Em negociação',convertido:'Convertido',descartado:'Descartado',concluido:'Concluído'};
export const OUTCOMES: Record<string,string> = {'':'Não informado',nao_respondeu:'Não respondeu',respondeu:'Respondeu',retornar:'Pediu retorno',sem_interesse:'Sem interesse',numero_invalido:'Número inválido',oportunidade:'Oportunidade aberta'};
export const LOSSES: Record<string,string> = {'':'Não informado',preco:'Preço',sem_interesse:'Sem interesse',sem_orcamento:'Sem orçamento',concorrente:'Concorrente',sem_resposta:'Sem resposta',fora_icp:'Fora do ICP',outro:'Outro'};
export interface Lead extends Row {
  profile_id:string; cnpj:string; added_at:string; updated_at:string; lead_status:string;
  favorito:number; observacoes:string; estrategia:string; contact_outcome:string; next_action:string;
  next_action_at:string|null; last_contact_at:string|null; first_contact_at:string|null; closed_at:string|null;
  offered_value_cents:number; negotiated_value_cents:number; closed_value_cents:number;
  whatsapp_status:string; whatsapp_phone:string; whatsapp_checked_at:string|null;
  campaign:string; persona:string; lead_origin:string; loss_reason:string;
  razao_social:string; nome_fantasia:string; telefone:string; segmento:string;
  do_not_contact?:boolean;
}
export const terminal=(lead:Lead)=>['convertido','descartado','concluido'].includes(lead.lead_status);
export const companyName=(lead:Lead)=>lead.nome_fantasia||lead.razao_social;
const day=86400000;
const pad=(v:number)=>String(v).padStart(2,'0');

/** Treat offset-free existing SQLite timestamps as São Paulo wall time. */
export function localTimestamp(value:unknown):string|null {
  const raw=String(value??'').trim();
  if(!/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(raw))return null;
  const calendar=new Date(raw.slice(0,10));
  if(raw.slice(0,4)==='0000'||!Number.isFinite(calendar.getTime())||calendar.toISOString().slice(0,10)!==raw.slice(0,10)||raw.length>10&&(Number(raw.slice(11,13))>23||Number(raw.slice(14,16))>59||raw.length>=19&&Number(raw.slice(17,19))>59))return null;
  const parsed=new Date(raw);
  if(!Number.isFinite(parsed.getTime()))return null;
  if(/(?:Z|[+-]\d{2}:\d{2})$/.test(raw)) {
    const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Sao_Paulo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(parsed);
    const at=(key:string)=>parts.find(p=>p.type===key)!.value;
    return `${at('year')}-${at('month')}-${at('day')}T${at('hour')}:${at('minute')}:${at('second')}`;
  }
  // Date.parse normalizes impossible dates. Reject those instead of inventing a date.
  if(parsed.toISOString().slice(0,10)!==raw.slice(0,10))return null;
  return raw.replace(' ','T');
}
export function time(value:unknown):number|null {
  const normalized=localTimestamp(value); if(!normalized)return null;
  const parsed=Date.parse(normalized); return Number.isFinite(parsed)?parsed:null;
}
export function dateOnly(value:string):boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)&&localTimestamp(value)===value;
}
export function dateRange(params:URLSearchParams,from='activity_from',to='activity_to'):[string,string] {
  const start=(params.get(from)||'').trim(), end=(params.get(to)||'').trim();
  if((start&&!dateOnly(start))||(end&&!dateOnly(end))||(start&&end&&start>end))throw new ApiError(400,'Período inválido');
  return [start,end];
}
export function safeDateTime(value:unknown,precision:'minutes'|'seconds'='minutes'):string|null {
  if(value===null||value===undefined||value==='')return null;
  const result=localTimestamp(value); if(!result)throw new ApiError(400,'Data e hora inválida');
  return (result.length===10?result+'T00:00:00':result+':00').slice(0,precision==='minutes'?16:19);
}
export function scoreCompany(row:Row):number {
  let score=(row.email?20:0)+(row.telefone?20:0)+(row.situacao==='ATIVA'?15:0)+(row.nome_fantasia?10:0)+(!row.mei?10:0);
  const opened=time(row.data_abertura),today=time(now().slice(0,10));
  if(opened!==null&&today!==null) {const age=(today-opened)/day;score+=age<=30?25:age<=90?15:age<=365?5:0;}
  return Math.min(score,100);
}
export function phoneQuality(value:unknown) {
  let digits=String(value??'').replace(/\D/g,'');
  if(digits.startsWith('55')&&[12,13].includes(digits.length))digits=digits.slice(2);
  const valid=[10,11].includes(digits.length)&&!['00','10','20'].includes(digits.slice(0,2))&&!digits.startsWith('0')&&new Set(digits).size>2&&(digits.length!==11||digits[2]==='9');
  return {format_valid:valid,mobile:valid&&digits.length===11,normalized:valid?'55'+digits:'',note:valid?'Formato plausível; existência no WhatsApp depende de confirmação humana.':'Telefone incompleto ou formato improvável.'};
}
const round1=(v:number)=>Math.round(v*10)/10;
export function metrics(items:Lead[],at=time(now())!) {
  const active=items.filter(x=>!terminal(x)&&!x.do_not_contact),won=items.filter(x=>x.lead_status==='convertido'),contacted=items.filter(x=>x.first_contact_at);
  const intervals=(rows:Lead[],field:'first_contact_at'|'closed_at',divisor:number)=>rows.flatMap(x=>{const start=time(x.added_at),end=time(x[field]);return start!==null&&end!==null&&end>=start?[(end-start)/divisor]:[];});
  const first=intervals(contacted,'first_contact_at',3600000),closing=intervals(won,'closed_at',day);
  return {total:items.length,active:active.length,contacted:contacted.length,won:won.length,conversion_pct:items.length?round1(100*won.length/items.length):0,
    offered_cents:active.reduce((a,x)=>a+(x.offered_value_cents||0),0),pipeline_cents:active.reduce((a,x)=>a+(x.negotiated_value_cents||0),0),closed_cents:won.reduce((a,x)=>a+(x.closed_value_cents||0),0),
    avg_first_contact_hours:first.length?round1(first.reduce((a,b)=>a+b,0)/first.length):null,avg_close_days:closing.length?round1(closing.reduce((a,b)=>a+b,0)/closing.length):null,
    first_contact_sample:first.length,closing_sample:closing.length,overdue:active.filter(x=>time(x.next_action_at)!==null&&time(x.next_action_at)!<at).length};
}
export function commercialAnalytics(all:Lead[],config:{contact_sla_hours:number;stalled_days:number},start='',end='',campaign='') {
  const items=all.filter(x=>(!start||x.added_at.slice(0,10)>=start)&&(!end||x.added_at.slice(0,10)<=end)&&(!campaign||x.campaign===campaign));
  const at=time(now())!,today=now().slice(0,10),active=items.filter(x=>!terminal(x)&&!x.do_not_contact);
  const queue=active.flatMap(x=>{
    const due=time(x.next_action_at),entered=time(x.added_at),touched=time(x.last_contact_at||x.updated_at),reasons:string[]=[];
    if(due!==null&&due<at)reasons.push('Retorno vencido');else if(x.next_action_at?.slice(0,10)===today)reasons.push('Contato de hoje');
    if(!x.first_contact_at)reasons.push(entered!==null&&at-entered>config.contact_sla_hours*3600000?'Primeiro contato fora do prazo':'Primeiro contato');
    if(x.lead_status==='negociacao'&&touched!==null&&at-touched>config.stalled_days*day)reasons.push('Negociação parada');
    if(due===null||!x.next_action.trim())reasons.push('Definir próxima ação');
    return reasons.length?[{cnpj:x.cnpj,company:companyName(x),reasons,stage:x.lead_status,due:x.next_action_at,phone:x.whatsapp_phone||x.telefone,
      priority:(reasons.includes('Retorno vencido')?100:0)+(reasons.includes('Negociação parada')?50:0)+(reasons.includes('Primeiro contato fora do prazo')?30:0)}]:[];
  }).sort((a,b)=>b.priority-a.priority||(a.due||'9999').localeCompare(b.due||'9999')||a.cnpj.localeCompare(b.cnpj));
  const breakdown:Record<string,Array<{label:string}&ReturnType<typeof metrics>>>={};
  for(const field of ['segmento','campaign','persona','lead_origin']) {
    const groups=new Map<string,Lead[]>();
    for(const item of items){const key=String(item[field]||'Não informado');if(!groups.has(key))groups.set(key,[]);groups.get(key)!.push(item);}
    breakdown[field]=[...groups].sort((a,b)=>b[1].length-a[1].length).map(([label,rows])=>({label,...metrics(rows,at)}));
  }
  const losses=new Map<string,number>();for(const item of items.filter(x=>x.lead_status==='descartado'))losses.set(item.loss_reason||'',(losses.get(item.loss_reason||'')||0)+1);
  const quality={invalid_phone:items.filter(x=>!phoneQuality(x.whatsapp_phone||x.telefone).format_valid).length,whatsapp_confirmed:items.filter(x=>x.whatsapp_status==='confirmed').length,
    whatsapp_pending:items.filter(x=>!x.whatsapp_status||x.whatsapp_status==='pending').length,missing_followup:active.filter(x=>!x.next_action_at||!x.next_action.trim()).length,
    missing_loss_reason:items.filter(x=>x.lead_status==='descartado'&&!x.loss_reason).length,unvalidated_public_data:items.filter(x=>!x.serpro_checked_at).length,
    won_without_positive_value:items.filter(x=>x.lead_status==='convertido'&&!x.closed_value_cents).length,active_without_positive_offer:active.filter(x=>!x.offered_value_cents).length};
  return {summary:metrics(items,at),settings:config,queue,breakdown,stages:Object.entries(STAGES).map(([key,label])=>({key,label,total:items.filter(x=>x.lead_status===key).length})),
    loss_reasons:[...losses].map(([key,total])=>({label:LOSSES[key]||key,total})),quality,items,period:{from:start,to:end,campaign,basis:'Data de entrada no painel'},
    metric_context:{conversion:'Convertidos / todos os leads deste recorte de entrada. Sem leads, 0% não indica desempenho.',
      money:'Pipeline soma negociados de leads ativos; receita soma valores fechados dos Convertidos. Campos antigos usam zero como padrão: não distinguem valor não preenchido de fechamento sem receita.',
      time:'Médias só usam datas válidas, posteriores à entrada. Sem amostra, aparece —; não zero dias.',stages:'Estoque atual por etapa, não retenção histórica. Contatos externos não vinculados ficam fora deste funil.'},generated_at:now()};
}
export function periodMetrics(items:Lead[],events:Row[],first:string,last:string) {
  const inside=(value:unknown)=>{const normalized=localTimestamp(value);return !!normalized&&normalized.slice(0,10)>=first&&normalized.slice(0,10)<=last;};
  const won=items.filter(x=>x.lead_status==='convertido'&&inside(x.closed_at)),entries=items.filter(x=>inside(x.added_at));
  const contacts=events.filter(x=>['contact_recorded','contact_outcome'].includes(String(x.event_type))&&inside(x.created_at));
  const revenue=won.reduce((a,x)=>a+(x.closed_value_cents||0),0);
  const quotient=won.length?Math.floor(revenue/won.length):0,remainder=won.length?revenue%won.length:0;
  const ticket=quotient+(remainder*2>won.length||remainder*2===won.length&&quotient%2===1?1:0);
  return {entries:entries.length,wins:won.length,closed_cents:revenue,contacts:contacts.length,contacted_leads:new Set(contacts.map(x=>x.cnpj)).size,ticket_cents:won.length?ticket:null,
    cohort_conversion_pct:metrics(entries).conversion_pct,wins_missing_date:items.filter(x=>x.lead_status==='convertido'&&time(x.closed_at)===null).length};
}
export async function leadRevision(row:Row):Promise<string> {
  // Match Python json.dumps(sort_keys=True, ensure_ascii=False)'s separators.
  const encoded='{'+Object.keys(row).sort().map(k=>JSON.stringify(k)+': '+JSON.stringify(row[k])).join(', ')+'}';
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(encoded));
  return [...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export async function operationsDashboard(items:Lead[],events:Row[],suppression:Map<string,string>,goal:Row|undefined,start='',end='',month='') {
  const at=time(now())!,today=now().slice(0,10);start=start||today.slice(0,7)+'-01';end=end||today;
  if(!dateOnly(start)||!dateOnly(end)||start>end||time(end)!-time(start)!>366*day)throw new ApiError(400,'Escolha um período de até 367 dias, com início antes do fim.');
  month=month||today.slice(0,7);if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)||month.startsWith('0000'))throw new ApiError(400,'Mês da meta inválido');
  const first=time(start)!,last=time(end)!,days=Math.round((last-first)/day)+1;
  const iso=(v:number)=>new Date(v).toISOString().slice(0,10);
  const counts:Record<string,number>={overdue:0,today:0,week:0,later:0,unscheduled:0,blocked:0};
  const agenda=[];
  for(const x of items) {
    if(suppression.has(x.cnpj)){counts.blocked++;continue;}if(terminal(x))continue;
    const due=time(x.next_action_at),bucket=due===null?'unscheduled':due<at?'overdue':x.next_action_at!.slice(0,10)===today?'today':due<time(today)!+8*day?'week':'later';
    counts[bucket]++;
    // Revision excludes derived analytics flags; it describes the underlying DB row.
    const {do_not_contact:_,...underlying}=x;
    agenda.push({cnpj:x.cnpj,company:companyName(x),stage:x.lead_status,outcome:x.contact_outcome||'',next_action:x.next_action||'',due:x.next_action_at||'',phone:x.whatsapp_phone||x.telefone||'',bucket,revision:await leadRevision(underlying)});
  }
  const order:Record<string,number>={overdue:0,today:1,week:2,unscheduled:3,later:4};
  agenda.sort((a,b)=>order[a.bucket]-order[b.bucket]||(a.due||'9999').localeCompare(b.due||'9999')||a.cnpj.localeCompare(b.cnpj));
  const [year,monthNumber]=month.split('-').map(Number),monthLast=`${year}-${pad(monthNumber)}-${pad(new Date(Date.UTC(year,monthNumber,0)).getUTCDate())}`;
  const trend=Array.from({length:days},(_,i)=>({date:iso(first+i*day),entries:0,contacts:0,wins:0,closed_cents:0}));
  const byDay=new Map(trend.map(x=>[x.date,x]));
  for(const x of items){const added=localTimestamp(x.added_at),closed=localTimestamp(x.closed_at);if(added&&byDay.has(added.slice(0,10)))byDay.get(added.slice(0,10))!.entries++;
    if(x.lead_status==='convertido'&&closed&&byDay.has(closed.slice(0,10))){const point=byDay.get(closed.slice(0,10))!;point.wins++;point.closed_cents+=x.closed_value_cents||0;}}
  for(const event of events){const stamp=localTimestamp(event.created_at);if(stamp&&byDay.has(stamp.slice(0,10)))byDay.get(stamp.slice(0,10))!.contacts++;}
  const visible=new Set(items.map(x=>x.cnpj));
  return {period:{from:start,to:end,days},current:periodMetrics(items,events,start,end),previous:periodMetrics(items,events,iso(first-days*day),iso(first-day)),
    previous_period:{from:iso(first-days*day),to:iso(first-day)},agenda,agenda_total:agenda.length,counts,targets:goal||{month,revenue_cents:0,contacts:0,wins:0},
    target_actual:periodMetrics(items,events,month+'-01',monthLast),trend,blocked_cnpjs:[...suppression.keys()].filter(x=>visible.has(x)).sort(),
    suppressed:items.filter(x=>suppression.has(x.cnpj)).map(x=>({cnpj:x.cnpj,company:companyName(x),reason:suppression.get(x.cnpj)})),
    definitions:{entries:'Leads incluídos no período, pela data de entrada.',closed:'Valores dos leads atualmente Convertidos, pela data de fechamento. Inclui leads que entraram antes do período.',
      contacts:'Contatos registrados e mudanças de resultado no histórico. Abrir um link de WhatsApp não comprova contato.',comparison:'Período anterior com a mesma quantidade de dias. Não é previsão.',
      legacy:'Registros antigos sem datas não são reconstruídos; reaberturas não representam receita contábil nem estornos.'}};
}

