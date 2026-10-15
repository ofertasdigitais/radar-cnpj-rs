(function(){
  const section=$('empresas'),table=section?.querySelector('.table-card'),wrap=table?.querySelector('.tableWrap');
  if(!table||!wrap)return;
  let columns=-1;
  try{const saved=Number(localStorage.getItem('radar-company-columns')??-1);if(Number.isInteger(saved)&&saved>=-1&&saved<=10)columns=saved;}catch(_){}
  const toolbar=document.createElement('div');toolbar.className='company-layout-toolbar';
  toolbar.innerHTML='<label>Visualização de empresas<select id="companyColumns" aria-label="Colunas de empresas"></select></label><span>Escolha tabela ou cartões. As colunas se ajustam ao espaço disponível.</span>';
  table.before(toolbar);
  const grid=document.createElement('div');grid.id='companyCards';grid.className='company-cards';grid.hidden=true;wrap.after(grid);
  const select=$('companyColumns');
  function fit(){
    const width=table.clientWidth;if(!width)return;
    const maximum=Math.max(1,Math.min(window.RadarRuntime?.max_columns||10,Math.floor((width+12)/292)));
    columns=Math.min(columns,maximum);
    select.innerHTML='<option value="-1">Tabela</option><option value="0">Cartões · automático ('+maximum+')</option>'+Array.from({length:maximum},(_,i)=>`<option value="${i+1}">${i+1} ${i===0?'coluna':'colunas'}</option>`).join('');
    select.value=String(columns);grid.style.setProperty('--company-columns',String(columns>0?columns:maximum));
    wrap.hidden=columns!==-1;grid.hidden=columns===-1;
  }
  function renderCards(){
    grid.innerHTML=lastItems.length?lastItems.map((x,i)=>`<article class="company-preview-card"><header><span class="company-avatar">${companyTag(x)}</span><span class="lead-stage">${esc(stageNames[x.lead_status]||'Novo')}</span><b>${Number(x.lead_score)||0}</b></header><h3>${esc(displayName(x))}${x.favorito?' ★':''}</h3><p>${esc(fmtCnpj(x.cnpj))}</p><dl><div><dt>Atividade principal</dt><dd>${esc(cnaeText(x))}</dd></div><div><dt>CNAE</dt><dd>${esc(x.cnae||'—')}</dd></div><div><dt>Localização</dt><dd>${esc(ptTitle(x.municipio))} · ${esc(x.regiao||'RS')}</dd></div><div><dt>Abertura</dt><dd>${esc(fmtDate(x.data_abertura))}</dd></div><div><dt>Telefone</dt><dd>${esc(fmtPhone(x.telefone))}</dd></div></dl><button class="primary" data-company-card="${i}" aria-label="Abrir ficha de ${esc(displayName(x))}">Abrir ficha →</button></article>`).join(''):'<p class="company-grid-empty">Nenhuma empresa encontrada. Ajuste os filtros da consulta.</p>';
    grid.querySelectorAll('[data-company-card]').forEach(button=>button.onclick=()=>openDetail(lastItems[Number(button.dataset.companyCard)]));
    fit();
  }
  const renderTable=renderRows;
  renderRows=function(){renderTable();renderCards();};
  select.onchange=()=>{columns=Number(select.value);try{localStorage.setItem('radar-company-columns',String(columns));}catch(_){}fit();};
  window.RadarLibraries.observeResize(table,fit,{widthOnly:true});
  window.addEventListener('radar:runtime',fit);
  renderCards();
})();
