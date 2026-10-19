import {ApiError, bodyJson, json, now, privateCompanyVisible, queryFirst, queryRows, type Env, type Principal, type Row} from './runtime';

export const PROSPECT_FIELDS: Record<string, number> = {name:180,company:180,phone:32,email:180,city:100,source:120,campaign:120,persona:120,website:300,notes:4000,cnpj:14};
export const PROSPECT_STATUSES = ['novo','contatado','qualificado','descartado'];
export function validateProspect(raw: Row): Record<string,string> {
  const row: Record<string,string> = {};
  for (const [key,limit] of Object.entries(PROSPECT_FIELDS)) {
    const value = key in raw ? raw[key] : '';
    if (typeof value !== 'string') throw new ApiError(400,`Campo ${key} precisa ser texto`);
    row[key]=value.trim();
    if ([...row[key]].length>limit) throw new ApiError(400,`Campo ${key} excede ${limit} caracteres`);
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value)) throw new ApiError(400,`Campo ${key} contém caracteres inválidos`);
  }
  row.name ||= row.company;
  if (!row.name) throw new ApiError(400,'Informe nome ou empresa');
  if(row.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(row.email)) throw new ApiError(400,'E-mail inválido');
  if(row.cnpj && !/^[A-Z0-9]{14}$/.test(row.cnpj)) throw new ApiError(400,'CNPJ precisa ter 14 caracteres, sem pontuação');
  if(row.website) {
    try {const u=new URL(row.website);if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password)throw Error();}
    catch {throw new ApiError(400,'Site precisa ser uma URL http/https, sem credenciais');}
  }
  row.source ||= 'Importação CSV';
  const status='status' in raw ? raw.status : 'novo';
  if(typeof status!=='string'||!PROSPECT_STATUSES.includes(status))throw new ApiError(400,'Situação inválida');
  row.status=status;
  return row;
}
export function identifier():string {return crypto.randomUUID().replace(/-/g,'');}
// Python str.casefold() exceptions keep migrated fingerprints stable, without a runtime dependency.
const CASE_FOLD:Record<string,string>={"µ":"μ","ß":"ss","ŉ":"ʼn","ſ":"s","ǰ":"ǰ","ͅ":"ι","ΐ":"ΐ","ΰ":"ΰ","ς":"σ","ϐ":"β","ϑ":"θ","ϕ":"φ","ϖ":"π","ϰ":"κ","ϱ":"ρ","ϵ":"ε","և":"եւ","ᲀ":"в","ᲁ":"д","ᲂ":"о","ᲃ":"с","ᲄ":"т","ᲅ":"т","ᲆ":"ъ","ᲇ":"ѣ","ᲈ":"ꙋ","ẖ":"ẖ","ẗ":"ẗ","ẘ":"ẘ","ẙ":"ẙ","ẚ":"aʾ","ẛ":"ṡ","ẞ":"ss","ὐ":"ὐ","ὒ":"ὒ","ὔ":"ὔ","ὖ":"ὖ","ᾀ":"ἀι","ᾁ":"ἁι","ᾂ":"ἂι","ᾃ":"ἃι","ᾄ":"ἄι","ᾅ":"ἅι","ᾆ":"ἆι","ᾇ":"ἇι","ᾈ":"ἀι","ᾉ":"ἁι","ᾊ":"ἂι","ᾋ":"ἃι","ᾌ":"ἄι","ᾍ":"ἅι","ᾎ":"ἆι","ᾏ":"ἇι","ᾐ":"ἠι","ᾑ":"ἡι","ᾒ":"ἢι","ᾓ":"ἣι","ᾔ":"ἤι","ᾕ":"ἥι","ᾖ":"ἦι","ᾗ":"ἧι","ᾘ":"ἠι","ᾙ":"ἡι","ᾚ":"ἢι","ᾛ":"ἣι","ᾜ":"ἤι","ᾝ":"ἥι","ᾞ":"ἦι","ᾟ":"ἧι","ᾠ":"ὠι","ᾡ":"ὡι","ᾢ":"ὢι","ᾣ":"ὣι","ᾤ":"ὤι","ᾥ":"ὥι","ᾦ":"ὦι","ᾧ":"ὧι","ᾨ":"ὠι","ᾩ":"ὡι","ᾪ":"ὢι","ᾫ":"ὣι","ᾬ":"ὤι","ᾭ":"ὥι","ᾮ":"ὦι","ᾯ":"ὧι","ᾲ":"ὰι","ᾳ":"αι","ᾴ":"άι","ᾶ":"ᾶ","ᾷ":"ᾶι","ᾼ":"αι","ι":"ι","ῂ":"ὴι","ῃ":"ηι","ῄ":"ήι","ῆ":"ῆ","ῇ":"ῆι","ῌ":"ηι","ῒ":"ῒ","ΐ":"ΐ","ῖ":"ῖ","ῗ":"ῗ","ῢ":"ῢ","ΰ":"ΰ","ῤ":"ῤ","ῦ":"ῦ","ῧ":"ῧ","ῲ":"ὼι","ῳ":"ωι","ῴ":"ώι","ῶ":"ῶ","ῷ":"ῶι","ῼ":"ωι","ﬀ":"ff","ﬁ":"fi","ﬂ":"fl","ﬃ":"ffi","ﬄ":"ffl","ﬅ":"st","ﬆ":"st","ﬓ":"մն","ﬔ":"մե","ﬕ":"մի","ﬖ":"վն","ﬗ":"մխ"};
function fold(value:string):string {
  return [...value].map(c=>{
    const point=c.codePointAt(0)!;
    if(point>=0x13a0&&point<=0x13f5)return c;
    if(point>=0x13f8&&point<=0x13fd)return String.fromCodePoint(point-8);
    if(point>=0xab70&&point<=0xabbf)return String.fromCodePoint(point-0x97d0);
    return CASE_FOLD[c]??c.toLowerCase();
  }).join('');
}
export async function prospectFingerprint(row: Row):Promise<string> {
  const key=[fold(String(row.name??'')),fold(String(row.company??'')),String(row.phone??'').replace(/\D/g,''),fold(String(row.email??'')),String(row.cnpj??'')].join('|');
  const bytes=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(key)));
  return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
}
/** D1 batch is transactional. This assertion deliberately aborts/rolls back a stale batch. */
export function assertSql(db:D1Database, condition:string, values:unknown[]):D1PreparedStatement {
  return db.prepare(`SELECT CASE WHEN (${condition}) THEN 1 ELSE json('radar_revision_conflict') END AS valid`).bind(...values);
}
export function isConstraint(error:unknown):boolean {return /constraint|unique|radar_revision_conflict|malformed json/i.test(String(error));}
export async function prospectSummary(db:D1Database,owner:string):Promise<Row> {
  const counts=await queryRows(db,'SELECT status,COUNT(*) AS count FROM prospect_inbox WHERE owner_id=? GROUP BY status',[owner]);
  const statuses=Object.fromEntries(counts.map(r=>[String(r.status),Number(r.count)]));
  const total=Object.values(statuses).reduce((a,b)=>a+b,0);
  const linked=Number((await queryFirst(db,'SELECT COUNT(DISTINCT prospect_id) AS n FROM prospect_links WHERE owner_id=?',[owner]))?.n??0);
  return {total,statuses,linked,not_linked:total-linked,basis:'Contatos externos da conta, todos os períodos. Somente vínculos entram no funil oficial.'};
}
function parseMetadata(value:unknown):unknown {try{return JSON.parse(String(value));}catch{return null;}}
function pageNumber(value:string|null):number {if(value!==null&&!/^-?\d+$/.test(value))throw new ApiError(400,'Página inválida');const page=Number(value??1);if(!Number.isSafeInteger(page))throw new ApiError(400,'Página inválida');return Math.max(1,page);}
async function qualify(env:Env,owner:string,raw:Row):Promise<Response> {
  if(Object.keys(raw).some(k=>!['prospect_id','profile_id','cnpj','allow_duplicate'].includes(k)))throw new ApiError(400,'Encaminhamento inválido');
  const {prospect_id:id,profile_id:profile,cnpj}=raw;
  if(typeof id!=='string'||typeof profile!=='string'||typeof cnpj!=='string'||!/^[A-Z0-9]{14}$/.test(cnpj))throw new ApiError(400,'Informe o contato, responsável e CNPJ sem pontuação');
  const db=env.DB;
  const contact=await queryFirst(db,'SELECT * FROM prospect_inbox WHERE id=? AND owner_id=?',[id,owner]);
  const owned=await queryFirst(db,'SELECT 1 AS ok FROM sales_profiles WHERE id=? AND owner_id=?',[profile,owner]);
  if(!contact||!owned)throw new ApiError(404,'Contato ou responsável não encontrado nesta conta');
  const visible=privateCompanyVisible('c','?');
  if(!await queryFirst(db,`SELECT 1 AS ok FROM companies c WHERE c.cnpj=? AND ${visible}`,[cnpj,owner]))throw new ApiError(404,'CNPJ não encontrado na base disponível. O contato externo foi preservado.');
  const already=!!await queryFirst(db,'SELECT 1 AS ok FROM sales_profile_leads WHERE profile_id=? AND cnpj=?',[profile,cnpj]);
  const other=await queryFirst(db,"SELECT 1 AS ok FROM sales_profile_leads WHERE cnpj=? AND profile_id<>? AND lead_status NOT IN ('convertido','descartado') LIMIT 1",[cnpj,profile]);
  if(other&&!already&&raw.allow_duplicate!==true)return json({erro:'Empresa em outro atendimento ativo. Confirme a duplicação da abordagem.',duplicate:true},409);
  const stamp=now(),fp=await prospectFingerprint({...contact,cnpj});
  const guard=assertSql(db,`EXISTS(SELECT 1 FROM prospect_inbox WHERE id=? AND owner_id=? AND revision=?) AND EXISTS(SELECT 1 FROM sales_profiles WHERE id=? AND owner_id=?) AND EXISTS(SELECT 1 FROM companies c WHERE c.cnpj=? AND ${visible}) AND (?=1 OR EXISTS(SELECT 1 FROM sales_profile_leads WHERE profile_id=? AND cnpj=?) OR NOT EXISTS(SELECT 1 FROM sales_profile_leads WHERE cnpj=? AND profile_id<>? AND lead_status NOT IN ('convertido','descartado')))`,[id,owner,contact.revision,profile,owner,cnpj,owner,raw.allow_duplicate===true?1:0,profile,cnpj,cnpj,profile]);
  const notes=`Contato externo: ${contact.name}\nTelefone declarado: ${contact.phone}\nE-mail declarado: ${contact.email}\n${contact.notes}`.slice(0,5000);
  // All steps share one transaction; existing lead strategy, stage and notes are never replaced.
  try {
    const results=await db.batch([
      guard,
      db.prepare(`INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,lead_status,observacoes,campaign,persona,lead_origin) VALUES(?,?,?,?,'qualificado',?,?,?,?) ON CONFLICT(profile_id,cnpj) DO NOTHING`).bind(profile,cnpj,stamp,stamp,notes,contact.campaign,contact.persona,contact.source),
      db.prepare("INSERT INTO prospect_history(prospect_id,owner_id,event,details,created_at) SELECT ?,?,'linked',?,? WHERE NOT EXISTS(SELECT 1 FROM prospect_links WHERE prospect_id=? AND profile_id=? AND cnpj=?)").bind(id,owner,'Encaminhado ao painel: '+cnpj,stamp,id,profile,cnpj),
      db.prepare("INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,details,created_at) SELECT ?,?,'external_linked','Contato externo vinculado',?,? WHERE NOT EXISTS(SELECT 1 FROM prospect_links WHERE prospect_id=? AND profile_id=? AND cnpj=?)").bind(profile,cnpj,`Origem: ${contact.source}; campanha: ${contact.campaign}`,stamp,id,profile,cnpj),
      db.prepare("UPDATE prospect_inbox SET status='qualificado',cnpj=?,fingerprint=?,updated_at=?,revision=revision+1 WHERE id=? AND owner_id=? AND NOT EXISTS(SELECT 1 FROM prospect_links WHERE prospect_id=? AND profile_id=? AND cnpj=?)").bind(cnpj,fp,stamp,id,owner,id,profile,cnpj),
      db.prepare('UPDATE sales_profiles SET updated_at=? WHERE id=? AND owner_id=? AND NOT EXISTS(SELECT 1 FROM prospect_links WHERE prospect_id=? AND profile_id=? AND cnpj=?)').bind(stamp,profile,owner,id,profile,cnpj),
      db.prepare('INSERT INTO prospect_links(prospect_id,profile_id,cnpj,owner_id,created_at) VALUES(?,?,?,?,?) ON CONFLICT(prospect_id,profile_id,cnpj) DO NOTHING').bind(id,profile,cnpj,owner,stamp),
    ]);
    const created=Number(results[1].meta.changes)>0,linked=Number(results[6].meta.changes)>0;
    return json({created,linked,profile_id:profile,cnpj,message:created?'Lead qualificado incluído no painel.':'Contato encaminhado; atendimento anterior preservado.'},created?201:200);
  }catch(error){if(isConstraint(error))throw new ApiError(409,'Contato ou atendimento alterado em outra sessão, ou já existe um contato com os mesmos dados. Atualize a lista; nenhum registro foi alterado.');throw error;}
}
export async function handleProspects(request:Request,env:Env,principal:Principal,url:URL):Promise<Response|undefined> {
  const path=url.pathname,owner=principal.accountId,db=env.DB;
  if(!path.startsWith('/api/prospects'))return undefined;
  if(request.method==='GET'&&path==='/api/prospects') {
    const page=pageNumber(url.searchParams.get('page')),status=url.searchParams.get('status')??'',search=(url.searchParams.get('q')??'').slice(0,180).trim();
    const clauses=['p.owner_id=?'],values:unknown[]=[owner];
    if(status){if(!PROSPECT_STATUSES.includes(status))throw new ApiError(400,'Situação inválida');clauses.push('p.status=?');values.push(status);}
    if(search){clauses.push('(p.name LIKE ? OR p.company LIKE ? OR p.phone LIKE ? OR p.email LIKE ? OR p.campaign LIKE ?)');values.push(...Array(5).fill('%'+search+'%'));}
    const where=clauses.join(' AND '),total=Number((await queryFirst(db,`SELECT COUNT(*) AS n FROM prospect_inbox p WHERE ${where}`,values))?.n??0);
    const items=await queryRows(db,`SELECT p.*,(SELECT COUNT(*) FROM prospect_links pl WHERE pl.prospect_id=p.id AND pl.owner_id=p.owner_id) AS linked,
      EXISTS(SELECT 1 FROM contact_suppression cs WHERE cs.owner_id=p.owner_id AND (cs.cnpj=p.cnpj OR EXISTS(SELECT 1 FROM prospect_links pl WHERE pl.prospect_id=p.id AND pl.owner_id=p.owner_id AND pl.cnpj=cs.cnpj))) AS do_not_contact,
      (SELECT metadata_json FROM discovery_sources ds WHERE ds.prospect_id=p.id AND ds.owner_id=p.owner_id ORDER BY ds.last_seen_at DESC LIMIT 1) AS provenance_json
      FROM prospect_inbox p WHERE ${where} ORDER BY p.updated_at DESC,p.id LIMIT 50 OFFSET ?`,[...values,(page-1)*50]);
    for(const item of items){item.provenance=item.provenance_json?parseMetadata(item.provenance_json):null;delete item.provenance_json;item.do_not_contact=!!item.do_not_contact;}
    return json({items,total,page,size:50,summary:await prospectSummary(db,owner)});
  }
  if(request.method==='GET'&&path==='/api/prospects/options')return json({profiles:await queryRows(db,'SELECT id,name FROM sales_profiles WHERE owner_id=? ORDER BY name',[owner])});
  if(request.method==='GET'&&path==='/api/prospects/company') {
    const cnpj=url.searchParams.get('cnpj')??'';if(!/^[A-Z0-9]{14}$/.test(cnpj))throw new ApiError(400,'CNPJ inválido');
    return json({item:await queryFirst(db,`SELECT c.cnpj,c.razao_social,c.nome_fantasia,c.municipio,c.situacao FROM companies c WHERE c.cnpj=? AND ${privateCompanyVisible('c','?')}`,[cnpj,owner])});
  }
  if(request.method==='GET'&&path==='/api/prospects/history') {
    const id=url.searchParams.get('id')??'';
    if(!await queryFirst(db,'SELECT 1 AS ok FROM prospect_inbox WHERE id=? AND owner_id=?',[id,owner]))throw new ApiError(404,'Contato não encontrado');
    return json({items:await queryRows(db,'SELECT event,details,created_at FROM prospect_history WHERE prospect_id=? AND owner_id=? ORDER BY id DESC LIMIT 50',[id,owner])});
  }
  if(request.method==='POST'&&path==='/api/prospects/qualify')return qualify(env,owner,await bodyJson(request,4096));
  if(request.method==='POST'&&path==='/api/prospects/import') {
    const raw=await bodyJson(request),rows=raw.rows;
    if(!Array.isArray(rows)||rows.length<1||rows.length>500)throw new ApiError(400,'Importe de 1 a 500 contatos por arquivo');
    const validated=rows.map((entry,index)=>{try{if(!entry||typeof entry!=='object'||Array.isArray(entry))throw new ApiError(400,'Contato inválido');return validateProspect(entry);}catch(error){throw new ApiError(400,`Linha ${index+1}: ${error instanceof Error?error.message:'Contato inválido'}`);}});
    const stamp=now(),records=await Promise.all(validated.map(async row=>({...row,id:identifier(),owner_id:owner,fingerprint:await prospectFingerprint(row),created_at:stamp,updated_at:stamp})));
    const fields=['id','owner_id','fingerprint',...Object.keys(PROSPECT_FIELDS),'status','created_at','updated_at'];
    const insert=await db.prepare(`INSERT INTO prospect_inbox(${fields.join(',')}) SELECT ${fields.map(k=>`json_extract(value,'$.${k}')`).join(',')} FROM json_each(?) WHERE 1 ON CONFLICT(owner_id,fingerprint) DO NOTHING`).bind(JSON.stringify(records)).run();
    const created=Number(insert.meta.changes);
    return json({created,duplicates:rows.length-created,total_received:rows.length},201);
  }
  const match=/^\/api\/prospects\/([^/]+)$/.exec(path);
  if(request.method==='PUT'&&match) {
    const id=match[1],raw=await bodyJson(request,16384),old=await queryFirst(db,'SELECT * FROM prospect_inbox WHERE id=? AND owner_id=?',[id,owner]);
    if(!old)throw new ApiError(404,'Contato não encontrado');
    if('revision'in raw&&(!Number.isInteger(raw.revision)||raw.revision!==old.revision))throw new ApiError(409,'Contato alterado em outra sessão. Atualize a lista antes de salvar.');
    const row=validateProspect({...old,...raw}),fp=await prospectFingerprint(row),stamp=now(),fields=Object.keys(row),changed=fields.filter(k=>row[k]!==old[k]).join(', ');
    try {
      await db.batch([
        assertSql(db,'EXISTS(SELECT 1 FROM prospect_inbox WHERE id=? AND owner_id=? AND revision=?)',[id,owner,old.revision]),
        db.prepare(`UPDATE prospect_inbox SET ${fields.map(k=>k+'=?').join(',')},fingerprint=?,updated_at=?,revision=revision+1 WHERE id=? AND owner_id=?`).bind(...fields.map(k=>row[k]),fp,stamp,id,owner),
        ...(changed?[db.prepare("INSERT INTO prospect_history(prospect_id,owner_id,event,details,created_at) VALUES(?,?,'updated',?,?)").bind(id,owner,changed,stamp)]:[]),
      ]);
    }catch(error){if(isConstraint(error))throw new ApiError(409,'Contato alterado em outra sessão ou já existe um contato igual nesta conta. Nenhum registro foi alterado.');throw error;}
    return json({ok:true});
  }
  return undefined;
}
