import { ApiError, bodyJson, headers, json, now, privateCompanyVisible, queryFirst, queryRows, type Env, type Principal, type Row } from './runtime';
import { COMPANY_SELECT_SQL as SELECT, COMPANY_SOURCE_SQL as SOURCE, LEAD_SCORE_SQL as SCORE, companyFilters, normalizeCnpj, scoreCompany } from './query-current';

const stages=new Set(['novo','qualificado','contatado','negociacao','convertido','descartado','concluido']);
const fields=new Set(['q','inicio','fim','segmento','cnae','municipio','regiao','situacao','mei','contato','lead_status','favorito','score_min','cnae_include','cnae_exclude','name_terms','name_exclude','porte','data_source','phone_available','email_available','work_stage']);
const official="c.uf='RS' AND COALESCE(c.situacao,'')<>'TESTE' AND NOT EXISTS(SELECT 1 FROM private_companies pc WHERE pc.cnpj=c.cnpj)";
// Bounded isolate-local caches. No cookies, credentials, or cross-account cache keys.
let generation=0;
let statCache=new WeakMap<D1Database,Map<string,{expires:number;body:string}>>();
let publicOptionsCache=new WeakMap<D1Database,{expires:number;options:Row;date:unknown}>();
export function invalidateStatistics():void{generation++;statCache=new WeakMap();}
export function invalidateOfficialMetadata():void{invalidateStatistics();publicOptionsCache=new WeakMap();}
async function publicOptions(env:Env):Promise<{options:Row;date:unknown}>{
  const cached=publicOptionsCache.get(env.DB);if(cached&&cached.expires>Date.now())return cached;
  const options:Row={};
  for(const column of ['municipio','regiao','segmento','porte','data_source'])options[column]=(await queryRows(env.DB,`SELECT DISTINCT c.${column} value FROM companies c WHERE ${official} AND c.${column}<>'' ORDER BY c.${column}`)).map(row=>row.value);
  options.cnaes=await queryRows(env.DB,`SELECT c.cnae codigo,MAX(c.cnae_descricao) descricao,MAX(c.segmento) segmento,COUNT(*) empresas FROM companies c WHERE ${official} AND c.cnae<>'' GROUP BY c.cnae ORDER BY empresas DESC,c.cnae`);
  const date=(await queryFirst(env.DB,`SELECT MAX(c.data_abertura) value FROM companies c WHERE ${official}`))?.value||null;
  publicOptionsCache.set(env.DB,{expires:Date.now()+300000,options,date});return {options,date};
}
async function cachedStats(env:Env,p:Principal,url:URL):Promise<Response>{
  const key=p.accountId+'\0'+url.searchParams.toString(),current=Date.now();
  let cache=statCache.get(env.DB);if(!cache){cache=new Map();statCache.set(env.DB,cache);}
  const cached=cache.get(key);if(cached&&cached.expires>current)return new Response(cached.body,{headers:headers({'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'})});
  const version=generation,response=await stats(env,p,url),body=await response.clone().text();
  if(version===generation){for(const [k,v]of cache)if(v.expires<=current)cache.delete(k);if(cache.size>=64)cache.delete(cache.keys().next().value!);cache.set(key,{expires:current+20000,body});}
  return response;
}
function pagination(url:URL):{page:number;size:number}{
  for(const key of ['page','size'])if(url.searchParams.has(key)&&!/^\d+$/.test(url.searchParams.get(key)!))throw new ApiError(400,'Paginação inválida');
  return {page:Math.min(1000000,Math.max(1,Number(url.searchParams.get('page')||1))),size:Math.min(100,Math.max(1,Number(url.searchParams.get('size')||24)))};
}
function decodeFilters(row:Row):Row{
  let filters:unknown={};try{filters=JSON.parse(String(row.filters_json||'{}'));}catch{/* invalid legacy row is empty */}
  const {filters_json:_raw,...profile}=row;return {...profile,filters:filters&&typeof filters==='object'&&!Array.isArray(filters)?filters:{}};
}
async function requireSegmentation(env:Env,id:string,p:Principal,custom=false):Promise<Row>{
  const row=await queryFirst(env.DB,`SELECT * FROM prospecting_profiles WHERE id=? AND ${custom?'owner_id=?':'(is_system=1 OR owner_id=?)'}`,[id,p.accountId]);
  if(!row)throw new ApiError(404,'Perfil não encontrado');return row;
}
async function visibleCompany(env:Env,cnpj:string,p:Principal):Promise<Row>{
  const row=await queryFirst(env.DB,`SELECT c.* FROM companies c WHERE c.cnpj=? AND ${privateCompanyVisible('c','?')}`,[cnpj,p.accountId]);
  if(!row)throw new ApiError(404,'Empresa não encontrada');return row;
}
async function stats(env:Env,p:Principal,url:URL):Promise<Response>{
  const filter=companyFilters(url.searchParams,new Set(),p.accountId);
  const mei=companyFilters(url.searchParams,new Set(['mei','lead_status','favorito']),p.accountId);
  const opportunity=companyFilters(url.searchParams,new Set(['score_min','lead_status','favorito']),p.accountId);
  const rows=(sql:string,f=filter)=>queryRows(env.DB,sql,[p.accountId,...f.values]);
  const first=(sql:string,f=filter)=>queryFirst(env.DB,sql,[p.accountId,...f.values]);
  const summary=await first(`SELECT COUNT(*) total,COALESCE(SUM(c.mei),0) meis,COUNT(DISTINCT c.municipio) municipios,
    COUNT(DISTINCT c.segmento) segmentos,COALESCE(SUM(CASE WHEN c.email<>'' OR c.telefone<>'' THEN 1 ELSE 0 END),0) com_contato,
    MAX(c.data_abertura) ultima_data FROM ${SOURCE} WHERE ${filter.where}`)||{};
  const [groups,cnaes,cities,timeline,pipeline,favorite,meiSummary,meiCnaes,meiGroups,meiCities,meiTimeline]=await Promise.all([
    rows(`SELECT c.segmento label,COUNT(*) value FROM ${SOURCE} WHERE ${filter.where} GROUP BY c.segmento ORDER BY value DESC LIMIT 6`),
    rows(`SELECT c.cnae label,MAX(c.cnae_descricao) description,c.segmento category,COUNT(*) value FROM ${SOURCE} WHERE ${filter.where} AND c.cnae<>'' GROUP BY c.cnae,c.segmento ORDER BY value DESC,c.cnae LIMIT 8`),
    rows(`SELECT c.municipio label,COUNT(*) value FROM ${SOURCE} WHERE ${filter.where} GROUP BY c.municipio ORDER BY value DESC,c.municipio LIMIT 5`),
    rows(`SELECT substr(c.data_abertura,1,7) label,COUNT(*) value FROM ${SOURCE} WHERE ${filter.where} AND c.data_abertura<>'' GROUP BY substr(c.data_abertura,1,7) ORDER BY label`),
    rows(`SELECT COALESCE(NULLIF(acs.lead_status,''),'novo') label,COUNT(*) value FROM ${SOURCE} WHERE ${filter.where} GROUP BY COALESCE(NULLIF(acs.lead_status,''),'novo')`),
    first(`SELECT COUNT(*) total FROM ${SOURCE} WHERE ${filter.where} AND COALESCE(acs.favorito,0)=1`),
    first(`SELECT COUNT(*) total,COUNT(DISTINCT c.cnae) cnaes,COUNT(DISTINCT c.municipio) municipios,MAX(c.data_abertura) ultima_data FROM ${SOURCE} WHERE ${mei.where} AND c.mei=1`,mei),
    rows(`SELECT c.cnae label,MAX(c.cnae_descricao) description,c.segmento category,COUNT(*) value FROM ${SOURCE} WHERE ${mei.where} AND c.mei=1 AND c.cnae<>'' GROUP BY c.cnae,c.segmento ORDER BY value DESC,c.cnae LIMIT 10`,mei),
    rows(`SELECT c.segmento label,COUNT(*) value FROM ${SOURCE} WHERE ${mei.where} AND c.mei=1 AND c.segmento<>'' GROUP BY c.segmento ORDER BY value DESC,c.segmento LIMIT 6`,mei),
    rows(`SELECT c.municipio label,COUNT(*) value FROM ${SOURCE} WHERE ${mei.where} AND c.mei=1 AND c.municipio<>'' GROUP BY c.municipio ORDER BY value DESC,c.municipio LIMIT 5`,mei),
    rows(`SELECT substr(c.data_abertura,1,7) label,COUNT(*) value FROM ${SOURCE} WHERE ${mei.where} AND c.mei=1 AND c.data_abertura<>'' GROUP BY substr(c.data_abertura,1,7) ORDER BY label`,mei),
  ]);
  const {options,date}=await publicOptions(env);summary.base_ultima_data=date;
  const high=`${opportunity.where} AND ${SCORE}>=80`;
  const highSummary=await first(`SELECT COUNT(*) total,COALESCE(SUM(CASE WHEN TRIM(COALESCE(c.email,''))<>'' OR TRIM(COALESCE(c.telefone,''))<>'' THEN 1 ELSE 0 END),0) with_contact,COALESCE(SUM(c.mei),0) mei FROM ${SOURCE} WHERE ${high}`,opportunity)||{};
  highSummary.items=(await rows(`SELECT ${SELECT} FROM ${SOURCE} WHERE ${high} ORDER BY ${SCORE} DESC,c.data_abertura DESC,c.id DESC LIMIT 8`,opportunity)).map(row=>({...row,lead_score:scoreCompany(row)}));
  return json({summary,groups,cnaes,cities,timeline,pipeline,favorites:favorite?.total||0,options,mei_summary:meiSummary,mei_cnaes:meiCnaes,mei_groups:meiGroups,mei_cities:meiCities,mei_timeline:meiTimeline,opportunities:highSummary});
}

export async function handleCore(request:Request,env:Env,p:Principal,url:URL):Promise<Response|undefined>{
  const path=url.pathname, method=request.method;
  if(!['GET','HEAD'].includes(method))invalidateStatistics();
  if(method==='GET'&&path==='/api/companies'){
    const {page,size}=pagination(url);const filter=companyFilters(url.searchParams,new Set(),p.accountId);
    const total=(await queryFirst(env.DB,`SELECT COUNT(*) total FROM ${SOURCE} WHERE ${filter.where}`,[p.accountId,...filter.values]))?.total||0;
    const items=(await queryRows(env.DB,`SELECT ${SELECT} FROM ${SOURCE} WHERE ${filter.where} ORDER BY COALESCE(acs.favorito,0) DESC,c.data_abertura DESC,c.id DESC LIMIT ? OFFSET ?`,[p.accountId,...filter.values,size,(page-1)*size])).map(row=>({...row,lead_score:scoreCompany(row)}));
    return json({items,total,page,size});
  }
  if(method==='GET'&&path==='/api/stats')return cachedStats(env,p,url);
  if(method==='GET'&&path==='/api/profiles'){
    const profiles=await queryRows(env.DB,'SELECT * FROM prospecting_profiles WHERE is_system=1 OR owner_id=? ORDER BY is_system DESC,created_at,name',[p.accountId]);
    const items=[];for(const row of profiles){
      const item=decodeFilters(row);const filters=new URLSearchParams(Object.entries(item.filters as Row).map(([key,value])=>[key,String(value)]));
      const filter=companyFilters(filters,new Set(),p.accountId);
      item.companies=(await queryFirst(env.DB,`SELECT COUNT(*) total FROM ${SOURCE} WHERE ${filter.where}`,[p.accountId,...filter.values]))?.total||0;
      item.lead_count=(await queryFirst(env.DB,'SELECT COUNT(*) total FROM profile_leads WHERE profile_id=?',[row.id]))?.total||0;
      items.push(item);
    }return json({items});
  }
  if(method==='GET'&&path==='/api/profile-memberships'){
    const cnpj=normalizeCnpj(url.searchParams.get('cnpj'));if(cnpj.length!==14)throw new ApiError(400,'CNPJ inválido');
    await visibleCompany(env,cnpj,p);
    return json({items:await queryRows(env.DB,`SELECT p.id,p.name,p.description,p.is_system,CASE WHEN pl.cnpj IS NULL THEN 0 ELSE 1 END selected
      FROM prospecting_profiles p LEFT JOIN profile_leads pl ON pl.profile_id=p.id AND pl.cnpj=? WHERE p.is_system=0 AND p.owner_id=? ORDER BY p.name`,[cnpj,p.accountId])});
  }
  if(method==='GET'&&path==='/api/profile-leads'){
    const profile=await requireSegmentation(env,url.searchParams.get('profile_id')||'',p);const {page,size}=pagination(url);
    const total=(await queryFirst(env.DB,`SELECT COUNT(*) total FROM ${SOURCE} JOIN profile_leads pl ON pl.cnpj=c.cnpj WHERE pl.profile_id=? AND ${privateCompanyVisible('c','?')}`,[p.accountId,profile.id,p.accountId]))?.total||0;
    const items=(await queryRows(env.DB,`SELECT ${SELECT},pl.added_at carteira_adicionado_em FROM ${SOURCE} JOIN profile_leads pl ON pl.cnpj=c.cnpj
      WHERE pl.profile_id=? AND ${privateCompanyVisible('c','?')} ORDER BY COALESCE(acs.favorito,0) DESC,c.data_abertura DESC,pl.added_at DESC LIMIT ? OFFSET ?`,[p.accountId,profile.id,p.accountId,size,(page-1)*size])).map(row=>({...row,lead_score:scoreCompany(row)}));
    return json({profile:{id:profile.id,name:profile.name,is_system:profile.is_system},items,total,page,size});
  }
  if(method==='POST'&&path==='/api/profiles'){
    const data=await bodyJson(request,65536);const name=String(data.name||'').trim().slice(0,60),description=String(data.description||'').trim().slice(0,180);
    if(!name)throw new ApiError(400,'Informe o nome do perfil');
    const rawFilters=data.filters===undefined?{}:data.filters;
    if(!rawFilters||typeof rawFilters!=='object'||Array.isArray(rawFilters))throw new ApiError(400,'Filtros do perfil inválidos');
    const filters=Object.fromEntries(Object.entries(rawFilters).filter(([k,v])=>fields.has(k)&&String(v).trim()).map(([k,v])=>[k,String(v).slice(0,1000)]));
    const id='perfil-'+crypto.randomUUID().replaceAll('-','').slice(0,12),stamp=now();
    await env.DB.prepare('INSERT INTO prospecting_profiles(id,name,description,filters_json,is_system,owner_id,created_at,updated_at) VALUES(?,?,?,?,0,?,?,?)').bind(id,name,description,JSON.stringify(filters),p.accountId,stamp,stamp).run();
    return json({id,name,description,filters,is_system:0,companies:0,lead_count:0},201);
  }
  if(method==='POST'&&path==='/api/profile-leads'){
    const data=await bodyJson(request,16384),id=String(data.profile_id||''),cnpj=normalizeCnpj(data.cnpj);
    if(cnpj.length!==14)throw new ApiError(400,'CNPJ inválido');const profile=await requireSegmentation(env,id,p,true);
    if(profile.is_system)throw new ApiError(400,'Escolha um perfil personalizado para montar uma lista');await visibleCompany(env,cnpj,p);
    const result=await env.DB.prepare('INSERT OR IGNORE INTO profile_leads(profile_id,cnpj,added_at) VALUES(?,?,?)').bind(id,cnpj,now()).run();
    const count=(await queryFirst(env.DB,'SELECT COUNT(*) total FROM profile_leads WHERE profile_id=?',[id]))?.total||0;
    return json({adicionado:result.meta.changes>0,profile_id:id,cnpj,lead_count:count},result.meta.changes?201:200);
  }
  if(method==='PUT'&&/^\/api\/leads\/[A-Za-z0-9]{14}$/.test(path)){
    const cnpj=normalizeCnpj(path.split('/').pop());await visibleCompany(env,cnpj,p);const data=await bodyJson(request,65536);
    if('lead_status' in data&&!stages.has(String(data.lead_status)))throw new ApiError(400,'Etapa inválida');
    if(!['lead_status','favorito','observacoes'].some(key=>key in data))throw new ApiError(400,'Nenhuma alteração válida');
    const state=await queryFirst(env.DB,'SELECT * FROM account_company_state WHERE account_id=? AND cnpj=?',[p.accountId,cnpj])||{lead_status:'novo',favorito:0,observacoes:''};
    const status=data.lead_status??state.lead_status,fav='favorito' in data?(data.favorito?1:0):state.favorito,notes='observacoes' in data?String(data.observacoes).slice(0,4000):state.observacoes;
    await env.DB.prepare(`INSERT INTO account_company_state(account_id,cnpj,lead_status,favorito,observacoes,updated_at) VALUES(?,?,?,?,?,?)
      ON CONFLICT(account_id,cnpj) DO UPDATE SET lead_status=excluded.lead_status,favorito=excluded.favorito,observacoes=excluded.observacoes,updated_at=excluded.updated_at`).bind(p.accountId,cnpj,status,fav,notes,now()).run();
    const result=(await queryFirst(env.DB,`SELECT ${SELECT} FROM ${SOURCE} WHERE c.cnpj=?`,[p.accountId,cnpj]))!;return json({...result,lead_score:scoreCompany(result)});
  }
  if(method==='DELETE'&&path==='/api/profile-leads'){
    const id=url.searchParams.get('profile_id')||'',cnpj=normalizeCnpj(url.searchParams.get('cnpj'));await requireSegmentation(env,id,p,true);
    const result=await env.DB.prepare('DELETE FROM profile_leads WHERE profile_id=? AND cnpj=?').bind(id,cnpj).run();return json({removido:result.meta.changes>0});
  }
  if(method==='DELETE'&&path.startsWith('/api/profiles/')){
    const id=path.split('/').pop()!;const profile=await requireSegmentation(env,id,p);
    if(profile.is_system)throw new ApiError(400,'Os perfis padrão não podem ser removidos');
    const result=await env.DB.prepare('DELETE FROM prospecting_profiles WHERE id=? AND owner_id=? AND is_system=0').bind(id,p.accountId).run();return json({removido:result.meta.changes>0});
  }
  return undefined;
}
