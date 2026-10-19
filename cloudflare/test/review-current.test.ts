import { env } from 'cloudflare:workers';
import { beforeAll, describe, expect, it } from 'vitest';
import worker from '../src/worker-current';
import { createSessionCookie, hashPassword, readSession } from '../src/security-current';
import { companyFilters } from '../src/query-current';
import { handleCore } from '../src/core-current';
import type { Env } from '../src/runtime';

beforeAll(async()=>{
  const hashed=await hashPassword('Review-password-2026');
  await env.DB.prepare('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)').bind('review-existing','Existing','review-existing','review-shared@example.test',hashed.digest,hashed.salt,'vendedor',1,'2026-10-16','2026-10-16').run();
  await env.DB.prepare('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)').bind('review-race','Login race','review-race','review-race@example.test',hashed.digest,hashed.salt,'vendedor',1,'2026-10-16','2026-10-16').run();
  await env.DB.prepare('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)').bind('review-role','Imported admin','review-role','review-role@example.test',hashed.digest,hashed.salt,' Administrador ',1,'2026-10-16','2026-10-16').run();
});
describe('launch review regressions',()=>{
  it('rejects duplicate email registration without a NULL account id or orphan profile',async()=>{
    const form=new URLSearchParams({name:'Duplicate User',username:'review-duplicate',email:'review-shared@example.test',password:'Review-password-2026',confirm_password:'Review-password-2026'});
    const response=await worker.fetch(new Request('https://radar.test/register',{method:'POST',headers:{Origin:'https://radar.test','Content-Type':'application/x-www-form-urlencoded','CF-Connecting-IP':'192.0.2.230'},body:form.toString()}),{...env,RADAR_ALLOW_REGISTRATION:'1'} as Env);
    const duplicate=await env.DB.prepare('SELECT COUNT(*) AS total FROM user_accounts WHERE email=? COLLATE NOCASE').bind('review-shared@example.test').first<{total:number}>();
    const nullId=await env.DB.prepare('SELECT COUNT(*) AS total FROM user_accounts WHERE id IS NULL').first<{total:number}>();
    expect({status:response.status,duplicate:duplicate?.total,nullIds:nullId?.total}).toEqual({status:409,duplicate:1,nullIds:0});
  });
  it('does not issue a usable session for an old password when reset occurs during login',async()=>{
    let intercepted=false;
    const db=new Proxy(env.DB,{get(target,property){
      if(property==='batch')return async(statements:D1PreparedStatement[])=>{
        if(!intercepted){
          intercepted=true;
          await target.batch([
            target.prepare('UPDATE user_accounts SET password_hash=? WHERE id=?').bind('0'.repeat(64),'review-race'),
            target.prepare('INSERT INTO admin_session_revisions(username,revision) VALUES(?,1) ON CONFLICT(username) DO UPDATE SET revision=revision+1').bind('review-race'),
          ]);
        }
        return target.batch(statements);
      };
      const member=Reflect.get(target,property);return typeof member==='function'?member.bind(target):member;
    }});
    const form=new URLSearchParams({username:'review-race',password:'Review-password-2026'});
    const response=await worker.fetch(new Request('https://radar.test/login',{method:'POST',headers:{Origin:'https://radar.test','Content-Type':'application/x-www-form-urlencoded'},body:form.toString()}),{...env,DB:db} as Env);
    expect(intercepted).toBe(true);
    const cookie=response.headers.get('Set-Cookie')?.split(';')[0]||'';
    const session=await readSession(new Request('https://radar.test/api/runtime',{headers:{Cookie:cookie}}),env);
    expect(session).toBeNull();
  });
  it('preserves the Python role normalization for migrated administrator accounts',async()=>{
    const cookie=(await createSessionCookie(env.SESSION_SECRET,'review-role','review-role',0)).split(';')[0];
    expect(await readSession(new Request('https://radar.test',{headers:{Cookie:cookie}}),env)).toMatchObject({role:'admin'});
  });
  it('keeps permitted combined filters within the D1 bound parameter budget or returns validation error',()=>{
    const values={cnae_include:Array.from({length:40},(_,index)=>String(1000000+index)).join(','),cnae_exclude:Array.from({length:40},(_,index)=>String(2000000+index)).join(','),name_terms:Array.from({length:12},(_,index)=>'include'+index).join(','),name_exclude:Array.from({length:12},(_,index)=>'exclude'+index).join(',')};
    let filter:ReturnType<typeof companyFilters>;
    try { filter=companyFilters(new URLSearchParams(values),new Set(),'review-existing'); }
    catch(error) { expect(error).toMatchObject({status:400}); return; }
    expect(filter.values.length+3).toBeLessThanOrEqual(100);
  });
  it('keeps unicode LIKE patterns within documented D1 limits or uses an unrestricted literal search',()=>{
    let filter:ReturnType<typeof companyFilters>;
    try { filter=companyFilters(new URLSearchParams({q:'á'.repeat(30)}),new Set(),'review-existing'); }
    catch(error) { expect(error).toMatchObject({status:400}); return; }
    if(/\bLIKE\b/i.test(filter.where))for(const pattern of filter.values)expect(new TextEncoder().encode(String(pattern)).byteLength).toBeLessThanOrEqual(50);
    else expect(filter.values.length).toBeGreaterThan(0);
  });
  it('measures default statistics read amplification on a synthetic company fixture',async()=>{
    const stamp='2026-10-01';
    await env.DB.batch(Array.from({length:200},(_,index)=>env.DB.prepare('INSERT INTO companies(cnpj,razao_social,uf,situacao,cnae,segmento,municipio,data_abertura,telefone,email) VALUES(?,?,?,?,?,?,?,?,?,?)').bind(String(90000000000000+index),'Review fixture '+index,'RS','ATIVA','5611201','Alimentação','Teste',stamp,'51999998888','fixture@example.test')));
    let reads=0,queries=0;
    const wrap=(statement:D1PreparedStatement):D1PreparedStatement=>new Proxy(statement,{get(target,property){
      if(property==='bind')return(...values:unknown[])=>wrap(target.bind(...values));
      if(property==='all')return async()=>{const result=await target.all();reads+=Number(result.meta.rows_read);queries++;return result;};
      if(property==='first')return async(column?:string)=>{const result=await target.all();reads+=Number(result.meta.rows_read);queries++;const item=result.results[0];return item?(column?item[column]:item):null;};
      const member=Reflect.get(target,property);return typeof member==='function'?member.bind(target):member;
    }});
    const db=new Proxy(env.DB,{get(target,property){if(property==='prepare')return(sql:string)=>wrap(target.prepare(sql));const member=Reflect.get(target,property);return typeof member==='function'?member.bind(target):member;}});
    const principal={accountId:'review-existing',username:'review-existing',role:'vendedor' as const,expires:9999999999};
    const url=new URL('https://radar.test/api/stats');
    const response=await handleCore(new Request(url),{...env,DB:db} as Env,principal,url);
    expect(response?.status).toBe(200);
    console.log(JSON.stringify({reviewMetric:'stats-read-amplification',companies:200,queries,rowsRead:reads}));
    expect(queries).toBeLessThanOrEqual(47); // Reserve authentication and request-budget calls.
    expect(reads).toBeGreaterThan(0);
  });
});
