(function(root){
 'use strict';
 const CHUNK_SIZE=1024*1024;
 function range(header,size){
  if(!Number.isSafeInteger(size)||size<=0)throw Error('Invalid media size');
  if(!header)return {start:0,end:size-1,status:200};
  const match=/^bytes=(\d*)-(\d*)$/.exec(header);
  if(!match||(!match[1]&&!match[2]))throw Error('Invalid range');
  let start,end;
  if(!match[1]){const suffix=Number(match[2]);if(suffix<=0)throw Error('Invalid range');start=Math.max(0,size-suffix);end=size-1;}
  else{start=Number(match[1]);end=match[2]?Math.min(Number(match[2]),size-1):size-1;}
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>=size||start>end)throw Error('Unsatisfiable range');
  return {start,end,status:206};
 }
 function chunkBounds(index,size){
  if(!Number.isSafeInteger(index)||index<0||index*CHUNK_SIZE>=size)throw Error('Invalid chunk');
  return {start:index*CHUNK_SIZE,end:Math.min(size-1,(index+1)*CHUNK_SIZE-1)};
 }
 const api={CHUNK_SIZE,range,chunkBounds};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.TeamWatchCache=api;
})(typeof globalThis!=='undefined'?globalThis:this);
