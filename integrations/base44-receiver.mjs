/* Portable Web API verification boundary. No SDK, external calls or writes here.
 * A Base44 handler must inject an atomic, owner-scoped persistence adapter.
 */
const encoder=new TextEncoder();
const fields=['contract_version','event_type','external_id','source_updated_at','owner','company','contact','commercial'];
const fail=(message,status=400)=>{throw new Response(JSON.stringify({erro:message}),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});};
export async function verifyRadarRequest(request,{secret,owners,now=Math.floor(Date.now()/1000)}){
 if(request.method!=='POST')fail('Use POST',405);
 if(typeof secret!=='string'||secret.length<32)fail('Receptor não configurado',503);
 const timestamp=request.headers.get('X-Radar-Timestamp')||'',signature=request.headers.get('X-Radar-Signature')||'';
 if(!/^\d{10}$/.test(timestamp)||Math.abs(now-Number(timestamp))>300||!/^sha256=[a-f0-9]{64}$/.test(signature))fail('Assinatura inválida ou expirada',401);
 if(!request.body)fail('Corpo ausente');
 const reader=request.body.getReader(),chunks=[];let size=0;
 try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>262144){await reader.cancel();fail('Corpo muito grande',413);}chunks.push(value);}}finally{reader.releaseLock();}
 const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
 const prefix=encoder.encode(timestamp+'.'),signed=new Uint8Array(prefix.length+bytes.length);signed.set(prefix);signed.set(bytes,prefix.length);
 const key=await crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const digest=Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,signed)),x=>x.toString(16).padStart(2,'0')).join('');
 let difference=0;for(let i=0;i<64;i++)difference|=digest.charCodeAt(i)^signature.charCodeAt(i+7);if(difference)fail('Assinatura inválida',401);
 let event;try{event=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{fail('JSON inválido');}
 if(!event||Array.isArray(event)||Object.keys(event).some(k=>!fields.includes(k))||event.contract_version!==1||event.event_type!=='lead.upsert')fail('Contrato inválido');
 for(const group of ['owner','company','contact','commercial'])if(!event[group]||typeof event[group]!=='object'||Array.isArray(event[group]))fail('Grupo inválido');
 const {radar_account_id:account,radar_profile_id:profile}=event.owner,cnpj=event.company.cnpj;
 if(!/^[\w-]{1,100}$/.test(account||'')||!/^[\w-]{1,100}$/.test(profile||'')||!/^\d{14}$/.test(cnpj||''))fail('Identidade inválida');
 if(event.external_id!==`radar:${account}:${profile}:${cnpj}`||!/^\d{4}-\d\d-\d\dT/.test(event.source_updated_at||'')||!Number.isFinite(Date.parse(event.source_updated_at)))fail('Identificador ou versão inválida');
 const ownerKey=account+':'+profile;
 if(!owners||!Object.hasOwn(owners,ownerKey)||!owners[ownerKey])fail('Responsável sem mapeamento autorizado',403);
 for(const field of ['offered_value_cents','negotiated_value_cents','closed_value_cents'])if(!Number.isSafeInteger(event.commercial[field])||event.commercial[field]<0)fail('Valor monetário inválido');
 if(!['novo','qualificado','contatado','negociacao','convertido','descartado','concluido'].includes(event.commercial.lead_status))fail('Etapa inválida');
 for(const group of ['owner','company','contact','commercial'])for(const value of Object.values(event[group]))if(value!==null&&typeof value!=='string'&&typeof value!=='number')fail('Campo inválido');else if(typeof value==='string'&&value.length>12000)fail('Texto muito longo');
 return{event,crmOwnerId:owners[ownerKey],idempotencyKey:event.external_id+':'+event.source_updated_at};
}

export async function receiveRadarLead(request,configuration){
 try{
  const validated=await verifyRadarRequest(request,configuration);
  if(typeof configuration.persistAtomic!=='function')fail('Persistência do CRM ainda não configurada',503);
  // Must atomically upsert by external_id, enforce owner and reject stale versions.
  const result=await configuration.persistAtomic(validated);
  return new Response(JSON.stringify(result),{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 }catch(error){if(error instanceof Response)return error;return new Response('{"erro":"Falha no receptor"}',{status:500,headers:{'Content-Type':'application/json'}});}
}
