(function(root){
 'use strict';
 let engine=null,mediaElement=null;
 function destroy(){if(engine){engine.destroy();engine=null;}mediaElement=null;}
 function attach(element,path,onError,options={}){
  destroy();
  if(!path.endsWith('.m3u8')){element.src=path;element.load();return true;}
  mediaElement=element;
  const ready=()=>{try{options.onReady?.();}catch{}};
  // Prefer the consistent MSE path when available; native HLS remains the
  // fallback on devices (including older iPhones) without a supported MSE path.
  element.disableRemotePlayback=true;
  if(!root.Hls?.isSupported()){
   if(element.canPlayType?.('application/vnd.apple.mpegurl')){
    element.src=path;element.load();
    element.addEventListener?.('loadedmetadata',ready,{once:true});
    return true;
   }
   onError('This browser does not support segmented playback. Try a current Safari, Chrome, Edge, or Firefox.');return false;
  }
  engine=new root.Hls({startPosition:0,maxBufferLength:30,maxMaxBufferLength:60,backBufferLength:60,
                      maxLiveSyncPlaybackRate:1});
  engine.on(root.Hls.Events.ERROR,(_,data)=>{if(data.fatal)onError('Playback could not load prepared segments. Rejoin or switch mode to retry.');});
  engine.on((root.Hls.Events&&root.Hls.Events.MANIFEST_PARSED)||'hlsManifestParsed',ready);
  engine.loadSource(path);engine.attachMedia(element);return true;
 }
 function selectAudio(index,track){
  if(engine){
   const list=engine.audioTracks||[];
   let found=Number.isInteger(index)&&index>=0&&index<list.length?index:-1;
   if(track&&list.length){
    const byLabel=list.findIndex(item=>String(item.name||'').trim()===String(track.label||'').trim());
    if(byLabel>=0)found=byLabel;
   }
   if(found>=0){engine.audioTrack=found;return true;}
   return false;
  }
  // Native HLS exposes alternate audio as HTMLMediaElement.audioTracks (Safari).
  const list=mediaElement?.audioTracks;
  if(list&&list.length){
   if(!(index>=0&&index<list.length))return false;
   for(let position=0;position<list.length;position++){
    try{list[position].enabled=position===index;}catch{}
   }
   return true;
  }
  return false;
 }
 root.TeamWatchPlayer={attach,destroy,selectAudio};
})(globalThis);
