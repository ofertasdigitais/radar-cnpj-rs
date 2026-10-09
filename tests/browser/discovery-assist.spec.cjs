const {test,expect}=require('@playwright/test');

test('pausar campanha supera consulta anterior em andamento',async({page})=>{
 let hold=false,release,started;
 const ready=new Promise(resolve=>started=resolve),gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/discovery',async route=>{
  if(route.request().method()!=='GET')return route.continue();
  const response=await route.fetch(),data=await response.json();
  if(hold){hold=false;started();await gate;}
  await route.fulfill({json:data});
 });
 try{
  await page.goto('/#ferramentas');await page.getByRole('button',{name:'Criar campanha'}).click();
  const editor=page.locator('.discovery-dialog[open]');
  await editor.getByLabel('Nome da campanha').fill('Corrida de atualização QA');
  await editor.getByLabel('Município do RS').fill('Porto Alegre');
  await editor.getByRole('button',{name:'Salvar campanha'}).click();
  const campaign=page.locator('.discovery-campaign').filter({hasText:'Corrida de atualização QA'});
  await expect(campaign.getByRole('button',{name:'Pausar'})).toBeVisible();
  hold=true;await page.evaluate(()=>window.dispatchEvent(new Event('radar:discovery-open')));await ready;
  await campaign.getByRole('button',{name:'Pausar'}).click();
  await expect(campaign.getByRole('button',{name:'Ativar',exact:true})).toBeEnabled();
  release();await expect(campaign.getByRole('button',{name:'Coletar agora'})).toBeDisabled();
  await expect(campaign.getByRole('button',{name:'Ativar',exact:true})).toBeEnabled();
 }finally{release();}
});

for(const width of [390,768,1024,1920])for(const theme of ['dark','light'])test(`recomendações e três horários ${width}/${theme}`,async({page})=>{
 await page.setViewportSize({width,height:1080});
 await page.addInitScript(theme=>localStorage.setItem('radar-theme',theme),theme);
 await page.addInitScript({path:require.resolve('axe-core')});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const rows=[1,2,3].map(i=>({id:`qa-rec-${i}`,revision:1,status:'pending',name:`Estabelecimento de demonstração ${i}`,city:'Porto Alegre',campaign:'Restaurantes QA',reason:'Porto Alegre · Restaurantes · Telefone público disponível',phone:'51987654321',email:'contato@example.invalid',created_at:'2026-10-07T08:00:00'}));
 const notices=[{id:'qa-note',run_id:'qa-run',campaign:'Restaurantes QA',added:3,created_at:'2026-10-07T08:00:00',read_at:null}];let enabled=true;
 // Deterministic browser fixtures; backend round/storage/privacy tested in Python.
 await page.route('**/api/discovery/recommendations**',async route=>{
  const request=route.request();if(request.method()==='POST'){const body=request.postDataJSON();for(const item of body.items){const row=rows.find(r=>r.id===item.id);row.status=body.status;row.revision++;}return route.fulfill({json:{updated:body.items.length,status:body.status}});}
  const url=new URL(request.url()),status=url.searchParams.get('status')||'pending';const items=rows.filter(r=>r.status===status);
  return route.fulfill({json:{items,total:items.length,page:1,size:50,counts:Object.fromEntries(['pending','accepted','dismissed'].map(s=>[s,rows.filter(r=>r.status===s).length]))}});
 });
 await page.route('**/api/discovery/notifications',async route=>{
  const request=route.request();if(request.method()==='POST'){const body=request.postDataJSON();if('enabled'in body)enabled=body.enabled;else for(const item of notices)if(body.ids.includes(item.id))item.read_at='2026-10-07T10:00:00';return route.fulfill({json:{ok:true}});}
  return route.fulfill({json:{items:notices,unread:notices.filter(i=>!i.read_at).length,enabled}});
 });
 await page.goto('/#ferramentas');
 const recs=page.getByRole('region',{name:'Recomendações de contatos'});
 await expect(recs).toContainText('Estabelecimento de demonstração 1');
 await recs.getByLabel('Selecionar esta página').check();
 await expect(recs).toContainText('3 selecionados');
 await recs.getByRole('button',{name:'Guardar seleção'}).click();
 await recs.getByRole('button',{name:/Selecionadas/}).click();
 await expect(recs.getByRole('button',{name:'Tratar contato →'})).toHaveCount(3);
 await page.getByRole('button',{name:'Criar campanha'}).click();
 const editor=page.locator('.discovery-dialog[open]');
 await editor.getByLabel('Nome da campanha').fill(`Horários QA ${width} ${theme}`);
 await editor.getByLabel('Município do RS').fill('Porto Alegre');
 await editor.getByLabel('Frequência',{exact:true}).selectOption('scheduled');
 await expect(editor.getByLabel('Horário da rodada 1')).toHaveValue('08:00');
 await expect(editor.getByLabel('Horário da rodada 2')).toHaveValue('13:00');
 await expect(editor.getByLabel('Horário da rodada 3')).toHaveValue('17:00');
 await editor.getByLabel('Horário da rodada 3').fill('17:30');
 await editor.getByRole('button',{name:'Salvar campanha'}).click();
 const campaign=page.locator('.discovery-campaign').filter({hasText:`Horários QA ${width} ${theme}`});
 await expect(campaign).toContainText('17:30');
 await campaign.getByRole('button',{name:'Pausar'}).click();
 await expect(campaign.getByRole('button',{name:'Coletar agora'})).toBeDisabled();
 await page.getByRole('button',{name:/^Recomendações/}).click();
 const dialog=page.locator('.discovery-notifications[open]');
 await expect(dialog).toContainText('3 novos contatos encontrados');
 await dialog.getByLabel('Receber avisos de novas recomendações').uncheck();
 await expect(dialog.getByLabel('Receber avisos de novas recomendações')).not.toBeChecked();
 await dialog.getByLabel('Receber avisos de novas recomendações').check();
 const bounds=await dialog.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width+1);
 await dialog.getByRole('button',{name:'Ver recomendações →'}).click();
 await expect(dialog).not.toBeVisible();
 await expect(page.getByRole('button',{name:'Recomendações',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
 const accessibility=await page.evaluate(async()=>{const result=await axe.run(document.querySelector('#discoveryRoot'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}});return result.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));});
 expect(accessibility).toEqual([]);
 await page.screenshot({path:`test-results/recomendacoes-${width}-${theme}.png`,fullPage:true});
 expect(errors).toEqual([]);
});
