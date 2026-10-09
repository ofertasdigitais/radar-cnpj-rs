import React,{useState,useEffect,useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {Recommendations,NotificationCenter,ScheduleFields} from './discovery-assist';

const empty={name:'',city:'',category:'restaurantes',frequency:'manual',times:['08:00','13:00','17:00'],icp_label:'',active:true,require_phone:false,require_website:false,enrich_websites:false};
const statusLabels={executando:'Coletando',concluido:'Concluído',parcial:'Parcial',falhou:'Indisponível',interrompido:'Interrompido'};
const date=value=>value?new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'}):'—';
async function api(path,method='GET',body){
 const response=await fetch('/api/discovery'+path,{method,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000)});
 if(response.status===401){location.href='/login';throw Error('Sessão expirada');}
 let data;try{data=await response.json();}catch{throw Error('Captação indisponível. Verifique se o servidor local está atualizado.');}
 if(!response.ok)throw Error(data.erro||'Não foi possível concluir.');return data;
}

function CampaignEditor({initial,categories,cities,onClose,onSave,busy,feedback}){
 const [form,setForm]=useState(initial||empty);const ref=useRef();
 useEffect(()=>{ref.current.showModal();},[]);
 const field=(name,value)=>setForm(current=>({...current,[name]:value,...(name==='frequency'&&value==='scheduled'&&!current.times?.length?{times:['08:00','13:00','17:00']}:{})}));
 return <dialog ref={ref} className="discovery-dialog" onCancel={onClose} aria-labelledby="campaignEditorTitle"><form onSubmit={event=>{event.preventDefault();onSave(form);}}>
 <header><div><p className="eyebrow">SUA ESTRATÉGIA DE CAPTAÇÃO</p><h2 id="campaignEditorTitle">{initial?'Editar campanha':'Nova campanha'}</h2></div><button type="button" onClick={onClose} aria-label="Fechar campanha">×</button></header>
 <p>Encontre estabelecimentos no RS e receba recomendações privadas, sem alterar seus leads ativos.</p>
 {feedback&&<p className="discovery-editor-error" role="alert">{feedback}</p>}
 <div className="discovery-form-grid">
 <label>Nome da campanha<input autoFocus required minLength={2} maxLength={100} value={form.name} onChange={e=>field('name',e.target.value)} placeholder="Ex.: Restaurantes de Porto Alegre"/></label>
 <label>Município do RS<input required minLength={2} maxLength={100} list="localOsmCities" value={form.city} onChange={e=>field('city',e.target.value)} placeholder="Ex.: Porto Alegre"/><datalist id="localOsmCities">{cities?.map(city=><option key={city.ibge} value={city.name}/>)}</datalist></label>
 <label>Categoria de estabelecimento<select value={form.category} onChange={e=>field('category',e.target.value)}>{categories.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
 <label>Frequência<select aria-label="Frequência" value={form.frequency} onChange={e=>field('frequency',e.target.value)}><option value="manual">Somente quando eu solicitar</option><option value="scheduled">Automática · até 3 horários por dia</option><option value="daily">Automática · a cada 24 horas</option></select></label>
 <ScheduleFields form={form} field={field}/>
 </div>
 <div className="discovery-checks">{[['require_phone','Somente registros com telefone no mapa'],['require_website','Somente registros com site no mapa'],['enrich_websites','Permito consultar os sites comerciais públicos para completar contatos']].map(([name,label])=><label key={name}><input type="checkbox" checked={!!form[name]} onChange={e=>field(name,e.target.checked)}/><span>{label}</span></label>)}</div>
 <div className="discovery-note">Até 50 estabelecimentos por rodada e até 10 sites, respeitando robots.txt. Até 6 rodadas por conta/24h, compartilhadas entre campanhas e buscas manuais, e 30 globais. Não confirma WhatsApp. O servidor precisa estar ligado.</div>
 <footer><button type="button" onClick={onClose}>Cancelar</button><button className="discovery-primary" disabled={busy} type="submit">{busy?'Salvando…':'Salvar campanha'}</button></footer>
 </form></dialog>;
}

function Discovery(){
 const [data,setData]=useState(null),[sources,setSources]=useState([]),[error,setError]=useState(''),[notice,setNotice]=useState(''),[editor,setEditor]=useState(null),[busy,setBusy]=useState('');
 const alive=useRef(true),running=useRef(false),generation=useRef(0),scrollToRecommendations=useRef(false);
 async function refresh(force=false){
  if(running.current&&force!==true)return;const request=++generation.current;running.current=true;
  try{const [value,results]=await Promise.all([api(''),api('/sources')]);if(alive.current&&request===generation.current){setData(value);setSources(results.items);setError('');}}
  catch(e){if(alive.current&&request===generation.current)setError(e.message);}finally{if(request===generation.current)running.current=false;}
 }
 useEffect(()=>{
  alive.current=true;const visible=()=>document.body.dataset.view==='ferramentas'&&!document.querySelector('[data-tool-panel="auto"]')?.hidden;
  if(visible())refresh();const listener=()=>{if(visible())refresh();};
  const recommendations=()=>{scrollToRecommendations.current=true;refresh();};
  window.addEventListener('radar:navigate',listener);window.addEventListener('radar:discovery-open',listener);window.addEventListener('radar:recommendations-open',recommendations);window.addEventListener('radar:recommendations-updated',listener);
  const timer=setInterval(()=>{if(visible()&&!document.hidden)refresh();},8000);
  return()=>{alive.current=false;clearInterval(timer);window.removeEventListener('radar:navigate',listener);window.removeEventListener('radar:discovery-open',listener);window.removeEventListener('radar:recommendations-open',recommendations);window.removeEventListener('radar:recommendations-updated',listener);};
 },[]);
 useEffect(()=>{if(data&&scrollToRecommendations.current){document.getElementById('discoveryRecommendations')?.scrollIntoView({block:'start'});scrollToRecommendations.current=false;}},[data]);
 async function action(key,fn,message){setBusy(key);setError('');try{await fn();setNotice(message);await refresh(true);window.dispatchEvent(new Event('radar:prospects-updated'));}catch(e){setError(e.message);}finally{setBusy('');}}
 const captureReady=data?.osm_mode!=='local'||data?.local_osm?.ready;
 const latest=id=>data?.runs.find(r=>r.campaign_id===id);
 const openContacts=()=>document.querySelector('[data-tool="inbox"]')?.click();
 return <div className="discovery-app">
 <section className="discovery-hero"><div><p className="eyebrow">CAPTAÇÃO AUTÔNOMA · OPENSTREETMAP + CRAWLEE</p><h3>Seu próximo mercado.<br/><em>Sem importar planilhas.</em></h3><p>Escolha cidade, categoria e até três horários. O Radar encontra contatos; você decide quais merecem uma abordagem.</p><div className="discovery-hero-actions"><button className="discovery-primary" onClick={()=>setEditor({value:null})} disabled={!data}>Criar campanha <span aria-hidden="true">＋</span></button><button onClick={openContacts}>Ver meus contatos →</button></div></div><aside className="discovery-flow" aria-label="Como funciona"><article><b>01</b><div><strong>Encontrar</strong><span>Cidade e categoria no mapa</span></div></article><article><b>02</b><div><strong>Completar</strong><span>Site e contatos comerciais públicos</span></div></article><article><b>03</b><div><strong>Recomendar</strong><span>Analise antes de incluir no funil</span></div></article></aside></section>
 {error&&<div className="discovery-feedback error" role="alert">{error}<button onClick={refresh}>Tentar novamente</button></div>}{notice&&<p className="discovery-feedback" role="status">{notice}</p>}
 {!data&&!error&&<p role="status">Carregando a central de captação…</p>}
 {data&&<>
 <div className="discovery-metrics"><article><span>ESTABELECIMENTOS DESCOBERTOS</span><strong>{data.total}</strong><small>Sem duplicar registros na sua conta</small></article><article><span>CAMPANHAS ATIVAS</span><strong>{data.campaigns.filter(c=>c.active).length}</strong><small>{data.campaigns.filter(c=>c.active&&c.frequency!=='manual').length} com coleta automática</small></article><article><span>RECOMENDAÇÕES PARA ANALISAR</span><strong>{data.pending_recommendations}</strong><small>Separadas dos seus leads ativos</small></article></div>
 <Recommendations request={api} refreshKey={data.pending_recommendations}/>
 <section className="discovery-section"><header><div><p className="eyebrow">ESTRATÉGIAS DE CAPTAÇÃO</p><h3>Campanhas da sua conta</h3></div><button onClick={refresh}>Atualizar ↻</button></header>
 <p className="discovery-muted">Horário do servidor: {date(data.server_time)}. Até {data.limits.runs_per_day} rodadas por conta/24h; campanhas compartilham o limite com consultas manuais.</p>
 {!data.scheduler_enabled&&<p className="discovery-feedback">Agendamento pausado pelo administrador. As campanhas não executarão automaticamente.</p>}
 {!data.enabled&&<p className="discovery-feedback">Captação desativada pelo administrador.</p>}
 {!data.campaigns.length?<div className="discovery-empty"><h4>Escolha onde quer vender.</h4><p>Crie sua primeira campanha por cidade e segmento. A cobertura do mapa pode ser incompleta.</p></div>:<div className="discovery-campaign-grid">{data.campaigns.map(c=>{const run=latest(c.id);return <article className="discovery-campaign" key={c.id}>
 <div className="discovery-campaign-top"><span className={'discovery-pill '+(c.active?'active':'')}>{c.active?'Ativa':'Pausada'}</span><small>{c.frequency==='scheduled'?`${c.times.length} HORÁRIOS / DIA`:c.frequency==='daily'?'AUTOMÁTICA · 24H':'SOB DEMANDA'}</small></div><h4>{c.name}</h4><p>{c.city} · {data.categories.find(x=>x.id===c.category)?.label}</p>{c.icp_label&&<p>Perfil de referência: {c.icp_label}</p>}
 {c.frequency==='scheduled'&&<div className="discovery-slot-list" aria-label="Horários de coleta">{c.times.map(t=><span key={t}>{t}</span>)}</div>}
 <dl><div><dt>Última rodada</dt><dd>{run?statusLabels[run.status]:'Ainda não executada'}</dd></div><div><dt>Novos contatos</dt><dd>{run?.added??'—'}</dd></div><div><dt>Próxima coleta</dt><dd>{!c.active?'Campanha pausada':c.frequency!=='manual'?date(c.next_run_at):'Quando você solicitar'}</dd></div></dl>
 <div className="discovery-campaign-actions"><button className="discovery-primary" disabled={!!busy||!data.enabled||!captureReady||!c.active||data.runs.some(r=>r.status==='executando')} onClick={()=>action(c.id,()=>api('/campaigns/'+c.id+'/run','POST'),'Coleta iniciada. Novos contatos aparecerão nas recomendações.')}>{busy===c.id?'Aguarde…':'Coletar agora'}</button><button disabled={!!busy} onClick={()=>setEditor({value:c})}>Editar</button><button disabled={!!busy} onClick={()=>action(c.id,()=>api('/campaigns/'+c.id,'PUT',{...c,active:!c.active}),'Campanha atualizada.')}>{c.active?'Pausar':'Ativar'}</button></div>
 </article>;})}</div>}
 </section>
 <section className="discovery-section" aria-label="Fonte e atualização OSM"><header><div><p className="eyebrow">FONTE GRATUITA · SEM ASSINATURA</p><h3>{data.osm_mode==='local'?'Base OpenStreetMap local':'Overpass público'}</h3></div><span className="discovery-pill">{data.osm_mode==='local'?(data.local_osm?.ready?'Índice pronto':'Aguardando preparação'):'Sujeito a indisponibilidade'}</span></header><p>{data.osm_mode==='local'?data.local_osm?.message:'Consultas públicas limitadas; indisponibilidade não significa ausência de empresas.'}</p>{data.local_osm?.ready&&<p>{data.local_osm.count.toLocaleString('pt-BR')} registros por categoria · {data.local_osm.cities.length} municípios RS · Preparado em {date(data.local_osm.built_at)}</p>}<p>Municípios definidos pelos limites geográficos OSM. Não inventa telefones, CNPJ ou redes sociais nem confirma WhatsApp. Atualização semanal pode ser habilitada no /admin.</p>{!data.local_osm?.ready&&data.osm_mode==='local'&&<p>Preparação inicial: execute <code>python tools/update-local-osm.py</code> na pasta principal do Radar.</p>}</section>
 {!data.collector_ready&&<p className="discovery-feedback">Instale o coletor Node para habilitar o enriquecimento dos sites.</p>}
 <section className="discovery-section"><header><div><p className="eyebrow">RESULTADOS COM RASTREABILIDADE</p><h3>Estabelecimentos encontrados</h3></div><button onClick={openContacts}>Tratar contatos →</button></header><div className="discovery-table-wrap"><table><thead><tr><th>Estabelecimento / cidade</th><th>Contatos públicos</th><th>Origem / conferência</th></tr></thead><tbody>{sources.map(s=><tr key={s.source_key}><td><strong>{s.name}</strong><small>{s.city} · {s.metadata.category}</small></td><td><span>{s.phone||'Telefone não informado'}</span><small>{s.email||'E-mail não informado'}</small>{s.website&&<a href={s.website} target="_blank" rel="noopener noreferrer">Site comercial ↗</a>}</td><td><a href={s.metadata.source_url} target="_blank" rel="noopener noreferrer">Ver registro no mapa ↗</a><small>{date(s.metadata.collected_at)} · {s.metadata.source_backend||'Overpass público'} · {s.metadata.pages?.length?'Site consultado':'Dados do mapa'}</small><small>{s.phone||s.email?'Contato disponível; validade não confirmada':'Dados parciais; revisar'}</small><details><summary>Fontes e presença digital</summary><p>{s.metadata.address||'Endereço não informado'}</p><p>Coleta do site: {s.metadata.enrichment_status}</p>{s.metadata.pages?.map(url=><a key={url} href={url} target="_blank" rel="noopener noreferrer">Página consultada ↗</a>)}{s.metadata.socials?.map(url=><a key={url} href={url} target="_blank" rel="noopener noreferrer">Rede social informada ↗</a>)}</details></td></tr>)}</tbody></table>{!sources.length&&<p className="discovery-empty">Após a primeira coleta, os resultados aparecem aqui. Nenhum dado fictício é usado.</p>}</div><p className="discovery-attribution">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors · ODbL</a>. Dados públicos podem estar incompletos ou desatualizados. Até 50 registros recentes nesta prévia.</p></section>
 <section className="discovery-section"><header><div><p className="eyebrow">OPERAÇÃO E QUALIDADE</p><h3>Histórico de coleta</h3></div></header><div className="discovery-table-wrap" tabIndex={0} role="region" aria-label="Tabela do histórico de coleta"><table><thead><tr><th>Campanha / início</th><th>Situação</th><th>Encontrados</th><th>Novos</th><th>Já existentes</th><th>Sites consultados</th></tr></thead><tbody>{data.runs.map(r=><tr key={r.id}><td><strong>{data.campaigns.find(c=>c.id===r.campaign_id)?.name}</strong><small>{date(r.started_at)}</small><small>{r.scheduled_for?'Rodada agendada':'Rodada manual'}</small><details><summary>Detalhes da rodada</summary><p>{r.message||'Consulta em execução. Aguarde.'}</p></details></td><td><span className={'discovery-pill '+(r.status==='executando'?'active':'')}>{statusLabels[r.status]||r.status}</span></td><td>{r.found}</td><td>{r.added}</td><td>{r.duplicates}</td><td>{r.enriched}</td></tr>)}</tbody></table>{!data.runs.length&&<p className="discovery-empty">Nenhuma rodada executada.</p>}</div></section>
 {editor&&<CampaignEditor initial={editor.value} categories={data.categories} cities={data.local_osm?.cities} onClose={()=>setEditor(null)} busy={busy==='save'} feedback={error} onSave={async form=>{setBusy('save');setError('');try{await api('/campaigns'+(form.id?'/'+form.id:''),form.id?'PUT':'POST',form);setEditor(null);setNotice('Campanha salva. '+(form.frequency==='manual'?'Use Coletar agora para iniciar.':'Coleta agendada; o servidor precisa estar ligado.'));await refresh(true);}catch(e){setError(e.message);}finally{setBusy('');}}}/>}</>}
 </div>;
}
class Boundary extends React.Component{state={error:false};static getDerivedStateFromError(){return {error:true};}render(){return this.state.error?<p role="alert">Não foi possível abrir a captação. Recarregue a página; seus contatos foram preservados.</p>:this.props.children;}}
const root=document.getElementById('discoveryRoot');if(root)createRoot(root).render(<Boundary><Discovery/></Boundary>);
const actions=document.querySelector('.top-actions');if(actions){const notices=document.createElement('div');notices.id='discoveryNotificationRoot';actions.prepend(notices);createRoot(notices).render(<Boundary><NotificationCenter request={api}/></Boundary>);}
