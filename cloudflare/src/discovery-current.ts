import {ApiError,bodyJson,json,now,queryFirst,queryRows,type Env,type Principal,type Row} from './runtime';
import {assertSql,identifier,isConstraint,prospectFingerprint,PROSPECT_FIELDS,validateProspect} from './prospects-current';

type Category = [string,[string,string][]];
export const CATEGORIES:Record<string,Category>={
  restaurantes:['Restaurantes',[['amenity','restaurant']]],'fast-food':['Lanchonetes e fast-food',[['amenity','fast_food']]],cafeterias:['Cafeterias',[['amenity','cafe']]],padarias:['Padarias',[['shop','bakery']]],mercados:['Mercados e supermercados',[['shop','supermarket'],['shop','convenience']]],bares:['Bares e pubs',[['amenity','bar'],['amenity','pub']]],hospedagem:['Hotéis e pousadas',[['tourism','hotel'],['tourism','guest_house']]],moda:['Roupas e calçados',[['shop','clothes'],['shop','shoes']]],beleza:['Salões e beleza',[['shop','hairdresser'],['shop','beauty']]],farmacias:['Farmácias',[['amenity','pharmacy']]],clinicas:['Clínicas e consultórios',[['amenity','clinic'],['amenity','doctors']]],dentistas:['Dentistas',[['amenity','dentist']]],academias:['Academias',[['leisure','fitness_centre']]],pets:['Pet shops e veterinários',[['shop','pet'],['amenity','veterinary']]],auto:['Oficinas e autopeças',[['shop','car_repair'],['shop','car_parts']]],postos:['Postos de combustível',[['amenity','fuel']]],construcao:['Materiais de construção',[['shop','doityourself'],['shop','hardware']]],moveis:['Móveis e decoração',[['shop','furniture'],['shop','interior_decoration']]],tecnologia:['Informática e eletrônicos',[['shop','computer'],['shop','electronics']]],educacao:['Escolas e cursos',[['amenity','school'],['amenity','language_school']]],servicos:['Serviços profissionais',[['office','company'],['office','consulting']]],contabilidade:['Escritórios de contabilidade',[['office','accountant']]],imobiliarias:['Imobiliárias',[['office','estate_agent']]],industria:['Instalações industriais',[['man_made','works']]],agro:['Lojas agropecuárias',[['shop','agrarian']]],
};
const DEFAULT_TIMES=['08:00','13:00','17:00'];
const zoneFormatter=new Intl.DateTimeFormat('sv-SE',{timeZone:'America/Sao_Paulo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
export function saoPauloTime(ms=Date.now()):string {return zoneFormatter.format(new Date(ms)).replace(' ','T');}
/** Convert a wall-clock slot using the named zone, independently of the host's timezone. */
export function nextScheduled(times:string[],reference=Date.now()):string {
  const local=saoPauloTime(reference),day=Date.parse(local.slice(0,10)+'T00:00:00Z');
  for(let offset=0;offset<3;offset++)for(const time of [...times].sort()) {
    const wanted=Date.parse(new Date(day+offset*86400000).toISOString().slice(0,10)+'T'+time+':00Z');
    let candidate=wanted;
    for(let i=0;i<3;i++)candidate+=wanted-Date.parse(saoPauloTime(candidate)+'Z');
    if(candidate>reference)return saoPauloTime(candidate);
  }
  throw new ApiError(400,'Informe pelo menos um horário');
}
function decoded(value:unknown,fallback:unknown):any {try{return JSON.parse(String(value));}catch{return fallback;}}
function boolOption(raw:Row,key:string,fallback:boolean):number {
  const value=key in raw?raw[key]:fallback;
  if(value!==true&&value!==false&&value!==0&&value!==1)throw new ApiError(400,'Opção inválida: '+key);
  return Number(value);
}
export function validateCampaign(raw:Row):Row {
  const {name,city,category}=raw,frequency='frequency'in raw?raw.frequency:'manual';
  if(typeof name!=='string'||[...name.trim()].length<2||[...name.trim()].length>100)throw new ApiError(400,'Nome: 2 a 100 caracteres');
  if(typeof city!=='string'||!/^[\p{L}\p{N} .'-]{2,100}$/u.test(city.trim()))throw new ApiError(400,'Informe o município do RS');
  if(typeof category!=='string'||!Object.hasOwn(CATEGORIES,category))throw new ApiError(400,'Categoria não suportada');
  if(!['manual','daily','scheduled'].includes(String(frequency)))throw new ApiError(400,'Frequência inválida');
  const input='times'in raw?raw.times:(frequency==='scheduled'?DEFAULT_TIMES:[]);
  if(!Array.isArray(input)||input.length>3||input.some(v=>typeof v!=='string'||!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(v)))throw new ApiError(400,'Use até três horários no formato HH:MM');
  if(new Set(input).size!==input.length||(frequency==='scheduled'&&!input.length))throw new ApiError(400,'Escolha de um a três horários diferentes');
  const times=[...input].sort() as string[],minutes=(v:string)=>Number(v.slice(0,2))*60+Number(v.slice(3));
  if(times.some((t,i)=>i>0&&minutes(t)-minutes(times[i-1])<60))throw new ApiError(400,'Deixe pelo menos uma hora entre as rodadas');
  const icp='icp_label'in raw?raw.icp_label:'';
  if(typeof icp!=='string'||[...icp].length>120||/[\x00-\x1f]/.test(icp))throw new ApiError(400,'Perfil comercial: até 120 caracteres');
  return {name:name.trim(),city:city.trim(),category,frequency,times_json:JSON.stringify(times),icp_label:icp.trim(),active:boolOption(raw,'active',true),require_phone:boolOption(raw,'require_phone',false),require_website:boolOption(raw,'require_website',false),enrich_websites:boolOption(raw,'enrich_websites',false)};
}
interface Config {capture_enabled:boolean;capture_scheduler:boolean;enrichment_enabled:boolean;capture_runs_account:number;capture_runs_global:number;capture_sites:number;capture_osm_mode:string;}
async function config(db:D1Database):Promise<Config> {
  const result:Config={capture_enabled:true,capture_scheduler:true,enrichment_enabled:true,capture_runs_account:6,capture_runs_global:30,capture_sites:10,capture_osm_mode:'overpass'};
  const rows=await queryRows(db,"SELECT key,value FROM admin_parameters WHERE key IN ('capture_enabled','capture_scheduler','enrichment_enabled','capture_runs_account','capture_runs_global','capture_sites','capture_osm_mode')");
  for(const row of rows) {
    const k=String(row.key),v=decoded(row.value,null);
    if(['capture_enabled','capture_scheduler','enrichment_enabled'].includes(k)&&typeof v==='boolean')(result as unknown as Row)[k]=v;
    if(['capture_runs_account','capture_runs_global','capture_sites'].includes(k)&&Number.isInteger(v))(result as unknown as Row)[k]=Math.max(1,Math.min(k==='capture_runs_global'?30:k==='capture_sites'?10:6,Number(v)));
    if(k==='capture_osm_mode'&&typeof v==='string')result.capture_osm_mode=v;
  }
  return result;
}
async function saveCampaign(db:D1Database,owner:string,raw:Row,id?:string):Promise<string> {
  const value=validateCampaign(raw),stamp=now(),fields=Object.keys(value);
  let old:Row|null=null,next:unknown=null;
  if(id) {
    old=await queryFirst(db,'SELECT * FROM discovery_campaigns WHERE id=? AND owner_id=?',[id,owner]);
    if(!old)throw new ApiError(404,'Campanha não encontrada');
    if('revision'in raw&&(!Number.isInteger(raw.revision)||raw.revision!==old.revision))throw new ApiError(409,'Campanha alterada em outra sessão. Atualize antes de salvar.');
    const changed=old.frequency!==value.frequency||JSON.stringify(decoded(old.times_json,[]))!==value.times_json||old.active!==value.active;
    next=old.next_run_at||stamp;
    if(value.frequency==='scheduled'&&changed)next=nextScheduled(decoded(value.times_json,[]));
  }else {id=identifier();next=value.frequency==='scheduled'?nextScheduled(decoded(value.times_json,[])):value.frequency==='daily'?stamp:null;}
  if(!value.active||value.frequency==='manual')next=null;
  try {
    if(old)await db.batch([
      assertSql(db,'EXISTS(SELECT 1 FROM discovery_campaigns WHERE id=? AND owner_id=? AND revision=?)',[id,owner,old.revision]),
      db.prepare(`UPDATE discovery_campaigns SET ${fields.map(k=>k+'=?').join(',')},updated_at=?,next_run_at=?,revision=revision+1,cursor_json=CASE WHEN city<>? OR category<>? THEN '{}' ELSE cursor_json END WHERE id=? AND owner_id=?`).bind(...fields.map(k=>value[k]),stamp,next,value.city,value.category,id,owner),
    ]);
    else {
      const inserted=await db.prepare(`INSERT INTO discovery_campaigns(id,owner_id,${fields.join(',')},created_at,updated_at,next_run_at) SELECT ${Array(fields.length+5).fill('?').join(',')} WHERE (SELECT COUNT(*) FROM discovery_campaigns WHERE owner_id=?)<30`).bind(id,owner,...fields.map(k=>value[k]),stamp,stamp,next,owner).run();
      if(!inserted.meta.changes)throw new ApiError(400,'Limite de 30 campanhas por conta');
    }
  }catch(error){if(isConstraint(error))throw new ApiError(409,'Campanha alterada em outra sessão. Atualize antes de salvar.');throw error;}
  return id;
}
export function overpassQuery(city:string,category:string,cursors:Row={}):string {
  if(!Object.hasOwn(CATEGORIES,category))throw new ApiError(400,'Categoria não suportada');
  const groups:Record<string,string>={a:'[aáàâãä]',e:'[eéèêë]',i:'[iíìîï]',o:'[oóòôõö]',u:'[uúùûü]',c:'[cç]'};
  const plain=city.normalize('NFD').replace(/\p{M}/gu,'').toLowerCase();
  const pattern='^'+[...plain].map(c=>groups[c]??c.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('')+'$';
  const selectors=['node','way','relation'].flatMap(kind=>CATEGORIES[category][1].map(([key,value])=>`${kind}[${JSON.stringify(key)}=${JSON.stringify(value)}](area.city)(if:id()>${Number.isSafeInteger(cursors[kind])?Math.max(0,Number(cursors[kind])):0});`)).join('');
  return `[out:json][timeout:7];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.state;area["name"~${JSON.stringify(pattern)},i]["admin_level"="8"](area.state)->.city;(${selectors});out center tags 51;`;
}
async function boundedResponse(response:Response,max:number):Promise<string> {
  if(Number(response.headers.get('Content-Length')??0)>max){await response.body?.cancel();throw Error('oversize');}
  if(!response.body)throw Error('empty');
  const reader=response.body.getReader(),chunks:Uint8Array[]=[];let size=0;
  try {while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;if(size>max){await reader.cancel();throw Error('oversize');}chunks.push(part.value);}}finally{reader.releaseLock();}
  const bytes=new Uint8Array(size);let at=0;for(const c of chunks){bytes.set(c,at);at+=c.byteLength;}return new TextDecoder('utf-8',{fatal:true}).decode(bytes);
}
export async function fetchOsm(query:string):Promise<Row[]> {
  const endpoints=['https://overpass.private.coffee/api/interpreter','https://overpass-api.de/api/interpreter'];
  for(let i=0;i<endpoints.length;i++) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8500);
    try {
      const response=await fetch(endpoints[i],{method:'POST',redirect:'error',signal:controller.signal,headers:{'User-Agent':'RadarCNPJ/1.0 public-business-discovery','Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body:new URLSearchParams({data:query}).toString()});
      if(!response.ok){await response.body?.cancel();if(response.status===429||response.status<500)throw new ApiError(503,'OSM recusou a consulta; aguarde antes de tentar novamente.');throw Error('upstream');}
      const data:unknown=JSON.parse(await boundedResponse(response,4*1024*1024));
      if(!data||typeof data!=='object'||Array.isArray(data)||'remark'in data||!Array.isArray((data as Row).elements))throw Error('incomplete');
      const elements=(data as {elements:unknown[]}).elements;
      if(elements.length>51)throw Error('unexpected result limit');
      return elements.filter((r):r is Row=>!!r&&typeof r==='object'&&!Array.isArray(r));
    }catch(error){if(error instanceof ApiError||i===endpoints.length-1)throw error;}finally{clearTimeout(timer);}
  }
  throw Error('unavailable');
}
function clean(value:unknown,limit:number):string {return typeof value==='string'?[...value.replace(/[\x00-\x1f]/g,' ').trim()].slice(0,limit).join(''):'';}
interface SourceRecord {key:string;row:Record<string,string>;metadata:Row;}
export function osmRecords(elements:Row[],campaign:Row):SourceRecord[] {
  const output:SourceRecord[]=[];
  for(const element of elements.slice(0,50)) {
    if(!['node','way','relation'].includes(String(element.type))||!Number.isSafeInteger(element.id)||Number(element.id)<=0||!element.tags||typeof element.tags!=='object'||Array.isArray(element.tags))continue;
    const tags=element.tags as Row,name=clean(tags.name||tags.brand,180);if(!name)continue;
    const phone=clean(tags['contact:phone']||tags.phone,32);let website=clean(tags['contact:website']||tags.website,300),email=clean(tags['contact:email']||tags.email,180);
    if(website){if(!website.includes('://'))website='https://'+website;try{const u=new URL(website);if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password||website.length>300)website='';}catch{website='';}}
    if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))email='';
    if(campaign.require_phone&&!phone||campaign.require_website&&!website)continue;
    const key=element.type+'/'+element.id;
    output.push({key,row:validateProspect({name,company:name,phone,email,city:campaign.city,source:'OpenStreetMap',campaign:campaign.name,website,notes:'',cnpj:'',persona:''}),metadata:{source_url:'https://www.openstreetmap.org/'+key,collected_at:now(),category:CATEGORIES[String(campaign.category)][0],address:clean(['addr:street','addr:housenumber','addr:suburb'].map(k=>clean(tags[k],200)).join(' '),300),attribution:'© OpenStreetMap contributors · ODbL',source_backend:'Overpass público',enrichment_status:campaign.enrich_websites?'indisponível neste ambiente':'não solicitado',pages:[],socials:[]}});
  }
  return output;
}
function nextCursor(elements:Row[],prior:Row):Row {
  if(elements.length<51)return {_source:'overpass'};
  const cursor:Row={...prior,_source:'overpass'};
  for(const e of elements.slice(0,50))if(['node','way','relation'].includes(String(e.type))&&Number.isSafeInteger(e.id))cursor[String(e.type)]=Math.max(Number(cursor[String(e.type)]??0),Number(e.id));
  return cursor;
}
async function executeDiscovery(env:Env,campaign:Row,runId:string,cfg:Config):Promise<void> {
  const db=env.DB,owner=String(campaign.owner_id),started=Date.now();
  try {
    let cursor=decoded(campaign.cursor_json,{}) as Row;if(!cursor||typeof cursor!=='object'||Array.isArray(cursor)||cursor._source!=='overpass')cursor={};
    const query=overpassQuery(String(campaign.city),String(campaign.category),cursor),key='overpass|'+query;
    const cache=await queryFirst(db,'SELECT elements_json,fetched_at FROM discovery_cache WHERE query_key=? AND expires_at>?',[key,now()]);
    const elements=cache?decoded(cache.elements_json,null):await fetchOsm(query);
    if(!Array.isArray(elements)||elements.length>51||elements.some(v=>!v||typeof v!=='object'||Array.isArray(v)))throw Error('invalid cache');
    const rows=osmRecords(elements,campaign),stamp=now(),fetched=cache?String(cache.fetched_at):stamp;
    for(const row of rows)row.metadata.collected_at=fetched;
    const warning=campaign.enrich_websites&&cfg.enrichment_enabled?' Contatos do mapa preservados; enriquecimento dos sites indisponível no Cloudflare Worker.':'';
    const reason=String(campaign.city)+' · '+CATEGORIES[String(campaign.category)][0]+(campaign.icp_label?' · Perfil definido por você: '+campaign.icp_label:'');
    const records=await Promise.all(rows.map(async item=>({...item.row,id:identifier(),source_key:item.key,owner_id:owner,fingerprint:await prospectFingerprint(item.row),metadata_json:JSON.stringify(item.metadata),created_at:stamp,updated_at:stamp,reason:reason+' · '+(item.row.phone?'Telefone público disponível':'Sem telefone publicado')+' · '+(item.row.email?'E-mail público disponível':'Sem e-mail publicado')})));
    const payload=JSON.stringify(records),fields=['id','owner_id','fingerprint',...Object.keys(PROSPECT_FIELDS),'status','created_at','updated_at'];
    const guard=assertSql(db,"EXISTS(SELECT 1 FROM discovery_campaigns WHERE id=? AND owner_id=? AND active=1 AND revision=?) AND EXISTS(SELECT 1 FROM discovery_runs WHERE id=? AND owner_id=? AND status='executando') AND NOT EXISTS(SELECT 1 FROM user_accounts WHERE id=? AND is_active=0) AND NOT EXISTS(SELECT 1 FROM admin_parameters WHERE key='capture_enabled' AND json_extract(value,'$')=0)",[campaign.id,owner,campaign.revision,runId,owner,owner]);
    await db.batch([
      guard,
      db.prepare(`INSERT INTO prospect_inbox(${fields.join(',')}) SELECT ${fields.map(k=>`json_extract(j.value,'$.${k}')`).join(',')} FROM json_each(?) j WHERE NOT EXISTS(SELECT 1 FROM discovery_sources ds WHERE ds.owner_id=? AND ds.source_key=json_extract(j.value,'$.source_key')) ON CONFLICT(owner_id,fingerprint) DO NOTHING`).bind(payload,owner),
      db.prepare(`INSERT INTO discovery_recommendations(id,owner_id,prospect_id,campaign_id,run_id,reason,created_at) SELECT lower(hex(randomblob(16))),?,p.id,?,?,json_extract(j.value,'$.reason'),? FROM json_each(?) j JOIN prospect_inbox p ON p.id=json_extract(j.value,'$.id') AND p.owner_id=? WHERE 1 ON CONFLICT(owner_id,prospect_id) DO NOTHING`).bind(owner,campaign.id,runId,stamp,payload,owner),
      db.prepare(`INSERT INTO discovery_sources(owner_id,source_key,prospect_id,metadata_json,last_seen_at) SELECT ?,json_extract(j.value,'$.source_key'),COALESCE(ds.prospect_id,p.id),json_extract(j.value,'$.metadata_json'),? FROM json_each(?) j LEFT JOIN discovery_sources ds ON ds.owner_id=? AND ds.source_key=json_extract(j.value,'$.source_key') LEFT JOIN prospect_inbox p ON p.owner_id=? AND p.fingerprint=json_extract(j.value,'$.fingerprint') WHERE COALESCE(ds.prospect_id,p.id) IS NOT NULL ON CONFLICT(owner_id,source_key) DO UPDATE SET metadata_json=excluded.metadata_json,last_seen_at=excluded.last_seen_at`).bind(owner,stamp,payload,owner,owner),
      db.prepare('INSERT INTO discovery_cache(query_key,elements_json,fetched_at,expires_at) SELECT ?,?,?,? WHERE ?=0 ON CONFLICT(query_key) DO UPDATE SET elements_json=excluded.elements_json,fetched_at=excluded.fetched_at,expires_at=excluded.expires_at').bind(key,JSON.stringify(elements),fetched,saoPauloTime(started+86400000),cache?1:0),
      db.prepare(`INSERT INTO discovery_notifications(id,owner_id,run_id,campaign_id,added,created_at) SELECT ?,?,?,?,COUNT(*),? FROM discovery_recommendations WHERE run_id=? AND owner_id=? HAVING COUNT(*)>0 AND COALESCE((SELECT notifications_enabled FROM discovery_preferences WHERE owner_id=?),1)=1 ON CONFLICT(run_id) DO NOTHING`).bind(identifier(),owner,runId,campaign.id,stamp,runId,owner,owner),
      db.prepare('UPDATE discovery_campaigns SET cursor_json=? WHERE id=? AND owner_id=? AND revision=?').bind(JSON.stringify(nextCursor(elements,cursor)),campaign.id,owner,campaign.revision),
      db.prepare("UPDATE discovery_runs SET status=?,found=?,added=(SELECT COUNT(*) FROM discovery_recommendations WHERE run_id=? AND owner_id=?),duplicates=?-(SELECT COUNT(*) FROM discovery_recommendations WHERE run_id=? AND owner_id=?),enriched=0,finished_at=?,message=? WHERE id=? AND owner_id=?").bind(warning?'parcial':'concluido',rows.length,runId,owner,rows.length,runId,owner,stamp,`${rows.length} estabelecimentos com dados públicos encontrados. Conferência comercial necessária.`+(cache?' Consulta do mapa reutilizada do cache público de 24 horas.':'')+warning,runId,owner),
    ]);
  }catch(error) {
    const interrupted=isConstraint(error);
    await db.prepare('UPDATE discovery_runs SET status=?,finished_at=?,message=? WHERE id=? AND owner_id=? AND status=\'executando\'').bind(interrupted?'interrompido':'falhou',now(),interrupted?'Campanha pausada, editada ou conta desativada durante a coleta. Nenhum contato desta rodada foi gravado.':'Fonte pública indisponível ou resposta incompleta. Nenhum contato desta rodada foi gravado; tente novamente mais tarde.',runId,owner).run();
  }
}
interface BackgroundContext {waitUntil(promise:Promise<unknown>):void;}
async function startDiscovery(env:Env,owner:string,campaignId:string,context?:BackgroundContext,scheduledFor?:string):Promise<string> {
  const db=env.DB,cfg=await config(db),stamp=now(),cutoff=saoPauloTime(Date.now()-86400000);
  if(!cfg.capture_enabled)throw new ApiError(400,'Captação desativada pelo administrador');
  const campaign=await queryFirst(db,'SELECT * FROM discovery_campaigns WHERE id=? AND owner_id=?',[campaignId,owner]);
  if(!campaign)throw new ApiError(404,'Campanha não encontrada');
  if(!campaign.active)throw new ApiError(400,'Campanha pausada');
  if(scheduledFor&&(!cfg.capture_scheduler||campaign.frequency==='manual'||campaign.next_run_at!==scheduledFor||scheduledFor>stamp))throw new ApiError(400,'Agendamento alterado; coleta não iniciada');
  if(await queryFirst(db,'SELECT 1 AS ok FROM user_accounts WHERE id=? AND is_active=0',[owner]))throw new ApiError(400,'Conta desativada; campanha não iniciada');
  const usage=await queryFirst(db,"SELECT COUNT(*) AS global_count,COALESCE(SUM(owner_id=?),0) AS own_count,COALESCE(SUM(started_at>?),0) AS recent,COALESCE(SUM(status='executando' AND started_at>=?),0) AS running FROM discovery_runs WHERE started_at>=?",[owner,saoPauloTime(Date.now()-60000),saoPauloTime(Date.now()-120000),cutoff]);
  if(Number(usage?.running)>0)throw new ApiError(400,'Outra campanha está em execução; aguarde a conclusão');
  if(Number(usage?.recent)>0)throw new ApiError(400,'Aguarde um minuto entre consultas');
  if(Number(usage?.global_count)>=cfg.capture_runs_global)throw new ApiError(400,'Limite global de rodadas nas últimas 24 horas; aguarde');
  if(Number(usage?.own_count)>=cfg.capture_runs_account)throw new ApiError(400,'Limite de rodadas por conta nas últimas 24 horas');
  const runId=identifier(),schedule=campaign.frequency==='daily'?saoPauloTime(Date.now()+86400000):campaign.frequency==='scheduled'&&scheduledFor?nextScheduled(decoded(campaign.times_json,[])):campaign.next_run_at;
  const conditions=["EXISTS(SELECT 1 FROM discovery_campaigns WHERE id=? AND owner_id=? AND revision=? AND active=1)","NOT EXISTS(SELECT 1 FROM user_accounts WHERE id=? AND is_active=0)","NOT EXISTS(SELECT 1 FROM admin_parameters WHERE key='capture_enabled' AND json_extract(value,'$')=0)","NOT EXISTS(SELECT 1 FROM discovery_runs WHERE status='executando')",'NOT EXISTS(SELECT 1 FROM discovery_runs WHERE started_at>?)','(SELECT COUNT(*) FROM discovery_runs WHERE started_at>=?)<?','(SELECT COUNT(*) FROM discovery_runs WHERE owner_id=? AND started_at>=?)<?'];
  const values:unknown[]=[campaignId,owner,campaign.revision,owner,saoPauloTime(Date.now()-60000),cutoff,cfg.capture_runs_global,owner,cutoff,cfg.capture_runs_account];
  if(scheduledFor){conditions.push("EXISTS(SELECT 1 FROM discovery_campaigns WHERE id=? AND owner_id=? AND next_run_at=?) AND NOT EXISTS(SELECT 1 FROM admin_parameters WHERE key='capture_scheduler' AND json_extract(value,'$')=0)");values.push(campaignId,owner,scheduledFor);}
  try {await db.batch([
    db.prepare("UPDATE discovery_runs SET status='interrompido',finished_at=?,message='Execução anterior não concluída no prazo; tente novamente.' WHERE status='executando' AND started_at<?").bind(stamp,saoPauloTime(Date.now()-120000)),
    assertSql(db,conditions.join(' AND '),values),
    db.prepare("INSERT INTO discovery_runs(id,campaign_id,owner_id,status,started_at,scheduled_for) VALUES(?,?,?,'executando',?,?)").bind(runId,campaignId,owner,stamp,scheduledFor??null),
    db.prepare('UPDATE discovery_campaigns SET next_run_at=? WHERE id=? AND owner_id=? AND revision=?').bind(schedule,campaignId,owner,campaign.revision),
  ]);}catch(error){if(isConstraint(error))throw new ApiError(400,'Outra coleta está em execução, o limite de rodadas foi atingido ou a campanha foi alterada. Aguarde um minuto e atualize a lista.');throw error;}
  const work=executeDiscovery(env,campaign,runId,cfg);
  if(context)context.waitUntil(work);else await work;
  return runId;
}
export async function scheduledDiscovery(env:Env,scheduledTime=Date.now()):Promise<void> {
  const cfg=await config(env.DB);if(!cfg.capture_enabled||!cfg.capture_scheduler)return;
  const due=await queryFirst(env.DB,"SELECT c.id,c.owner_id,c.next_run_at FROM discovery_campaigns c WHERE c.active=1 AND c.frequency IN ('daily','scheduled') AND c.next_run_at<=? AND NOT EXISTS(SELECT 1 FROM user_accounts a WHERE a.id=c.owner_id AND a.is_active=0) AND (SELECT COUNT(*) FROM discovery_runs r WHERE r.owner_id=c.owner_id AND r.started_at>=?)<? ORDER BY c.next_run_at,c.id LIMIT 1",[saoPauloTime(scheduledTime),saoPauloTime(scheduledTime-86400000),cfg.capture_runs_account]);
  if(!due)return;
  try {await startDiscovery(env,String(due.owner_id),String(due.id),undefined,String(due.next_run_at));}catch(error){if(error instanceof ApiError)return;throw error;}
}
export async function handleDiscovery(request:Request,env:Env,principal:Principal,url:URL,context?:BackgroundContext):Promise<Response|undefined> {
  const path=url.pathname,db=env.DB,owner=principal.accountId;if(!path.startsWith('/api/discovery'))return undefined;
  if(request.method==='GET'&&path==='/api/discovery') {
    const cfg=await config(db),campaigns=await queryRows(db,'SELECT * FROM discovery_campaigns WHERE owner_id=? ORDER BY created_at DESC',[owner]);
    for(const c of campaigns){c.times=decoded(c.times_json,[]);delete c.times_json;}
    return json({campaigns,runs:await queryRows(db,'SELECT * FROM discovery_runs WHERE owner_id=? ORDER BY started_at DESC LIMIT 30',[owner]),total:Number((await queryFirst(db,'SELECT COUNT(*) AS n FROM discovery_sources WHERE owner_id=?',[owner]))?.n??0),categories:Object.entries(CATEGORIES).map(([id,c])=>({id,label:c[0]})),limits:{per_run:50,runs_per_day:cfg.capture_runs_account,websites_per_run:0},enabled:cfg.capture_enabled,collector_ready:false,enrichment_backend:'unavailable',enrichment_message:'O coletor Node local não está hospedado neste Cloudflare Worker. Os contatos do mapa são preservados.',osm_mode:'overpass',configured_osm_mode:cfg.capture_osm_mode,local_osm:{ready:false,count:0,cities:[],version:'',built_at:null,stale:false,message:'Índice OSM local indisponível no Worker; fonte ativa: Overpass público.'},scheduler_enabled:cfg.capture_scheduler,server_time:now(),pending_recommendations:Number((await queryFirst(db,"SELECT COUNT(*) AS n FROM discovery_recommendations WHERE owner_id=? AND status='pending'",[owner]))?.n??0)});
  }
  if(request.method==='GET'&&path==='/api/discovery/sources') {
    const items=await queryRows(db,'SELECT d.source_key,d.metadata_json,p.id,p.name,p.city,p.phone,p.email,p.website FROM discovery_sources d JOIN prospect_inbox p ON p.id=d.prospect_id AND p.owner_id=d.owner_id WHERE d.owner_id=? ORDER BY d.last_seen_at DESC,d.source_key LIMIT 50',[owner]);
    for(const row of items){row.metadata=decoded(row.metadata_json,{});delete row.metadata_json;}return json({items});
  }
  if(request.method==='GET'&&path==='/api/discovery/recommendations') {
    const status=url.searchParams.get('status')??'pending',rawPage=url.searchParams.get('page')??'1';
    if(!['pending','accepted','dismissed'].includes(status))throw new ApiError(400,'Situação inválida');
    if(!/^-?\d+$/.test(rawPage)||!Number.isSafeInteger(Number(rawPage)))throw new ApiError(400,'Página inválida');
    const total=Number((await queryFirst(db,'SELECT COUNT(*) AS n FROM discovery_recommendations WHERE owner_id=? AND status=?',[owner,status]))?.n??0),page=Math.min(Math.max(1,Number(rawPage)),Math.max(1,Math.ceil(total/50)));
    const items=await queryRows(db,'SELECT r.*,p.name,p.city,p.phone,p.email,p.website,p.cnpj,c.name AS campaign FROM discovery_recommendations r JOIN prospect_inbox p ON p.id=r.prospect_id AND p.owner_id=r.owner_id JOIN discovery_campaigns c ON c.id=r.campaign_id AND c.owner_id=r.owner_id WHERE r.owner_id=? AND r.status=? ORDER BY r.created_at DESC,r.id LIMIT 50 OFFSET ?',[owner,status,(page-1)*50]);
    const counts=Object.fromEntries((await queryRows(db,'SELECT status,COUNT(*) AS n FROM discovery_recommendations WHERE owner_id=? GROUP BY status',[owner])).map(r=>[String(r.status),Number(r.n)]));return json({items,total,page,size:50,counts});
  }
  if(request.method==='POST'&&path==='/api/discovery/recommendations/review') {
    const raw=await bodyJson(request,16384),items=raw.items;
    if(raw.status!=='accepted'&&raw.status!=='dismissed')throw new ApiError(400,'Escolha selecionar ou descartar');
    if(!Array.isArray(items)||items.length<1||items.length>50)throw new ApiError(400,'Selecione de 1 a 50 recomendações');
    if(items.some(i=>!i||typeof i!=='object'||typeof i.id!=='string'||!Number.isInteger(i.revision)))throw new ApiError(400,'Seleção inválida');
    if(new Set(items.map(i=>i.id)).size!==items.length)throw new ApiError(400,'Seleção duplicada');
    const selection=JSON.stringify(items),existing=Number((await queryFirst(db,"SELECT COUNT(*) AS n FROM discovery_recommendations WHERE owner_id=? AND id IN(SELECT json_extract(value,'$.id') FROM json_each(?))",[owner,selection]))?.n??0);
    if(existing!==items.length)throw new ApiError(404,'Recomendação não encontrada nesta conta');
    const updated=await db.prepare(`UPDATE discovery_recommendations SET status=?,revision=revision+1,reviewed_at=? WHERE owner_id=? AND id IN(SELECT json_extract(value,'$.id') FROM json_each(?)) AND (SELECT COUNT(*) FROM discovery_recommendations r JOIN json_each(?) j ON r.id=json_extract(j.value,'$.id') AND r.revision=json_extract(j.value,'$.revision') WHERE r.owner_id=? AND r.status='pending')=?`).bind(raw.status,now(),owner,selection,selection,owner,items.length).run();
    if(Number(updated.meta.changes)!==items.length)throw new ApiError(409,'Recomendação alterada em outra sessão. Atualize a lista.');return json({updated:items.length,status:raw.status});
  }
  if(request.method==='GET'&&path==='/api/discovery/notifications')return json({items:await queryRows(db,'SELECT n.*,c.name AS campaign FROM discovery_notifications n JOIN discovery_campaigns c ON c.id=n.campaign_id AND c.owner_id=n.owner_id WHERE n.owner_id=? ORDER BY (n.read_at IS NULL) DESC,n.created_at DESC,n.id LIMIT 30',[owner]),unread:Number((await queryFirst(db,'SELECT COUNT(*) AS n FROM discovery_notifications WHERE owner_id=? AND read_at IS NULL',[owner]))?.n??0),enabled:!!((await queryFirst(db,'SELECT notifications_enabled FROM discovery_preferences WHERE owner_id=?',[owner]))?.notifications_enabled??1)});
  if(request.method==='POST'&&path==='/api/discovery/notifications') {
    const raw=await bodyJson(request,16384);
    if(Object.keys(raw).length===1&&typeof raw.enabled==='boolean'){await db.prepare('INSERT INTO discovery_preferences(owner_id,notifications_enabled) VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET notifications_enabled=excluded.notifications_enabled').bind(owner,Number(raw.enabled)).run();return json({enabled:raw.enabled});}
    if(Object.keys(raw).length!==1||!Array.isArray(raw.ids)||raw.ids.length<1||raw.ids.length>30||raw.ids.some(i=>typeof i!=='string'))throw new ApiError(400,'Notificações inválidas');
    await db.prepare('UPDATE discovery_notifications SET read_at=COALESCE(read_at,?) WHERE owner_id=? AND id IN(SELECT value FROM json_each(?))').bind(now(),owner,JSON.stringify(raw.ids)).run();return json({ok:true});
  }
  if(request.method==='POST'&&path==='/api/discovery/campaigns')return json({id:await saveCampaign(db,owner,await bodyJson(request,8192))},201);
  const campaign=/^\/api\/discovery\/campaigns\/([a-f0-9]{32})$/.exec(path);
  if(request.method==='PUT'&&campaign)return json({id:await saveCampaign(db,owner,await bodyJson(request,8192),campaign[1])});
  const run=/^\/api\/discovery\/campaigns\/([a-f0-9]{32})\/run$/.exec(path);
  if(request.method==='POST'&&run)return json({id:await startDiscovery(env,owner,run[1],context),status:'executando'},202);
  return undefined;
}
