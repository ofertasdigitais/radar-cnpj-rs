import { env } from 'cloudflare:workers';
import { beforeAll, describe, expect, it } from 'vitest';
import { createSessionCookie, hashPassword, readSession, revokeSession, verifyPassword } from '../src/security-current';

beforeAll(async()=>{
  const stamp='2026-10-16T10:00:00';
  await env.DB.prepare(`INSERT INTO user_accounts(id,name,username,password_hash,password_salt,created_at,updated_at)
    VALUES('secure-a','Conta A','conta-a','unused','unused',?,?)`).bind(stamp,stamp).run();
});
describe('current account sessions and Python password compatibility',()=>{
  it('matches an independent Python hashlib vector including UTF-8 at 260000 iterations',async()=>{
    const salt='00112233445566778899aabbccddeeff';
    const expected='cd4531dbe37357ee37d55f357c7398a22909c3db8f064eca656a0ab183480110';
    expect(await verifyPassword('Compatibilidade-á-2026!',salt,expected)).toBe(true);
    expect(await verifyPassword('Compatibilidade-a-2026!',salt,expected)).toBe(false);
    expect(await verifyPassword('Compatibilidade-á-2026!',salt,'f'.repeat(64))).toBe(false);
  });
  it('uses PBKDF2 SHA256 at the existing 260000 iterations',async()=>{
    const result=await hashPassword('Teste-compatibilidade-2026!');
    expect(await verifyPassword('Teste-compatibilidade-2026!',result.salt,result.digest)).toBe(true);
    expect(await verifyPassword('wrong',result.salt,result.digest)).toBe(false);
  });
  it('rejects replay after logout and reads the authoritative server role',async()=>{
    const cookie=await createSessionCookie(env.SESSION_SECRET,'secure-a','conta-a',0);
    const request=new Request('https://radar.test/api/companies',{headers:{Cookie:cookie.split(';')[0]}});
    expect(await readSession(request,env)).toMatchObject({accountId:'secure-a',role:'vendedor',revision:0});
    await revokeSession(env.DB,'conta-a');
    expect(await readSession(request,env)).toBeNull();
    const next=await createSessionCookie(env.SESSION_SECRET,'secure-a','conta-a',1);
    await env.DB.prepare("UPDATE user_accounts SET role='admin' WHERE id='secure-a'").run();
    expect(await readSession(new Request(request.url,{headers:{Cookie:next.split(';')[0]}}),env)).toMatchObject({role:'admin'});
  });
  it('rejects missing revision, malformed and unsigned cookies',async()=>{
    expect(await readSession(new Request('https://radar.test',{headers:{Cookie:'radar_session=abc.def'}}),env)).toBeNull();
  });
});
