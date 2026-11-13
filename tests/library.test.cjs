const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function harness(){
 const nodes=new Map(),requests=[];
 function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,value:'',innerHTML:'',textContent:'',files:[],querySelector(){return null;},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(id);}
 class XMLHttpRequest{
  constructor(){this.upload={};}
  open(method,url){this.url=url;}
  send(file){requests.push({file,url:this.url});this.status=201;this.onload();}
 }
 const context=vm.createContext({document:{getElementById:node,activeElement:null},XMLHttpRequest,
  fetch:async()=>({ok:true,json:async()=>({episodes:[]})}),console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/library.js'),'utf8'),context);
 return {api:context.TeamWatchLibrary,node,requests};
}
test('next episode requires playable content and a live connection',()=>{
 const h=harness();const state={active_episode_id:'first',episodes:[{id:'first',title:'Pilot',active:true,status:'ready'},{id:'second',title:'Second',status:'queued',playable:false}]};
 h.api.update(state,true,true);assert.equal(h.node('nextEpisode').disabled,true);assert.match(h.node('nextHint').textContent,/queued/);
 state.episodes[1].playable=true;state.episodes[1].status='partial';h.api.update(state,true,true);assert.equal(h.node('nextEpisode').disabled,false);
 h.api.connection(false);assert.equal(h.node('nextEpisode').disabled,true);
});
test('library escapes titles and hides mutation tools for participants',()=>{
 const h=harness();h.api.update({episodes:[{id:'first',title:'<img src=x onerror=evil()>',status:'failed',error:'<script>bad</script>'}]},false,true);
 assert.equal(h.node('libraryHostTools').hidden,true);assert.equal(h.node('libraryUpload').hidden,true);
 assert.ok(!h.node('episodeList').innerHTML.includes('<img'));assert.ok(!h.node('episodeList').innerHTML.includes('<script>'));
 assert.ok(!h.node('episodeList').innerHTML.includes('data-episode-action'));
});
test('multiple files upload sequentially with edited titles and do not select episodes',async()=>{
 const h=harness();h.api.update({episodes:[]},true,true);h.node('file').files=[{name:'One.mp4'},{name:'Two.mp4'}];h.node('file').onchange();
 h.node('uploadQueue').onchange({target:{dataset:{queueTitle:'0'},value:'Pilot'}});
 await h.node('upload').onclick();assert.equal(h.requests.length,2);
 assert.equal(h.requests[0].url,'/api/episodes?name=Pilot');assert.equal(h.requests[1].url,'/api/episodes?name=Two.mp4');
 assert.ok(h.node('uploadQueue').innerHTML.includes('Uploaded'));
});
