"""Admin SPA and API routes; services are injected at registration time."""
import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .schemas import Login, Password, Room, NewRoom, User, Confirm, Command
from .service import ADMIN_USER, password_valid

FRONTEND = Path(__file__).resolve().parents[2] / 'static' / 'admin'
logger = logging.getLogger(__name__)


def create_admin_router(manager):
    """Build a router bound to one application service, without global state."""
    root = manager.root
    router = APIRouter(prefix='/api/admin')
    protected = APIRouter(dependencies=[Depends(manager.require)])

    @router.post('/login')
    async def login(body: Login, request: Request):
        now = time.time()
        for key in list(manager.failures):
            if not manager.failures[key] or manager.failures[key][-1] <= now - 600:
                del manager.failures[key]
        if request.client.host not in manager.failures and len(manager.failures) >= 4096:
            raise HTTPException(429, 'Login is busy. Try again later.')
        attempts = manager.failures[request.client.host]
        while attempts and attempts[0] <= now - 600:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, 'Too many failed attempts. Try again in ten minutes.')
        stored = manager.setting('password')
        if not stored:
            raise HTTPException(503, 'Admin password is not configured. Run python -m admin_portal set-password on the server.')
        # Reserve an attempt before yielding so concurrent logins cannot bypass the limit.
        attempts.append(now)
        valid = await manager.verify_password(body.password, stored)
        if body.username != ADMIN_USER or not valid:
            raise HTTPException(401, 'Incorrect username or password.')
        attempts.remove(now)
        token = root.token_for('admin')
        for old_token, session in list(manager.sessions.items()):
            if now - session['last'] >= 86400:
                manager.sessions.pop(old_token, None)
        if len(manager.sessions) >= 256:
            oldest = min(manager.sessions, key=lambda key: manager.sessions[key]['last'])
            manager.sessions.pop(oldest, None)
        manager.sessions[token] = {'last': now, 'password': stored}
        with manager.db() as db:
            manager.audit(db, 'admin.login', ADMIN_USER)
        response = JSONResponse({'username': ADMIN_USER})
        response.set_cookie('admin_session', token, httponly=True, secure=root.SECURE, samesite='strict', max_age=86400)
        return response

    @protected.get('/me')
    async def me():
        return {'username': ADMIN_USER}

    @protected.post('/logout')
    async def logout(request: Request):
        manager.sessions.pop(request.cookies.get('admin_session'), None)
        response = JSONResponse({'ok': True})
        response.delete_cookie('admin_session')
        return response

    @protected.put('/password')
    async def password(body: Password):
        if not await manager.verify_password(body.current_password, manager.setting('password')):
            raise HTTPException(400, 'Current password is incorrect.')
        if not password_valid(body.new_password):
            raise HTTPException(422, 'Use 8–16 characters with uppercase, lowercase, number and special character.')
        encoded = await manager.hash_password(body.new_password)
        with manager.db() as db:
            db.execute("UPDATE settings SET value=? WHERE key='password'", (encoded,))
            manager.audit(db, 'password.changed', ADMIN_USER)
        manager.sessions.clear()
        return {'ok': True}

    @protected.get('/metrics')
    async def metrics():
        return await manager.overview()

    @protected.get('/rooms')
    async def rooms():
        return (await manager.overview())['rooms']

    @protected.post('/rooms', status_code=201)
    async def create_room(body: NewRoom):
        return await manager.create_room(body)

    @protected.put('/rooms/{ident}')
    async def edit_room(ident: str, body: Room):
        return await manager.edit_room(ident, body)

    @protected.delete('/rooms/{ident}')
    async def remove_room(ident: str):
        return await manager.remove_room(ident)

    @protected.get('/users')
    async def users():
        return (await manager.overview())['users']

    @protected.post('/users', status_code=201)
    async def create_user(body: User):
        return await manager.create_user(body)

    @protected.put('/users/{ident}')
    async def edit_user(ident: str, body: User):
        return await manager.edit_user(ident, body)

    @protected.delete('/users/{ident}')
    async def remove_user(ident: str):
        return await manager.remove_user(ident)

    @protected.delete('/rooms/{ident}/media')
    async def clear_media(ident: str):
        return await manager.clear_media(ident)

    @protected.delete('/media')
    async def clear_all(body: Confirm):
        return await manager.clear_all(body)

    @protected.post('/rooms/{ident}/control')
    async def control(ident: str, body: Command):
        return await manager.control(ident, body)

    @protected.post('/rooms/{ident}/upload')
    async def upload(ident: str, request: Request):
        return await manager.upload(ident, request)

    @protected.get('/audit')
    async def audit():
        return await manager.read_audit()

    @router.websocket('/ws')
    async def live(ws: WebSocket):
        try:
            manager.authenticate(ws.cookies.get('admin_session'))
            if not root.same_origin(ws.headers):
                raise HTTPException(403)
        except HTTPException:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            previous = None
            while True:
                manager.authenticate(ws.cookies.get('admin_session'))
                data = await manager.overview()
                encoded = json.dumps(data)
                if encoded != previous:
                    await asyncio.wait_for(ws.send_json(data), timeout=2)
                    previous = encoded
                try:
                    # Consume close frames even when the snapshot has not changed.
                    await asyncio.wait_for(ws.receive_text(), timeout=.25)
                except asyncio.TimeoutError:
                    pass
        except HTTPException:
            await ws.close(code=1008)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception('Admin live monitoring failed')
            try:
                await asyncio.wait_for(ws.close(code=1011), timeout=2)
            except Exception:
                pass

    router.include_router(protected)
    admin_router = APIRouter()

    @admin_router.get('/admin', include_in_schema=False)
    @admin_router.get('/admin/{path:path}', include_in_schema=False)
    async def serve_admin_page(path: str = ''):
        return FileResponse(FRONTEND / 'index.html')

    @admin_router.get('/admin-assets/{asset}', include_in_schema=False)
    async def legacy_admin_asset(asset: str):
        if asset not in ('app.js', 'style.css', 'index.html'):
            raise HTTPException(404)
        return RedirectResponse('/static/admin/' + asset)

    admin_router.include_router(router)
    return admin_router


