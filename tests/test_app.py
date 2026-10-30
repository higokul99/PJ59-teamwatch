import asyncio
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

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
        app.peer_status.clear()
        app.upload_busy = False
        app.processing = {'status': 'idle', 'message': 'Ready'}
        (app.DATA / 'current.json').unlink(missing_ok=True)
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

    def test_viewer_can_play_pause_but_not_seek_or_sync(self):
        self.fake_media()
        self.join()
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            self.assertEqual(ws.receive_json()['type'], 'state')
            ws.send_json({'type': 'control', 'action': 'seek', 'position': 42})
            self.assertEqual(ws.receive_json()['type'], 'error')
            for action in ('sync', 'skip', 'restart'):
                ws.send_json({'type': 'control', 'action': action, 'seconds': 10})
                self.assertEqual(ws.receive_json()['type'], 'error')
            ws.send_json({'type': 'control', 'action': 'play'})
            self.assertTrue(ws.receive_json()['timeline']['playing'])
            ws.send_json({'type': 'control', 'action': 'pause'})
            self.assertFalse(ws.receive_json()['timeline']['playing'])
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

    def test_download_metadata_and_worker(self):
        self.fake_media()
        url = '/api/media/testmedia/audio.m4a'
        self.assertEqual(self.client.get(url).status_code, 401)
        self.join()
        self.assertEqual(self.client.get(url).json(), {'size': 10, 'type': 'audio/mp4'})
        self.assertEqual(self.client.get('/api/media/testmedia/conversion.log').status_code, 404)
        worker = self.client.get('/sw.js')
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.headers['Service-Worker-Allowed'], '/')
        self.assertEqual(self.client.get('/').headers['Cache-Control'], 'no-cache')
        self.assertEqual(self.client.get('/static/app.js').headers['Cache-Control'], 'no-cache')

    def test_active_buffering_pauses_everyone_but_stale_events_do_not(self):
        self.fake_media()
        self.join()
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            ws.receive_json()
            ws.send_json({'type': 'status', 'media_id': 'testmedia', 'active': True, 'ready': True, 'mode': 'audio'})
            ws.send_json({'type': 'control', 'action': 'play'})
            revision = ws.receive_json()['timeline']['revision']
            ws.send_json({'type': 'control', 'action': 'buffering', 'revision': revision - 1})
            ws.send_json({'type': 'ping', 'sent': 1})
            ws.receive_json()
            self.assertTrue(ws.receive_json()['timeline']['playing'])
            ws.send_json({'type': 'control', 'action': 'buffering', 'revision': revision})
            paused = ws.receive_json()['timeline']
            self.assertFalse(paused['playing'])
            self.assertIn('buffering', paused['reason'])

    def test_play_waits_for_active_devices_and_disconnect_pauses_room(self):
        self.fake_media()
        self.join()
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            ws.receive_json()
            ws.send_json({'type': 'status', 'media_id': 'testmedia', 'active': True, 'ready': False})
            ws.send_json({'type': 'control', 'action': 'play'})
            self.assertEqual(ws.receive_json()['type'], 'error')
            ws.send_json({'type': 'status', 'media_id': 'testmedia', 'active': True, 'ready': True})
            ws.send_json({'type': 'control', 'action': 'play'})
            self.assertTrue(ws.receive_json()['timeline']['playing'])
        self.assertFalse(app.state['playing'])
        self.assertIn('disconnected', app.state['reason'])

    def test_host_sync_keeps_position_and_schedules_common_start(self):
        self.fake_media()
        app.state.update(position=30, anchor=100, playing=True)
        with patch.object(app.time, 'time', return_value=105):
            app.control({'action': 'sync'})
        self.assertEqual(app.state['position'], 35)
        self.assertEqual(app.state['anchor'], 106.5)
        self.assertTrue(app.state['playing'])

    def test_host_skip_clamps_boundaries_and_preserves_pause(self):
        self.fake_media()
        app.state.update(position=5, playing=False)
        app.control({'action': 'skip', 'seconds': -10})
        self.assertEqual(app.state['position'], 0)
        self.assertFalse(app.state['playing'])
        app.control({'action': 'skip', 'seconds': 10})
        self.assertEqual(app.state['position'], 10)
        app.state['position'] = 115
        app.control({'action': 'skip', 'seconds': 10})
        self.assertEqual(app.state['position'], 120)
        for invalid in (0, 30, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                app.control({'action': 'skip', 'seconds': invalid})

    def test_host_skip_uses_server_time_and_restart_preserves_playing(self):
        self.fake_media()
        app.state.update(position=30, playing=True, anchor=100)
        with patch.object(app.time, 'time', return_value=105):
            app.control({'action': 'skip', 'seconds': -10})
            self.assertEqual(app.state['position'], 25)
            self.assertEqual(app.state['anchor'], 106.5)
            app.control({'action': 'skip', 'seconds': -10})
            self.assertEqual(app.state['position'], 15)
            app.control({'action': 'restart'})
            self.assertEqual(app.state['position'], 0)
            self.assertTrue(app.state['playing'])
        app.state['playing'] = False
        app.control({'action': 'restart'})
        self.assertFalse(app.state['playing'])

    def test_host_skip_and_restart_over_websocket(self):
        self.fake_media()
        self.join('9292')
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            ws.receive_json()
            for command, expected in [({'action': 'seek', 'position': 40}, 40),
                                      ({'action': 'skip', 'seconds': 10}, 50),
                                      ({'action': 'skip', 'seconds': -10}, 40),
                                      ({'action': 'restart'}, 0)]:
                ws.send_json({'type': 'control', **command})
                self.assertEqual(ws.receive_json()['timeline']['position'], expected)

    def test_delete_media_is_host_only_and_clears_disk_and_state(self):
        self.fake_media()
        (app.DATA / 'current.json').write_text(json.dumps(app.media))
        app.state.update(playing=True, position=50, reason='old reason')
        self.assertEqual(self.client.delete('/api/media', headers=ORIGIN).status_code, 401)
        self.join()
        self.assertEqual(self.client.delete('/api/media', headers=ORIGIN).status_code, 403)
        self.join('9292')
        self.assertEqual(self.client.delete('/api/media').status_code, 403)
        response = self.client.delete('/api/media', headers=ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['media'])
        self.assertFalse(app.state['playing'])
        self.assertEqual(app.state['position'], 0)
        self.assertFalse((app.DATA / 'current.json').exists())
        self.assertFalse((app.DATA / 'testmedia').exists())
        self.assertFalse(app.upload_busy)
        self.assertEqual(self.client.delete('/api/media', headers=ORIGIN).status_code, 200)

    def test_delete_during_preparation_is_rejected(self):
        self.fake_media()
        self.join('9292')
        app.upload_busy = True
        response = self.client.delete('/api/media', headers=ORIGIN)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(app.media['id'], 'testmedia')
        app.upload_busy = False

    def test_failed_manifest_delete_preserves_current_media(self):
        self.fake_media()
        self.join('9292')
        with patch.object(Path, 'unlink', side_effect=PermissionError):
            response = self.client.delete('/api/media', headers=ORIGIN)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(app.media['id'], 'testmedia')
        self.assertFalse(app.upload_busy)

    def test_successful_replacement_resets_room_and_readiness(self):
        self.fake_media()
        (app.DATA / 'current.json').write_text(json.dumps(app.media))
        app.state.update(position=45, playing=True, reason='An old buffering message')
        peer = object()
        app.peers[peer] = 'token'
        app.peer_status[peer] = {'active': True, 'ready': True}
        ident = 'replacement'
        source = app.DATA / 'replacement.upload'
        source.write_bytes(b'media')
        info = {'format': {'duration': '90'}, 'streams': [{'codec_type': 'audio'}]}
        async def fake_process(*args, **kwargs):
            if args[0] == 'ffmpeg':
                Path(args[-1]).write_bytes(b'prepared audio')
            return SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0),
                                   communicate=AsyncMock(return_value=(json.dumps(info).encode(), b'')))
        with patch.object(app.asyncio, 'create_subprocess_exec', side_effect=fake_process), patch.object(app, 'broadcast', new_callable=AsyncMock):
            asyncio.run(app.process(source, ident, 'Replacement song'))
        self.assertEqual(app.media['id'], ident)
        self.assertEqual(json.loads((app.DATA / 'current.json').read_text())['id'], ident)
        self.assertEqual(app.state['position'], 0)
        self.assertFalse(app.state['playing'])
        self.assertFalse(app.peer_status[peer]['active'])
        self.assertFalse(app.peer_status[peer]['ready'])
        self.assertNotIn('old buffering', app.state['reason'])
        self.assertFalse((app.DATA / 'testmedia').exists())
        self.assertFalse(source.exists())
        self.assertFalse(app.upload_busy)

    def test_processing_folder_failure_releases_upload_lock(self):
        self.fake_media()
        source = app.DATA / 'mkdir-failed.upload'
        source.write_bytes(b'media')
        app.upload_busy = True
        with patch.object(Path, 'mkdir', side_effect=PermissionError):
            asyncio.run(app.process(source, 'mkdir-failed', 'New movie'))
        self.assertEqual(app.processing['status'], 'error')
        self.assertIn('not replaced', app.processing['message'])
        self.assertEqual(app.media['id'], 'testmedia')
        self.assertFalse(app.upload_busy)

    def test_source_cleanup_failure_does_not_lock_future_uploads(self):
        self.fake_media()
        source = app.DATA / 'cleanup-failed.upload'
        source.write_bytes(b'media')
        app.upload_busy = True
        with patch.object(app.asyncio, 'create_subprocess_exec', side_effect=FileNotFoundError), patch.object(Path, 'unlink', side_effect=PermissionError):
            asyncio.run(app.process(source, 'cleanup-failed', 'New movie'))
        self.assertFalse(app.upload_busy)
        self.assertIn('Source upload could not be removed', app.processing['message'])

    def test_delete_reports_unremoved_files_after_clearing_room(self):
        self.fake_media()
        self.join('9292')
        with patch.object(app.shutil, 'rmtree', side_effect=PermissionError):
            response = self.client.delete('/api/media', headers=ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(app.media)
        self.assertEqual(response.json()['processing']['status'], 'error')
        self.assertFalse(app.upload_busy)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe unavailable')
    def test_real_upload_replace_and_delete_through_api(self):
        fixture = app.DATA / 'api-fixture.mkv'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=12',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(fixture)], check=True)
        with self.client:
            self.join('9292')
            previous = None
            for name in ('First movie', 'Replacement movie'):
                response = self.client.post('/api/upload', params={'name': name}, content=fixture.read_bytes(), headers=ORIGIN)
                self.assertEqual(response.status_code, 200, response.text)
                for _ in range(100):
                    data = self.client.get('/api/me').json()
                    if data['processing']['status'] not in ('uploading', 'processing'):
                        break
                    time.sleep(.05)
                self.assertEqual(data['processing']['status'], 'ready', data['processing'])
                self.assertEqual(data['media']['name'], name)
                self.assertFalse(data['timeline']['playing'])
                self.assertEqual(data['timeline']['position'], 0)
                if previous:
                    self.assertNotEqual(data['media']['id'], previous)
                    self.assertFalse((app.DATA / previous).exists())
                previous = data['media']['id']
            response = self.client.delete('/api/media', headers=ORIGIN)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(self.client.get('/api/me').json()['media'])
            self.assertFalse((app.DATA / previous).exists())
            self.assertFalse((app.DATA / 'current.json').exists())

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
