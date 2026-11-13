# TeamWatch

TeamWatch is a private, real-time synchronized media streaming server. It is built for movie nights where:

1. **Projector / TV**: Plays video only (muted / no sound track).
2. **Personal Devices**: Participants listen to audio only on their phones with headphones, or watch video + audio on personal screens.
3. **Authoritative Timeline**: The server maintains a synchronized master timeline over WebSockets, keeping all devices aligned within milliseconds using smooth, dynamic playback-rate adjustments ($\pm 8\%$) without audible skipping.

For the Metora VPS layout and Nginx deployment, see [docs/deployment/README.md](docs/deployment/README.md).

---

## System Architecture & Tech Stack

### Backend
- **Framework & Runtime**: Python 3.11+ with [FastAPI](https://fastapi.tiangolo.com/) (0.141.x) and [Starlette](https://www.starlette.io/) (1.6.x) running on [Uvicorn](https://www.uvicorn.org/) (0.52.x).
- **Real-Time Communication**: Native Starlette WebSockets (`/ws`) for bidirectional timeline events, NTP-style monotonic clock offset calculation, and room state broadcasts.
- **Media Pipeline**: FFmpeg & FFprobe subprocess pipeline ([media_pipeline.py](media_pipeline.py)) producing incremental 4-second fragmented MP4 (`fmp4`) HLS event streams (`.m3u8`). Stream-copies compatible H.264 video and AAC audio to avoid full re-encoding. Supports instant playback startup (~8 seconds of segments) while background encoding continues.
- **State Management & Storage**:
  - **In-Memory**: Room play/pause state, active timeline anchor, connected peers, and IP rate limits live in memory (single-worker architecture).
  - **Filesystem**: Uploaded sources, generated HLS segments, and diagnostic conversion logs persist under `./data/` (`DATA_DIR`).
  - **Zero Database**: No SQL or ORM dependencies; runs entirely on disk and in-memory structures.
- **Security & Authentication**:
  - Dual-role authentication (`host` vs `viewer`) verified via PINs (`ROOM_CODE`, `HOST_PIN`, `VIEWER_PIN`).
  - HMAC-SHA256 signed session cookies with 24-hour TTL.
  - Brute-force protection: in-memory IP rate limiting (10 failed attempts / 5 minutes).
  - CSRF protection: strict same-origin verification on all mutation endpoints.

### Frontend
- **Architecture**: Lightweight, vanilla Single Page Application (SPA) with zero external JavaScript framework, build step, or npm dependencies.
- **Markup & Styling**: Semantic HTML5 ([index.html](static/index.html)) with a responsive, mobile-first dark-mode stylesheet ([style.css](static/style.css)).
- **Client Modules** (`static/`):
  - [`app.js`](static/app.js): Core application UI controller, join/host modal management, button interactions, and upload workflows.
  - [`sync.js`](static/sync.js): High-precision clock synchronization, round-trip NTP-style offset tracking, and dynamic drift correction ($\pm 8\%$ speed adjustments).
  - [`player.js`](static/player.js): HTML5 `<video>` / `<audio>` abstraction layer.
  - [`download.js`](static/download.js) & [`cache-core.js`](static/cache-core.js): Progressive download engine storing chunks into browser IndexedDB.
  - [`sw.js`](static/sw.js): Service Worker intercepting media byte-range requests and HLS segment downloads for local offline/ahead playback.
  - [`vendor/hls-1.7.4.min.js`](static/vendor/): Vendored HLS.js client bundle for browsers lacking native HLS Media Source Extensions.

### DevOps & Infrastructure
- **Containerization**: Multi-stage [Dockerfile](Dockerfile) bundling Python, FFmpeg, and Node.js (for test runner), orchestrated via [compose.yaml](compose.yaml).
- **Reverse Proxy**: Production-ready configurations for Caddy ([Caddyfile.example](Caddyfile.example)) or Nginx ([docs/deployment/nginx.conf.template](docs/deployment/nginx.conf.template)), handling WebSocket upgrades and up to 10 GiB upload limits (`MAX_UPLOAD_MB`).

---

## Project Structure

```text
4-teamwatch/
├── app.py                  # FastAPI application, REST endpoints, WebSocket hub, session auth
├── media_pipeline.py       # FFmpeg probe & incremental HLS fMP4 segmentation pipeline
├── requirements.txt        # Production Python dependencies (fastapi, starlette, uvicorn)
├── requirements-dev.txt    # Development & testing dependencies
├── Dockerfile              # Multi-stage container build with FFmpeg & Node.js test environment
├── compose.yaml            # Docker Compose service definition
├── static/                 # Frontend assets (served directly by FastAPI)
│   ├── index.html          # Main application UI markup
│   ├── style.css           # Responsive mobile-friendly dark theme
│   ├── app.js              # UI controller and room event handlers
│   ├── sync.js             # Real-time WebSocket clock sync and playback rate controller
│   ├── player.js           # Media element wrapper
│   ├── download.js         # Pre-download manager
│   ├── cache-core.js       # IndexedDB storage utilities
│   ├── sw.js               # Service Worker for progressive caching
│   └── vendor/             # Vendored client dependencies (hls.js)
├── docs/deployment/        # Production deployment scripts and Nginx configuration
├── docs/                   # Specifications, PRDs, architecture notes, and developer guides
└── tests/                  # Test suites (Python unittest + Node.js browser sync tests)
```

---

## Quick start with Docker

```sh
cp .env.example .env
# Edit .env, set SESSION_SECRET, and change PINs for a public deployment.
docker compose up -d --build
```

Open http://localhost:8000. Default room code: **8889292**, viewer PIN: **8989**, host PIN: **9292**. The dictated code had seven digits despite the request describing eight; change `ROOM_CODE` to any 6–8 digit code in `.env` if needed. All devices use the same room code. PIN determines the role. The default room is imported once; the admin portal manages additional rooms and host/participant accounts. Each room retains a library of episodes with one active playback selection.

For a VPS, put Caddy (example config included) or another HTTPS reverse proxy in front of port 8000. Point a domain to the VPS, allow ports 80/443, set `COOKIE_SECURE=true`, and restart the container. Keep port 8000 bound to localhost. The proxy must forward WebSocket upgrades and preserve the Host header. Set its upload limit at least as high as `MAX_UPLOAD_MB`. If using Nginx, also configure `client_max_body_size`, upgrade headers, and suitable upload/read timeouts. Avoid a CDN with a smaller upload limit.

For a trusted LAN test, set `BIND_ADDRESS=0.0.0.0` and `COOKIE_SECURE=false`, restart, and open `http://YOUR_COMPUTER_LAN_IP:8000` from phones on the same Wi-Fi. `localhost` on a phone points to that phone, not the server. Use HTTPS for access over the internet.

## Movie night

1. Join using the host PIN. Choose a file, then **Upload & prepare**. Playback becomes available once the first playable segments are ready; the rest prepares in the background. Watch the preparation progress bar. Most formats ffmpeg can decode are accepted, including MKV; an audio track is required. Audio-only files are supported too.
2. Open the same URL on the projector and choose **Video only**. The server sends a video file with no audio track.
3. Friends join with the viewer PIN and select **Audio only** on their phones, or **Video + audio** to watch on their own screens.
4. Everyone taps **Connect playback** when the movie is ready. The host does this too if watching or listening on that device. The host can also control the room without connecting local playback.
5. Any participant can press **Play for everyone** or **Pause everyone**. The host can **Restart movie**, jump **10 seconds** backward/forward, drag the position slider, enter an exact timestamp using **Go to time** (for example `01:23` or `01:02:03`), or press **Sync all devices** to re-align the room at a common timestamp. Late arrivals catch up after connecting playback. A connected device buffering, stopping, or disconnecting pauses the room. Resume manually with Play when active devices are ready.
6. Keep phone browser pages visible and screens awake. The app requests a screen wake lock where supported. Background playback, locked screens, battery-saving modes, and browser timer throttling can interfere with synchronization. Switching modes or replacing a movie requires tapping Connect playback again.

## Synchronization and bandwidth

- The server owns the position, play state, and start timestamp. Play and seek while playing schedule a start 1.5 seconds ahead.
- Devices sample server clock offset using WebSocket round-trip measurements and the lowest-latency recent sample. A monotonic browser clock avoids local wall-clock jumps.
- A deadline timer starts playback at the shared timestamp. Every 100 ms, the client compares its media time with the shared timeline. Small errors use up to ±8% playback-rate adjustment, smoothed over one second with hysteresis so a coarse browser clock does not repeatedly reset playback speed. Normal playback no longer triggers repeated hard seeks, which can interrupt phone audio. Explicit sync/seek commands and initial connection can reposition playback. Clock offset is sampled several times immediately on connection. Use Resync this device for a local correction, or the host’s Sync all devices to schedule a new room-wide anchor. Persistent buffering is debounced and pauses everyone; readiness reports prevent resuming while active devices are unready. New seeks have a grace period so ordinary decoder activity does not pause the room. Resume manually with Play when ready.
- New uploads use event HLS playlists with four-second fragmented-MP4 segments. Compatible 8-bit H.264 video up to 1080p is copied without video re-encoding; other video is converted once to H.264. AAC-LC audio is copied where possible. Video-only and audio-only playlists contain only their respective tracks; combined mode references both without creating a duplicate full movie. Playlists retain segments from the beginning and become final when preparation completes. Supported browsers use the pinned, vendored hls.js player, with native HLS as a fallback on devices without Media Source Extensions. Older prepared MP4/M4A media still plays normally.
- Audio-only clients download approximately 160 kbps plus overhead. Video is capped at 1920 pixels wide, with variable bitrate. Each viewer consumes outbound VPS bandwidth independently.
- There is **no guarantee of identical acoustic latency**. This is best-effort browser synchronization, not sample-accurate multi-device audio. Bluetooth, hardware, buffering, and mobile browser restrictions introduce delay. Use per-device adjustment (±2000 ms); positive values advance playback to compensate for slow audio output. Start with +150 ms for late Bluetooth audio and adjust by ear. Reported drift measures browser media position, not sound reaching headphones.

## Local Python development

Use the requested shared environment:

```sh
cd /Applications/XAMPP/xamppfiles/htdocs/github/7-python/4-teamwatch
/Applications/XAMPP/xamppfiles/htdocs/github/7-python/venv/bin/python -m pip install -r requirements.txt
# Install ffmpeg with your system package manager (ffmpeg and ffprobe must be on PATH).
/Applications/XAMPP/xamppfiles/htdocs/github/7-python/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000 --ws-max-size 4096
```

Local Python reads environment variables, not `.env` automatically. Defaults work for development. `DATA_DIR` defaults to `./data`. Docker Compose loads `.env` for you. Always run **one worker and one replica**: room state and connected peers are in memory. Multiple workers require an external shared state/broadcast service.

## Operations

- Uploads default to a 10 GiB limit and stream to disk with bounded memory. Only one upload/conversion runs at a time. Full preparation can take minutes to hours, but playback opens after approximately eight seconds of complete segments exist (or the entire clip for shorter files). The progress bar shows the prepared percentage, playable duration, and preparation speed. Startup is a target rather than an unconditional two-minute guarantee: upload time, codec, storage, and VPS capacity still matter. ffmpeg video encoding is limited to two threads.
- Allow space for retained source files and generated audio/video segments for every episode. New uploads do not delete existing episodes. Library deletion removes the associated source and output; cleanup failures are visible and retryable. Configure room/server quotas and a free-disk reserve in `.env`.
- The Docker named volume retains the prepared movie across container restarts. Playback restarts paused at zero; interrupted uploads/conversions are not resumed. Repeated abrupt shutdowns can leave orphaned files needing cleanup.
- Sessions expire after 24 hours. Set a stable random `SESSION_SECRET` to preserve signed sessions across restarts; leaving it empty generates a new secret each startup. Logout revokes the session in memory and disconnects its sockets. Rotate the secret to invalidate all sessions.
- Host/viewer PINs are shared credentials for a small trusted group. Login is rate-limited per source IP (10 failed attempts/5 minutes), media requires a session, mutations require same-origin requests, and only hosts can upload, seek, restart, or sync all devices. All joined participants can play/pause the room. Behind a proxy, configure trusted proxy IPs correctly to preserve client IP rate limiting. Default proxy trust is loopback only.
- `GET /health` reports service status and whether ffmpeg/ffprobe are installed. Use `docker compose logs -f` for server logs; conversion diagnostics are in `/app/data/<media-id>/conversion.log`.
- No DRM, subtitles, multiple audio-track selection, adaptive bitrate, or frame-accurate guarantees in this first version. The first video/audio tracks are selected.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests cover authentication, role separation, same-origin enforcement, byte ranges, WebSocket control, timeline behavior, upload limits, and ffmpeg preparation where ffmpeg is installed. A real projector/phone/headphone test is still needed to tune hardware delay.

Implementation references: [Starlette byte-range responses](https://www.starlette.dev/responses/), [browser playback rate](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/playbackRate), and [browser seeking](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/currentTime).

Run all tests including real media conversion without installing FFmpeg on the host:

```sh
docker build --target test -t teamwatch:test .
docker run --rm teamwatch:test
```

Browser synchronization regressions can also be run with `node --test tests/*.test.cjs`. Node.js is installed only in the Docker test stage.

## Download ahead on each device

On HTTPS (or localhost), the browser downloads the selected media into IndexedDB through a service worker. HLS initialization/segment files are saved as they become available, from the beginning; combined mode interleaves audio/video files. Storage/network reads are bounded in 1 MiB chunks. Legacy MP4 tracks also use the existing sequential byte-range cache. Native
media range requests read those same chunks; missing chunks are fetched on demand.
Playback can start while downloading continues. Progress shows how much of the
selected track is saved; **Fully downloaded** means the sequential download
completed. Audio-only mode saves only AAC audio, and video-only mode saves a silent
video track. Switching modes downloads the corresponding track.

Downloads use device storage, not an entire movie held in JavaScript RAM. Old
movies are removed from the cache when a new movie is selected, and logout clears
the cache. **Clear device downloads** also removes saved chunks; **Retry download**
continues using any surviving chunks. Storage limits, private browsing, OS eviction,
and background restrictions can prevent or remove downloads. If persistent storage
is unavailable/full, playback falls back to on-demand streaming and reports that
condition. Plain HTTP on a LAN does not support service workers: use HTTPS on the
VPS for download-ahead. Keep the page visible while downloading on iPhone.

This is a playback cache, not an offline room: authorization and the shared clock
still require the server. Losing the room connection pauses playback even when
media is cached. A completed download avoids further media-byte network traffic
while its chunks remain saved, but media authorization checks still use the network.
Full caching does not measure or eliminate a device’s acoustic output latency.

When a connected playback device disconnects, experiences a persistent buffer
stall, is paused using native controls, or fails playback, the room pauses and stays
paused until someone resumes it. Merely opening the page without connecting
playback does not participate in this barrier. Mode changes on a playing device
also pause the room. Mobile OS termination/connection loss is detected when the
WebSocket closes, which may take time on a broken network.

## Diagnosing playback glitches

Open **Troubleshoot playback** on the affected device and press **Copy playback
report** after a glitch. The report contains recent waiting/seeking/rate-change
and room-control events, current buffer depth, playback speed, download status,
round-trip time, and video frame-drop counters where the browser supports them.
It includes browser identification but no PIN, room code, cookie, or media title.
Reports remain on the device unless you choose to copy and share them.

Playback no longer waits for an IndexedDB write before decoding a fetched chunk.
Download progress still waits for successful storage, with at most four pending
1 MiB write buffers. If storage cannot keep up, unsaved chunks can stream and the
page offers retry. Playback speed adjustments use a one-second median window and
hysteresis instead of writing the decoder rate on every 100 ms sample. App assets
revalidate on reload, and service-worker setup waits for an installing update to
activate before setting up media playback.

Host navigation preserves the current play/pause state. Ten-second jumps use the server position, so device timing adjustments do not change where the room lands. Slider dragging previews a position and commits the room seek on release.

## Series libraries and episode selection

Each room has a retained episode library. Hosts can select multiple files, review titles/order and upload them sequentially. A single server-wide worker prepares accepted uploads in the background and rotates fairly between rooms. Each entry reports queued/preparing/partly ready/fully ready/failed status and prepared duration.

Upload does not select, replace or delete the current episode. Use **Select episode** or **Next episode** to switch; confirm the action, wait for device readiness, then press Play. Switching pauses at zero and invalidates old readiness/control messages. Participants remain in the room. Autoplay is intentionally not included.

Hosts can rename, reorder, retry and delete episodes. Deleting the active episode stops playback. Deleting a whole library requires typing `CONFIRM`; rooms and accounts remain. Admins manage the same libraries from `/admin`. Existing media is migrated automatically without moving its files.

Defaults: `ROOM_STORAGE_MB=51200`, `SERVER_STORAGE_MB=204800`, `MIN_FREE_DISK_MB=512`; values are MiB and account for retained sources plus output. Continue running one Uvicorn worker. Back up the complete data volume before upgrading or rolling back.

See the [series user guide](docs/project/viewers-portal/using-guide.md) and [implementation notes](docs/project/viewers-portal/implementation.md).

## Fast-start preparation and progress

The host uploads the complete source file first. Preparation then publishes the
first playable HLS segments instead of waiting for the entire movie to convert.
The **Movie preparation** progress bar reports actual completed-segment duration,
percentage, and encoder speed. There is no simulated progress timer. Seeking is
restricted to prepared positions while the rest is being generated. Finishing
background preparation does not reload the player or reset the room timeline.

For a common H.264/AAC 480p MP4, the fast path repackages compressed data instead
of re-encoding every frame. This is intended to make the movie playable in seconds
rather than waiting for its two-hour runtime to process. A guaranteed total wait
under two minutes is not possible for every codec/VPS/network; upload time is
separate, and an encoder slower than playback can still require buffering pauses.

A preparation job interrupted by restart is not automatically resumed. Any
published portion remains available and is labeled interrupted. Use Retry preparation
when the retained source is available, or upload the file again. Queued uploads resume automatically. Old fully prepared MP4/M4A files are still supported by this release.
An older application release cannot play the new HLS layout; rolling back across
this change requires restoring the previous media backup or uploading again.

Reference: [FFmpeg HLS muxer](https://ffmpeg.org/ffmpeg-formats.html#hls),
[hls.js](https://github.com/video-dev/hls.js). The pinned hls.js 1.7.4 bundle and
license are checked into `static/vendor/`, so browser playback needs no CDN.

## Admin portal

Open `/admin` to manage rooms, host/participant accounts, passcodes, uploaded media and live playback. Initialize the dedicated administrator password with `python3 -m admin_portal set-password` (or `docker compose exec teamwatch python -m admin_portal set-password`). The username is `hellometora@gmail.com`; no default admin password is supplied.

See [Admin portal setup and operation](docs/project/admin-portal/README.md) for persistence, recovery, API architecture and verification details. Existing room settings are imported once and subsequently managed in the portal.
