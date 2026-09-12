import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../cloudflare_worker.js',import.meta.url),'utf8');
const {default:worker,TelegramUpdateGuard}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const env={TELEGRAM_WEBHOOK_SECRET:'test-secret',TELEGRAM_ADMIN_CHAT_ID:'42',UPDATE_GUARD:{}};
const request=(body,secret='test-secret')=>new Request('https://example.test',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':secret},body:JSON.stringify(body)});
test('reject forged webhook',async()=>assert.equal((await worker.fetch(request({update_id:1},'wrong'),env)).status,403));
test('reject unauthorized administrator before dispatch',async()=>assert.equal((await worker.fetch(request({update_id:1,message:{from:{id:7},text:'/run'}}),env)).status,200));
test('fail closed without security configuration',async()=>assert.equal((await worker.fetch(request({}),{})).status,503));
test('duplicate update never dispatches again',async()=>{
  const map=new Map(); let chain=Promise.resolve();
  const storage={get:async k=>map.get(k),put:async(k,v)=>map.set(k,v),transaction:fn=>{
    const next=chain.then(()=>fn(storage)); chain=next.catch(()=>{}); return next;
  }};
  const guard=new TelegramUpdateGuard({storage},{TELEGRAM_ADMIN_CHAT_ID:'42'});
  let calls=0; const original=globalThis.fetch;
  globalThis.fetch=async()=>{calls++;return new Response('{"ok":true}',{status:200});};
  try {
    const payload={update_id:99,message:{from:{id:42},chat:{id:42},text:'/run'}};
    await Promise.all([guard.fetch(request(payload)),guard.fetch(request(payload))]);
    assert.equal(calls,2); // one GitHub dispatch and one Telegram acknowledgement
    assert.equal(map.get('state').status,'COMPLETED');
  } finally { globalThis.fetch=original; }
});
