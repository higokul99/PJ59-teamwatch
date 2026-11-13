"""Admin security, persistence, isolation and destructive-action regression tests."""
import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from admin_portal.backend.service import digest

ORIGIN = {'Origin': 'http://testserver'}
PASSWORD = 'TestPass123!'


class AdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = digest(PASSWORD)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import app
        # A fresh module makes these tests independent of the legacy singleton tests.
        self.root = types.ModuleType('admin_test_root')
        self.root.__file__ = app.__file__
        self.root.IS_ROOM_RUNTIME = True
        self.root.ROOM_DATA = Path(self.tmp.name)
        exec(compile(Path(app.__file__).read_text(), app.__file__, 'exec'), self.root.__dict__)
        from admin_portal.backend import install
        with patch.dict(os.environ, {'ADMIN_PASSWORD_HASH': self.password_hash}):
            self.manager = install(self.root)
        self.root.admin_manager = self.manager
        self.client = TestClient(self.root.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def login(self, password=PASSWORD):
        return self.client.post('/api/admin/login', json={'username':'hellometora@gmail.com','password':password}, headers=ORIGIN)

    def create_room(self, code='123456'):
        response = self.client.post('/api/admin/rooms', json={'code':code,'name':'Screening','host_pin':'1234','viewer_pin':'5678'}, headers=ORIGIN)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_admin_auth_origin_and_rate_limit(self):
        for path in ('/metrics','/users','/rooms','/audit'):
            self.assertEqual(self.client.get('/api/admin'+path).status_code, 401)
        self.assertEqual(self.client.post('/api/admin/login',json={'username':'x','password':'x'}).status_code,403)
        for _ in range(5):
            self.assertEqual(self.login('wrong').status_code,401)
        self.assertEqual(self.login().status_code,429)
        self.manager.failures.clear()
        response=self.login()
        self.assertEqual(response.status_code,200)
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=strict',response.headers['set-cookie'])
        self.assertEqual(self.client.post('/api/admin/logout',headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.get('/api/admin/metrics').status_code,401)

    def test_host_is_not_admin_and_session_expires(self):
        self.client.post('/api/join',json={'code':self.root.ROOM_CODE,'pin':'9292'},headers=ORIGIN)
        self.assertEqual(self.client.get('/api/admin/metrics').status_code,401)
        self.login()
        token=self.client.cookies.get('admin_session')
        self.manager.sessions[token]['last']-=86401
        self.assertEqual(self.client.get('/api/admin/me').status_code,401)

    def test_room_account_crud_and_isolation(self):
        self.login()
        room=self.create_room()
        self.assertEqual(self.client.post('/api/admin/rooms',json={'code':'123456','name':'Duplicate','host_pin':'1234','viewer_pin':'5678'},headers=ORIGIN).status_code,409)
        with TestClient(self.root.app) as viewer:
            self.assertEqual(viewer.post('/api/join',json={'code':room['code'],'pin':'5678'},headers=ORIGIN).status_code,200)
            self.assertEqual(viewer.get('/api/me').json()['room'],room['code'])
            runtime=self.manager.runtimes[room['id']]
            runtime.media={'id':'fixture','name':'Other room movie','duration':10}
            (runtime.DATA/'fixture').mkdir()
            (runtime.DATA/'fixture'/'audio.m4a').write_bytes(b'other room')
            self.assertEqual(viewer.get('/media/fixture/audio.m4a').status_code,200)
            self.client.post('/api/join',json={'code':self.root.ROOM_CODE,'pin':'9292'},headers=ORIGIN)
            self.assertEqual(self.client.get('/media/fixture/audio.m4a').status_code,404)
            user=next(u for u in self.client.get('/api/admin/users').json() if u['room_id']==room['id'] and u['role']=='viewer')
            self.assertNotIn('pin_hash',user)
            edited={k:user[k] for k in ('room_id','name','role','blocked')}
            edited.update(name='Alex',pin='7788')
            self.assertEqual(self.client.put('/api/admin/users/'+user['id'],json=edited,headers=ORIGIN).status_code,200)
            self.assertEqual(viewer.get('/api/me').status_code,401)
            self.assertEqual(viewer.post('/api/join',json={'code':room['code'],'pin':'5678'},headers=ORIGIN).status_code,401)
            self.assertEqual(viewer.post('/api/join',json={'code':room['code'],'pin':'7788'},headers=ORIGIN).status_code,200)
            edited['blocked']=True
            self.client.put('/api/admin/users/'+user['id'],json=edited,headers=ORIGIN)
            self.assertEqual(viewer.get('/api/me').status_code,401)
            self.assertEqual(self.client.delete('/api/admin/users/'+user['id'],headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.delete('/api/admin/rooms/'+room['id'],headers=ORIGIN).status_code,200)
        self.assertFalse((runtime.DATA/'fixture').exists())
        self.assertFalse(any(u['room_id']==room['id'] for u in self.manager.rows('users')))

    def test_block_room_and_unique_passcodes(self):
        self.login()
        room=self.create_room()
        new={'room_id':room['id'],'name':'New viewer','role':'viewer','pin':'9012'}
        response=self.client.post('/api/admin/users',json=new,headers=ORIGIN)
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.client.post('/api/admin/users',json=new,headers=ORIGIN).status_code,409)
        self.assertEqual(self.client.post('/api/join',json={'code':room['code'],'pin':'9012'},headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.put('/api/admin/rooms/'+room['id'],json={'name':'Blocked','code':'654321','blocked':True},headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertEqual(self.client.post('/api/join',json={'code':'654321','pin':'9012'},headers=ORIGIN).status_code,401)

    def test_confirmation_and_media_cleanup(self):
        self.login()
        self.root.media={'id':'testmedia','name':'Movie','duration':10}
        folder=self.root.DATA/'testmedia';folder.mkdir();(folder/'audio.m4a').write_bytes(b'audio')
        self.root.save_media(self.root.media)
        self.assertEqual(self.client.request('DELETE','/api/admin/media',json={'confirmation':'yes'},headers=ORIGIN).status_code,422)
        self.assertTrue(folder.exists())
        self.root.upload_busy=True
        self.assertEqual(self.client.request('DELETE','/api/admin/media',json={'confirmation':'CONFIRM'},headers=ORIGIN).status_code,409)
        self.root.upload_busy=False
        self.assertEqual(self.client.request('DELETE','/api/admin/media',json={'confirmation':'CONFIRM'},headers=ORIGIN).status_code,200)
        self.assertFalse(folder.exists())
        self.assertTrue(self.manager.path.exists())
        self.assertIsNone(self.root.media)

    def test_password_change_and_audit(self):
        self.login()
        self.assertEqual(self.client.put('/api/admin/password',json={'current_password':PASSWORD,'new_password':'weak'},headers=ORIGIN).status_code,422)
        self.assertEqual(self.client.put('/api/admin/password',json={'current_password':PASSWORD,'new_password':'AnotherPass1!'},headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.get('/api/admin/me').status_code,401)
        self.assertEqual(self.login().status_code,401)
        self.assertEqual(self.login('AnotherPass1!').status_code,200)
        self.assertIn('password.changed',[entry['action'] for entry in self.client.get('/api/admin/audit').json()])
        self.assertNotIn('AnotherPass1!',self.manager.path.read_bytes().decode(errors='ignore'))

    def test_persistence_and_live_admin_socket(self):
        self.login()
        room=self.create_room()
        from admin_portal.backend.service import Manager
        restored=Manager(self.root)
        self.assertEqual(restored.room(room['id'])['code'],'123456')
        with self.client.websocket_connect('/api/admin/ws',headers=ORIGIN) as ws:
            self.assertEqual(len(ws.receive_json()['rooms']),2)
        self.assertEqual(self.client.get('/admin').status_code,200)
        self.assertEqual(self.client.get('/admin-assets/app.js').status_code,200)

    def test_cold_imports_work_in_both_orders(self):
        for order in ('import app; import admin_portal.backend.routes',
                      'import admin_portal.backend.routes; import app'):
            with tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, '-c', order],
                                        env={**os.environ, 'DATA_DIR': directory},
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_admin_failure_does_not_stop_viewer_websocket(self):
        self.login()
        self.client.post('/api/join', json={'code':self.root.ROOM_CODE,'pin':'9292'}, headers=ORIGIN)
        self.root.media = {'id':'playing', 'duration':300}
        self.root.state.update(playing=True, position=10)
        with self.client.websocket_connect('/ws', headers=ORIGIN) as ws:
            ws.receive_json()
            with patch.object(self.manager, 'overview', side_effect=RuntimeError('monitor failed')):
                with self.assertRaises(RuntimeError):
                    self.client.get('/api/admin/metrics')
            ws.send_json({'type':'ping', 'sent':123})
            self.assertEqual(ws.receive_json()['type'], 'pong')
            self.assertTrue(ws.receive_json()['timeline']['playing'])
            self.assertEqual(self.client.get('/api/admin/metrics').status_code, 200)

    def test_password_hashing_does_not_block_event_loop(self):
        from admin_portal.backend.schemas import NewRoom
        entered, release = threading.Event(), threading.Event()
        def slow_hash(value):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Event loop could not run while hashing')
            return self.password_hash
        async def scenario():
            task = asyncio.create_task(self.manager.create_room(NewRoom(
                code='654321', name='Background hashing', host_pin='1234', viewer_pin='5678')))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                await asyncio.sleep(.01)
                release.set()
                await task
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
        with patch('admin_portal.backend.service.digest', side_effect=slow_hash):
            asyncio.run(scenario())

    def test_deleted_room_releases_runtime_and_assets_share_cache_policy(self):
        self.login()
        room = self.create_room()
        self.client.get('/api/admin/metrics')
        self.assertIn(room['id'], self.manager.runtimes)
        self.assertEqual(self.client.delete('/api/admin/rooms/'+room['id'],headers=ORIGIN).status_code,200)
        self.assertNotIn(room['id'], self.manager.runtimes)
        for asset in ('/static/app.js', '/static/admin/app.js', '/static/admin/style.css'):
            response = self.client.get(asset)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['cache-control'],'no-cache')
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        legacy = self.client.get('/admin-assets/app.js', follow_redirects=False)
        self.assertEqual(legacy.status_code,307)
        self.assertEqual(legacy.headers['location'],'/static/admin/app.js')
        self.assertEqual(self.client.get('/admin-assets/unknown').status_code,404)


if __name__=='__main__':
    unittest.main()
