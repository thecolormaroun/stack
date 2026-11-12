// Validation-only observer: actual film source/launcher stay byte-for-byte intact.
import {chromium} from 'playwright-core';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const original=chromium.launch.bind(chromium);
chromium.launch=async options=>{
 assert.equal(options.chromiumSandbox,true);
 const browser=await original(options);const newPage=browser.newPage.bind(browser);
 browser.newPage=async options=>{
  const page=await newPage(options);const setContent=page.setContent.bind(page);
  page.setContent=async html=>{
   const result=await setContent(html);
   const payloads=await page.locator('figcaption').allTextContents();
   const injected=await page.locator('figcaption img, figcaption script').count();
   const executed=await page.evaluate(()=>window.__captionExecuted||0);
   assert.equal(injected,0);assert.equal(executed,0);
   if(process.env.CAPTION_AUDIT)fs.writeFileSync(process.env.CAPTION_AUDIT,JSON.stringify({payloads,injected,executed,escaped:html.includes('&lt;img')},null,2));
   return result;
  };return page;
 };return browser;
};
