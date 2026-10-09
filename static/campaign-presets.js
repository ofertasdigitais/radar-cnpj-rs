(function(){
  const taxonomy=window.RadarCommercialTaxonomy;if(!taxonomy)return;
  const filter=$('filterDrawer');if(!filter)return;
  const panel=document.createElement('section');panel.className='commercial-tools';
  panel.innerHTML='<h3>Campanhas de prospecção</h3><p>Parta de uma área econômica, refine as subcategorias CNAE e salve sua segmentação. Cargo/persona e valor da oferta são informados no tratamento do lead, não inferidos da base pública.</p><div class="commercial-controls"><label>Área econômica<select id="campaignPresetArea"><option value="">Selecione uma área</option></select></label><label>Município da campanha<input id="campaignPresetCity" list="campaignPresetCities" placeholder="Opcional"><datalist id="campaignPresetCities"></datalist></label><label>Nome da campanha<input id="campaignPresetName" maxlength="80" placeholder="Ex.: Comércio - Porto Alegre"></label><button id="campaignPresetApply" class="secondary">Montar segmentação</button><button id="campaignPresetSave" class="primary">Salvar campanha</button></div>';
  filter.prepend(panel);
  $('campaignPresetArea').innerHTML+='<option value="any">Todas as áreas</option>'+(taxonomy.areas||[]).map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');
  function apply(){
    const area=$('campaignPresetArea').value;if(!area){toast('Escolha a área econômica');return false;}
    ['q','segmento','cnae','cnae_exclude','name_terms','name_exclude','regiao','mei','contato','score_min','lead_status','favorito','porte','data_source','email_available','work_stage'].forEach(id=>$(id).value='');
    $('situacao').value='ATIVA';
    const entry=taxonomy.areas.find(x=>x.id===area);
    const codes=entry?Array.from({length:entry.max-entry.min+1},(_,i)=>String(entry.min+i).padStart(2,'0')):[];
    $('cnae_include').value=codes.join(',');$('cnae_include').dispatchEvent(new Event('change',{bubbles:true}));
    const city=$('campaignPresetCity').value.trim(),options=Array.from($('municipio').options),match=options.find(x=>x.value.toLocaleLowerCase()===city.toLocaleLowerCase());
    if(city&&!match){toast('Selecione um município disponível na base');return false;}
    $('municipio').value=match?.value||'';$('phone_available').value='sim';
    $('filterDrawer').querySelector('#apply').click();return true;
  }
  $('campaignPresetApply').onclick=apply;
  $('campaignPresetCity').onfocus=()=>{$('campaignPresetCities').innerHTML=Array.from($('municipio').options).filter(x=>x.value).map(x=>`<option value="${esc(x.value)}"></option>`).join('');};
  $('campaignPresetSave').onclick=()=>{if(!$('campaignPresetName').value.trim()){toast('Informe o nome da campanha');return;}if(!apply())return;$('saveCurrentProfile').click();$('profileName').value=$('campaignPresetName').value.trim();$('profileDescription').value='Campanha de prospecção com CNAE, território e telefone público. Refine as subcategorias antes da abordagem.';};
})();
