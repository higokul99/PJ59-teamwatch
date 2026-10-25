/* Pure playback decisions, shared by the browser and regression tests. */
(function(root) {
 'use strict';
 function target(timeline, duration, now, offsetMs = 0) {
  const started = timeline.playing && now >= timeline.anchor;
  const elapsed = started ? now - timeline.anchor : 0;
  return Math.max(0, Math.min(duration, timeline.position + elapsed + (started ? offsetMs / 1000 : 0)));
 }
 function correction({target, current, playing, seeking, force, now, lastSeek}) {
  const drift = target - current;
  // A seek temporarily stops decoding. Repeated seeks can keep a slow phone
  // buffering forever. While playing, only an explicit resync may seek.
  if (seeking) return {drift, rate: 1, seek: false};
  const seek = Math.abs(drift) > .025 && (force || !playing);
  const rate = seek || !playing || Math.abs(drift) <= .03 ? 1 : 1 + Math.max(-.08, Math.min(.08, drift * .4));
  return {drift, rate, seek};
 }
 // Media clocks can update in coarse steps. Never drive the decoder's rate
 // directly from each 100 ms sample: smooth a full second, then use hysteresis.
 class RateController {
  constructor(){this.reset();}
  reset(now=null){this.samples=[];this.next=now===null?null:now+1;this.rate=1;this.lastSample=null;}
  update(drift,now){
   if(!Number.isFinite(drift)||!Number.isFinite(now))return this.rate;
   if(this.lastSample!==null&&now-this.lastSample<.05)return this.rate;
   this.lastSample=now;
   if(this.next===null)this.next=now+1;
   this.samples.push(drift);
   if(this.samples.length>20)this.samples.shift();
   if(now<this.next)return this.rate;
   const samples=this.samples.slice().sort((a,b)=>a-b);
   const middle=Math.floor(samples.length/2);
   const filtered=samples.length%2?samples[middle]:(samples[middle-1]+samples[middle])/2;
   this.samples=[];this.next=now+1;
   const desired=Math.abs(filtered)<=.06?1:1+Math.max(-.08,Math.min(.08,Math.round(filtered*.4*100)/100));
   if(desired===1||Math.abs(desired-this.rate)>=.015)this.rate=desired;
   return this.rate;
  }
 }
 const api = {target, correction, RateController};
 if (typeof module !== 'undefined' && module.exports) module.exports = api;
 else root.TeamWatchSync = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
