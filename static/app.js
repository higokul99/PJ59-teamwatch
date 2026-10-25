'use strict';
const $ = id => document.getElementById(id);
let role, ws, roomState, media, mediaKey = '', mode = localStorage.getItem('tw-mode') || 'combined';
let enabled = false, clockOffset = 0, clockSamples = [], reconnect, pingTimer, leaving = false, connecting = false, uploading = false;
let startTimer, clockTimers = [], lastSeek = -Infinity, pendingForce = false, playPending = false;
let adjustment = Number(localStorage.getItem('tw-offset') || 0);
if (!Number.isFinite(adjustment)) adjustment = 0;
adjustment = Math.max(-2000, Math.min(2000, adjustment));
$('offset').value = adjustment;
const monotonicEpoch = Date.now() - performance.now();
const localNow = () => (monotonicEpoch + performance.now()) / 1000;
const serverNow = () => localNow() + clockOffset;
const player = () => mode === 'audio' || (media && !media.has_video) ? $('audio') : $('video');
const fmt = n => {n = Math.max(0, Math.floor(n || 0)); return `${n >= 3600 ? Math.floor(n/3600)+':' : ''}${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
function notice(message) {$('notice').textContent = message;}
async function api(path, data) {
 const r = await fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const b = await r.json(); if (!r.ok) throw Error(b.detail || 'Request failed'); return b;
}
$('joinForm').onsubmit = async e => {
 e.preventDefault(); $('loginError').textContent='';
 const button=e.currentTarget.querySelector('button'); button.disabled=true;
 try {await api('/api/join',{code:$('code').value.trim(),pin:$('pin').value}); $('pin').value=''; await enter();}
 catch(e){$('loginError').textContent=e.message;} finally{button.disabled=false;}
};
async function enter(){
 const data=await api('/api/me'); role=data.role;
 $('login').hidden=true; $('room').hidden=false; $('logout').hidden=false;
 $('hostControls').hidden=role!=='host'; $('uploadPanel').hidden=role!=='host';
 $('roomLabel').textContent=`ROOM ${data.room} · ${role.toUpperCase()}`;
 receiveState(data); openSocket();
}
function openSocket(){
 clearInterval(pingTimer); clearTimeout(reconnect);
 ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
 ws.onopen=()=>{clockSamples=[]; measureClock(); pingTimer=setInterval(ping,2000);};
 ws.onmessage=e=>{
  const data=JSON.parse(e.data);
  if(data.type==='pong'){
   const now=localNow(), rtt=now-data.sent;
   if(!Number.isFinite(rtt)||rtt<0||rtt>5)return;
   clockSamples.push({rtt,offset:data.server_time-(data.sent+now)/2});
   clockSamples=clockSamples.slice(-15);
   clockOffset=[...clockSamples].sort((a,b)=>a.rtt-b.rtt)[0].offset;
   scheduleStart();
   $('clockInfo').textContent=`Round trip: ${Math.round(rtt*1000)} ms · Device adjustment: ${adjustment} ms`;
  } else if(data.type==='state') receiveState(data);
  else if(data.type==='error') notice(data.message);
 };
 ws.onclose=e=>{
  clearInterval(pingTimer); clearTimeout(startTimer); clockTimers.forEach(clearTimeout); $('connection').textContent='Disconnected';
  $('video').pause(); $('audio').pause();
  if(leaving)return;
  if(e.code===1008){notice('Your session ended. Leave the room and join again.');return;}
  notice('Connection lost. Reconnecting; playback will catch up.'); reconnect=setTimeout(openSocket,2000);
 };
 ws.onerror=()=>ws.close();
}
function ping(){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'ping',sent:localNow()}));}
function measureClock(){
 clockTimers.forEach(clearTimeout);
 ping(); clockTimers=[150,350,650,1000].map(delay=>setTimeout(ping,delay));
}
function scheduleStart(){
 clearTimeout(startTimer);
 if(!roomState?.playing||!enabled)return;
 const wait=(roomState.anchor-serverNow())*1000;
 if(wait>0)startTimer=setTimeout(()=>{if(serverNow()<roomState.anchor)scheduleStart();else sync();},Math.max(1,Math.min(wait,2147483647)));
}
function receiveState(data){
 if(!clockSamples.length)clockOffset=data.server_time-localNow();
 const changed=roomState?.revision!==data.timeline.revision;
 roomState=data.timeline; media=data.media;
 if(changed)pendingForce=true;
 $('connection').textContent=`${data.count} connected`;
 $('movieName').textContent=media?.name || 'Your shared cinema';
 if(!uploading)$('uploadStatus').textContent=data.processing.message;
 const busy=uploading||data.processing.status==='processing';
 $('upload').disabled=busy; $('file').disabled=busy;
 $('play').disabled=$('pause').disabled=$('restart').disabled=$('seek').disabled=!media;
 if(media){$('seek').max=media.duration;}
 notice(data.processing.message);
 configureMedia(); scheduleStart(); sync();
}
function configureMedia(){
 if(!['audio','video','combined'].includes(mode))mode='combined';
 document.querySelectorAll('[data-mode]').forEach(b=>{
  b.classList.toggle('active',b.dataset.mode===mode);
  b.setAttribute('aria-pressed',String(b.dataset.mode===mode));
  b.disabled=!!media && !media.has_video && b.dataset.mode!=='audio';
 });
 if(media&&!media.has_video&&mode!=='audio'){mode='audio';configureMedia();return;}
 const key=media ? `${media.id}:${mode}` : '';
 if(key===mediaKey)return;
 mediaKey=key; enabled=false; playPending=false; pendingForce=true; lastSeek=-Infinity; clearTimeout(startTimer);
 for(const el of [$('video'),$('audio')]){el.pause();el.removeAttribute('src');el.load();}
 $('resync').disabled=!media;
 $('connect').disabled=!media; $('connect').textContent='Connect playback';
 $('connectHint').textContent='Tap to enable playback on this device.';
 $('volume').disabled=mode==='video';
 $('placeholder').hidden=!!media&&mode!=='audio';
 $('video').hidden=!media||mode==='audio';
 $('fullscreen').hidden=!media||mode==='audio';
 if(media){
  const p=player(); p.muted=mode==='video';
  p.src=`/media/${media.id}/${mode==='audio'?'audio.m4a':mode==='video'?'video.mp4':'combined.mp4'}`;
  p.load(); $('screenTitle').textContent='Just you and the sound.';
  $('screenText').textContent='Put on your headphones. Playback follows the host.';
 }
}
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;localStorage.setItem('tw-mode',mode);configureMedia();});
let wakeLock;
async function keepAwake(){try{if('wakeLock' in navigator)wakeLock=await navigator.wakeLock.request('screen');}catch{}}
$('connect').onclick=async()=>{
 if(!media)return;
 const p=player(); connecting=true; pendingForce=true;
 // play() must be called directly from the gesture for mobile autoplay policies.
 try{
  await p.play(); enabled=true; connecting=false; sync(); scheduleStart(); await keepAwake();
  $('connect').textContent='Playback connected ✓';
  $('connectHint').textContent='Keep this page visible for the best synchronization.';
 }catch(e){enabled=false;notice('Playback could not start. Wait for buffering, then tap Connect playback again.');}
 finally{connecting=false;sync();}
};
function targetPosition(){
 if(!roomState||!media)return 0;
 return TeamWatchSync.target(roomState,media.duration,serverNow(),adjustment);
}
function sync(force=false){
 if(force)pendingForce=true;
 if(!media||!roomState)return;
 const p=player(), target=targetPosition();
 $('time').textContent=`${fmt(target)} / ${fmt(media.duration)}`;
 if(document.activeElement!==$('seek'))$('seek').value=target;
 if(!enabled||connecting){$('syncStatus').textContent='Tap Connect playback';return;}
 if(ws?.readyState!==WebSocket.OPEN){p.pause();return;}
 const playing=roomState.playing&&serverNow()>=roomState.anchor&&target<media.duration;
 // Apply pause immediately, even when the decoder is buffering.
 if(!playing&&!p.paused)p.pause();
 if(p.readyState<2){$('syncStatus').textContent='Buffering…';return;}
 const decision=TeamWatchSync.correction({target,current:p.currentTime,playing,seeking:p.seeking,force:pendingForce,now:performance.now()/1000,lastSeek});
 if(p.seeking){$('syncStatus').textContent='Aligning playback…';return;}
 pendingForce=false;
 if(decision.seek){
  lastSeek=performance.now()/1000;
  p.currentTime=target;
 }
 p.playbackRate=decision.rate;
 if(playing&&p.paused&&!playPending){
  playPending=true;
  p.play().catch(()=>{enabled=false;$('connect').textContent='Reconnect playback';notice('Your browser paused playback. Tap Connect playback to resume.');}).finally(()=>{playPending=false;});
 }
 const ms=Math.round(Math.abs(decision.drift)*1000);
 $('syncStatus').textContent=!roomState.playing?'Room paused':serverNow()<roomState.anchor?'Starting together…':ms<=30?'Following host · aligned':`Following host · ${ms} ms ${decision.drift>0?'behind':'ahead'}`;
}
// The deadline timer starts playback at the anchor instead of waiting up to
// 200 ms for the next periodic check. This interval handles ongoing drift.
setInterval(sync,100);
$('resync').onclick=()=>{measureClock();pendingForce=true;sync();scheduleStart();};
function command(action,extra={}){
 if(ws?.readyState!==WebSocket.OPEN){notice('Wait for the room connection.');return;}
 ws.send(JSON.stringify({type:'control',action,...extra}));
}
$('play').onclick=()=>command('play'); $('pause').onclick=()=>command('pause');
$('restart').onclick=()=>command('seek',{position:0});
$('seek').onchange=()=>command('seek',{position:Number($('seek').value)});
$('offset').onchange=()=>{adjustment=Math.max(-2000,Math.min(2000,Number($('offset').value)||0));$('offset').value=adjustment;localStorage.setItem('tw-offset',adjustment);sync(true);};
$('volume').oninput=()=>{for(const p of [$('video'),$('audio')])p.volume=Number($('volume').value);$('volumeValue').textContent=`${Math.round(Number($('volume').value)*100)}%`;};
$('fullscreen').onclick=async()=>{try{if($('video').webkitEnterFullscreen&&!$('video').requestFullscreen)$('video').webkitEnterFullscreen();else await $('video').requestFullscreen();}catch{notice('Full screen is not supported on this browser.');}};
$('logout').onclick=async()=>{try{await api('/api/logout',{});leaving=true;ws?.close();location.reload();}catch(e){notice(e.message);}};
$('upload').onclick=()=>{
 const file=$('file').files[0]; if(!file){notice('Choose a movie or song first.');return;}
 uploading=true;$('upload').disabled=true;$('file').disabled=true;$('uploadProgress').hidden=false;
 const xhr=new XMLHttpRequest();xhr.open('POST',`/api/upload?name=${encodeURIComponent(file.name)}`);
 xhr.setRequestHeader('Content-Type','application/octet-stream');
 xhr.upload.onprogress=e=>{if(e.lengthComputable){$('uploadProgress').value=e.loaded/e.total*100;$('uploadStatus').textContent=`Uploading ${Math.round(e.loaded/e.total*100)}%`;}};
 xhr.onload=()=>{
  uploading=false;
  $('uploadProgress').hidden=true;
  if(xhr.status>=200&&xhr.status<300){notice('Upload complete. Preparing movie tracks…');}
  else{let message='Upload failed.';try{message=JSON.parse(xhr.responseText).detail||message;}catch{}notice(message);$('upload').disabled=false;$('file').disabled=false;}
 };
 xhr.onerror=()=>{uploading=false;notice('Upload connection failed. Please try again.');$('upload').disabled=false;$('file').disabled=false;$('uploadProgress').hidden=true;};
 xhr.send(file);
};
document.addEventListener('visibilitychange',()=>{if(!document.hidden){measureClock();sync(true);scheduleStart();if(enabled)keepAwake();}});
for(const p of [$('video'),$('audio')]){
 p.addEventListener('canplay',()=>{if(p===player())sync();});
 p.addEventListener('seeked',()=>{if(p===player())sync();});
}
for(const p of [$('video'),$('audio')])p.addEventListener('error',()=>{if(p.getAttribute('src'))notice('This media could not be loaded. Check your connection, then switch mode or rejoin.');});
enter().catch(()=>{});
