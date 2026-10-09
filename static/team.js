(function(){
  const teamEscape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Mesma correção aplicada em app.js: sem nome fantasia, o título já mostra a
  // razão social, então repeti-la de novo ao lado do CNPJ só duplica o texto.
  const teamLegalNameIfDistinct = x => x.nome_fantasia && x.nome_fantasia !== x.razao_social ? teamEscape(x.razao_social) : '';
  // Quarta rodada (Empresas): para MEI sem nome fantasia, a razão social já vem
  // prefixada com a raiz do CNPJ ("69.097.364 MARIA ..."); o CNPJ completo já
  // aparece logo abaixo, então o prefixo numérico só atrapalha a leitura do nome.
  const teamDisplayName = x => {
    const base = x.nome_fantasia || x.razao_social || '';
    if (!x.nome_fantasia && x.razao_social && x.cnpj) {
      const root = String(x.cnpj).replace(/\D/g, '').slice(0, 8);
      const stripped = base.replace(/^[\d.\-\/\s]+/, '');
      const removedDigits = base.slice(0, base.length - stripped.length).replace(/\D/g, '');
      if (root && removedDigits === root && stripped.trim()) return stripped.trim();
    }
    return base;
  };
  function closeTeamLayers(){
    $('overlay').classList.remove('open'); $('detailDrawer').classList.remove('open');
    $('importModal').classList.remove('open'); $('profileModal').classList.remove('open'); $('exportCrmModal')?.classList.remove('open');
     $('teamProfileModal').classList.remove('open'); $('messageTemplateModal')?.classList.remove('open'); $('testLeadModal')?.classList.remove('open'); document.body.classList.remove('modal-open');
  }
  function openTeamLayer(name){
    closeTeamLayers(); $('overlay').classList.add('open');
    if(name==='detail') $('detailDrawer').classList.add('open');
    if(name==='import') $('importModal').classList.add('open');
    if(name==='profile') $('profileModal').classList.add('open');
    if(name==='team-profile') $('teamProfileModal').classList.add('open');
    if(name==='message-template') $('messageTemplateModal').classList.add('open');
    if(name==='test-lead') $('testLeadModal').classList.add('open');
    if(name==='export-crm') $('exportCrmModal').classList.add('open');
    document.body.classList.add('modal-open');
  }
  openLayer = openTeamLayer; closeLayers = closeTeamLayers;

  const fallbackMessageTemplate={id:'local-fallback',name:'Apresentação inicial',body:'Olá! Tudo bem? Meu nome é {vendedor}. Encontrei a {empresa} e gostaria de conversar sobre uma oportunidade. Posso te explicar rapidamente?',is_default:1};
  const contactOutcomeNames={'':'Não informado',nao_respondeu:'Não respondeu',respondeu:'Respondeu',retornar:'Pediu retorno',sem_interesse:'Sem interesse',numero_invalido:'Número inválido',oportunidade:'Oportunidade aberta'};
  let messageTemplates=[],activeMessageTemplateId='',portfolioStageFilter='',portfolioWhatsappFilter='',portfolioLayout='cards',portfolioFocus='all',portfolioSort='priority',portfolioSearch='',portfolioSearchTimer=null,canManageTeam=false;
  let portfolioColumns=0;
  try{const saved=Number(localStorage.getItem('radar-lead-columns'));if(Number.isInteger(saved)&&saved>=0&&saved<=10)portfolioColumns=saved;}catch(_){}
  function portfolioPageSize(){return 60;}
  let activityPage=1,activityTotal=0,activityRequest=0,portfolioRequest=0;
  function fitLeadColumns(){
    const box=$('portfolioLeads'),select=$('portfolioColumns');if(!box||!select)return;
    const width=box.parentElement.clientWidth;
    if(!width)return;
    const maximum=Math.max(1,Math.min(window.RadarRuntime?.max_columns||10,Math.floor((width+8)/288)));
    portfolioColumns=Math.min(portfolioColumns,maximum);
    select.innerHTML='<option value="0">Automático · '+maximum+' '+(maximum===1?'coluna':'colunas')+'</option>'+Array.from({length:maximum},(_,i)=>`<option value="${i+1}">${i+1} ${i===0?'coluna':'colunas'}</option>`).join('');
    select.value=String(portfolioColumns);
    box.style.setProperty('--lead-columns',String(portfolioColumns||maximum));
    box.classList.toggle('custom-columns',portfolioLayout==='cards');
    select.disabled=portfolioLayout==='list';
    $('portfolioColumnsHint').hidden=true;
  }
  window.addEventListener('radar:runtime',fitLeadColumns);
  async function loadTeamActivity(){
    const request=++activityRequest,box=$('portfolioActivityItems');
    if(!$('portfolioActivity').open||!activeTeamProfileId)return;
    box.textContent='Carregando atividades…';
    const query=new URLSearchParams({profile_id:activeTeamProfileId,activity_from:$('portfolioActivityFrom').value,activity_to:$('portfolioActivityTo').value,page:String(activityPage)});
    try{const data=await api('/api/team-activity?'+query);if(request!==activityRequest)return;activityTotal=data.total;
      box.innerHTML=data.items.length?data.items.map(item=>`<article class="lead-activity-row"><time>${teamEscape(fmtDateTime(item.created_at))}</time><div><strong>${teamEscape(teamDisplayName(item))}</strong><span>${teamEscape(fmtCnpj(item.cnpj))}</span></div><div><strong>${teamEscape(item.title)}</strong><p>${teamEscape(item.details||'')}</p>${window.RadarCommercialChanges?.(item.changes_json)||''}</div></article>`).join(''):'Nenhuma atividade registrada neste período.';
      $('portfolioActivityPage').textContent=`${activityTotal} atividades · página ${activityPage} / ${Math.max(1,Math.ceil(activityTotal/50))}`;
      $('portfolioActivityPrev').disabled=activityPage<=1;$('portfolioActivityNext').disabled=activityPage*50>=activityTotal;
    }catch(error){if(request===activityRequest)box.textContent=error.message;}
  }
  const whatsappStatusNames={pending:'Pendente',confirmed:'Confirmado',not_found:'Não localizado',invalid:'Inválido'};
  const portfolioFocusNames={all:'Todos',overdue:'Atrasados',today:'Para hoje',no_action:'Sem próxima ação',uncontacted:'Não contatados',negotiation:'Negociação',favorites:'Favoritos'};
  const moneyBRL=cents=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0}).format(Number(cents||0)/100);
  const moneyInput=cents=>Number(cents||0)?(Number(cents)/100).toFixed(2).replace('.',','):'';
  function whatsappContact(lead){
    if(lead?.profile_do_not_contact||window.RadarDoNotContact?.has(lead?.cnpj))return{e164:'',adjusted:false};
    if(!window.RadarTools?.whatsapp||!window.RadarLibraries)return{e164:'',adjusted:false};
    const parse=window.RadarLibraries.parsePhoneNumberFromString;
    for(const value of [lead?.profile_whatsapp_phone,lead?.telefone]){
      const result=window.RadarTools.whatsapp(value,parse);
      if(result.e164)return result;
    }
    return{e164:'',adjusted:false};
  }
  function whatsappLeadPhone(lead){
    return whatsappContact(lead).e164.replace('+','');
  }
  function activeMessageTemplate(){return messageTemplates.find(x=>x.id===activeMessageTemplateId)||messageTemplates.find(x=>x.is_default)||messageTemplates[0]||fallbackMessageTemplate;}
  function messageForLead(template,lead){
    const seller=teamProfiles[activeTeamProfileId];
    const values={
      empresa:teamDisplayName(lead)||lead.razao_social||'',
      razao_social:lead.razao_social||'',nome_fantasia:lead.nome_fantasia||'',
      cnpj:fmtCnpj(lead.cnpj),cidade:ptTitle(lead.municipio||''),
      cnae:cnaeText(lead)||lead.cnae||'',segmento:lead.segmento||'',
      vendedor:seller?.name||'nossa equipe'
    };
    return String(template.body||'').replace(/\{(empresa|razao_social|nome_fantasia|cnpj|cidade|cnae|segmento|vendedor)\}/g,(_,key)=>values[key]||'');
  }
  function openWhatsApp(lead){
    if(lead?.profile_do_not_contact||window.RadarDoNotContact?.has(lead?.cnpj)){toast('Não contatar: empresa bloqueada nesta conta.');return;}
    const contact=whatsappContact(lead),phone=contact.e164.replace('+','');
    if(!phone){toast('Este lead não possui um telefone válido para WhatsApp');return;}
    const template=activeMessageTemplate(),text=messageForLead(template,lead);
    if(activeTeamProfileId&&lead.cnpj) void api('/api/team-lead-events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:activeTeamProfileId,cnpj:lead.cnpj,event_type:'whatsapp_opened',details:`Modelo: ${template.name}`})}).catch(()=>{});
    window.open(`https://wa.me/${phone}?text=${encodeURIComponent(text)}`,'_blank','noopener,noreferrer');
    toast(contact.adjusted?'9 completado automaticamente. Confira o destinatário no WhatsApp.':`WhatsApp aberto com o modelo “${template.name}”`);
  }
  function renderMessageTemplateSelector(){
    const select=$('whatsappTemplateSelect');if(!select)return;
    const list=messageTemplates.length?messageTemplates:[fallbackMessageTemplate];
    if(!list.some(x=>x.id===activeMessageTemplateId))activeMessageTemplateId=(list.find(x=>x.is_default)||list[0]).id;
    select.innerHTML=list.map(item=>`<option value="${teamEscape(item.id)}" ${item.id===activeMessageTemplateId?'selected':''}>${teamEscape(item.name)}${item.is_default?' · padrão':''}</option>`).join('');
  }
  async function loadMessageTemplates(preferredId=''){
    try{
      const data=await api('/api/message-templates');messageTemplates=data.items||[];
      activeMessageTemplateId=preferredId||activeMessageTemplateId||(messageTemplates.find(x=>x.is_default)||messageTemplates[0]||{}).id||'';
    }catch(error){console.error(error);messageTemplates=[fallbackMessageTemplate];activeMessageTemplateId=fallbackMessageTemplate.id;}
    renderMessageTemplateSelector();renderMessageTemplateList();
  }
  function clearMessageTemplateForm(){
    $('messageTemplateId').value='';$('messageTemplateName').value='';$('messageTemplateBody').value='';$('messageTemplateDefault').checked=messageTemplates.length===0;$('messageTemplateName').focus();
  }
  function renderMessageTemplateList(){
    const box=$('messageTemplateList');if(!box)return;
    box.innerHTML=messageTemplates.length?messageTemplates.map(item=>`<article class="message-template-item ${item.id===activeMessageTemplateId?'active':''}"><button class="message-template-edit" data-message-edit="${teamEscape(item.id)}"><span><strong>${teamEscape(item.name)}</strong><small>${item.is_default?'Modelo padrão':'Modelo alternativo'}</small></span><em>Editar</em></button><button class="message-template-delete" data-message-delete="${teamEscape(item.id)}" aria-label="Excluir ${teamEscape(item.name)}">×</button></article>`).join(''):'<div class="message-template-empty">Nenhum modelo cadastrado.</div>';
    box.querySelectorAll('[data-message-edit]').forEach(button=>button.onclick=()=>editMessageTemplate(button.dataset.messageEdit));
    box.querySelectorAll('[data-message-delete]').forEach(button=>button.onclick=()=>deleteMessageTemplate(button.dataset.messageDelete));
  }
  function editMessageTemplate(id){
    const item=messageTemplates.find(x=>x.id===id);if(!item)return;
    $('messageTemplateId').value=item.id;$('messageTemplateName').value=item.name;$('messageTemplateBody').value=item.body;$('messageTemplateDefault').checked=Boolean(item.is_default);
  }
  function openMessageTemplateManager(){renderMessageTemplateList();clearMessageTemplateForm();openTeamLayer('message-template');}
  async function saveMessageTemplate(){
    const id=$('messageTemplateId').value,name=$('messageTemplateName').value.trim(),body=$('messageTemplateBody').value.trim(),is_default=$('messageTemplateDefault').checked;
    if(!name){toast('Informe o nome do modelo');$('messageTemplateName').focus();return;}
    if(!body){toast('Escreva a mensagem automática');$('messageTemplateBody').focus();return;}
    try{
      const saved=await api(id?`/api/message-templates/${encodeURIComponent(id)}`:'/api/message-templates',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,body,is_default})});
      await loadMessageTemplates(saved.id);clearMessageTemplateForm();toast(`Modelo “${saved.name}” salvo`);
    }catch(error){toast(error.message);}
  }
  async function deleteMessageTemplate(id){
    const item=messageTemplates.find(x=>x.id===id);if(!item||!confirm(`Excluir o modelo “${item.name}”?`))return;
    try{await api(`/api/message-templates/${encodeURIComponent(id)}`,{method:'DELETE'});activeMessageTemplateId='';await loadMessageTemplates();clearMessageTemplateForm();toast('Modelo excluído');}catch(error){toast(error.message);}
  }
  function insertMessageVariable(value){
    const input=$('messageTemplateBody'),start=input.selectionStart??input.value.length,end=input.selectionEnd??start;
    input.value=input.value.slice(0,start)+value+input.value.slice(end);input.focus();input.setSelectionRange(start+value.length,start+value.length);
  }
  function normalizeLeadPanelCopy(root){
    if(!root)return;
    const replacements=[
      ['indicadores da carteira','indicadores do painel'],['Selecione uma carteira','Selecione um responsável'],
      ['Carteira não vinculada','Responsável não vinculado'],['Adicionar à carteira','Incluir no painel'],
      ['Verificando carteiras','Verificando responsáveis'],['Verificando carteira','Verificando responsável'],
      ['nesta carteira','no painel deste responsável'],['à carteira','ao painel'],['na carteira','no painel']
    ];
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
    while((node=walker.nextNode())){let value=node.nodeValue;for(const [from,to] of replacements)value=value.replaceAll(from,to);if(value!==node.nodeValue)node.nodeValue=value;}
    root.querySelectorAll('[aria-label]').forEach(element=>{let value=element.getAttribute('aria-label');for(const [from,to] of replacements)value=value.replaceAll(from,to);element.setAttribute('aria-label',value)});
  }

  async function loadTeamProfiles(){
    try{
      const data = await api('/api/team-profiles');
      canManageTeam=Boolean(data.can_manage_team);
      teamProfiles = Object.fromEntries((data.items||[]).map(item=>[item.id,item]));
      if(!teamProfiles[activeTeamProfileId]) activeTeamProfileId = Object.keys(teamProfiles)[0] || '';
      // Perfis comerciais nascem junto com a conta de acesso; não crie áreas órfãs pela interface.
      $('portfolioCreate').hidden=true;$('newTeamProfile').hidden=true;
      renderTeamProfiles(); renderTeamPortfolioProfiles();
      if(activeTeamProfileId) loadTeamPortfolio(); else renderTeamPortfolioLeads();
    }catch(error){ console.error(error); toast('Não foi possível carregar os perfis individuais'); }
  }
  function renderTeamProfiles(){
    const box=$('teamProfileGrid'); if(!box)return;
    const list=Object.values(teamProfiles);
    box.innerHTML=list.length ? list.map(profile=>`<article class="team-profile-card ${activeTeamProfileId===profile.id?'active':''}">
      <div class="team-profile-card-head"><span class="team-profile-avatar">${teamEscape(profile.initials||'R')}</span><span><strong>${teamEscape(profile.name)}</strong><small>${teamEscape(profile.role||'Vendedor')}</small></span><span class="team-profile-star">★ ${Number(profile.favorite_count||0).toLocaleString('pt-BR')}</span></div>
      <div class="team-profile-stats"><span><b>${Number(profile.lead_count||0).toLocaleString('pt-BR')}</b> leads em acompanhamento</span><span>${profile.last_activity?`Atividade ${fmtDateTime(profile.last_activity)}`:'Ainda sem atividade'}</span></div>
      <div class="team-profile-card-actions"><button data-team-open="${teamEscape(profile.id)}">Abrir Painel de Leads →</button></div></article>`).join('') : '<div class="team-profile-empty"><strong>Nenhum responsável vinculado</strong><p>Esta conta ainda não possui um perfil comercial.</p></div>';
    box.querySelectorAll('[data-team-open]').forEach(button=>button.onclick=()=>openTeamPortfolio(button.dataset.teamOpen));
  }
  function renderTeamPortfolioProfiles(){
    const box=$('portfolioProfiles'); if(!box)return; const list=Object.values(teamProfiles);
    $('portfolioProfileCount').textContent=list.length;
    box.innerHTML=list.length ? list.map(profile=>`<button class="portfolio-profile ${activeTeamProfileId===profile.id?'active':''}" data-team-portfolio="${teamEscape(profile.id)}"><span class="portfolio-profile-mark">${teamEscape(profile.initials||'R')}</span><span class="portfolio-profile-copy"><strong>${teamEscape(profile.name)}</strong><small>${Number(profile.lead_count||0).toLocaleString('pt-BR')} ${Number(profile.lead_count||0)===1?'lead':'leads'}</small></span><b class="portfolio-profile-count">${Number(profile.favorite_count||0).toLocaleString('pt-BR')} ★</b></button>`).join('') : '<div class="portfolio-empty-small"><strong>Nenhum responsável vinculado</strong><p>Crie uma conta para separar o trabalho de cada vendedor.</p></div>';
    box.querySelectorAll('[data-team-portfolio]').forEach(button=>button.onclick=()=>openTeamPortfolio(button.dataset.teamPortfolio));
  }
  function setPortfolioFocus(value,reload=true){
    if(!portfolioFocusNames[value])value='all';
    portfolioFocus=value;teamPortfolioView=value==='favorites'?'favorites':'all';portfolioPage=1;
    document.querySelectorAll('[data-crm-focus]').forEach(button=>button.classList.toggle('active',button.dataset.crmFocus===value));
    if(reload)loadTeamPortfolio();
  }
  function openTeamPortfolio(id,focus='all'){ activeTeamProfileId=id; portfolioPage=1; portfolioFocus='all'; teamPortfolioView='all'; portfolioStageFilter=''; portfolioSearch=''; $('portfolioStageFilter').value='';$('portfolioSearch').value='';setPortfolioFocus(focus,false);renderTeamProfiles();renderTeamPortfolioProfiles();loadTeamPortfolio();navigateToSection('leads'); }
  window.addEventListener('radar:open-leads',async event=>{const {profileId,focus}=event.detail;if(!teamProfiles[profileId])await loadTeamProfiles();if(teamProfiles[profileId])openTeamPortfolio(profileId,focus);else toast('Responsável indisponível para esta conta.');});
  async function loadTeamPortfolio(){
    const request=++portfolioRequest;
    const profile=teamProfiles[activeTeamProfileId]; if(!profile){portfolioItems=[];portfolioTotal=0;renderTeamPortfolioLeads();return;}
    const query=new URLSearchParams({profile_id:activeTeamProfileId,view:portfolioFocus==='favorites'?'favorites':'all',focus:portfolioFocus==='favorites'?'all':portfolioFocus,status:portfolioStageFilter,whatsapp:portfolioWhatsappFilter,sort:portfolioSort,q:portfolioSearch,page:String(portfolioPage),size:String(portfolioPageSize())});
    query.set('activity_from',$('portfolioActivityFrom').value);query.set('activity_to',$('portfolioActivityTo').value);
    loadTeamActivity();
    try{const [data,dashboard]=await Promise.all([api(`/api/team-leads?${query}`),api(`/api/team-dashboard?profile_id=${encodeURIComponent(activeTeamProfileId)}`)]);if(request!==portfolioRequest)return;portfolioItems=data.items||[];portfolioTotal=Number(data.total||0);renderTeamDashboard(dashboard);renderTeamPortfolioLeads();window.dispatchEvent(new Event("radar-commercial:updated"));}catch(error){if(request!==portfolioRequest)return;console.error(error);toast('Não foi possível carregar o Painel de Leads');}
  }
  function renderTeamDashboard(data){
    const s=data?.summary||{},kpis=$('portfolioKpis');if(!kpis)return;
    kpis.innerHTML=`<article><span>LEADS ATIVOS</span><strong>${Number(s.active||0).toLocaleString('pt-BR')}</strong><small>${Number(s.total||0).toLocaleString('pt-BR')} no histórico</small></article><article><span>CONTATADOS</span><strong>${Number(s.contact_rate||0).toLocaleString('pt-BR')}%</strong><small>média: ${s.avg_first_contact_days??'—'} dias</small></article><article class="${Number(s.overdue||0)?'danger':''}"><span>ATRASADOS</span><strong>${Number(s.overdue||0)}</strong><small>${Number(s.due_today||0)} para hoje</small></article><article><span>EM NEGOCIAÇÃO</span><strong>${moneyBRL(s.negotiated_value_cents)}</strong><small>${Number(s.negotiation_count||0)} leads · ${moneyBRL(s.offered_value_cents)} ofertados</small></article><article class="positive"><span>FECHADO</span><strong>${moneyBRL(s.closed_value_cents)}</strong><small>média: ${s.avg_close_days??'—'} dias</small></article>`;
    const focusCounts={all:s.total,overdue:s.overdue,today:s.due_today,no_action:s.without_next_action,uncontacted:s.uncontacted,negotiation:s.negotiation_count,favorites:teamProfiles[activeTeamProfileId]?.favorite_count};
    document.querySelectorAll('[data-crm-focus]').forEach(button=>{const key=button.dataset.crmFocus,count=focusCounts[key];button.innerHTML=`<span>${teamEscape(portfolioFocusNames[key]||key)}</span>${count===undefined?'':`<b>${Number(count||0).toLocaleString('pt-BR')}</b>`}`;button.classList.toggle('active',portfolioFocus===key)});
    const stages=Object.fromEntries((data.stages||[]).map(x=>[x.key,x]));
    $('portfolioStageSummary').innerHTML=Object.entries(stageNames).map(([key,label])=>`<button data-stage-summary="${key}" class="${portfolioStageFilter===key?'active':''}"><span>${teamEscape(label)}</span><strong>${Number(stages[key]?.total||0)}</strong><i style="--share:${Math.round(Number(stages[key]?.total||0)*100/Math.max(1,Number(s.total||0)))}%"></i></button>`).join('');
    const outcomes=Object.fromEntries((data.outcomes||[]).map(x=>[x.key,x]));
    $('portfolioOutcomeSummary').innerHTML=Object.entries({...contactOutcomeNames,nao_informado:'Não informado'}).filter(([key])=>key!==''||!outcomes.nao_informado).map(([key,label])=>{const lookup=key||'nao_informado';return `<span><b>${teamEscape(label)}</b><strong>${Number(outcomes[lookup]?.total||0)}</strong></span>`}).join('');
    const whatsappCounts={confirmed:s.whatsapp_confirmed,not_found:s.whatsapp_not_found,pending:s.whatsapp_pending,invalid:s.whatsapp_invalid};
    document.querySelectorAll('[data-whatsapp-filter]').forEach(button=>{const key=button.dataset.whatsappFilter;button.querySelector('b').textContent=Number(whatsappCounts[key]||0).toLocaleString('pt-BR');button.classList.toggle('active',portfolioWhatsappFilter===key)});
    $('portfolioStageSummary').querySelectorAll('[data-stage-summary]').forEach(button=>button.onclick=()=>{portfolioStageFilter=portfolioStageFilter===button.dataset.stageSummary?'':button.dataset.stageSummary;$('portfolioStageFilter').value=portfolioStageFilter;portfolioPage=1;loadTeamPortfolio()});
  }
  function renderTeamPortfolioLeads(){
    const box=$('portfolioLeads'); if(!box)return; const profile=teamProfiles[activeTeamProfileId],empty=$('portfolioEmpty'),pager=$('portfolioPager');
    if(!profile){$('portfolioTitle').textContent='Selecione um responsável';$('portfolioMeta').textContent='Esta conta ainda não possui uma área comercial.';box.innerHTML='';empty.hidden=false;if(pager)pager.hidden=true;return;}
    $('portfolioTitle').textContent=profile.name; $('portfolioMeta').textContent=`${Number(portfolioTotal).toLocaleString('pt-BR')} ${portfolioTotal===1?'lead':'leads'} · ${profile.role||'Vendedor'}${portfolioFocus!=='all'?' · '+(portfolioFocusNames[portfolioFocus]||portfolioFocus):''}${portfolioStageFilter?' · '+(stageNames[portfolioStageFilter]||portfolioStageFilter):''}${portfolioSearch?' · busca: “'+portfolioSearch+'”':''}`; empty.hidden=portfolioItems.length>0;
    box.classList.toggle('list-mode',portfolioLayout==='list');
    fitLeadColumns();
    box.innerHTML=portfolioItems.map((x,i)=>{const due=x.profile_next_action_at?new Date(x.profile_next_action_at):null,overdue=due&&due<new Date()&&!['convertido','descartado','concluido'].includes(x.profile_lead_status);return `<article class="portfolio-lead ${x.profile_favorito?'is-favorite':''} ${overdue?'is-overdue':''}"><div class="portfolio-lead-top"><span>${x.mei?'MEI':'PJ'} · ${teamEscape(ptTitle(x.municipio))}</span><button class="portfolio-star ${x.profile_favorito?'active':''}" data-team-favorite="${teamEscape(x.cnpj)}" title="${x.profile_favorito?'Remover favorito':'Favoritar lead'}">★</button><b>${x.lead_score}</b></div><div class="portfolio-lead-identity"><h4>${teamEscape(teamDisplayName(x))}</h4><span class="portfolio-lead-meta">${teamEscape(fmtCnpj(x.cnpj))}</span><strong class="portfolio-lead-activity">${teamEscape(cnaeText(x))}</strong></div><div class="portfolio-lead-commercial"><div class="portfolio-lead-tags"><span class="portfolio-lead-stage stage-${teamEscape(x.profile_lead_status)}">${teamEscape(stageNames[x.profile_lead_status]||'Novo')}</span><span class="portfolio-lead-outcome">${teamEscape(contactOutcomeNames[x.profile_contact_outcome]||'Sem contato registrado')}</span><span class="whatsapp-status status-${teamEscape(x.profile_whatsapp_status||'pending')}">WA · ${teamEscape(whatsappStatusNames[x.profile_whatsapp_status||'pending'])}</span></div><div class="portfolio-values"><span><small>Negociado</small><b>${moneyBRL(x.profile_negotiated_value_cents)}</b></span><span><small>Fechado</small><b>${moneyBRL(x.profile_closed_value_cents)}</b></span></div></div><p class="portfolio-next-action ${overdue?'overdue':''}"><b>${x.profile_lead_status==='concluido'?'Atendimento concluído':overdue?'Ação atrasada':'Próxima ação'}</b><span>${teamEscape(x.profile_next_action||'Nenhuma ação agendada')}</span>${x.profile_next_action_at?`<time>${teamEscape(fmtDateTime(x.profile_next_action_at))}</time>`:''}</p><div class="portfolio-lead-actions"><button data-team-open-lead="${i}">Tratar lead →</button><button class="whatsapp" data-team-whatsapp="${i}" ${whatsappLeadPhone(x)?'':'disabled'}>Contatar Whatsapp</button><select class="whatsapp-result" data-whatsapp-status="${teamEscape(x.cnpj)}" aria-label="Resultado do WhatsApp"><option value="pending" ${(x.profile_whatsapp_status||'pending')==='pending'?'selected':''}>Pendente</option><option value="confirmed" ${x.profile_whatsapp_status==='confirmed'?'selected':''}>Confirmado</option><option value="not_found" ${x.profile_whatsapp_status==='not_found'?'selected':''}>Não localizado</option><option value="invalid" ${x.profile_whatsapp_status==='invalid'?'selected':''}>Inválido</option></select><button data-team-complete="${teamEscape(x.cnpj)}" ${['convertido','descartado','concluido'].includes(x.profile_lead_status)?'disabled':''}>Concluir / dar baixa ✓</button><button class="remove" data-team-remove-lead="${teamEscape(x.cnpj)}">Remover</button></div></article>`}).join('');
    const size=portfolioPageSize(),pages=Math.max(1,Math.ceil(portfolioTotal/size)); $('portfolioRange').textContent=portfolioTotal?`Exibindo ${(portfolioPage-1)*size+1}–${Math.min(portfolioPage*size,portfolioTotal)} de ${portfolioTotal}`:'Nenhum lead selecionado'; $('portfolioPageInfo').textContent=`Página ${portfolioPage} / ${pages}`; $('portfolioPrev').disabled=portfolioPage===1; $('portfolioNext').disabled=portfolioPage>=pages; if(pager)pager.hidden=portfolioTotal===0;
    box.querySelectorAll('[data-team-complete]').forEach(button=>button.onclick=()=>window.dispatchEvent(new CustomEvent('radar:lead-complete',{detail:{cnpj:button.dataset.teamComplete}})));
    box.querySelectorAll('[data-team-open-lead]').forEach(button=>button.onclick=()=>openDetail(portfolioItems[+button.dataset.teamOpenLead])); box.querySelectorAll('[data-team-whatsapp]').forEach(button=>button.onclick=()=>openWhatsApp(portfolioItems[+button.dataset.teamWhatsapp])); box.querySelectorAll('[data-team-remove-lead]').forEach(button=>button.onclick=()=>removeTeamLead(button.dataset.teamRemoveLead)); box.querySelectorAll('[data-team-favorite]').forEach(button=>button.onclick=()=>toggleTeamFavorite(button.dataset.teamFavorite,button.classList.contains('active'))); box.querySelectorAll('[data-whatsapp-status]').forEach(select=>select.onchange=()=>saveWhatsappStatus(select.dataset.whatsappStatus,select.value));
  }
  async function removeTeamLead(cnpj){if(!activeTeamProfileId)return;try{await api(`/api/team-leads?profile_id=${encodeURIComponent(activeTeamProfileId)}&cnpj=${encodeURIComponent(cnpj)}`,{method:'DELETE'});await loadTeamProfiles();toast('Lead removido do painel');}catch(error){toast(error.message);}}
  async function addTeamLead(cnpj,profileId,asFavorite=false,allowDuplicate=false){profileId=profileId||$('detailTeamProfile')?.value||activeTeamProfileId;if(!profileId){toast('Selecione ou crie um perfil individual primeiro');return;}try{const result=await api('/api/team-leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profileId,cnpj,allow_duplicate:allowDuplicate})});activeTeamProfileId=profileId;if(asFavorite)await api('/api/team-leads',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profileId,cnpj,favorito:true})});await loadTeamProfiles();await loadTeamMemberships(cnpj);toast(result.adicionado?'Lead incluído no painel':'Este lead já está no painel');}catch(error){if(!allowDuplicate&&error.message.includes("outro atendimento ativo")&&confirm(error.message+" Deseja continuar mesmo assim?"))return addTeamLead(cnpj,profileId,asFavorite,true);toast(error.message);}}
  function openTestLeadModal(){if(!activeTeamProfileId){toast('Crie ou selecione um perfil individual primeiro');return;}$('testLeadName').value='Teste WhatsApp';$('testLeadPhone').value='';openTeamLayer('test-lead');setTimeout(()=>$('testLeadPhone').focus(),80);}
  async function saveTestLead(){const name=$('testLeadName').value.trim(),phone=$('testLeadPhone').value.trim();if(!name){toast('Informe o nome do lead de teste');return;}if(!phone){toast('Informe seu número de WhatsApp');return;}try{const result=await api('/api/team-leads/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:activeTeamProfileId,name,phone})});closeTeamLayers();portfolioPage=1;await loadTeamProfiles();toast('Lead de teste adicionado. Clique em WhatsApp para abrir sua conversa.');}catch(error){toast(error.message);}}
  async function toggleTeamFavorite(cnpj,current){try{await api('/api/team-leads',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:activeTeamProfileId,cnpj,favorito:!current})});await loadTeamProfiles();toast(current?'Lead removido dos favoritos':'Lead favoritado');}catch(error){toast(error.message);}}
  async function saveWhatsappStatus(cnpj,status){const lead=portfolioItems.find(item=>item.cnpj===cnpj),phone=whatsappLeadPhone(lead);try{await api('/api/team-leads',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:activeTeamProfileId,cnpj,whatsapp_status:status,whatsapp_phone:phone})});await loadTeamPortfolio();toast(`WhatsApp marcado como “${whatsappStatusNames[status]}”`);}catch(error){toast(error.message);}}
  async function loadTeamHistory(cnpj){const box=$('teamLeadHistory');if(!box||!activeTeamProfileId)return;try{const data=await api(`/api/team-lead-history?profile_id=${encodeURIComponent(activeTeamProfileId)}&cnpj=${encodeURIComponent(cnpj)}`),items=data.items||[];box.innerHTML=items.length?items.map(item=>`<article><span></span><div><strong>${teamEscape(item.title)}</strong>${window.RadarCommercialChanges?.(item.changes_json)||''}${item.details?`<p>${teamEscape(item.details)}</p>`:''}<time>${teamEscape(fmtDateTime(item.created_at))}</time></div></article>`).join(''):'<p class="team-history-empty">Nenhuma atividade registrada.</p>';}catch(error){box.innerHTML='<p class="team-history-empty">Inclua o lead no painel para iniciar o histórico.</p>';}}
  function ensureLeadSalesFields(){
    const grid=document.querySelector('#detailContent .team-editor-grid'),editor=document.querySelector('#detailContent .team-lead-editor');
    if(!grid||!editor||$('teamContactOutcome'))return;
    grid.insertAdjacentHTML('beforeend','<div class="team-editor-section-title"><strong>Segmentação comercial e perdas</strong><small>Dados declarados pelo vendedor, não inferidos da Receita</small></div><label>Campanha / ICP<input id="teamCampaign" maxlength="120" disabled placeholder="Ex.: Restaurantes de Porto Alegre"></label><label>Cargo / persona<input id="teamPersona" maxlength="120" disabled placeholder="Ex.: Proprietário"></label><label>Origem do lead<input id="teamOrigin" maxlength="120" disabled placeholder="Ex.: Prospecção Radar / indicação"></label><label>Motivo de perda<select id="teamLossReason" disabled><option value="">Não informado</option><option value="preco">Preço</option><option value="sem_interesse">Sem interesse</option><option value="sem_orcamento">Sem orçamento</option><option value="concorrente">Concorrente</option><option value="sem_resposta">Sem resposta</option><option value="fora_icp">Fora do ICP</option><option value="outro">Outro</option></select></label>');
    const stage=grid.querySelector('label');
    stage.insertAdjacentHTML('afterend',`<label>Resultado do contato<select id="teamContactOutcome" disabled>${Object.entries(contactOutcomeNames).map(([v,n])=>`<option value="${v}">${n}</option>`).join('')}</select></label><label class="team-field-wide">Próxima ação<input id="teamNextAction" maxlength="240" disabled placeholder="Ex.: enviar proposta ou retornar ligação"></label><label>Prazo da próxima ação<input id="teamNextActionAt" type="datetime-local" disabled></label><div class="team-editor-section-title"><strong>Valores da oportunidade</strong><small>Use para compor o painel comercial</small></div><label>Valor ofertado<input id="teamOfferedValue" inputmode="decimal" disabled placeholder="R$ 0,00"></label><label>Valor em negociação<input id="teamNegotiatedValue" inputmode="decimal" disabled placeholder="R$ 0,00"></label><label>Valor fechado<input id="teamClosedValue" inputmode="decimal" disabled placeholder="R$ 0,00"></label><label>Data do fechamento<input id="teamClosedAt" type="datetime-local" disabled></label><div class="team-editor-section-title"><strong>Contexto comercial</strong><small>Informações privadas desta conta</small></div>`);
    editor.insertAdjacentHTML('beforeend','<div class="team-history"><div class="team-history-head"><strong>Histórico do lead</strong><small>Últimas 100 atividades</small></div><div id="teamLeadHistory"><p class="team-history-empty">Carregando histórico…</p></div></div>');
  }
  async function loadTeamMemberships(cnpj){const box=$('detailTeamMemberships');if(!box)return;try{const data=await api(`/api/team-memberships?cnpj=${encodeURIComponent(cnpj)}`),items=data.items||[];box.innerHTML=items.filter(x=>x.selected).map(x=>`<span>${teamEscape(x.name)}${x.favorito?' ★':''}</span>`).join('')||'<small>Este lead ainda não está nesta carteira.</small>';const selected=items.find(x=>x.id===activeTeamProfileId&&x.selected),controls=['teamLeadStage','teamContactOutcome','teamNextAction','teamNextActionAt','teamOfferedValue','teamNegotiatedValue','teamClosedValue','teamClosedAt','teamNotes','teamStrategy','teamLeadSave','teamCampaign','teamPersona','teamOrigin','teamLossReason'];if(selected){$('teamLeadSave').dataset.revision=selected.updated_at;$('teamCampaign').value=selected.campaign||'';$('teamPersona').value=selected.persona||'';$('teamOrigin').value=selected.lead_origin||'';$('teamLossReason').value=selected.loss_reason||'';$('detailTeamProfile').value=selected.id;$('teamLeadStage').value=selected.lead_status||'novo';$('teamContactOutcome').value=selected.contact_outcome||'';$('teamNextAction').value=selected.next_action||'';$('teamNextActionAt').value=selected.next_action_at||'';$('teamOfferedValue').value=moneyInput(selected.offered_value_cents);$('teamNegotiatedValue').value=moneyInput(selected.negotiated_value_cents);$('teamClosedValue').value=moneyInput(selected.closed_value_cents);$('teamClosedAt').value=selected.closed_at||'';$('teamFavoriteBtn').classList.toggle('active',Boolean(selected.favorito));$('teamNotes').value=selected.observacoes||'';$('teamStrategy').value=selected.estrategia||'';controls.forEach(id=>$(id).disabled=false);loadTeamHistory(cnpj);}else{controls.forEach(id=>$(id).disabled=true);$('teamLeadHistory').innerHTML='<p class="team-history-empty">Adicione o lead à carteira para iniciar o histórico.</p>';}}catch(error){console.warn(error);}}
  function openTeamDetail(x){const list=Object.values(teamProfiles);if(!activeTeamProfileId&&list[0])activeTeamProfileId=list[0].id;$('detailContent').innerHTML=`<div class="detail-hero"><span class="company-avatar">${companyTag(x)}</span>${x.mei?'':`<span class="badge">${teamEscape(x.porte||'Empresa')}</span>`}<h2>${teamEscape(teamDisplayName(x))}</h2>${teamLegalNameIfDistinct(x)?'<p>'+teamLegalNameIfDistinct(x)+'</p>':''}<span class="status">${teamEscape(x.situacao)}</span></div><div class="detail-leadbox"><div class="score"><div><strong>Potencial comercial</strong><p class="score-explain">Índice de acionabilidade baseado em recência, situação ativa e completude dos dados públicos; não representa intenção de compra.</p></div><span class="score-ring" style="--score:${x.lead_score}"><b>${x.lead_score}</b></span></div></div><section class="detail-section"><h3>CADASTRO E ATIVIDADE</h3><div class="detail-grid"><div class="detail-item"><span>CNPJ</span><strong>${fmtCnpj(x.cnpj)}</strong></div><div class="detail-item"><span>Início da atividade</span><strong>${fmtDate(x.data_abertura)}</strong></div><div class="detail-item detail-wide"><span>CNAE principal · ${teamEscape(x.cnae||'—')}</span><strong>${teamEscape(cnaeText(x))}</strong></div><div class="detail-item"><span>Segmento econômico</span><strong>${teamEscape(x.segmento||'—')}</strong></div><div class="detail-item"><span>Tipo e porte</span><strong>${x.mei?'Microempreendedor individual':teamEscape(x.porte||'Pessoa jurídica')}</strong></div></div></section><section class="detail-section"><h3>LOCALIZAÇÃO</h3><div class="detail-item"><span>Endereço</span><strong>${teamEscape([x.logradouro,x.numero,x.bairro].filter(Boolean).join(', ')||'—')}</strong></div><div class="detail-grid"><div class="detail-item"><span>Município</span><strong>${teamEscape(ptTitle(x.municipio))} / RS</strong></div><div class="detail-item"><span>CEP</span><strong>${teamEscape(x.cep||'—')}</strong></div></div></section><section class="detail-section"><h3>CONTATO PÚBLICO</h3><div class="detail-grid contact-grid"><div class="detail-item"><span>Telefone</span><strong>${teamEscape(fmtPhone(x.telefone))}</strong></div><div class="detail-item contact-email"><span>Correio eletrônico</span><strong>${teamEscape(x.email||'—')}</strong></div></div><button class="detail-whatsapp" id="detailWhatsApp" ${whatsappLeadPhone(x)?'':'disabled'}>Abrir WhatsApp com mensagem automática</button></section><section class="detail-section source-audit"><h3>ORIGEM E VALIDAÇÃO</h3><div class="detail-grid"><div class="detail-item"><span>Fonte mais recente</span><strong>${teamEscape(x.data_source||'Receita Federal')}</strong></div><div class="detail-item"><span>Validação Serpro</span><strong>${x.serpro_checked_at?fmtDateTime(x.serpro_checked_at):'Ainda não validado'}</strong></div></div></section><section class="detail-section detail-workspace"><div class="workspace-heading"><div><p class="eyebrow">TRATAMENTO COMERCIAL</p><h3>Oportunidade e negociação</h3></div><span class="workspace-badge">Privado por conta</span></div><p class="detail-wallet-copy">Organize a etapa, o retorno, os prazos e os valores desta oportunidade. Cada alteração alimenta o histórico e os indicadores da carteira.</p><div class="detail-wallet-controls"><select id="detailTeamProfile" aria-label="Perfil individual"><option value="">${list.length?'Selecione uma carteira':'Carteira não vinculada'}</option>${list.map(p=>`<option value="${teamEscape(p.id)}" ${p.id===activeTeamProfileId?'selected':''}>${teamEscape(p.name)} · ${teamEscape(p.role||'Vendedor')}</option>`).join('')}</select><button id="addToTeamPortfolio" ${list.length?'':'disabled'}>Adicionar à carteira</button></div>${list.length?'':'<button class="secondary detail-create-profile" id="detailCreateTeamProfile">Criar perfil individual →</button>'}<div class="detail-memberships" id="detailTeamMemberships"><small>Verificando carteira…</small></div><div class="team-lead-editor"><div class="team-editor-head"><strong>Painel de tratamento do lead</strong><button class="favorite-btn" id="teamFavoriteBtn" title="Favoritar lead">★</button></div><div class="team-editor-grid"><label>Etapa<select id="teamLeadStage" disabled>${Object.entries(stageNames).map(([v,n])=>`<option value="${v}">${n}</option>`).join('')}</select></label><label>Estratégia<textarea id="teamStrategy" maxlength="4000" disabled placeholder="Como abordar este lead, oferta, canal e próxima ação…"></textarea></label><label>Observações<textarea id="teamNotes" maxlength="4000" disabled placeholder="Registre contexto, histórico e retornos…"></textarea></label></div><button class="primary save-note" id="teamLeadSave" disabled>Salvar oportunidade</button></div></section>`;$('detailWhatsApp')?.addEventListener('click',()=>openWhatsApp(x));$('detailTeamProfile')?.addEventListener('change',e=>{activeTeamProfileId=e.target.value;loadTeamMemberships(x.cnpj)});$('addToTeamPortfolio')?.addEventListener('click',()=>addTeamLead(x.cnpj));$('detailCreateTeamProfile')?.addEventListener('click',openTeamProfileModal);$('teamFavoriteBtn')?.addEventListener('click',()=>{if($('teamLeadSave').disabled)addTeamLead(x.cnpj,null,true);else saveTeamLead(x.cnpj)});$('teamLeadSave')?.addEventListener('click',()=>saveTeamLead(x.cnpj,true));openTeamLayer('detail');loadTeamMemberships(x.cnpj);}
  async function saveTeamLead(cnpj,closeAfter){const favoriteButton=$('teamFavoriteBtn'),currentFavorite=favoriteButton.classList.contains('active'),favorite=closeAfter?currentFavorite:!currentFavorite;if(!closeAfter)favoriteButton.classList.toggle('active',favorite);try{await api('/api/team-leads',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:activeTeamProfileId,cnpj,expected_updated_at:$('teamLeadSave').dataset.revision,lead_status:$('teamLeadStage').value,favorito:favorite,contact_outcome:$('teamContactOutcome').value,next_action:$('teamNextAction').value,next_action_at:$('teamNextActionAt').value,offered_value_cents:$('teamOfferedValue').value,negotiated_value_cents:$('teamNegotiatedValue').value,closed_value_cents:$('teamClosedValue').value,closed_at:$('teamClosedAt').value,observacoes:$('teamNotes').value,estrategia:$('teamStrategy').value,campaign:$('teamCampaign').value,persona:$('teamPersona').value,lead_origin:$('teamOrigin').value,loss_reason:$('teamLossReason').value})});await loadTeamProfiles();if(closeAfter)closeTeamLayers();else loadTeamMemberships(cnpj);toast(closeAfter?'Oportunidade atualizada':favorite?'Lead favoritado':'Lead removido dos favoritos');}catch(error){if(!closeAfter)favoriteButton.classList.toggle('active',currentFavorite);toast(error.message);}}
  openDetail = openTeamDetail;
  function openTeamProfileModal(){ $('teamProfileName').value='';$('teamProfileRole').value='';$('teamProfileEmail').value='';openTeamLayer('team-profile');setTimeout(()=>$('teamProfileName').focus(),80); }
  async function saveTeamProfile(){const name=$('teamProfileName').value.trim();if(!name){toast('Informe o nome do usuário');$('teamProfileName').focus();return;}try{const created=await api('/api/team-profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,role:$('teamProfileRole').value.trim(),email:$('teamProfileEmail').value.trim()})});activeTeamProfileId=created.id;closeTeamLayers();await loadTeamProfiles();navigateToSection('leads');toast(`Perfil “${created.name}” criado`);}catch(error){toast(error.message);}}
  async function deleteTeamProfile(id){if(!confirm('Excluir este perfil e todos os leads vinculados a ele?'))return;try{await api('/api/team-profiles/'+encodeURIComponent(id),{method:'DELETE'});if(activeTeamProfileId===id)activeTeamProfileId='';await loadTeamProfiles();toast('Perfil individual excluído');}catch(error){toast(error.message);}}
  $('newTeamProfile').onclick=openTeamProfileModal;
  $('teamProfileSave').onclick=saveTeamProfile;
  $('teamProfileClose').onclick=closeTeamLayers;
  $('portfolioCreate').onclick=openTeamProfileModal;
  $('portfolioAddTestLead').onclick=openTestLeadModal;
  $('testLeadClose').onclick=closeTeamLayers;
  $('testLeadSave').onclick=saveTestLead;
  $('portfolioRefresh').onclick=()=>{loadTeamProfiles();toast('Painel atualizado')};
  document.querySelectorAll('[data-crm-focus]').forEach(button=>button.onclick=()=>setPortfolioFocus(button.dataset.crmFocus));
  $('portfolioStageFilter').onchange=e=>{portfolioStageFilter=e.target.value;portfolioPage=1;loadTeamPortfolio()};
  $('portfolioSort').onchange=e=>{portfolioSort=e.target.value;portfolioPage=1;loadTeamPortfolio()};
  $('portfolioColumns').innerHTML='<option value="0">Automático</option>'+Array.from({length:10},(_,i)=>`<option value="${i+1}">${i+1} ${i===0?'coluna':'colunas'}</option>`).join('');
  $('portfolioColumns').value=String(portfolioColumns);
  $('portfolioColumns').onchange=e=>{portfolioColumns=Number(e.target.value);try{localStorage.setItem('radar-lead-columns',String(portfolioColumns));}catch(_){}portfolioPage=1;renderTeamPortfolioLeads();loadTeamPortfolio()};
  new ResizeObserver(fitLeadColumns).observe($('portfolioLeads').parentElement);
  $('portfolioActivityApply').onclick=()=>{if($('portfolioActivityFrom').value&&$('portfolioActivityTo').value&&$('portfolioActivityFrom').value>$('portfolioActivityTo').value){toast('A data inicial deve ser anterior à final');return;}portfolioPage=1;activityPage=1;loadTeamPortfolio()};
  $('portfolioActivityClear').onclick=()=>{$('portfolioActivityFrom').value='';$('portfolioActivityTo').value='';portfolioPage=1;activityPage=1;loadTeamPortfolio()};
  $('portfolioActivity').ontoggle=()=>{if($('portfolioActivity').open)loadTeamActivity()};
  $('portfolioActivityPrev').onclick=()=>{activityPage=Math.max(1,activityPage-1);loadTeamActivity()};
  $('portfolioActivityNext').onclick=()=>{if(activityPage*50<activityTotal){activityPage++;loadTeamActivity()}};
  $('portfolioSearch').oninput=e=>{clearTimeout(portfolioSearchTimer);portfolioSearchTimer=setTimeout(()=>{portfolioSearch=e.target.value.trim();portfolioPage=1;loadTeamPortfolio()},260)};
  $('portfolioSearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(portfolioSearchTimer);portfolioSearch=e.target.value.trim();portfolioPage=1;loadTeamPortfolio()}};
  $('portfolioCardsMode').onclick=()=>{portfolioLayout='cards';$('portfolioCardsMode').classList.add('active');$('portfolioListMode').classList.remove('active');renderTeamPortfolioLeads()};
  $('portfolioListMode').onclick=()=>{portfolioLayout='list';$('portfolioListMode').classList.add('active');$('portfolioCardsMode').classList.remove('active');renderTeamPortfolioLeads()};
  document.querySelectorAll('[data-whatsapp-filter]').forEach(button=>button.onclick=()=>{portfolioWhatsappFilter=button.dataset.whatsappFilter;portfolioPage=1;loadTeamPortfolio()});
  $('whatsappShowAll').onclick=()=>{portfolioWhatsappFilter='';portfolioPage=1;loadTeamPortfolio()};
  const exportFields=[['empresa','Empresa'],['razao_social','Razão social'],['cnpj','CNPJ'],['telefone','Telefone original'],['whatsapp_phone','Telefone WhatsApp'],['whatsapp_status','Situação WhatsApp'],['email','E-mail'],['municipio','Município'],['regiao','Região'],['segmento','Segmento'],['cnae','CNAE'],['cnae_descricao','Descrição do CNAE'],['data_abertura','Data de abertura'],['situacao','Situação cadastral'],['potencial','Potencial'],['favorito','Favorito'],['etapa','Etapa'],['resultado','Resultado do contato'],['proxima_acao','Próxima ação'],['data_proxima_acao','Data da próxima ação'],['valor_ofertado','Valor ofertado'],['valor_negociado','Valor negociado'],['valor_fechado','Valor fechado'],['observacoes','Observações'],['estrategia','Estratégia'],['campanha','Campanha / ICP'],['persona','Cargo / persona'],['origem','Origem do lead'],['motivo_perda','Motivo de perda']];
  const exportDefaults=new Set(['empresa','cnpj','telefone','whatsapp_phone','whatsapp_status','email','municipio','segmento','etapa','resultado','proxima_acao','data_proxima_acao','valor_negociado','valor_fechado']);
  function renderExportFields(selectAll=false){$('exportFieldList').innerHTML=exportFields.map(([value,label])=>`<label><input type="checkbox" value="${value}" ${(selectAll||exportDefaults.has(value))?'checked':''}><span>${teamEscape(label)}</span></label>`).join('');$('exportFieldList').querySelectorAll('input').forEach(input=>input.onchange=updateExportFieldCount);updateExportFieldCount();}
  function updateExportFieldCount(){$('exportFieldCount').textContent=`${$('exportFieldList').querySelectorAll('input:checked').length} colunas selecionadas`;}
  function openExportCrm(){if(!activeTeamProfileId){toast('Selecione um responsável primeiro');return;}$('exportStage').value=portfolioStageFilter;$('exportWhatsapp').value=portfolioWhatsappFilter;renderExportFields();openTeamLayer('export-crm');}
  function downloadExportCrm(){const fields=[...$('exportFieldList').querySelectorAll('input:checked')].map(input=>input.value);if(!fields.length){toast('Selecione pelo menos uma coluna');return;}const query=new URLSearchParams({profile_id:activeTeamProfileId,view:portfolioFocus==='favorites'?'favorites':'all',status:$('exportStage').value,whatsapp:$('exportWhatsapp').value,delimiter:$('exportDelimiter').value,filename:$('exportFilename').value.trim(),fields:fields.join(',')});window.location.href=`/api/team-leads.csv?${query}`;closeTeamLayers();toast('Arquivo CSV preparado para o CRM');}
  $('portfolioExport').onclick=openExportCrm;
  $('exportCrmClose').onclick=closeTeamLayers;
  $('exportCrmDownload').onclick=downloadExportCrm;
  $('exportFieldsAll').onclick=()=>renderExportFields(true);
  $('portfolioPrev').onclick=()=>{if(portfolioPage>1){portfolioPage--;loadTeamPortfolio()}};
  $('portfolioNext').onclick=()=>{if(portfolioPage<Math.ceil(portfolioTotal/portfolioPageSize())){portfolioPage++;loadTeamPortfolio()}};
  $('whatsappTemplateSelect').onchange=e=>{activeMessageTemplateId=e.target.value;renderMessageTemplateList();toast(`Modelo “${activeMessageTemplate().name}” selecionado`);};
  $('whatsappTemplatesManage').onclick=openMessageTemplateManager;
  $('messageTemplateClose').onclick=closeTeamLayers;
  $('messageTemplateNew').onclick=clearMessageTemplateForm;
  $('messageTemplateSave').onclick=saveMessageTemplate;
  document.querySelectorAll('[data-message-variable]').forEach(button=>button.onclick=()=>insertMessageVariable(button.dataset.messageVariable));
  new MutationObserver(()=>{ensureLeadSalesFields();normalizeLeadPanelCopy($('detailContent'))}).observe($('detailContent'),{childList:true,subtree:true});
  window.addEventListener('radar:team-updated',loadTeamProfiles);
  loadTeamProfiles();
  loadMessageTemplates();
})();
