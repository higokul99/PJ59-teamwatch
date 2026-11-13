"""Persistent episode libraries and a single, fair preparation worker.

The encoder uses the proven room pipeline in an isolated runtime. Its publication
callback updates library records, never selects/replaces the live room's media.
"""
import asyncio
import importlib.util
import json
import logging
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from media_pipeline import finish_partial

log = logging.getLogger(__name__)


class EditEpisode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)


class EpisodeOrder(BaseModel):
    ids: list[str] = Field(max_length=1000)


class DeleteEpisodes(BaseModel):
    confirmation: str


class Library:
    def __init__(self, manager):
        self.manager = manager
        self.task = None
        self.encoder_task = None
        self.running = None
        self.stopping = False
        self.last_room = None
        self.mutation = asyncio.Lock()
        self.quota_lock = asyncio.Lock()
        self.uploading = set()
        self.clearing = set()
        self.room_limit = int(os.getenv('ROOM_STORAGE_MB', '51200')) * 1048576
        self.server_limit = int(os.getenv('SERVER_STORAGE_MB', '204800')) * 1048576
        self.minimum_free = int(os.getenv('MIN_FREE_DISK_MB', '512')) * 1048576
        self.usage = {}
        with manager.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, room_id TEXT NOT NULL, title TEXT NOT NULL,
                ordinal INTEGER NOT NULL, status TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 1,
                asset_id TEXT NOT NULL, source TEXT, media TEXT, progress TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS episodes_room ON episodes(room_id, ordinal);
            CREATE TABLE IF NOT EXISTS episode_selection (
                room_id TEXT PRIMARY KEY, episode_id TEXT, revision INTEGER NOT NULL DEFAULT 0);
            ''')

    def records(self, room=None):
        with self.manager.db() as db:
            rows = db.execute('SELECT * FROM episodes'+(' WHERE room_id=?' if room else '')+' ORDER BY ordinal,created', (room,) if room else ())
            return [dict(r) for r in rows]

    def get(self, room, ident):
        record = next((r for r in self.records(room) if r['id'] == ident), None)
        if not record:
            raise HTTPException(404, 'Episode not found in this room.')
        return record

    def selection(self, room):
        with self.manager.db() as db:
            row = db.execute('SELECT * FROM episode_selection WHERE room_id=?', (room,)).fetchone()
        return dict(row) if row else None

    def view(self, room):
        selected = self.selection(room) or {}
        items = []
        for row in self.records(room):
            meta = json.loads(row['media']) if row['media'] else None
            progress = json.loads(row['progress'])
            items.append({'id': row['id'], 'title': row['title'], 'ordinal': row['ordinal'],
                          'status': row['status'], 'error': row['error'], 'generation': row['generation'],
                          'media_id': row['asset_id'], 'duration': (meta or {}).get('duration', progress.get('total_seconds', 0)),
                          'prepared_seconds': (meta or {}).get('available_duration', progress.get('prepared_seconds', 0)),
                          'percent': progress.get('percent', 100 if (meta or {}).get('complete') else 0),
                          'playable': bool(meta) and row['status'] not in ('deleting', 'cleanup_pending', 'queued', 'uploading'),
                          'active': row['id'] == selected.get('episode_id'), 'retryable': row['status']=='failed' and bool(row['source'])})
        return {'episodes': items, 'active_episode_id': selected.get('episode_id'),
                'selection_revision': selected.get('revision', 0),
                'storage': {'used_bytes': self.usage.get(room, 0), 'room_limit_bytes': self.room_limit,
                            'server_used_bytes': sum(self.usage.values()), 'server_limit_bytes': self.server_limit,
                            'file_limit_bytes': self.manager.root.MAX_UPLOAD}}

    def migrate(self, runtime, room):
        """Idempotently import a legacy current.json without touching its files."""
        selected = self.selection(room)
        if selected is None:
            meta = runtime.media
            with self.manager.db() as db:
                ident = None
                if meta:
                    ident = secrets.token_hex(12)
                    value = dict(meta, episode_id=ident)
                    status = 'ready' if meta.get('complete', meta.get('format') != 'hls') else 'failed'
                    db.execute('INSERT INTO episodes(id,room_id,title,ordinal,status,asset_id,media,progress,created) VALUES(?,?,?,?,?,?,?,?,?)',
                               (ident, room, meta.get('name', 'Imported movie'), 0, status, meta['id'], json.dumps(value), json.dumps(runtime.processing), time.time()))
                db.execute('INSERT INTO episode_selection VALUES(?,?,0)', (room, ident))
            selected = self.selection(room)
        runtime.media = None
        if selected['episode_id']:
            try:
                row = self.get(room, selected['episode_id'])
                if row['media'] and row['status'] not in ('deleting', 'cleanup_pending'):
                    meta = json.loads(row['media'])
                    expected = runtime.DATA/meta['id']/('master.m3u8' if meta.get('format')=='hls' else 'audio.m4a')
                    if expected.is_file():
                        runtime.media = meta
                        runtime.processing = json.loads(row['progress'])
                    else:
                        with self.manager.db() as db:
                            db.execute("UPDATE episodes SET status='failed',media=NULL,error='Prepared files are missing. Retry or reupload.' WHERE id=?",(row['id'],))
            except HTTPException:
                pass
        runtime.state.update(playing=False, position=0, selection_revision=selected['revision'])

    def scan_usage(self):
        usage = {}
        root = self.manager.root.DATA
        for room in self.manager.rows('rooms'):
            base = root if room['id']=='default' else root/'rooms'/room['id']
            total = 0
            if base.exists():
                for path in base.iterdir():
                    if room['id']=='default' and path.name=='rooms':
                        continue
                    if path.is_symlink():
                        continue
                    if path.is_file():
                        total += path.stat().st_size
                    elif path.is_dir():
                        total += sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())
            usage[room['id']] = total
        return usage

    async def refresh_usage(self):
        async with self.quota_lock:
            self.usage = await asyncio.to_thread(self.scan_usage)

    def check_space(self, room, additional=0):
        # Upload check/write is serialized under quota_lock; encoder usage is sampled.
        if self.usage.get(room, 0)+additional > self.room_limit:
            raise HTTPException(413, 'Room storage limit reached. Delete episodes or increase the quota.')
        if sum(self.usage.values())+additional > self.server_limit:
            raise HTTPException(507, 'Server storage limit reached.')
        if shutil.disk_usage(self.manager.root.DATA).free-additional < self.minimum_free:
            raise HTTPException(507, 'Server disk space is low. Ask the administrator to free space.')

    async def start(self):
        if self.task and not self.task.done():
            return
        self.stopping = False
        for room in self.manager.rows('rooms'):
            runtime = await self.manager.runtime(room['id'])
            self.migrate(runtime, room['id'])
        # Never silently append to an interrupted playlist. Preserve its playable prefix.
        with self.manager.db() as db:
            db.execute("UPDATE episodes SET status='failed',error='Interrupted by restart. Retry preparation or reupload.' WHERE status IN ('uploading','preparing','partial')")
        for record in self.records():
            if record['status']=='failed' and record['media']:
                meta=json.loads(record['media'])
                if meta.get('preparing'):
                    meta['preparing']=False
                    runtime = await self.manager.runtime(record['room_id'])
                    try:
                        await asyncio.to_thread(finish_partial, runtime.DATA/record['asset_id'], meta.get('has_video',False))
                    except OSError:
                        log.warning('Could not finalize interrupted episode %s', record['id'])
                    progress=json.loads(record['progress'])
                    progress.update(status='error',message=record['error'] or 'Preparation interrupted. Retry to finish.')
                    with self.manager.db() as db:
                        db.execute('UPDATE episodes SET media=?,progress=? WHERE id=?',(json.dumps(meta),json.dumps(progress),record['id']))
        for room in self.manager.rows('rooms'):
            self.migrate(await self.manager.runtime(room['id']),room['id'])
        await self.refresh_usage()
        self.task = asyncio.create_task(self.worker())

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    def pick(self):
        queued = [r for r in self.records() if r['status']=='queued']
        rooms = list(dict.fromkeys(r['room_id'] for r in queued))
        if not rooms:
            return None
        if self.last_room in rooms:
            index = rooms.index(self.last_room)
            rooms = rooms[index+1:]+rooms[:index+1]
        room = rooms[0]
        candidates = [r for r in queued if r['room_id']==room]
        selected = (self.selection(room) or {}).get('episode_id')
        active = next((r for r in self.records(room) if r['id']==selected), None)
        candidates.sort(key=lambda r: (0 if r['id']==selected else 1 if not active or r['ordinal']>active['ordinal'] else 2, r['ordinal']))
        return candidates[0]

    async def worker(self):
        while not self.stopping:
            record = self.pick()
            if not record:
                await asyncio.sleep(.25)
                continue
            self.last_room = record['room_id']
            try:
                async with self.mutation:
                    current = self.get(record['room_id'], record['id'])
                    if current['status'] != 'queued':
                        continue
                    with self.manager.db() as db:
                        db.execute("UPDATE episodes SET status='preparing',error='' WHERE id=?", (record['id'],))
                    self.running = record['id']
                    self.encoder_task = asyncio.create_task(self.prepare(record))
                await self.encoder_task
            except asyncio.CancelledError:
                if self.stopping or asyncio.current_task().cancelling():
                    if self.encoder_task:
                        self.encoder_task.cancel()
                        await asyncio.gather(self.encoder_task, return_exceptions=True)
                    raise
            except Exception:
                log.exception('Episode preparation failed: %s', record['id'])
                with self.manager.db() as db:
                    db.execute("UPDATE episodes SET status='failed',error='Preparation failed. Check storage and retry.' WHERE id=? AND status NOT IN ('deleting','cleanup_pending')", (record['id'],))
            finally:
                self.running = None
                self.encoder_task = None

    async def prepare(self, record):
        room, ident = record['room_id'], record['id']
        runtime = await self.manager.runtime(room)
        spec = importlib.util.spec_from_file_location('episode_encoder_'+ident, runtime.BASE/'app.py')
        encoder = importlib.util.module_from_spec(spec)
        encoder.IS_ROOM_RUNTIME = True
        encoder.ROOM_DATA = runtime.DATA
        spec.loader.exec_module(encoder)
        encoder.KEEP_UPLOAD_SOURCE = True
        encoder.save_media = lambda value: None
        async def publish():
            current = self.get(room, ident)
            if current['generation'] != record['generation'] or current['status'] in ('deleting', 'cleanup_pending'):
                return
            progress = dict(encoder.processing)
            meta = dict(encoder.media, episode_id=ident, name=current['title']) if encoder.media else None
            status = 'failed' if progress.get('status')=='error' else 'ready' if meta and meta.get('complete') else 'partial' if meta else 'preparing'
            with self.manager.db() as db:
                db.execute('UPDATE episodes SET status=?,media=?,progress=?,error=? WHERE id=? AND generation=?',
                           (status,json.dumps(meta) if meta else None,json.dumps(progress),progress.get('message','') if status=='failed' else '',ident,record['generation']))
            if (self.selection(room) or {}).get('episode_id') == ident and meta:
                runtime.media = meta
                runtime.processing = progress
                if status=='failed' and runtime.state['playing']:
                    runtime.control({'action':'pause','reason':'Preparation stopped. Only the prepared portion is available.'})
                runtime.save_media(meta)
            await runtime.broadcast()
        encoder.broadcast = publish
        work = asyncio.create_task(encoder.process(runtime.DATA/record['source'], record['asset_id'], record['title']))
        try:
            while not work.done():
                await asyncio.sleep(.25)
                await self.refresh_usage()
                self.check_space(room)
            await work
        except HTTPException as exc:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            with self.manager.db() as db:
                db.execute("UPDATE episodes SET status='failed',error=? WHERE id=? AND status NOT IN ('deleting','cleanup_pending')", (exc.detail,ident))
        finally:
            if not work.done():
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
            await self.refresh_usage()

    async def upload(self, room, request):
        runtime = await self.manager.runtime(room)
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            raise HTTPException(503, 'FFmpeg and FFprobe are required.')
        async with self.mutation:
            if room in self.uploading or room in self.clearing:
                raise HTTPException(409, 'An upload or library cleanup is running in this room.')
            self.uploading.add(room)
        ident, asset = secrets.token_hex(12), secrets.token_hex(12)
        source = ident+'.upload'
        path = runtime.DATA/source
        try:
            await self.refresh_usage()
            self.check_space(room)
            size = 0
            with self.manager.db() as db:
                ordinal = max((r['ordinal'] for r in self.records(room)), default=-1)+1
                db.execute('INSERT INTO episodes(id,room_id,title,ordinal,status,asset_id,source,created) VALUES(?,?,?,?,?,?,?,?)',
                           (ident,room,request.query_params.get('name','Episode')[:200] or 'Episode',ordinal,'uploading',asset,source,time.time()))
            with path.open('xb') as target:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size>runtime.MAX_UPLOAD:
                        raise HTTPException(413, 'File exceeds the upload limit.')
                    async with self.quota_lock:
                        self.check_space(room,len(chunk))
                        await asyncio.to_thread(target.write,chunk)
                        self.usage[room] = self.usage.get(room,0)+len(chunk)
            if not size:
                raise HTTPException(400,'Choose a non-empty media file.')
            with self.manager.db() as db:
                db.execute("UPDATE episodes SET status='queued' WHERE id=?",(ident,))
            return {'id':ident,'status':'queued'}
        except BaseException:
            cleanup_failed = False
            try:
                path.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
            with self.manager.db() as db:
                db.execute('UPDATE episodes SET status=?,source=?,error=? WHERE id=?',
                           ('cleanup_pending' if cleanup_failed else 'failed',source if cleanup_failed else None,
                            'Upload cleanup failed. Retry deletion.' if cleanup_failed else 'Upload interrupted or rejected. Select the file again.',ident))
            raise
        finally:
            self.uploading.discard(room)
            await self.refresh_usage()
            await runtime.broadcast()

    async def select(self, room, ident):
        async with self.mutation:
            row = self.get(room, ident)
            if not row['media'] or row['status'] in ('queued','uploading','deleting','cleanup_pending'):
                raise HTTPException(409,'This episode does not have playable segments yet.')
            runtime = await self.manager.runtime(room)
            meta = json.loads(row['media'])
            runtime.save_media(meta)  # Keep the legacy manifest readable for rollback.
            with self.manager.db() as db:
                db.execute('UPDATE episode_selection SET episode_id=?,revision=revision+1 WHERE room_id=?',(ident,room))
            runtime.media = meta
            runtime.processing = json.loads(row['progress'])
            runtime.reset_playback('Episode selected. Connect playback and wait for devices before pressing Play.')
            runtime.state['selection_revision'] = self.selection(room)['revision']
        await runtime.broadcast()
        return runtime.snapshot()

    async def rename(self, room, ident, title):
        async with self.mutation:
            row = self.get(room,ident)
            meta = json.loads(row['media']) if row['media'] else None
            if meta:
                meta['name'] = title
            with self.manager.db() as db:
                db.execute('UPDATE episodes SET title=?,media=? WHERE id=?',(title,json.dumps(meta) if meta else None,ident))
            runtime = await self.manager.runtime(room)
            if runtime.media and runtime.media.get('episode_id')==ident:
                runtime.media = meta
                runtime.save_media(meta)
        await runtime.broadcast()
        return {'ok':True}

    async def reorder(self, room, ids):
        async with self.mutation:
            current = [r['id'] for r in self.records(room)]
            if len(ids)!=len(set(ids)) or set(ids)!=set(current):
                raise HTTPException(409,'Episode list changed. Refresh and reorder the complete list.')
            with self.manager.db() as db:
                for ordinal,ident in enumerate(ids):
                    db.execute('UPDATE episodes SET ordinal=? WHERE id=?',(ordinal,ident))
        await (await self.manager.runtime(room)).broadcast()
        return {'ok':True}

    async def retry(self, room, ident):
        async with self.mutation:
            row = self.get(room,ident)
            runtime = await self.manager.runtime(room)
            if row['status']!='failed' or not row['source'] or not (runtime.DATA/row['source']).is_file():
                raise HTTPException(409,'No retryable source. Upload this episode again.')
            if (self.selection(room) or {}).get('episode_id')==ident:
                with self.manager.db() as db:
                    db.execute('UPDATE episode_selection SET episode_id=NULL,revision=revision+1 WHERE room_id=?',(room,))
                runtime.media = None
                runtime.reset_playback('Retrying preparation. Select the episode again when ready.')
                runtime.state['selection_revision']=self.selection(room)['revision']
                (runtime.DATA/'current.json').unlink(missing_ok=True)
            await self.refresh_usage()
            self.check_space(room)
            old = runtime.DATA/row['asset_id']
            if old.exists():
                await asyncio.to_thread(shutil.rmtree,old)
            with self.manager.db() as db:
                db.execute("UPDATE episodes SET status='queued',generation=generation+1,asset_id=?,media=NULL,progress='{}',error='' WHERE id=?",(secrets.token_hex(12),ident))
        await runtime.broadcast()
        return {'ok':True}

    async def delete(self, room, ident):
        async with self.mutation:
            if room in self.uploading:
                raise HTTPException(409,'Wait for this room’s upload to finish before deleting episodes.')
            row = self.get(room,ident)
            runtime = await self.manager.runtime(room)
            with self.manager.db() as db:
                db.execute("UPDATE episodes SET status='deleting',generation=generation+1 WHERE id=?",(ident,))
            if self.running==ident and self.encoder_task:
                self.encoder_task.cancel()
                await asyncio.gather(self.encoder_task,return_exceptions=True)
            if (self.selection(room) or {}).get('episode_id')==ident:
                # DB tombstone already prevents access even if filesystem cleanup fails.
                with self.manager.db() as db:
                    db.execute('UPDATE episode_selection SET episode_id=NULL,revision=revision+1 WHERE room_id=?',(room,))
                runtime.media = None
                runtime.processing = {'status':'idle','message':'Episode deleted. Select another episode.'}
                runtime.reset_playback('Episode deleted.')
                runtime.state['selection_revision']=self.selection(room)['revision']
            try:
                if not runtime.media:
                    (runtime.DATA/'current.json').unlink(missing_ok=True)
                folder = runtime.DATA/row['asset_id']
                if folder.exists():
                    await asyncio.to_thread(shutil.rmtree,folder)
                if row['source']:
                    (runtime.DATA/row['source']).unlink(missing_ok=True)
            except OSError:
                with self.manager.db() as db:
                    db.execute("UPDATE episodes SET status='cleanup_pending',error='Files could not be removed. Retry deletion.' WHERE id=?",(ident,))
                await runtime.broadcast()
                raise HTTPException(500,'Playback access revoked, but cleanup failed. Retry deletion.')
            with self.manager.db() as db:
                db.execute('DELETE FROM episodes WHERE id=?',(ident,))
        await self.refresh_usage()
        await runtime.broadcast()
        return {'ok':True}

    async def clear(self, room):
        async with self.mutation:
            if room in self.uploading or room in self.clearing:
                raise HTTPException(409, 'Wait for uploads or library cleanup to finish.')
            self.clearing.add(room)
        failures=[]
        try:
            for row in self.records(room):
                try:
                    await self.delete(room,row['id'])
                except HTTPException as exc:
                    failures.append({'id':row['id'],'error':exc.detail})
        finally:
            self.clearing.discard(room)
        if failures:
            raise HTTPException(409, 'Some episodes could not be removed. Retry after uploads finish or storage permissions are fixed.')
        return {'ok':True}


def install_room(runtime, service, room):
    runtime.library_runtime = runtime
    runtime.library_service = service
    runtime.library_room = room
    router = APIRouter(prefix='/api/episodes')
    @router.get('')
    async def listing(request: Request):
        runtime.auth(request)
        return service.view(room)
    @router.post('',status_code=202)
    async def upload(request: Request):
        runtime.auth(request,host=True)
        return await service.upload(room,request)
    @router.put('/order')
    async def order(body: EpisodeOrder,request: Request):
        runtime.auth(request,host=True)
        return await service.reorder(room,body.ids)
    @router.delete('')
    async def clear(body: DeleteEpisodes,request: Request):
        runtime.auth(request,host=True)
        if body.confirmation!='CONFIRM':
            raise HTTPException(422,'Type CONFIRM to delete the library.')
        return await service.clear(room)
    @router.patch('/{ident}')
    async def rename(ident: str,body: EditEpisode,request: Request):
        runtime.auth(request,host=True)
        return await service.rename(room,ident,body.title)
    @router.post('/{ident}/select')
    async def select(ident: str,request: Request):
        runtime.auth(request,host=True)
        return await service.select(room,ident)
    @router.post('/{ident}/retry')
    async def retry(ident: str,request: Request):
        runtime.auth(request,host=True)
        return await service.retry(room,ident)
    @router.delete('/{ident}')
    async def delete(ident: str,request: Request):
        runtime.auth(request,host=True)
        return await service.delete(room,ident)
    runtime.app.include_router(router)
