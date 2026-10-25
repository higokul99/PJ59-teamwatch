# TeamWatch

For the Metora VPS layout and Nginx deployment, see [deploy/README.md](deploy/README.md).

One private room for a projector and everyone's headphones. Python/FastAPI serves a responsive browser interface, protected media, and a shared playback timeline over WebSockets.

## Quick start with Docker

```sh
cp .env.example .env
# Edit .env, set SESSION_SECRET, and change PINs for a public deployment.
docker compose up -d --build
```

Open http://localhost:8000. Default room code: **8889292**, viewer PIN: **8989**, host PIN: **9292**. The dictated code had seven digits despite the request describing eight; change `ROOM_CODE` to any 6–8 digit code in `.env` if needed. All devices use the same room code. PIN determines the role. This first version has one shared room, one host role, and one active movie, not separate accounts or multiple simultaneous rooms.

For a VPS, put Caddy (example config included) or another HTTPS reverse proxy in front of port 8000. Point a domain to the VPS, allow ports 80/443, set `COOKIE_SECURE=true`, and restart the container. Keep port 8000 bound to localhost. The proxy must forward WebSocket upgrades and preserve the Host header. Set its upload limit at least as high as `MAX_UPLOAD_MB`. If using Nginx, also configure `client_max_body_size`, upgrade headers, and suitable upload/read timeouts. Avoid a CDN with a smaller upload limit.

For a trusted LAN test, set `BIND_ADDRESS=0.0.0.0` and `COOKIE_SECURE=false`, restart, and open `http://YOUR_COMPUTER_LAN_IP:8000` from phones on the same Wi-Fi. `localhost` on a phone points to that phone, not the server. Use HTTPS for access over the internet.

## Movie night

1. Join using the host PIN. Choose a file, then **Upload & prepare**. Wait until preparation finishes. Most formats ffmpeg can decode are accepted, including MKV; an audio track is required. Audio-only files are supported too.
2. Open the same URL on the projector and choose **Video only**. The server sends a video file with no audio track.
3. Friends join with the viewer PIN and select **Audio only** on their phones, or **Video + audio** to watch on their own screens.
4. Everyone taps **Connect playback** when the movie is ready. The host does this too if watching or listening on that device. The host can also control the room without connecting local playback.
5. The host presses **Play together**. Play, pause, restart, and seeking affect everyone. Late arrivals catch up to the current room position. Reconnecting devices catch up automatically once their browser permits playback.
6. Keep phone browser pages visible and screens awake. The app requests a screen wake lock where supported. Background playback, locked screens, battery-saving modes, and browser timer throttling can interfere with synchronization. Switching modes or replacing a movie requires tapping Connect playback again.

## Synchronization and bandwidth

- The server owns the position, play state, and start timestamp. Play and seek while playing schedule a start 1.5 seconds ahead.
- Devices sample server clock offset using WebSocket round-trip measurements and the lowest-latency recent sample. A monotonic browser clock avoids local wall-clock jumps.
- A deadline timer starts playback at the shared timestamp. Every 100 ms, the client compares its media time with the shared timeline. Small errors use up to ±8% playback-rate adjustment; errors above 800 ms seek to catch up, with a two-second cooldown to avoid repeated decoder stalls. Clock offset is sampled several times immediately on connection. Use Resync this device for an immediate clock refresh and playback correction. A slow/buffering device catches up independently rather than pausing the entire room.
- ffmpeg produces an H.264 video-only MP4, AAC audio-only M4A, and combined MP4 with fast-start metadata. Tracks use the same input timestamp origin. HTTP byte-range requests let browsers buffer and seek without downloading the whole file. This is progressive, on-demand streaming after preparation, not live transcoding or adaptive HLS.
- Audio-only clients download approximately 160 kbps plus overhead. Video is capped at 1920 pixels wide, with variable bitrate. Each viewer consumes outbound VPS bandwidth independently.
- There is **no guarantee of identical acoustic latency**. This is best-effort browser synchronization, not sample-accurate multi-device audio. Bluetooth, hardware, buffering, and mobile browser restrictions introduce delay. Use per-device adjustment (±2000 ms); positive values advance playback to compensate for slow audio output. Start with +150 ms for late Bluetooth audio and adjust by ear. Reported drift measures browser media position, not sound reaching headphones.

## Local Python development

Use the requested shared environment:

```sh
cd /Applications/XAMPP/xamppfiles/htdocs/github/7-python/3-teamwatch
/Applications/XAMPP/xamppfiles/htdocs/github/7-python/venv/bin/python -m pip install -r requirements.txt
# Install ffmpeg with your system package manager (ffmpeg and ffprobe must be on PATH).
/Applications/XAMPP/xamppfiles/htdocs/github/7-python/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000 --ws-max-size 4096
```

Local Python reads environment variables, not `.env` automatically. Defaults work for development. `DATA_DIR` defaults to `./data`. Docker Compose loads `.env` for you. Always run **one worker and one replica**: room state and connected peers are in memory. Multiple workers require an external shared state/broadcast service.

## Operations

- Uploads default to a 10 GiB limit and stream to disk with bounded memory. Only one upload/conversion runs at a time. Preparation can take minutes to hours depending on movie length and VPS CPU. ffmpeg video encoding is limited to two threads.
- Allow several times the upload size in free storage: source, video, audio, combined output, and the previous movie may coexist during conversion. The source is deleted after preparation. Successfully replaced media is deleted; failed conversion folders/logs remain for diagnosis and can be manually cleaned when idle.
- The Docker named volume retains the prepared movie across container restarts. Playback restarts paused at zero; interrupted uploads/conversions are not resumed. Repeated abrupt shutdowns can leave orphaned files needing cleanup.
- Sessions expire after 24 hours. Set a stable random `SESSION_SECRET` to preserve signed sessions across restarts; leaving it empty generates a new secret each startup. Logout revokes the session in memory and disconnects its sockets. Rotate the secret to invalidate all sessions.
- Host/viewer PINs are shared credentials for a small trusted group. Login is rate-limited per source IP (10 failed attempts/5 minutes), media requires a session, mutations require same-origin requests, and only hosts can upload/control playback. Behind a proxy, configure trusted proxy IPs correctly to preserve client IP rate limiting. Default proxy trust is loopback only.
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

Browser synchronization regressions can also be run with `node --test tests/sync.test.cjs`. Node.js is installed only in the Docker test stage.
