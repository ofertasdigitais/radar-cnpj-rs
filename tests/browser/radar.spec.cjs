const {test,expect}=require('@playwright/test');const path=require('node:path');const fs=require('node:fs');
test('fontes externas, telefone, CSV, gráficos e PDF personalizado',async({page})=>{
  await page.setViewportSize({width:1920,height:1080});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#ferramentas');await expect(page.locator('#ferramentas')).toBeVisible();
  await page.locator('[data-tool=phone]').click();await page.locator('#toolPhone').fill('5187654321');await page.locator('#toolPhoneCheck').click();await expect(page.locator('#toolPhoneResult')).toContainText('+5551987654321');
  await page.locator('[data-tool=csv]').click();await page.locator('#csvFile').setInputFiles({name:'indicacoes.csv',mimeType:'text/csv',buffer:Buffer.from('Nome;Empresa;Telefone;Origem\nJoão;Loja de indicação;51987654321;Evento')});
  await expect(page.locator('#csvImport')).toBeEnabled();await page.locator('#csvImport').click();await expect(page.locator('#csvFeedback')).toContainText('1 contato incluído');
  await page.locator('[data-tool=inbox]').click();await expect(page.locator('#prospectList')).toContainText('João');await page.locator('[data-edit]').first().click();await page.locator('.radar-dialog[open] select[name=status]').selectOption('qualificado');await page.locator('.radar-dialog[open] button[type=submit]').click();await expect(page.locator('#prospectList')).toContainText('qualificado');
  await page.locator('a[href="#bi"]').click();await expect(page.locator('#biDashboard')).toBeVisible();await expect(page.locator('#funnelChart .radar-echart svg')).toBeVisible();await expect(page.locator('#commercialBiContent')).toContainText('Campanhas');
  await page.locator('#biCommercialPdf').click();await expect(page.locator('#reportGenerate')).toBeEnabled();await page.locator('#reportTitle').fill('Análise comercial | Radar');await page.locator('#reportCompany').fill('Equipe de demonstração');await page.locator('#reportNotes').fill('Dados fictícios para revisão de layout. Priorizar retornos e registrar próximos passos.');await page.locator('#reportGenerate').click();await expect(page.locator('#reportDownload')).toBeEnabled({timeout:30000});
  const pending=page.waitForEvent('download');await page.locator('#reportDownload').click();const download=await pending;fs.mkdirSync('output/pdf',{recursive:true});await download.saveAs('output/pdf/radar-modelo-personalizado.pdf');expect(fs.readFileSync('output/pdf/radar-modelo-personalizado.pdf').subarray(0,5).toString()).toBe('%PDF-');
  await page.locator('.report-studio[open] [data-close]').first().click();await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'test-results/radar-bi-desktop.png'});expect(errors).toEqual([]);
});
for(const width of [390,768,1024,1920])for(const theme of ['dark','light'])test(`responsivo ${width}px / ${theme}`,async({page})=>{
  await page.setViewportSize({width,height:1080});await page.goto('/#ferramentas');await expect(page.locator('#ferramentas')).toBeVisible();await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;},theme);
  for(const view of ['ferramentas','leads','empresas','bi']){await page.evaluate(view=>navigateToSection(view),view);await expect(page.locator('#'+view)).toBeVisible();if(view==='bi')await expect(page.locator('#biDashboard')).toBeVisible();const geometry=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}));expect(geometry.scroll).toBeLessThanOrEqual(geometry.viewport+1);}
});
test('acessibilidade das novas ferramentas',async({page})=>{
  await page.addInitScript({path:require.resolve('axe-core')});await page.goto('/#ferramentas');await expect(page.locator('#ferramentas')).toBeVisible();await expect(page.locator('.discovery-metrics')).toBeVisible();const results=await page.evaluate(async()=>axe.run('#ferramentas',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}}));fs.mkdirSync('test-results',{recursive:true});fs.writeFileSync('test-results/axe-tools.json',JSON.stringify(results.violations,null,2));expect(results.violations.filter(x=>['critical','serious'].includes(x.impact))).toEqual([]);
});
