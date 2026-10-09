const {test,expect}=require('@playwright/test');

for(const width of [390,768,1024,1920])for(const theme of ['dark','light'])test(`visão geral React ${width}px / ${theme}`,async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width,height:1080});await page.addInitScript({path:require.resolve('axe-core')});await page.addInitScript(theme=>localStorage.setItem('radar-theme',theme),theme);await page.goto('/#dashboard');
 await expect(page.locator('#overviewRoot h1')).toHaveText('Visão geral.');await expect(page.locator('.ov-loaded')).toContainText('Dados carregados');await expect(page.locator('.ov-chart svg')).toBeVisible();
 const profiles=await (await page.request.get('/api/team-profiles')).json();
 const operation=await (await page.request.get('/api/team-dashboard?profile_id='+encodeURIComponent(profiles.items[0].id))).json();
 await expect(page.locator('.ov-operation-numbers > div').first().locator('strong')).toHaveText(Number(operation.summary.active).toLocaleString('pt-BR'));
 const geometry=await page.locator('#overviewRoot').evaluate(node=>({width:node.getBoundingClientRect().width,content:node.closest('.content').getBoundingClientRect().width,padding:parseFloat(getComputedStyle(node.closest('.content')).paddingLeft),scroll:document.documentElement.scrollWidth,viewport:innerWidth,font:getComputedStyle(node.querySelector('.ov-ranking button')).fontSize}));
 expect(geometry.scroll).toBeLessThanOrEqual(width+1);expect(geometry.width).toBeGreaterThanOrEqual(geometry.content-geometry.padding*2-2);expect(parseFloat(geometry.font)).toBeGreaterThanOrEqual(15);
 const violations=await page.evaluate(async()=> (await axe.run('#overviewRoot',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));expect(violations).toEqual([]);
 await expect(page.locator('.ov-ranking').last().locator('tbody tr')).toHaveCount(3);await expect(page.locator('.ov-ranking').last().locator('td').first()).toBeVisible();await expect(page.locator('.ov-ranking').last().locator('td').nth(1)).toBeVisible();await expect(page.locator('.ov-ranking').last().locator('td').nth(2)).toBeVisible();
 if([390,768,1920].includes(width))await page.screenshot({path:`test-results/overview-${width}-${theme}.png`,fullPage:width===390});expect(errors).toEqual([]);
 await page.getByRole('button',{name:'Minha operação',exact:true}).click();await expect(page.locator('.ov-stage-table tbody tr')).toHaveCount(operation.stages.length);expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
 await page.getByRole('button',{name:'Ferramentas e integrações'}).click();await expect(page.locator('.ov-sources')).not.toContainText('Serpro');expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
});

test('filtros, atalhos de tratamento, integrações e exportação preservados',async({page})=>{
 await page.setViewportSize({width:1920,height:1080});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/#dashboard');await expect(page.locator('.ov-loaded')).toContainText('Dados carregados');
 await page.getByRole('button',{name:'Toda a base',exact:true}).click();await expect(page.locator('.ov-loaded')).toContainText('Dados carregados');await expect(page.getByRole('button',{name:'Toda a base',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.locator('.ov-opportunities button').first().click();await expect(page.locator('#teamContactOutcome')).toBeVisible();await expect(page.locator('#teamNegotiatedValue')).toBeVisible();await page.locator('#detailClose').click();
 await page.locator('.ov-ranking').last().getByRole('button',{name:/Porto Alegre/}).click();await expect(page.locator('#empresas')).toBeVisible();await expect(page.locator('#municipio')).toHaveValue('Porto Alegre');await expect(page.locator('#resultText')).toContainText('32 empresas');
 const pending=page.waitForEvent('download');await page.locator('#export').click();const download=await pending;expect(download.suggestedFilename()).toMatch(/radar-segmentacao/);
 await page.evaluate(()=>navigateToSection('dashboard'));await page.locator('.ov-action-list button').first().click();await expect(page.locator('#leads')).toBeVisible();await expect(page.locator('[data-crm-focus=overdue]')).toHaveClass(/active/);await expect(page.locator('.portfolio-lead').first()).toBeVisible();
 await page.evaluate(()=>navigateToSection('dashboard'));await page.getByRole('button',{name:'Ferramentas e integrações'}).click();await expect(page.locator('.ov-sources')).toContainText('Coleta ainda não validada');await expect(page.locator('.ov-sources')).not.toContainText('Serpro');await expect(page.locator('.ov-repositories tbody tr')).toHaveCount(7);
 await page.screenshot({path:'test-results/overview-integracoes.png'});await page.getByRole('button',{name:'Configurar campanhas'}).click();await expect(page.locator('.discovery-metrics')).toBeVisible();expect(errors).toEqual([]);
});

test('falha de API é explícita e permite recuperação sem travar',async({page})=>{
 await page.route('**/api/stats?**',route=>route.fulfill({status:503,contentType:'application/json',body:'{"erro":"QA: indisponível"}'}));await page.goto('/#dashboard');await expect(page.locator('#overviewRoot [role=alert]')).toContainText('Não foi possível atualizar');await expect(page.locator('.ov-loaded')).not.toContainText('Atualizando');await page.unroute('**/api/stats?**');await page.locator('#overviewRoot').getByRole('button',{name:'Tentar novamente',exact:true}).click();await expect(page.locator('.ov-loaded')).toContainText('Dados carregados');await expect(page.locator('.ov-chart svg')).toBeVisible();
});
