import React,{useEffect,useRef,useState} from 'react';

const date=value=>value?new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'}):'—';
export function openExternalContact(item){
 document.querySelector('[data-tool="inbox"]')?.click();
 const search=document.getElementById('prospectSearch');
 if(search){search.value=item.name;document.getElementById('prospectStatus').value='';document.getElementById('prospectRefresh')?.click();}
}
export function ScheduleFields({form,field}){
 const times=form.times?.length?form.times:['08:00','13:00','17:00'];
 return <><label className="discovery-icp">Perfil comercial de referência (opcional)<input maxLength={120} value={form.icp_label||''} onChange={e=>field('icp_label',e.target.value)} placeholder="Ex.: Restaurantes com presença digital"/><small>Rótulo para sua estratégia; não é uma qualificação automática de compra.</small></label>
 {form.frequency==='scheduled'&&<fieldset className="discovery-schedule"><legend>Horários das recomendações</legend><label>Rodadas por dia<select value={times.length} onChange={e=>field('times',['08:00','13:00','17:00'].slice(0,Number(e.target.value)))}><option value="1">1 rodada</option><option value="2">2 rodadas</option><option value="3">3 rodadas</option></select></label><div className="discovery-time-grid">{times.map((value,index)=><label key={index}>Rodada {index+1}<input aria-label={`Horário da rodada ${index+1}`} type="time" required value={value} onChange={e=>field('times',times.map((v,i)=>i===index?e.target.value:v))}/></label>)}</div><p>Horário local do servidor. Intervalo mínimo de uma hora. Sem computador ligado, não há coleta; ao retornar, não são disparadas todas as rodadas perdidas.</p></fieldset>}</>;
}

export function Recommendations({request,refreshKey=0}){
 const [data,setData]=useState(null),[status,setStatus]=useState('pending'),[page,setPage]=useState(1),[selected,setSelected]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const sequence=useRef(0);
 async function load(){const ticket=++sequence.current;try{const value=await request('/recommendations?'+new URLSearchParams({status,page}));if(ticket===sequence.current){setData(value);setSelected([]);setError('');}}catch(e){if(ticket===sequence.current)setError(e.message);}}
 useEffect(()=>{load();return()=>{sequence.current++;};},[status,page,refreshKey]);
 async function review(next,items){setBusy(true);setError('');try{await request('/recommendations/review','POST',{status:next,items:items.map(({id,revision})=>({id,revision}))});setNotice(next==='accepted'?'Selecionado para sua análise. Nenhum lead foi incluído no funil.':'Recomendação descartada. Não será sugerida novamente pela coleta.');await load();window.dispatchEvent(new Event('radar:recommendations-updated'));}catch(e){setError(e.message);}finally{setBusy(false);}}
 const chosen=data?.items.filter(i=>selected.includes(i.id))||[];
 return <section className="discovery-section discovery-recommendations" id="discoveryRecommendations" aria-label="Recomendações de contatos">
 <header><div><p className="eyebrow">CAPTAÇÃO ASSISTIDA · VOCÊ DECIDE</p><h3>Recomendações para sua análise</h3><p>Separadas do funil e da agenda. Selecione o que faz sentido antes de abordar.</p></div><button onClick={load} disabled={busy}>Atualizar recomendações</button></header>
 <div className="discovery-review-tabs" role="group" aria-label="Situação das recomendações">{[['pending','Para analisar'],['accepted','Selecionadas'],['dismissed','Descartadas']].map(([value,label])=><button key={value} aria-pressed={status===value} onClick={()=>{setStatus(value);setPage(1);}}>{label} <b>{data?.counts[value]||0}</b></button>)}</div>
 {error&&<p role="alert" className="discovery-feedback error">{error}</p>}{notice&&<p role="status" className="discovery-feedback">{notice}</p>}
 {status==='pending'&&!!data?.items.length&&<div className="discovery-selection"><label><input type="checkbox" checked={selected.length===data.items.length} onChange={e=>setSelected(e.target.checked?data.items.map(i=>i.id):[])}/> Selecionar esta página</label><span>{selected.length} selecionados</span><button className="discovery-primary" disabled={busy||!chosen.length} onClick={()=>review('accepted',chosen)}>Guardar seleção</button><button disabled={busy||!chosen.length} onClick={()=>review('dismissed',chosen)}>Descartar seleção</button></div>}
 {!data&&!error&&<p role="status">Carregando recomendações…</p>}
 <div className="discovery-recommendation-grid">{data?.items.map(item=><article key={item.id} className="discovery-recommendation">
 <div className="discovery-recommendation-title">{status==='pending'&&<input type="checkbox" aria-label={`Selecionar ${item.name}`} checked={selected.includes(item.id)} onChange={e=>setSelected(old=>e.target.checked?[...old,item.id]:old.filter(id=>id!==item.id))}/>}<div><h4>{item.name}</h4><small>{item.city} · {item.campaign}</small></div></div>
 <dl><div><dt>Por que apareceu</dt><dd>{item.reason}</dd></div><div><dt>Contato publicado</dt><dd>{item.phone||'Telefone não informado'}<br/>{item.email||'E-mail não informado'}</dd></div><div><dt>Encontrado em</dt><dd>{date(item.created_at)}</dd></div></dl>
 <p className="discovery-muted">Correspondência de região e categoria; interesse de compra e WhatsApp não confirmados.</p>
 <div className="discovery-campaign-actions">{status==='pending'?<><button className="discovery-primary" disabled={busy} onClick={()=>review('accepted',[item])}>Selecionar contato</button><button disabled={busy} onClick={()=>review('dismissed',[item])}>Descartar</button></>:status==='accepted'?<button className="discovery-primary" onClick={()=>openExternalContact(item)}>Tratar contato →</button>:<span>Descartado da fila de recomendações; histórico preservado.</span>}</div>
 </article>)}</div>
 {data&&!data.items.length&&<div className="discovery-empty"><h4>{status==='pending'?'Sua fila está em dia.':'Nenhuma recomendação nesta seção.'}</h4><p>Novos contatos encontrados nas campanhas aparecem aqui. Não usamos dados fictícios nem repetimos sugestões já analisadas.</p></div>}
 {data&&data.total>0&&<div className="discovery-pagination"><button disabled={busy||data.page<=1} onClick={()=>setPage(data.page-1)}>Anterior</button><span>Página {data.page} de {Math.ceil(data.total/50)} · {data.total} contatos</span><button disabled={busy||data.page*50>=data.total} onClick={()=>setPage(data.page+1)}>Próxima</button></div>}
 </section>;
}

export function NotificationCenter({request}){
 const [data,setData]=useState(null),[open,setOpen]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false);const ref=useRef(),alive=useRef(true),sequence=useRef(0);
 async function load(){const ticket=++sequence.current;try{const value=await request('/notifications');if(alive.current&&ticket===sequence.current){setData(value);setError('');}}catch(e){if(alive.current&&ticket===sequence.current)setError(e.message);}}
 useEffect(()=>{alive.current=true;load();const tick=()=>{if(!document.hidden)load();};const timer=setInterval(tick,60000);window.addEventListener('radar:recommendations-updated',tick);document.addEventListener('visibilitychange',tick);return()=>{alive.current=false;clearInterval(timer);window.removeEventListener('radar:recommendations-updated',tick);document.removeEventListener('visibilitychange',tick);};},[]);
 useEffect(()=>{if(open&&!ref.current.open){ref.current.showModal();load();}else if(!open&&ref.current.open)ref.current.close();},[open]);
 async function update(body){setBusy(true);sequence.current++;const before=data;if('enabled'in body)setData(current=>({...current,enabled:body.enabled}));try{await request('/notifications','POST',body);await load();return true;}catch(e){setData(before);setError(e.message);return false;}finally{setBusy(false);}}
 async function view(item){if(!item.read_at&&!await update({ids:[item.id]}))return;setOpen(false);document.querySelector('.primary-navigation a[href="#ferramentas"]')?.click();document.querySelector('[data-tool="auto"]')?.click();window.dispatchEvent(new Event('radar:recommendations-open'));}
 const unread=data?.enabled?data.unread:0;
 return <><button className="discovery-bell" aria-label={`Recomendações${unread?` (${unread} não lidas)`:''}`} onClick={()=>setOpen(true)} title="Recomendações de contatos"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg><span className="discovery-bell-label">Recomendações</span>{unread>0&&<b>{unread>99?'99+':unread}</b>}</button>
 <dialog ref={ref} className="discovery-dialog discovery-notifications" aria-labelledby="recommendationsNoticeTitle" onCancel={()=>setOpen(false)} onClose={()=>setOpen(false)}><header><div><p className="eyebrow">SUA CENTRAL DE RECOMENDAÇÕES</p><h2 id="recommendationsNoticeTitle">Novos contatos para analisar</h2></div><button onClick={()=>setOpen(false)} aria-label="Fechar notificações">×</button></header><p>Um resumo por rodada com novidades. Não envia mensagens, não cria tarefas e não adiciona leads ao funil.</p>
 {error&&<p role="alert">{error}</p>}<label className="discovery-notice-toggle"><input type="checkbox" checked={data?.enabled??true} disabled={busy||!data} onChange={e=>update({enabled:e.target.checked})}/> Receber avisos de novas recomendações</label><p>Desativar avisos não pausa suas campanhas nem apaga recomendações.</p>
 {data?.items.length?<><p>Até 30 avisos por vez, com os não lidos primeiro.</p><button disabled={busy||!data.items.some(i=>!i.read_at)} onClick={()=>update({ids:data.items.filter(i=>!i.read_at).map(i=>i.id)})}>Marcar avisos exibidos como lidos</button><ul className="discovery-notice-list">{data.items.map(item=><li key={item.id} className={item.read_at?'':'unread'}><strong>{item.added} {item.added===1?'novo contato encontrado':'novos contatos encontrados'}</strong><span>{item.campaign} · {date(item.created_at)}</span><button disabled={busy} onClick={()=>view(item)}>Ver recomendações →</button></li>)}</ul></>:<p className="discovery-empty">Nenhum aviso ainda. Crie uma campanha para receber recomendações.</p>}
 <footer><button onClick={()=>setOpen(false)}>Fechar</button></footer></dialog></>;
}
