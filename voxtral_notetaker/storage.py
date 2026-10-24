"""
Cloud storage module for saving recordings and transcripts
"""

import os
import json
import shutil
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import dropbox

from .config import StorageConfig, StorageProvider


@dataclass
class UploadResult:
    """Result of file upload"""
    success: bool
    file_path: str
    url: Optional[str] = None
    provider: str = ""
    size: int = 0
    error: Optional[str] = None


class CloudStorage:
    """Cloud storage manager for multiple providers"""
    
    def __init__(self, config: StorageConfig):
        self.config = config
        self._google_service = None
        self._dropbox_client = None
        self._s3_client = None
    
    def upload(self, file_path: str, 
               destination: Optional[str] = None) -> List[UploadResult]:
        """Upload file to configured cloud providers"""
        results = []
        
        if self.config.provider == StorageProvider.LOCAL or self.config.provider == StorageProvider.ALL:
            result = self._upload_local(file_path, destination)
            results.append(result)
        
        if self.config.provider == StorageProvider.GOOGLE_DRIVE or self.config.provider == StorageProvider.ALL:
            result = self._upload_google_drive(file_path, destination)
            results.append(result)
        
        if self.config.provider == StorageProvider.DROPBOX or self.config.provider == StorageProvider.ALL:
            result = self._upload_dropbox(file_path, destination)
            results.append(result)
        
        if self.config.provider == StorageProvider.S3 or self.config.provider == StorageProvider.ALL:
            result = self._upload_s3(file_path, destination)
            results.append(result)
        
        return results
    
    def _upload_local(self, file_path: str, 
                      destination: Optional[str] = None) -> UploadResult:
        """Save file to local storage"""
        try:
            # Determine destination path
            if destination:
                dest_path = Path(destination)
            else:
                dest_path = Path(self.config.local_path) / Path(file_path).name
            
            # Create directory if it doesn't exist
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file
            shutil.copy2(file_path, dest_path)
            
            file_size = os.path.getsize(file_path)
            
            return UploadResult(
                success=True,
                file_path=str(dest_path),
                provider="local",
                size=file_size
            )
        except Exception as e:
            return UploadResult(
                success=False,
                file_path=file_path,
                provider="local",
                error=str(e)
            )
    
    def _upload_google_drive(self, file_path: str, 
                             destination: Optional[str] = None) -> UploadResult:
        """Upload file to Google Drive"""
        try:
            if not self.config.google_credentials:
                return UploadResult(
                    success=False,
                    file_path=file_path,
                    provider="google_drive",
                    error="Google credentials not configured"
                )
            
            # Initialize Google Drive service
            if not self._google_service:
                self._initialize_google_drive()
            
            if not self._google_service:
                return UploadResult(
                    success=False,
                    file_path=file_path,
                    provider="google_drive",
                    error="Failed to initialize Google Drive service"
                )
            
            # Determine file name and destination
            file_name = Path(file_path).name
            if destination:
                file_name = Path(destination).name
            
            # Determine folder
            folder_id = self.config.google_folder_id
            
            # Create file metadata
            file_metadata = {
                'name': file_name,
            }
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            # Upload file
            media = MediaFileUpload(file_path, mimetype=None, resumable=True)
            file = self._google_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,webViewLink'
            ).execute()
            
            file_size = os.path.getsize(file_path)
            
            return UploadResult(
                success=True,
                file_path=file_path,
                url=file.get('webViewLink'),
                provider="google_drive",
                size=file_size
            )
            
        except Exception as e:
            return UploadResult(
                success=False,
                file_path=file_path,
                provider="google_drive",
                error=str(e)
            )
    
    def _upload_dropbox(self, file_path: str, 
                        destination: Optional[str] = None) -> UploadResult:
        """Upload file to Dropbox"""
        try:
            if not self.config.dropbox_token:
                return UploadResult(
                    success=False,
                    file_path=file_path,
                    provider="dropbox",
                    error="Dropbox token not configured"
                )
            
            # Initialize Dropbox client
            if not self._dropbox_client:
                self._dropbox_client = dropbox.Dropbox(self.config.dropbox_token)
            
            # Determine destination path
            file_name = Path(file_path).name
            if destination:
                dropbox_path = f"{self.config.dropbox_folder}/{destination}"
            else:
                dropbox_path = f"{self.config.dropbox_folder}/{file_name}"
            
            # Upload file
            with open(file_path, 'rb') as f:
                response = self._dropbox_client.files_upload(
                    f.read(),
                    dropbox_path,
                    mode=dropbox.files.WriteMode('overwrite')
                )
            
            file_size = os.path.getsize(file_path)
            
            return UploadResult(
                success=True,
                file_path=file_path,
                url=f"https://www.dropbox.com{response.path_display}",
                provider="dropbox",
                size=file_size
            )
            
        except Exception as e:
            return UploadResult(
                success=False,
                file_path=file_path,
                provider="dropbox",
                error=str(e)
            )
    
    def _upload_s3(self, file_path: str, 
                   destination: Optional[str] = None) -> UploadResult:
        """Upload file to Amazon S3"""
        try:
            if not self.config.s3_bucket:
                return UploadResult(
                    success=False,
                    file_path=file_path,
                    provider="s3",
                    error="S3 bucket not configured"
                )
            
            # Initialize S3 client
            if not self._s3_client:
                self._s3_client = boto3.client(
                    's3',
                    region_name=self.config.s3_region,
                    aws_access_key_id=self.config.s3_access_key,
                    aws_secret_access_key=self.config.s3_secret_key
                )
            
            # Determine object key
            file_name = Path(file_path).name
            if destination:
                object_key = destination
            else:
                object_key = f"voxtral_notetaker/{file_name}"
            
            # Upload file
            self._s3_client.upload_file(
                file_path,
                self.config.s3_bucket,
                object_key,
                ExtraArgs={
                    'ACL': 'private',
                    'ContentType': self._get_mime_type(file_path)
                }
            )
            
            file_size = os.path.getsize(file_path)
            
            # Generate presigned URL
            url = self._s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.config.s3_bucket,
                    'Key': object_key
                },
                ExpiresIn=3600
            )
            
            return UploadResult(
                success=True,
                file_path=file_path,
                url=url,
                provider="s3",
                size=file_size
            )
            
        except Exception as e:
            return UploadResult(
                success=False,
                file_path=file_path,
                provider="s3",
                error=str(e)
            )
    
    def _initialize_google_drive(self):
        """Initialize Google Drive service"""
        try:
            # Load credentials
            creds = Credentials.from_authorized_user_file(
                self.config.google_credentials,
                ['https://www.googleapis.com/auth/drive.file']
            )
            
            self._google_service = build('drive', 'v3', credentials=creds)
        except Exception as e:
            print(f"Failed to initialize Google Drive: {e}")
            self._google_service = None
    
    def _get_mime_type(self, file_path: str) -> str:
        """Get MIME type for file"""
        extension = Path(file_path).suffix.lower()
        mime_types = {
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
            '.flac': 'audio/flac',
            '.ogg': 'audio/ogg',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.pdf': 'application/pdf',
            '.json': 'application/json',
        }
        return mime_types.get(extension, 'application/octet-stream')
    
    def download(self, remote_path: str, local_path: str, 
                 provider: StorageProvider) -> bool:
        """Download file from cloud storage"""
        if provider == StorageProvider.GOOGLE_DRIVE:
            return self._download_google_drive(remote_path, local_path)
        elif provider == StorageProvider.DROPBOX:
            return self._download_dropbox(remote_path, local_path)
        elif provider == StorageProvider.S3:
            return self._download_s3(remote_path, local_path)
        else:
            # Local - just copy
            try:
                shutil.copy2(remote_path, local_path)
                return True
            except Exception as e:
                print(f"Failed to copy local file: {e}")
                return False
    
    def _download_google_drive(self, file_id: str, local_path: str) -> bool:
        """Download file from Google Drive"""
        try:
            if not self._google_service:
                self._initialize_google_drive()
            
            if not self._google_service:
                return False
            
            request = self._google_service.files().get_media(fileId=file_id)
            fh = open(local_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            fh.close()
            return True
        except Exception as e:
            print(f"Failed to download from Google Drive: {e}")
            return False
    
    def _download_dropbox(self, remote_path: str, local_path: str) -> bool:
        """Download file from Dropbox"""
        try:
            if not self._dropbox_client:
                self._dropbox_client = dropbox.Dropbox(self.config.dropbox_token)
            
            response = self._dropbox_client.files_download(remote_path)
            
            with open(local_path, 'wb') as f:
                f.write(response.content)
            
            return True
        except Exception as e:
            print(f"Failed to download from Dropbox: {e}")
            return False
    
    def _download_s3(self, object_key: str, local_path: str) -> bool:
        """Download file from S3"""
        try:
            if not self._s3_client:
                self._s3_client = boto3.client(
                    's3',
                    region_name=self.config.s3_region,
                    aws_access_key_id=self.config.s3_access_key,
                    aws_secret_access_key=self.config.s3_secret_key
                )
            
            self._s3_client.download_file(
                self.config.s3_bucket,
                object_key,
                local_path
            )
            
            return True
        except Exception as e:
            print(f"Failed to download from S3: {e}")
            return False
    
    def list_files(self, provider: StorageProvider, 
                   path: str = "") -> List[Dict[str, Any]]:
        """List files in cloud storage"""
        if provider == StorageProvider.LOCAL:
            return self._list_local_files(path)
        elif provider == StorageProvider.GOOGLE_DRIVE:
            return self._list_google_drive_files(path)
        elif provider == StorageProvider.DROPBOX:
            return self._list_dropbox_files(path)
        elif provider == StorageProvider.S3:
            return self._list_s3_files(path)
        else:
            return []
    
    def _list_local_files(self, path: str) -> List[Dict[str, Any]]:
        """List files in local directory"""
        files = []
        full_path = Path(self.config.local_path) / path
        
        if full_path.exists() and full_path.is_dir():
            for item in full_path.iterdir():
                if item.is_file():
                    files.append({
                        'name': item.name,
                        'path': str(item),
                        'size': item.stat().st_size,
                        'modified': datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                    })
        
        return files
    
    def _list_google_drive_files(self, folder_id: str = None) -> List[Dict[str, Any]]:
        """List files in Google Drive"""
        try:
            if not self._google_service:
                self._initialize_google_drive()
            
            if not self._google_service:
                return []
            
            query = "mimeType != 'application/vnd.google-apps.folder'"
            if folder_id:
                query += f" and '{folder_id}' in parents"
            
            results = self._google_service.files().list(
                q=query,
                fields="files(id, name, size, modifiedTime, webViewLink)"
            ).execute()
            
            files = []
            for item in results.get('files', []):
                files.append({
                    'name': item.get('name'),
                    'id': item.get('id'),
                    'size': int(item.get('size', 0)),
                    'modified': item.get('modifiedTime'),
                    'url': item.get('webViewLink')
                })
            
            return files
        except Exception as e:
            print(f"Failed to list Google Drive files: {e}")
            return []
    
    def _list_dropbox_files(self, path: str) -> List[Dict[str, Any]]:
        """List files in Dropbox"""
        try:
            if not self._dropbox_client:
                self._dropbox_client = dropbox.Dropbox(self.config.dropbox_token)
            
            full_path = f"{self.config.dropbox_folder}/{path}" if path else self.config.dropbox_folder
            
            result = self._dropbox_client.files_list_folder(full_path)
            
            files = []
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    files.append({
                        'name': entry.name,
                        'path': entry.path_display,
                        'size': entry.size,
                        'modified': entry.client_modified.isoformat()
                    })
            
            return files
        except Exception as e:
            print(f"Failed to list Dropbox files: {e}")
            return []
    
    def _list_s3_files(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List files in S3 bucket"""
        try:
            if not self._s3_client:
                self._s3_client = boto3.client(
                    's3',
                    region_name=self.config.s3_region,
                    aws_access_key_id=self.config.s3_access_key,
                    aws_secret_access_key=self.config.s3_secret_key
                )
            
            response = self._s3_client.list_objects_v2(
                Bucket=self.config.s3_bucket,
                Prefix=prefix
            )
            
            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'name': obj['Key'].split('/')[-1],
                    'path': obj['Key'],
                    'size': obj['Size'],
                    'modified': obj['LastModified'].isoformat()
                })
            
            return files
        except Exception as e:
            print(f"Failed to list S3 files: {e}")
            return []
