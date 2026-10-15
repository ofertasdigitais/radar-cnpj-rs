const {test,expect}=require('@playwright/test');

for(const theme of ['light','dark'])for(const [width,height] of [[320,568],[390,844],[844,390],[768,1024],[1366,768],[1920,1080]]){
 test(`contraste e navegação ${theme} ${width}x${height}`,async({page})=>{
  await page.setViewportSize({width,height});
  await page.addInitScript(theme=>localStorage.setItem('radar-theme',theme),theme);
  await page.route('**/api/discovery/notifications',route=>route.fulfill({json:{items:[],unread:1,enabled:true}}));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#segmentacoes');
  await page.evaluate(()=>window.RadarAppReady);
  const bell=page.locator('.discovery-bell');
  await expect(bell).toBeVisible();
  const contrast=await bell.evaluate(e=>{
   const css=getComputedStyle(e),rgb=s=>s.match(/[\d.]+/g).slice(0,3).map(Number);
   const lum=c=>c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
   const a=lum(rgb(css.color)),b=lum(rgb(css.backgroundColor));return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });
  expect(contrast).toBeGreaterThanOrEqual(4.5);
  if(width<=900){
   await page.locator('#menu').click();
   await expect(page.locator('#sidebar')).toHaveClass(/open/);
   const navHeight=await page.locator('.primary-navigation').evaluate(e=>e.getBoundingClientRect().height);
   expect(navHeight).toBeGreaterThan(170);
   expect(await page.locator('.sidebar-scrim').evaluate(e=>getComputedStyle(e).position)).toBe('fixed');
   await page.locator('.sidebar-scrim').click({position:{x:width-15,y:100}});
   await expect(page.locator('#sidebar')).not.toHaveClass(/open/);
   await page.locator('#menu').click();await page.keyboard.press('Escape');
   await expect(page.locator('#sidebar')).not.toHaveClass(/open/);
  }
  for(const view of ['dashboard','analises','empresas','oportunidades','leads','bi','perfis','segmentacoes','pipeline','ferramentas','ajuda']){
   await page.goto('/#'+view);
   await expect(page.locator('body')).toHaveAttribute('data-view',view);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth),view).toBeLessThanOrEqual(1);
  }
  await page.goto('/#bi');
  const segments=page.locator('#bi').getByRole('button',{name:'Segmentos',exact:true});
  await expect(segments).toBeVisible();
  const bounds=await segments.boundingBox();expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
  expect(errors).toEqual([]);
 });
}
