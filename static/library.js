/* Room library UI. Shared by hosts/viewers; permissions are still enforced by the API. */
(function(root){
 'use strict';
 const $=id=>document.getElementById(id);
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const stamp=v=>{v=Math.max(0,Math.floor(v||0));return [Math.floor(v/3600),Math.floor(v/60)%60,v%60].map(n=>String(n).padStart(2,'0')).join(':');};
 const preparedPercent=e=>e.duration>0?Math.max(0,Math.min(100,(e.prepared_seconds||0)/e.duration*100)):0;
 const bytes=v=>(v/1073741824).toFixed(2)+' GB';
 let state={episodes:[]},host=false,online=false,lastHTML='',queue=[],transferring=false,submitAction;
 const names={uploading:'Uploading',queued:'Queued',preparing:'Preparing',partial:'Partly ready',ready:'Fully ready',failed:'Preparation stopped',deleting:'Deleting',cleanup_pending:'Cleanup pending'};
 async function api(path,method='GET',body){
  const response=await fetch('/api/episodes'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Could not update the library.');return result;
 }
 function error(message){$('libraryMessage').textContent=message;}
 function next(){const i=state.episodes.findIndex(e=>e.id===state.active_episode_id);return i<0?null:state.episodes[i+1];}
 function render(){
  $('libraryHostTools').hidden=!host;$('libraryUpload').hidden=!host;
  $('libraryConnection').textContent=online?'Live library':'Reconnecting — actions unavailable';
  const storage=state.storage;if(storage)$('libraryStorage').textContent=`Room: ${bytes(storage.used_bytes)} / ${bytes(storage.room_limit_bytes)} · Server: ${bytes(storage.server_used_bytes)} / ${bytes(storage.server_limit_bytes)} · Per-file limit: ${bytes(storage.file_limit_bytes)}`;
  const nextEpisode=next();$('nextEpisode').disabled=!online||!nextEpisode?.playable;
  $('nextHint').textContent=!state.active_episode_id?'Select an episode to start.':!nextEpisode?'End of series':nextEpisode.playable?`Next: ${nextEpisode.title}`:`Next episode is ${names[nextEpisode.status]?.toLowerCase()||'not ready'}.`;
  $('nextEpisode').dataset.disabledReason=!online?'Reconnect to the room first.':!state.active_episode_id?'Select an episode first.':!nextEpisode?'You have reached the last episode.':'The next episode is not playable yet. Wait for preparation or retry it if it failed.';
  $('clearLibrary').dataset.disabledReason=!online?'Reconnect to the room first.':transferring?'Wait for the current uploads to finish.':'The library is empty.';
  $('clearLibrary').disabled=!online||!state.episodes.length||transferring;
  const action=(name,id,label,disabled=false)=>`<button type="button" data-episode-action="${name}" data-id="${id}" ${!online||disabled?'disabled':''} data-disabled-reason="${esc(!online?'Reconnect to the room first.':name==='select'?(label==='Selected'?'This episode is already selected.':'This episode is not playable yet. Wait for preparation or retry it if it failed.'):name==='up'?'This episode is already first.':name==='down'?'This episode is already last.':'Please wait for the current operation.')}">${label}</button>`;
  const html=state.episodes.map((e,i)=>`<article class="episode-card ${e.active?'episode-active':''}"><div class="episode-heading"><h3>${i+1}. ${esc(e.title)}</h3><span>${e.active?'● Selected · ':''}${esc(names[e.status]||e.status)}</span></div><p>Prepared through ${stamp(e.prepared_seconds)} / ${stamp(e.duration)} · ${preparedPercent(e).toFixed(1)}%</p><progress max="100" value="${preparedPercent(e)}" aria-label="Preparation for ${esc(e.title)}"></progress>${e.status==='partial'?'<small>Playback may pause beyond the prepared portion.</small>':''}${e.status==='failed'?`<p class="error">Preparation stopped. ${e.playable?'Only the prepared portion is available. ':''}${e.retryable?'Retry preparation to prepare the whole episode.':'Upload the episode again to prepare it.'}</p>`:e.error?`<p class="error">${esc(e.error)}</p>`:''}${e.status==='ready'?'<small>Fully prepared — ready to watch.</small>':''}${host?`<div class="episode-actions">${action('select',e.id,e.active?'Selected':'Select episode',!e.playable||e.active)}${action('rename',e.id,'Rename')}${action('up',e.id,'Move up',i===0)}${action('down',e.id,'Move down',i===state.episodes.length-1)}${e.retryable?action('retry',e.id,'Retry preparation'):''}${action('delete',e.id,e.status==='cleanup_pending'?'Retry deletion':'Delete')}</div>`:''}</article>`).join('')||`<p class="muted">${host?'Add episodes to build this room’s series.':'Your host has not added an episode yet.'}</p>`;
  if(html!==lastHTML){
   const focused=document.activeElement?.closest('[data-episode-action]');const key=focused?{id:focused.dataset.id,action:focused.dataset.episodeAction}:null;
   $('episodeList').innerHTML=html;lastHTML=html;
   if(key){const target=$('episodeList').querySelector(`[data-id="${key.id}"][data-episode-action="${key.action}"]`);if(target&&!target.disabled)target.focus({preventScroll:true});}
  }
 }
 function update(value,isHost,isOnline){state=value||{episodes:[]};host=isHost;online=isOnline;render();}
 async function refresh(){state=await api('');render();}
 function open(title,message,action,{rename=false,typed=false,value=''}={}){
  $('episodeDialogTitle').textContent=title;$('episodeDialogMessage').textContent=message;
  $('episodeTitleLabel').hidden=!rename;$('episodeTitleInput').required=rename;$('episodeTitleInput').value=value;
  $('episodeConfirmLabel').hidden=!typed;$('episodeConfirmInput').value='';$('episodeDialogError').textContent='';
  $('episodeDialogSubmit').disabled=typed;submitAction=action;$('episodeDialog').showModal();
 }
 function select(e){open('Switch episode',`Switch to “${e.title}”? Playback will pause and restart at 00:00 for everyone. Participants stay in this room.`,()=>api('/'+e.id+'/select','POST'));}
 $('episodeConfirmInput').oninput=()=>{$('episodeDialogSubmit').disabled=$('episodeConfirmInput').value!=='CONFIRM';};
 $('episodeDialogCancel').onclick=()=>$('episodeDialog').close();
 $('episodeDialogForm').onsubmit=async ev=>{ev.preventDefault();$('episodeDialogSubmit').disabled=true;try{if(!online)throw Error('Reconnect before changing the library.');await submitAction();$('episodeDialog').close();await refresh();error('Library updated.');}catch(e){$('episodeDialogError').textContent=e.message;}finally{$('episodeDialogSubmit').disabled=!$('episodeConfirmLabel').hidden&&$('episodeConfirmInput').value!=='CONFIRM';}};
 $('episodeList').onclick=async ev=>{const button=ev.target.closest('[data-episode-action]');if(!button||button.disabled)return;const e=state.episodes.find(e=>e.id===button.dataset.id);if(!e)return;
  const action=button.dataset.episodeAction;
  if(action==='select')select(e);
  if(action==='rename')open('Rename episode','Choose a title for this episode.',()=>api('/'+e.id,'PATCH',{title:$('episodeTitleInput').value.trim()}),{rename:true,value:e.title});
  if(action==='retry')open('Retry preparation',e.active?'This pauses playback and clears the selected episode. Select it again once playable.':'The incomplete output will be regenerated. Other episodes keep playing.',()=>api('/'+e.id+'/retry','POST'));
  if(action==='delete')open('Delete episode',`Permanently delete “${e.title}”? ${e.active?'Playback will stop for everyone. ':''}This cannot be undone.`,()=>api('/'+e.id,'DELETE'));
  if(action==='up'||action==='down'){const ids=state.episodes.map(e=>e.id),i=ids.indexOf(e.id),j=i+(action==='up'?-1:1);[ids[i],ids[j]]=[ids[j],ids[i]];try{await api('/order','PUT',{ids});await refresh();}catch(e){error(e.message);}}
 };
 $('nextEpisode').onclick=()=>{const e=next();if(e?.playable)select(e);};
 $('clearLibrary').onclick=()=>open('Delete entire library','All episodes will be removed permanently and playback will stop. The room and accounts remain intact.',()=>api('','DELETE',{confirmation:$('episodeConfirmInput').value}),{typed:true});
 function renderQueue(){
  $('uploadQueue').innerHTML=queue.map((item,i)=>`<div class="upload-queue-row"><input aria-label="Title for upload ${i+1}" data-queue-title="${i}" value="${esc(item.title)}" maxlength="200" ${item.status!=='Waiting'?'disabled':''}><span>${esc(item.file.name)} · ${esc(item.status)}</span>${item.status==='Waiting'?`<button type="button" data-queue-up="${i}" ${i===0?'disabled':''}>Move up</button>`:''}${item.failed?`<button type="button" data-upload-retry="${i}">Retry upload</button>`:''}</div>`).join('');
  $('upload').dataset.disabledReason=transferring?'Uploads are already running. Wait for them to finish.':!online?'Reconnect to the room before uploading.':'Choose files to upload, or retry a failed upload.';
  $('upload').disabled=transferring||!online||!queue.some(e=>e.status==='Waiting');$('file').disabled=transferring;
 }
 $('file').onchange=()=>{if(transferring)return;queue=Array.from($('file').files).map(file=>({file,title:file.name,status:'Waiting'}));renderQueue();};
 $('uploadQueue').onchange=ev=>{if(ev.target.dataset.queueTitle!==undefined)queue[Number(ev.target.dataset.queueTitle)].title=ev.target.value||queue[Number(ev.target.dataset.queueTitle)].file.name;};
 $('uploadQueue').onclick=ev=>{if(transferring)return;const button=ev.target.closest('button');if(!button)return;if(button.dataset.queueUp!==undefined){const i=Number(button.dataset.queueUp);if(i>0)[queue[i-1],queue[i]]=[queue[i],queue[i-1]];}else if(button.dataset.uploadRetry!==undefined){const item=queue[Number(button.dataset.uploadRetry)];item.status='Waiting';item.failed=false;}renderQueue();};
 function transfer(item){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/episodes?name='+encodeURIComponent(item.title));xhr.upload.onprogress=e=>{item.status=e.lengthComputable?'Uploading '+Math.round(e.loaded/e.total*100)+'%':'Uploading';renderQueue();};xhr.onload=()=>{if(xhr.status>=200&&xhr.status<300)resolve();else{let message='Upload failed';try{message=JSON.parse(xhr.responseText).detail||message;}catch{}reject(Error(message));}};xhr.onerror=()=>reject(Error('Connection interrupted. Retry this upload.'));xhr.send(item.file);});}
 $('upload').onclick=async()=>{transferring=true;renderQueue();for(const item of queue){if(item.status!=='Waiting')continue;item.status='Uploading';renderQueue();try{await transfer(item);item.status='Uploaded — queued for preparation';}catch(e){item.status=e.message;item.failed=true;}renderQueue();}transferring=false;renderQueue();refresh().catch(e=>error(e.message));};
 root.TeamWatchLibrary={update,connection(value){online=value;render();renderQueue();}};
})(globalThis);
