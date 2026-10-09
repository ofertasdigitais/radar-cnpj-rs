(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;else root.RadarTools=value;})(typeof window==='object'?window:globalThis,function(){
  'use strict';
  const fields={name:'Nome do contato',company:'Empresa',phone:'Telefone',email:'E-mail',city:'Cidade',cnpj:'CNPJ',campaign:'Campanha / ICP',persona:'Cargo / persona',website:'Site',source:'Origem',notes:'Observações'};
  function phone(raw,parse){
    const text=String(raw||'').trim(),digits=text.replace(/\D/g,'');
    if(!text)return{valid:false,formatted:'Não informado',e164:'',suggestion:'',note:'Informe o telefone com DDD.'};
    const candidate=/^55\d{10,11}$/.test(digits)?'+'+digits:text;
    let number;try{number=parse(candidate,{defaultCountry:'BR',extract:false});}catch{}
    const valid=!!number?.isValid()&&number.country==='BR';
    let suggestion='';
    let national=/^55\d{10,11}$/.test(digits)?digits.slice(2):digits;
    if(/^0\d{10,11}$/.test(national))national=national.slice(1);
    if(!valid&&/^\+?[\d\s().-]+$/.test(text)&&(!text.startsWith('+')||/^\+55(?:\D|\d)/.test(text))&&/^\d{2}[6-9]\d{7}$/.test(national)){
      let revised;try{revised=parse(national.slice(0,2)+'9'+national.slice(2),{defaultCountry:'BR',extract:false});}catch{}
      if(revised?.isValid()&&revised.country==='BR'&&revised.getType()==='MOBILE')suggestion=revised.number;
    }
    return{valid,formatted:valid?number.formatNational():text,e164:valid?number.number:'',suggestion,
      type:valid?number.getType():'',note:valid?'Formato brasileiro válido. WhatsApp ainda precisa de confirmação.':suggestion?'Possível celular antigo sem o 9. Confirme antes de usar a sugestão.':'DDD ou número inválido; revise na fonte.'};
  }
  // A valid format is not proof of a WhatsApp account. Never mutate the source phone.
  function whatsapp(raw,parse){
    const result=phone(raw,parse);
    return{...result,e164:result.e164||result.suggestion,adjusted:!result.e164&&!!result.suggestion};
  }
  const normalized=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]/g,'');
  const aliases={name:['nome','nomecontato','contato','name'],company:['empresa','razaosocial','nomefantasia','company'],phone:['telefone','celular','whatsapp','phone','telefoneoriginal'],email:['email'],city:['cidade','municipio','city'],cnpj:['cnpj'],campaign:['campanha','campanhaicp','campaign'],persona:['cargo','persona','cargopersona'],website:['site','website'],source:['origem','fonte','source'],notes:['observacoes','notas','notes']};
  function autoMap(headers){return Object.fromEntries(Object.keys(fields).map(key=>[key,headers.find(header=>aliases[key].includes(normalized(header)))||'']));}
  function mapped(rows,map,source){return rows.map(row=>{const result={};for(const key of Object.keys(fields))result[key]=String(row[map[key]]??'').trim();result.source=result.source||source||'Importação CSV';result.cnpj=result.cnpj.replace(/[^A-Za-z0-9]/g,'').toUpperCase();return result;});}
  function validate(row){const errors=[];if(!row.name&&!row.company)errors.push('Nome/empresa ausente');if(row.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(row.email))errors.push('E-mail inválido');if(row.cnpj&&!/^[A-Z0-9]{14}$/.test(row.cnpj))errors.push('CNPJ inválido');if(row.website){try{const url=new URL(row.website);if(!['https:','http:'].includes(url.protocol)||url.username||url.password)errors.push('Site inválido');}catch{errors.push('Site inválido');}}return errors;}
  function researchLinks(company,city){const q=[company,city].filter(Boolean).join(' ');return[
    {label:'Google Maps',url:'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(q)},
    {label:'Site e presença digital',url:'https://www.google.com/search?q='+encodeURIComponent(q+' site oficial')},
    {label:'LinkedIn da empresa',url:'https://www.google.com/search?q='+encodeURIComponent('site:linkedin.com/company/ '+q)}
  ];}
  return{fields,phone,whatsapp,autoMap,mapped,validate,researchLinks};
});
