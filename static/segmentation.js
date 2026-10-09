(() => {
  // CNAE/CONCLA: https://cnae.ibge.gov.br/?classe=56112&tipo=cnae&versao=9&view=classe
  // Catering: https://cnae.ibge.gov.br/?Itemid=6160&chave=5620-1&option=com_cnae&versao_classe=7.0.0&versao_subclasse=10.1.0&view=atividades
  const catalog = [
    {name:'Restaurantes e similares', codes:['5611201'], terms:'restaurante churrascaria self service comida quilo'},
    {name:'Lanchonetes e fast food', codes:['5611203'], terms:'hamburgueria fast foods pastelaria cafeteria sucos chá sorveteria', note:'CNAE compartilhado com casas de chá, sucos e similares; use o nome para refinar.'},
    {name:'Bares e estabelecimentos de bebidas', codes:['5611202','5611204','5611205'], terms:'bar pub choperia boteco bebidas'},
    {name:'Alimentação ambulante', codes:['5612100'], terms:'food truck ambulante'},
    {name:'Refeições para empresas', codes:['5620101'], terms:'refeição coletiva cozinha industrial'},
    {name:'Buffet e alimentação para eventos', codes:['5620102'], terms:'buffet bufê festas recepções'},
    {name:'Cantinas e alimentação privativa', codes:['5620103'], terms:'cantina'},
    {name:'Refeições para consumo domiciliar', codes:['5620104'], terms:'marmita marmitaria delivery domiciliar', note:'Atividade cadastrada de fornecimento de refeições; não indica presença em aplicativos.'},
    {name:'Hospedagem — grupo 55', codes:['55'], terms:'hotel hotéis pousada hospedagem', note:'Grupo amplo. Escolha os códigos específicos no campo de inclusão para afunilar.'}
  ];
  const node = id => document.getElementById(id);
  const commercialGrid=node('work_stage').closest('.filter-grid');
  commercialGrid.append(node('lead_status').closest('label'),node('favorito').closest('label'));
  node('lead_status').closest('label').firstChild.textContent='Etapa marcada na base';
  let officialCatalog=[],activeArea='',visibleLimit=24;
  const areaBox=document.createElement('div');areaBox.className='commercial-areas';
  areaBox.setAttribute('aria-label','Áreas de atividade');node('commercialCategories').before(areaBox);
  const categoryHeading=document.createElement('div');categoryHeading.className='commercial-category-heading';
  areaBox.after(categoryHeading);
  const moreButton=document.createElement('button');moreButton.type='button';moreButton.className='commercial-more';
  node('commercialCategories').after(moreButton);
  moreButton.onclick=()=>{visibleLimit+=24;render();};
  const clean = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  function render() {
    const chosen = new Set(node('cnae_include').value.split(/[,;\s]+/).filter(Boolean));
    const search = clean(node('categorySearch').value);
    const box = node('commercialCategories'); box.replaceChildren();
    const taxonomy=window.RadarCommercialTaxonomy;
    const allItems=taxonomy.build(officialCatalog,catalog);
    areaBox.replaceChildren();
    for(const area of taxonomy.areas){
      const count=allItems.filter(item=>item.area===area.id).length;
      const button=document.createElement('button');button.type='button';button.className='commercial-area';
      button.classList.toggle('active',activeArea===area.id);button.setAttribute('aria-pressed',String(activeArea===area.id));
      const name=document.createElement('strong');name.textContent=area.name;
      const meta=document.createElement('small');meta.textContent=count?`${count} ${count===1?'subcategoria':'subcategorias'}`:'Sem atividades nesta base';
      button.append(name,meta);button.onclick=()=>{activeArea=activeArea===area.id?'':area.id;node('categorySearch').value='';visibleLimit=24;render();};areaBox.append(button);
    }
    const items=allItems.filter(item=>(!activeArea||item.area===activeArea)&&(!search||clean(item.name+' '+item.terms+' '+item.codes.join(' ')+' '+(taxonomy.areas.find(area=>area.id===item.area)?.name||'')).includes(search)));
    const showCards=Boolean(activeArea||search);
    categoryHeading.textContent=showCards?`${taxonomy.areas.find(area=>area.id===activeArea)?.name||'Todas as áreas'} · ${items.length} ${items.length===1?'subcategoria':'subcategorias'} · ${chosen.size} códigos selecionados`:`Escolha uma área acima ou pesquise uma atividade. ${chosen.size} códigos selecionados.`;
    moreButton.hidden=!showCards||items.length<=visibleLimit;
    moreButton.textContent=`Mostrar mais subcategorias (${Math.min(visibleLimit,items.length)} de ${items.length})`;
    (showCards?items.slice(0,visibleLimit):[]).forEach(item => {
      const label = document.createElement('label'); label.className='commercial-category';
      const check = document.createElement('input'); check.type='checkbox'; check.checked=item.codes.every(code=>chosen.has(code));
      const copy = document.createElement('span'); const title=document.createElement('strong'); title.textContent=item.name;
      const code=document.createElement('small'); code.textContent='CNAE '+item.codes.join(' · '); copy.append(title,code);
      if(item.note){const note=document.createElement('small');note.textContent=item.note;copy.append(note);}
      check.addEventListener('change',()=>{
        const codes=new Set(node('cnae_include').value.split(/[,;\s]+/).filter(Boolean));
        item.codes.forEach(code=>check.checked?codes.add(code):codes.delete(code));
        if(codes.size>40){check.checked=false;toast('Selecione até 40 códigos por segmentação. Você também pode usar prefixos de CNAE.');return;}
        node('cnae_include').value=[...codes].join(',');node('cnae_include').dispatchEvent(new Event('change',{bubbles:true}));
      });
      label.append(check,copy);box.append(label);
    });
    if(showCards&&!box.childElementCount){const text=document.createElement('p');text.textContent='Nenhuma subcategoria encontrada neste recorte. Consulte outra área, ajuste a busca ou informe os códigos abaixo.';box.append(text);}
  }
  window.refreshCommercialCategories=render;
  window.fillSegmentationOptions=options=>{
    officialCatalog=options.cnaes||[];render();
    for(const [key,id] of [['porte','porteOptions'],['data_source','sourceOptions']]){
      const box=node(id);box.replaceChildren();
      (options[key]||[]).forEach(value=>{const option=document.createElement('option');option.value=value;box.append(option);});
    }
  };
  node('categorySearch').addEventListener('input',()=>{visibleLimit=24;render();});
  node('cnae_include').addEventListener('change',render);
  const preview=document.createElement('div');preview.className='seg-preview';preview.setAttribute('aria-live','polite');
  preview.textContent='Ajuste os filtros para consultar a quantidade de empresas.';
  node('activeSegmentation').before(preview);
  let previewTimer,previewAbort;
  function schedulePreview(){
    clearTimeout(previewTimer);previewAbort?.abort();
    previewTimer=setTimeout(async()=>{
      previewAbort=new AbortController();preview.textContent='Consultando quantidade de empresas…';
      try{
        const params=query(false);params.set('size','1');
        const response=await fetch('/api/companies?'+params,{signal:previewAbort.signal});
        if(!response.ok)throw new Error('Falha na consulta');
        const result=await response.json();preview.textContent=`${Number(result.total||0).toLocaleString('pt-BR')} empresas correspondem aos filtros. Clique em Aplicar para atualizar a lista.`;
      }catch(error){if(error.name!=='AbortError')preview.textContent='Não foi possível calcular a prévia. Tente aplicar os filtros.';}
    },500);
  }
  document.querySelectorAll('#filterDrawer input:not(#categorySearch),#filterDrawer select').forEach(input=>{
    input.addEventListener('change',schedulePreview);
    if(input.tagName==='INPUT')input.addEventListener('input',schedulePreview);
  });
  node('clear').addEventListener('click',()=>{activeArea='';node('categorySearch').value='';visibleLimit=24;render();schedulePreview();});
  node('export').onclick=async()=>{
    const button=node('export'),params=query(false),items=[];button.disabled=true;
    try{
      let current=1,count=0;
      do{
        params.set('page',current);params.set('size','100');
        const data=await api('/api/companies?'+params);count=Number(data.total||0);
        items.push(...data.items);button.textContent=`Exportando ${items.length.toLocaleString('pt-BR')} / ${count.toLocaleString('pt-BR')}`;
        if(!data.items.length)break;current++;
      }while(items.length<count);
      const columns=['cnpj','razao_social','nome_fantasia','data_abertura','cnae','cnae_descricao','segmento','municipio','regiao','porte','situacao','mei','lead_score','telefone','email','data_source'];
      const cell=value=>{let text=String(value??'');if(/^[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
      const csv=[columns.join(';'),...items.map(item=>columns.map(key=>cell(item[key])).join(';'))].join('\r\n');
      const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));
      const anchor=document.createElement('a');anchor.href=url;anchor.download=`radar-segmentacao-${new Date().toISOString().slice(0,10)}.csv`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      toast(`${items.length.toLocaleString('pt-BR')} empresas exportadas com os filtros aplicados`);
    }catch(error){toast('Falha ao exportar a segmentação: '+error.message);}
    finally{button.disabled=false;button.textContent='Exportar ↗';}
  };
  render();
})();
