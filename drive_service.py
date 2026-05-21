import os
import json
import time
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive']
FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


def get_drive_service():
    sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        sa_path = os.path.join(os.path.dirname(__file__), 'service_account.json')
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def list_subfolders(service, parent_id):
    results = service.files().list(
        q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        orderBy="name"
    ).execute()
    return results.get('files', [])


def list_videos(service, folder_id):
    results = service.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'video/' and trashed=false",
        fields="files(id, name, size, mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        orderBy="name"
    ).execute()
    return results.get('files', [])


def download_video(service, file_id, save_path):
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(save_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def rename_file(service, file_id, new_name):
    new_name = FORBIDDEN.sub('_', new_name).strip()
    service.files().update(
        fileId=file_id,
        body={'name': new_name},
        supportsAllDrives=True
    ).execute()
    time.sleep(0.1)
