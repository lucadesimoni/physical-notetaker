"""
Lean cloud storage for recordings and transcripts
"""

import shutil
from typing import Optional, List
from dataclasses import dataclass
from pathlib import Path

from .config import StorageConfig, StorageProvider


@dataclass
class UploadResult:
    success: bool
    file_path: str
    provider: str
    url: Optional[str] = None
    error: Optional[str] = None


class CloudStorage:
    """Cloud storage manager"""
    
    def __init__(self, config: StorageConfig):
        self.config = config
        self._google_service = None
        self._dropbox_client = None
        self._s3_client = None
    
    def upload(self, file_path: str) -> List[UploadResult]:
        """Upload file to configured providers"""
        results = []
        
        if self.config.provider == StorageProvider.LOCAL or self.config.provider == StorageProvider.ALL:
            results.append(self._upload_local(file_path))
        
        if self.config.provider == StorageProvider.GOOGLE_DRIVE or self.config.provider == StorageProvider.ALL:
            if self.config.google_credentials:
                results.append(self._upload_google(file_path))
        
        if self.config.provider == StorageProvider.DROPBOX or self.config.provider == StorageProvider.ALL:
            if self.config.dropbox_token:
                results.append(self._upload_dropbox(file_path))
        
        if self.config.provider == StorageProvider.S3 or self.config.provider == StorageProvider.ALL:
            if self.config.s3_bucket:
                results.append(self._upload_s3(file_path))
        
        return results
    
    def _upload_local(self, file_path: str) -> UploadResult:
        """Save to local storage"""
        try:
            dest = Path(self.config.local_path) / Path(file_path).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (dest.exists() and dest.samefile(file_path)):
                shutil.copy2(file_path, dest)
            return UploadResult(success=True, file_path=str(dest), provider="local")
        except Exception as e:
            return UploadResult(success=False, file_path=file_path, provider="local", error=str(e))
    
    def _upload_google(self, file_path: str) -> UploadResult:
        """Upload to Google Drive"""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            
            if not self._google_service:
                creds = Credentials.from_authorized_user_file(
                    self.config.google_credentials,
                    ['https://www.googleapis.com/auth/drive.file']
                )
                self._google_service = build('drive', 'v3', credentials=creds)
            
            file_metadata = {'name': Path(file_path).name}
            if self.config.google_folder_id:
                file_metadata['parents'] = [self.config.google_folder_id]
            
            media = MediaFileUpload(file_path, mimetype=None, resumable=True)
            file = self._google_service.files().create(
                body=file_metadata, media_body=media, fields='id,webViewLink'
            ).execute()
            
            return UploadResult(
                success=True, file_path=file_path, 
                provider="google_drive", url=file.get('webViewLink')
            )
        except Exception as e:
            return UploadResult(success=False, file_path=file_path, provider="google_drive", error=str(e))
    
    def _upload_dropbox(self, file_path: str) -> UploadResult:
        """Upload to Dropbox"""
        try:
            import dropbox
            
            if not self._dropbox_client:
                self._dropbox_client = dropbox.Dropbox(self.config.dropbox_token)
            
            dest = f"{self.config.dropbox_folder}/{Path(file_path).name}"
            with open(file_path, 'rb') as f:
                response = self._dropbox_client.files_upload(
                    f.read(), dest, mode=dropbox.files.WriteMode.overwrite
                )
            
            return UploadResult(
                success=True, file_path=file_path,
                provider="dropbox", 
                url=f"https://www.dropbox.com/home{response.path_display}"
            )
        except Exception as e:
            return UploadResult(success=False, file_path=file_path, provider="dropbox", error=str(e))
    
    def _upload_s3(self, file_path: str) -> UploadResult:
        """Upload to S3"""
        try:
            import boto3
            
            if not self._s3_client:
                self._s3_client = boto3.client(
                    's3', region_name=self.config.s3_region,
                    aws_access_key_id=self.config.s3_access_key,
                    aws_secret_access_key=self.config.s3_secret_key
                )
            
            obj_key = f"voxtral_notetaker/{Path(file_path).name}"
            self._s3_client.upload_file(file_path, self.config.s3_bucket, obj_key)
            
            url = self._s3_client.generate_presigned_url(
                'get_object', Params={'Bucket': self.config.s3_bucket, 'Key': obj_key}, ExpiresIn=3600
            )
            
            return UploadResult(success=True, file_path=file_path, provider="s3", url=url)
        except Exception as e:
            return UploadResult(success=False, file_path=file_path, provider="s3", error=str(e))
