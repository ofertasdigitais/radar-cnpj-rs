const {test,expect}=require('@playwright/test');

test('tablet touch: botões, diálogo, rotação e limite de colunas',async({browser})=>{
 const context=await browser.newContext({viewport:{width:1024,height:768},hasTouch:true,isMobile:true});const page=await context.newPage();
 try{
  await page.goto('http://127.0.0.1:18000/#leads');await expect(page.locator('#salesOpsRoot .ops-task').first()).toBeVisible();
  await page.locator('#salesOpsRoot .ops-task').first().getByRole('button',{name:'Registrar contato',exact:true}).tap();await expect(page.locator('.ops-dialog[open]')).toBeVisible();
  await page.locator('.ops-dialog[open]').getByRole('button',{name:'Cancelar',exact:true}).tap();
  await page.setViewportSize({width:768,height:1024});expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(769);
  const columns=page.locator('#portfolioColumns');await columns.selectOption('1');await expect(columns).toHaveValue('1');
  const widths=await page.locator('#portfolioLeads').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));expect(widths.scroll).toBeLessThanOrEqual(widths.client+1);
 }finally{await context.close();}
});

test('agenda registra contato, retorno, bloqueio e reautorização',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/#leads');const root=page.locator('#salesOpsRoot');
 await expect(root.getByRole('heading',{name:'Agenda e retornos'})).toBeVisible();
 await expect(root.locator('.ops-task').first()).toBeVisible();
 const task=root.locator('.ops-task').first(),name=await task.locator('h4').textContent();
 await task.getByRole('button',{name:'Registrar contato',exact:true}).click();
 const dialog=page.locator('.ops-dialog[open]');
 await dialog.getByLabel('Resultado do contato').selectOption('retornar');
 await dialog.getByLabel('Próxima ação',{exact:true}).fill('Retorno QA agendado');
 await dialog.getByLabel('Data e hora do retorno').fill('2026-12-01T10:00');
 await dialog.getByLabel('Nota deste contato').fill('Registro isolado, sem leads reais.');
 await dialog.getByRole('button',{name:'Salvar contato e retorno'}).click();
 await expect(dialog).toHaveCount(0);
 await root.getByRole('searchbox').fill(name);await root.getByRole('button',{name:/Mais adiante/}).click();
 const saved=root.locator('.ops-task').filter({hasText:name});await expect(saved).toContainText('Retorno QA agendado');
 await saved.getByRole('button',{name:'Tratar lead',exact:true}).click();await expect(page.locator('#detailDrawer')).toHaveClass(/open/);await page.keyboard.press('Escape');
 await saved.getByRole('button',{name:'Não contatar',exact:true}).click();
 await dialog.getByLabel('Motivo do bloqueio').fill('Autorização retirada — QA');
 await dialog.getByRole('button',{name:'Confirmar bloqueio'}).click();
 await expect(root.locator('.ops-suppressed')).toContainText(name);
 await root.locator('.ops-suppressed summary').click();
 const blocked=root.locator('.ops-suppressed article').filter({hasText:name});
 page.once('dialog',d=>d.accept());await blocked.getByRole('button',{name:'Reautorizar contato'}).click();
 await expect(root.locator('.ops-suppressed article').filter({hasText:name})).toHaveCount(0);
 expect(errors).toEqual([]);
});

test('BI separa fechamentos, compara períodos e salva metas mensais',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/#bi');
 const root=page.locator('#salesPerformanceRoot');await expect(root.locator('.ops-kpis article')).toHaveCount(4);
 await root.getByRole('button',{name:'Últimos 7 dias'}).click();await expect(root.locator('.ops-trend svg')).toBeVisible();
 await root.getByLabel('Meta de receita (R$)').fill('12500.50');await root.getByLabel('Meta de contatos',{exact:true}).fill('75');await root.getByLabel('Meta de vendas',{exact:true}).fill('8');
 await root.getByRole('button',{name:'Salvar metas'}).click();await expect(root).toContainText('Metas salvas');
 await page.reload();await expect(root.getByLabel('Meta de receita (R$)')).toHaveValue('12500.5');
 await root.getByText('Ver evolução em tabela',{exact:true}).click();await expect(root.locator('tbody tr').first()).toBeVisible();
 await root.getByText('Entenda a base de cálculo',{exact:true}).click();await expect(root).toContainText('Abrir um link de WhatsApp não comprova contato');
 expect(errors).toEqual([]);
});

for(const viewport of [{width:390,height:844},{width:768,height:1024},{width:1024,height:768},{width:1920,height:1080}])for(const theme of ['light','dark'])test(`agenda e BI responsivos ${viewport.width}x${viewport.height} ${theme}`,async({page})=>{
 await page.setViewportSize(viewport);await page.goto('/#leads');await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
 await expect(page.locator('#salesOpsRoot .ops-task').first()).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width+1);
 await page.locator('#salesOpsRoot').screenshot({path:`test-results/agenda-${viewport.width}-${theme}.png`});
 await page.locator('#salesOpsRoot .ops-task').first().getByRole('button',{name:'Registrar contato',exact:true}).click();
 const dialog=page.locator('.ops-dialog[open]');await expect(dialog).toBeVisible();
 const bounds=await dialog.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(viewport.width+1);
 await dialog.getByRole('button',{name:'Cancelar',exact:true}).click();
 await page.goto('/#bi');await expect(page.locator('#salesPerformanceRoot .ops-kpis article')).toHaveCount(4);
 const header=await page.locator('#salesPerformanceRoot .ops-heading').boundingBox();expect(header.height).toBeLessThan(230);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width+1);
 await page.locator('#salesPerformanceRoot').screenshot({path:`test-results/resultados-${viewport.width}-${theme}.png`});
});

test('acessibilidade da agenda, diálogo e BI',async({page})=>{
 await page.addInitScript({path:require.resolve('axe-core')});await page.goto('/#leads');await expect(page.locator('#salesOpsRoot .ops-task').first()).toBeVisible();
 const audit=async selector=>{const result=await page.evaluate(async s=>(await axe.run(s,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)),selector);expect(result).toEqual([]);};
 await audit('#salesOpsRoot');await page.locator('#salesOpsRoot .ops-task').first().getByRole('button',{name:'Registrar contato',exact:true}).click();await audit('.ops-dialog');await page.keyboard.press('Escape');
 await page.goto('/#bi');await expect(page.locator('#salesPerformanceRoot .ops-kpis article')).toHaveCount(4);await audit('#salesPerformanceRoot');
});
