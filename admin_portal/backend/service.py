"""Dedicated admin REST API and persistent, isolated room runtimes."""
import asyncio
import hashlib
import hmac
import json
import importlib.util
import os
import re
import secrets
import shutil
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from functools import wraps

from fastapi import HTTPException, Request, Response

from .schemas import Room, NewRoom, User, Confirm, Command

ADMIN_USER = 'hellometora@gmail.com'


def digest(value):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def matches(value, encoded):
    try:
        salt, expected = encoded.split(':')
        actual = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def password_valid(value):
    return (8 <= len(value) <= 16 and re.search('[A-Z]', value) and re.search('[a-z]', value)
            and re.search('[0-9]', value) and re.search(r'[^A-Za-z0-9\s]', value))


def serialized_mutation(method):
    """Keep account validation and writes atomic across asynchronous hashing."""
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self.mutation_lock:
            return await method(self, *args, **kwargs)
    return wrapped


class Manager:
    def __init__(self, root):
        self.root = root
        self.path = root.DATA / 'admin.sqlite3'
        self.runtimes = {'default': root}
        self.sessions = {}
        self.mutation_lock = asyncio.Lock()
        self.password_slots = asyncio.Semaphore(2)
        self.failures = defaultdict(deque)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, room_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, blocked INTEGER NOT NULL, pin_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL);
            ''')
            if not db.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
                db.execute('INSERT INTO rooms VALUES(?,?,?,0)', ('default', root.ROOM_CODE, 'Main room'))
                for role, pin in [('host', root.HOST_PIN), ('viewer', root.VIEWER_PIN)]:
                    db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,0)', (secrets.token_hex(12), 'default', role.title(), role, 0, digest(pin)))
                db.execute("INSERT INTO settings VALUES('initialized','1')")
            configured = os.getenv('ADMIN_PASSWORD_HASH')
            if configured and not self.setting('password', db):
                # Only a hash is accepted in configuration; bootstrap through the CLI below.
                db.execute("INSERT INTO settings VALUES('password',?)", (configured,))
        self.path.chmod(0o600)
        from episode_library import Library
        self.library = Library(self)
        self.attach(root, 'default')

    async def hash_password(self, value):
        async with self.password_slots:
            return await asyncio.to_thread(digest, value)

    async def verify_password(self, value, encoded):
        async with self.password_slots:
            return await asyncio.to_thread(matches, value, encoded)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=0.1)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def setting(self, key, db=None):
        if db is None:
            with self.db() as db:
                return self.setting(key, db)
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else None

    def rows(self, table):
        with self.db() as db:
            return [dict(r) for r in db.execute(f'SELECT * FROM {table}')]

    def room(self, ident):
        row = next((r for r in self.rows('rooms') if r['id'] == ident), None)
        if row is None:
            raise HTTPException(404, 'Room not found.')
        return row

    def audit(self, db, action, target):
        db.execute('INSERT INTO audit(at,action,target) VALUES(?,?,?)', (time.time(), action, target))

    def attach(self, runtime, ident):
        def access(role, nonce):
            try:
                if self.room(ident)['blocked']:
                    return False
            except HTTPException:
                return False
            parts = nonce.split('.')
            users = [u for u in self.rows('users') if u['room_id'] == ident and u['role'] == role and not u['blocked']]
            return any(u['id'] == parts[1] and str(u['version']) == parts[2] for u in users) if len(parts) == 3 else bool(users)

        async def login(code, pin):
            room = self.room(ident)
            if room['blocked'] or room['code'] != code:
                return None
            for user in self.rows('users'):
                if user['room_id'] == ident and not user['blocked'] and await self.verify_password(pin, user['pin_hash']):
                    return user
            return None
        from episode_library import install_room
        install_room(runtime, self.library, ident)
        runtime.access_check = access
        runtime.account_login = login
        runtime.ROOM_CODE = self.room(ident)['code'] if any(r['id'] == ident for r in self.rows('rooms')) else ''

    async def runtime(self, ident):
        self.room(ident)
        if ident not in self.runtimes:
            spec = importlib.util.spec_from_file_location('teamwatch_room_' + ident, self.root.BASE / 'app.py')
            module = importlib.util.module_from_spec(spec)
            module.ROOM_DATA = self.root.DATA / 'rooms' / ident
            module.IS_ROOM_RUNTIME = True
            spec.loader.exec_module(module)
            module.SECRET = hmac.new(self.root.SECRET.encode(), ident.encode(), hashlib.sha256).hexdigest()
            self.attach(module, ident)
            self.runtimes[ident] = module
            module.room_lifespan = module.lifespan(module.app)
            await module.room_lifespan.__aenter__()
        return self.runtimes[ident]

    async def disconnect(self, ident):
        runtime = self.runtimes.get(ident)
        if runtime:
            for ws in list(runtime.peers):
                try:
                    await asyncio.wait_for(ws.close(code=1008), timeout=2)
                except (RuntimeError, asyncio.TimeoutError):
                    runtime.peers.pop(ws, None)
                    runtime.peer_status.pop(ws, None)

    def authenticate(self, token, touch=False):
        session = self.sessions.get(token)
        if not session or time.time() - session['last'] >= 86400 or session['password'] != self.setting('password'):
            self.sessions.pop(token, None)
            raise HTTPException(401, 'Admin sign-in required.')
        if touch:
            session['last'] = time.time()
        return session

    async def require(self, request: Request, response: Response):
        token = request.cookies.get('admin_session')
        self.authenticate(token, touch=True)
        response.set_cookie('admin_session', token, httponly=True, secure=self.root.SECURE, samesite='strict', max_age=86400)

    async def overview(self):
        rooms = []
        devices = []
        for room in self.rows('rooms'):
            runtime = await self.runtime(room['id'])
            rooms.append({**room, 'media': runtime.media, 'processing': runtime.processing,
                          'connected': len(runtime.peers), 'playing': runtime.state['playing'],
                          'position': runtime.position(), 'library': self.library.view(room['id'])})
            for ws, token in list(runtime.peers.items()):
                devices.append({'room_id': room['id'], 'role': runtime.role_for(token),
                                'ip': ws.client.host if ws.client else '', **runtime.peer_status.get(ws, {})})
        users = [{k: v for k, v in u.items() if k not in ('pin_hash', 'version')} for u in self.rows('users')]
        return {'rooms': rooms, 'users': users, 'devices': devices}

    async def clear(self, ident):
        runtime = await self.runtime(ident)
        if self.library.records(ident):
            await self.library.clear(ident)
        # Reuse the viewer portal's cancellation and safe deletion implementation.
        result = await runtime.clear_media()
        # Also remove abandoned/failed uploads; never touch the database or other rooms.
        runtime.upload_busy = runtime.deleting = True
        try:
            for path in runtime.DATA.iterdir():
                if not re.fullmatch(r'[a-f0-9]{24}(?:\.upload)?', path.name):
                    continue
                try:
                    if path.is_dir() and not path.is_symlink():
                        await asyncio.to_thread(shutil.rmtree, path)
                    else:
                        path.unlink(missing_ok=True)
                except OSError:
                    runtime.processing = {'status': 'error', 'message': 'Some media files could not be removed. Check storage permissions and retry.'}
            result['processing'] = runtime.processing.copy()
            return result
        finally:
            runtime.upload_busy = runtime.deleting = False
            await runtime.broadcast()


    async def save_user(self, body, ident=None):
        self.room(body.room_id)
        records = self.rows('users')
        previous = next((u for u in records if u['id'] == ident), None)
        if ident and previous is None:
            raise HTTPException(404, 'Account not found.')
        if not ident and not body.pin:
            raise HTTPException(422, 'Passcode is required.')
        encoded = await self.hash_password(body.pin) if body.pin else previous['pin_hash']
        for u in records:
            if u['id'] != ident and u['room_id'] == body.room_id:
                # Moving without a new PIN cannot safely check uniqueness of salted hashes.
                if body.pin and await self.verify_password(body.pin, u['pin_hash']):
                    raise HTTPException(409, 'Passcode is already used in this room.')
        if previous and previous['room_id'] != body.room_id and not body.pin:
            raise HTTPException(422, 'Set a new passcode when moving an account.')
        ident = ident or secrets.token_hex(12)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO users VALUES(?,?,?,?,?,?,?)',
                       (ident, body.room_id, body.name, body.role, body.blocked, encoded, previous['version'] + 1 if previous else 0))
            self.audit(db, 'user.updated' if previous else 'user.created', ident)
        return ident, previous



    @serialized_mutation
    async def create_room(self, body: NewRoom):
        if body.host_pin == body.viewer_pin:
            raise HTTPException(422, 'Host and participant passcodes must differ.')
        ident = secrets.token_hex(12)
        hashes = [(role, await self.hash_password(pin)) for role, pin in [('host', body.host_pin), ('viewer', body.viewer_pin)]]
        try:
            with self.db() as db:
                db.execute('INSERT INTO rooms VALUES(?,?,?,?)', (ident, body.code, body.name, body.blocked))
                for role, encoded in hashes:
                    db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,0)', (secrets.token_hex(12), ident, role.title(), role, 0, encoded))
                self.audit(db, 'room.created', ident)
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Room code already exists.')
        return self.room(ident)


    @serialized_mutation
    async def edit_room(self, ident: str, body: Room):
        self.room(ident)
        try:
            with self.db() as db:
                db.execute('UPDATE rooms SET code=?,name=?,blocked=? WHERE id=?', (body.code, body.name, body.blocked, ident))
                db.execute('UPDATE users SET version=version+1 WHERE room_id=?', (ident,))
                self.audit(db, 'room.updated', ident)
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Room code already exists.')
        runtime = await self.runtime(ident)
        runtime.ROOM_CODE = body.code
        await self.disconnect(ident)
        return self.room(ident)


    @serialized_mutation
    async def remove_room(self, ident: str):
        result = await self.clear(ident)
        if result['processing'].get('status') == 'error':
            raise HTTPException(500, result['processing']['message'])
        with self.db() as db:
            db.execute('DELETE FROM users WHERE room_id=?', (ident,))
            db.execute('DELETE FROM rooms WHERE id=?', (ident,))
            self.audit(db, 'room.deleted', ident)
        await self.disconnect(ident)
        if ident != 'default':
            runtime = self.runtimes.pop(ident, None)
            if runtime:
                await runtime.room_lifespan.__aexit__(None, None, None)
        return {'ok': True}


    @serialized_mutation
    async def create_user(self, body: User):
        ident, _ = await self.save_user(body)
        return {'id': ident}


    @serialized_mutation
    async def edit_user(self, ident: str, body: User):
        _, previous = await self.save_user(body, ident)
        await self.disconnect(previous['room_id'])
        return {'id': ident}


    @serialized_mutation
    async def remove_user(self, ident: str):
        user = next((u for u in self.rows('users') if u['id'] == ident), None)
        if not user:
            raise HTTPException(404, 'Account not found.')
        with self.db() as db:
            db.execute('DELETE FROM users WHERE id=?', (ident,))
            self.audit(db, 'user.deleted', ident)
        await self.disconnect(user['room_id'])
        return {'ok': True}


    async def clear_media(self, ident: str):
        result = await self.clear(ident)
        with self.db() as db:
            self.audit(db, 'media.deleted', ident)
        return result


    async def clear_all(self, body: Confirm):
        if body.confirmation != 'CONFIRM':
            raise HTTPException(422, 'Type CONFIRM to delete media from all rooms.')
        rooms = self.rows('rooms')
        for room in rooms:
            runtime = await self.runtime(room['id'])
            if runtime.upload_busy or runtime.deleting:
                raise HTTPException(409, 'Wait for uploads/preparation to finish before clearing all rooms.')
        results = []
        for room in rooms:
            try:
                result = await self.clear_media(room['id'])
                results.append({'room_id': room['id'], 'processing': result['processing']})
            except HTTPException as exc:
                results.append({'room_id': room['id'], 'error': exc.detail})
        return {'results': results}


    async def control(self, ident: str, body: Command):
        runtime = await self.runtime(ident)
        try:
            if body.action == 'play' and any(s.get('active') and not s.get('ready') for s in runtime.peer_status.values()):
                raise ValueError('Wait for playback devices to become ready.')
            runtime.control(body.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        await runtime.broadcast()
        with self.db() as db:
            self.audit(db, 'playback.' + body.action, ident)
        return {'ok': True}


    async def upload(self, ident: str, request: Request):
        runtime = await self.runtime(ident)
        with self.db() as db:
            self.audit(db, 'media.upload', ident)
        return await self.library.upload(ident, request)


    async def read_audit(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]

