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
    await navigator.serviceWorker.register('/sw.js');
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
    if(!result.saved){emit({status:'fallback',message:'Device storage is full or unavailable. Using streaming.'});return;}
    completed+=result.bytes;
    emit({status:completed>=metadata.size?'complete':'downloading',bytes:completed,total:metadata.size});
    // Leave room for playback's on-demand range requests between prefetches.
    await new Promise(resolve=>setTimeout(resolve,60));
   }
  }catch(error){emit({status:'error',message:`Download paused: ${error.message}. Playback can still stream. Retry download when connected.`});}
 }
 async function clear(){stop();if(available)try{await request({type:'clear'});}catch{}}
 root.TeamWatchDownload={ready,start,stop,clear};
})(globalThis);
