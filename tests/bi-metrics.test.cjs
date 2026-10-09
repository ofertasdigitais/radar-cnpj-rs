const {test}=require('node:test');const assert=require('node:assert/strict');
const {active,deadlines}=require('../static/bi-metrics.js');
test('BI excludes all finished and suppressed leads from active queues',()=>{
 for(const profile_lead_status of ['convertido','descartado','concluido'])assert.equal(active({profile_lead_status}),false);
 assert.equal(active({profile_lead_status:'novo',profile_do_not_contact:1}),false);
 assert.equal(active({profile_lead_status:'contatado',profile_do_not_contact:0}),true);
});
test('deadline buckets are mutually exclusive and exclude completed records',()=>{
 const now=new Date('2026-10-07T12:00:00');
 const lead=(due,status='novo')=>({profile_lead_status:status,profile_next_action_at:due});
 assert.deepEqual(deadlines([lead('2026-10-07T09:00:00'),lead('2026-10-07T18:00:00'),lead('2026-10-09T09:00:00'),lead(null),lead('bad'),lead('2026-10-07T09:00:00','concluido')],now),[1,1,1,2]);
});
