const {test, expect} = require('@playwright/test');

for (const theme of ['light', 'dark']) for (const width of [390, 768, 1920]) {
 test(`login público completo ${theme} ${width}px`, async ({page}) => {
  await page.setViewportSize({width, height: 1080});
  await page.addInitScript(theme => localStorage.setItem('radar-theme', theme), theme);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const cssResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/radar-polish.css');
  await page.goto('http://127.0.0.1:18001/login');
  const response = await cssResponse;
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('text/css');
  await expect(page.getByRole('button', {name: 'Entrar no Radar', exact: true})).toBeVisible();
  await expect(page.locator('.access-entry')).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({path: `test-results/login-${theme}-${width}.png`, fullPage: true});
  expect(errors).toEqual([]);
 });
}
