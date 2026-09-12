// Run against Vite with synthetic media and mocked APIs; never touches the project database.
const { chromium } = require(process.env.WORKBENCH_PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
let browser;
(async () => {
 browser = await chromium.launch({headless:true, channel:process.env.WORKBENCH_BROWSER || 'msedge'});
 const page = await browser.newPage();
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 const wav=Buffer.alloc(44+48000*4*2); wav.write('RIFF'); wav.writeUInt32LE(wav.length-8,4); wav.write('WAVEfmt ',8); wav.writeUInt32LE(16,16); wav.writeUInt16LE(1,20); wav.writeUInt16LE(1,22); wav.writeUInt32LE(48000,24); wav.writeUInt32LE(96000,28); wav.writeUInt16LE(2,32); wav.writeUInt16LE(16,34); wav.write('data',36); wav.writeUInt32LE(wav.length-44,40);
 for(let i=0;i<48000*4;i++) wav.writeInt16LE(Math.round(2000*(Math.sin(2*Math.PI*110*i/48000)+Math.sin(2*Math.PI*880*i/48000)+Math.sin(2*Math.PI*6000*i/48000))),44+2*i);
 await page.route('**/api/artifact/**',r=>{ const range=r.request().headers()['range']; const start=range ? Number(range.match(/bytes=(\d+)/)?.[1] ?? 0) : 0; return r.fulfill({status:range?206:200,contentType:'audio/wav',headers:{'Accept-Ranges':'bytes',...(range?{'Content-Range':`bytes ${start}-${wav.length-1}/${wav.length}`}:{})},body:wav.subarray(start)}); });
 const base={filename:'test.wav',duration_seconds:4,sample_rate:48000,channels:1,original_token:'original',playback_token:'wave',peaks:[[-.2,.2],[-.3,.3]],anchors:[],media_kind:'audio',has_audio:true};
 await page.route('**/api/references',r=>r.fulfill({json:{ok:true,result:{references:[{...base,id:'a'},{...base,id:'b',filename:'second.wav'},{...base,id:'silent',filename:'silent.mp4',media_kind:'video',has_audio:false,video_token:'video',video_width:640,video_height:360}]}}}));
 await page.route('**/eq-check',r=>r.fulfill({contentType:'text/html',body:`<html><div id="root"></div><script type="module">
 import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>type=>type;window.__vite_plugin_react_preamble_installed__=true;
 const React=(await import('/node_modules/.vite/deps/react.js')).default; const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default; const {ReferencePanel}=await import('/src/components/ReferencePanel.tsx'); await import('/src/index.css');
 createRoot(document.getElementById('root')).render(React.createElement(React.StrictMode,null,React.createElement(ReferencePanel,{score:null,selection:null,onLocate:()=>{},onCreated:()=>{},onCursor:()=>{},onReferencesChanged:()=>{}})));
 </script></html>`}));
 await page.goto((process.env.WORKBENCH_WEB_URL || 'http://127.0.0.1:5173') + '/eq-check');
 await page.getByRole('button',{name:'突出低频',exact:true}).click();
 await page.getByRole('button',{name:'播放原曲选段',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('audio')?.currentTime>.15);
 const before=await page.locator('audio').evaluate(m=>m.currentTime);
 await page.getByRole('button',{name:'原声',exact:true}).click();
 assert((await page.locator('audio').evaluate(m=>m.currentTime))>=before);
 await page.getByLabel('听辨速度').selectOption('0.5');
 assert.equal(await page.locator('audio').evaluate(m=>m.playbackRate),.5);
 await page.getByLabel('原曲起始秒').fill('1'); await page.getByLabel('原曲结束秒').fill('1.4');
 await page.getByRole('button',{name:'播放原曲选段',exact:true}).click();
 await page.waitForTimeout(1000);
 const loopTime=await page.locator('audio').evaluate(m=>m.currentTime); assert(loopTime>=1 && loopTime<1.45, 'loop time: '+loopTime);
 await page.getByLabel('高频增益').fill('-12');
 if(process.env.WORKBENCH_EQ_SCREENSHOT) await page.screenshot({path:process.env.WORKBENCH_EQ_SCREENSHOT,fullPage:true});
 await page.getByLabel('参考材料',{exact:true}).selectOption('b');
 assert.equal(await page.getByRole('button',{name:'原声',exact:true}).getAttribute('aria-pressed'),'true');
 await page.getByRole('button',{name:'突出中频',exact:true}).click();
 await page.getByRole('button',{name:'播放原曲选段',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('audio')?.currentTime>.1);
 await page.getByLabel('参考材料',{exact:true}).selectOption('silent');
 assert.equal(await page.getByRole('button',{name:'突出低频',exact:true}).count(),0);
 await page.getByLabel('参考材料',{exact:true}).selectOption('a');
 await page.getByRole('button',{name:'突出高频',exact:true}).click();
 const numerical=await page.evaluate(async()=>{
  const {ListeningEq,defaultBands,eqPresets}=await import('/src/components/listeningEq.ts');
  const media=document.createElement('audio'); const eq=new ListeningEq(media,()=>{});
  const results={};
  for(const [key,preset] of Object.entries(eqPresets)) {
   const curve=eq.apply(defaultBands().map((b,i)=>({...b,gain:preset.gains[i]})),false);
   results[key]=[110,900,6000].map(f=>curve[Math.round(Math.log10(f/20)/3*240)]);
   if(curve.some(v=>!Number.isFinite(v)||v>.001))throw Error('invalid response');
  }
  results.bypass=Math.max(...eq.apply(defaultBands(),true).map(Math.abs)); eq.dispose(); return results;
 });
 assert(numerical.low[0]>numerical.low[2]+15);
 assert(numerical.mid[1]>numerical.mid[0]+8 && numerical.mid[1]>numerical.mid[2]+8);
 assert(numerical.high[2]>numerical.high[0]+15);
 assert(numerical.bypass<.001);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,numerical,checks:'StrictMode, presets, bypass position, rate, loop, sliders, material switching, silent video'},null,2));
 
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>browser?.close());




