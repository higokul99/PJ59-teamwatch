'use strict';
const rateController=new TeamWatchSync.RateController();
const $ = id => document.getElementById(id);
let role, ws, roomState, media, mediaKey = '', mode = localStorage.getItem('tw-mode') || 'combined';
let enabled = false, clockOffset = 0, clockSamples = [], reconnect, pingTimer, leaving = false, connecting = false, uploading = false;
let startTimer, clockTimers = [], lastSeek = -Infinity, pendingForce = false, playPending = false;
let downloadState={},stallSince=null,stallReported=-1,seekDragging=false,playbackSource='';
let playbackEvents=[],playbackCounts={};
let latestPreparation={};
let adjustment = Number(localStorage.getItem('tw-offset') || 0);
if (!Number.isFinite(adjustment)) adjustment = 0;
adjustment = Math.max(-2000, Math.min(2000, adjustment));
$('offset').value = adjustment;
const monotonicEpoch = Date.now() - performance.now();
const localNow = () => (monotonicEpoch + performance.now()) / 1000;
const serverNow = () => localNow() + clockOffset;
const player = () => mode === 'audio' || (media && !media.has_video) ? $('audio') : $('video');
function bufferedAhead(p){
 try{for(let i=0;i<p.buffered.length;i++)if(p.buffered.start(i)<=p.currentTime&&p.buffered.end(i)>p.currentTime)return p.buffered.end(i)-p.currentTime;}catch{}
 return 0;
}
function playbackReport(){
 const p=player();let frames={};
 try{const quality=$('video').getVideoPlaybackQuality();frames={total:quality.totalVideoFrames,dropped:quality.droppedVideoFrames};}catch{}
 return {version:'smooth-playback-3',mode,browser:navigator.userAgent,playing:roomState?.playing,
  mediaPosition:p.currentTime,targetPosition:targetPosition(),rate:p.playbackRate,readyState:p.readyState,
  bufferedAheadSeconds:Number(bufferedAhead(p).toFixed(2)),download:downloadState.status||'unknown',
  roundTripMs:clockSamples.length?Math.round(clockSamples.at(-1).rtt*1000):null,
  frames,counts:{...playbackCounts},events:playbackEvents.slice()};
}
function recordPlayback(type,p=player(),extra={}){
 if(p!==player())return;
 playbackCounts[type]=(playbackCounts[type]||0)+1;
 playbackEvents.push({at:Math.round(performance.now()),type,position:Number(p.currentTime.toFixed(3)),rate:p.playbackRate,ready:p.readyState,buffered:Number(bufferedAhead(p).toFixed(2)),...extra});
 playbackEvents=playbackEvents.slice(-50);
 $('diagnosticsSummary').textContent=`Buffer events: ${playbackCounts.waiting||0} · Speed changes: ${playbackCounts.ratechange||0} · Seeks: ${playbackCounts.seeking||0}`;
}
$('copyReport').onclick=async()=>{
 const text=JSON.stringify(playbackReport(),null,2);
 $('reportOutput').hidden=false;$('reportOutput').value=text;
 try{await navigator.clipboard.writeText(text);$('reportStatus').textContent='Copied. The report is also shown below; paste it into this chat.';}
 catch{$('reportOutput').hidden=false;$('reportOutput').value=text;$('reportStatus').textContent='Copy the report below.';}
};
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
 $('hostControls').hidden=role!=='host'; $('uploadPanel').hidden=true;
 $('roomLabel').textContent=`ROOM ${data.room} · ${role.toUpperCase()}`;
 if(globalThis.TeamWatchDownload)await TeamWatchDownload.ready();
 receiveState(data); openSocket();
}
function openSocket(){
 clearInterval(pingTimer); clearTimeout(reconnect);
 ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
 ws.onopen=()=>{if(globalThis.TeamWatchLibrary)TeamWatchLibrary.connection(true);clockSamples=[]; measureClock(); pingTimer=setInterval(ping,2000);};
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
  if(globalThis.TeamWatchLibrary)TeamWatchLibrary.connection(false);
  clearInterval(pingTimer); clearTimeout(startTimer); clockTimers.forEach(clearTimeout); $('connection').textContent='Disconnected from room';
  $('video').pause(); $('audio').pause();
  if(leaving)return;
  if(e.code===1008){notice('Your session ended. Leave the room and join again.');return;}
  notice('Connection lost. Reconnecting; playback will catch up.'); reconnect=setTimeout(openSocket,2000);
 };
 ws.onerror=()=>ws.close();
}
function ping(){if(ws?.readyState===WebSocket.OPEN){reportStatus();ws.send(JSON.stringify({type:'ping',sent:localNow()}));}}
function reportStatus(){
 if(ws?.readyState!==WebSocket.OPEN||!media)return;
 const p=player();
 ws.send(JSON.stringify({type:'status',media_id:media.id,episode_id:media.episode_id,selection_revision:roomState?.selection_revision,revision:roomState?.revision,active:enabled,ready:enabled&&!p.seeking&&p.readyState>=3,mode,drift:roomState?targetPosition()-p.currentTime:null,downloaded:downloadState.status==='complete'}));
}
function downloadTrack(){
 if(!media||!globalThis.TeamWatchDownload)return;
 const path=playbackSource||player().getAttribute('src');
 if(!path)return;
 TeamWatchDownload.start(path,state=>{
  const justFinished=state.status==='complete'&&downloadState.status!=='complete';
  downloadState={...downloadState,...state};
  if(justFinished)recordPlayback('download-complete');
  renderDownload();
  reportStatus();
 });
}
function renderDownload(){
 const state=downloadState;
 if(!state.status)return;
 if(state.hls){
  $('downloadProgress').value=state.status==='complete'&&media?.complete?100:Math.min(99,Number(media?.available_duration||0)/Number(media?.duration||1)*100);
  $('downloadStatus').textContent=state.status==='complete'?(media?.complete?'Fully downloaded on this device. Playback uses saved segments.':'All available segments saved; the rest is not prepared yet.'):
   `${state.message||'Downloading prepared segments.'} · ${state.segments||0} files · ${((state.bytes||0)/1048576).toFixed(1)} MB saved`;
 }else{
  const progress=state.total?state.bytes/state.total*100:0;
  $('downloadProgress').value=progress;
  $('downloadStatus').textContent=state.status==='complete'?'Fully downloaded on this device. Playback uses the saved track.':state.status==='downloading'?`Downloading ${Math.floor(progress)}% · ${(state.bytes/1048576).toFixed(1)} / ${(state.total/1048576).toFixed(1)} MB`:state.message;
 }
}
function seekLimit(){return media?Math.min(media.duration,media.available_duration??media.duration):0;}
function renderPreparation(preparation){
 latestPreparation=preparation;
 renderHostPreparation();
 const visible=typeof preparation.percent==='number'||(media?.format==='hls')||['processing','uploading'].includes(preparation.status);
 $('preparePanel').hidden=!visible;
 if(!visible)return;
 const contextMedia=preparation.media_id&&preparation.media_id!==media?.id?null:media;
 const percent=Number.isFinite(preparation.percent)?preparation.percent:(preparation.status==='ready'&&contextMedia?.complete?100:null);
 if(percent===null){$('prepareProgress').removeAttribute('value');$('preparePercent').textContent='Working…';}
 else{$('prepareProgress').value=percent;$('preparePercent').textContent=`${percent.toFixed(1)}%`;}
 $('prepareHeading').textContent=preparation.status==='error'?'Preparation stopped':preparation.status==='uploading'?'Uploading movie':preparation.status==='ready'?'Movie ready':preparation.playable?'Ready to play · preparing the rest':'Preparing the first segments';
 const prepared=preparation.prepared_seconds??contextMedia?.available_duration??0;
 const total=preparation.total_seconds??contextMedia?.duration??0;
 const speed=preparation.speed?` · ${preparation.speed.toFixed(1)}× preparation speed`:'';
 $('prepareDetail').textContent=`${preparation.message}${total?` Prepared ${fmt(prepared)} of ${fmt(total)}.`:''}${speed}`;
 $('prepareHint').textContent=preparation.status==='error'?'Preparation stopped. Only the prepared portion is available; upload again to finish.':preparation.status==='ready'&&contextMedia?.complete?'The entire movie is ready. You can seek anywhere.':preparation.playable?`Play now${preparation.startup_seconds?` · first segments ready after ${preparation.startup_seconds.toFixed(1)} seconds`:''}. Available positions extend as background preparation continues.`:'Playback becomes available after the first few complete segments, without waiting for the whole movie.';
}
function preparationTime(seconds){
 const value=Math.max(0,Math.floor(Number(seconds)||0));
 return [Math.floor(value/3600),Math.floor(value/60)%60,value%60].map(n=>String(n).padStart(2,'0')).join(':');
}
function renderHostPreparation(){
 const preparation=latestPreparation;
 const current=preparation.media_id&&preparation.media_id!==media?.id?null:media;
 const total=Number(preparation.total_seconds??current?.duration??0);
 const complete=!!current?.complete;
 const prepared=Math.max(0,Math.min(total,complete?total:Number(preparation.prepared_seconds??current?.available_duration??0)));
 const activePosition=current&&roomState?TeamWatchSync.target(roomState,total,serverNow(),0):0;
 const ahead=Math.max(0,prepared-activePosition);
 $('hostPreparation').hidden=role!=='host'||!total;
 if(role!=='host'||!total)return;
 $('preparedThrough').textContent=preparationTime(prepared)+' / '+preparationTime(total);
 $('preparationRemaining').textContent=preparationTime(total-prepared);
 $('preparedAhead').textContent=current?preparationTime(ahead):'Next movie';
 const stopped=preparation.status==='error';
 const nearEdge=!complete&&!!current&&ahead<=30;
 $('hostPreparation').classList.toggle('prepared-complete',complete);
 $('hostPreparation').classList.toggle('preparation-warning',stopped||nearEdge);
 let advice;
 if(complete)advice='Fully prepared — the entire movie is ready. Tell participants they can connect, then check device readiness before starting.';
 else if(stopped)advice=`Preparation stopped at ${preparationTime(prepared)}. Upload again to prepare the rest of the movie.`;
 else if(!prepared)advice='No playable portion is prepared yet. Wait for the first segments, or wait for Fully prepared before starting the screening.';
 else advice=`Prepared from the start through ${preparationTime(prepared)}. Beyond this point, playback may pause until processing catches up.`;
 if(nearEdge&&!stopped&&prepared)advice+=' Playback is within 30 seconds of the prepared limit. Pause and wait, or wait for Fully prepared.';
 if($('preparationAdvice').textContent!==advice)$('preparationAdvice').textContent=advice;
}
$('retryDownload').onclick=downloadTrack;
$('clearDownloads').onclick=async()=>{if(globalThis.TeamWatchDownload)await TeamWatchDownload.clear();downloadState={};$('downloadProgress').value=0;$('downloadStatus').textContent='Device downloads cleared. Playback can stream; tap Retry download to save again.';reportStatus();};

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
 if(globalThis.TeamWatchLibrary)TeamWatchLibrary.update(data.library,role==='host',ws?.readyState===WebSocket.OPEN);
 if(!clockSamples.length)clockOffset=data.server_time-localNow();
 const changed=roomState?.revision!==data.timeline.revision;
 roomState=data.timeline; media=data.media;
 if(changed){pendingForce=true;stallSince=null;recordPlayback('room-state',player(),{revision:roomState.revision,playing:roomState.playing});}
 const roomCount=Number(data.count)||0;
 $('connection').textContent=`${roomCount} device${roomCount===1?'':'s'} connected to room`;
 const devices=(data.participants||[]).filter(p=>p.active);
 $('readiness').textContent=`${devices.filter(p=>p.ready).length}/${devices.length} playback devices ready`;
 $('movieName').textContent=media?.name || 'Your shared cinema';
 if(!uploading)$('uploadStatus').textContent=data.processing.message;
 const busy=uploading||['uploading','processing','deleting'].includes(data.processing.status);
 if(!globalThis.TeamWatchLibrary){$('upload').disabled=busy; $('file').disabled=busy;}
 $('deleteMedia').disabled=uploading||(busy&&!data.processing.playable)||!media;
 $('currentMedia').textContent=media?`Current media: ${media.name}`:'No media in this room.';
 if(!globalThis.TeamWatchLibrary)$('upload').textContent=media?'Upload & replace':'Upload & prepare';
 $('play').disabled=$('pause').disabled=$('restart').disabled=$('seek').disabled=$('syncAll').disabled=$('back10').disabled=$('forward10').disabled=$('jumpTime').disabled=$('jumpButton').disabled=!media;
 if(media){$('seek').max=seekLimit();}
 renderPreparation(data.processing);renderDownload();
 notice(data.processing.status==='error'||busy?data.processing.message:(data.timeline.reason||data.processing.message));
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
 if(enabled&&roomState?.playing)command('pause');
 if(globalThis.TeamWatchDownload)TeamWatchDownload.stop();
 if(globalThis.TeamWatchPlayer)TeamWatchPlayer.destroy();
 playbackSource='';
 rateController.reset();playbackEvents=[];playbackCounts={};
 mediaKey=key; enabled=false; stallSince=null;downloadState={};reportStatus(); playPending=false; pendingForce=true; lastSeek=-Infinity; clearTimeout(startTimer);
 for(const el of [$('video'),$('audio')]){el.pause();el.removeAttribute('src');el.load();}
 $('resync').disabled=!media; $('retryDownload').disabled=!media;
 $('connect').disabled=!media; $('connect').textContent='Connect playback';
 $('connectHint').textContent='Tap to enable playback on this device.';
 $('volume').disabled=mode==='video';
 $('placeholder').hidden=!!media&&mode!=='audio';
 $('video').hidden=!media||mode==='audio';
 $('fullscreen').hidden=!media||mode==='audio';
 if(!media){
  if(globalThis.TeamWatchDownload)TeamWatchDownload.clear();
  $('screenTitle').textContent='The room is ready.';$('screenText').textContent='Your host will upload a movie or song.';
  $('time').textContent='00:00 / 00:00';$('syncStatus').textContent='Waiting for media';
  $('seek').value=0;$('seekPreview').textContent='00:00';$('jumpError').textContent='';
  $('downloadProgress').value=0;$('downloadStatus').textContent='No media to download.';
 }
 if(media){
  const p=player(); p.muted=mode==='video';
  playbackSource=media.format==='hls'?`/hls/${media.id}/${mode==='audio'?'audio.m3u8':mode==='video'?'video.m3u8':'master.m3u8'}`:`/media/${media.id}/${mode==='audio'?'audio.m4a':mode==='video'?'video.mp4':'combined.mp4'}`;
  if(globalThis.TeamWatchPlayer){
   const supported=TeamWatchPlayer.attach(p,playbackSource,message=>{notice(message);if(enabled&&roomState?.playing)command('pause');enabled=false;reportStatus();});
   if(!supported){$('connect').disabled=true;return;}
  }else{p.src=playbackSource;p.load();}
  downloadTrack(); $('screenTitle').textContent='Just you and the sound.';
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
  await p.play(); enabled=true; connecting=false; sync(); reportStatus(); scheduleStart(); await keepAwake();
  $('connect').textContent='Playback connected ✓';
  $('connectHint').textContent='Keep this page visible for the best synchronization.';
 }catch(e){enabled=false;notice(`Playback could not start: ${e.message||'wait for buffering and try again.'}`);}
 finally{connecting=false;sync();}
};
function targetPosition(){
 if(!roomState||!media)return 0;
 return TeamWatchSync.target(roomState,media.duration,serverNow(),adjustment);
}
function sync(force=false){
 renderHostPreparation();
 if(force)pendingForce=true;
 if(!media||!roomState)return;
 const p=player(), target=targetPosition();
 $('time').textContent=`${fmt(target)} / ${fmt(media.duration)}`;
 if(!seekDragging){$('seek').value=Math.min(target,seekLimit());$('seekPreview').textContent=fmt(target);}
 $('seek').setAttribute('aria-valuetext',fmt(Number($('seek').value))+' of '+fmt(media.duration));
 if(!enabled||connecting){$('syncStatus').textContent='Tap Connect playback';return;}
 if(ws?.readyState!==WebSocket.OPEN){p.pause();return;}
 const playing=roomState.playing&&serverNow()>=roomState.anchor&&target<media.duration;
 monitorStall(p,playing);
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
 let desiredRate=1;
 if(playing&&!decision.seek&&p.readyState>=3)desiredRate=rateController.update(decision.drift,performance.now()/1000);
 else rateController.reset();
 if(Math.abs(p.playbackRate-desiredRate)>.005)p.playbackRate=desiredRate;
 if(playing&&p.paused&&!playPending){
  playPending=true;
  const key=mediaKey;
  p.play().catch(()=>{
   // pause() during a room command aborts a pending play promise on Safari.
   // That expected cancellation must not disable this device or pause again.
   if(key!==mediaKey||!roomState?.playing||serverNow()<roomState.anchor)return;
   command('pause');enabled=false;reportStatus();$('connect').textContent='Reconnect playback';notice('Your browser paused playback. Tap Connect playback to resume.');
  }).finally(()=>{if(key===mediaKey)playPending=false;});
 }
 const ms=Math.round(Math.abs(decision.drift)*1000);
 $('syncStatus').textContent=!roomState.playing?'Room paused':serverNow()<roomState.anchor?'Starting together…':ms<=30?'Following host · aligned':`Following host · ${ms} ms ${decision.drift>0?'behind':'ahead'}`;
}
// The deadline timer starts playback at the anchor instead of waiting up to
// 200 ms for the next periodic check. This interval handles ongoing drift.
setInterval(sync,100);
$('resync').onclick=()=>{recordPlayback('local-resync');measureClock();pendingForce=true;sync();scheduleStart();};
function monitorStall(p,playing){
 const now=performance.now()/1000;
 if(!playing||connecting||p.seeking||now-lastSeek<1.5||serverNow()-roomState.anchor<1){stallSince=null;return;}
 if(p.readyState>=3){stallSince=null;return;}
 if(stallSince===null)stallSince=now;
 if(now-stallSince>=1&&stallReported!==roomState.revision){
  stallReported=roomState.revision;
  recordPlayback('room-buffering-pause');
  command('buffering',{revision:roomState.revision});
 }
}
function command(action,extra={}){
 if(ws?.readyState!==WebSocket.OPEN){notice('Wait for the room connection.');return;}
 recordPlayback('command:'+action);
 if(action==='play')reportStatus();
 ws.send(JSON.stringify({type:'control',action,episode_id:media?.episode_id,selection_revision:roomState?.selection_revision,revision:roomState?.revision,...extra}));
}
$('play').onclick=()=>command('play'); $('pause').onclick=()=>command('pause');
$('syncAll').onclick=()=>command('sync');
$('restart').onclick=()=>command('restart');
$('back10').onclick=()=>command('skip',{seconds:-10});
$('forward10').onclick=()=>command('skip',{seconds:10});
$('seek').oninput=()=>{seekDragging=true;$('seekPreview').textContent=fmt(Number($('seek').value));};
$('seek').onchange=()=>{command('seek',{position:Number($('seek').value)});seekDragging=false;};
$('seek').onblur=()=>{seekDragging=false;};
$('jumpForm').onsubmit=event=>{
 event.preventDefault();
 const seconds=TeamWatchSync.parseTimestamp($('jumpTime').value);
 $('jumpError').textContent='';
 if(seconds===null){$('jumpError').textContent='Enter a time such as 01:23 or 01:02:03.';return;}
 if(!media){$('jumpError').textContent='Upload a movie first.';return;}
 if(seconds>seekLimit()){$('jumpError').textContent=`Choose a time between 00:00 and ${fmt(seekLimit())}${media.complete===false?' (prepared so far)':''}.`;return;}
 command('seek',{position:seconds});
};
$('offset').onchange=()=>{adjustment=Math.max(-2000,Math.min(2000,Number($('offset').value)||0));$('offset').value=adjustment;localStorage.setItem('tw-offset',adjustment);sync(true);};
$('volume').oninput=()=>{for(const p of [$('video'),$('audio')])p.volume=Number($('volume').value);$('volumeValue').textContent=`${Math.round(Number($('volume').value)*100)}%`;};
$('fullscreen').onclick=async()=>{try{if($('video').webkitEnterFullscreen&&!$('video').requestFullscreen)$('video').webkitEnterFullscreen();else await $('video').requestFullscreen();}catch{notice('Full screen is not supported on this browser.');}};
$('logout').onclick=async()=>{try{await api('/api/logout',{});if(globalThis.TeamWatchDownload)await TeamWatchDownload.clear();leaving=true;ws?.close();location.reload();}catch(e){notice(e.message);}};
$('deleteMedia').onclick=async()=>{
 if(!media||uploading)return;
 if(!confirm('Delete current media for everyone? This clears playback and removes the server files.'))return;
 $('deleteMedia').disabled=true;
 try{
  const response=await fetch('/api/media',{method:'DELETE'});
  const data=await response.json();
  if(!response.ok)throw Error(data.detail||'Could not delete media.');
  if(!roomState||data.timeline.revision>=roomState.revision)receiveState(data);
 }catch(error){notice(error.message);$('uploadStatus').textContent=error.message;$('deleteMedia').disabled=!media;}
};
document.addEventListener('visibilitychange',()=>{if(!document.hidden){measureClock();sync(true);scheduleStart();if(enabled)keepAwake();}});
for(const p of [$('video'),$('audio')]){
 for(const event of ['waiting','stalled','seeking','seeked','ratechange','playing','pause','error'])p.addEventListener(event,()=>recordPlayback(event,p));
 p.addEventListener('canplay',()=>{if(p===player()){sync();reportStatus();}});
 p.addEventListener('seeked',()=>{if(p===player()){sync();reportStatus();}});
 p.addEventListener('pause',()=>{
  if(p===player()&&enabled&&!connecting&&roomState?.playing&&serverNow()>=roomState.anchor&&ws?.readyState===WebSocket.OPEN&&!p.seeking&&performance.now()/1000-lastSeek>1.5)command('pause');
 });
 p.addEventListener('ended',()=>{if(p===player()&&enabled&&roomState?.playing)command('pause');});
}
for(const p of [$('video'),$('audio')])p.addEventListener('error',()=>{if(p===player()&&enabled&&roomState?.playing)command('pause');if(p.getAttribute('src'))notice('This media could not be loaded. Check your connection, then switch mode or rejoin.');});
enter().catch(()=>{});
