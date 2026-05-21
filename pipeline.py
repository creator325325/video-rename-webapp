import os
import subprocess
import base64
import re
import shutil
from pathlib import Path

FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


def get_duration(video_path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 30.0


def extract_audio(video_path, audio_path):
    result = subprocess.run(
        ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le',
         '-ar', '16000', '-ac', '1', '-y', audio_path],
        capture_output=True
    )
    return result.returncode == 0 and os.path.exists(audio_path)


def extract_keyframes(video_path, frames_dir, duration):
    os.makedirs(frames_dir, exist_ok=True)
    if duration < 10:
        vf = 'fps=1,scale=640:-1'
    elif duration < 300:
        vf = 'fps=1/10,scale=640:-1'
    elif duration < 1800:
        vf = 'fps=1/30,scale=640:-1'
    else:
        vf = 'fps=1/60,scale=640:-1'

    subprocess.run(
        ['ffmpeg', '-i', video_path, '-vf', vf, '-frames:v', '8',
         '-y', os.path.join(frames_dir, 'frame_%03d.jpg')],
        capture_output=True
    )

    frames = sorted(Path(frames_dir).glob('frame_*.jpg'))
    if not frames:
        subprocess.run(
            ['ffmpeg', '-i', video_path, '-ss', '0', '-frames:v', '1',
             '-q:v', '2', '-y', os.path.join(frames_dir, 'frame_001.jpg')],
            capture_output=True
        )
        frames = sorted(Path(frames_dir).glob('frame_*.jpg'))

    return [str(f) for f in frames]


def transcribe(audio_path):
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_path, language="ko", beam_size=3)
    return " ".join(seg.text for seg in segments)


def generate_filename(transcript, frame_paths, original_name):
    import anthropic

    client = anthropic.Anthropic()
    ext = Path(original_name).suffix or '.mp4'

    content = [{
        "type": "text",
        "text": f"""다음은 영상의 자막과 화면 스냅샷입니다. 영상 내용을 파악해서 의미있는 파일명을 만들어주세요.

규칙:
- 형식: 주제_세부키워드{ext}
- 한글 사용 가능, 공백 대신 언더스코어(_)
- 50자 이내, 특수문자 금지 (\ / : * ? " < > | 불가)
- 파일명만 답하세요 (설명 없이, 확장자 포함)

원본 파일명: {original_name}
자막: {transcript[:3000] if transcript else '(음성 없음)'}"""
    }]

    for frame_path in frame_paths[:6]:
        try:
            with open(frame_path, 'rb') as f:
                data = base64.standard_b64encode(f.read()).decode()
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": data}
            })
        except Exception:
            pass

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": content}]
    )

    new_name = response.content[0].text.strip()
    new_name = FORBIDDEN.sub('_', new_name).strip()
    if not new_name.lower().endswith(ext.lower()):
        new_name += ext
    return new_name


def process_video(service, file_id, original_name, work_dir):
    from drive_service import download_video

    os.makedirs(work_dir, exist_ok=True)
    ext = Path(original_name).suffix or '.mp4'
    video_path = os.path.join(work_dir, f'video{ext}')
    audio_path = os.path.join(work_dir, 'audio.wav')
    frames_dir = os.path.join(work_dir, 'frames')

    try:
        download_video(service, file_id, video_path)
        duration = get_duration(video_path)

        transcript = ""
        if extract_audio(video_path, audio_path):
            try:
                transcript = transcribe(audio_path)
            except Exception:
                pass

        frame_paths = extract_keyframes(video_path, frames_dir, duration)
        new_name = generate_filename(transcript, frame_paths, original_name)
        return new_name

    finally:
        for p in [video_path, audio_path]:
            if os.path.exists(p):
                os.remove(p)
        if os.path.exists(frames_dir):
            shutil.rmtree(frames_dir, ignore_errors=True)
