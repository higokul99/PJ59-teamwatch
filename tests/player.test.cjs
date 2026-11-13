const {test}=require('node:test'),assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function playerHarness(native=false,supported=true){
 const engines=[];
 class Hls{
  static Events={ERROR:'error'};static isSupported(){return supported;}
  constructor(config){this.config=config;engines.push(this);}
  on(name,callback){this.callback=callback;}
  loadSource(value){this.source=value;}
  attachMedia(value){this.media=value;}
  destroy(){this.destroyed=true;}
 }
 const element={canPlayType:()=>native?'probably':'',load(){this.loaded=true;}};
 const context=vm.createContext({Hls});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/player.js'),'utf8'),context);
 return {api:context.TeamWatchPlayer,engines,element};
}
test('native HLS uses the actual playlist directly',()=>{
 const h=playerHarness(true,false);
 assert.equal(h.api.attach(h.element,'/hls/id/master.m3u8',()=>{}),true);
 assert.equal(h.element.src,'/hls/id/master.m3u8');assert.equal(h.engines.length,0);
});
test('MSE playback starts at zero and does not accelerate toward the conversion edge',()=>{
 const h=playerHarness();h.api.attach(h.element,'/hls/id/master.m3u8',()=>{});
 assert.equal(h.engines[0].config.startPosition,0);
 assert.equal(h.engines[0].config.maxLiveSyncPlaybackRate,1);
 h.api.attach(h.element,'/hls/id/audio/index.m3u8',()=>{});
 assert.equal(h.engines[0].destroyed,true);
 assert.equal(h.engines[1].source,'/hls/id/audio/index.m3u8');
});
test('unsupported browser reports an error without pretending playback is ready',()=>{
 const h=playerHarness(false,false);let message='';
 assert.equal(h.api.attach(h.element,'/hls/id/master.m3u8',error=>message=error),false);
 assert.ok(message.includes('does not support'));
});
