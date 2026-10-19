/** Current Python administration/help contracts on D1. No filesystem or account API access. */
import definitions from './admin-definitions.json';
import helpDefaults from './help-definitions.json';
import { hashPassword } from './security-current';
import { receitaSyncState } from './receita-current';
import { ApiError, bodyJson, headers, json, now, queryFirst, queryRows, type Env, type Principal, type Row } from './runtime';

interface Field { group:string; label:string; type:string; default:unknown; min?:number; max?:number; env?:string; options?:Record<string,string>; help?:string }
const fields = definitions.fields as Record<string,Field>;
const categories:Record<string,string> = definitions.categories;
const actions:Record<string,string> = definitions.actions;
const adminRoles = ['admin','administrador','gestor'];
const conflict = 'Outra configuração foi salva. Atualize o painel antes de salvar.';
const articleConflict = 'Artigo alterado por outra sessão. Atualize antes de salvar.';
const ownKeys = (value:Row, allowed:string[], message:string) => { if (Object.keys(value).some(key=>!allowed.includes(key))) throw new ApiError(400,message); };
const binding = (env:Env,key:string):string => { const value = (env as unknown as Row)[key]; return typeof value==='string' ? value.trim() : ''; };
const isObject = (value:unknown):value is Row => !!value && typeof value==='object' && !Array.isArray(value);

export async function adminCsrf(env:Env, principal:Principal):Promise<string> {
  if (!env.SESSION_SECRET || env.SESSION_SECRET.length<32) throw new ApiError(503,'Proteção da sessão administrativa indisponível');
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey('raw',encoder.encode(env.SESSION_SECRET),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  return Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,encoder.encode('admin-csrf:'+principal.username))),byte=>byte.toString(16).padStart(2,'0')).join('');
}
async function guard(request:Request,env:Env,principal:Principal,write=false) {
  if (principal.role!=='admin') throw new ApiError(403,'Área exclusiva do administrador');
  if (!write) return;
  const origin = request.headers.get('Origin');
  if ((origin && origin!==new URL(request.url).origin) || request.headers.get('Sec-Fetch-Site')==='cross-site') throw new ApiError(403,'Origem não permitida');
  const expected = await adminCsrf(env,principal), supplied = request.headers.get('X-Radar-CSRF') || '';
  let difference = expected.length ^ supplied.length;
  for(let index=0;index<expected.length;index++) difference |= expected.charCodeAt(index) ^ (supplied.charCodeAt(index)||0);
  if(difference) throw new ApiError(403,'Atualize o painel para renovar a proteção da sessão');
}
async function revision(db:D1Database):Promise<number> {
  await db.prepare('INSERT OR IGNORE INTO admin_revision(id,revision) VALUES(1,0)').run();
  return Number((await queryFirst(db,'SELECT revision FROM admin_revision WHERE id=1'))?.revision ?? 0);
}
/** D1 batch is transactional. The NOT NULL constraint aborts the entire stale batch. */
async function mutate(db:D1Database,expected:number,statements:D1PreparedStatement[],actor:string,action:string,detail:string):Promise<number> {
  try {
    const result = await db.batch([
      db.prepare('UPDATE admin_revision SET revision=CASE WHEN revision=? THEN revision+1 ELSE NULL END WHERE id=1 RETURNING revision').bind(expected),
      ...statements,
      db.prepare('INSERT INTO admin_audit(actor,action,detail,created_at) VALUES(?,?,?,?)').bind(actor,action,detail,now()),
    ]);
    if(!result[0].results?.length) throw new ApiError(409,conflict);
    return expected+1;
  } catch(error) {
    if(error instanceof ApiError) throw error;
    if(/NOT NULL constraint failed: admin_revision\.revision/i.test(String(error))) throw new ApiError(409,conflict);
    if(/UNIQUE constraint failed/i.test(String(error))) throw new ApiError(409,'Usuário ou e-mail já utilizado; nenhuma alteração aplicada');
    throw error;
  }
}

export function validateParameter(key:string,value:unknown):unknown {
  const spec=fields[key]; if(!spec) throw new ApiError(400,'Campos de parâmetros inválidos');
  if(spec.type==='bool') { if(typeof value!=='boolean') throw new ApiError(400,spec.label+': opção inválida'); return value; }
  if(spec.type==='int') { if(typeof value!=='number'||!Number.isSafeInteger(value)||value<spec.min!||value>spec.max!) throw new ApiError(400,`${spec.label}: ${spec.min} a ${spec.max}`); return value; }
  if(typeof value!=='string') throw new ApiError(400,spec.label+': texto inválido');
  const clean=value.trim();
  if(clean.length>(spec.max??500)||/[\x00-\x1f]/.test(clean)) throw new ApiError(400,spec.label+': tamanho ou caracteres inválidos');
  if(spec.type==='select'&&!Object.hasOwn(spec.options||{},clean)) throw new ApiError(400,spec.label+': opção inválida');
  if(spec.type==='text'&&!clean) throw new ApiError(400,spec.label+': preencha o campo');
  if(spec.type==='path'&&clean) throw new ApiError(400,'Cloudflare D1 não possui pasta Windows. Configure a proteção de backups no ambiente Cloudflare.');
  if(spec.type==='secret') throw new ApiError(400,'Esta chave é gerenciada por um binding secreto Cloudflare; não pode ser alterada pelo navegador.');
  if(spec.type==='url'&&clean) {
    let valid=false;
    try { const url=new URL(clean); const host=url.hostname.toLowerCase(); valid=url.protocol==='https:'&&!url.username&&!url.password&&!url.hash&&!url.search&&(!url.port||url.port==='443')&&['base44.app','base44.com'].some(domain=>host===domain||host.endsWith('.'+domain)); } catch { /* Validation below. */ }
    if(!valid) throw new ApiError(400,'Informe uma URL HTTPS Base44, sem senha, fragmento ou parâmetros.');
  }
  return clean;
}
function parametersStatement(env:Env):D1PreparedStatement {
  // Exclude secrets at SQL boundary: imported DPAPI ciphertext never enters response handling.
  const secretKeys=Object.entries(fields).filter(([,spec])=>spec.type==='secret').map(([key])=>key);
  return env.DB.prepare(`SELECT key,value FROM admin_parameters WHERE key NOT IN (${secretKeys.map(()=>'?').join(',')})`).bind(...secretKeys);
}
function parameterValues(env:Env,stored:Row[]):Row {
  const values:Row={};
  for(const [key,spec] of Object.entries(fields)) {
    if(spec.type==='secret') continue;
    let value:unknown=spec.default;
    const source=stored.find(row=>row.key===key);
    if(source) { try { value=JSON.parse(String(source.value)); } catch { value=spec.default; } }
    else if(spec.env) { const raw=binding(env,spec.env); if(raw) value=spec.type==='bool' ? !['0','false'].includes(raw.toLowerCase()) : spec.type==='int' ? Number(raw) : raw; }
    // A migrated Windows path is retained in D1 but has no meaning in this runtime.
    try { values[key]=spec.type==='path' ? '' : validateParameter(key,value); } catch { values[key]=spec.default; }
  }
  return values;
}
export async function adminValues(env:Env):Promise<Row> {
  return parameterValues(env,(await parametersStatement(env).all<Row>()).results||[]);
}
export async function runtimeConfig(env:Env,principal:Principal):Promise<Row> {
  const values=await adminValues(env);
  return {...Object.fromEntries(['site_name','copyright','default_theme','animations','max_columns','test_leads','serpro_visible'].map(key=>[key,values[key]])),is_admin:principal.role==='admin'};
}
async function configSnapshot(env:Env,principal:Principal):Promise<Row> {
  await revision(env.DB);
  // A single D1 batch pairs displayed values with their exact revision.
  const snapshot=await env.DB.batch<Row>([parametersStatement(env),env.DB.prepare('SELECT revision FROM admin_revision WHERE id=1')]);
  const values=parameterValues(env,snapshot[0].results||[]);
  const list=Object.entries(fields).map(([key,spec])=>{
    const {env:variable,default:_default,...visible}=spec;
    return {key,...visible,...(spec.type==='secret'?{configured:!!binding(env,variable||''),readonly:true,storage:binding(env,variable||'')?'environment':'environment-only'}:{}),...(key==='backup_directory'||key==='backup_daily'?{supported:false,help:'A cópia SQLite e a pasta Windows não são executadas pelo Worker. Use a exportação e o Time Travel administrativos do Cloudflare D1.'}:{})};
  });
  return {revision:Number(snapshot[1].results[0]?.revision||0),values,fields:list,free_only:true,csrf:await adminCsrf(env,principal),username:principal.username,
    base44_status:values.base44_endpoint?'Destino configurado; receptor e sincronização ainda não validados':'Não conectado',serpro_status:'Oculto / consultas desativadas — custos não autorizados'};
}
async function saveConfig(env:Env,principal:Principal,payload:Row) {
  ownKeys(payload,['revision','values'],'Parâmetros inválidos');
  if(typeof payload.revision!=='number'||!Number.isSafeInteger(payload.revision)||payload.revision<0) throw new ApiError(400,'Informe a revisão carregada');
  if(!isObject(payload.values)||!Object.keys(payload.values).length||Object.keys(payload.values).some(key=>!Object.hasOwn(fields,key))) throw new ApiError(400,'Campos de parâmetros inválidos');
  const entries=Object.entries(payload.values).map(([key,value])=>[key,validateParameter(key,value)] as const);
  const current=await revision(env.DB); if(current!==payload.revision) throw new ApiError(409,conflict);
  const stamp=now();
  const saved=await mutate(env.DB,current,entries.map(([key,value])=>env.DB.prepare('INSERT INTO admin_parameters(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at').bind(key,JSON.stringify(value),stamp)),principal.username,'parameters.updated',entries.map(([key])=>fields[key].label).join(', '));
  return json({saved:true,revision:saved});
}

async function saveAccount(env:Env,principal:Principal,payload:Row) {
  ownKeys(payload,['id','name','username','email','role','is_active','password'],'Campos de conta inválidos');
  const name=typeof payload.name==='string'?payload.name.trim():'';
  const username=typeof payload.username==='string'?payload.username.trim():'';
  if(payload.email!==undefined&&typeof payload.email!=='string') throw new ApiError(400,'E-mail inválido');
  const email=typeof payload.email==='string'?payload.email.trim().toLowerCase():'';
  const role=payload.role===undefined?'vendedor':payload.role,active=payload.is_active===undefined?true:payload.is_active,password=payload.password===undefined?'':payload.password;
  const identifier=payload.id;
  if(identifier!==undefined&&(typeof identifier!=='string'||!identifier||identifier.length>100)) throw new ApiError(400,'Conta inválida');
  if(name.length<2||name.length>100||!/^[-A-Za-z0-9_.]{3,40}$/.test(username)) throw new ApiError(400,'Nome: 2 a 100 caracteres. Usuário: 3 a 40 letras, números, ponto, traço ou sublinhado.');
  if(email&&(email.length>180||! /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))) throw new ApiError(400,'E-mail inválido');
  if(!['admin','vendedor'].includes(String(role))||typeof active!=='boolean') throw new ApiError(400,'Permissão ou situação inválida');
  if(binding(env,'RADAR_ADMIN_USER')&&username.toLowerCase()===binding(env,'RADAR_ADMIN_USER').toLowerCase()) throw new ApiError(400,'Este usuário é o administrador do servidor; não pode ser duplicado em outra conta.');
  if(typeof password!=='string'||password.length>200) throw new ApiError(400,'Senha inválida');
  if((password||!identifier)&&(password.length<10||!/[A-Za-zÀ-ÿ]/.test(password)||!/[0-9]/.test(password))) throw new ApiError(400,'Senha: pelo menos 10 caracteres, uma letra e um número');
  const expected=await revision(env.DB);
  const old=identifier?await queryFirst(env.DB,'SELECT * FROM user_accounts WHERE id=?',[identifier]):null;
  if(identifier&&!old) throw new ApiError(404,'Conta não encontrada');
  if(old&&old.id===principal.accountId&&(!active||role!=='admin'||username.toLowerCase()!==String(old.username).toLowerCase())) throw new ApiError(400,'Não é permitido desativar, renomear ou retirar a própria administração');
  if(old&&old.is_active&&adminRoles.includes(String(old.role).toLowerCase())&&(!active||role!=='admin')) {
    const count=await queryFirst(env.DB,"SELECT COUNT(*) AS total FROM user_accounts WHERE is_active=1 AND lower(role) IN ('admin','administrador','gestor')");
    if(Number(count?.total)<=1) throw new ApiError(400,'Mantenha pelo menos um administrador ativo');
  }
  if(await queryFirst(env.DB,'SELECT id FROM user_accounts WHERE (username=? COLLATE NOCASE OR (?<>\'\' AND email=? COLLATE NOCASE)) AND id<>?',[username,email,email,identifier||''])) throw new ApiError(409,'Usuário ou e-mail já utilizado; nenhuma alteração aplicada');
  const id=typeof identifier==='string'?identifier:'conta-'+crypto.randomUUID().replaceAll('-','');
  const stamp=now(),statements:D1PreparedStatement[]=[];
  const passwordData=(password||!identifier)?await hashPassword(password):undefined;
  if(old) {
    statements.push(env.DB.prepare('UPDATE user_accounts SET name=?,username=?,email=?,role=?,is_active=?,updated_at=? WHERE id=?').bind(name,username,email,role,Number(active),stamp,id));
    if(passwordData) statements.push(env.DB.prepare('UPDATE user_accounts SET password_salt=?,password_hash=? WHERE id=?').bind(passwordData.salt,passwordData.digest,id));
    if(password||username!==old.username||active!==Boolean(old.is_active)||role!==old.role) {
      const names=new Set([String(old.username).toLowerCase(),username.toLowerCase()]);
      for(const account of names) statements.push(env.DB.prepare('INSERT INTO admin_session_revisions(username,revision) VALUES(?,1) ON CONFLICT(username) DO UPDATE SET revision=revision+1').bind(account));
    }
  } else {
    statements.push(env.DB.prepare('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)').bind(id,name,username,email,passwordData!.digest,passwordData!.salt,role,Number(active),stamp,stamp));
    const initials=name.split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase();
    statements.push(env.DB.prepare('INSERT INTO sales_profiles(id,name,role,email,initials,color,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)').bind('usuario-'+crypto.randomUUID().replaceAll('-','').slice(0,12),name,'Vendedor',email,initials,'#b82043',id,stamp,stamp));
  }
  await mutate(env.DB,expected,statements,principal.username,old?'account.updated':'account.created',`Conta ${username}; permissão ${role}; ativa ${active}`+(password?'; senha redefinida':''));
  return json({saved:true,id});
}
async function saveCommercial(env:Env,principal:Principal,payload:Row) {
  ownKeys(payload,['profile_id','contact_sla_hours','stalled_days'],'Regra comercial inválida');
  const id=payload.profile_id,hours=payload.contact_sla_hours,days=payload.stalled_days;
  if(typeof id!=='string'||!id||id.length>100) throw new ApiError(400,'Responsável inválido');
  const inherit=hours===null&&days===null;
  if(!inherit) {validateParameter('contact_sla_hours',hours);validateParameter('stalled_days',days);}
  const expected=await revision(env.DB);
  if(!await queryFirst(env.DB,'SELECT id FROM sales_profiles WHERE id=?',[id])) throw new ApiError(404,'Responsável não encontrado');
  const statement=inherit?env.DB.prepare('DELETE FROM commercial_settings WHERE profile_id=?').bind(id):env.DB.prepare('INSERT INTO commercial_settings(profile_id,contact_sla_hours,stalled_days) VALUES(?,?,?) ON CONFLICT(profile_id) DO UPDATE SET contact_sla_hours=excluded.contact_sla_hours,stalled_days=excluded.stalled_days').bind(id,hours,days);
  await mutate(env.DB,expected,[statement],principal.username,'commercial.updated','Responsável '+id+(inherit?'; padrão geral':`; SLA ${hours}h; negociação parada ${days} dias`));
  return json({saved:true});
}
async function systemState(env:Env) {
  const tables={companies:'companies',accounts:'user_accounts',profiles:'sales_profiles',leads:'sales_profile_leads',campaigns:'discovery_campaigns'};
  const counts:Row={}; for(const [key,table] of Object.entries(tables)) counts[key]=Number((await queryFirst(env.DB,`SELECT COUNT(*) AS total FROM ${table}`))?.total||0);
  const accounts=await queryRows(env.DB,`SELECT a.id,a.name,a.username,a.email,a.role,a.is_active,a.last_login_at,COUNT(DISTINCT p.id) AS profiles,COUNT(l.cnpj) AS leads FROM user_accounts a LEFT JOIN sales_profiles p ON p.owner_id=a.id LEFT JOIN sales_profile_leads l ON l.profile_id=p.id GROUP BY a.id ORDER BY a.name`);
  const profiles=await queryRows(env.DB,'SELECT p.id,p.name,p.owner_id,c.contact_sla_hours,c.stalled_days FROM sales_profiles p LEFT JOIN commercial_settings c ON c.profile_id=p.id ORDER BY p.name');
  const audit=await queryRows(env.DB,'SELECT id,actor,action,detail,created_at FROM admin_audit ORDER BY id DESC LIMIT 80');
  const values=await adminValues(env);
  return json({counts,accounts,profiles,audit,db_bytes:null,environment:env.RADAR_ENV==='production'?'production':'local',secrets_storage:'Bindings secretos Cloudflare',session_protected:env.SESSION_SECRET.length>=32,backups:[],
    backup_protection:{state:'external-management',secondary_verified:false,message:'D1 é gerenciado pela Cloudflare. Backup, exportação e ensaio de recuperação exigem o fluxo administrativo D1; nenhuma cópia SQLite foi criada por este painel.'},
    local_osm:{ready:false,count:0,cities:[],message:'O índice regional em disco do Windows não está disponível no Worker. Requer serviço de dados preparado para Cloudflare.',update:{status:'unavailable',message:'Atualização local indisponível no Worker'}},osm_mode:values.capture_osm_mode,collector_ready:false,
    sync:await receitaSyncState(env),
    capabilities:{database:'D1',sqlite_download:false,windows_backup_directory:false,backup_recovery:false,local_osm:false,crawlee_local:false,receita_local_sync:false,receita_github_sync:env.RECEITA_SYNC_AUTOMATION==='1'}});
}

export async function handleAdmin(request:Request,env:Env,principal:Principal,url:URL):Promise<Response|undefined> {
  if(!['/admin','/admin/','/admin.html'].includes(url.pathname)&&!url.pathname.startsWith('/api/admin/')) return undefined;
  const write=!['GET','HEAD'].includes(request.method);
  await guard(request,env,principal,write);
  if(['GET','HEAD'].includes(request.method)&&['/admin','/admin/','/admin.html'].includes(url.pathname)) {
    const asset=await env.ASSETS.fetch(new Request(new URL('/admin.html',url.origin),{method:request.method}));
    return new Response(asset.body,{status:asset.status,headers:headers({...Object.fromEntries(asset.headers), 'Cache-Control':'no-store'})});
  }
  if(request.method==='GET') {
    if(url.pathname==='/api/admin/config') return json(await configSnapshot(env,principal));
    if(url.pathname==='/api/admin/state') return systemState(env);
    if(url.pathname==='/api/admin/export') return json({format:'radar-admin-parameters',version:1,values:await adminValues(env),note:'Sem chaves, senhas ou dados de leads. Não é backup do banco.'});
    if(url.pathname==='/api/admin/help') return json(await helpListing(env,principal,true));
    if(url.pathname.startsWith('/api/admin/backups/')) throw new ApiError(501,'Downloads de arquivos SQLite locais não estão disponíveis no Cloudflare D1. Use a exportação administrativa D1.');
  }
  if(request.method==='POST') {
    const payload=await bodyJson(request,url.pathname==='/api/admin/help'?65536:16384);
    if(url.pathname==='/api/admin/config') return saveConfig(env,principal,payload);
    if(url.pathname==='/api/admin/accounts') return saveAccount(env,principal,payload);
    if(url.pathname==='/api/admin/commercial') return saveCommercial(env,principal,payload);
    if(url.pathname==='/api/admin/help') return saveHelp(env,principal,payload);
    if(url.pathname==='/api/admin/integrity') {
      // D1 supports SQLite quick_check/foreign_key_check; this verifies current DB only.
      const expected=await revision(env.DB);
      const check=await queryRows(env.DB,'PRAGMA quick_check'),relations=await queryRows(env.DB,'PRAGMA foreign_key_check');
      const ok=check.length===1&&Object.values(check[0])[0]==='ok'&&relations.length===0;
      await mutate(env.DB,expected,[],principal.username,'database.checked',`Integridade: ${ok?'ok':'requer revisão'}; vínculos inválidos: ${relations.length}`);
      return json({ok,relations:relations.length,message:ok?'Banco íntegro':'Banco requer revisão. Nenhuma correção automática executada.'});
    }
    if(['/api/admin/backup','/api/admin/recovery-check'].includes(url.pathname)) throw new ApiError(501,'Cloudflare D1 não fornece arquivos SQLite locais ao Worker. Use o fluxo administrativo de exportação/Time Travel e valide a recuperação em uma base isolada. Nenhuma base foi substituída.');
  }
  throw new ApiError(404,'Rota administrativa não encontrada');
}

async function helpListing(env:Env,principal:Principal,edit=false):Promise<Row> {
  await seedHelp(env.DB);
  const admin=principal.role==='admin';
  const rows=await queryRows(env.DB,`SELECT a.id,a.category,a.title,a.summary,a.steps_json,a.action,a.tags,a.admin_only,a.published,a.revision,a.updated_at,f.useful AS own_feedback FROM help_articles a LEFT JOIN help_feedback f ON f.article_id=a.id AND f.owner_id=? ${edit&&admin?'':'WHERE a.published=1'+(admin?'':' AND a.admin_only=0')} ORDER BY a.category,a.title COLLATE NOCASE`,[principal.accountId]);
  const items:Row[]=[];
  for(const row of rows) {
    const {steps_json,own_feedback,...item}=row;
    let steps:unknown; try{steps=JSON.parse(String(steps_json));}catch{steps=[];}
    item.steps=Array.isArray(steps)?steps.filter(step=>typeof step==='string'):[];
    item.admin_only=Boolean(item.admin_only);item.published=Boolean(item.published);
    if(edit) item.feedback=Object.fromEntries((await queryRows(env.DB,'SELECT useful,COUNT(*) AS total FROM help_feedback WHERE article_id=? GROUP BY useful',[item.id])).map(value=>[String(value.useful),Number(value.total)]));
    else item.my_feedback=own_feedback===null?null:Boolean(own_feedback);
    items.push(item);
  }
  return {items,categories:Object.fromEntries(Object.entries(categories).filter(([key])=>admin||key!=='admin')),actions:edit?actions:null};
}
/** Static Python guides only. INSERT OR IGNORE preserves migrated and administrator-edited articles. */
async function seedHelp(db:D1Database):Promise<void> {
    if(await queryFirst(db,"SELECT value FROM help_meta WHERE key='cloudflare_seed_current_v2'")) return;
  const stamp=now();
  await db.batch([
    ...helpDefaults.map(article=>db.prepare('INSERT OR IGNORE INTO help_articles(id,category,title,summary,steps_json,action,tags,admin_only,published,revision,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?)').bind(article.id,article.category,article.title,article.summary,JSON.stringify(article.steps),article.action,article.tags,Number(article.admin_only),Number(article.published),stamp)),
    db.prepare("INSERT OR IGNORE INTO help_meta(key,value) VALUES('cloudflare_seed_current_v2','1')"),
  ]);
}
function articleText(value:unknown,key:string,limit:number,required=false):string {
  if(typeof value!=='string'||value.length>limit||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value)) throw new ApiError(400,'Texto inválido: '+key);
  const clean=value.trim(); if(required&&!clean) throw new ApiError(400,'Preencha título e resumo');return clean;
}
async function saveHelp(env:Env,principal:Principal,payload:Row) {
  ownKeys(payload,['id','revision','category','title','summary','steps','action','tags','admin_only','published'],'Artigo inválido');
  const title=articleText(payload.title,'title',160,true),summary=articleText(payload.summary,'summary',1600,true),tags=articleText(payload.tags??'','tags',300);
  const category=payload.category,action=payload.action??'',steps=payload.steps;
  if(typeof category!=='string'||!Object.hasOwn(categories,category)||typeof action!=='string'||!Object.hasOwn(actions,action)) throw new ApiError(400,'Categoria ou atalho inválido');
  if(!Array.isArray(steps)||steps.length<1||steps.length>12||steps.some(step=>typeof step!=='string'||!step.trim()||step.length>1000||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(step))) throw new ApiError(400,'Use de 1 a 12 passos, até 1000 caracteres cada');
  if(typeof payload.admin_only!=='boolean'||typeof payload.published!=='boolean') throw new ApiError(400,'Opção inválida');
  if((category==='admin'||action==='admin')&&!payload.admin_only) throw new ApiError(400,'Conteúdo administrativo deve ser restrito ao administrador');
  const id=payload.id||'artigo-'+crypto.randomUUID().replaceAll('-','').slice(0,12);
  if(typeof id!=='string'||!/^[a-z0-9-]{3,50}$/.test(id)||typeof payload.revision!=='number'||!Number.isSafeInteger(payload.revision)||payload.revision<0) throw new ApiError(400,'Identificador ou revisão inválida');
  const expected=await revision(env.DB),old=await queryFirst(env.DB,'SELECT revision FROM help_articles WHERE id=?',[id]);
  if(Number(old?.revision||0)!==payload.revision) throw new ApiError(409,articleConflict);
  const next=payload.revision+1;
  await mutate(env.DB,expected,[env.DB.prepare(`INSERT INTO help_articles(id,category,title,summary,steps_json,action,tags,admin_only,published,revision,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET category=excluded.category,title=excluded.title,summary=excluded.summary,steps_json=excluded.steps_json,action=excluded.action,tags=excluded.tags,admin_only=excluded.admin_only,published=excluded.published,revision=excluded.revision,updated_at=excluded.updated_at`).bind(id,category,title,summary,JSON.stringify(steps.map(step=>String(step).trim())),action,tags,Number(payload.admin_only),Number(payload.published),next,now())],principal.username,'help.updated','Artigo '+id+(payload.published?'; publicado':'; rascunho'));
  return json({saved:true,id,revision:next});
}
export async function handleHelp(request:Request,env:Env,principal:Principal,url:URL):Promise<Response|undefined> {
  if(request.method==='GET'&&url.pathname==='/api/runtime') return json(await runtimeConfig(env,principal));
  if(request.method==='GET'&&url.pathname==='/api/help') return json(await helpListing(env,principal));
  if(request.method==='POST'&&url.pathname==='/api/help/feedback') {
    const origin=request.headers.get('Origin');
    if((origin&&origin!==url.origin)||request.headers.get('Sec-Fetch-Site')==='cross-site') throw new ApiError(403,'Origem não permitida');
    const payload=await bodyJson(request,2048);
    ownKeys(payload,['id','useful'],'Resposta inválida');
    if(typeof payload.id!=='string'||!/^[a-z0-9-]{3,50}$/.test(payload.id)||typeof payload.useful!=='boolean') throw new ApiError(400,'Resposta inválida');
    // Visibility remains part of the write statement, even if the article is unpublished concurrently.
    const response=await env.DB.prepare(`INSERT INTO help_feedback(article_id,owner_id,useful,updated_at) SELECT id,?,?,? FROM help_articles WHERE id=? AND published=1 AND (admin_only=0 OR ?=1) ON CONFLICT(article_id,owner_id) DO UPDATE SET useful=excluded.useful,updated_at=excluded.updated_at`).bind(principal.accountId,Number(payload.useful),now(),payload.id,principal.role==='admin'?1:0).run();
    if(!response.meta.changes) throw new ApiError(404,'Artigo não encontrado');
    return json({saved:true});
  }
  return undefined;
}
