"""TeamWatch: one room, one authoritative timeline, three device modes."""
import asyncio
import hashlib
import hmac
import json
import math
import os
import secrets
import shutil
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv('DATA_DIR', str(BASE / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
ROOM_CODE = os.getenv('ROOM_CODE', '8889292')
VIEWER_PIN = os.getenv('VIEWER_PIN', '8989')
HOST_PIN = os.getenv('HOST_PIN', '9292')
if HOST_PIN == VIEWER_PIN:
    raise RuntimeError('Host and viewer PINs must differ')
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
# Reject playlist/container indirection to network or unrelated server files.
INPUT_OPTIONS = ['-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm,avi,mp3,wav,flac,ogg,aac,mpeg,mpegts,asf,aiff']
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_MB', '10240')) * 1024 * 1024
SECRET = os.getenv('SESSION_SECRET', '') or secrets.token_hex(32)
TTL = 24 * 60 * 60
sessions_revoked = {}
attempts = defaultdict(deque)
peers = {}
peer_status = {}
job = None
upload_busy = False
media = None
processing = {'status': 'idle', 'message': 'Upload a movie to begin.'}
state = {'playing': False, 'position': 0.0, 'anchor': time.time(), 'revision': 0}


def token_for(role):
    payload = f'{role}:{int(time.time()) + TTL}:{secrets.token_hex(16)}'
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f'{payload}:{signature}'


def role_for(token):
    try:
        role, expiry, nonce, signature = token.split(':')
        payload = f'{role}:{expiry}:{nonce}'
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if role in ('host', 'viewer') and int(expiry) > time.time() and token not in sessions_revoked and hmac.compare_digest(expected, signature):
            return role
    except (ValueError, AttributeError, TypeError):
        pass
    return None


def auth(request, host=False):
    role = role_for(request.cookies.get('session'))
    if not role:
        raise HTTPException(401, 'Join the room first.')
    if host and role != 'host':
        raise HTTPException(403, 'Only the host can do this.')
    return role


def same_origin(headers):
    origin = headers.get('origin')
    return bool(origin and urlsplit(origin).netloc == headers.get('host'))


def position(now=None):
    now = time.time() if now is None else now
    elapsed = max(0, now - state['anchor']) if state['playing'] else 0
    return min((media or {}).get('duration', 0), state['position'] + elapsed)


def snapshot():
    return {'type': 'state', 'timeline': state.copy(), 'media': media,
            'processing': processing.copy(), 'count': len(peers),
            'participants': [peer_status.get(ws, {'active': False, 'ready': False}) for ws in peers],
            'server_time': time.time()}


async def broadcast():
    if peers:
        await asyncio.gather(*(send(ws, snapshot()) for ws in list(peers)), return_exceptions=True)


async def send(ws, value):
    try:
        await asyncio.wait_for(ws.send_json(value), 2)
    except Exception:
        peers.pop(ws, None)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


async def process(source, ident, name):
    global media, processing, upload_busy
    folder = DATA / ident
    folder.mkdir()
    proc = None
    try:
        processing = {'status': 'processing', 'message': 'Preparing synchronized video and audio. Large movies can take a while.'}
        await broadcast()
        proc = await asyncio.create_subprocess_exec('ffprobe', '-v', 'error', *INPUT_OPTIONS, '-show_format', '-show_streams', '-of', 'json', str(source), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), 60)
        if proc.returncode:
            raise ValueError('The uploaded file could not be read as media.')
        info = json.loads(out)
        duration = float(info['format']['duration'])
        has_video = any(s['codec_type'] == 'video' for s in info['streams'])
        has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
        if not has_audio or not math.isfinite(duration) or duration <= 0:
            raise ValueError('Choose a movie or song with an audio track and a finite duration.')
        # All outputs share the input timestamp origin. Preserve relative A/V offsets.
        args = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-copyts', '-start_at_zero', *INPUT_OPTIONS, '-i', str(source)]
        if has_video:
            args += ['-map', '0:v:0', '-an', '-vf', "scale=w='trunc(min(1920,iw)/2)*2':h=-2", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart', str(folder / 'video.mp4')]
        args += ['-map', '0:a:0', '-vn', '-af', 'aresample=async=1:first_pts=0', '-c:a', 'aac', '-b:a', '160k', '-ac', '2', '-movflags', '+faststart', str(folder / 'audio.m4a')]
        # Log to disk, not RAM; ffmpeg diagnostics can be large for damaged inputs.
        with (folder / 'conversion.log').open('wb') as log:
            proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=log)
            await proc.wait()
        if proc.returncode:
            raise ValueError('Conversion failed. Try another file; see the server conversion log.')
        if has_video:
            with (folder / 'conversion.log').open('ab') as log:
                proc = await asyncio.create_subprocess_exec('ffmpeg', '-nostdin', '-y', '-v', 'error', '-copyts', '-i', str(folder / 'video.mp4'), '-i', str(folder / 'audio.m4a'), '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', '-movflags', '+faststart', str(folder / 'combined.mp4'), stdout=asyncio.subprocess.DEVNULL, stderr=log)
                await proc.wait()
            if proc.returncode:
                raise ValueError('Could not combine the movie tracks.')
        new_media = {'id': ident, 'name': name[:200], 'duration': duration, 'has_video': has_video}
        temp = DATA / 'current.tmp'
        temp.write_text(json.dumps(new_media))
        temp.replace(DATA / 'current.json')
        old = media
        media = new_media
        state.update(playing=False, position=0.0, anchor=time.time(), revision=state['revision'] + 1)
        processing = {'status': 'ready', 'message': 'Ready. Connect playback on each device, then press Play.'}
        if old:
            shutil.rmtree(DATA / old['id'], ignore_errors=True)
    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as exc:
        processing = {'status': 'error', 'message': str(exc) if isinstance(exc, ValueError) else 'Media processing failed. Check ffmpeg installation and available disk space.'}
    finally:
        source.unlink(missing_ok=True)
        upload_busy = False
        await broadcast()


@asynccontextmanager
async def lifespan(app):
    global media, processing
    manifest = DATA / 'current.json'
    if manifest.exists():
        try:
            candidate = json.loads(manifest.read_text())
            if (DATA / candidate['id'] / 'audio.m4a').exists():
                media = candidate
                processing = {'status': 'ready', 'message': 'Movie restored. Playback starts paused.'}
        except (ValueError, KeyError):
            pass
    yield
    if job and not job.done():
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


app = FastAPI(lifespan=lifespan)


@app.middleware('http')
async def protections(request, call_next):
    if request.method in ('POST', 'PUT', 'DELETE') and not same_origin(request.headers):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': 'Same-origin request required.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
async def index():
    return FileResponse(BASE / 'static/index.html')


@app.get('/health')
async def health():
    return {'ok': True, 'ffmpeg': bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))}


@app.post('/api/join')
async def join(request: Request):
    ip = request.client.host
    now = time.time()
    # Expire unused keys so the limiter stays bounded over long-running deployments.
    for key in list(attempts):
        if not attempts[key] or attempts[key][-1] < now - 300:
            del attempts[key]
    recent = attempts[ip]
    while recent and recent[0] < now - 300:
        recent.popleft()
    if len(recent) >= 10:
        raise HTTPException(429, 'Too many attempts. Try again in five minutes.')
    try:
        body = await request.json()
        code, pin = str(body.get('code', '')), str(body.get('pin', ''))
    except (ValueError, AttributeError):
        recent.append(now)
        raise HTTPException(400, 'Invalid login request.')
    if not code.isascii() or not pin.isascii():
        recent.append(now)
        raise HTTPException(401, 'Incorrect room code or PIN.')
    role = 'host' if hmac.compare_digest(pin, HOST_PIN) else 'viewer' if hmac.compare_digest(pin, VIEWER_PIN) else None
    if not hmac.compare_digest(code, ROOM_CODE) or not role:
        recent.append(now)
        raise HTTPException(401, 'Incorrect room code or PIN.')
    from fastapi.responses import JSONResponse
    response = JSONResponse({'role': role})
    response.set_cookie('session', token_for(role), httponly=True, secure=SECURE, samesite='strict', max_age=TTL)
    return response


@app.post('/api/logout')
async def logout(request: Request):
    token = request.cookies.get('session')
    if role_for(token):
        sessions_revoked[token] = time.time() + TTL
    for key, expiry in list(sessions_revoked.items()):
        if expiry < time.time():
            del sessions_revoked[key]
    from fastapi.responses import JSONResponse
    response = JSONResponse({'ok': True})
    response.delete_cookie('session')
    for ws, peer_token in list(peers.items()):
        if peer_token == token:
            await ws.close(code=1008)
    return response


@app.get('/api/me')
async def me(request: Request):
    return {'role': auth(request), 'room': ROOM_CODE, **snapshot()}


@app.post('/api/upload')
async def upload(request: Request):
    global upload_busy, job, processing
    auth(request, host=True)
    if upload_busy:
        raise HTTPException(409, 'Another upload is being prepared.')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise HTTPException(503, 'Install ffmpeg and ffprobe, or run the Docker image.')
    upload_busy = True
    ident = secrets.token_hex(12)
    source = DATA / f'{ident}.upload'
    try:
        size = 0
        with source.open('wb') as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, f'Upload limit is {MAX_UPLOAD // 1024 // 1024} MB.')
                await asyncio.to_thread(target.write, chunk)
        if not size:
            raise HTTPException(400, 'The file is empty.')
        name = request.query_params.get('name', 'Movie')
        processing = {'status': 'processing', 'message': 'Upload complete. Preparing media…'}
        job = asyncio.create_task(process(source, ident, name))
        return {'ok': True}
    except BaseException:
        upload_busy = False
        source.unlink(missing_ok=True)
        raise


@app.get('/sw.js')
async def service_worker():
    return FileResponse(BASE / 'static/sw.js', media_type='text/javascript',
                        headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})


@app.get('/api/media/{ident}/{track}')
async def media_details(ident: str, track: str, request: Request):
    auth(request)
    path = media_path(ident, track)
    return {'size': path.stat().st_size, 'type': 'audio/mp4' if track == 'audio.m4a' else 'video/mp4'}


def media_path(ident, track):
    if not media or ident != media['id'] or track not in ('video.mp4', 'audio.m4a', 'combined.mp4'):
        raise HTTPException(404)
    path = DATA / ident / track
    if not path.exists():
        raise HTTPException(404)
    return path


@app.get('/media/{ident}/{track}')
async def stream(ident: str, track: str, request: Request):
    auth(request)
    path = media_path(ident, track)
    return FileResponse(path, media_type='audio/mp4' if track == 'audio.m4a' else 'video/mp4', headers={'Cache-Control': 'private, no-cache'})


def control(body):
    if not media:
        raise ValueError('Upload a movie first.')
    action = body.get('action')
    if action not in ('play', 'pause', 'seek', 'sync'):
        raise ValueError('Unknown playback command.')
    now = time.time()
    pos = position(now)
    if action == 'seek':
        pos = float(body.get('position', 0))
        if not math.isfinite(pos):
            raise ValueError('Invalid seek position.')
        pos = max(0.0, min(media['duration'], pos))
    playing = state['playing'] if action in ('seek', 'sync') else action == 'play'
    if action == 'play' and pos >= media['duration']:
        pos = 0.0
    state.update(position=pos, playing=playing, anchor=now + (1.5 if playing else 0),
                 revision=state['revision'] + 1, reason=body.get('reason', ''))


@app.websocket('/ws')
async def websocket(ws: WebSocket):
    token = ws.cookies.get('session')
    if not role_for(token) or not same_origin(ws.headers):
        await ws.close(code=1008)
        return
    await ws.accept()
    peers[ws] = token
    peer_status[ws] = {'active': False, 'ready': False}
    await broadcast()
    try:
        while True:
            body = await ws.receive_json()
            role = role_for(token)
            if not role:
                await ws.close(code=1008)
                break
            if not isinstance(body, dict):
                continue
            if body.get('type') == 'ping':
                await send(ws, {'type': 'pong', 'sent': body.get('sent'), 'server_time': time.time()})
                await send(ws, snapshot())
            elif body.get('type') == 'status':
                # Readiness is advisory; only devices which enabled playback
                # participate in the play barrier and disconnect-pause rule.
                if not media or body.get('media_id') != media['id']:
                    continue
                peer_status[ws] = {
                    'active': body.get('active') is True,
                    'ready': body.get('ready') is True,
                    'mode': body.get('mode') if body.get('mode') in ('audio', 'video', 'combined') else 'audio',
                    'downloaded': body.get('downloaded') is True,
                }
            elif body.get('type') == 'control':
                action = body.get('action')
                if role != 'host' and action not in ('play', 'pause', 'buffering'):
                    await send(ws, {'type': 'error', 'message': 'Only the host can seek or sync all devices.'})
                    continue
                try:
                    if action == 'buffering':
                        # Ignore a delayed stall event from a previous seek/play.
                        if (not state['playing'] or body.get('revision') != state['revision']
                                or not peer_status.get(ws, {}).get('active')):
                            continue
                        control({'action': 'pause', 'reason': 'A device is buffering. Everyone is paused; press Play when ready.'})
                    elif action == 'play':
                        if any(status.get('active') and not status.get('ready') for peer, status in peer_status.items() if peer in peers):
                            raise ValueError('Wait for connected playback devices to be ready, then press Play again.')
                        control({'action': 'play'})
                    else:
                        control({'action': action, 'position': body.get('position', 0)})
                    await broadcast()
                except (ValueError, TypeError) as exc:
                    await send(ws, {'type': 'error', 'message': str(exc)})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        active = peer_status.pop(ws, {}).get('active')
        peers.pop(ws, None)
        if active and media and state['playing']:
            control({'action': 'pause', 'reason': 'A playback device disconnected. Everyone is paused.'})
        await broadcast()


app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
