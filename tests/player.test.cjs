const {test}=require('node:test'),assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function playerHarness(native=false,supported=true){
 const engines=[];
 class Hls{
  static Events={ERROR:'error',MANIFEST_PARSED:'manifestparsed'};static isSupported(){return supported;}
  constructor(config){this.config=config;this.callbacks={};engines.push(this);}
  on(name,callback){this.callbacks[name]=callback;}
  fire(name){this.callbacks[name]?.();}
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
test('MSE audio language selection waits for the manifest and uses alternate audio tracks',()=>{
 const h=playerHarness();let ready=0;
 assert.equal(h.api.attach(h.element,'/hls/id/master.m3u8',()=>{}, {onReady:()=>ready++}),true);
 const engine=h.engines[0];
 engine.audioTracks=[{name:'English',lang:'eng'},{name:'Hindi',lang:'hin'}];
 assert.equal(ready,0);
 engine.fire('manifestparsed');
 assert.equal(ready,1);
 assert.equal(h.api.selectAudio(1,{label:'Hindi'}),true);
 assert.equal(engine.audioTrack,1);
 assert.equal(h.api.selectAudio(0,{label:'English'}),true);
 assert.equal(engine.audioTrack,0);
 assert.equal(h.api.selectAudio(5,{label:'Missing'}),false);
});
test('native HLS enables the chosen alternate audio track',()=>{
 const h=playerHarness(true,false);
 h.element.audioTracks=[{enabled:true},{enabled:false}];
 assert.equal(h.api.attach(h.element,'/hls/id/master.m3u8',()=>{}),true);
 assert.equal(h.api.selectAudio(1,{label:'Hindi'}),true);
 assert.equal(h.element.audioTracks[0].enabled,false);
 assert.equal(h.element.audioTracks[1].enabled,true);
 assert.equal(h.api.selectAudio(3,{label:'Missing'}),false);
});

test('audio requested before manifest readiness is applied when tracks arrive',()=>{
 const h=playerHarness();h.api.attach(h.element,'/hls/movie/master.m3u8',()=>{});
 assert.equal(h.api.selectAudio(1,{id:'audio2',label:'English'}),true);
 const engine=h.engines[0];engine.audioTracks=[{name:'Hindi'},{name:'English'}];engine.fire('manifestparsed');
 assert.equal(engine.audioTrack,1);
});
test('rendition URI takes precedence over duplicate names and reordered indexes',()=>{
 const h=playerHarness();h.api.attach(h.element,'/hls/movie/master.m3u8',()=>{});
 const engine=h.engines[0];engine.audioTracks=[{name:'Audio',url:'https://example.test/hls/movie/audio2/index.m3u8'},{name:'Audio',url:'https://example.test/hls/movie/audio/index.m3u8'}];
 assert.equal(h.api.selectAudio(1,{id:'audio2',label:'Audio'}),true);assert.equal(engine.audioTrack,0);
});
test('native audio selection follows language labels when browser order differs',()=>{
 const h=playerHarness(true,false);h.element.audioTracks=[{label:'English',enabled:false},{label:'Hindi',enabled:true}];
 h.api.attach(h.element,'/hls/movie/master.m3u8',()=>{});
 assert.equal(h.api.selectAudio(1,{label:'English'}),true);
 assert.equal(h.element.audioTracks[0].enabled,true);assert.equal(h.element.audioTracks[1].enabled,false);
});
