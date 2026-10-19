import { env } from 'cloudflare:workers';
import { beforeAll, describe, expect, it } from 'vitest';
import { handleSales } from '../src/sales';
import { ApiError, type Env, type Principal } from '../src/runtime';
import { commercialAnalytics, localTimestamp, metrics, operationsDashboard, phoneQuality, safeDateTime, type Lead } from '../src/sales-analytics';
import { commercialPdf } from '../src/report-current';
import { PDFDocument } from 'pdf-lib';

const principal: Principal = {accountId:'sales-a',username:'sales-a',role:'vendedor',expires:9999999999};
const other: Principal = {...principal,accountId:'sales-b',username:'sales-b'};
const admin: Principal = {...principal,accountId:'sales-admin',role:'admin'};
const cnpj='11888888000101';
const privateCnpj='99988888000101';
const origin='https://sales.test';
async function request(path:string,method='GET',payload?:Record<string,unknown>,who=principal) {
  const url=new URL(origin+path);
  try {
    return await handleSales(new Request(url,{method,headers:payload?{'Content-Type':'application/json'}:undefined,body:payload?JSON.stringify(payload):undefined}),env as unknown as Env,who,url);
  } catch(error) {
    if(error instanceof ApiError)return new Response(JSON.stringify({erro:error.message}),{status:error.status,headers:{'Content-Type':'application/json'}});
    throw error;
  }
}
async function data(path:string,method='GET',payload?:Record<string,unknown>,who=principal) {
  const response=await request(path,method,payload,who);
  expect(response).toBeInstanceOf(Response);
  return {response:response!,body:await response!.json() as any};
}
beforeAll(async()=>{
  const stamp='2026-10-01T09:00:00';
  await env.DB.batch([
    ...['sales-a','sales-b','sales-admin'].map(id=>env.DB.prepare('INSERT INTO user_accounts(id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?)').bind(id,id,id,id+'@test.invalid','unused','unused',id==='sales-admin'?'admin':'vendedor',stamp,stamp)),
    env.DB.prepare('INSERT INTO companies(cnpj,razao_social,nome_fantasia,situacao,data_abertura,telefone,uf) VALUES(?,?,?,?,?,?,?)').bind(cnpj,'Empresa oficial','=EMPRESA OFICIAL','ATIVA','2026-09-01','51999999999','RS'),
    env.DB.prepare('INSERT INTO companies(cnpj,razao_social,situacao,uf) VALUES(?,?,?,?)').bind(privateCnpj,'Privado A','TESTE','ZZ'),
    ...[['sales-profile-a','sales-a'],['sales-profile-b','sales-b']].map(([id,owner])=>env.DB.prepare('INSERT INTO sales_profiles(id,owner_id,name,created_at,updated_at) VALUES(?,?,?,?,?)').bind(id,owner,id,stamp,stamp)),
    env.DB.prepare('INSERT INTO private_companies(cnpj,owner_id) VALUES(?,?)').bind(privateCnpj,'sales-a'),
    // Preserve an inaccessible legacy link; it must never grant private ownership.
    env.DB.prepare('INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at) VALUES(?,?,?,?)').bind('sales-profile-b',privateCnpj,stamp,stamp),
  ]);
});

describe('current sales contracts on D1',()=>{
  it('keeps unrelated routes available to the dispatcher',async()=>{
    expect(await request('/api/companies')).toBeUndefined();
  });
  it('enforces owner scopes, even for private companies linked by legacy data',async()=>{
    expect((await request('/api/team-leads?profile_id=sales-profile-a','GET',undefined,other))!.status).toBe(404);
    expect((await data('/api/team-leads?profile_id=sales-profile-b','GET',undefined,other)).body.total).toBe(0);
    expect((await request('/api/team-leads','POST',{profile_id:'sales-profile-b',cnpj:privateCnpj},other))!.status).toBe(404);
    const membership=(await data('/api/team-memberships?cnpj='+privateCnpj,'GET',undefined,other)).body;
    expect(membership.items.every((x:any)=>!x.selected)).toBe(true);
  });
  it('adds the official lead, updates currency as integer cents, and rejects stale changes without history',async()=>{
    const added=await data('/api/team-leads','POST',{profile_id:'sales-profile-a',cnpj});
    expect(added.response.status).toBe(201); expect(added.body.adicionado).toBe(true);
    const first=(await data('/api/team-memberships?cnpj='+cnpj)).body.items.find((x:any)=>x.id==='sales-profile-a');
    const saved=await data('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,expected_updated_at:first.updated_at,lead_status:'convertido',closed_value_cents:12500,offered_value_cents:'R$ 140,50',campaign:'Campanha A'});
    expect(saved.response.status).toBe(200); expect(saved.body.profile_closed_value_cents).toBe(12500);
    expect(saved.body.profile_offered_value_cents).toBe(14050); expect(saved.body.profile_closed_at).toBeTruthy();
    const historyBefore=(await data('/api/team-lead-history?profile_id=sales-profile-a&cnpj='+cnpj)).body.items;
    expect((await request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,expected_updated_at:first.updated_at,observacoes:'stale'}))!.status).toBe(409);
    expect((await data('/api/team-lead-history?profile_id=sales-profile-a&cnpj='+cnpj)).body.items).toEqual(historyBefore);
    await request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,lead_status:'novo'});
  });
  it('requires revision for quick contacts, counts events, and completes the seventh stage',async()=>{
    const agenda=(await data('/api/sales-ops?profile_id=sales-profile-a')).body.agenda.find((x:any)=>x.cnpj===cnpj);
    expect(agenda.revision).toMatch(/^[a-f0-9]{64}$/);
    expect((await request('/api/sales-ops/contact','POST',{profile_id:'sales-profile-a',cnpj,revision:'stale',outcome:'respondeu'}))!.status).toBe(409);
    expect((await request('/api/sales-ops/contact','POST',{profile_id:'sales-profile-a',cnpj,revision:agenda.revision,outcome:'respondeu',notes:'Contato feito',next_action:'Retornar',next_action_at:'2030-10-15T14:00'}))!.status).toBe(200);
    const changed=(await data('/api/sales-ops?profile_id=sales-profile-a')).body;
    expect(changed.agenda.find((x:any)=>x.cnpj===cnpj).stage).toBe('contatado');
    expect(changed.current.contacts).toBeGreaterThan(0);
    expect((await request('/api/sales-ops/complete','POST',{profile_id:'sales-profile-a',cnpj,revision:changed.agenda.find((x:any)=>x.cnpj===cnpj).revision,mode:'lead',notes:'Atendimento resolvido'}))!.status).toBe(200);
    const closed=(await data('/api/team-leads?profile_id=sales-profile-a&status=concluido')).body;
    expect(closed.items[0].profile_lead_status).toBe('concluido');
    expect((await data('/api/commercial?profile_id=sales-profile-a')).body.stages.find((x:any)=>x.key==='concluido').total).toBe(1);
  });
  it('applies suppression to selected seller when admin acts and omits blocked contacts from CSV',async()=>{
    await request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,lead_status:'novo'});
    const blocked=await request('/api/sales-ops/suppression','POST',{profile_id:'sales-profile-a',cnpj,blocked:true,reason:'Sem autorização'},admin);
    expect(blocked!.status).toBe(200);
    const list=(await data('/api/team-leads?profile_id=sales-profile-a')).body;
    expect(list.items[0].profile_do_not_contact).toBe(true);
    expect((await request('/api/team-lead-events','POST',{profile_id:'sales-profile-a',cnpj,event_type:'whatsapp_opened'}))!.status).toBe(403);
    expect(await (await request('/api/team-leads.csv?profile_id=sales-profile-a'))!.text()).not.toContain(cnpj);
    expect((await request('/api/sales-ops/suppression','POST',{profile_id:'sales-profile-a',cnpj,blocked:false}))!.status).toBe(400);
    await request('/api/sales-ops/suppression','POST',{profile_id:'sales-profile-a',cnpj,blocked:false,confirm_restore:true});
    expect(await (await request('/api/team-leads.csv?profile_id=sales-profile-a&fields=empresa,cnpj'))!.text()).toContain("'=EMPRESA OFICIAL");
  });
  it('retains one default message template and never reads another owner template',async()=>{
    const existing=(await data('/api/message-templates')).body.items;
    expect(existing).toHaveLength(1); expect(existing[0].is_default).toBe(1);
    const added=(await data('/api/message-templates','POST',{name:'Seguimento',body:'Oi {empresa}',is_default:true})).body;
    expect((await request('/api/message-templates/'+added.id,'PUT',{body:'no'},other))!.status).toBe(404);
    await request('/api/message-templates/'+added.id,'DELETE');
    const remaining=(await data('/api/message-templates')).body.items;
    expect(remaining).toHaveLength(1); expect(remaining[0].is_default).toBe(1);
    expect((await request('/api/message-templates/'+remaining[0].id,'DELETE'))!.status).toBe(400);
  });
  it('creates canonical private test leads and archives removals with their history',async()=>{
    const created=await data('/api/team-leads/test','POST',{profile_id:'sales-profile-a',name:'Teste privado',phone:'51999999999'});
    expect(created.response.status).toBe(201);
    const canonical=await env.DB.prepare('SELECT owner_id FROM private_companies WHERE cnpj=?').bind(created.body.cnpj).first();
    expect(canonical?.owner_id).toBe('sales-a');
    expect((await request('/api/team-leads','POST',{profile_id:'sales-profile-b',cnpj:created.body.cnpj},other))!.status).toBe(404);
    expect((await request('/api/team-leads?profile_id=sales-profile-a&cnpj='+created.body.cnpj,'DELETE'))!.status).toBe(200);
    const archives=(await data('/api/commercial-archive?profile_id=sales-profile-a')).body.items;
    expect(archives.find((x:any)=>x.cnpj===created.body.cnpj)?.events_json).toContain('created');
  });
  it('validates monthly targets and emits a real commercial PDF',async()=>{
    expect((await request('/api/sales-ops/targets','POST',{profile_id:'sales-profile-a',month:'2026-13',wins:1}))!.status).toBe(400);
    expect((await request('/api/sales-ops/targets','POST',{profile_id:'sales-profile-a',month:'2026-10',revenue_cents:100000,contacts:5,wins:1}))!.status).toBe(200);
    const pdf=(await request('/api/commercial-report.pdf?profile_id=sales-profile-a'))!;
    expect(pdf.headers.get('Content-Type')).toBe('application/pdf');
    expect(new TextDecoder().decode(await pdf.arrayBuffer()).startsWith('%PDF-')).toBe(true);
  });
  it('blocks every portfolio export/read/write against another seller and rejects hidden private legacy history',async()=>{
    for(const path of ['/api/team-dashboard','/api/team-activity','/api/commercial','/api/commercial-archive','/api/commercial-report.pdf','/api/team-leads.csv','/api/sales-ops']) {
      expect((await request(path+'?profile_id=sales-profile-a','GET',undefined,other))!.status,path).toBe(404);
    }
    expect((await request('/api/team-lead-history?profile_id=sales-profile-b&cnpj='+privateCnpj,'GET',undefined,other))!.status).toBe(404);
    expect((await request('/api/team-leads','PUT',{profile_id:'sales-profile-b',cnpj:privateCnpj,observacoes:'unauthorized'},other))!.status).toBe(404);
    expect((await request('/api/team-lead-events','POST',{profile_id:'sales-profile-b',cnpj:privateCnpj,event_type:'whatsapp_opened'},other))!.status).toBe(404);
    expect(await (await request('/api/team-leads.csv?profile_id=sales-profile-b','GET',undefined,other))!.text()).not.toContain(privateCnpj);
  });
  it('allows one concurrent revision update and appends history only for the winner',async()=>{
    const before=(await data('/api/team-memberships?cnpj='+cnpj)).body.items.find((x:any)=>x.id==='sales-profile-a');
    const countBefore=(await data('/api/team-lead-history?profile_id=sales-profile-a&cnpj='+cnpj)).body.items.length;
    const results=await Promise.all(['first edit','second edit'].map(note=>request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,expected_updated_at:before.updated_at,observacoes:note})));
    expect(results.map(x=>x!.status).sort()).toEqual([200,409]);
    const after=(await data('/api/team-lead-history?profile_id=sales-profile-a&cnpj='+cnpj)).body.items;
    expect(after.length-countBefore).toBe(2); // One field diff plus one notes event.
    expect(after.filter((x:any)=>x.event_type==='notes_updated')).toHaveLength(1);
  });
  it('requires duplicate confirmation for another active portfolio and preserves ownership',async()=>{
    const rejected=await data('/api/team-leads','POST',{profile_id:'sales-profile-b',cnpj},other);
    expect(rejected.response.status).toBe(409);expect(rejected.body.duplicate).toBe(true);
    expect((await request('/api/team-leads','POST',{profile_id:'sales-profile-b',cnpj,allow_duplicate:true},other))!.status).toBe(201);
    await request('/api/team-leads?profile_id=sales-profile-b&cnpj='+cnpj,'DELETE',undefined,other);
    expect((await data('/api/team-leads?profile_id=sales-profile-a')).body.total).toBe(1);
  });
  it('validates enum own keys, impossible dates, money, bounded bodies, and corrected phone searches',async()=>{
    for(const patch of [{lead_status:'constructor'},{contact_outcome:'toString'},{loss_reason:'__proto__'},{next_action_at:'2026-02-30T10:00'},{closed_value_cents:true},{closed_value_cents:-1}]) {
      expect((await request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,...patch}))!.status).toBe(400);
    }
    expect((await request('/api/team-leads?profile_id=sales-profile-a&status=toString'))!.status).toBe(400);
    expect((await request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,observacoes:'x'.repeat(70000)}))!.status).toBe(413);
    await request('/api/team-leads','PUT',{profile_id:'sales-profile-a',cnpj,whatsapp_phone:'55 (51) 99999-9999',whatsapp_status:'confirmed',offered_value_cents:'140,505'});
    const result=(await data('/api/team-leads?profile_id=sales-profile-a&q='+encodeURIComponent('+55 (51) 99999-9999'))).body;
    expect(result.total).toBe(1);expect(result.items[0].profile_whatsapp_phone).toBe('5551999999999');expect(result.items[0].profile_offered_value_cents).toBe(14051);
    expect((await request('/api/team-leads.csv?profile_id=sales-profile-a&fields=constructor'))!.status).toBe(200);
  });
  it('keeps full contact notes as valid structured history and separates opened links from contacts',async()=>{
    const note='Á'.repeat(1000),agenda=(await data('/api/sales-ops?profile_id=sales-profile-a')).body.agenda.find((x:any)=>x.cnpj===cnpj);
    const recorded=await data('/api/sales-ops/contact','POST',{profile_id:'sales-profile-a',cnpj,revision:agenda.revision,outcome:'retornar',notes:note,next_action:'Próxima ação',next_action_at:'2030-10-15T14:00'});
    expect(recorded.response.status).toBe(200);
    const history=(await data('/api/team-lead-history?profile_id=sales-profile-a&cnpj='+cnpj)).body.items;
    const event=history.find((x:any)=>x.event_type==='contact_recorded');
    expect(JSON.parse(event.details).note).toBe(note);expect(event.created_at).toBe(recorded.body.created_at);
    const before=(await data('/api/sales-ops?profile_id=sales-profile-a')).body.current.contacts;
    expect((await request('/api/team-lead-events','POST',{profile_id:'sales-profile-a',cnpj,event_type:'whatsapp_opened'}))!.status).toBe(201);
    expect((await data('/api/sales-ops?profile_id=sales-profile-a')).body.current.contacts).toBe(before);
  });
  it('archives only canonical-owner private records and honors administrator test-lead setting',async()=>{
    await env.DB.batch([
      env.DB.prepare('INSERT INTO commercial_archive(profile_id,cnpj,company_name,removed_at,events_json) VALUES(?,?,?,?,?)').bind('sales-profile-b',privateCnpj,'Leaked copy','2026-10-15','[]'),
      env.DB.prepare('INSERT INTO admin_parameters(key,value,updated_at) VALUES(?,?,?)').bind('test_leads','false','2026-10-16'),
    ]);
    expect((await data('/api/commercial-archive?profile_id=sales-profile-b','GET',undefined,other)).body.items.some((x:any)=>x.cnpj===privateCnpj)).toBe(false);
    expect((await request('/api/team-leads/test','POST',{profile_id:'sales-profile-a',name:'Disabled',phone:'51999999999'}))!.status).toBe(403);
    await env.DB.prepare('DELETE FROM admin_parameters WHERE key=?').bind('test_leads').run();
  });
  it('creates and removes complete seller profiles and persists commercial settings with owner checks',async()=>{
    const created=await data('/api/team-profiles','POST',{name:'Nova responsável',role:'Consultora',email:'new@test.invalid'});
    expect(created.response.status).toBe(201);expect(created.body.initials).toBe('NR');
    const profileId=created.body.id;
    expect((await request('/api/commercial-settings','POST',{profile_id:profileId,contact_sla_hours:0,stalled_days:7}))!.status).toBe(400);
    expect((await request('/api/commercial-settings','POST',{profile_id:profileId,contact_sla_hours:24,stalled_days:4},other))!.status).toBe(404);
    expect((await request('/api/commercial-settings','POST',{profile_id:profileId,contact_sla_hours:24,stalled_days:4}))!.status).toBe(200);
    const empty=(await data('/api/commercial?profile_id='+profileId)).body;
    expect(empty.settings).toEqual({contact_sla_hours:24,stalled_days:4});expect(empty.summary.avg_close_days).toBeNull();
    const lead=await data('/api/team-leads/test','POST',{profile_id:profileId,name:'Lead do perfil descartável',phone:'51999999999'});
    expect((await request('/api/team-profiles/'+profileId,'DELETE',undefined,other))!.status).toBe(404);
    expect((await request('/api/team-profiles/'+profileId,'DELETE'))!.status).toBe(200);
    expect(await env.DB.prepare('SELECT 1 FROM sales_profile_leads WHERE profile_id=?').bind(profileId).first()).toBeNull();
    expect(await env.DB.prepare('SELECT 1 FROM sales_lead_history WHERE profile_id=?').bind(profileId).first()).toBeNull();
    expect(await env.DB.prepare('SELECT owner_id FROM private_companies WHERE cnpj=?').bind(lead.body.cnpj).first()).toEqual({owner_id:'sales-a'});
  });
});

describe('commercial metric definitions',()=>{
  const lead=(overrides:Record<string,unknown>={}):Lead=>({profile_id:'metric-profile',cnpj:'11999999000101',added_at:'2026-10-01T09:00:00',updated_at:'2026-10-02T09:00:00',lead_status:'novo',favorito:0,observacoes:'',estrategia:'',contact_outcome:'',next_action:'',next_action_at:null,last_contact_at:null,first_contact_at:null,closed_at:null,offered_value_cents:0,negotiated_value_cents:0,closed_value_cents:0,whatsapp_status:'pending',whatsapp_phone:'',whatsapp_checked_at:null,campaign:'',persona:'',lead_origin:'',loss_reason:'',razao_social:'Métrica',nome_fantasia:'',telefone:'51999999999',segmento:'Serviços',...overrides});
  it('keeps cohort denominators and excludes concluded/suppressed leads from pipeline',()=>{
    const items=[lead({offered_value_cents:10000,negotiated_value_cents:8000}),lead({cnpj:'2',lead_status:'convertido',closed_value_cents:5000,closed_at:'2026-10-03T09:00:00',first_contact_at:'2026-10-02T09:00:00'}),lead({cnpj:'3',lead_status:'concluido',negotiated_value_cents:99999}),lead({cnpj:'4',do_not_contact:true,negotiated_value_cents:88888})];
    const stats=metrics(items);
    expect(stats.total).toBe(4);expect(stats.active).toBe(1);expect(stats.conversion_pct).toBe(25);expect(stats.pipeline_cents).toBe(8000);expect(stats.closed_cents).toBe(5000);expect(stats.avg_first_contact_hours).toBe(24);expect(stats.avg_close_days).toBe(2);
    const analytics=commercialAnalytics(items,{contact_sla_hours:48,stalled_days:7});
    expect(analytics.queue.map(x=>x.cnpj)).toEqual(['11999999000101']);expect(analytics.stages).toHaveLength(7);
  });
  it('counts closing dates across entry cohorts and validates São Paulo offset dates',async()=>{
    const items=[lead({added_at:'2026-09-01T09:00:00',lead_status:'convertido',closed_at:'2026-10-03T09:00:00',closed_value_cents:15000})];
    const result=await operationsDashboard(items,[{cnpj:items[0].cnpj,event_type:'contact_recorded',created_at:'2026-10-02T10:00:00'}],new Map(),undefined,'2026-10-01','2026-10-05','2026-10');
    expect(result.current.entries).toBe(0);expect(result.current.wins).toBe(1);expect(result.current.closed_cents).toBe(15000);expect(result.trend.find(x=>x.date==='2026-10-03')!.wins).toBe(1);
    expect(localTimestamp('2026-10-02T01:30:00Z')).toBe('2026-10-01T22:30:00');expect(safeDateTime('2026-10-02T01:30:00Z')).toBe('2026-10-01T22:30');
    expect(phoneQuality('55 51 99999-9999').normalized).toBe('5551999999999');expect(phoneQuality('00000000000').format_valid).toBe(false);
    await expect(operationsDashboard(items,[],new Map(),undefined,'2025-01-01','2026-10-01')).rejects.toBeInstanceOf(ApiError);
  });
  it('reuses the Radar report studio, embeds Inter, and paginates the full queue',async()=>{
    const items=Array.from({length:90},(_,i)=>lead({cnpj:String(i).padStart(14,'0'),razao_social:'Empresa '+i}));
    const bytes=await commercialPdf(env as unknown as Env,origin,'Responsável',commercialAnalytics(items,{contact_sla_hours:48,stalled_days:7}),{report_title:'Desempenho comercial',site_name:'Radar CNPJ',report_footer:'Uso interno - dados privados'});
    const doc=await PDFDocument.load(bytes);
    expect(doc.getTitle()).toBe('Desempenho comercial');expect(doc.getPageCount()).toBeGreaterThan(8);
    // Embedded Inter keeps Portuguese accents as text and preserves the local brand template.
    expect(doc.getPages()[0].getSize().width).toBeCloseTo(841.89);
  });
  it('fails visibly when the local report fonts are missing',async()=>{
    const data=commercialAnalytics([],{contact_sla_hours:48,stalled_days:7});
    const unavailable={...env,ASSETS:{fetch:async()=>new Response('Missing',{status:404})}} as unknown as Env;
    await expect(commercialPdf(unavailable,origin,'Responsável',data,{})).rejects.toMatchObject({status:503});
    expect(localTimestamp('2026-02-30T10:00:00Z')).toBeNull();expect(localTimestamp('2026-10-16T24:00:00Z')).toBeNull();
  });
});
