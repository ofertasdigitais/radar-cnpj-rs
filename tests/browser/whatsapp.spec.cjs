const {test,expect}=require('@playwright/test');

for(const width of [768,1920])test(`WhatsApp completa o 9 sem bloquear nem alterar o telefone original (${width}px)`,async({page})=>{
  await page.setViewportSize({width,height:1080});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
    window.whatsappOpened=[];window.whatsappConfirmations=0;
    window.open=(...args)=>{window.whatsappOpened.push(args);return null;};
    window.confirm=()=>{window.whatsappConfirmations++;return false;};
  });
  const fixtures=[
    {telefone:'5187654321',profile_whatsapp_phone:''},
    {telefone:'5132345678',profile_whatsapp_phone:''},
    {telefone:'123',profile_whatsapp_phone:''},
    {telefone:'5587654321',profile_whatsapp_phone:'123'},
    {telefone:'51987654321',profile_whatsapp_phone:'+55 (51) 8765-4321'},
  ];
  const sourcePhones=new Map(),events=[];
  await page.route('**/api/team-leads?**',async route=>{
    const response=await route.fetch(),body=await response.json();
    body.items.forEach((item,i)=>{
      if(fixtures[i])Object.assign(item,fixtures[i],{profile_whatsapp_status:'pending'});
      sourcePhones.set(item.cnpj,item.telefone);
    });
    await route.fulfill({response,json:body});
  });
  await page.route('**/api/team-lead-events',async route=>{
    events.push(route.request().postDataJSON());await route.fulfill({json:{ok:true}});
  });
  await page.goto('/#leads');
  const buttons=page.locator('[data-team-whatsapp]');await expect(buttons.first()).toBeVisible();
  for(const i of [0,1,3,4])await expect(buttons.nth(i)).toBeEnabled();
  await expect(buttons.nth(2)).toBeDisabled();
  for(const [i,number] of [[0,'5551987654321'],[1,'555132345678'],[3,'5555987654321'],[4,'5551987654321']]){
    await buttons.nth(i).click();
    const args=await page.evaluate(()=>window.whatsappOpened.at(-1)),url=new URL(args[0]);
    expect(url.origin).toBe('https://wa.me');expect(url.pathname).toBe('/'+number);
    expect(url.searchParams.get('text')).toBeTruthy();expect(args.slice(1)).toEqual(['_blank','noopener,noreferrer']);
  }
  await page.locator('[data-team-open-lead]').first().click();
  await expect(page.locator('#detailWhatsApp')).toBeEnabled();await page.locator('#detailWhatsApp').click();
  expect(await page.evaluate(()=>window.whatsappOpened.at(-1)[0])).toContain('https://wa.me/5551987654321?text=');
  expect(await page.evaluate(()=>window.whatsappConfirmations)).toBe(0);
  const untouched=await page.evaluate(()=>portfolioItems.map(x=>[x.cnpj,x.telefone,x.profile_whatsapp_status]));
  for(const [cnpj,phone,status]of untouched){expect(phone).toBe(sourcePhones.get(cnpj));expect(status||'pending').toBe('pending');}
  await expect.poll(()=>events.length).toBe(5);expect(events.every(x=>x.event_type==='whatsapp_opened')).toBe(true);
  expect(errors).toEqual([]);
});
