/* Disabled controls stay disabled; pointer hit-testing also works on browsers
   that suppress events originating from native disabled buttons. */
(()=>{
 'use strict';
 const tip=document.createElement('div');
 tip.id='disabledHelp';tip.role='tooltip';tip.hidden=true;
 document.body.append(tip);
 let active=null,timer=null,start=null;
 function reason(button){
  if(button.dataset.disabledReason)return button.dataset.disabledReason;
  if(button.dataset.mode)return 'This media has no video. Choose Audio only.';
  if(button.dataset.queueUp!==undefined)return 'This episode is already first in the upload queue.';
  if(button.id==='episodeDialogSubmit')return document.getElementById('episodeConfirmLabel')?.hidden===false&&document.getElementById('episodeConfirmInput').value!=='CONFIRM'?'Type CONFIRM exactly to continue.':'Please wait while your change is saved.';
  if(button.id==='confirmSubmit')return document.getElementById('confirmLabel')?.hidden===false&&document.getElementById('confirmText').value!=='CONFIRM'?'Type CONFIRM exactly to continue.':'Please wait while the request completes.';
  if(button.id==='connect')return document.getElementById('screenText')?.textContent||'Select a playable episode first.';
  if(['play','pause','restart','syncAll','back10','forward10','jumpButton','resync','retryDownload'].includes(button.id))return 'Select an episode with playable media first. If it is preparing, wait for the first segments.';
  return 'Please wait while the current request completes.';
 }
 function hide(){clearTimeout(timer);timer=null;active=null;tip.hidden=true;}
 function hit(x,y){return [...document.querySelectorAll('button:disabled')].find(b=>{const r=b.getBoundingClientRect();return r.width&&r.height&&x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom;});}
 function show(button){
  if(!button?.isConnected||!button.disabled)return hide();
  active=button;tip.textContent=reason(button);
  // Dialogs and fullscreen elements occupy a separate top layer.
  (button.closest('dialog[open]')||document.fullscreenElement||document.body).append(tip);
  tip.hidden=false;
  const r=button.getBoundingClientRect();
  tip.style.left=Math.max(8,Math.min(r.left,innerWidth-tip.offsetWidth-8))+'px';
  tip.style.top=Math.max(8,r.bottom+tip.offsetHeight+8<innerHeight?r.bottom+8:r.top-tip.offsetHeight-8)+'px';
 }
 document.addEventListener('pointermove',e=>{
  if(e.pointerType==='touch'){if(start&&Math.hypot(e.clientX-start.x,e.clientY-start.y)>10)hide();return;}
  const button=hit(e.clientX,e.clientY);if(button)show(button);else hide();
 },true);
 document.addEventListener('pointerdown',e=>{
  hide();start={x:e.clientX,y:e.clientY};
  const button=hit(e.clientX,e.clientY);
  if(button&&e.pointerType!=='mouse')timer=setTimeout(()=>show(button),500);
 },true);
 document.addEventListener('pointerup',()=>{clearTimeout(timer);start=null;},true);
 document.addEventListener('pointercancel',hide,true);
 document.addEventListener('scroll',hide,true);
 document.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
 document.addEventListener('pointerleave',hide);
 window.addEventListener('blur',hide);window.addEventListener('resize',hide);
 new MutationObserver(()=>{if(active){if(!active.disabled||!active.isConnected)hide();else if(tip.textContent!==reason(active))tip.textContent=reason(active);}}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled','data-disabled-reason']});
})();
