import { env } from 'cloudflare:workers';
import { beforeAll, describe, expect, it } from 'vitest';
import worker from '../src/worker-current';
import { createSessionCookie, hashPassword } from '../src/security-current';
import type { Env } from '../src/runtime';
let seller='',admin='';
const call=(path:string,cookie='',method='GET',body?:string,extra:Record<string,string>={})=>worker.fetch(new Request('https://radar.test'+path,{method,body,headers:{Cookie:cookie,Origin:'https://radar.test',...extra}}),env as Env);
beforeAll(async()=>{
  const hashed=await hashPassword('Worker-validation-2026!');
  for(const [id,username,role] of [['worker-seller','seller','vendedor'],['worker-admin','administrator','admin']])await env.DB.prepare(`INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`).bind(id,username,username,username+'@example.test',hashed.digest,hashed.salt,role,'2026-10-16','2026-10-16').run();
  seller=(await createSessionCookie(env.SESSION_SECRET,'worker-seller','seller',0)).split(';')[0];
  admin=(await createSessionCookie(env.SESSION_SECRET,'worker-admin','administrator',0)).split(';')[0];
});
describe('integrated current Worker boundary',()=>{
  it('requires auth for APIs and protected HTML/assets',async()=>{
    expect((await call('/api/companies')).status).toBe(401);
    expect((await call('/')).status).toBe(303);
    expect((await call('/admin.html')).status).toBe(303);
    expect((await call('/react-admin.js')).status).toBe(303);
    expect((await call('/admin',seller)).status).toBe(403);
    expect((await call('/api/admin/state',seller)).status).toBe(403);
    expect((await call('/api/admin/state',admin)).status).toBe(200);
    const help=await call('/ajuda',seller);expect(help.status).toBe(303);expect(help.headers.get('Location')).toBe('/#ajuda');
  });
  it('renders public login and its bundle, with no unreplaced template markers',async()=>{
    const response=await call('/login');expect(response.status).toBe(200);
    expect(await response.text()).not.toContain('__SITE_NAME__');
    expect((await call('/react-login.js')).status).toBe(200);
    expect((await call('/radar-polish.css')).status).toBe(200);
    expect((await call('/data/radar.db',admin)).status).toBe(404);
    expect((await call('/admin-definitions.json',admin)).status).toBe(404);
  });
  it('logs in with case/email aliases, then revokes the previous session on logout',async()=>{
    const response=await call('/login','','POST',new URLSearchParams({username:'SELLER@example.test',password:'Worker-validation-2026!'}).toString(),{'Content-Type':'application/x-www-form-urlencoded'});
    expect(response.status).toBe(303);const cookie=response.headers.get('Set-Cookie')!.split(';')[0];
    expect((await call('/api/runtime',cookie)).status).toBe(200);
    const home=await call('/',cookie);expect(home.status).toBe(200);
    expect(home.headers.get('Location')).toBeNull();
    expect(await home.text()).toContain('<html');
    expect((await call('/logout',cookie)).status).toBe(303);
    expect((await call('/api/runtime',cookie)).status).toBe(401);
  });
  it('refuses unsafe origins and exposes no server error internals',async()=>{
    const response=await call('/api/profiles',admin,'POST','{}',{Origin:'https://evil.test','Content-Type':'application/json'});
    expect(response.status).toBe(403);
    expect(response.headers.get('Content-Security-Policy')).toContain("frame-ancestors 'none'");
    expect((await call('/register','','POST','')).status).toBe(403);
  });
  it('atomically rejects duplicate emails when public registration is enabled',async()=>{
    const previous=await env.DB.prepare('SELECT COUNT(*) n FROM sales_profiles').first<{n:number}>();
    await env.DB.prepare("INSERT INTO admin_parameters(key,value,updated_at) VALUES('registration','\"on\"','2026-10-16')").run();
    const response=await call('/register','','POST',new URLSearchParams({name:'Outra Pessoa',username:'another-person',email:'seller@example.test',password:'Password-test-2026!',confirm_password:'Password-test-2026!'}).toString(),{'Content-Type':'application/x-www-form-urlencoded'});
    expect(response.status).toBe(409);
    expect((await env.DB.prepare('SELECT COUNT(*) n FROM sales_profiles').first<{n:number}>())?.n).toBe(previous?.n);
    expect(await env.DB.prepare("SELECT id FROM user_accounts WHERE username='another-person'").first()).toBeNull();
    await env.DB.prepare("DELETE FROM admin_parameters WHERE key='registration'").run();
  });
});
