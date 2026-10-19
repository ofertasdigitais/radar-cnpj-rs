import {env} from 'cloudflare:workers';
import {beforeEach,describe,expect,it} from 'vitest';
import {handleProspects,prospectFingerprint,validateProspect} from '../src/prospects-current';
import {ApiError,now,type Principal,type Env} from '../src/runtime';

const principal:Principal={accountId:'prospect-owner-a',username:'seller-a',role:'vendedor',expires:9999999999};
const other:Principal={...principal,accountId:'prospect-owner-b'};
async function call(path:string,method='GET',body?:unknown,actor=principal):Promise<Response> {
  const request=new Request('https://radar.test'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  try {const response=await handleProspects(request,env as unknown as Env,actor,new URL(request.url));if(!response)throw Error('unhandled');return response;}
  catch(error){if(error instanceof ApiError)return new Response(JSON.stringify({erro:error.message}),{status:error.status});throw error;}
}
async function imported(rows:unknown[]):Promise<string[]> {
  const response=await call('/api/prospects/import','POST',{rows});expect(response.status).toBe(201);
  return (await env.DB.prepare('SELECT id FROM prospect_inbox WHERE owner_id=? ORDER BY name').bind(principal.accountId).all<{id:string}>()).results.map(r=>r.id);
}
beforeEach(async()=>{
  for(const table of ['discovery_notifications','discovery_recommendations','discovery_sources','discovery_runs','discovery_campaigns','prospect_links','prospect_history','prospect_inbox','sales_lead_history','sales_profile_leads','sales_profiles','private_companies','contact_suppression','companies'])await env.DB.prepare('DELETE FROM '+table).run();
  const stamp=now();
  await env.DB.batch([
    env.DB.prepare('INSERT INTO sales_profiles(id,name,owner_id,created_at,updated_at) VALUES(?,?,?,?,?)').bind('own-profile','Meu painel',principal.accountId,stamp,stamp),
    env.DB.prepare('INSERT INTO sales_profiles(id,name,owner_id,created_at,updated_at) VALUES(?,?,?,?,?)').bind('other-profile','Outro painel',other.accountId,stamp,stamp),
    env.DB.prepare("INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,municipio,uf) VALUES('12345678000190','Empresa oficial','Loja oficial','ATIVA','Porto Alegre','RS')"),
    env.DB.prepare("INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,municipio,uf) VALUES('12345678000191','Privada B','Privada B','TESTE','Porto Alegre','ZZ')"),
    env.DB.prepare("INSERT INTO private_companies(cnpj,owner_id) VALUES('12345678000191',?)").bind(other.accountId),
  ]);
});
describe('prospects current contracts',()=>{
  it('validates an entire CSV import before inserting and imports 500 contacts in one SQL',async()=>{
    const invalid=await call('/api/prospects/import','POST',{rows:[{name:'Válido'},{name:'Inválido',email:'bad'}]});expect(invalid.status).toBe(400);
    expect((await call('/api/prospects').then(r=>r.json())) as unknown).toMatchObject({total:0});
    const rows=Array.from({length:500},(_,i)=>({name:'Contato '+i,phone:'519999'+i}));
    expect(await (await call('/api/prospects/import','POST',{rows})).json()).toEqual({created:500,duplicates:0,total_received:500});
    expect(await (await call('/api/prospects/import','POST',{rows})).json()).toEqual({created:0,duplicates:500,total_received:500});
    const page=await (await call('/api/prospects?page=2')).json() as {items:unknown[];total:number;size:number};expect(page.items).toHaveLength(50);expect(page.total).toBe(500);expect(page.size).toBe(50);
    expect(await (await call('/api/prospects',undefined,undefined,other)).json()).toMatchObject({total:0});
  });
  it('keeps edits isolated and rejects stale revisions without adding history',async()=>{
    const [id]=await imported([{name:'Loja',notes:'anotação original'}]);
    expect((await call('/api/prospects/'+id,'PUT',{notes:'primeira alteração',revision:1})).status).toBe(200);
    expect((await call('/api/prospects/'+id,'PUT',{notes:'stale',revision:1})).status).toBe(409);
    expect((await call('/api/prospects/'+id,'PUT',{notes:'cross-account'},other)).status).toBe(404);
    const history=await (await call('/api/prospects/history?id='+id)).json() as {items:unknown[]};expect(history.items).toHaveLength(1);
    expect((await call('/api/prospects/history?id='+id,'GET',undefined,other)).status).toBe(404);
    const row=await env.DB.prepare('SELECT * FROM prospect_inbox WHERE id=?').bind(id).first();expect(row).toMatchObject({notes:'primeira alteração',revision:2});
  });
  it('previews only visible company identities and allows only owner profiles',async()=>{
    const [id]=await imported([{name:'Externo'}]);
    expect(await (await call('/api/prospects/company?cnpj=12345678000191')).json()).toEqual({item:null});
    expect((await call('/api/prospects/qualify','POST',{prospect_id:id,profile_id:'own-profile',cnpj:'12345678000191'})).status).toBe(404);
    expect((await call('/api/prospects/qualify','POST',{prospect_id:id,profile_id:'other-profile',cnpj:'12345678000190'})).status).toBe(404);
    expect(await (await call('/api/prospects/options')).json()).toEqual({profiles:[{id:'own-profile',name:'Meu painel'}]});
  });
  it('qualifies idempotently and preserves existing lead work',async()=>{
    const [id]=await imported([{name:'Externo',phone:'51999999999',notes:'Fonte externa',source:'CSV da equipe',campaign:'Campanha A'}]);
    await env.DB.prepare("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,lead_status,observacoes,estrategia) VALUES('own-profile','12345678000190',?,?,'negociacao','Trabalho existente','Estratégia existente')").bind(now(),now()).run();
    const body={prospect_id:id,profile_id:'own-profile',cnpj:'12345678000190'};
    expect(await (await call('/api/prospects/qualify','POST',body)).json()).toMatchObject({created:false,linked:true});
    expect(await (await call('/api/prospects/qualify','POST',body)).json()).toMatchObject({created:false,linked:false});
    expect(await env.DB.prepare("SELECT lead_status,observacoes,estrategia FROM sales_profile_leads WHERE profile_id='own-profile'").first()).toEqual({lead_status:'negociacao',observacoes:'Trabalho existente',estrategia:'Estratégia existente'});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM prospect_history').first()).toEqual({n:1});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM sales_lead_history').first()).toEqual({n:1});
    expect(await env.DB.prepare('SELECT status,revision FROM prospect_inbox WHERE id=?').bind(id).first()).toEqual({status:'qualificado',revision:2});
  });
  it('requires confirmation for another active approach and rolls back fingerprint collisions',async()=>{
    const [id]=await imported([{name:'Externo'}]);
    await env.DB.prepare("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,lead_status) VALUES('other-profile','12345678000190',?,?,'contatado')").bind(now(),now()).run();
    const body={prospect_id:id,profile_id:'own-profile',cnpj:'12345678000190'};
    const duplicate=await call('/api/prospects/qualify','POST',body);expect(duplicate.status).toBe(409);expect(await duplicate.json()).toMatchObject({duplicate:true});
    await call('/api/prospects/import','POST',{rows:[{name:'Externo',cnpj:'12345678000190'}]});
    expect((await call('/api/prospects/qualify','POST',{...body,allow_duplicate:true})).status).toBe(409);
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM sales_profile_leads WHERE profile_id='own-profile'").first()).toEqual({n:0});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM prospect_links').first()).toEqual({n:0});
    expect(await env.DB.prepare('SELECT status,cnpj FROM prospect_inbox WHERE id=?').bind(id).first()).toEqual({status:'novo',cnpj:''});
  });
  it('carries suppression flags through a linked CNPJ and rejects unsafe URL schemes',async()=>{
    const [id]=await imported([{name:'Externo'}]);
    expect((await call('/api/prospects/qualify','POST',{prospect_id:id,profile_id:'own-profile',cnpj:'12345678000190'})).status).toBe(201);
    await env.DB.prepare('INSERT INTO contact_suppression(owner_id,cnpj,reason,updated_at) VALUES(?,?,?,?)').bind(principal.accountId,'12345678000190','Solicitado',now()).run();
    const data=await (await call('/api/prospects')).json() as {items:{do_not_contact:boolean;linked:number}[];summary:unknown};expect(data.items[0]).toMatchObject({do_not_contact:true,linked:1});expect(data.summary).toMatchObject({linked:1,not_linked:0});
    expect(()=>validateProspect({name:'Externo',website:'javascript:alert(1)'})).toThrow();
    expect(await prospectFingerprint(validateProspect({name:'  LOJA ',company:'Comércio',phone:'(51) 99999-9999',email:'TESTE@EXAMPLE.COM'}))).toBe(await prospectFingerprint(validateProspect({name:'loja',company:'COMÉRCIO',phone:'51999999999',email:'teste@example.com'})));
    // Expected SHA-256 from the existing Python fingerprint, including Unicode case folding.
    expect(await prospectFingerprint({name:'Straße Μῆνιν Ꭰ ꭰ ﬃ'})).toBe('a9c3c2ad8c12d59ef0b3cfdd3b110852eb73de3676a80dbac86df9869103862b');
    expect(()=>validateProspect({name:'Contato',phone:null})).toThrow('precisa ser texto');
  });
});
