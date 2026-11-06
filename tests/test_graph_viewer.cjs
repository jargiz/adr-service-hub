// Run with Node + Playwright. Optional CHROMIUM_EXECUTABLE selects a local browser.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const fixture = execFileSync('python', ['-c', `
import sys
sys.path.insert(0,'adr_service_agent')
from dashboard_visuals import trend_chart, history_chart
from network_trial_ui import chart
points=[{'time':f'2026-11-05T0{i}:00:00+00:00','value':i+3} for i in range(6)]
current={'started':1793836800,'targets':[('Gateway','a'),('Cloudflare','b')],'id':'test'}
samples=[{'time':1793836800+i*60,'rows':[{'latency_ms':i+1},{'latency_ms':i+5}]} for i in range(10)]
print(chart(current,samples,'latency_ms','Ping latency history','ms'))
print(trend_chart([{'name':'Download','points':points},{'name':'Upload','points':points}], 'Speed history','Mbit/s',True))
print(history_chart({'name':'Voltage','points':points,'unit':'V'}))
`], {encoding:'utf8'});
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE || undefined, args:['--no-sandbox']});
 try {
  for (const mobile of [false,true]) {
   const context = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1280,height:850}, isMobile:mobile, hasTouch:mobile});
   const page = await context.newPage(); const errors = [], requests = [];
   page.on('pageerror', e => errors.push(e.message));
   page.on('request', r => requests.push(r.url()));
   await page.setContent('<meta name="viewport" content="width=device-width,initial-scale=1"><style>'+fs.readFileSync('adr_service_agent/dashboard.css','utf8')+'</style>'+fixture);
   await page.addScriptTag({content:fs.readFileSync('adr_service_agent/dashboard_live.js','utf8')});
   for (const selector of ['.trial-chart svg','.trend-card [data-trend-window="day"] svg','.sense-series svg']) {
    const source = page.locator(selector);
    await source.click({position:{x:100,y:50}});
    const modal = page.locator('dialog.chart-viewer');
    await modal.waitFor({state:'visible'});
    assert.equal(await modal.evaluate(e=>e.matches(':modal')),true);
    assert.equal(await page.locator('body').evaluate(e=>e.style.overflow),'hidden');
    await modal.locator('[data-chart-in]').click();
    assert.equal(await modal.locator('output').textContent(),'150%');
    await modal.locator('[data-chart-reset]').click();
    assert.equal(await modal.locator('output').textContent(),'100%');
    const viewport = modal.locator('.chart-viewer-viewport');
    await viewport.click({position:{x:120,y:80}});
    assert.match(await modal.locator('[role="status"]').textContent(),/2026|Nov 0[45]/);
    await viewport.focus(); await page.keyboard.press('ArrowRight');
    assert.equal(await modal.locator('.chart-selection').count(),1);
    if (mobile) {
     // Real touch input exercises the two-pointer pinch path in Chromium.
     const client = await context.newCDPSession(page), bounds = await viewport.boundingBox();
     const point = (x,id) => ({x:bounds.x+x,y:bounds.y+70,id});
     await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[point(100,1),point(180,2)]});
     await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[point(60,1),point(230,2)]});
     await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
     assert.ok(parseInt(await modal.locator('output').textContent())>100,'pinch zoom increases scale');
     await modal.locator('[data-chart-close]').click();
    } else await page.keyboard.press('Escape');
    await modal.waitFor({state:'detached'});
    assert.equal(await modal.count(),0);
    assert.equal(await page.locator('body').evaluate(e=>e.style.overflow),'');
    assert.equal(await source.evaluate(e=>e===document.activeElement),true);
   }
   // Delegation survives the dashboard replacing a chart during refresh.
   await page.locator('.trial-chart').evaluate(e=>e.replaceWith(e.cloneNode(true)));
   await page.locator('.trial-chart svg').focus(); await page.keyboard.press('Enter');
   await page.locator('[data-chart-close]').click();
   await page.locator('dialog.chart-viewer').waitFor({state:'detached'});
   assert.deepEqual(errors,[]); assert.deepEqual(requests,[],'inspection must not trigger device or network requests');
   await context.close();
  }
  console.log('Graph viewer passed: desktop/mobile, all chart types, sample details, keyboard/focus, close/Escape, zoom/reset, touch pinch and replacement; no requests.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
