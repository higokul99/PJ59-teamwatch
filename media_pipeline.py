"""Incremental HLS preparation: one video stream, one audio stream, shared master."""
from pathlib import Path
import math
import re

SEGMENT_SECONDS = 4
STARTUP_SECONDS = 8


def video_stream(info):
    return next((s for s in info['streams'] if s['codec_type'] == 'video'
                 and not s.get('disposition', {}).get('attached_pic')), None)


def can_copy_video(stream):
    return bool(stream and stream.get('codec_name') == 'h264'
                and stream.get('pix_fmt') == 'yuv420p'
                and 0 < stream.get('width', 0) <= 1920
                and 0 < stream.get('height', 0) <= 1080)


def build_command(source, folder, info, input_options):
    video = video_stream(info)
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    args = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-nostats', '-stats_period', '0.5',
            '-progress', 'pipe:1', '-copyts', '-start_at_zero', *input_options, '-i', str(source)]

    def output(track):
        target = folder / track
        target.mkdir()
        return ['-f', 'hls', '-hls_time', str(SEGMENT_SECONDS), '-hls_list_size', '0',
                '-hls_playlist_type', 'event', '-hls_segment_type', 'fmp4',
                '-hls_fmp4_init_filename', 'init.mp4', '-hls_flags', 'temp_file+independent_segments',
                '-hls_segment_filename', str(target / 'segment_%06d.m4s'), str(target / 'index.m3u8')]

    copied = can_copy_video(video)
    if video:
        selector = f"0:{video['index']}" if 'index' in video else '0:v:0'
        args += ['-map', selector, '-an']
        if copied:
            args += ['-c:v', 'copy']
        else:
            args += ['-vf', "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30", '-c:v', 'libx264',
                     '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-threads', '2',
                     '-force_key_frames', 'expr:gte(t,n_forced*4)', '-sc_threshold', '0']
        args += output('video')
    args += ['-map', '0:a:0', '-vn']
    if audio.get('codec_name') == 'aac' and audio.get('profile', 'LC') == 'LC':
        args += ['-c:a', 'copy']
    else:
        args += ['-af', 'aresample=async=1:first_pts=0', '-c:a', 'aac', '-b:a', '160k', '-ac', '2']
    args += output('audio')
    return args, copied


def playlist_status(path):
    """Only count published complete segments, never ffmpeg's temporary files."""
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        return 0.0, False
    duration, pending = 0.0, None
    for line in text.splitlines():
        if line.startswith('#EXTINF:'):
            try:
                pending = float(line.split(':', 1)[1].split(',')[0])
            except ValueError:
                pending = None
        elif line and not line.startswith('#') and pending is not None:
            if (not re.fullmatch(r'segment_\d{6,}\.m4s', line)
                    or not (path.parent / line).is_file()):
                break
            if math.isfinite(pending) and pending > 0:
                duration += pending
            pending = None
    if not (path.parent / 'init.mp4').is_file():
        return 0.0, False
    return duration, '#EXT-X-ENDLIST' in text


def available_seconds(folder, has_video):
    tracks = ['audio', 'video'] if has_video else ['audio']
    return min(playlist_status(folder / track / 'index.m3u8')[0] for track in tracks)


def write_master(folder, has_video):
    header = '#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-START:TIME-OFFSET=0,PRECISE=YES\n'
    audio = '#EXT-X-STREAM-INF:BANDWIDTH=192000,CODECS="mp4a.40.2"\naudio/index.m3u8\n'
    (folder / 'audio.m3u8').write_text(header + audio)
    if has_video:
        codec = 'avc1.64001f'
        init = folder / 'video/init.mp4'
        if init.exists():
            data = init.read_bytes()
            offset = data.find(b'avcC')
            if offset >= 0 and len(data) >= offset + 8:
                codec = 'avc1.' + data[offset + 5:offset + 8].hex()
        content = (f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="audio/index.m3u8"\n'
                   f'#EXT-X-STREAM-INF:BANDWIDTH=8000000,CODECS="{codec},mp4a.40.2",AUDIO="audio"\nvideo/index.m3u8\n')
        (folder / 'video.m3u8').write_text(header + f'#EXT-X-STREAM-INF:BANDWIDTH=8000000,CODECS="{codec}"\nvideo/index.m3u8\n')
    else:
        content = audio
    (folder / 'master.m3u8').write_text(header + content)


def finish_partial(folder, has_video):
    for track in (['audio', 'video'] if has_video else ['audio']):
        path = folder / track / 'index.m3u8'
        if path.exists():
            content = path.read_text()
            if '#EXT-X-ENDLIST' not in content:
                temporary = path.with_suffix('.final')
                temporary.write_text(content.rstrip() + '\n#EXT-X-ENDLIST\n')
                temporary.replace(path)
