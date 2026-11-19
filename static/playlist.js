/* Parse the few HLS tags the download-ahead engine needs. Kept separate from
   download.js so track filtering can be tested without a browser or worker. */
(function(root){
 'use strict';
 function attributes(line){
  const map={};
  const text=line.slice(line.indexOf(':')+1);
  const expression=/([A-Z0-9-]+)=("([^"]*)"|[^,]*)/g;
  let match;
  while((match=expression.exec(text)))map[match[1]]=match[3]!==undefined?match[3]:match[2];
  return map;
 }
 function trackMatches(uri,id){
  const path=uri.split('?')[0];
  return path===id+'/index.m3u8'||path.endsWith('/'+id+'/index.m3u8');
 }
 function entries(text,options={}){
  const files=[],children=[];
  for(const raw of String(text).split('\n')){
   const line=raw.trim();
   if(!line)continue;
   if(line.startsWith('#EXT-X-MAP:')){
    const uri=attributes(line).URI;if(uri)files.push(uri);
   }else if(line.startsWith('#EXT-X-MEDIA:')){
    const media=attributes(line),uri=media.URI;if(!uri)continue;
    const type=(media.TYPE||'').toUpperCase();
    // A device downloads the audio language it is listening to, not every
    // language packaged into the movie.
    if(type==='AUDIO'&&options.audio&&!trackMatches(uri,options.audio))continue;
    if(type==='SUBTITLES'&&options.subtitles===false)continue;
    children.push(uri);
   }else if(!line.startsWith('#')){
    if(line.endsWith('.m3u8'))children.push(line);else files.push(line);
   }
  }
  return {files,children,complete:/^#EXT-X-ENDLIST\s*$/m.test(String(text))};
 }
 const api={entries,trackMatches};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 else root.TeamWatchPlaylist=api;
})(typeof globalThis!=='undefined'?globalThis:this);
