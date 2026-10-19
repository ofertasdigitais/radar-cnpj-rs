import {env} from 'cloudflare:workers';
import {beforeEach,describe,expect,it} from 'vitest';
import {handleReceita,receitaDigest,receitaSyncState,RECEITA_FIELDS} from '../src/receita-current';
import {ApiError,now,type Env,type Row} from '../src/runtime';

const secret='test-radar-receita-secret-0123456789abcdefghijklmnopqrstuv';
const runtime={...env,RECEITA_IMPORT_SECRET:secret,RECEITA_SYNC_AUTOMATION:'0'} as unknown as Env;
async function call(body:Row,token=secret,overrides:Partial<Env>={}):Promise<Response> {
  const request=new Request('https://radar-cnpj-rs.example.workers.dev/api/internal/receita',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)});
  try {const response=await handleReceita(request,{...runtime,...overrides});if(!response)throw Error('unhandled');return response;}
  catch(error){if(error instanceof ApiError)return new Response(JSON.stringify({erro:error.message}),{status:error.status});throw error;}
}
function company(cnpj='12345678000190',extra:Row={}):Row {return {...Object.fromEntries(Object.keys(RECEITA_FIELDS).map(k=>[k,''])),cnpj,razao_social:'RAZÃO OFICIAL ATUALIZADA',nome_fantasia:'Loja pública',situacao:'ATIVA',data_abertura:'2026-10-01',cnae:'6201501',cnae_descricao:'Descrição oficial',segmento:'Tecnologia e comunicação',municipio:'Porto Alegre',regiao:'Metropolitana',uf:'RS',mei:0,...extra};}
async function start(run='1001-1',rows:number|null=1,month='2026-10',mode='full'):Promise<Response>{return call({action:'start',run_id:run,competencia:month,mode,expected_rows:rows});}
async function send(rows:Row[],run='1001-1',sequence=0):Promise<Response>{return call({action:'batch',run_id:run,sequence,rows,sha256:await receitaDigest(rows)});}
const catalog=[{codigo:'6201501',descricao:'Desenvolvimento de programas de computador sob encomenda'}];
async function finish(run='1001-1',batches=1,items=catalog):Promise<Response>{return call({action:'finalize',run_id:run,expected_batches:batches,catalog:items,catalog_sha256:await receitaDigest(items)});}

beforeEach(async()=>{
  for(const table of ['sync_import_batches','sync_import_runs','sync_meta','cnae_catalog','prospect_links','sales_lead_history','sales_profile_leads','account_company_state','contact_suppression','profile_leads','private_companies','companies','sales_profiles','user_accounts'])await env.DB.prepare('DELETE FROM '+table).run();
  await env.DB.prepare("INSERT INTO sync_meta(key,value) VALUES('competencia','2026-09')").run();
});
describe('Radar-only Receita pipeline',()=>{
  it('requires its own long bearer secret and bounds actual body bytes',async()=>{
    expect((await call({action:'status'},'incorrect')).status).toBe(401);
    expect((await call({action:'status'},secret,{RECEITA_IMPORT_SECRET:''})).status).toBe(503);
    expect((await call({action:'status'},secret,{RECEITA_IMPORT_SECRET:'short'})).status).toBe(503);
    const oversized=new Request('https://radar.test/api/internal/receita',{method:'POST',headers:{Authorization:'Bearer '+secret,'Content-Length':'1'},body:'x'.repeat(2*1024*1024+1)});
    await expect(handleReceita(oversized,runtime)).rejects.toMatchObject({status:413});
    expect((await call({action:'status'})).status).toBe(200);
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM sync_import_runs').first()).toEqual({n:0});
  });
  it('acquires a six-hour job lock before loading, validates IDs and never advertises inactive automation',async()=>{
    expect((await start('1001-1',null)).status).toBe(201);
    expect((await start('1002-1',null)).status).toBe(409);
    expect((await start('not-github',null)).status).toBe(400);
    const job=await env.DB.prepare('SELECT * FROM sync_import_runs').first();
    expect(job).toMatchObject({status:'loading',expected_rows:null,active_lock:1});
    expect(Date.parse(String(job!.expires_at))-Date.parse(String(job!.started_at))).toBe(6*3600000);
    expect(await receitaSyncState(runtime)).toMatchObject({status:'running',competencia:'2026-09',automatic_sync:false});
    expect(await (await call({action:'status',run_id:'1001-1',progress:35,phase:'parse'})).json()).toMatchObject({job:{progress:35,phase:'Filtrando estabelecimentos do RS'}});
    expect((await call({action:'status',run_id:'1001-1',progress:35,phase:'secret user input'})).status).toBe(400);
    expect((await start('1001-1',2)).status).toBe(200);
    expect((await start('1001-1',3)).status).toBe(409);
  });
  it('rejects foreign states and commercial fields without changing any row',async()=>{
    await start();
    expect((await send([company(undefined,{uf:'SP'})])).status).toBe(400);
    expect((await send([company(undefined,{situacao:'TESTE'})])).status).toBe(400);
    expect((await send([company(undefined,{favorito:1,observacoes:'payload'} )])).status).toBe(400);
    expect((await call({action:'batch',run_id:'1001-1',sequence:0,rows:[company()],sha256:'0'.repeat(64)})).status).toBe(400);
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM companies').first()).toEqual({n:0});
    expect(await env.DB.prepare('SELECT received_rows FROM sync_import_runs').first()).toEqual({received_rows:0});
  });
  it('updates only public fields while preserving private identities and all commercial work',async()=>{
    const stamp=now();
    await env.DB.batch([
      env.DB.prepare("INSERT INTO companies(cnpj,razao_social,situacao,uf,favorito,lead_status,observacoes,cnae) VALUES('12345678000190','Anterior','ATIVA','RS',1,'negociacao','Notas existentes','6201501')"),
      env.DB.prepare("INSERT INTO companies(cnpj,razao_social,situacao,uf,cnae,cnae_descricao) VALUES('12345678000191','Privada ZZ','TESTE','ZZ','6201501','Descrição privada')"),
      env.DB.prepare("INSERT INTO companies(cnpj,razao_social,situacao,uf,cnae,cnae_descricao) VALUES('12345678000192','Privada marcada','ATIVA','RS','6201501','Descrição privada marcada')"),
      env.DB.prepare("INSERT INTO companies(cnpj,razao_social,situacao,uf,cnae,cnae_descricao) VALUES('12345678000193','Outra UF','ATIVA','SP','6201501','Descrição SP')"),
      env.DB.prepare("INSERT INTO private_companies(cnpj,owner_id) VALUES('12345678000192','owner-a')"),
      env.DB.prepare("INSERT INTO sales_profiles(id,name,owner_id,created_at,updated_at) VALUES('sales-a','Equipe A','owner-a',?,?)").bind(stamp,stamp),
      env.DB.prepare("INSERT INTO sales_profile_leads(profile_id,cnpj,added_at,updated_at,lead_status,observacoes,estrategia) VALUES('sales-a','12345678000190',?,?,'negociacao','Privado do vendedor','Estratégia anterior')").bind(stamp,stamp),
      env.DB.prepare("INSERT INTO account_company_state(account_id,cnpj,favorito,observacoes,updated_at) VALUES('owner-a','12345678000190',1,'Privado da conta',?)").bind(stamp),
      env.DB.prepare("INSERT INTO sales_lead_history(profile_id,cnpj,event_type,title,created_at) VALUES('sales-a','12345678000190','note','Histórico anterior',?)").bind(stamp),
    ]);
    const beforeLead=await env.DB.prepare('SELECT * FROM sales_profile_leads').all();
    const beforeState=await env.DB.prepare('SELECT * FROM account_company_state').all();
    const beforeHistory=await env.DB.prepare('SELECT * FROM sales_lead_history').all();
    await start('1001-1',3);
    const batch=await send([company(),company('12345678000191'),company('12345678000192')]);expect(batch.status).toBe(200);expect(await batch.json()).toMatchObject({received:3,applied:1});
    expect((await finish()).status).toBe(200);
    expect(await env.DB.prepare("SELECT razao_social,favorito,lead_status,observacoes,cnae_descricao FROM companies WHERE cnpj='12345678000190'").first()).toEqual({razao_social:'RAZÃO OFICIAL ATUALIZADA',favorito:1,lead_status:'negociacao',observacoes:'Notas existentes',cnae_descricao:catalog[0].descricao});
    expect((await env.DB.prepare('SELECT * FROM sales_profile_leads').all()).results).toEqual(beforeLead.results);
    expect((await env.DB.prepare('SELECT * FROM account_company_state').all()).results).toEqual(beforeState.results);
    expect((await env.DB.prepare('SELECT * FROM sales_lead_history').all()).results).toEqual(beforeHistory.results);
    expect((await env.DB.prepare("SELECT cnpj,razao_social,cnae_descricao FROM companies WHERE cnpj<>'12345678000190' ORDER BY cnpj").all()).results).toEqual([
      {cnpj:'12345678000191',razao_social:'Privada ZZ',cnae_descricao:'Descrição privada'},
      {cnpj:'12345678000192',razao_social:'Privada marcada',cnae_descricao:'Descrição privada marcada'},
      {cnpj:'12345678000193',razao_social:'Outra UF',cnae_descricao:'Descrição SP'},
    ]);
  });
  it('supports identical batch and finalize replay but rejects conflicting content and missing rows',async()=>{
    await start('1001-1',2);
    const one=[company()];expect((await send(one)).status).toBe(200);
    expect(await (await send(one)).json()).toMatchObject({replay:true,received:1,applied:1});
    expect((await send([company(undefined,{razao_social:'Different'})])).status).toBe(409);
    expect((await finish()).status).toBe(409);
    expect(await env.DB.prepare("SELECT value FROM sync_meta WHERE key='competencia'").first()).toEqual({value:'2026-09'});
    expect((await send([company('12345678000191')],'1001-1',2)).status).toBe(409);
    expect((await send([company('12345678000191')],'1001-1',1)).status).toBe(200);
    expect((await finish('1001-1',2)).status).toBe(200);
    expect(await (await finish('1001-1',2)).json()).toMatchObject({complete:true,replay:true,competencia:'2026-10'});
    expect((await finish('1001-1',2,[{codigo:'6201501',descricao:'Different'}])).status).toBe(409);
    expect(await env.DB.prepare('SELECT received_rows,next_sequence,status,active_lock FROM sync_import_runs').first()).toEqual({received_rows:2,next_sequence:2,status:'complete',active_lock:null});
    expect(await env.DB.prepare("SELECT value FROM sync_meta WHERE key='competencia'").first()).toEqual({value:'2026-10'});
  });
  it('enforces cross-batch ordering and a 500-row cap, and accepts a 1359-row CNAE catalog',async()=>{
    await start('1001-1',500);
    const rows=Array.from({length:500},(_,i)=>company(String(i+1).padStart(14,'0')));
    expect((await send([...rows,company('99999999000190')])).status).toBe(400);
    expect((await send(rows)).status).toBe(200);
    expect((await send([rows[0]],'1001-1',1)).status).toBe(409);
    const cnaes=Array.from({length:1359},(_,i)=>({codigo:String(i+1).padStart(7,'0'),descricao:'Atividade econômica '+i}));
    expect((await finish('1001-1',1,cnaes)).status).toBe(200);
    expect(await env.DB.prepare('SELECT COUNT(*) AS n FROM cnae_catalog').first()).toEqual({n:1359});
  });
  it('expires abandoned locks, releases explicit failures and permits catalog-only refresh of the published month',async()=>{
    await start('1001-1',null);
    await env.DB.prepare("UPDATE sync_import_runs SET expires_at='2000-01-01T00:00:00.000Z' WHERE id='1001-1'").run();
    expect((await start('1002-1',1)).status).toBe(201);
    expect((await send([company()])).status).toBe(409);
    expect((await call({action:'fail',run_id:'1002-1',message:'Never copy arbitrary remote content'})).status).toBe(200);
    expect(await env.DB.prepare("SELECT status,error_code FROM sync_import_runs WHERE id='1002-1'").first()).toEqual({status:'failed',error_code:'pipeline_failed'});
    expect((await start('1003-1',0,'2026-09','catalog')).status).toBe(201);
    expect((await finish('1003-1',0)).status).toBe(200);
    expect(await env.DB.prepare("SELECT value FROM sync_meta WHERE key='competencia'").first()).toEqual({value:'2026-09'});
    expect(await env.DB.prepare("SELECT value FROM sync_meta WHERE key='cnae_catalog_competencia'").first()).toEqual({value:'2026-09'});
  });
  it('does not rewrite identical public records and refuses a stale competency publication',async()=>{
    const row=company(undefined,{cnae_descricao:catalog[0].descricao});
    await start();expect(await (await send([row])).json()).toMatchObject({applied:1});await finish();
    await start('1002-1',1,'2026-11');
    expect(await (await send([row],'1002-1')).json()).toMatchObject({applied:0,received:1});
    await env.DB.prepare("UPDATE sync_meta SET value='2026-12' WHERE key='competencia'").run();
    expect((await finish('1002-1')).status).toBe(409);
    expect(await env.DB.prepare("SELECT value FROM sync_meta WHERE key='competencia'").first()).toEqual({value:'2026-12'});
  });
});
