#pragma once
#include <Arduino.h>
const char ROBOT_PAGE[] PROGMEM = R"PAGE(<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HTN Robot</title>
<style>body{font:18px system-ui;max-width:600px;margin:40px auto;padding:20px}button,input{font:inherit;padding:12px;margin:6px 0}input{display:block;width:90%}button{cursor:pointer}pre{white-space:pre-wrap}#stop{background:#a00;color:white}</style>
<h1>HTN Robot</h1>
<p>Starts stopped. The motor battery stays separate from USB power.</p>
<h2>Wi-Fi</h2>
<p>Join a 2.4 GHz network or phone hotspot without a captive login page.</p>
<form id="wifi"><input name="ssid" placeholder="Network name" maxlength="32" required autocomplete="off"><input name="password" type="password" placeholder="Network password" maxlength="63" autocomplete="new-password"><button>Save and connect</button></form>
<p id="notice"></p>
<h2>Supervision</h2>
<p>Connect the agent first, then enable supervision. Keep this page visible while supervising. Hiding or closing it ends the grant within two seconds. This page sends no movement commands.</p>
<button id="enable">Enable supervision</button> <button id="stop">STOP / disable</button>
<pre id="state">Connecting…</pre>
<script>
let supervising=false,busy=false;
const note=document.querySelector('#notice');
async function post(path,body=''){
 const r=await fetch(path,{method:'POST',headers:{'X-Robot-Control':'1','Content-Type':'application/x-www-form-urlencoded'},body,signal:AbortSignal.timeout(1200)});
 if(!r.ok)throw new Error(await r.text());return r;
}
document.querySelector('#wifi').onsubmit=async e=>{e.preventDefault();supervising=false;try{await post('/network',new URLSearchParams(new FormData(e.target)));note.textContent='Saved. Check station address below; robot access point remains available.';e.target.password.value='';}catch(e){note.textContent=e.message;}};
document.querySelector('#enable').onclick=async()=>{try{await post('/supervise','enabled=1');supervising=true;note.textContent='Supervision enabled; stay with the robot.';}catch(e){note.textContent=e.message;}};
document.querySelector('#stop').onclick=async()=>{supervising=false;try{await post('/supervise','enabled=0');note.textContent='Stopped and disarmed.';}catch(e){note.textContent='Connection lost; local command expiry remains active.';}};
document.addEventListener('visibilitychange',()=>{if(document.hidden){supervising=false;post('/supervise','enabled=0').catch(()=>{});}});
setInterval(async()=>{if(busy)return;busy=true;try{
 if(supervising&&!document.hidden)await post('/supervise','enabled=1&renew=1');
 const r=await fetch('/status',{signal:AbortSignal.timeout(1200)});const s=await r.json();
 if(!s.network.controller_connected)supervising=false;
 document.querySelector('#state').textContent=JSON.stringify(s,null,2);
}catch(e){supervising=false;note.textContent='Disconnected. Reconnect and explicitly enable supervision again.';}finally{busy=false;}},500);
</script>)PAGE";
