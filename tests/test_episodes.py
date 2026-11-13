"""Episode library integration tests: persistence, authorization and real encoding."""
import asyncio
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

import test_admin
from episode_library import Library

ORIGIN = test_admin.ORIGIN


class EpisodeTests(unittest.TestCase):
    setUpClass = classmethod(test_admin.AdminTests.setUpClass.__func__)
    setUp = test_admin.AdminTests.setUp
    tearDown = test_admin.AdminTests.tearDown
    login = test_admin.AdminTests.login
    create_room = test_admin.AdminTests.create_room

    def join(self, code=None, pin='9292'):
        response = self.client.post('/api/join', json={'code':code or self.root.ROOM_CODE,'pin':pin},headers=ORIGIN)
        self.assertEqual(response.status_code,200,response.text)

    def episode(self, title='Episode', room='default', status='ready', duration=120):
        library = self.manager.library
        runtime = self.manager.runtimes[room]
        ident, asset = secrets.token_hex(12), secrets.token_hex(12)
        folder=runtime.DATA/asset;folder.mkdir();(folder/'audio.m4a').write_bytes(b'0123456789')
        meta={'id':asset,'episode_id':ident,'name':title,'duration':duration,'available_duration':duration,'complete':True,'has_video':False}
        with self.manager.db() as db:
            db.execute('INSERT INTO episodes(id,room_id,title,ordinal,status,asset_id,media,progress,created) VALUES(?,?,?,?,?,?,?,?,?)',
                       (ident,room,title,len(library.records(room)),status,asset,json.dumps(meta),json.dumps({'status':'ready','percent':100,'message':'Ready'}),time.time()))
        return ident,meta

    def test_eight_episodes_retained_and_selection_is_explicit(self):
        self.join()
        episodes=[self.episode('Episode '+str(i)) for i in range(1,9)]
        self.assertEqual(len(self.client.get('/api/episodes').json()['episodes']),8)
        self.assertIsNone(self.root.media)
        response=self.client.post('/api/episodes/'+episodes[0][0]+'/select',headers=ORIGIN)
        self.assertEqual(response.status_code,200)
        self.root.state.update(playing=True,position=30)
        before=self.root.state.copy()
        self.episode('Bonus')
        self.assertEqual(self.root.state,before)
        response=self.client.post('/api/episodes/'+episodes[1][0]+'/select',headers=ORIGIN)
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.root.state['playing']);self.assertEqual(self.root.state['position'],0)
        self.assertEqual(self.root.media['episode_id'],episodes[1][0])
        self.assertTrue((self.root.DATA/episodes[0][1]['id']).exists())
        self.assertEqual(len(self.client.get('/api/episodes').json()['episodes']),9)

    def test_participants_and_other_rooms_cannot_mutate_or_stream(self):
        ident,meta=self.episode()
        self.join(pin='8989')
        for method,path,body in [('POST','',None),('POST','/'+ident+'/select',None),('POST','/'+ident+'/retry',None),('PATCH','/'+ident,{'title':'Hack'}),('DELETE','/'+ident,None),('PUT','/order',{'ids':[ident]}),('DELETE','',{'confirmation':'CONFIRM'})]:
            response=self.client.request(method,'/api/episodes'+path,json=body,headers=ORIGIN)
            self.assertEqual(response.status_code,403,(path,response.text))
        self.login();room=self.create_room();self.client.get('/api/admin/metrics')
        self.join(code=room['code'],pin='1234')
        self.assertEqual(self.client.post('/api/episodes/'+ident+'/select',headers=ORIGIN).status_code,404)
        self.assertEqual(self.client.get('/media/'+meta['id']+'/audio.m4a').status_code,404)

    def test_reorder_and_rename_persist_and_reject_incomplete_lists(self):
        self.join();first,_=self.episode('One');second,_=self.episode('Two')
        self.assertEqual(self.client.put('/api/episodes/order',json={'ids':[second]},headers=ORIGIN).status_code,409)
        self.assertEqual(self.client.put('/api/episodes/order',json={'ids':[second,first]},headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.patch('/api/episodes/'+first,json={'title':'Pilot'},headers=ORIGIN).status_code,200)
        restored=Library(self.manager)
        records=restored.records('default')
        self.assertEqual([r['id'] for r in records],[second,first]);self.assertEqual(records[1]['title'],'Pilot')

    def test_stale_readiness_and_controls_do_not_affect_new_episode(self):
        self.join();first,_=self.episode('One');second,_=self.episode('Two')
        self.client.post('/api/episodes/'+first+'/select',headers=ORIGIN)
        with self.client.websocket_connect('/ws',headers=ORIGIN) as ws:
            previous=ws.receive_json()
            self.client.post('/api/episodes/'+second+'/select',headers=ORIGIN)
            current=ws.receive_json()
            ws.send_json({'type':'status','media_id':previous['media']['id'],'episode_id':first,'revision':previous['timeline']['revision'],'selection_revision':previous['timeline']['selection_revision'],'active':True,'ready':True})
            ws.send_json({'type':'control','action':'play','episode_id':first,'revision':previous['timeline']['revision'],'selection_revision':previous['timeline']['selection_revision']})
            self.assertEqual(ws.receive_json()['type'],'error');self.assertFalse(self.root.state['playing'])
            ws.send_json({'type':'ping','sent':1});ws.receive_json();snap=ws.receive_json()
            self.assertFalse(snap['participants'][0]['ready'])
            ws.send_json({'type':'control','action':'play','episode_id':second,'revision':current['timeline']['revision'],'selection_revision':current['timeline']['selection_revision']})
            self.assertTrue(ws.receive_json()['timeline']['playing'])

    def test_deletion_revokes_access_even_when_disk_cleanup_fails(self):
        self.join();ident,meta=self.episode()
        self.client.post('/api/episodes/'+ident+'/select',headers=ORIGIN)
        with patch('episode_library.shutil.rmtree',side_effect=PermissionError):
            self.assertEqual(self.client.delete('/api/episodes/'+ident,headers=ORIGIN).status_code,500)
        self.assertIsNone(self.root.media)
        self.assertEqual(self.client.get('/media/'+meta['id']+'/audio.m4a').status_code,404)
        self.assertEqual(self.manager.library.get('default',ident)['status'],'cleanup_pending')
        self.assertEqual(self.client.delete('/api/episodes/'+ident,headers=ORIGIN).status_code,200)
        self.assertFalse((self.root.DATA/meta['id']).exists())

    def test_library_confirmation_preserves_accounts(self):
        self.join();self.episode();accounts=self.manager.rows('users')
        self.assertEqual(self.client.request('DELETE','/api/episodes',json={'confirmation':'yes'},headers=ORIGIN).status_code,422)
        self.assertEqual(len(self.manager.library.records('default')),1)
        self.assertEqual(self.client.request('DELETE','/api/episodes',json={'confirmation':'CONFIRM'},headers=ORIGIN).status_code,200)
        self.assertEqual(self.manager.rows('users'),accounts)

    def test_migration_is_idempotent_and_does_not_move_legacy_media(self):
        with self.manager.db() as db:db.execute('DELETE FROM episode_selection')
        folder=self.root.DATA/'legacy';folder.mkdir();(folder/'audio.m4a').write_bytes(b'audio')
        self.root.media={'id':'legacy','name':'Old movie','duration':60,'has_video':False}
        library=self.manager.library
        library.migrate(self.root,'default');ident=self.root.media['episode_id']
        library.migrate(self.root,'default')
        self.assertEqual(len(library.records('default')),1)
        self.assertEqual(self.root.media['episode_id'],ident)
        self.assertTrue((folder/'audio.m4a').exists());self.assertFalse(self.root.state['playing'])

    def test_room_and_file_limits_reject_without_changing_playback(self):
        self.join();ident,_=self.episode();self.client.post('/api/episodes/'+ident+'/select',headers=ORIGIN)
        with patch('episode_library.shutil.which',return_value='/fake/ffmpeg'),patch.object(self.manager.library,'room_limit',1):
            response=self.client.post('/api/episodes?name=TooBig',content=b'12345',headers=ORIGIN)
            self.assertEqual(response.status_code,413,response.text)
        with patch('episode_library.shutil.which',return_value='/fake/ffmpeg'),patch.object(self.root,'MAX_UPLOAD',2):
            response=self.client.post('/api/episodes?name=TooBig',content=b'12345',headers=ORIGIN)
            self.assertEqual(response.status_code,413,response.text)
        self.assertEqual(self.root.media['episode_id'],ident)
        self.assertFalse(self.manager.library.uploading)

    def test_scheduler_rotates_rooms_and_prioritizes_upcoming(self):
        self.login();room=self.create_room();self.client.get('/api/admin/metrics')
        a,_=self.episode('A',status='failed');b,_=self.episode('B',room=room['id'],status='failed')
        with self.manager.db() as db:db.execute("UPDATE episodes SET status='queued'")
        library=self.manager.library
        library.last_room='default';self.assertEqual(library.pick()['id'],b)
        library.last_room=room['id'];self.assertEqual(library.pick()['id'],a)
        # Avoid running fixture-only jobs in the actual worker.
        with self.manager.db() as db:db.execute("UPDATE episodes SET status='failed'")

    def test_restart_restores_selection_paused_and_marks_interrupted_work(self):
        self.join();ident,meta=self.episode()
        self.client.post('/api/episodes/'+ident+'/select',headers=ORIGIN)
        self.client.portal.call(self.manager.library.stop)
        meta.update(complete=False,preparing=True,available_duration=12)
        with self.manager.db() as db:
            db.execute("UPDATE episodes SET status='partial',media=?,progress=? WHERE id=?",(json.dumps(meta),json.dumps({'status':'processing','prepared_seconds':12,'total_seconds':120,'percent':10}),ident))
        self.root.state.update(playing=True,position=9)
        self.client.portal.call(self.manager.library.start)
        self.assertFalse(self.root.state['playing']);self.assertEqual(self.root.state['position'],0)
        self.assertEqual(self.root.media['episode_id'],ident)
        self.assertFalse(self.root.media['preparing'])
        self.assertEqual(self.manager.library.get('default',ident)['status'],'failed')
        self.assertEqual(self.root.processing['status'],'error')

    def test_retry_generates_new_asset_and_preserves_other_episodes(self):
        self.join();ident,meta=self.episode(status='failed');other,_=self.episode('Other')
        self.client.portal.call(self.manager.library.stop)
        source=ident+'.upload';(self.root.DATA/source).write_bytes(b'source')
        with self.manager.db() as db:db.execute('UPDATE episodes SET source=? WHERE id=?',(source,ident))
        self.client.post('/api/episodes/'+ident+'/select',headers=ORIGIN)
        response=self.client.post('/api/episodes/'+ident+'/retry',headers=ORIGIN)
        self.assertEqual(response.status_code,200,response.text)
        row=self.manager.library.get('default',ident)
        self.assertEqual(row['status'],'queued');self.assertEqual(row['generation'],2)
        self.assertNotEqual(row['asset_id'],meta['id']);self.assertIsNone(self.root.media)
        self.assertTrue((self.root.DATA/source).exists())
        self.assertEqual(self.manager.library.get('default',other)['status'],'ready')

    def test_one_worker_serves_rooms_fairly(self):
        self.login();room=self.create_room();self.client.get('/api/admin/metrics')
        library=self.manager.library
        self.client.portal.call(library.stop)
        expected=[]
        for number in range(3):
            for room_id in ['default',room['id']]:
                ident,_=self.episode(str(number),room=room_id,status='failed');expected.append(ident)
        with self.manager.db() as db:db.execute("UPDATE episodes SET status='queued'")
        active=0;maximum=0;processed=[]
        async def fake_prepare(record):
            nonlocal active,maximum
            active+=1;maximum=max(active,maximum);processed.append(record['id'])
            await asyncio.sleep(.01)
            with self.manager.db() as db:db.execute("UPDATE episodes SET status='ready' WHERE id=?",(record['id'],))
            active-=1
        with patch.object(library,'prepare',side_effect=fake_prepare):
            self.client.portal.call(library.start)
            deadline=time.time()+3
            while len(processed)<6 and time.time()<deadline:time.sleep(.01)
            self.client.portal.call(library.stop)
        self.assertEqual(maximum,1);self.assertEqual(processed,expected)

    def test_admin_library_controls_and_bulk_confirmation(self):
        ident,_=self.episode();self.login()
        path='/api/admin/rooms/default/episodes/'+ident
        self.assertEqual(self.client.post(path+'/select',headers=ORIGIN).status_code,200)
        self.assertEqual(self.client.patch(path,json={'title':'Admin title'},headers=ORIGIN).status_code,200)
        self.assertEqual(self.root.media['name'],'Admin title')
        self.assertEqual(self.client.delete('/api/admin/rooms/default/media',headers=ORIGIN).status_code,422)
        self.assertEqual(self.client.request('DELETE','/api/admin/rooms/default/media',json={'confirmation':'CONFIRM'},headers=ORIGIN).status_code,200)
        self.assertEqual(self.manager.library.records('default'),[])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_real_eight_uploads_prepare_without_replacing_selection(self):
        source=self.root.DATA/'fixture.wav'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1',str(source)],check=True)
        payload=source.read_bytes();source.unlink();self.join()
        ids=[]
        for i in range(8):
            response=self.client.post('/api/episodes?name=Episode'+str(i+1),content=payload,headers=ORIGIN)
            self.assertEqual(response.status_code,202,response.text);ids.append(response.json()['id'])
        deadline=time.time()+45
        while time.time()<deadline:
            records=self.client.get('/api/episodes').json()['episodes']
            if all(e['status']=='ready' for e in records):break
            time.sleep(.05)
        self.assertEqual([e['status'] for e in records],['ready']*8,records)
        self.assertIsNone(self.root.media)
        self.assertEqual(self.client.post('/api/episodes/'+ids[0]+'/select',headers=ORIGIN).status_code,200)
        first=self.root.media['id']
        self.assertEqual(self.client.get('/hls/'+first+'/audio/index.m3u8').status_code,200)
        self.assertEqual(self.client.post('/api/episodes/'+ids[1]+'/select',headers=ORIGIN).status_code,200)
        self.assertTrue((self.root.DATA/first).exists())
        self.assertEqual(len(self.manager.library.records('default')),8)
        self.assertEqual(self.client.request('DELETE','/api/episodes',json={'confirmation':'CONFIRM'},headers=ORIGIN).status_code,200)
        self.assertEqual(self.manager.library.records('default'),[])
