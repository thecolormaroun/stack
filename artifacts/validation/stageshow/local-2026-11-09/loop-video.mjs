import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch} from './scripts/browser.mjs';
const out=new URL('../outputs/',import.meta.url).pathname;
const browser=await launch();
try{
 const context=await browser.newContext({viewport:{width:640,height:360},recordVideo:{dir:out,size:{width:640,height:360}}});
 const p=await context.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(new URL('./acceptance.html?mode=scene',import.meta.url).href);const start=Date.now();const samples=[];
 for(let at=0;at<=7200;at+=600){
  await p.waitForTimeout(Math.max(0,start+at-Date.now()));
  samples.push(await p.locator('.ss-stage').getAttribute('data-mark'));
 }
 await p.waitForTimeout(Math.max(0,start+8000-Date.now()));
 const video=p.video();await context.close();await video.saveAs(out+'loop-ui.webm');
 assert.equal(errors.length,0);const marks=samples.filter((s,i)=>s&&s!==samples[i-1]);
 assert(marks.filter(x=>x==='saved').length>=2);assert(marks.filter(x=>x==='reset').length>=2);
 fs.writeFileSync(out+'loop-video.json',JSON.stringify({samples,marks,errors,targetDurationMs:8000,passed:true},null,2));
}finally{await browser.close()}
