import {ApiError,bodyJson,json,now,queryFirst,queryRows,type Env,type Row} from './runtime';

export const RECEITA_FIELDS:Record<string,number>={cnpj:14,razao_social:300,nome_fantasia:300,situacao:20,data_abertura:10,cnae:7,cnae_descricao:1000,cnaes_secundarios:6000,segmento:120,municipio:120,regiao:120,uf:2,cep:8,bairro:300,logradouro:500,numero:60,telefone:60,email:300,porte:60};
const columns=[...Object.keys(RECEITA_FIELDS),'mei'];
const encoder=new TextEncoder();
const runPattern=/^[0-9]{1,20}-[1-9][0-9]{0,3}$/;
const active="active_lock=1 AND status IN ('loading','receiving') AND expires_at>?";
const publicCompany="COALESCE(companies.uf,'')<>'ZZ' AND COALESCE(companies.situacao,'')<>'TESTE' AND NOT EXISTS(SELECT 1 FROM private_companies p WHERE p.cnpj=companies.cnpj)";
function utc():string{return new Date().toISOString();}
function integer(value:unknown,min:number,max:number,message:string):number {if(typeof value!=='number'||!Number.isSafeInteger(value)||value<min||value>max)throw new ApiError(400,message);return value;}
function runId(value:unknown):string {if(typeof value!=='string'||!runPattern.test(value))throw new ApiError(400,'Identificador GitHub inválido');return value;}
function assertion(db:D1Database,condition:string,values:unknown[]):D1PreparedStatement{return db.prepare(`SELECT CASE WHEN (${condition}) THEN 1 ELSE json('receita_import_conflict') END AS ok`).bind(...values);}
function conflict(error:unknown):boolean{return /constraint|malformed json|receita_import_conflict/i.test(String(error));}
function canonical(value:Row[]):string{return JSON.stringify(value.map(row=>Object.fromEntries(Object.keys(row).sort().map(k=>[k,row[k]]))));}
export async function receitaDigest(rows:Row[]):Promise<string> {return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(canonical(rows)))),b=>b.toString(16).padStart(2,'0')).join('');}
async function authorize(request:Request,env:Env):Promise<void> {
  const secret=env.RECEITA_IMPORT_SECRET;
  if(!secret||!/^[-A-Za-z0-9_]{48,256}$/.test(secret))throw new ApiError(503,'Importação oficial ainda não configurada');
  const header=request.headers.get('Authorization')??'',provided=header.length<=512&&header.startsWith('Bearer ')?header.slice(7):'';
  const [a,b]=await Promise.all([crypto.subtle.digest('SHA-256',encoder.encode(secret)),crypto.subtle.digest('SHA-256',encoder.encode(provided))]);
  // Compare two fixed-length digests without an early exit or length-dependent comparison.
  const left=new Uint8Array(a),right=new Uint8Array(b);let difference=0;
  for(let i=0;i<32;i++)difference|=left[i]^right[i];
  if(difference!==0)throw new ApiError(401,'Autenticação da importação necessária');
}
function companyRows(value:unknown):Row[] {
  if(!Array.isArray(value)||value.length<1||value.length>500)throw new ApiError(400,'Envie de 1 a 500 estabelecimentos por lote');
  let previous='';
  return value.map(item=>{
    if(!item||typeof item!=='object'||Array.isArray(item)||Object.keys(item).some(k=>!columns.includes(k)))throw new ApiError(400,'Lote deve conter somente campos públicos da Receita');
    const row:Row={};
    for(const [field,maximum] of Object.entries(RECEITA_FIELDS)) {
      const text=item[field];
      if(typeof text!=='string'||[...text].length>maximum||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text))throw new ApiError(400,'Campo público inválido: '+field);
      row[field]=text;
    }
    if(!/^[A-Z0-9]{14}$/.test(String(row.cnpj))||String(row.cnpj)<=previous)throw new ApiError(400,'CNPJs devem ser únicos e crescentes em cada lote');
    previous=String(row.cnpj);
    if(row.uf!=='RS'||!['ATIVA','NULA','SUSPENSA','INAPTA','BAIXADA'].includes(String(row.situacao))&&!/^\d{2}$/.test(String(row.situacao))||!String(row.razao_social).trim())throw new ApiError(400,'Somente estabelecimentos oficiais do RS são permitidos');
    if(!/^\d{7}$/.test(String(row.cnae))||row.cep!==''&&!/^\d{8}$/.test(String(row.cep)))throw new ApiError(400,'CNAE ou CEP inválido');
    if(row.data_abertura!==''&&(!/^\d{4}-\d{2}-\d{2}$/.test(String(row.data_abertura))||!Number.isFinite(Date.parse(String(row.data_abertura)+'T00:00:00Z'))))throw new ApiError(400,'Data oficial inválida');
    row.mei=integer(item.mei,0,1,'Opção MEI inválida');return row;
  });
}
function catalogRows(value:unknown):Row[] {
  if(!Array.isArray(value)||!value.length||value.length>2000||encoder.encode(JSON.stringify(value)).length>512*1024)throw new ApiError(400,'Catálogo CNAE inválido ou acima do limite');
  let previous='';
  return value.map(row=>{
    if(!row||typeof row!=='object'||Array.isArray(row)||Object.keys(row).some(k=>!['codigo','descricao'].includes(k))||typeof row.codigo!=='string'||!/^\d{7}$/.test(row.codigo)||row.codigo<=previous||typeof row.descricao!=='string'||!row.descricao.trim()||[...row.descricao].length>1000||/[\x00-\x1f]/.test(row.descricao))throw new ApiError(400,'Catálogo CNAE deve conter códigos únicos e crescentes');
    previous=row.codigo;return {codigo:row.codigo,descricao:row.descricao};
  });
}
async function published(db:D1Database):Promise<Row> {return Object.fromEntries((await queryRows(db,"SELECT key,value FROM sync_meta WHERE key IN ('competencia','cnae_catalog_competencia','sincronizado_em')")).map(r=>[String(r.key),r.value]));}
function safeJob(row:Row|null):Row|null {
  if(!row)return null;
  const expired=!!row.active_lock&&String(row.expires_at)<=utc();
  return {id:row.id,competencia:row.competencia,mode:row.mode,status:expired?'expired':row.status,expected_rows:row.expected_rows,received_rows:row.received_rows,applied_rows:row.applied_rows,next_sequence:row.next_sequence,phase:expired?'Execução anterior expirou':row.phase,progress:row.progress,error_code:expired?'expired':row.error_code,started_at:row.started_at,updated_at:row.updated_at,expires_at:row.expires_at,finished_at:row.finished_at};
}
async function status(env:Env,id?:string):Promise<Row> {
  const meta=await published(env.DB),job=await queryFirst(env.DB,id?'SELECT * FROM sync_import_runs WHERE id=?':'SELECT * FROM sync_import_runs ORDER BY started_at DESC,id DESC LIMIT 1',id?[id]:[]);
  const parameter=await queryFirst(env.DB,"SELECT value FROM admin_parameters WHERE key='sync_scheduler'");
  return {competencia:meta.competencia??null,cnae_catalog_competencia:meta.cnae_catalog_competencia??null,sincronizado_em:meta.sincronizado_em??null,enabled:parameter?.value!=='false',automation_configured:env.RECEITA_SYNC_AUTOMATION==='1',job:safeJob(job)};
}
export async function receitaSyncState(env:Env):Promise<Row> {
  const state=await status(env),job=state.job as Row|null,running=job&&['loading','receiving'].includes(String(job.status));
  return {status:running?'running':job&&['failed','expired'].includes(String(job.status))?'error':state.competencia?'complete':'idle',fase:job?.phase??'Aguardando verificação da Receita',progresso:job?.progress??(state.competencia?100:0),mensagem:running?'Carga oficial em execução no GitHub Actions.':job&&['failed','expired'].includes(String(job.status))?'A última carga não foi concluída. A competência publicada foi preservada.':'A atualização oficial depende da disponibilidade da Receita e do GitHub Actions.',competencia:state.competencia,importados:job?.applied_rows??0,baixados:0,total_bytes:0,iniciado_em:job?.started_at??null,finalizado_em:job?.finished_at??state.sincronizado_em,automatic_sync:state.automation_configured,local:{competencia:state.competencia,cnae_catalog_competencia:state.cnae_catalog_competencia,sincronizado_em:state.sincronizado_em}};
}
async function start(env:Env,raw:Row):Promise<Response> {
  const id=runId(raw.run_id),month=raw.competencia,mode=raw.mode??'full';
  if(typeof month!=='string'||!/^20\d{2}-(?:0[1-9]|1[0-2])$/.test(month)||!['full','catalog'].includes(String(mode)))throw new ApiError(400,'Competência ou modalidade inválida');
  const expected=raw.expected_rows===undefined||raw.expected_rows===null?null:integer(raw.expected_rows,mode==='catalog'?0:1,1000000,'Quantidade esperada inválida');
  if(mode==='catalog'&&expected!==null&&expected!==0)throw new ApiError(400,'Atualização CNAE não recebe estabelecimentos');
  const db=env.DB,stamp=utc(),existing=await queryFirst(db,'SELECT * FROM sync_import_runs WHERE id=?',[id]),meta=await published(db);
  if(existing&&(existing.competencia!==month||existing.mode!==mode||expected!==null&&existing.expected_rows!==null&&existing.expected_rows!==expected))throw new ApiError(409,'Identificador reutilizado com dados diferentes');
  if(existing?.status==='complete')return json({replay:true,job:safeJob(existing)});
  if(existing&&['failed','expired'].includes(String(existing.status)))throw new ApiError(409,'Execução encerrada; use uma nova tentativa GitHub');
  if(mode==='full'&&String(meta.competencia??'')>=month||mode==='catalog'&&meta.competencia!==month)throw new ApiError(409,'A competência não requer esta modalidade de atualização');
  const expires=new Date(Date.parse(stamp)+6*3600000).toISOString();
  try {await db.batch([
    db.prepare("UPDATE sync_import_runs SET status='expired',active_lock=NULL,finished_at=?,error_code='expired',phase='Execução anterior expirou' WHERE active_lock=1 AND expires_at<=?").bind(stamp,stamp),
    assertion(db,"NOT EXISTS(SELECT 1 FROM sync_import_runs WHERE active_lock=1 AND id<>?) AND NOT EXISTS(SELECT 1 FROM sync_import_runs WHERE id=? AND (active_lock IS NULL OR expires_at<=? OR competencia<>? OR mode<>? OR (? IS NOT NULL AND expected_rows IS NOT NULL AND expected_rows<>?))) AND (?='full' AND COALESCE((SELECT value FROM sync_meta WHERE key='competencia'),'')<? OR ?='catalog' AND (SELECT value FROM sync_meta WHERE key='competencia')=?)",[id,id,stamp,month,mode,expected,expected,mode,month,mode,month]),
    db.prepare(`INSERT INTO sync_import_runs(id,competencia,mode,status,active_lock,expected_rows,started_at,updated_at,expires_at,phase,progress) VALUES(?,?,?,?,1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET expected_rows=COALESCE(excluded.expected_rows,sync_import_runs.expected_rows),status=CASE WHEN COALESCE(excluded.expected_rows,sync_import_runs.expected_rows) IS NULL THEN 'loading' ELSE 'receiving' END,updated_at=excluded.updated_at,phase=CASE WHEN excluded.expected_rows IS NULL THEN sync_import_runs.phase ELSE 'Enviando estabelecimentos oficiais' END,progress=CASE WHEN excluded.expected_rows IS NULL THEN sync_import_runs.progress ELSE MAX(85,sync_import_runs.progress) END`).bind(id,month,mode,expected===null?'loading':'receiving',expected,stamp,stamp,expires,expected===null?'Carregando fonte oficial':'Enviando estabelecimentos oficiais',expected===null?0:85),
  ]);}catch(error){if(conflict(error))throw new ApiError(409,'Outra importação está ativa ou esta execução expirou');throw error;}
  return json({job:safeJob(await queryFirst(db,'SELECT * FROM sync_import_runs WHERE id=?',[id]))},existing?200:201);
}
async function batch(env:Env,raw:Row):Promise<Response> {
  const id=runId(raw.run_id),sequence=integer(raw.sequence,0,10000,'Sequência inválida'),rows=companyRows(raw.rows),hash=await receitaDigest(rows);
  if(typeof raw.sha256!=='string'||raw.sha256!==hash)throw new ApiError(400,'SHA-256 do lote não confere');
  const db=env.DB,prior=await queryFirst(db,'SELECT sha256,row_count,applied_rows FROM sync_import_batches WHERE run_id=? AND sequence=?',[id,sequence]);
  if(prior){if(prior.sha256!==hash||prior.row_count!==rows.length)throw new ApiError(409,'Sequência já usada com conteúdo diferente');return json({replay:true,sequence,received:prior.row_count,applied:prior.applied_rows});}
  const stamp=utc(),first=String(rows[0].cnpj),last=String(rows[rows.length-1].cnpj),payload=canonical(rows);
  const updates=columns.filter(k=>k!=='cnpj').map(k=>k==='cnae_descricao'?"cnae_descricao=CASE WHEN excluded.cnae_descricao<>'' THEN excluded.cnae_descricao ELSE companies.cnae_descricao END":`${k}=excluded.${k}`);
  const changed=columns.filter(k=>k!=='cnpj').map(k=>k==='cnae_descricao'?"(excluded.cnae_descricao<>'' AND companies.cnae_descricao IS NOT excluded.cnae_descricao)":`companies.${k} IS NOT excluded.${k}`).join(' OR ');
  try {await db.batch([
    assertion(db,`EXISTS(SELECT 1 FROM sync_import_runs WHERE id=? AND ${active} AND status='receiving' AND mode='full' AND expected_rows IS NOT NULL AND next_sequence=? AND received_rows+?<=expected_rows AND last_cnpj<?)`,[id,stamp,sequence,rows.length,first]),
    db.prepare(`INSERT INTO companies(${columns.join(',')},data_source) SELECT ${columns.map(k=>`json_extract(j.value,'$.${k}')`).join(',')},'Receita Federal' FROM json_each(?) j WHERE NOT EXISTS(SELECT 1 FROM private_companies p WHERE p.cnpj=json_extract(j.value,'$.cnpj')) AND NOT EXISTS(SELECT 1 FROM companies c WHERE c.cnpj=json_extract(j.value,'$.cnpj') AND (COALESCE(c.uf,'')='ZZ' OR COALESCE(c.situacao,'')='TESTE')) ON CONFLICT(cnpj) DO UPDATE SET ${updates.join(',')},data_source='Receita Federal' WHERE ${publicCompany} AND (${changed} OR companies.data_source IS NOT 'Receita Federal')`).bind(payload),
    db.prepare('INSERT INTO sync_import_batches(run_id,sequence,sha256,row_count,applied_rows,first_cnpj,last_cnpj,created_at) VALUES(?,?,?,?,changes(),?,?,?)').bind(id,sequence,hash,rows.length,first,last,stamp),
    db.prepare("UPDATE sync_import_runs SET received_rows=received_rows+?,applied_rows=applied_rows+(SELECT applied_rows FROM sync_import_batches WHERE run_id=? AND sequence=?),next_sequence=next_sequence+1,last_cnpj=?,updated_at=?,phase='Enviando estabelecimentos oficiais',progress=85.0+10.0*(received_rows+?)/expected_rows WHERE id=?").bind(rows.length,id,sequence,last,stamp,rows.length,id),
  ]);}catch(error){
    if(conflict(error)) {
      const raced=await queryFirst(db,'SELECT sha256,row_count,applied_rows FROM sync_import_batches WHERE run_id=? AND sequence=?',[id,sequence]);
      if(raced?.sha256===hash&&raced.row_count===rows.length)return json({replay:true,sequence,received:raced.row_count,applied:raced.applied_rows});
      throw new ApiError(409,'Lote fora da sequência, quantidade divergente ou execução encerrada');
    }
    throw error;
  }
  const saved=await queryFirst(db,'SELECT row_count,applied_rows FROM sync_import_batches WHERE run_id=? AND sequence=?',[id,sequence]);
  return json({replay:false,sequence,received:saved!.row_count,applied:saved!.applied_rows});
}
async function finalize(env:Env,raw:Row):Promise<Response> {
  const id=runId(raw.run_id),count=integer(raw.expected_batches,0,10001,'Quantidade de lotes inválida'),catalog=catalogRows(raw.catalog),hash=await receitaDigest(catalog);
  if(raw.catalog_sha256!==hash)throw new ApiError(400,'SHA-256 do catálogo CNAE não confere');
  const db=env.DB,job=await queryFirst(db,'SELECT * FROM sync_import_runs WHERE id=?',[id]);
  if(!job)throw new ApiError(404,'Importação não encontrada');
  if(job.status==='complete') {if(job.catalog_sha256!==hash||job.next_sequence!==count)throw new ApiError(409,'Finalização reutilizada com dados diferentes');return json({complete:true,replay:true,competencia:job.competencia});}
  const stamp=utc(),localTime=now();
  try {await db.batch([
    assertion(db,`EXISTS(SELECT 1 FROM sync_import_runs WHERE id=? AND ${active} AND expected_rows IS NOT NULL AND received_rows=expected_rows AND next_sequence=? AND (mode='full' AND COALESCE((SELECT value FROM sync_meta WHERE key='competencia'),'')<competencia OR mode='catalog' AND (SELECT value FROM sync_meta WHERE key='competencia')=competencia)) AND (SELECT COUNT(*) FROM sync_import_batches WHERE run_id=?)=? AND COALESCE((SELECT SUM(row_count) FROM sync_import_batches WHERE run_id=?),0)=(SELECT expected_rows FROM sync_import_runs WHERE id=?) AND (?=0 OR (SELECT MIN(sequence) FROM sync_import_batches WHERE run_id=?)=0 AND (SELECT MAX(sequence) FROM sync_import_batches WHERE run_id=?)=?-1)`,[id,stamp,count,id,count,id,id,count,id,id,count]),
    db.prepare("INSERT INTO cnae_catalog(codigo,descricao) SELECT json_extract(value,'$.codigo'),json_extract(value,'$.descricao') FROM json_each(?) WHERE 1 ON CONFLICT(codigo) DO UPDATE SET descricao=excluded.descricao WHERE cnae_catalog.descricao IS NOT excluded.descricao").bind(canonical(catalog)),
    db.prepare(`UPDATE companies SET cnae_descricao=(SELECT descricao FROM cnae_catalog WHERE codigo=companies.cnae) WHERE uf='RS' AND ${publicCompany} AND EXISTS(SELECT 1 FROM cnae_catalog WHERE codigo=companies.cnae AND descricao IS NOT companies.cnae_descricao)`),
    db.prepare("INSERT INTO sync_meta(key,value) SELECT 'competencia',competencia FROM sync_import_runs WHERE id=? AND mode='full' ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(id),
    db.prepare("INSERT INTO sync_meta(key,value) SELECT 'cnae_catalog_competencia',competencia FROM sync_import_runs WHERE id=? ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(id),
    db.prepare("INSERT INTO sync_meta(key,value) VALUES('sincronizado_em',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(localTime),
    db.prepare("UPDATE sync_import_runs SET status='complete',active_lock=NULL,phase='Sincronização concluída',progress=100,updated_at=?,finished_at=?,catalog_sha256=?,catalog_count=? WHERE id=?").bind(stamp,stamp,hash,catalog.length,id),
  ]);}catch(error){if(conflict(error))throw new ApiError(409,'Finalização recusada: faltam lotes, registros ou a execução expirou');throw error;}
  return json({complete:true,replay:false,competencia:job.competencia,received:job.received_rows,applied:job.applied_rows,catalog_count:catalog.length});
}
export async function handleReceita(request:Request,env:Env,url=new URL(request.url)):Promise<Response|undefined> {
  if(url.pathname!=='/api/internal/receita')return undefined;
  if(request.method!=='POST')throw new ApiError(405,'Use POST para a importação oficial');
  await authorize(request,env);
  const raw=await bodyJson(request,2*1024*1024);
  if(raw.action==='status') {
    const id=raw.run_id===undefined?undefined:runId(raw.run_id);
    if(id&&raw.progress!==undefined) {
      const progress=raw.progress;if(typeof progress!=='number'||!Number.isFinite(progress)||progress<0||progress>85)throw new ApiError(400,'Progresso inválido');
      // Only fixed phase keys enter user-visible state; remote error strings/data are never logged.
      const phases:Record<string,string>={catalog:'Consultando catálogo oficial',download:'Baixando arquivos oficiais',parse:'Filtrando estabelecimentos do RS',join:'Cruzando dados oficiais',ready:'Preparando envio dos lotes'};
      const phase=typeof raw.phase==='string'?phases[raw.phase]:undefined;if(!phase)throw new ApiError(400,'Fase inválida');
      await env.DB.prepare(`UPDATE sync_import_runs SET phase=?,progress=MAX(progress,?),updated_at=? WHERE id=? AND ${active} AND status='loading'`).bind(phase,progress,utc(),id,utc()).run();
    }
    return json(await status(env,id));
  }
  if(raw.action==='start')return start(env,raw);
  if(raw.action==='batch')return batch(env,raw);
  if(raw.action==='finalize')return finalize(env,raw);
  if(raw.action==='fail') {
    const id=runId(raw.run_id),stamp=utc();
    await env.DB.prepare("UPDATE sync_import_runs SET status='failed',active_lock=NULL,phase='Falha na sincronização',error_code='pipeline_failed',updated_at=?,finished_at=? WHERE id=? AND active_lock=1 AND status IN ('loading','receiving')").bind(stamp,stamp,id).run();
    return json({ok:true});
  }
  throw new ApiError(400,'Ação de importação inválida');
}
