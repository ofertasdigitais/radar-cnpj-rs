const {test,expect}=require('@playwright/test');
for(const theme of ['light','dark'])for(const width of [390,768,1920]){
 test(`auditoria de contraste ${theme} ${width}px`,async({page})=>{
  test.setTimeout(120000);
  await page.setViewportSize({width,height:1080});
  await page.addInitScript(theme=>localStorage.setItem('radar-theme',theme),theme);
  await page.addInitScript({path:require.resolve('axe-core')});
  const issues=[];
  for(const view of ['dashboard','analises','empresas','oportunidades','leads','bi','perfis','segmentacoes','pipeline','ferramentas','ajuda']){
   await page.goto('/#'+view);await page.evaluate(()=>window.RadarAppReady);
   if(view==='leads')await expect(page.locator('.portfolio-lead').first()).toBeVisible();
   if(view==='bi')await expect(page.locator('#bi').getByRole('button',{name:'Segmentos',exact:true})).toBeVisible();
   await page.evaluate(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await Promise.all(document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().iterations)).map(a=>a.finished.catch(()=>{})));});
   await expect(page.locator('body')).toHaveAttribute('data-view',view);
   const failures=await page.evaluate(async()=> (await axe.run(document,{runOnly:{type:'rule',values:['color-contrast']}})).violations.flatMap(v=>v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))));
   issues.push(...failures.map(x=>({view,...x})));
   if(width===1920||view==='bi'||view==='leads')await page.screenshot({path:`test-results/visual-${view}-${theme}-${width}.png`,fullPage:await page.evaluate(()=>document.documentElement.scrollHeight<30000)});
  }
  expect(issues).toEqual([]);
 });
}
