const {test,expect}=require('@playwright/test');
for(const width of [390,1024])test(`concluir lead pelos cartões ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.goto('/#leads');
 const button=page.locator('[data-team-complete]:not([disabled])').first();await expect(button).toBeVisible();
 const cnpj=await button.getAttribute('data-team-complete');await button.click();
 const dialog=page.locator('.ops-dialog[open]');await expect(dialog.getByRole('heading',{name:'Concluir ação ou dar baixa'})).toBeVisible();
 const box=await dialog.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width+1);
 await dialog.getByLabel('Ação realizada').fill('Atendimento concluído no teste isolado.');await dialog.getByRole('button',{name:'Confirmar baixa do lead'}).click();
 await expect(dialog).toHaveCount(0);await expect(page.locator(`[data-team-complete="${cnpj}"]`)).toBeDisabled();
 await expect(page.locator('.portfolio-lead').filter({has:page.locator(`[data-team-complete="${cnpj}"]`)})).toContainText('Concluído');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
});
