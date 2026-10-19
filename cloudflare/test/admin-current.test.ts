import { env } from 'cloudflare:workers';
import { beforeAll, describe, expect, it } from 'vitest';
import { handleAdmin, handleHelp } from '../src/admin-current';
import { ApiError, type Env, type Principal } from '../src/runtime';
import { verifyPassword } from '../src/security-current';

const origin = 'https://radar.test';
const admin: Principal = { accountId: 'admin-current', username: 'current-admin', role: 'admin', expires: 9999999999 };
const seller: Principal = { accountId: 'seller-current', username: 'current-seller', role: 'vendedor', expires: 9999999999 };
const bindings = env as unknown as Env;
function request(path: string, payload?: unknown, csrf = '') {
  return new Request(origin + path, { method: payload === undefined ? 'GET' : 'POST', headers: { Origin: origin, 'Content-Type': 'application/json', 'X-Radar-CSRF': csrf }, body: payload === undefined ? undefined : JSON.stringify(payload) });
}
async function call(path: string, payload?: unknown, csrf = '', principal = admin): Promise<Response> {
  const req = request(path, payload, csrf);
  try { return (await handleAdmin(req, bindings, principal, new URL(req.url))) || (await handleHelp(req, bindings, principal, new URL(req.url))) || new Response('', {status:404}); }
  catch (error) { if (error instanceof ApiError) return Response.json({erro:error.message}, {status:error.status}); throw error; }
}
async function configuration() { return (await (await call('/api/admin/config')).json()) as {revision:number; csrf:string; values:Record<string,unknown>; fields:Record<string,unknown>[]}; }

beforeAll(async () => {
  const stamp = new Date().toISOString();
  for (const [id, username, role] of [[admin.accountId,admin.username,'admin'],[seller.accountId,seller.username,'vendedor']]) {
    await env.DB.prepare('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)').bind(id, username, username, username+'@example.test','hash','salt',role,1,stamp,stamp).run();
  }
  await env.DB.prepare('INSERT INTO sales_profiles(id,name,owner_id,created_at,updated_at) VALUES(?,?,?,?,?)').bind('profile-current','Seller',seller.accountId,stamp,stamp).run();
});

describe('current Radar administration', () => {
  it('enforces administrator role and CSRF before any write', async () => {
    expect((await call('/api/admin/config',undefined,'',seller)).status).toBe(403);
    expect((await call('/api/admin/config',{revision:0,values:{site_name:'Attack'}})).status).toBe(403);
    const config=await configuration();
    const crossOrigin=new Request('https://radar.test/api/admin/config',{method:'POST',headers:{Origin:'https://attacker.test','X-Radar-CSRF':config.csrf},body:JSON.stringify({revision:config.revision,values:{site_name:'Attack'}})});
    await expect(handleAdmin(crossOrigin,bindings,admin,new URL(crossOrigin.url))).rejects.toMatchObject({status:403});
    expect((await call('/admin',undefined,'',seller)).status).toBe(403);
  });
  it('returns current defaults and binding metadata without exposing stored ciphertext', async () => {
    await env.DB.prepare('INSERT OR REPLACE INTO admin_parameters(key,value,updated_at) VALUES(?,?,?)').bind('base44_secret',JSON.stringify('DPAPI-PRIVATE-CIPHERTEXT'),'2026').run();
    const config = await configuration();
    expect(config.values.site_name).toBe('Radar CNPJ');
    expect(config.values.contact_sla_hours).toBe(48);
    expect(config.csrf).toMatch(/^[0-9a-f]{64}$/);
    expect(config.fields.find(field=>field.key==='base44_secret')).toMatchObject({readonly:true,configured:false,storage:'environment-only'});
    expect(JSON.stringify(config)).not.toContain('DPAPI-PRIVATE-CIPHERTEXT');
    expect(config.values).not.toHaveProperty('base44_secret');
  });
  it('atomically rejects an obsolete configuration without partial writes or audit', async () => {
    const config = await configuration();
    expect((await call('/api/admin/config',{revision:config.revision,values:{site_name:'Radar Test'}},config.csrf)).status).toBe(200);
    const before = await env.DB.prepare('SELECT COUNT(*) AS total FROM admin_audit').first<{total:number}>();
    expect((await call('/api/admin/config',{revision:config.revision,values:{site_name:'Lost write',copyright:'Lost footer'}},config.csrf)).status).toBe(409);
    expect((await configuration()).values.site_name).toBe('Radar Test');
    expect((await env.DB.prepare('SELECT COUNT(*) AS total FROM admin_audit').first<{total:number}>())?.total).toBe(before?.total);
  });
  it('rejects secret editing and invalid numeric parameters', async () => {
    const config = await configuration();
    expect((await call('/api/admin/config',{revision:config.revision,values:{base44_secret:'a'.repeat(40)}},config.csrf)).status).toBe(400);
    expect((await call('/api/admin/config',{revision:config.revision,values:{max_columns:true}},config.csrf)).status).toBe(400);
    expect((await call('/api/admin/accounts',{name:'Owner injection',username:'owner-injected',owner_id:admin.accountId,password:'Senha-segura-2026'},config.csrf)).status).toBe(400);
  });
  it('serializes concurrent writes so exactly one loaded revision wins', async () => {
    const config=await configuration();
    const before=await env.DB.prepare('SELECT COUNT(*) AS total FROM admin_audit').first<{total:number}>();
    const responses=await Promise.all(['One','Two'].map(site_name=>call('/api/admin/config',{revision:config.revision,values:{site_name}},config.csrf)));
    expect(responses.map(response=>response.status).sort()).toEqual([200,409]);
    expect((await configuration()).revision).toBe(config.revision+1);
    expect((await env.DB.prepare('SELECT COUNT(*) AS total FROM admin_audit').first<{total:number}>())?.total).toBe(Number(before?.total)+1);
  });
  it('creates a salted-password account with its own profile atomically', async () => {
    const config=await configuration();
    const payload={name:'Conta Nova',username:'account-new-current',email:'new-current@example.test',role:'vendedor',is_active:true,password:'Senha-segura-2026'};
    const result=await call('/api/admin/accounts',payload,config.csrf);
    expect(result.status).toBe(200);
    const body=await result.json() as {id:string};
    const account=await env.DB.prepare('SELECT password_hash,password_salt FROM user_accounts WHERE id=?').bind(body.id).first<{password_hash:string;password_salt:string}>();
    expect(account?.password_hash).not.toBe(payload.password);
    expect(await verifyPassword(payload.password,account!.password_salt,account!.password_hash)).toBe(true);
    expect(await env.DB.prepare('SELECT owner_id FROM sales_profiles WHERE owner_id=?').bind(body.id).first()).toMatchObject({owner_id:body.id});
    expect((await call('/api/admin/accounts',{...payload,username:'duplicate-current'},config.csrf)).status).toBe(409);
  });
  it('updates account security, revokes sessions, and preserves profile ownership', async () => {
    const config = await configuration();
    const result = await call('/api/admin/accounts',{id:seller.accountId,name:'Seller Updated',username:seller.username,email:'updated@example.test',role:'vendedor',is_active:false},config.csrf);
    expect(result.status).toBe(200);
    expect(await env.DB.prepare('SELECT owner_id FROM sales_profiles WHERE id=?').bind('profile-current').first()).toMatchObject({owner_id:seller.accountId});
    expect(await env.DB.prepare('SELECT revision FROM admin_session_revisions WHERE username=?').bind(seller.username).first()).toMatchObject({revision:1});
    expect((await call('/api/admin/accounts',{id:admin.accountId,name:'Admin',username:admin.username,email:admin.username+'@example.test',role:'vendedor',is_active:true},config.csrf)).status).toBe(400);
  });
  it('returns an explicit unsupported response for a SQLite file backup in D1', async () => {
    const config = await configuration();
    const response = await call('/api/admin/backup',{},config.csrf);
    expect(response.status).toBe(501);
    expect(await response.json()).toMatchObject({erro:expect.stringContaining('D1')});
  });
  it('checks D1 integrity and audits the actual result', async () => {
    const config=await configuration();
    const response=await call('/api/admin/integrity',{},config.csrf);
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ok:true,relations:0});
  });
  it('supports administrator per-profile rules and safe inheritance', async () => {
    const config=await configuration();
    expect((await call('/api/admin/commercial',{profile_id:'profile-current',contact_sla_hours:24,stalled_days:3},config.csrf)).status).toBe(200);
    expect(await env.DB.prepare('SELECT * FROM commercial_settings WHERE profile_id=?').bind('profile-current').first()).toMatchObject({contact_sla_hours:24,stalled_days:3});
    expect((await call('/api/admin/commercial',{profile_id:'profile-current',contact_sla_hours:null,stalled_days:null},config.csrf)).status).toBe(200);
    expect(await env.DB.prepare('SELECT * FROM commercial_settings WHERE profile_id=?').bind('profile-current').first()).toBe(null);
  });
});

describe('current help center', () => {
  it('saves plain text with article revision and hides admin content from sellers', async () => {
    const config = await configuration();
    const payload = {id:'admin-test-guide',revision:0,category:'admin',title:'Guia administrativo',summary:'Texto simples',steps:['Confira o sistema'],action:'admin',tags:'teste',admin_only:true,published:true};
    const response = await call('/api/admin/help',payload,config.csrf);
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({id:payload.id,revision:1});
    expect((await call('/api/admin/help',payload,config.csrf)).status).toBe(409);
    const publicResult = await (await call('/api/help',undefined,'',seller)).json() as {items:{id:string}[];categories:Record<string,string>};
    expect(publicResult.items.some(item=>item.id===payload.id)).toBe(false);
    expect(publicResult.categories).not.toHaveProperty('admin');
    expect((await call('/api/help/feedback',{id:payload.id,useful:true},'',seller)).status).toBe(404);
    expect((await call('/api/admin/help',{...payload,id:'unsafe-guide',admin_only:false},config.csrf)).status).toBe(400);
  });
  it('stores one independent feedback answer per authenticated account', async () => {
    const config = await configuration();
    const payload = {id:'public-test-guide',revision:0,category:'inicio',title:'Guia público',summary:'Texto simples',steps:['Passo um'],action:'',tags:'',admin_only:false,published:true};
    expect((await call('/api/admin/help',payload,config.csrf)).status).toBe(200);
    expect((await call('/api/help/feedback',{id:payload.id,useful:true},'',seller)).status).toBe(200);
    expect((await call('/api/help/feedback',{id:payload.id,useful:false},'',seller)).status).toBe(200);
    const listed = await (await call('/api/help',undefined,'',seller)).json() as {items:{id:string;my_feedback:boolean|null}[]};
    expect(listed.items.find(item=>item.id===payload.id)?.my_feedback).toBe(false);
    const own = await (await call('/api/help')).json() as {items:{id:string;my_feedback:boolean|null}[]};
    expect(own.items.find(item=>item.id===payload.id)?.my_feedback).toBe(null);
  });
  it('seeds the existing public guides without overwriting edited content', async () => {
    const result=await (await call('/api/help',undefined,'',seller)).json() as {items:{id:string;admin_only:boolean}[]};
    expect(result.items.length).toBeGreaterThan(10);
    expect(result.items.every(item=>!item.admin_only)).toBe(true);
    const config=await configuration();
    const item=await env.DB.prepare('SELECT * FROM help_articles WHERE admin_only=0 LIMIT 1').first<Record<string,unknown>>();
    const payload={id:item!.id,revision:item!.revision,category:item!.category,title:'Guia revisado',summary:item!.summary,steps:JSON.parse(String(item!.steps_json)),action:item!.action,tags:item!.tags,admin_only:false,published:true};
    expect((await call('/api/admin/help',payload,config.csrf)).status).toBe(200);
    const refreshed=await (await call('/api/help',undefined,'',seller)).json() as {items:{id:string;title:string}[]};
    expect(refreshed.items.find(article=>article.id===item!.id)?.title).toBe('Guia revisado');
  });
});
