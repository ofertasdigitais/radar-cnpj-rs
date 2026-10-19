import {env} from 'cloudflare:workers';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {fetchOsm,handleDiscovery,nextScheduled,osmRecords,overpassQuery,saoPauloTime,scheduledDiscovery,validateCampaign} from '../src/discovery-current';
import {ApiError,now,type Env,type Principal} from '../src/runtime';

const actor:Principal={accountId:'discovery-owner-a',username:'seller-a',role:'vendedor',expires:9999999999};
const other:Principal={...actor,accountId:'discovery-owner-b'};
const campaign={name:'Restaurantes POA',city:'Porto Alegre',category:'restaurantes',frequency:'manual',active:true};
const elements=[{type:'node',id:101,tags:{name:'Restaurante público',phone:'51999999999',website:'https://example.com',email:'contato@example.com'}},{type:'way',id:202,tags:{name:'Café público'}}];
async function call(path:string,method='GET',body?:unknown,principal=actor,context?:{waitUntil(promise:Promise<unknown>):void}):Promise<Response> {
  const request=new Request('https://radar.test'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  try {const response=await handleDiscovery(request,env as unknown as Env,principal,new URL(request.url),context);if(!response)throw Error('unhandled');return response;}
  catch(error){if(error instanceof ApiError)return new Response(JSON.stringify({erro:error.message}),{status:error.status});throw error;}
}
async function create(body:unknown=campaign):Promise<string> {const response=await call('/api/discovery/campaigns','POST',body);expect(response.status).toBe(201);return (await response.json() as {id:string}).id;}
async function run(id:string):Promise<string> {const response=await call('/api/discovery/campaigns/'+id+'/run','POST');expect(response.status).toBe(202);return (await response.json() as {id:string}).id;}
beforeEach(async()=>{
  for(const table of ['discovery_notifications','discovery_recommendations','discovery_sources','discovery_runs','discovery_campaigns','discovery_preferences','discovery_cache','prospect_links','prospect_history','prospect_inbox','admin_parameters'])await env.DB.prepare('DELETE FROM '+table).run();
});
afterEach(()=>{vi.restoreAllMocks();});

describe('discovery current contracts',()=>{
  it('calculates three daily Sao Paulo slots and skips missed slots without host timezone dependence',()=>{
    expect(nextScheduled(['08:00','13:00','17:00'],Date.parse('2026-10-16T10:59:59Z'))).toBe('2026-10-16T08:00:00');
    expect(nextScheduled(['08:00','13:00','17:00'],Date.parse('2026-10-16T11:00:00Z'))).toBe('2026-10-16T13:00:00');
    expect(nextScheduled(['08:00','13:00','17:00'],Date.parse('2026-10-16T20:00:00Z'))).toBe('2026-10-17T08:00:00');
    expect(()=>validateCampaign({...campaign,frequency:'scheduled',times:['08:00','08:30']})).toThrow('uma hora');
    expect(()=>validateCampaign({...campaign,frequency:'scheduled',times:['08:00','08:00']})).toThrow();
    expect(()=>validateCampaign({...campaign,city:'Porto Alegre"];out;'})).toThrow();
  });
  it('creates, pauses and edits owner campaigns with revisions and cursor resets',async()=>{
    const id=await create({...campaign,frequency:'scheduled',times:['08:00','13:00','17:00']});
    await env.DB.prepare('UPDATE discovery_campaigns SET cursor_json=? WHERE id=?').bind('{"node":100}',id).run();
    expect((await call('/api/discovery/campaigns/'+id,'PUT',{...campaign,city:'Caxias do Sul',active:false,revision:1})).status).toBe(200);
    expect((await call('/api/discovery/campaigns/'+id,'PUT',{...campaign,revision:1})).status).toBe(409);
    expect((await call('/api/discovery/campaigns/'+id,'PUT',campaign,other)).status).toBe(404);
    expect(await env.DB.prepare('SELECT revision,cursor_json,next_run_at FROM discovery_campaigns WHERE id=?').bind(id).first()).toEqual({revision:2,cursor_json:'{}',next_run_at:null});
    expect((await call('/api/discovery/campaigns/'+id+'/run','POST')).status).toBe(400);
    const snapshot=await (await call('/api/discovery')).json() as {campaigns:unknown[];collector_ready:boolean;osm_mode:string;local_osm:{ready:boolean}};
    expect(snapshot.campaigns).toHaveLength(1);expect(snapshot.collector_ready).toBe(false);expect(snapshot.osm_mode).toBe('overpass');expect(snapshot.local_osm.ready).toBe(false);
    expect(await (await call('/api/discovery','GET',undefined,other)).json()).toMatchObject({campaigns:[],runs:[],total:0});
  });
  it('captures real mocked source rows, creates private recommendations/notifications and preserves seller edits on repeat',async()=>{
    const network=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({elements}),{headers:{'Content-Type':'application/json'}}));
    const id=await create({...campaign,enrich_websites:true}),runId=await run(id);
    expect(await env.DB.prepare('SELECT status,found,added,duplicates,enriched FROM discovery_runs WHERE id=?').bind(runId).first()).toEqual({status:'parcial',found:2,added:2,duplicates:0,enriched:0});
    expect(network).toHaveBeenCalledTimes(1);expect(network.mock.calls[0][1]).toMatchObject({redirect:'error',method:'POST'});
    const cacheExpiry=await env.DB.prepare('SELECT expires_at FROM discovery_cache').first();
    const recommendations=await (await call('/api/discovery/recommendations')).json() as {items:{id:string;revision:number;prospect_id:string}[];total:number};expect(recommendations.total).toBe(2);
    expect(await (await call('/api/discovery/notifications')).json()).toMatchObject({unread:1,enabled:true});
    expect(await (await call('/api/discovery/sources','GET',undefined,other)).json()).toEqual({items:[]});
    await env.DB.prepare("UPDATE prospect_inbox SET notes='Trabalho do vendedor',phone='51912345678',revision=revision+1 WHERE id=?").bind(recommendations.items[0].prospect_id).run();
    await env.DB.prepare('UPDATE discovery_runs SET started_at=?').bind(saoPauloTime(Date.now()-120000)).run();
    const repeat=await run(id);
    expect(network).toHaveBeenCalledTimes(1);
    expect(await env.DB.prepare('SELECT expires_at FROM discovery_cache').first()).toEqual(cacheExpiry);
    expect(await env.DB.prepare('SELECT added,duplicates FROM discovery_runs WHERE id=?').bind(repeat).first()).toEqual({added:0,duplicates:2});
    expect(await env.DB.prepare('SELECT notes,phone FROM prospect_inbox WHERE id=?').bind(recommendations.items[0].prospect_id).first()).toEqual({notes:'Trabalho do vendedor',phone:'51912345678'});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM discovery_recommendations').first()).toEqual({n:2});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM discovery_notifications').first()).toEqual({n:1});
  });
  it('validates a recommendation review batch atomically and never qualifies prospects implicitly',async()=>{
    vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({elements})));
    const id=await create();await run(id);
    const list=await (await call('/api/discovery/recommendations')).json() as {items:{id:string;revision:number}[]};
    const items=list.items.map(({id,revision})=>({id,revision}));
    expect((await call('/api/discovery/recommendations/review','POST',{status:'accepted',items:[items[0],{...items[1],revision:99}]})).status).toBe(409);
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM discovery_recommendations WHERE status='pending'").first()).toEqual({n:2});
    expect((await call('/api/discovery/recommendations/review','POST',{status:'accepted',items},other)).status).toBe(404);
    expect(await (await call('/api/discovery/recommendations/review','POST',{status:'accepted',items})).json()).toEqual({status:'accepted',updated:2});
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM prospect_inbox WHERE status='novo'").first()).toEqual({n:2});
    expect((await call('/api/discovery/recommendations/review','POST',{status:'dismissed',items})).status).toBe(409);
  });
  it('records upstream failures accurately and does not retry rate limits',async()=>{
    const network=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('',{status:429}));
    const id=await create(),runId=await run(id);
    expect(network).toHaveBeenCalledTimes(1);
    expect(await env.DB.prepare('SELECT status,added FROM discovery_runs WHERE id=?').bind(runId).first()).toEqual({status:'falhou',added:0});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM prospect_inbox').first()).toEqual({n:0});
    expect((await call('/api/discovery/campaigns/'+id+'/run','POST')).status).toBe(400);
  });
  it('interrupts a campaign edited while its source request is running',async()=>{
    let release:(response:Response)=>void=()=>{};
    const network=vi.spyOn(globalThis,'fetch').mockImplementation(()=>new Promise<Response>(resolve=>{release=resolve;}));
    const work:Promise<unknown>[]=[],id=await create();
    const response=await call('/api/discovery/campaigns/'+id+'/run','POST',undefined,actor,{waitUntil:p=>{work.push(p);}});expect(response.status).toBe(202);
    await vi.waitFor(()=>expect(network).toHaveBeenCalledTimes(1));
    expect((await call('/api/discovery/campaigns/'+id,'PUT',{...campaign,active:false,revision:1})).status).toBe(200);
    release(new Response(JSON.stringify({elements})));await Promise.all(work);
    expect(await env.DB.prepare('SELECT status FROM discovery_runs WHERE campaign_id=?').bind(id).first()).toEqual({status:'interrompido'});
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM prospect_inbox').first()).toEqual({n:0});
  });
  it('honors disabled notifications and isolates read updates',async()=>{
    vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response(JSON.stringify({elements})));
    expect(await (await call('/api/discovery/notifications','POST',{enabled:false})).json()).toEqual({enabled:false});
    const id=await create();await run(id);
    expect(await (await call('/api/discovery/notifications')).json()).toEqual({items:[],unread:0,enabled:false});
    await env.DB.prepare('UPDATE discovery_runs SET started_at=?').bind(saoPauloTime(Date.now()-120000)).run();
    await call('/api/discovery/notifications','POST',{enabled:true});
    const id2=await create({...campaign,category:'padarias'});await run(id2);
    // The same contacts are duplicates across campaigns, so no new recommendation notification.
    expect(await (await call('/api/discovery/notifications')).json()).toMatchObject({unread:0});
  });
  it('runs at most one due cron slot and schedules the next future wall-clock slot',async()=>{
    const network=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({elements:[]})));
    const id=await create({...campaign,frequency:'scheduled',times:['08:00','13:00','17:00']});
    const overdue=saoPauloTime(Date.now()-3600000);
    await env.DB.prepare('UPDATE discovery_campaigns SET next_run_at=? WHERE id=?').bind(overdue,id).run();
    await scheduledDiscovery(env as unknown as Env);await scheduledDiscovery(env as unknown as Env);
    expect(network).toHaveBeenCalledTimes(1);
    expect(await env.DB.prepare('SELECT scheduled_for,status FROM discovery_runs').first()).toEqual({scheduled_for:overdue,status:'concluido'});
    const row=await env.DB.prepare('SELECT next_run_at FROM discovery_campaigns WHERE id=?').bind(id).first<{next_run_at:string}>();expect(row!.next_run_at>now()).toBe(true);
  });
  it('advances a 51-record source page and resets at exhaustion',async()=>{
    const first=Array.from({length:51},(_,i)=>({type:'node',id:i+1,tags:{name:'Estabelecimento '+(i+1)}}));
    const network=vi.spyOn(globalThis,'fetch').mockImplementationOnce(async()=>new Response(JSON.stringify({elements:first}))).mockImplementationOnce(async()=>new Response(JSON.stringify({elements:first.slice(50)})));
    const id=await create();await run(id);
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM prospect_inbox').first()).toEqual({n:50});
    expect(await env.DB.prepare('SELECT cursor_json FROM discovery_campaigns WHERE id=?').bind(id).first()).toEqual({cursor_json:'{"_source":"overpass","node":50}'});
    await env.DB.prepare('UPDATE discovery_runs SET started_at=?').bind(saoPauloTime(Date.now()-120000)).run();
    await run(id);
    expect(new URLSearchParams(String(network.mock.calls[1][1]?.body)).get('data')).toContain('id()>50');
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM prospect_inbox').first()).toEqual({n:51});
    expect(await env.DB.prepare('SELECT cursor_json FROM discovery_campaigns WHERE id=?').bind(id).first()).toEqual({cursor_json:'{"_source":"overpass"}'});
  });
  it('enforces configured account quotas and the capture switch',async()=>{
    const network=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response(JSON.stringify({elements:[]})));
    const id=await create();await run(id);
    await env.DB.prepare('UPDATE discovery_runs SET started_at=?').bind(saoPauloTime(Date.now()-120000)).run();
    await env.DB.prepare("INSERT INTO admin_parameters(key,value,updated_at) VALUES('capture_runs_account','1',?)").bind(now()).run();
    const quota=await call('/api/discovery/campaigns/'+id+'/run','POST');expect(quota.status).toBe(400);expect(await quota.json()).toMatchObject({erro:'Limite de rodadas por conta nas últimas 24 horas'});
    await env.DB.prepare("INSERT INTO admin_parameters(key,value,updated_at) VALUES('capture_enabled','false',?)").bind(now()).run();
    const disabled=await call('/api/discovery/campaigns/'+id+'/run','POST');expect(disabled.status).toBe(400);expect(await disabled.json()).toMatchObject({erro:'Captação desativada pelo administrador'});
    expect(network).toHaveBeenCalledTimes(1);
  });
  it('escapes query input, advances type cursors, validates source shapes and bounds streamed bytes',async()=>{
    const query=overpassQuery('São Leopoldo','restaurantes',{node:101,way:202});expect(query).toContain('id()>101');expect(query).toContain('id()>202');expect(query).toContain('[aáàâãä]');
    expect(osmRecords([{type:'node',id:'not-a-number',tags:{name:'Bad'}},{type:'node',id:8,tags:{name:'Safe',website:'javascript:alert(1)',email:'invalid'}}],campaign).map(x=>x.row)).toMatchObject([{name:'Safe',email:'',website:''}]);
    const network=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response('x'.repeat(4*1024*1024+1),{headers:{'Content-Length':'1'}}));
    await expect(fetchOsm(query)).rejects.toThrow();expect(network).toHaveBeenCalledTimes(2);
    network.mockReset().mockImplementation(async()=>new Response(JSON.stringify({remark:'timeout',elements:[]})));
    await expect(fetchOsm(query)).rejects.toThrow();expect(network).toHaveBeenCalledTimes(2);
  });
});
