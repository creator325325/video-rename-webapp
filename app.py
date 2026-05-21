import streamlit as st
import os
import re
import shutil
import pandas as pd

TMP_DIR = "/tmp/video_rename"

st.set_page_config(page_title="영상 자동 리네이밍", page_icon="🎬", layout="wide")
st.title("🎬 영상 자동 리네이밍")
st.caption("Google Drive 폴더의 영상을 자동으로 분석해 파일명을 변경합니다.")

from drive_service import get_drive_service, list_videos, rename_file


@st.cache_resource
def get_service():
    return get_drive_service()


try:
    service = get_service()
except Exception as e:
    st.error(f"Drive 연결 실패: {e}")
    st.stop()

if 'results' not in st.session_state:
    st.session_state.results = None
if 'folder_id' not in st.session_state:
    st.session_state.folder_id = None


def extract_folder_id(url: str) -> str | None:
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    if re.fullmatch(r'[a-zA-Z0-9_-]{10,}', url.strip()):
        return url.strip()
    return None


# ── Step 1: 폴더 URL 입력 ──────────────────────────────────────────────────────
st.subheader("① 폴더 URL 입력")

folder_url = st.text_input(
    "Google Drive 폴더 링크",
    placeholder="https://drive.google.com/drive/folders/...",
    label_visibility="collapsed"
)

if folder_url:
    folder_id = extract_folder_id(folder_url)
    if not folder_id:
        st.error("올바른 Google Drive 폴더 URL이 아닙니다.")
        st.stop()

    st.session_state.folder_id = folder_id

    try:
        videos = list_videos(service, folder_id)
    except Exception as e:
        st.error(f"폴더 접근 실패: {e}\n\n서비스 계정에 폴더 공유가 됐는지 확인하세요.")
        st.stop()

    if not videos:
        st.info("이 폴더에 영상이 없습니다.")
        st.stop()

    st.info(f"📹 {len(videos)}개 영상 발견")
    with st.expander("목록 보기"):
        for v in videos:
            size_mb = int(v.get('size', 0)) / (1024 * 1024)
            st.text(f"{v['name']}  ({size_mb:.1f} MB)")

    # ── Step 2: 분석 시작 ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("② 분석")
    st.caption("영상당 1~3분 소요됩니다. 탭을 닫지 마세요.")

    if st.button("🔍 분석 시작", type="primary"):
        st.session_state.results = None
        from pipeline import process_video

        results = []
        progress = st.progress(0, text="분석 준비 중...")

        for i, video in enumerate(videos):
            progress.progress(i / len(videos), text=f"[{i+1}/{len(videos)}] {video['name']} 처리 중...")
            work_dir = os.path.join(TMP_DIR, video['id'])

            try:
                new_name = process_video(service, video['id'], video['name'], work_dir)
                results.append({
                    'file_id': video['id'],
                    'original_name': video['name'],
                    'new_name': new_name,
                    'apply': True,
                    'status': '✓'
                })
            except Exception as e:
                results.append({
                    'file_id': video['id'],
                    'original_name': video['name'],
                    'new_name': video['name'],
                    'apply': False,
                    'status': f'실패: {str(e)[:60]}'
                })
            finally:
                if os.path.exists(work_dir):
                    shutil.rmtree(work_dir, ignore_errors=True)

        progress.progress(1.0, text="분석 완료!")
        st.session_state.results = results


# ── Step 3: 확인 및 적용 ────────────────────────────────────────────────────────
if st.session_state.results:
    st.divider()
    st.subheader("③ 확인 및 적용")
    st.caption("새 파일명 직접 수정 가능 | apply 체크 해제 시 해당 파일은 변경하지 않습니다")

    df = pd.DataFrame(st.session_state.results)

    edited = st.data_editor(
        df[['original_name', 'new_name', 'apply', 'status']],
        use_container_width=True,
        hide_index=True,
        column_config={
            'original_name': st.column_config.TextColumn("원본 파일명", disabled=True, width="large"),
            'new_name': st.column_config.TextColumn("새 파일명", width="large"),
            'apply': st.column_config.CheckboxColumn("적용", width="small"),
            'status': st.column_config.TextColumn("상태", disabled=True, width="small"),
        }
    )

    to_apply = edited[edited['apply'] == True]
    st.caption(f"적용 대상: **{len(to_apply)}개** / 전체 {len(edited)}개")

    if st.button("✅ 적용하기", type="primary", disabled=len(to_apply) == 0):
        file_id_map = {r['original_name']: r['file_id'] for r in st.session_state.results}
        success, fail = 0, 0

        with st.status("Drive에 적용 중...", expanded=True) as status_widget:
            for _, row in to_apply.iterrows():
                fid = file_id_map.get(row['original_name'])
                try:
                    rename_file(service, fid, row['new_name'])
                    st.write(f"✓ {row['original_name']}  →  {row['new_name']}")
                    success += 1
                except Exception as e:
                    st.write(f"✗ {row['original_name']} 실패: {e}")
                    fail += 1

            status_widget.update(
                label=f"완료!  성공 {success}개 / 실패 {fail}개",
                state="complete"
            )

        st.session_state.results = None
        if success > 0:
            st.balloons()
