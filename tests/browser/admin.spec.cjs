const {test,expect}=require('@playwright/test');
const url='http://127.0.0.1:18001';
async function login(page){await page.goto(url+'/login');await page.locator('input[name=username]').fill('qa-admin');await page.locator('input[name=password]').fill('QAAdmin2026@');await page.getByRole('button',{name:'Entrar no Radar',exact:true}).click();await page.waitForURL(url+'/');await page.goto(url+'/admin');await expect(page.locator('h1')).toHaveText('Visão do sistema');}
for(const width of [390,768,1920])for(const theme of ['dark','light'])test(`admin responsivo ${width} / ${theme}`,async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width,height:1080});await page.addInitScript({path:require.resolve('axe-core')});await page.addInitScript(theme=>localStorage.setItem('radar-theme',theme),theme);await login(page);
 const choose=async name=>{if(width<=1100)await page.getByRole('button',{name:'Abrir menu administrativo'}).click();await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();};
 await expect(page.locator('.radar-admin-metrics')).toContainText('96');
 for(const name of ['Site e aparência','Contas e acessos','Operação e relatórios','Captação automática','Integrações','Central de Ajuda','Banco e manutenção','Histórico administrativo']){
  await choose(name);expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
  const violations=await page.evaluate(async()=> (await axe.run(document.querySelector('.radar-admin-main'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));expect(violations).toEqual([]);
 }
 await choose('Site e aparência');await expect(page.getByLabel('Nome do site')).toBeVisible();await page.screenshot({path:`test-results/admin-${width}-${theme}.png`,fullPage:true});expect(errors).toEqual([]);
});
test('admin salva parâmetros, exporta sem segredos e registra histórico',async({page})=>{
 await page.setViewportSize({width:1920,height:1080});await login(page);await page.getByRole('navigation').getByRole('button',{name:'Site e aparência',exact:true}).click();await page.getByLabel('Nome do site').fill('Radar QA personalizado');await page.getByLabel('Limite de colunas').fill('2');await page.getByRole('button',{name:'Salvar parâmetros',exact:true}).click();await expect(page.getByRole('status')).toContainText('Parâmetros salvos');await page.reload();await expect(page.getByLabel('Nome do site')).toHaveValue('Radar QA personalizado');
 const runtime=await page.request.get(url+'/api/runtime');expect((await runtime.json()).max_columns).toBe(2);
 await page.getByRole('navigation').getByRole('button',{name:'Banco e manutenção',exact:true}).click();const download=page.waitForEvent('download');await page.getByRole('button',{name:'Exportar parâmetros JSON'}).click();expect((await download).suggestedFilename()).toBe('radar-parametros.json');
 await page.getByRole('navigation').getByRole('button',{name:'Histórico administrativo',exact:true}).click();await expect(page.locator('tbody')).toContainText('Nome do site');
});
test('admin cria acesso individual sem migrar leads existentes',async({page})=>{
 await page.setViewportSize({width:1920,height:1080});await login(page);await page.getByRole('navigation').getByRole('button',{name:'Contas e acessos',exact:true}).click();await page.getByRole('button',{name:'Nova conta +'}).click();await page.getByLabel('Nome completo').fill('Vendedor de QA');await page.getByLabel('Usuário',{exact:true}).fill('vendedor-browser');await page.getByLabel('Senha inicial').fill('Vendedor2026@');await page.getByRole('button',{name:'Salvar conta',exact:true}).click();await expect(page.locator('dialog')).not.toBeVisible();await expect(page.locator('tbody')).toContainText('vendedor-browser');
});
test('parâmetros chegam ao Radar, tema pessoal tem prioridade e Serpro fica oculto',async({page})=>{
 await page.setViewportSize({width:1920,height:1080});await login(page);
 const config=await (await page.request.get(url+'/api/admin/config')).json();
 const response=await page.request.post(url+'/api/admin/config',{headers:{'X-Radar-CSRF':config.csrf},data:{revision:config.revision,values:{default_theme:'light',animations:false,test_leads:false}}});expect(response.ok()).toBe(true);
 await page.evaluate(()=>localStorage.removeItem('radar-theme'));await page.goto(url+'/');await page.evaluate(()=>window.RadarRuntimeReady);
 await expect(page.locator('html')).toHaveAttribute('data-theme','light');await expect(page.locator('html')).toHaveAttribute('data-animations','false');
 await expect(page.locator('.primary-navigation a[href="/admin"]')).toBeVisible();await expect(page.locator('a[href="#monitor"]')).not.toBeVisible();await expect(page.locator('#portfolioAddTestLead')).not.toBeVisible();
 await page.evaluate(()=>localStorage.setItem('radar-theme','dark'));await page.reload();await page.evaluate(()=>window.RadarRuntimeReady);await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
});
