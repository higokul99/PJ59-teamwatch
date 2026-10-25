/* Disk-backed media ranges. The page drives prefetch one short request at a time,
   avoiding an hours-long service worker job on mobile browsers. */
'use strict';
importScripts('/static/cache-core.js');
const {CHUNK_SIZE,range,chunkBounds}=TeamWatchCache;
const inflight=new Map();
let database,epoch=0;
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
function db(){
 if(!database)database=new Promise((resolve,reject)=>{
  const request=indexedDB.open('teamwatch-media-v1',1);
  request.onupgradeneeded=()=>request.result.createObjectStore('chunks');
  request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
 });
 return database;
}
async function stored(key){
 const connection=await db();
 return new Promise((resolve,reject)=>{
  const transaction=connection.transaction('chunks','readonly');
  const request=transaction.objectStore('chunks').get(key);
  request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
 });
}
async function write(key,bytes){
 const connection=await db();
 return new Promise((resolve,reject)=>{
  const transaction=connection.transaction('chunks','readwrite');
  transaction.objectStore('chunks').put(bytes,key);
  transaction.oncomplete=()=>resolve();transaction.onerror=transaction.onabort=()=>reject(transaction.error||Error('Storage unavailable'));
 });
}
async function prune(mediaId){
 const connection=await db();
 return new Promise((resolve,reject)=>{
  const transaction=connection.transaction('chunks','readwrite');
  const request=transaction.objectStore('chunks').openCursor();
  request.onsuccess=()=>{
   const cursor=request.result;if(!cursor)return;
   if(!mediaId||!String(cursor.key).startsWith(`/media/${mediaId}/`))cursor.delete();
   cursor.continue();
  };
  transaction.oncomplete=()=>resolve();transaction.onabort=transaction.onerror=()=>reject(transaction.error);
 });
}
function mediaPath(raw){
 const url=new URL(raw,self.location.origin);
 if(url.origin!==self.location.origin||!/^\/media\/[a-f0-9]{24}\/(audio\.m4a|video\.mp4|combined\.mp4)$/.test(url.pathname))throw Error('Invalid media path');
 return url.pathname;
}
async function info(path){
 // Authorization and active-media validation still happen on the server, even
 // for cached files. This cache does not grant offline room access.
 const response=await fetch('/api'+path,{cache:'no-store',credentials:'same-origin'});
 if(!response.ok)throw Error(`Media access failed (${response.status})`);
 return response.json();
}
async function chunk(path,index,total){
 const key=`${path}#${index}`;
 if(inflight.has(key))return inflight.get(key);
 const promise=(async()=>{
  const generation=epoch;
  try{const cached=await stored(key);if(cached)return {bytes:cached,saved:true};}catch{}
  const {start,end}=chunkBounds(index,total),controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),30000);
  let bytes;
  try{
   const response=await fetch(path,{headers:{Range:`bytes=${start}-${end}`},credentials:'same-origin',cache:'no-store',signal:controller.signal});
   if(response.status!==206||response.headers.get('Content-Range')!==`bytes ${start}-${end}/${total}`)throw Error('Invalid chunk response');
   bytes=await response.arrayBuffer();
   if(bytes.byteLength!==end-start+1)throw Error('Incomplete chunk');
  }finally{clearTimeout(timer);}
  if(generation!==epoch)throw Error('Download was cleared');
  try{await write(key,bytes);return {bytes,saved:true};}catch{return {bytes,saved:false};}
 })();
 inflight.set(key,promise);
 try{return await promise;}finally{if(inflight.get(key)===promise)inflight.delete(key);}
}
async function serve(request){
 const path=mediaPath(request.url);
 let metadata;
 try{metadata=await info(path);}catch{return fetch(request);}
 let selected;
 try{selected=range(request.headers.get('Range'),metadata.size);}catch{return new Response(null,{status:416,headers:{'Content-Range':`bytes */${metadata.size}`}});}
 let offset=selected.start,cancelled=false;
 const body=new ReadableStream({
  async pull(controller){
   if(cancelled)return;
   if(offset>selected.end){controller.close();return;}
   try{
    const index=Math.floor(offset/CHUNK_SIZE);
    const {bytes}=await chunk(path,index,metadata.size);
    if(cancelled)return;
    const base=index*CHUNK_SIZE,limit=Math.min(selected.end+1,base+bytes.byteLength);
    controller.enqueue(new Uint8Array(bytes,offset-base,limit-offset));offset=limit;
   }catch(error){controller.error(error);}
  },cancel(){cancelled=true;}
 });
 const headers={'Content-Type':metadata.type,'Content-Length':String(selected.end-selected.start+1),'Accept-Ranges':'bytes','Cache-Control':'no-store'};
 if(selected.status===206)headers['Content-Range']=`bytes ${selected.start}-${selected.end}/${metadata.size}`;
 return new Response(body,{status:selected.status,headers});
}
self.addEventListener('fetch',event=>{
 if(event.request.method!=='GET')return;
 try{mediaPath(event.request.url);}catch{return;}
 event.respondWith(serve(event.request));
});
self.addEventListener('message',event=>{
 const port=event.ports[0];if(!port)return;
 event.waitUntil((async()=>{
  try{
   const data=event.data;
   if(data.type==='clear'){
    epoch++;await prune(null);port.postMessage({ok:true});return;
   }
   if(data.type==='prune'){
    if(!/^[a-f0-9]{24}$/.test(data.id))throw Error('Invalid media');
    await prune(data.id);port.postMessage({ok:true});return;
   }
   if(data.type!=='chunk')throw Error('Invalid cache command');
   const path=mediaPath(data.path),metadata=await info(path);
   const result=await chunk(path,data.index,metadata.size);
   port.postMessage({ok:true,saved:result.saved,size:metadata.size,bytes:result.bytes.byteLength});
  }catch(error){port.postMessage({ok:false,error:error.message});}
 })());
});
