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
 const api = {target, correction};
 if (typeof module !== 'undefined' && module.exports) module.exports = api;
 else root.TeamWatchSync = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
