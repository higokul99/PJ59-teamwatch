const {test}=require('node:test');
const assert=require('node:assert/strict');
const {entries,trackMatches}=require('../static/playlist.js');
const master=`#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",LANGUAGE="eng",DEFAULT=YES,URI="audio/index.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Hindi",LANGUAGE="hin",DEFAULT=NO,URI="audio2/index.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",URI="subs0/index.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=8000000,CODECS="avc1.64001f,mp4a.40.2",AUDIO="audio"
video/index.m3u8
`;
test('only the selected audio language is downloaded ahead',()=>{
 const parsed=entries(master,{audio:'audio2',subtitles:false});
 assert.deepEqual(parsed.children,['audio2/index.m3u8','video/index.m3u8']);
 assert.deepEqual(parsed.files,[]);
 assert.equal(parsed.complete,false);
});
test('without a selection every rendition remains available',()=>{
 assert.deepEqual(entries(master,{}).children,
  ['audio/index.m3u8','audio2/index.m3u8','subs0/index.m3u8','video/index.m3u8']);
 assert.deepEqual(entries(master,{audio:'audio'}).children,
  ['audio/index.m3u8','subs0/index.m3u8','video/index.m3u8']);
});
test('subtitle renditions can be excluded from downloads',()=>{
 assert.deepEqual(entries(master,{subtitles:false}).children,
  ['audio/index.m3u8','audio2/index.m3u8','video/index.m3u8']);
});
test('media playlists expose init and segment files',()=>{
 const playlist='#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4,\nsegment_000000.m4s\n#EXT-X-ENDLIST\n';
 const parsed=entries(playlist);
 assert.deepEqual(parsed.files,['init.mp4','segment_000000.m4s']);
 assert.deepEqual(parsed.children,[]);
 assert.equal(parsed.complete,true);
});
test('track matching accepts absolute and relative rendition URIs',()=>{
 assert.equal(trackMatches('/hls/0123456789abcdef01234567/audio2/index.m3u8','audio2'),true);
 assert.equal(trackMatches('audio2/index.m3u8','audio2'),true);
 assert.equal(trackMatches('audio/index.m3u8','audio2'),false);
});
