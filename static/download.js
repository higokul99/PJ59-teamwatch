/* Sequential 1 MiB download-ahead, persisted on disk by the service worker. */
(function(root){
 'use strict';
 let generation=0,available=false,readyPromise;
 function request(data){
  return new Promise((resolve,reject)=>{
   const worker=navigator.serviceWorker.controller;
   if(!worker){reject(Error('Download cache unavailable'));return;}
   const channel=new MessageChannel(),timer=setTimeout(()=>{channel.port1.close();reject(Error('Download timed out'));},40000);
   channel.port1.onmessage=event=>{clearTimeout(timer);channel.port1.close();event.data.ok?resolve(event.data):reject(Error(event.data.error));};
   worker.postMessage(data,[channel.port2]);
  });
 }
 function ready(){
  if(!readyPromise)readyPromise=(async()=>{
   if(!('serviceWorker' in navigator)||!('indexedDB' in root)||!root.isSecureContext)return false;
   try{
    const registration=await navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'});
    const installing=registration.installing||registration.waiting;
    if(installing&&installing.state!=='activated')await new Promise((resolve,reject)=>{
     const timer=setTimeout(()=>finish(Error('Worker update timed out')),5000);
     function finish(error){clearTimeout(timer);installing.removeEventListener('statechange',changed);error?reject(error):resolve();}
     function changed(){if(installing.state==='activated')finish();else if(installing.state==='redundant')finish(Error('Worker update failed'));}
     installing.addEventListener('statechange',changed);changed();
    });
    await Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(Error('Worker timeout')),5000))]);
    if(!navigator.serviceWorker.controller)await new Promise(resolve=>{
     const finish=()=>{navigator.serviceWorker.removeEventListener('controllerchange',finish);resolve();};
     navigator.serviceWorker.addEventListener('controllerchange',finish);setTimeout(finish,3000);
    });
    available=!!navigator.serviceWorker.controller;return available;
   }catch{return false;}
  })();
  return readyPromise;
 }
 function stop(){generation++;}
 async function start(path,onProgress){
  const current=++generation;
  const emit=value=>{if(current===generation)onProgress(value);};
  if(!await ready()){emit({status:'fallback',message:'Download storage unavailable. Using streaming.'});return;}
  if(current!==generation)return;
  try{
   if(path.startsWith('/hls/')){await hlsDownload(path,current,emit);return;}
   const response=await fetch('/api'+path,{cache:'no-store'});
   if(!response.ok)throw Error('Could not read media details');
   const metadata=await response.json();
   if(current!==generation)return;
   await request({type:'prune',id:path.split('/')[2]});
   let completed=0;
   emit({status:'downloading',bytes:0,total:metadata.size});
   for(let index=0;index<Math.ceil(metadata.size/(1024*1024));index++){
    if(current!==generation)return;
    const result=await request({type:'chunk',path,index});
    if(!result.saved){emit({status:'fallback',message:'Device storage is busy, full, or unavailable. Using streaming; retry downloading later.'});return;}
    completed+=result.bytes;
    emit({status:completed>=metadata.size?'complete':'downloading',bytes:completed,total:metadata.size});
    // Leave room for playback's on-demand range requests between prefetches.
    await new Promise(resolve=>setTimeout(resolve,60));
   }
  }catch(error){emit({status:'error',message:`Download paused: ${error.message}. Playback can still stream. Retry download when connected.`});}
 }
 async function playlistTree(path,seen=new Set()){
  if(seen.has(path))return {groups:[],complete:true};
  seen.add(path);
  const response=await fetch(path,{cache:'no-store'});
  if(!response.ok)throw Error('Prepared segments could not be read');
  const text=await response.text(),files=[],children=[];
  function resolve(value){
   const url=new URL(value,new URL(path,location.origin));
   if(url.origin!==location.origin||!url.pathname.startsWith('/hls/'))throw Error('Invalid playlist resource');
   return url.pathname;
  }
  for(const raw of text.split('\n')){
   const line=raw.trim();if(!line)continue;
   if(line.startsWith('#EXT-X-MAP:')){const match=/URI="([^"]+)"/.exec(line);if(match)files.push(resolve(match[1]));}
   else if(line.startsWith('#EXT-X-MEDIA:')){const match=/URI="([^"]+)"/.exec(line);if(match)children.push(resolve(match[1]));}
   else if(!line.startsWith('#')){const resource=resolve(line);resource.endsWith('.m3u8')?children.push(resource):files.push(resource);}
  }
  if(children.length){
   const nested=await Promise.all(children.map(child=>playlistTree(child,seen)));
   return {groups:nested.flatMap(item=>item.groups),complete:nested.every(item=>item.complete)};
  }
  return {groups:[files],complete:text.includes('#EXT-X-ENDLIST')};
 }
 async function hlsDownload(path,current,emit){
  await request({type:'prune',id:path.split('/')[2]});
  const saved=new Set();let bytes=0;
  while(current===generation){
   const tree=await playlistTree(path),ordered=[];
   const count=Math.max(0,...tree.groups.map(group=>group.length));
   // Interleave audio/video segments so both tracks download from the beginning.
   for(let index=0;index<count;index++)for(const group of tree.groups)if(group[index])ordered.push(group[index]);
   for(const resource of ordered){
    if(current!==generation)return;
    if(saved.has(resource))continue;
    const result=await request({type:'file',path:resource});
    if(!result.saved){emit({status:'fallback',message:'Device storage is busy or unavailable. Playback will stream.'});return;}
    saved.add(resource);bytes+=result.bytes;
    emit({status:'downloading',bytes,segments:saved.size,totalSegments:ordered.length,hls:true});
    await new Promise(resolve=>setTimeout(resolve,60));
   }
   if(tree.complete){emit({status:'complete',bytes,segments:saved.size,hls:true});return;}
   emit({status:'waiting',bytes,segments:saved.size,hls:true,message:'Available segments saved. Download continues as more are prepared.'});
   await new Promise(resolve=>setTimeout(resolve,1500));
  }
 }
 async function clear(){stop();if(available)try{await request({type:'clear'});}catch{}}
 root.TeamWatchDownload={ready,start,stop,clear};
})(globalThis);
