import React,{useState,useEffect,useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {createPortal} from 'react-dom';

const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const destinations={empresas:['empresas'],segmentar:['empresas'],leads:['leads'],whatsapp:['ferramentas','phone'],captacao:['ferramentas','auto'],contatos:['ferramentas','inbox'],csv:['ferramentas','csv'],pesquisa:['ferramentas','research'],bi:['bi'],pdf:['leads']};
const tours={
 empresas:[['empresas',null,'#q','Pesquise uma empresa','Use nome, CNPJ ou os filtros para encontrar o perfil desejado.'],['empresas',null,'#companyFilterToggle','Refine seu recorte','Abra Filtrar para combinar atividade, localização e contato.'],['empresas',null,'#rows,#companyCards','Confira os resultados','Abra a empresa antes de adicioná-la ao painel. O guia não seleciona leads por você.']],
 segmentar:[['empresas',null,'#companyFilterToggle','Segmentação','Clique em Filtrar para abrir as opções.'],['empresas',null,'#categorySearch','Categoria comercial','Pesquise por termos do seu segmento. Combine critérios e clique em Aplicar quando estiver pronto.']],
 leads:[['leads',null,'#leads .portfolio-board','Sua área comercial','Escolha o responsável e acompanhe a fila.'],['leads',null,'.crm-toolbar','Encontre o lead','Pesquise empresa, CNPJ ou telefone; ajuste etapa e visualização.'],['leads',null,'#portfolioLeads','Trate a oportunidade','Abra Tratar lead, registre o resultado, os prazos e os valores reais. O guia não altera registros.']],
 captacao:[['ferramentas','auto','#discoveryRoot','Sua campanha','Clique em Criar campanha, escolha cidade e categoria.'],['ferramentas','auto','.discovery-campaign-grid,.discovery-empty','Controle a execução','Depois de salvar, use Coletar agora. Confira o histórico; falha de fonte não é coleta concluída.'],['ferramentas','inbox','#prospectList','Confira os contatos','Trate os resultados e encaminhe os qualificados ao painel com um CNPJ conferido.']],
 contatos:[['ferramentas','inbox','#prospectList','Sua prospecção externa','Use Tratar para qualificar ou Encaminhar ao painel para vincular um CNPJ oficial.']],
 whatsapp:[['ferramentas','phone','#toolPhone','Confira o formato','Digite o telefone com DDD e use Revisar formato. A existência no WhatsApp precisa de confirmação.']],
 csv:[['ferramentas','csv','#csvFile','Importação guiada','Selecione o arquivo, confira o mapeamento e revise a prévia antes de confirmar.']],
 pesquisa:[['ferramentas','research','#researchCompany','Pesquisa auxiliar','Informe empresa e cidade. Consultas externas só acontecem quando você solicita.']],
 bi:[['bi',null,'#biDashboard','Métricas com contexto','Selecione responsável e período. Leia a base de cálculo antes de comparar indicadores.']],
 pdf:[['leads',null,'#commercialPdf','Relatório personalizado','Abra este botão para escolher apresentação e seções. Confira os dados antes de compartilhar.']]
};
function openAction(action){const destination=destinations[action];if(!destination)return;window.navigateToSection?.(destination[0]);if(action==='segmentar')window.setFilterDrawer?.(true);if(destination[1])document.querySelector(`[data-tool="${destination[1]}"]`)?.click();}
async function api(url,options={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...options});if(r.status===401){location.href='/login';throw Error('Entre novamente para acessar a ajuda.');}const data=await r.json();if(!r.ok)throw Error(data.erro||'Não foi possível carregar.');return data;}

function GuidedTour({action,close}){const [index,setIndex]=useState(0),[found,setFound]=useState(false);const ref=useRef(null),steps=tours[action]||[],step=steps[index];
 useEffect(()=>{let disposed=false,target;setFound(false);window.navigateToSection?.(step[0]);if(step[1])document.querySelector(`[data-tool="${step[1]}"]`)?.click();if(action==='segmentar'&&index===1)window.setFilterDrawer?.(true);
 const timer=setTimeout(()=>{if(disposed)return;target=document.querySelector(step[2]);if(target){for(let node=target.parentElement;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;target.classList.add('help-tour-target');target.scrollIntoView({behavior:'auto',block:'center'});setFound(true);}ref.current?.focus();},350);
 const key=e=>{if(e.key==='Escape')close();};addEventListener('keydown',key);return()=>{disposed=true;clearTimeout(timer);target?.classList.remove('help-tour-target');removeEventListener('keydown',key);};
 },[index]);
 return createPortal(<section className="help-tour" role="dialog" aria-modal="false" aria-labelledby="help-tour-title" tabIndex={-1} ref={ref}><header><span>GUIA PRÁTICO · {index+1}/{steps.length}</span><button aria-label="Fechar guia" onClick={close}>×</button></header><h2 id="help-tour-title">{step[3]}</h2><p>{step[4]}</p>{!found&&<small>A área pode aparecer após carregar os dados ou escolher um responsável.</small>}<footer><button disabled={!index} onClick={()=>setIndex(index-1)}>Anterior</button><button className="help-primary" onClick={()=>index+1<steps.length?setIndex(index+1):close()}>{index+1<steps.length?'Próximo':'Concluir guia'}</button></footer><small>Apenas orientação: nenhum cadastro, coleta ou envio é executado pelo guia.</small></section>,document.body);
}

const shortcuts=[
 {id:'comece-aqui',label:'Começar a usar',hint:'Da pesquisa ao primeiro lead',icon:'01'},
 {id:'tratar-lead',label:'Organizar meus leads',hint:'Etapas, retornos e próximas ações',icon:'02'},
 {id:'mensagens',label:'Contatar pelo WhatsApp',hint:'Números e modelos de mensagem',icon:'03'},
 {id:'pdf',label:'Gerar relatórios',hint:'PDF e indicadores comerciais',icon:'04'}
];

function Help(){
 const [data,setData]=useState(null),[query,setQuery]=useState(''),[category,setCategory]=useState('');
 const [selected,setSelected]=useState(new URLSearchParams(location.search).get('ajuda')||'');
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[tour,setTour]=useState('');
 const search=useRef(null);
 const load=()=>api('/api/help').then(value=>{setData(value);setError('');}).catch(e=>setError(e.message));
 useEffect(()=>{
  load();
  const key=e=>{if(document.body.dataset.view==='ajuda'&&e.key==='/'&&!e.target.isContentEditable&&!/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)){e.preventDefault();search.current?.focus();}};
  const navigate=e=>{if(e.detail?.view==='ajuda')load();};
  addEventListener('keydown',key);addEventListener('radar:navigate',navigate);
  return()=>{removeEventListener('keydown',key);removeEventListener('radar:navigate',navigate);};
 },[]);
 const items=data?.items||[],categories=Object.entries(data?.categories||{}).filter(([id])=>items.some(x=>x.category===id));
 const terms=normalize(query).replace(/[^a-z0-9\s]/g,' ').split(/\s+/).filter(Boolean);
 const filtered=items.filter(x=>(!category||x.category===category)&&terms.every(t=>normalize([x.title,x.summary,x.tags,...x.steps].join(' ')).includes(t)));
 const groups=categories.map(([id,label])=>({id,label,items:filtered.filter(x=>x.category===id)})).filter(x=>x.items.length);
 const setArticle=id=>{
  setSelected(id);setNotice('');const url=new URL(location.href);
  if(id)url.searchParams.set('ajuda',id);else url.searchParams.delete('ajuda');
  history.replaceState(null,'',url.pathname+url.search+'#ajuda');
 };
 const focusQuestion=id=>requestAnimationFrame(()=>document.getElementById('help-question-'+id)?.focus({preventScroll:true}));
 const changeCategory=id=>{setCategory(id);setArticle('');};
 const changeQuery=value=>{setQuery(value);setArticle('');};
 const clear=()=>{setQuery('');setCategory('');setArticle('');};
 const openShortcut=id=>{
  setQuery('');setCategory('');setArticle(id);
  requestAnimationFrame(()=>{const question=document.getElementById('help-question-'+id);question?.scrollIntoView({block:'start',behavior:'auto'});question?.focus({preventScroll:true});});
 };
 useEffect(()=>{if(data&&selected)requestAnimationFrame(()=>document.getElementById('help-question-'+selected)?.scrollIntoView({block:'start',behavior:'auto'}));},[!!data]);
 const feedback=async(article,useful)=>{
  try{
   await api('/api/help/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:article.id,useful})});
   setData(current=>({...current,items:current.items.map(x=>x.id===article.id?{...x,my_feedback:useful}:x)}));
   setNotice('Obrigado! Sua avaliação ajuda a melhorar os guias.');
  }catch(e){setNotice(e.message);}
 };
 const copyLink=async id=>{
  try{await navigator.clipboard.writeText(location.origin+'/?ajuda='+encodeURIComponent(id)+'#ajuda');setNotice('Link copiado. O acesso exige login.');}
  catch{setNotice('Copie o endereço da barra do navegador.');}
 };
 return <div className="help-app">
  <header className="help-hero"><div><p className="help-eyebrow">CENTRAL DE AJUDA</p><h1>Como podemos ajudar?</h1><p>Busque sua dúvida ou escolha um assunto. A resposta abre aqui, com o passo a passo.</p></div></header>
  <div className="help-search"><span aria-hidden="true">⌕</span><label className="help-sr" htmlFor="help-search">Pesquisar dúvidas</label><input ref={search} id="help-search" type="search" value={query} onChange={e=>changeQuery(e.target.value)} placeholder="Busque por WhatsApp, filtros, etapas, PDF…"/>{query&&<button onClick={()=>{changeQuery('');search.current?.focus();}} aria-label="Limpar pesquisa">×</button>}<kbd aria-hidden="true">/</kbd></div>
  {error&&<div role="alert" className="help-error">{error} <button onClick={load}>Tentar novamente</button></div>}
  {!data&&!error&&<p role="status">Carregando ajuda…</p>}
  {data&&<>
   <nav className="help-shortcuts" aria-label="Atalhos de ajuda">{shortcuts.filter(s=>items.some(x=>x.id===s.id)).map(s=><button key={s.id} data-help-shortcut={s.id} onClick={()=>openShortcut(s.id)}><span className="help-shortcut-icon" aria-hidden="true">{s.icon}</span><span><strong>{s.label}</strong><small>{s.hint}</small></span><b aria-hidden="true">↗</b></button>)}</nav>
   <div className="help-layout">
    <nav className="help-categories" aria-label="Categorias de ajuda"><p className="help-eyebrow">ASSUNTOS</p><label className="help-category-select">Escolha um assunto<select value={category} onChange={e=>changeCategory(e.target.value)}><option value="">Todas as dúvidas ({items.length})</option>{categories.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><button aria-pressed={!category} onClick={()=>changeCategory('')}>Todas as dúvidas <span>{items.length}</span></button>{categories.map(([id,label])=><button key={id} aria-pressed={category===id} onClick={()=>changeCategory(id)}>{label}<span>{items.filter(x=>x.category===id).length}</span></button>)}</nav>
    <section className="help-results" aria-label="Resultados da busca"><header><div><h2>{query?'Resultados da busca':category?data.categories[category]:'Perguntas frequentes'}</h2><p>{query?'Respostas para “'+query+'”':'Clique na pergunta para ver como fazer.'}</p></div><span role="status">{filtered.length} {filtered.length===1?'resposta':'respostas'}</span></header>
     {(query||category)&&<div className="help-filter-summary"><span>{category?data.categories[category]:'Todos os assuntos'}</span><button onClick={clear}>Limpar busca</button></div>}
     {groups.length?groups.map(group=><section className="help-group" key={group.id} aria-label={group.label}><h3 className="help-group-title">{group.label}<span>{group.items.length}</span></h3><div className="help-question-list">{group.items.map(article=>{
      const expanded=selected===article.id;
      return <article className={'help-question'+(expanded?' expanded':'')} key={article.id}>
       <button id={'help-question-'+article.id} className={'help-result'+(expanded?' active':'')} aria-expanded={expanded} aria-controls={'help-answer-'+article.id} onClick={()=>setArticle(expanded?'':article.id)}><strong>{article.title}</strong><span className="help-expand" aria-hidden="true">{expanded?'−':'+'}</span></button>
       <div id={'help-answer-'+article.id} hidden={!expanded}>{expanded&&<section className="help-reader" aria-label="Leitura do guia"><h2 className="help-sr">{article.title}</h2><p className="help-summary">{article.summary}</p><ol className="help-steps">{article.steps.map((step,i)=><li key={i}><span aria-hidden="true">{i+1}</span><p>{step}</p></li>)}</ol>
        <div className="help-actions">{article.action&&<button className="help-primary" onClick={()=>article.action==='admin'?location.assign('/admin'):openAction(article.action)}>Abrir ferramenta ↗</button>}{tours[article.action]&&<button onClick={()=>setTour(article.action)}>Guiar na tela →</button>}<button onClick={()=>copyLink(article.id)}>Copiar link</button></div>
        <div className="help-feedback"><strong>Esta resposta ajudou?</strong><div><button aria-pressed={article.my_feedback===true} onClick={()=>feedback(article,true)}>Sim</button><button aria-pressed={article.my_feedback===false} onClick={()=>feedback(article,false)}>Ainda tenho dúvidas</button></div><button className="help-collapse" onClick={()=>{setArticle('');focusQuestion(article.id);}}>Recolher resposta ↑</button></div>
        {notice&&<p className="help-notice" role="status">{notice}</p>}<small className="help-updated">Atualizado em {new Date(article.updated_at).toLocaleDateString('pt-BR')}</small>
       </section>}</div>
      </article>;
     })}</div></section>):<div className="help-empty"><h3>Nenhum guia encontrado.</h3><p>Tente outro termo ou remova os filtros para consultar todas as dúvidas.</p>{category&&query&&<button onClick={()=>changeCategory('')}>Buscar em todos os assuntos</button>}</div>}
    </section>
   </div>
  </>}
  {tour&&<GuidedTour action={tour} close={()=>{setTour('');window.navigateToSection?.('ajuda');}}/>}
 </div>;
}
const root=document.getElementById('helpRoot');if(root){const nav=document.querySelector('.primary-navigation'),link=document.createElement('a');link.href='#ajuda';link.className='nav-item';link.innerHTML='<span aria-hidden="true">?</span><span><b>Central de Ajuda</b><small>Guias e dúvidas</small></span>';link.onclick=e=>{e.preventDefault();window.navigateToSection?.('ajuda',link);};nav?.append(link);const button=document.createElement('button');button.className='radar-quick-nav radar-help-shortcut';button.textContent='Ajuda';button.setAttribute('aria-label','Ajuda');button.title='Central de Ajuda';button.onclick=()=>window.navigateToSection?.('ajuda',link);document.querySelector('.top-actions')?.prepend(button);createRoot(root).render(<Help/>);}
