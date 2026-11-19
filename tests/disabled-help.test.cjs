const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function harness(){
 const events={},timers=new Map();let id=0,changed;
 const button={disabled:true,isConnected:true,dataset:{disabledReason:'Wait for preparation.'},getBoundingClientRect:()=>({left:10,right:100,top:10,bottom:40,width:90,height:30}),closest:()=>null};
 const tip={hidden:true,style:{},offsetWidth:200,offsetHeight:40};
 const body={append(){}};
 const context={document:{body,createElement:()=>tip,querySelectorAll:()=>button.disabled?[button]:[],addEventListener:(n,f)=>events[n]=f},window:{addEventListener:(n,f)=>events[n]=f},innerWidth:375,innerHeight:700,setTimeout:f=>{timers.set(++id,f);return id;},clearTimeout:i=>timers.delete(i),MutationObserver:class{constructor(f){changed=f;}observe(){}}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../static/disabled-help.js'),'utf8'),context);
 return {button,tip,events,changed,fire:()=>{for(const f of timers.values())f();timers.clear();}};
}
test('hover shows the reason and enabling the button dismisses it',()=>{
 const h=harness();h.events.pointermove({pointerType:'mouse',clientX:20,clientY:20});
 assert.equal(h.tip.hidden,false);assert.equal(h.tip.textContent,'Wait for preparation.');
 h.button.disabled=false;h.changed();assert.equal(h.tip.hidden,true);
});
test('long press reveals help without enabling the button; moving cancels it',()=>{
 const h=harness();const touch={pointerType:'touch',clientX:20,clientY:20};
 h.events.pointerdown(touch);assert.equal(h.tip.hidden,true);h.fire();
 assert.equal(h.tip.hidden,false);assert.equal(h.button.disabled,true);
 h.events.pointerdown(touch);h.events.pointermove({...touch,clientX:60});h.fire();assert.equal(h.tip.hidden,true);
 h.events.pointerdown(touch);h.events.pointerup();h.fire();assert.equal(h.tip.hidden,true);
});
