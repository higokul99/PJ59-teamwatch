import asyncio
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

TMP = tempfile.TemporaryDirectory()
os.environ['DATA_DIR'] = TMP.name
os.environ['SESSION_SECRET'] = 'test-secret'
import app

ORIGIN = {'Origin': 'http://testserver'}


class RoomTests(unittest.TestCase):
    def setUp(self):
        app.media = None
        app.attempts.clear()
        app.sessions_revoked.clear()
        app.peers.clear()
        app.upload_busy = False
        app.processing = {'status': 'idle', 'message': 'Ready'}
        app.state.update(playing=False, position=0, anchor=100, revision=0)
        self.client = TestClient(app.app)

    def tearDown(self):
        self.client.close()

    def join(self, pin='8989'):
        return self.client.post('/api/join', json={'code': app.ROOM_CODE, 'pin': pin}, headers=ORIGIN)

    def fake_media(self):
        app.media = {'id': 'testmedia', 'name': 'Test movie', 'duration': 120, 'has_video': True}
        folder = app.DATA / 'testmedia'
        folder.mkdir(exist_ok=True)
        (folder / 'audio.m4a').write_bytes(b'0123456789')

    def test_auth_and_role_separation(self):
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.join('0000').status_code, 401)
        self.assertEqual(self.join().json()['role'], 'viewer')
        self.assertEqual(self.client.post('/api/upload', content=b'fake', headers=ORIGIN).status_code, 403)
        self.assertEqual(self.join('9292').json()['role'], 'host')
        self.assertEqual(self.client.get('/api/me').json()['role'], 'host')
        self.assertIn('HttpOnly', self.join().headers['set-cookie'])

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.join('0000').status_code, 401)
        self.assertEqual(self.join().status_code, 429)

    def test_origin_and_malformed_login(self):
        self.assertEqual(self.client.post('/api/join', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/join', json=[], headers=ORIGIN).status_code, 400)
        self.assertEqual(self.client.post('/api/join', json={'code': '♥', 'pin': '♥'}, headers=ORIGIN).status_code, 401)

    def test_signature_expiry_and_logout(self):
        token = app.token_for('host')
        self.assertEqual(app.role_for(token), 'host')
        self.assertIsNone(app.role_for(token + '0'))
        with patch.object(app.time, 'time', return_value=10):
            expired = app.token_for('viewer')
        self.assertIsNone(app.role_for(expired))
        self.join()
        cookie = self.client.cookies.get('session')
        self.assertEqual(self.client.post('/api/logout', json={}, headers=ORIGIN).status_code, 200)
        self.assertIsNone(app.role_for(cookie))
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_media_byte_ranges_and_access(self):
        self.fake_media()
        url = '/media/testmedia/audio.m4a'
        self.assertEqual(self.client.get(url).status_code, 401)
        self.join()
        response = self.client.get(url, headers={'Range': 'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'2345')
        self.assertEqual(response.headers['content-range'], 'bytes 2-5/10')
        self.assertEqual(self.client.get(url, headers={'Range': 'bytes=99-100'}).status_code, 416)
        self.assertEqual(self.client.get('/media/testmedia/conversion.log').status_code, 404)

    def test_authoritative_timeline(self):
        self.fake_media()
        with patch.object(app.time, 'time', return_value=100):
            app.control({'action': 'play'})
        self.assertEqual(app.state['anchor'], 101.5)
        self.assertEqual(app.position(101), 0)
        self.assertEqual(app.position(105), 3.5)
        with patch.object(app.time, 'time', return_value=105):
            app.control({'action': 'pause'})
        self.assertEqual(app.position(1000), 3.5)
        app.control({'action': 'seek', 'position': 999})
        self.assertEqual(app.position(), 120)
        app.control({'action': 'play'})
        self.assertEqual(app.state['position'], 0)
        with self.assertRaises(ValueError):
            app.control({'action': 'seek', 'position': float('nan')})

    def test_viewer_cannot_control_socket(self):
        self.fake_media()
        self.join()
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            self.assertEqual(ws.receive_json()['type'], 'state')
            ws.send_json({'type': 'control', 'action': 'play'})
            self.assertEqual(ws.receive_json()['type'], 'error')
            self.assertFalse(app.state['playing'])
            ws.send_json({'type': 'ping', 'sent': 123})
            self.assertEqual(ws.receive_json()['sent'], 123)
            self.assertEqual(ws.receive_json()['type'], 'state')

    def test_host_socket_controls_and_late_join(self):
        self.fake_media()
        self.join('9292')
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            ws.receive_json()
            ws.send_json({'type': 'control', 'action': 'seek', 'position': 42})
            self.assertEqual(ws.receive_json()['timeline']['position'], 42)
            ws.send_json({'type': 'control', 'action': 'play'})
            self.assertTrue(ws.receive_json()['timeline']['playing'])
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            self.assertEqual(ws.receive_json()['timeline']['position'], 42)

    def test_websocket_requires_auth_and_origin(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws', headers=ORIGIN):
                pass
        self.join()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws', headers={'Origin': 'http://evil.example'}):
                pass

    def test_upload_bounds_and_busy(self):
        self.join('9292')
        with patch.object(app.shutil, 'which', return_value='/fake/ffmpeg'), patch.object(app, 'MAX_UPLOAD', 5):
            self.assertEqual(self.client.post('/api/upload', content=b'123456', headers=ORIGIN).status_code, 413)
            self.assertFalse(app.upload_busy)
            self.assertEqual(self.client.post('/api/upload', content=b'', headers=ORIGIN).status_code, 400)
            app.upload_busy = True
            self.assertEqual(self.client.post('/api/upload', content=b'1', headers=ORIGIN).status_code, 409)
        app.upload_busy = False

    def test_conversion_failure_keeps_previous_movie(self):
        self.fake_media()
        source = app.DATA / 'broken.upload'
        source.write_bytes(b'not media')
        async def run():
            with patch.object(app.asyncio, 'create_subprocess_exec', side_effect=FileNotFoundError):
                await app.process(source, 'broken', 'Broken')
        asyncio.run(run())
        self.assertEqual(app.media['id'], 'testmedia')
        self.assertEqual(app.processing['status'], 'error')
        self.assertFalse(source.exists())
        self.assertFalse(app.upload_busy)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe unavailable')
    def test_actual_movie_and_audio_conversion(self):
        for video in (True, False):
            ident = 'realvideo' if video else 'realaudio'
            source = app.DATA / f'{ident}.upload'
            args = ['ffmpeg', '-y', '-v', 'error']
            if video:
                args += ['-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=24']
            args += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '3', '-c:a', 'aac']
            if video:
                args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
            args += ['-f', 'matroska', str(source)]
            subprocess.run(args, check=True)
            asyncio.run(app.process(source, ident, 'Fixture'))
            self.assertEqual(app.processing['status'], 'ready', app.processing)
            self.assertEqual(app.media['has_video'], video)
            for track in (['audio.m4a', 'video.mp4', 'combined.mp4'] if video else ['audio.m4a']):
                info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(app.DATA / ident / track)]))
                types = [s['codec_type'] for s in info['streams']]
                self.assertEqual(types, {'audio.m4a':['audio'], 'video.mp4':['video'], 'combined.mp4':['video', 'audio']}[track])


if __name__ == '__main__':
    unittest.main()
