from pathlib import Path
import tempfile
import unittest
from media_pipeline import available_seconds, build_command, can_copy_video, playlist_status


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
