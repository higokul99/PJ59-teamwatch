(function(root){
 'use strict';
 let engine=null,mediaElement=null,pendingAudio=null,tracksReady=false,cleanup=[];
 function destroy(){for(const stop of cleanup)stop();cleanup=[];pendingAudio=null;tracksReady=false;if(engine){engine.destroy();engine=null;}mediaElement=null;}
 function attach(element,path,onError,options={}){
  destroy();
  if(!path.endsWith('.m3u8')){element.src=path;element.load();return true;}
  mediaElement=element;
  const ready=()=>{tracksReady=true;if(pendingAudio)applyAudio();try{options.onReady?.();}catch{}};
  const listen=(target,event,fn)=>{target?.addEventListener?.(event,fn);cleanup.push(()=>target?.removeEventListener?.(event,fn));};
  // Prefer the consistent MSE path when available; native HLS remains the
  // fallback on devices (including older iPhones) without a supported MSE path.
  element.disableRemotePlayback=true;
  if(!root.Hls?.isSupported()){
   if(element.canPlayType?.('application/vnd.apple.mpegurl')){
    listen(element,'loadedmetadata',ready);
    listen(element.audioTracks,'addtrack',()=>{if(pendingAudio)applyAudio();});
    element.src=path;element.load();
    return true;
   }
   onError('This browser does not support segmented playback. Try a current Safari, Chrome, Edge, or Firefox.');return false;
  }
  engine=new root.Hls({startPosition:0,maxBufferLength:30,maxMaxBufferLength:60,backBufferLength:60,
                      maxLiveSyncPlaybackRate:1});
  engine.on(root.Hls.Events.ERROR,(_,data)=>{if(data.fatal)onError('Playback could not load prepared segments. Rejoin or switch mode to retry.');});
  engine.on((root.Hls.Events&&root.Hls.Events.MANIFEST_PARSED)||'hlsManifestParsed',ready);
  if(root.Hls.Events.AUDIO_TRACKS_UPDATED)engine.on(root.Hls.Events.AUDIO_TRACKS_UPDATED,()=>{if(pendingAudio)applyAudio();});
  engine.loadSource(path);engine.attachMedia(element);return true;
 }
 function applyAudio(){
  if(!pendingAudio)return false;
  const {index,track}=pendingAudio;
  const list=Array.from(engine?.audioTracks||mediaElement?.audioTracks||[]);
  if(!list.length)return !tracksReady;
  // HLS implementations may reorder tracks. Prefer the rendition URI, then
  // its unique manifest label; the source index is only a final fallback.
  let found=-1;
  if(track?.id)found=list.findIndex(item=>String(item.url||'').split('?')[0].endsWith('/'+track.id+'/index.m3u8')||String(item.url||'')===track.id+'/index.m3u8');
  if(found<0&&track?.label)found=list.findIndex(item=>String(item.name||item.label||'').trim()===track.label.trim());
  if(found<0&&track?.language){
   const matches=list.map((item,i)=>({item,i})).filter(({item})=>(item.lang||item.language)===track.language);
   if(matches.length===1)found=matches[0].i;
  }
  if(found<0&&Number.isInteger(index)&&index>=0&&index<list.length)found=index;
  if(found<0)return false;
  try{
   if(engine){engine.audioTrack=found;return engine.audioTrack===found;}
   for(let i=0;i<list.length;i++)list[i].enabled=i===found;
   return list[found].enabled===true;
  }catch{return false;}
 }
 function selectAudio(index,track){
  pendingAudio={index,track};
  const accepted=applyAudio();
  if(!accepted)pendingAudio=null;
  return accepted;
 }
 root.TeamWatchPlayer={attach,destroy,selectAudio};
})(globalThis);
