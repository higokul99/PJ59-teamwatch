"""Route viewer traffic to the room selected by its session."""
import json
from http.cookies import SimpleCookie
from fastapi import HTTPException
from fastapi.responses import JSONResponse


class RoomDispatch:
    def __init__(self, app, manager):
        self.app, self.manager = app, manager

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] not in ('http', 'websocket') or path.startswith(('/api/admin', '/admin')) or not path.startswith(('/api/', '/ws', '/media/', '/hls/')):
            return await self.app(scope, receive, send)
        cookies = SimpleCookie()
        try:
            cookies.load(dict(scope['headers']).get(b'cookie', b'').decode())
        except Exception:
            pass
        ident = cookies['room_id'].value if 'room_id' in cookies else 'default'
        joining = path == '/api/join' and scope.get('method') == 'POST'
        if joining:
            raw = bytearray()
            while True:
                message = await receive()
                raw.extend(message.get('body', b''))
                if len(raw) > 4096 or message['type'] == 'http.disconnect':
                    return await JSONResponse({'detail': 'Invalid join request.'}, status_code=400)(scope, receive, send)
                if not message.get('more_body'):
                    break
            try:
                code = json.loads(raw).get('code')
                ident = next((r['id'] for r in self.manager.rows('rooms') if r['code'] == code), 'default')
            except (ValueError, AttributeError):
                pass
            delivered = False
            original_receive = receive
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(raw), 'more_body': False}
                return await original_receive()
            receive = replay
        try:
            runtime = await self.manager.runtime(ident)
        except HTTPException:
            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 1008})
            return await JSONResponse({'detail': 'Room no longer exists.'}, status_code=401)(scope, receive, send)
        async def wrapped_send(message):
            if joining and message['type'] == 'http.response.start' and message['status'] == 200:
                value = f'room_id={ident}; HttpOnly; Path=/; SameSite=Strict; Max-Age=86400'
                if self.manager.root.SECURE:
                    value += '; Secure'
                message['headers'].append((b'set-cookie', value.encode()))
            await send(message)
        target = self.app if ident == 'default' else runtime.app
        await target(scope, receive, wrapped_send)


