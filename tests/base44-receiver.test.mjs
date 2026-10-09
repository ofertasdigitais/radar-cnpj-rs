import {test} from 'node:test';import assert from 'node:assert/strict';import {createHmac} from 'node:crypto';
import {verifyRadarRequest,receiveRadarLead} from '../integrations/base44-receiver.mjs';
const secret='local-test-only-'.repeat(3),now=1791370800;
const event={contract_version:1,event_type:'lead.upsert',external_id:'radar:account:profile:11222333000181',source_updated_at:'2026-10-07T10:00:00',owner:{radar_account_id:'account',radar_profile_id:'profile'},company:{cnpj:'11222333000181'},contact:{telefone:'51999999999'},commercial:{lead_status:'novo',offered_value_cents:0,negotiated_value_cents:12345,closed_value_cents:0}};
function request(value=event,stamp=now){const body=JSON.stringify(value);return new Request('https://test.base44.app/receive',{method:'POST',body,headers:{'X-Radar-Timestamp':String(stamp),'X-Radar-Signature':'sha256='+createHmac('sha256',secret).update(stamp+'.'+body).digest('hex')}});}
const configuration={secret,now,owners:{'account:profile':'crm-owner'}};
test('signed contract preserves centavos, stable ID and owner mapping',async()=>{
 const value=await verifyRadarRequest(request(),configuration);assert.equal(value.event.commercial.negotiated_value_cents,12345);assert.equal(value.crmOwnerId,'crm-owner');
 assert.equal((await receiveRadarLead(request(),configuration)).status,503); // never pretends it was saved
});
test('tampering, expired signatures, unknown owner and invalid money are rejected',async()=>{
 for(const [req,config,status] of [[request(event,now-301),configuration,401],[request(),{...configuration,secret:'wrong'.repeat(10)},401],[request(),{...configuration,owners:{}},403],[request({...event,commercial:{...event.commercial,closed_value_cents:-1}}),configuration,400]]){
  try{await verifyRadarRequest(req,config);assert.fail('accepted');}catch(error){assert.equal(error.status,status);}
 }
});
