/** Current Radar entrypoint. No Python origin, tunnel, or shared customer bindings. */
import { handleCore, invalidateStatistics, invalidateOfficialMetadata } from './core-current';
import { adminValues, handleAdmin, handleHelp } from './admin-current';
import { handleSales } from './sales';
import { handleDiscovery, scheduledDiscovery } from './discovery-current';
import { handleProspects } from './prospects-current';
import { handleReceita, receitaSyncState } from './receita-current';
import { clearSessionCookie, consumeBudget, createSessionCookie, hashPassword, readSession, requestIsSameOrigin, revokeSession, verifyPassword } from './security-current';
import { ApiError, headers, json, now, queryFirst, queryRows, type Env, type Row, type Principal } from './runtime';

function redirect(location:string,cookie?:string):Response{
  const h=headers({'Location':location,'Cache-Control':'no-store'});if(cookie)h.set('Set-Cookie',cookie);return new Response(null,{status:303,headers:h});
}
function escapeHtml(value:unknown):string{return String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');}
async function registrationEnabled(env:Env,values?:Row):Promise<boolean>{const current=values||await adminValues(env);return current.registration==='on'||current.registration==='inherit'&&env.RADAR_ALLOW_REGISTRATION==='1';}
async function loginPage(request:Request,env:Env,mode='login',error='',status=200,values:Row={}):Promise<Response>{
  const asset=await env.ASSETS.fetch(new Request(new URL('/login.html',request.url)));
  if(!asset.ok)throw new ApiError(503,'Página de acesso indisponível');
  const config=await adminValues(env),canRegister=await registrationEnabled(env,config);
  const replacements:Record<string,string>={
    '__SITE_NAME__':escapeHtml(config.site_name),'__COPYRIGHT__':escapeHtml(String(config.copyright).replaceAll('{ano}',now().slice(0,4))),
    '__AUTH_VIEW__':mode==='register'&&canRegister?'register':'login','__REGISTRATION_STATE__':canRegister?'enabled':'disabled',
    '<!--AUTH_ERROR-->':error?`<div class="auth-alert" role="alert"><span>!</span><p>${escapeHtml(error)}</p></div>`:'',
    '__REGISTER_NAME__':escapeHtml(values.name),'__REGISTER_USERNAME__':escapeHtml(values.username),'__REGISTER_EMAIL__':escapeHtml(values.email),
  };
  let text=await asset.text();for(const [key,value]of Object.entries(replacements))text=text.replaceAll(key,value);
  return new Response(text,{status,headers:headers({'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'})});
}
async function boundedForm(request:Request,limit:number):Promise<URLSearchParams>{
  if(!(request.headers.get('Content-Type')||'').startsWith('application/x-www-form-urlencoded'))throw new ApiError(415,'Formulário inválido');
  const reader=request.body?.getReader();if(!reader)return new URLSearchParams();
  let size=0;const chunks:Uint8Array[]=[];
  try{for(;;){const part=await reader.read();if(part.done)break;size+=part.value.length;if(size>limit){await reader.cancel();throw new ApiError(413,'Formulário acima do limite');}chunks.push(part.value);}}finally{reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  try{return new URLSearchParams(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new ApiError(400,'Formulário inválido');}
}
async function authenticateForm(request:Request,env:Env):Promise<Response>{
  const form=await boundedForm(request,4096),login=(form.get('username')||'').trim().slice(0,180),password=form.get('password')||'';
  const account=await queryFirst(env.DB,`SELECT u.id,u.username,u.password_hash,u.password_salt,COALESCE(r.revision,0) session_revision
    FROM user_accounts u LEFT JOIN admin_session_revisions r ON r.username=u.username COLLATE NOCASE
    WHERE u.is_active=1 AND (u.username=? COLLATE NOCASE OR u.email=? COLLATE NOCASE) LIMIT 1`,[login,login]);
  const key=account?'login:account:'+account.id:'login:unknown:'+login.toLowerCase();
  if(!account&&!await consumeBudget(env.DB,'login-edge:'+(request.headers.get('CF-Connecting-IP')||'local'),1000,900)||!await consumeBudget(env.DB,key,8,900))return loginPage(request,env,'login','Muitas tentativas. Aguarde 15 minutos.',429);
  if(password.length>1024||!account||!await verifyPassword(password,String(account.password_salt),String(account.password_hash)))return loginPage(request,env,'login','Usuário, e-mail ou senha incorretos.',401);
  await env.DB.batch([
    env.DB.prepare('UPDATE user_accounts SET last_login_at=?,updated_at=? WHERE id=?').bind(now(),now(),account.id),
    env.DB.prepare('DELETE FROM auth_attempts WHERE key=?').bind(key),
  ]);
  // Capture revision with the verified hash, not after it: concurrent resets must invalidate this login.
  const revision=Number(account.session_revision);
  return redirect('/',await createSessionCookie(env.SESSION_SECRET,String(account.id),String(account.username),revision));
}
async function register(request:Request,env:Env):Promise<Response>{
  if(!await registrationEnabled(env))return loginPage(request,env,'login','A criação de contas está desativada neste ambiente.',403);
  if(!await consumeBudget(env.DB,'register:'+(request.headers.get('CF-Connecting-IP')||'local'),8,900))throw new ApiError(429,'Muitas tentativas. Aguarde 15 minutos.');
  const form=await boundedForm(request,16384),name=(form.get('name')||'').trim(),username=(form.get('username')||'').trim(),email=(form.get('email')||'').trim().toLowerCase(),password=form.get('password')||'';
  const values={name,username,email};let error='';
  if(name.length<2||name.length>100)error='Informe seu nome completo.';
  else if(!/^[a-zA-Z0-9._-]{3,40}$/.test(username))error='O usuário deve ter de 3 a 40 caracteres: letras, números, ponto, traço ou sublinhado.';
  else if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)||email.length>160)error='Informe um endereço de e-mail válido.';
  else if(password.length<10||password.length>200||!/[A-Za-zÀ-ÿ]/.test(password)||!/[0-9]/.test(password))error='Crie uma senha com pelo menos 10 caracteres, uma letra e um número.';
  else if(password!==form.get('confirm_password'))error='As senhas informadas não coincidem.';
  else if(env.RADAR_REGISTRATION_CODE&&form.get('invite_code')!==env.RADAR_REGISTRATION_CODE)error='O código de convite é inválido.';
  if(error)return loginPage(request,env,'register',error,400,values);
  const hash=await hashPassword(password),id='conta-'+crypto.randomUUID().replaceAll('-',''),stamp=now();
  const initials=name.split(/\s+/).slice(0,2).map(s=>s[0]).join('').toUpperCase();
  try{
    await env.DB.batch([
      // A NOT NULL assertion makes the email check + account/profile creation atomic.
      env.DB.prepare(`INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at)
        VALUES(?,CASE WHEN EXISTS(SELECT 1 FROM user_accounts WHERE email=? COLLATE NOCASE) THEN NULL ELSE ? END,?,?,?,?,'vendedor',1,?,?)`).bind(id,email,name,username,email,hash.digest,hash.salt,stamp,stamp),
      env.DB.prepare('INSERT INTO sales_profiles(id,name,role,email,initials,color,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)').bind('usuario-'+crypto.randomUUID().replaceAll('-','').slice(0,12),name,'Vendedor',email,initials,'#b82043',id,stamp,stamp),
    ]);
  }catch(e){if(/constraint/i.test(String(e)))return loginPage(request,env,'register','Usuário ou e-mail já utilizado.',409,values);throw e;}
  return redirect('/',await createSessionCookie(env.SESSION_SECRET,id,username,0));
}
async function maintenance(request:Request,env:Env,p:Principal,url:URL):Promise<Response|undefined>{
  if(url.pathname==='/api/sync'){
    if(request.method!=='GET'){
      if(p.role!=='admin')throw new ApiError(403,'Somente o administrador pode iniciar a carga da base oficial');
      throw new ApiError(501,'A Receita é verificada diariamente pelo GitHub Actions. Para antecipar, execute Receita mensal · Radar Cloudflare no GitHub do Radar. Nenhuma carga foi iniciada por este botão.');
    }
    return json(await receitaSyncState(env));
  }
  if(url.pathname==='/api/monitor'){
    if(request.method!=='GET'){
      if(p.role!=='admin')throw new ApiError(403,'Área exclusiva do administrador');
      throw new ApiError(409,'Serpro desativado para evitar custos.');
    }
    return json({status:'disabled',fase:'Serpro desativado',mensagem:'Consultas bloqueadas para evitar custos.',configurado:false,pendencias_configuracao:['Contrato e credenciais oficiais Serpro'],ambiente:'homologacao',limite_diario:50,janela_dias:30,hora_execucao:6,fonte_descoberta_configurada:false,fila:0,validados_hoje:0,ultima_execucao:null,processados:0,atualizados:0,falhas:0,iniciado_em:null,finalizado_em:null});
  }
  return undefined;
}
async function fetchCurrent(request:Request,env:Env,context?:ExecutionContext):Promise<Response>{
  const url=new URL(request.url),path=url.pathname;
  if(!['GET','HEAD','POST','PUT','DELETE','PATCH'].includes(request.method))throw new ApiError(405,'Método não permitido');
  // Separate, narrow server-to-server credential; no account-wide Cloudflare token.
  if(path==='/api/internal/receita'){
    const imported=await handleReceita(request,env,url);
    if(imported){invalidateOfficialMetadata();return imported;}
  }
  if(!['GET','HEAD'].includes(request.method)&&!requestIsSameOrigin(request))throw new ApiError(403,'Origem não permitida');
  if(path==='/healthz'){
    const row=await queryFirst(env.DB,'SELECT id FROM user_accounts WHERE is_active=1 LIMIT 1');return json({status:row?'ok':'not_ready'},row?200:503);
  }
  if(path==='/login'&&request.method==='GET')return await readSession(request,env)?redirect('/'):loginPage(request,env,url.searchParams.get('mode')||'login');
  if(path==='/login'&&request.method==='POST')return authenticateForm(request,env);
  if(path==='/register'&&request.method==='POST')return register(request,env);
  const publicAsset=['/style.css','/visual.css','/radar-polish.css','/auth.js','/icon.svg','/react-login.css','/react-login.js','/manifest.webmanifest'].includes(path)||/^\/fonts\/[a-zA-Z0-9_.-]+\.(woff2|ttf)$/.test(path);
  if(publicAsset&&['GET','HEAD'].includes(request.method))return env.ASSETS.fetch(request);
  const principal=await readSession(request,env);
  if(!principal)return path.startsWith('/api/')?json({erro:'Autenticação necessária'},401):redirect('/login');
  if(path==='/logout'){
    if(!requestIsSameOrigin(request))throw new ApiError(403,'Origem não permitida');
    await revokeSession(env.DB,principal.username);return redirect('/login',clearSessionCookie());
  }
  if(path.startsWith('/api/')){
    const read=request.method==='GET';
    if(!await consumeBudget(env.DB,'api:'+principal.accountId+':'+(read?'read':'write'),read?600:300,60))throw new ApiError(429,'Muitas solicitações. Aguarde um minuto.');
    if(!read)invalidateStatistics();
  }
  for(const handler of [handleAdmin,handleHelp,handleCore,handleSales,handleProspects]){
    const response=await handler(request,env,principal,url);if(response)return response;
  }
  const found=await handleDiscovery(request,env,principal,url,context);if(found)return found;
  const maintenanceResponse=await maintenance(request,env,principal,url);if(maintenanceResponse)return maintenanceResponse;
  if(path.startsWith('/api/'))throw new ApiError(404,'Rota não encontrada');
  if(!['GET','HEAD'].includes(request.method))throw new ApiError(405,'Método não permitido');
  if(['/ajuda','/ajuda/'].includes(path))return redirect('/#ajuda');
  let decoded:string;try{decoded=decodeURIComponent(path).replaceAll('\\','/');}catch{throw new ApiError(404,'Arquivo não encontrado');}
  if(decoded.split('/').some(part=>part.startsWith('.'))||![ '/', '/ajuda', '/ajuda/' ].includes(path)&&!(/\.(html|css|js|svg|png|jpg|jpeg|webp|ico|woff2|ttf|webmanifest|txt)$/i.test(path)))throw new ApiError(404,'Arquivo não encontrado');
  // ASSETS serves index.html at /; requesting /index.html redirects back to /.
  // Preserve the original canonical path to avoid an authenticated redirect loop.
  const response=await env.ASSETS.fetch(request);
  const h=headers(response.headers);h.set('Cache-Control','no-store');return new Response(response.body,{status:response.status,headers:h});
}
export default {
  async fetch(request:Request,env:Env,context?:ExecutionContext):Promise<Response>{
    try{
      if(!env.SESSION_SECRET||env.SESSION_SECRET.length<32)throw new ApiError(503,'Proteção de sessão não configurada');
      const response=await fetchCurrent(request,env,context);return new Response(response.body,{status:response.status,headers:headers(response.headers)});
    }catch(error){
      if(error instanceof ApiError)return json({erro:error.message},error.status);
      const incident=crypto.randomUUID();console.error('Radar incident',incident,error instanceof Error?error.name:'Error');return json({erro:'Falha interna',incidente:incident},500);
    }
  },
  async scheduled(controller:ScheduledController,env:Env,context:ExecutionContext):Promise<void>{context.waitUntil(scheduledDiscovery(env,controller.scheduledTime));},
} satisfies ExportedHandler<Env>;
