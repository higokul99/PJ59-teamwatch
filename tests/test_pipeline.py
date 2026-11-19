from pathlib import Path
import tempfile
import unittest
from media_pipeline import (available_seconds, build_command, build_subtitle_command, can_copy_video,
                            describe_audio, describe_subtitles, finish_partial, playlist_status,
                            write_master)


class PipelineTests(unittest.TestCase):
    def test_compatible_h264_avoids_video_reencoding(self):
        stream = {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'width': 854, 'height': 480, 'index': 0}
        self.assertTrue(can_copy_video(stream))
        with tempfile.TemporaryDirectory() as directory:
            args, copied = build_command(Path('movie.mp4'), Path(directory), {'streams': [stream, {'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC'}]}, [])
        self.assertTrue(copied)
        self.assertNotIn('libx264', args)
        self.assertIn('event', args)
        self.assertIn('fmp4', args)
        self.assertIn('pipe:1', args)

    def test_incompatible_video_uses_one_encoder_and_audio_only_does_not(self):
        for stream in ({'codec_type': 'video', 'codec_name': 'hevc'}, {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p10le'}):
            with tempfile.TemporaryDirectory() as directory:
                args, copied = build_command(Path('movie.mkv'), Path(directory), {'streams': [stream, {'codec_type': 'audio', 'codec_name': 'opus'}]}, [])
            self.assertFalse(copied)
            self.assertEqual(args.count('libx264'), 1)
        with tempfile.TemporaryDirectory() as directory:
            args, _ = build_command(Path('song.wav'), Path(directory), {'streams': [{'codec_type': 'audio', 'codec_name': 'pcm_s16le'}]}, [])
        self.assertNotIn('libx264', args)

    def test_progress_counts_only_complete_segments_in_both_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for track, duration in [('video', 8), ('audio', 4)]:
                folder = root / track
                folder.mkdir()
                (folder / 'init.mp4').write_bytes(b'init')
                (folder / 'segment_000000.m4s').write_bytes(b'segment')
                (folder / 'index.m3u8').write_text(f'#EXTM3U\n#EXTINF:{duration},\nsegment_000000.m4s\n#EXTINF:4,\nsegment_000001.m4s\n')
                (folder / 'segment_000001.m4s.tmp').write_bytes(b'incomplete')
            self.assertEqual(available_seconds(root, True), 4)
            self.assertEqual(playlist_status(root / 'video/index.m3u8'), (8, False))

    def test_audio_tracks_keep_the_default_first_and_create_one_playlist_each(self):
        info = {'streams': [
            {'index': 0, 'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'width': 640, 'height': 360},
            {'index': 1, 'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC', 'channels': 2,
             'tags': {'language': 'eng', 'title': 'English'}, 'disposition': {}},
            {'index': 2, 'codec_type': 'audio', 'codec_name': 'eac3', 'channels': 6,
             'tags': {'language': 'hin'}, 'disposition': {'default': 1}},
        ]}
        tracks = describe_audio(info)
        self.assertEqual([track['id'] for track in tracks], ['audio', 'audio2'])
        self.assertEqual([track['language'] for track in tracks], ['hin', 'eng'])
        self.assertEqual(tracks[0]['label'], 'Hindi')
        self.assertTrue(tracks[0]['default'])
        self.assertNotIn('default', tracks[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, _ = build_command(Path('movie.mkv'), root, info, [], tracks)
            self.assertIn('0:a:1', args)
            self.assertIn('0:a:0', args)
            self.assertIn(str(root / 'audio/index.m3u8'), args)
            self.assertIn(str(root / 'audio2/index.m3u8'), args)
            write_master(root, True, tracks)
            master = (root / 'master.m3u8').read_text()
            self.assertIn('TYPE=AUDIO', master)
            self.assertIn('NAME="Hindi"', master)
            self.assertIn('NAME="English"', master)
            self.assertIn('DEFAULT=YES', master)
            self.assertIn('audio2/index.m3u8', master)
            self.assertIn('video/index.m3u8', master)
            self.assertTrue((root / 'audio2.m3u8').is_file())
            self.assertIn('audio2/index.m3u8', (root / 'audio2.m3u8').read_text())

    def test_text_subtitles_keep_their_original_stream_ordinal(self):
        info = {'streams': [
            {'codec_type': 'video', 'codec_name': 'h264'},
            {'codec_type': 'audio', 'codec_name': 'aac'},
            {'codec_type': 'subtitle', 'codec_name': 'hdmv_pgs_subtitle', 'tags': {'language': 'eng'}},
            {'codec_type': 'subtitle', 'codec_name': 'subrip', 'tags': {'language': 'hin', 'title': 'Hindi'}},
        ]}
        tracks = describe_subtitles(info)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]['id'], 's0')
        self.assertEqual(tracks[0]['stream'], 1)
        self.assertEqual(tracks[0]['label'], 'Hindi')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = build_subtitle_command(Path('movie.mkv'), root, tracks, [])
            self.assertIn('0:s:1', args)
            self.assertIn(str(root / 'subtitles/s0.vtt'), args)
            self.assertIn('webvtt', args)

    def test_audio_only_master_lists_each_language_as_a_variant(self):
        tracks = [{'id': 'audio', 'label': 'English', 'language': 'eng', 'default': True},
                  {'id': 'audio2', 'label': 'Hindi', 'language': 'hin'}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_master(root, False, tracks)
            master = (root / 'master.m3u8').read_text()
            self.assertEqual(master.count('#EXT-X-STREAM-INF'), 2)
            self.assertIn('audio/index.m3u8', master)
            self.assertIn('audio2/index.m3u8', master)
            self.assertNotIn('video/index.m3u8', master)

    def test_finish_partial_finalizes_every_audio_language(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for track in ('audio', 'audio2'):
                folder = root / track
                folder.mkdir()
                (folder / 'index.m3u8').write_text('#EXTM3U\n#EXTINF:4,\nsegment_000000.m4s\n')
            finish_partial(root, False)
            for track in ('audio', 'audio2'):
                self.assertIn('#EXT-X-ENDLIST', (root / track / 'index.m3u8').read_text())
