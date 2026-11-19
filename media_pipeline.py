"""Incremental HLS preparation: one video playlist, one playlist per audio
language, and WebVTT sidecars for text subtitles."""
from pathlib import Path
import math
import re

SEGMENT_SECONDS = 4
STARTUP_SECONDS = 8

# ffprobe codec names of subtitle streams that can be converted to WebVTT text.
TEXT_SUBTITLE_CODECS = {
    'ass', 'ssa', 'subrip', 'srt', 'mov_text', 'webvtt', 'text',
}

# Common ISO 639-2/639-1 codes used when a stream carries no title tag. The
# browser can also localise these codes, so this is only a readable fallback.
LANGUAGE_NAMES = {
    'eng': 'English', 'en': 'English', 'hin': 'Hindi', 'hi': 'Hindi',
    'tam': 'Tamil', 'ta': 'Tamil', 'tel': 'Telugu', 'te': 'Telugu',
    'mal': 'Malayalam', 'ml': 'Malayalam', 'kan': 'Kannada', 'kn': 'Kannada',
    'ben': 'Bengali', 'bn': 'Bengali', 'mar': 'Marathi', 'mr': 'Marathi',
    'guj': 'Gujarati', 'gu': 'Gujarati', 'pan': 'Punjabi', 'pa': 'Punjabi',
    'urd': 'Urdu', 'ur': 'Urdu', 'ori': 'Odia', 'or': 'Odia',
    'sin': 'Sinhala', 'si': 'Sinhala', 'nep': 'Nepali', 'ne': 'Nepali',
    'ara': 'Arabic', 'ar': 'Arabic', 'spa': 'Spanish', 'es': 'Spanish',
    'fre': 'French', 'fra': 'French', 'fr': 'French',
    'ger': 'German', 'deu': 'German', 'de': 'German',
    'ita': 'Italian', 'it': 'Italian', 'por': 'Portuguese', 'pt': 'Portuguese',
    'rus': 'Russian', 'ru': 'Russian', 'jpn': 'Japanese', 'ja': 'Japanese',
    'kor': 'Korean', 'ko': 'Korean', 'chi': 'Chinese', 'zho': 'Chinese',
    'zh': 'Chinese', 'dut': 'Dutch', 'nld': 'Dutch', 'nl': 'Dutch',
    'pol': 'Polish', 'pl': 'Polish', 'tur': 'Turkish', 'tr': 'Turkish',
    'swe': 'Swedish', 'sv': 'Swedish', 'nor': 'Norwegian', 'no': 'Norwegian',
    'dan': 'Danish', 'da': 'Danish', 'fin': 'Finnish', 'fi': 'Finnish',
    'cze': 'Czech', 'ces': 'Czech', 'cs': 'Czech',
    'gre': 'Greek', 'ell': 'Greek', 'el': 'Greek',
    'heb': 'Hebrew', 'he': 'Hebrew', 'tha': 'Thai', 'th': 'Thai',
    'vie': 'Vietnamese', 'vi': 'Vietnamese', 'ind': 'Indonesian', 'id': 'Indonesian',
    'msa': 'Malay', 'ms': 'Malay', 'fil': 'Filipino', 'tgl': 'Tagalog',
    'ukr': 'Ukrainian', 'uk': 'Ukrainian', 'rum': 'Romanian', 'ron': 'Romanian',
    'hun': 'Hungarian', 'hu': 'Hungarian', 'bul': 'Bulgarian', 'bg': 'Bulgarian',
    'hrv': 'Croatian', 'srp': 'Serbian', 'slk': 'Slovak', 'slk': 'Slovak',
    'slv': 'Slovenian', 'lit': 'Lithuanian', 'lav': 'Latvian', 'est': 'Estonian',
    'cat': 'Catalan', 'ca': 'Catalan', 'eus': 'Basque', 'baq': 'Basque',
    'glg': 'Galician', 'gl': 'Galician', 'per': 'Persian', 'fas': 'Persian',
    'swa': 'Swahili', 'sw': 'Swahili', 'amh': 'Amharic', 'am': 'Amharic',
    'yor': 'Yoruba', 'yo': 'Yoruba', 'ibo': 'Igbo', 'ig': 'Igbo',
    'hau': 'Hausa', 'ha': 'Hausa', 'zul': 'Zulu', 'zu': 'Zulu',
    'afr': 'Afrikaans', 'af': 'Afrikaans',
}


def video_stream(info):
    return next((s for s in info['streams'] if s['codec_type'] == 'video'
                 and not s.get('disposition', {}).get('attached_pic')), None)


def audio_streams(info):
    return [s for s in info['streams'] if s['codec_type'] == 'audio']


def subtitle_streams(info):
    return [s for s in info['streams'] if s['codec_type'] == 'subtitle']


def can_copy_video(stream):
    return bool(stream and stream.get('codec_name') == 'h264'
                and stream.get('pix_fmt') == 'yuv420p'
                and 0 < stream.get('width', 0) <= 1920
                and 0 < stream.get('height', 0) <= 1080)


def _text(value):
    """Collapse whitespace and strip quotes so values are safe in HLS attributes."""
    return ' '.join(str(value or '').replace('"', "'").split())


def _language_label(code):
    return LANGUAGE_NAMES.get((code or '').lower(), '')


def _unique_label(label, used):
    candidate, suffix = label, 2
    while candidate.casefold() in used:
        candidate = f'{label} ({suffix})'
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def describe_audio(info):
    """Audio tracks in playback order, with the container's default track first."""
    streams = audio_streams(info)
    order = sorted(range(len(streams)),
                   key=lambda index: (0 if (streams[index].get('disposition') or {}).get('default') else 1,
                                      index))
    used, tracks = set(), []
    for position, ordinal in enumerate(order):
        stream = streams[ordinal]
        tags = stream.get('tags') or {}
        title = _text(tags.get('title'))
        language = _text(tags.get('language')).lower()
        label = _unique_label(title or _language_label(language) or f'Audio {position + 1}', used)
        track = {'id': 'audio' if position == 0 else f'audio{position + 1}',
                 'stream': ordinal, 'label': label, 'title': title,
                 'language': language, 'channels': int(stream.get('channels') or 0)}
        if position == 0:
            track['default'] = True
        tracks.append(track)
    return tracks


def describe_subtitles(info):
    """Text subtitle tracks that can be converted to WebVTT, in stream order."""
    used, tracks = set(), []
    for ordinal, stream in enumerate(subtitle_streams(info)):
        codec = (stream.get('codec_name') or '').lower()
        if codec not in TEXT_SUBTITLE_CODECS:
            continue
        tags = stream.get('tags') or {}
        title = _text(tags.get('title'))
        language = _text(tags.get('language')).lower()
        label = _unique_label(title or _language_label(language) or f'Subtitles {len(tracks) + 1}', used)
        tracks.append({'id': f's{len(tracks)}', 'stream': ordinal, 'label': label,
                       'title': title, 'language': language, 'codec': codec})
    return tracks


def build_command(source, folder, info, input_options, audio_tracks=None):
    video = video_stream(info)
    streams = audio_streams(info)
    tracks = describe_audio(info) if audio_tracks is None else audio_tracks
    if not tracks:
        raise ValueError('Choose a movie or song with an audio track.')
    args = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-nostats', '-stats_period', '0.5',
            '-progress', 'pipe:1', '-copyts', '-start_at_zero', *input_options, '-i', str(source)]

    def output(track):
        target = folder / track
        target.mkdir(exist_ok=True)
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
    for track in tracks:
        audio = streams[track['stream']]
        args += ['-map', f"0:a:{track['stream']}", '-vn']
        if audio.get('codec_name') == 'aac' and audio.get('profile', 'LC') == 'LC':
            args += ['-c:a', 'copy']
        else:
            args += ['-af', 'aresample=async=1:first_pts=0', '-c:a', 'aac', '-b:a', '160k', '-ac', '2']
        args += output(track['id'])
    return args, copied


def build_subtitle_command(source, folder, subtitle_tracks, input_options):
    """Best-effort WebVTT extraction, run separately from the playable encodes."""
    target = folder / 'subtitles'
    target.mkdir(parents=True, exist_ok=True)
    args = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-copyts', '-start_at_zero',
            *input_options, '-i', str(source)]
    for track in subtitle_tracks:
        args += ['-map', f"0:s:{track['stream']}", '-c:s', 'webvtt', '-f', 'webvtt',
                 str(target / f"{track['id']}.vtt")]
    return args


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
    # Extra audio languages are encoded from the same timeline as the default
    # track, so the default track plus video is enough to bound readiness.
    tracks = ['audio', 'video'] if has_video else ['audio']
    return min(playlist_status(folder / track / 'index.m3u8')[0] for track in tracks)


def _master_header():
    return '#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-START:TIME-OFFSET=0,PRECISE=YES\n'


def _audio_media_line(track, default):
    attributes = ['TYPE=AUDIO', 'GROUP-ID="audio"', f'NAME="{_text(track.get("label") or track["id"])}"']
    if track.get('language'):
        attributes.append(f'LANGUAGE="{_text(track["language"])}"')
    attributes += [f'DEFAULT={"YES" if default else "NO"}', 'AUTOSELECT=YES']
    if track.get('channels'):
        attributes.append(f'CHANNELS="{int(track["channels"])}"')
    attributes.append(f'URI="{track["id"]}/index.m3u8"')
    return '#EXT-X-MEDIA:' + ','.join(attributes)


def write_master(folder, has_video, audio_tracks=None):
    tracks = audio_tracks or [{'id': 'audio', 'label': 'Audio', 'default': True}]
    header = _master_header()
    # A single-language master per track keeps audio-only mode able to switch
    # languages without depending on alternate-audio support in hls.js.
    for track in tracks:
        (folder / f"{track['id']}.m3u8").write_text(
            header + f'#EXT-X-STREAM-INF:BANDWIDTH=192000,CODECS="mp4a.40.2"\n{track["id"]}/index.m3u8\n')
    media = '\n'.join(_audio_media_line(track, index == 0) for index, track in enumerate(tracks))
    if has_video:
        codec = 'avc1.64001f'
        init = folder / 'video/init.mp4'
        if init.exists():
            data = init.read_bytes()
            offset = data.find(b'avcC')
            if offset >= 0 and len(data) >= offset + 8:
                codec = 'avc1.' + data[offset + 5:offset + 8].hex()
        content = (f'{media}\n'
                   f'#EXT-X-STREAM-INF:BANDWIDTH=8000000,CODECS="{codec},mp4a.40.2",AUDIO="audio"\nvideo/index.m3u8\n')
        (folder / 'video.m3u8').write_text(header + f'#EXT-X-STREAM-INF:BANDWIDTH=8000000,CODECS="{codec}"\nvideo/index.m3u8\n')
    else:
        content = ''.join(f'#EXT-X-STREAM-INF:BANDWIDTH=192000,CODECS="mp4a.40.2"\n{track["id"]}/index.m3u8\n'
                          for track in tracks)
    (folder / 'master.m3u8').write_text(header + content)


def finish_partial(folder, has_video):
    tracks = ['video'] if has_video else []
    try:
        tracks += sorted(path.name for path in folder.iterdir()
                         if path.is_dir() and re.fullmatch(r'audio\d*', path.name))
    except OSError:
        pass
    for track in tracks:
        path = folder / track / 'index.m3u8'
        if path.exists():
            content = path.read_text()
            if '#EXT-X-ENDLIST' not in content:
                temporary = path.with_suffix('.final')
                temporary.write_text(content.rstrip() + '\n#EXT-X-ENDLIST\n')
                temporary.replace(path)
