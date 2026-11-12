import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch} from './scripts/browser.mjs';
const out=new URL('../outputs/',import.meta.url).pathname;
fs.mkdirSync(out,{recursive:true});
const url=new URL('./acceptance.html',import.meta.url).href;
const result={browser:null,sandbox:null,network:[],pages:[],durationTargetMs:12000};
// Kernel filter must deny both IP families before the browser starts.
const net=await import('node:net');
for(const host of ['1.1.1.1','::1']){
 const error=await new Promise(resolve=>{const s=net.connect({host,port:443});s.on('error',e=>resolve(e.code));s.on('connect',()=>{s.destroy();resolve('CONNECTED')});});
 assert.equal(error,'EPERM'); result.network.push({host,error});
}
const browser=await launch();
try{
 result.browser=browser.version();assert.equal(result.browser,'130.0.6723.31');
 const page=await browser.newPage();
 await page.goto('data:text/html,<p>Sandbox validation</p>');
 const renderers=[];
 for(const pid of fs.readdirSync('/proc').filter(x=>/^\d+$/.test(x))){
  try{const command=fs.readFileSync(`/proc/${pid}/cmdline`,'utf8');
   if(!command.includes('--type=renderer'))continue;
   const status=fs.readFileSync(`/proc/${pid}/status`,'utf8');
   renderers.push({pid,command:command.split('\0'),status});
  }catch{}
 }
 assert(renderers.length>0);
 for(const r of renderers){
  assert.match(r.status,/Seccomp:\s+2/);assert.match(r.status,/NoNewPrivs:\s+1/);
  assert(Number(r.status.match(/Seccomp_filters:\s+(\d+)/)?.[1])>=2);
  assert(r.status.match(/NSpid:([^\n]+)/)[1].trim().split(/\s+/).length>=2);
 }
 result.sandbox={renderers,verified:'renderer PID namespace + additional Chromium seccomp filter + NNP, no sandbox-disabling flags'};
 const cdp=await browser.newBrowserCDPSession();
 result.commandLine=(await cdp.send('Browser.getBrowserCommandLine')).arguments;
 assert(!result.commandLine.some(x=>/--no-sandbox|--disable-seccomp-filter-sandbox/.test(x)));
 await assert.rejects(page.goto('https://example.com',{timeout:3000}));
 await page.close();
 const context=await browser.newContext({viewport:{width:640,height:480},recordVideo:{dir:out,size:{width:640,height:480}},reducedMotion:'no-preference'});
 const started=Date.now();const clip=await context.newPage();const errors=[];const requests=[];
 clip.on('pageerror',e=>errors.push(e.message));clip.on('request',r=>requests.push(r.url()));
 await clip.goto(url);await clip.locator('.ss-stage').waitFor();
 for(const at of [0,3000,7000,11000]){
  await clip.waitForTimeout(Math.max(0,started+at-Date.now()));
  const state=await clip.locator('.ss-stage').innerText();
  result.pages.push({at:Date.now()-started,state});
  await clip.screenshot({path:out+`video-${at}.png`});
 }
 assert.equal(await clip.locator('[data-target="create"]').getAttribute('data-done'),'true');
 assert.equal(errors.length,0,errors.join('\n'));assert(requests.every(x=>x.startsWith('file:')));
 await clip.waitForTimeout(Math.max(0,started+12000-Date.now()));
 const video=clip.video();await context.close();await video.saveAs(out+'sample-ui.webm');
 result.recordedWallMs=Date.now()-started;result.resources=requests;result.pageErrors=errors;
 for(const width of [640,390]){
  const p=await browser.newPage({viewport:{width,height:500},reducedMotion:'reduce'});await p.goto(url);await p.waitForTimeout(500);
  const state=await p.locator('[data-target="create"]').getAttribute('data-done');assert.equal(state,'true');
  const layout=await p.locator('.ss-stage').getAttribute('data-layout');assert.equal(layout,width===390?'compact':'wide');
  assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const a=await p.screenshot({path:out+`reduced-${width}.png`});await p.waitForTimeout(700);const b=await p.screenshot();assert(a.equals(b),'reduced motion must be stable');
  result.pages.push({reduced:true,width,layout,state,stable:true});await p.close();
 }
 result.passed=true;
}finally{
 await browser.close();result.browserClosed=!browser.isConnected();
 fs.writeFileSync(out+'browser-acceptance.json',JSON.stringify(result,null,2)+'\n');
}
