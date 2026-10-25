const {test} = require('node:test');
const assert = require('node:assert/strict');
const {target,correction} = require('../static/sync.js');
const decide = overrides => correction({target:10,current:10,playing:true,seeking:false,force:false,now:10,lastSeek:-Infinity,...overrides});
test('future start is held at room position; paused state ignores hardware adjustment',()=>{
 const timeline={position:20,anchor:100,playing:true};
 assert.equal(target(timeline,200,99,150),20);
 assert.equal(target(timeline,200,101,150),21.15);
 assert.equal(target({...timeline,playing:false},200,101,150),20);
 assert.equal(target(timeline,21,110,0),21);
});
test('200 ms lag catches up without seeking or interrupting audio',()=>{
 let current=9.8;
 for(let step=0;step<60;step++){
  const now=10+step*.1;
  const result=decide({target:now,current,now});
  assert.equal(result.seek,false);
  current+=result.rate*.1;
 }
 assert.ok(Math.abs(16-current)<.05,`Remaining lag: ${16-current}`);
});
test('slow seek is allowed to finish instead of restarting it',()=>{
 assert.equal(decide({current:5,seeking:true,force:true}).seek,false);
 assert.equal(decide({current:5,lastSeek:9}).seek,false);
 assert.equal(decide({current:5,lastSeek:8}).seek,true);
});
test('slow decoder recovers after initial hard seek without a seek loop',()=>{
 let current=0,seekingUntil=0,lastSeek=-Infinity,seeks=0;
 for(let step=0;step<200;step++){
  const now=10+step*.1;
  const seeking=now<seekingUntil;
  const result=decide({target:now,current,now,seeking,lastSeek});
  if(result.seek){current=now;lastSeek=now;seekingUntil=now+.45;seeks++;}
  else if(!seeking)current+=result.rate*.1;
 }
 assert.equal(seeks,1);
 assert.ok(Math.abs(30-current)<.05,`Remaining lag: ${30-current}`);
});
test('ahead device slows down and rates stay bounded',()=>{
 assert.ok(decide({current:10.2}).rate<1);
 for(const current of [0,9.9,10,10.1,20]){
  const rate=decide({current,lastSeek:10}).rate;
  assert.ok(rate>=.92&&rate<=1.08);
 }
});
test('pause and explicit resync align immediately, even during seek cooldown',()=>{
 assert.equal(decide({playing:false,current:9.8,lastSeek:10}).seek,true);
 assert.equal(decide({force:true,current:9.8,lastSeek:10}).seek,true);
 assert.equal(decide({current:9.99,force:true}).seek,false);
});
test('700 ms phone lag converges without repeated seek interruptions',()=>{
 let current=9.3;
 for(let step=0;step<150;step++){
  const now=10+step*.1;
  const result=decide({target:now,current,now});
  assert.equal(result.seek,false);
  current+=result.rate*.1;
 }
 assert.ok(Math.abs(25-current)<.05,`Remaining lag: ${25-current}`);
});
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function browserHarness(){
 let elapsed=0;
 const nodes=new Map(),timers=[];
 function node(id){
  if(!nodes.has(id))nodes.set(id,{value:0,disabled:false,hidden:false,currentTime:0,readyState:4,paused:true,seeking:false,playbackRate:1,plays:0,
   classList:{toggle(){}},setAttribute(){},removeAttribute(){},load(){},addEventListener(){},pause(){this.paused=true;},
   play(){this.paused=false;this.plays++;return Promise.resolve();}});
  return nodes.get(id);
 }
 const context=vm.createContext({console,Date:{now:()=>100000},performance:{now:()=>elapsed},localStorage:{getItem:()=>null,setItem(){}},
  document:{getElementById:node,querySelectorAll:()=>[],addEventListener(){},activeElement:null},
  navigator:{},fetch:()=>Promise.reject(Error('Not signed in')),WebSocket:{OPEN:1},
  setInterval(){},clearInterval(){},setTimeout(fn,delay){timers.push({fn,delay});return timers.length;},clearTimeout(){}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/sync.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8'),context);
 vm.runInContext("ws={readyState:1};media={duration:200,has_video:true};roomState={position:0,playing:true,anchor:101.5};enabled=true;",context);
 return {context,node,timers,advance(ms){elapsed=ms;},run(source){return vm.runInContext(source,context);}};
}
test('browser starts at the scheduled deadline, not the periodic polling tick',()=>{
 const h=browserHarness();
 h.run('scheduleStart();sync();');
 assert.equal(h.node('video').plays,0);
 assert.equal(h.timers.at(-1).delay,1500);
 h.advance(1500);h.timers.at(-1).fn();
 assert.equal(h.node('video').plays,1);
});
test('host pause applies even when the phone has not buffered enough data',()=>{
 const h=browserHarness();
 h.node('video').paused=false;h.node('video').readyState=1;
 h.run('roomState.playing=false;sync();');
 assert.equal(h.node('video').paused,true);
});
test('clock correction re-schedules the same playback deadline',()=>{
 const h=browserHarness();
 h.run('scheduleStart();clockOffset=.1;scheduleStart();');
 assert.ok(Math.abs(h.timers.at(-1).delay-1400)<.001);
});
