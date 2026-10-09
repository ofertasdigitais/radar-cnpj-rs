/* Shared BI cohorts: completed/suppressed leads never enter operational queues. */
(function(root){'use strict';
  function active(lead){return !['convertido','descartado','concluido'].includes(lead.profile_lead_status)&&!Number(lead.profile_do_not_contact||0);}
  function deadlines(leads,now=new Date()){
    const today=new Date(now);today.setHours(23,59,59,999);
    const week=new Date(today);week.setDate(week.getDate()+7);
    const buckets=[0,0,0,0];
    leads.filter(active).forEach(lead=>{
      const due=lead.profile_next_action_at?new Date(lead.profile_next_action_at):null;
      if(!due||!Number.isFinite(+due))buckets[3]++;
      else if(due<now)buckets[0]++;else if(due<=today)buckets[1]++;else if(due<=week)buckets[2]++;
    });return buckets;
  }
  const api={active,deadlines};if(typeof module==='object'&&module.exports)module.exports=api;else root.RadarBIMetrics=api;
})(typeof window!=='undefined'?window:globalThis);
