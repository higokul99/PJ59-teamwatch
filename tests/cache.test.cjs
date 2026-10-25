const {test}=require('node:test');
const assert=require('node:assert/strict');
const {range,chunkBounds,CHUNK_SIZE}=require('../static/cache-core.js');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
test('range handling supports Safari two-byte probes, open and suffix ranges',()=>{
 assert.deepEqual(range('bytes=0-1',100),{start:0,end:1,status:206});
 assert.deepEqual(range('bytes=10-',100),{start:10,end:99,status:206});
 assert.deepEqual(range('bytes=-8',100),{start:92,end:99,status:206});
 assert.deepEqual(range('bytes=90-200',100),{start:90,end:99,status:206});
 assert.deepEqual(range(null,100),{start:0,end:99,status:200});
 for(const invalid of ['bytes=100-','bytes=8-3','bytes=-0','bytes=-','bytes=0-1,3-4','bytes=1.2-4'])assert.throws(()=>range(invalid,100));
});
test('chunk bounds include the final short chunk without reading beyond EOF',()=>{
 assert.deepEqual(chunkBounds(0,CHUNK_SIZE+3),{start:0,end:CHUNK_SIZE-1});
 assert.deepEqual(chunkBounds(1,CHUNK_SIZE+3),{start:CHUNK_SIZE,end:CHUNK_SIZE+2});
 assert.throws(()=>chunkBounds(2,CHUNK_SIZE+3));
});
function workerHarness(){
 const mediaPath='/media/0123456789abcdef01234567/audio.m4a';
 const bytes=Uint8Array.from({length:CHUNK_SIZE*2+53},(_,i)=>i%251);
 const store=new Map(),network=[];
 let authorized=true;
 const workerFile=fs.readFileSync(path.join(__dirname,'../static/sw.js'),'utf8');
 const core=fs.readFileSync(path.join(__dirname,'../static/cache-core.js'),'utf8');
 const context=vm.createContext({URL,Request,Response,ReadableStream,Uint8Array,ArrayBuffer,AbortController,setTimeout,clearTimeout,testStore:store,
  self:{location:{origin:'https://testserver'},addEventListener(){},clients:{claim(){}},skipWaiting(){}},
  async fetch(input,options={}){
   const url=typeof input==='string'?input:input.url;
   if(!authorized)return new Response('Join first',{status:401});
   if(url.includes('/api/media/'))return Response.json({size:bytes.length,type:'audio/mp4'});
   const header=options.headers?.Range||(typeof input!=='string'?input.headers.get('Range'):null);
   const selected=range(header,bytes.length);network.push(header);
   return new Response(bytes.slice(selected.start,selected.end+1),{status:selected.status,headers:{'Content-Range':`bytes ${selected.start}-${selected.end}/${bytes.length}`}});
  }
 });
 context.importScripts=()=>vm.runInContext(core,context);
 vm.runInContext(workerFile,context);
 vm.runInContext('stored=async key=>testStore.get(key);write=async(key,bytes)=>{testStore.set(key,bytes);};',context);
 return {context,store,bytes,network,path:mediaPath,deny(){authorized=false;},run(code){return vm.runInContext(code,context);},
  async serve(header){context.testRequest=new Request('https://testserver'+mediaPath,{headers:header?{Range:header}:{}});return vm.runInContext('serve(testRequest)',context);}};
}
test('cached media serves exact bytes across chunk boundaries without redownloading',async()=>{
 const h=workerHarness(),start=CHUNK_SIZE-3,end=CHUNK_SIZE+9;
 const response=await h.serve(`bytes=${start}-${end}`);
 assert.equal(response.status,206);
 assert.equal(response.headers.get('Content-Length'),'13');
 assert.deepEqual(new Uint8Array(await response.arrayBuffer()),h.bytes.slice(start,end+1));
 assert.equal(h.network.length,2);
 const again=await h.serve(`bytes=${start}-${end}`);await again.arrayBuffer();
 assert.equal(h.network.length,2);
});
test('complete cached playback can read without further media network requests',async()=>{
 const h=workerHarness();
 const first=await h.serve();assert.deepEqual(new Uint8Array(await first.arrayBuffer()),h.bytes);
 const count=h.network.length;
 const second=await h.serve();assert.deepEqual(new Uint8Array(await second.arrayBuffer()),h.bytes);
 assert.equal(h.network.length,count);
});
test('concurrent prefetch and playback share the same chunk download',async()=>{
 const h=workerHarness();
 const code=`chunk('${h.path}',0,${h.bytes.length})`;
 await Promise.all([h.run(code),h.run(code)]);
 assert.equal(h.network.length,1);
});
test('cached bytes cannot bypass a logged-out session',async()=>{
 const h=workerHarness();await(await h.serve('bytes=0-1')).arrayBuffer();
 h.deny();assert.equal((await h.serve('bytes=0-1')).status,401);
});
test('storage quota failure keeps playback working and tells prefetch to stop',async()=>{
 const h=workerHarness();h.run('write=async()=>{throw Error("QuotaExceededError");};');
 const result=await h.run(`chunk('${h.path}',0,${h.bytes.length})`);
 assert.equal(result.saved,false);
 const response=await h.serve('bytes=0-1');
 assert.deepEqual(new Uint8Array(await response.arrayBuffer()),h.bytes.slice(0,2));
});
