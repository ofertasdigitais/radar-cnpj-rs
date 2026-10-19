import { env } from 'cloudflare:workers';
import { beforeAll, describe, expect, it } from 'vitest';
import { handleCore } from '../src/core-current';
import type { Env, Principal, Row } from '../src/runtime';
const a:Principal={accountId:'core-a',username:'a',role:'vendedor',expires:9999999999};
const b:Principal={accountId:'core-b',username:'b',role:'vendedor',expires:9999999999};
const call=(path:string,owner=a,method='GET',body?:Row)=>handleCore(new Request('https://radar.test'+path,{method,body:body?JSON.stringify(body):undefined}),env as Env,owner,new URL('https://radar.test'+path));
beforeAll(async()=>{
  for(const [cnpj,name,uf,situation] of [['11111111000111','Público','RS','ATIVA'],['22222222000122','Privado A','ZZ','TESTE'],['33333333000133','Private mapped RS','RS','ATIVA']])
    await env.DB.prepare(`INSERT INTO companies(cnpj,razao_social,uf,situacao,cnae,segmento,municipio,data_abertura,telefone) VALUES(?,?,?,?,?,?,?,?,?)`).bind(cnpj,name,uf,situation,'5611201','Alimentação','Teste','2026-10-01','51999998888').run();
  await env.DB.batch([
    env.DB.prepare("INSERT INTO private_companies VALUES('22222222000122','core-a')"),
    env.DB.prepare("INSERT INTO private_companies VALUES('33333333000133','core-a')"),
  ]);
});
describe('current search and segmentation',()=>{
  it('excludes canonical private companies from official listings and options',async()=>{
    const response=await call('/api/companies');expect(response?.status).toBe(200);
    const data=await response!.json<{items:Row[];total:number}>();expect(data.total).toBe(1);
    expect(data.items[0].cnpj).toBe('11111111000111');
    const stats=await (await call('/api/stats'))!.json<{summary:Row;options:Row}>();expect(stats.summary.total).toBe(1);
    expect(stats.options.cnaes).toHaveLength(1);
  });
  it('isolates company state and refuses foreign private writes',async()=>{
    const body={favorito:true,observacoes:'privado da conta A'};
    expect((await call('/api/leads/11111111000111',a,'PUT',body))?.status).toBe(200);
    const data=await (await call('/api/companies',b))!.json<{items:Row[]}>();expect(data.items[0].favorito).toBe(0);
    await expect(call('/api/leads/22222222000122',b,'PUT',body)).rejects.toMatchObject({status:404});
  });
  it('creates and isolates custom segmentation lists',async()=>{
    const created=await (await call('/api/profiles',a,'POST',{name:'Restaurantes',filters:{cnae_include:'5611201'}}))!.json<{id:string}>();
    expect((await call('/api/profile-leads',a,'POST',{profile_id:created.id,cnpj:'11111111000111'}))?.status).toBe(201);
    await expect(call('/api/profile-leads?profile_id='+created.id,b)).rejects.toMatchObject({status:404});
    await expect(call('/api/profiles/'+created.id,b,'DELETE')).rejects.toMatchObject({status:404});
    const own=await (await call('/api/profile-leads?profile_id='+created.id))!.json<{total:number}>();expect(own.total).toBe(1);
  });
});
