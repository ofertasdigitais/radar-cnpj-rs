const {test,expect}=require('@playwright/test');
const adminURL='http://127.0.0.1:18001';
async function loginAdmin(page){await page.goto(adminURL+'/login');await page.locator('input[name=username]').fill('qa-admin');await page.locator('input[name=password]').fill('QAAdmin2026@');await page.getByRole('button',{name:'Entrar no Radar',exact:true}).click();await page.waitForURL(adminURL+'/');}
for(const width of [390,768,1920])for(const theme of ['dark','light'])test(`ajuda responsiva ${width} / ${theme}`,async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width,height:1080});await page.addInitScript({path:require.resolve('axe-core')});await page.addInitScript(theme=>localStorage.setItem('radar-theme',theme),theme);
 await page.goto('/#ajuda');await expect(page.locator('#ajuda')).toBeVisible();await expect(page.locator('.help-result').first()).toBeVisible();
 await page.getByLabel('Pesquisar dúvidas').fill('WhatsApp');await expect(page.locator('.help-results')).toContainText('O número não abre no WhatsApp. O que conferir?');
 await page.locator('.help-result').filter({hasText:'O número não abre no WhatsApp. O que conferir?'}).click();await expect(page.locator('.help-reader h2')).toHaveText('O número não abre no WhatsApp. O que conferir?');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
 const violations=await page.evaluate(async()=> (await axe.run('#ajuda',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));expect(violations).toEqual([]);
 await page.locator('.help-feedback').getByRole('button',{name:'Sim',exact:true}).click();await expect(page.locator('.help-notice')).toContainText('Obrigado');
 await page.screenshot({path:`test-results/help-${width}-${theme}.png`,fullPage:true});expect(errors).toEqual([]);
});
test('FAQ organiza assuntos e abre uma resposta por vez, com links e teclado',async({page})=>{
 await page.setViewportSize({width:1920,height:1080});await page.goto('/#ajuda');
 await expect(page.locator('.help-result').first()).toBeVisible();
 await expect(page.locator('#helpRoot')).not.toContainText('sem chatbot pago');
 await expect(page.locator('.help-reader')).toHaveCount(0);
 await page.locator('[data-help-shortcut=tratar-lead]').click();
 await expect(page.locator('.help-reader')).toHaveCount(1);
 await expect(page).toHaveURL(/ajuda=tratar-lead/);
 await expect(page.locator('#help-question-tratar-lead')).toHaveAttribute('aria-expanded','true');
 await page.locator('#help-question-etapa-resultado').click();
 await expect(page.locator('.help-reader')).toHaveCount(1);
 await expect(page.locator('#help-question-tratar-lead')).toHaveAttribute('aria-expanded','false');
 await page.getByRole('button',{name:'Recolher resposta ↑'}).click();
 await expect(page.locator('#help-question-etapa-resultado')).toBeFocused();
 await expect(page).not.toHaveURL(/ajuda=/);
 await page.locator('.help-categories').getByRole('button',{name:'WhatsApp e telefones'}).click();
 await expect(page.locator('.help-group')).toHaveCount(1);
 await expect(page.locator('.help-results>header')).toContainText('WhatsApp e telefones');
 await page.getByLabel('Pesquisar dúvidas').fill('número não abre');
 await expect(page.locator('.help-result')).toHaveCount(1);
 await page.getByRole('button',{name:'Limpar pesquisa',exact:true}).click();
 await expect(page.getByLabel('Pesquisar dúvidas')).toBeFocused();
 await page.setViewportSize({width:768,height:1024});
 await page.getByLabel('Escolha um assunto').selectOption('leads');
 await expect(page.locator('.help-group')).toHaveCount(1);
 await page.locator('.help-result').first().focus();await page.keyboard.press('Enter');
 await expect(page.locator('.help-reader')).toHaveCount(1);
 await page.getByRole('button',{name:'Limpar busca',exact:true}).click();
 await expect(page.locator('.help-reader')).toHaveCount(0);
 await page.screenshot({path:'test-results/faq-organizado-tablet.png',fullPage:true});
 await page.setViewportSize({width:1920,height:1080});await page.screenshot({path:'test-results/faq-organizado-desktop.png',fullPage:true});
});

test('guia navega sem iniciar coleta, alterar leads ou enviar mensagens',async({page})=>{
 const mutations=[];page.on('request',r=>{if(r.method()!=='GET')mutations.push(r.url());});await page.goto('/?ajuda=whatsapp-formato#ajuda');await expect(page.locator('.help-result').first()).toBeVisible();
 await page.getByLabel('Pesquisar dúvidas').fill('O número não abre');await page.locator('.help-result').first().click();await page.getByRole('button',{name:'Guiar na tela →'}).click();await expect(page.locator('.help-tour')).toBeVisible();await expect(page.locator('#toolPhone')).toBeVisible();await page.keyboard.press('Escape');await expect(page.locator('#ajuda')).toBeVisible();expect(mutations).toEqual([]);
 await page.getByLabel('Pesquisar dúvidas').fill('termo-impossível-xyz');await expect(page.locator('.help-empty')).toContainText('Nenhum guia');await page.getByRole('button',{name:'Limpar busca',exact:true}).click();await expect(page.locator('.help-result').first()).toBeVisible();
});
test('admin publica guia em texto seguro e ensaia recuperação sem restaurar',async({page})=>{
 await page.setViewportSize({width:1920,height:1080});await page.addInitScript({path:require.resolve('axe-core')});await loginAdmin(page);await page.goto(adminURL+'/admin#help');await page.getByRole('button',{name:'Novo artigo +'}).click();await page.getByLabel('Título',{exact:true}).fill('FAQ QA <img src=x onerror=alert(1)>');await page.getByLabel('Resumo',{exact:true}).fill('Resumo de teste privado em base descartável.');await page.getByLabel('Passos (um por linha, de 1 a 12)').fill('Abra o Radar.\nConfira seus leads.');await page.getByLabel('Publicado para o público permitido').check();await page.getByRole('button',{name:'Salvar artigo',exact:true}).click();await expect(page.locator('.ad-help-editor [role=status]')).toContainText('Artigo publicado');
 const violations=await page.evaluate(async()=> (await axe.run('.ad-main',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));expect(violations).toEqual([]);
 await page.goto(adminURL+'/#ajuda');await page.getByLabel('Pesquisar dúvidas').fill('FAQ QA');await expect(page.locator('.help-result')).toHaveCount(1);expect(await page.locator('.help-result img').count()).toBe(0);
 await page.goto(adminURL+'/admin#system');page.on('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Criar backup',exact:true}).click();await expect(page.locator('.ad-backups a').first()).toBeVisible();await page.getByRole('button',{name:'Verificar recuperação',exact:true}).first().click();await expect(page.locator('.ad-recovery-result')).toContainText('Teste aprovado');await expect(page.locator('.ad-recovery-result')).toContainText('Produção não alterada');
});
test('contato externo vincula empresa conferida, preserva tratamento e funciona em tablet',async({page})=>{
 await page.setViewportSize({width:768,height:1024});await page.addInitScript({path:require.resolve('axe-core')});await page.goto('/#ferramentas');const created=await page.request.post('/api/prospects/import',{data:{rows:[{name:'Contato qualificação QA',phone:'51987654321',source:'Indicação QA'}]}});expect(created.ok()).toBe(true);
 await page.locator('[data-tool=inbox]').click();await page.locator('tr').filter({hasText:'Contato qualificação QA'}).getByRole('button',{name:'Encaminhar ao painel',exact:true}).click();const modal=page.locator('.prospect-qualify[open]');await expect(modal.getByLabel('Responsável da minha conta')).toContainText('Vendedor de demonstração');await modal.getByLabel('CNPJ da empresa').fill('99000000000000');await modal.getByRole('button',{name:'Conferir empresa',exact:true}).click();await expect(modal.locator('.prospect-preview')).toContainText('Loja demonstração 0');await modal.getByLabel('Conferi o nome, município e CNPJ; este contato pertence à empresa.').check();
 const violations=await page.evaluate(async()=> (await axe.run('.prospect-qualify',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));expect(violations).toEqual([]);
 await modal.getByRole('button',{name:'Confirmar encaminhamento',exact:true}).click();await expect(modal).not.toBeVisible();await expect(page.locator('#prospectSummary')).toContainText('Vinculados ao painel');const rows=await (await page.request.get('/api/team-leads?profile_id=qa-preview&q=99000000000000')).json();expect(rows.items[0].profile_lead_status).toBe('novo');
 await page.locator('tr').filter({hasText:'Contato qualificação QA'}).getByRole('button',{name:'Ver vínculo / encaminhar',exact:true}).click();await expect(modal.locator('[data-history]')).toContainText('Encaminhado ao painel');expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(769);
});
