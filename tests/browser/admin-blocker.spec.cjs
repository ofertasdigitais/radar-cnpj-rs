const {test,expect}=require('@playwright/test');
const origin='http://127.0.0.1:18001';

// Reproduce cosmetic filters observed in the user's browser. The administration
// is not advertising and must remain usable without disabling those filters.
for(const width of [390,1920])test(`admin permanece visível com filtros de anúncios / ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1080});
  await page.route('**/react-admin.css*',async route=>{
    const response=await route.fetch();
    await route.fulfill({response,body:await response.text()+'\n.ad-main,.ad-sidebar,.ad-content,.ad-card,.ad-field,.ad-feedback{display:none!important}'});
  });
  await page.goto(origin+'/login');
  await page.locator('input[name=username]').fill('qa-admin');
  await page.locator('input[name=password]').fill('QAAdmin2026@');
  await page.getByRole('button',{name:'Entrar no Radar',exact:true}).click();
  await page.waitForURL(origin+'/');
  await page.goto(origin+'/admin');
  await expect(page.locator('h1')).toHaveText('Visão do sistema');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('Empresas na base',{exact:true})).toBeVisible();
  if(width<=1100)await page.getByRole('button',{name:'Abrir menu administrativo'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'Site e aparência',exact:true}).click();
  await expect(page.getByLabel('Cadastro público de contas')).toBeVisible();
  await expect(page.getByRole('button',{name:'Salvar parâmetros',exact:true})).toBeVisible();
});
