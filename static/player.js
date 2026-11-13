(function(root){
 'use strict';
 let engine=null;
 function destroy(){if(engine){engine.destroy();engine=null;}}
 function attach(element,path,onError){
  destroy();
  if(!path.endsWith('.m3u8')){element.src=path;element.load();return true;}
  // Prefer the consistent MSE path when available; native HLS remains the
  // fallback on devices (including older iPhones) without a supported MSE path.
  element.disableRemotePlayback=true;
  if(!root.Hls?.isSupported()){
   if(element.canPlayType?.('application/vnd.apple.mpegurl')){element.src=path;element.load();return true;}
   onError('This browser does not support segmented playback. Try a current Safari, Chrome, Edge, or Firefox.');return false;
  }
  engine=new root.Hls({startPosition:0,maxBufferLength:30,maxMaxBufferLength:60,backBufferLength:60,
                      maxLiveSyncPlaybackRate:1});
  engine.on(root.Hls.Events.ERROR,(_,data)=>{if(data.fatal)onError('Playback could not load prepared segments. Rejoin or switch mode to retry.');});
  engine.loadSource(path);engine.attachMedia(element);return true;
 }
 root.TeamWatchPlayer={attach,destroy};
})(globalThis);
