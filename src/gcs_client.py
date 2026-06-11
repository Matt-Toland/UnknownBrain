"""
Google Cloud Storage client for UNKNOWN Brain
Handles file operations in Cloud Storage for Cloud Run deployment
"""

import json
import os
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
import tempfile
from datetime import datetime

from google.cloud import storage
from google.cloud.exceptions import NotFound

logger = logging.getLogger(__name__)

class GCSClient:
    """Client for Google Cloud Storage operations"""
    
    def __init__(self, bucket_name: Optional[str] = None):
        """
        Initialize GCS client
        
        Args:
            bucket_name: Cloud Storage bucket name (defaults to env var)
        """
        self.client = storage.Client()
        self.bucket_name = bucket_name or os.getenv('GCS_BUCKET_NAME', 'unknown-brain-transcripts')
        self.bucket = self.client.bucket(self.bucket_name)
    
    def list_transcripts(self, prefix: str = "transcripts/", max_files: int = 100) -> List[storage.Blob]:
        """
        List transcript files in Cloud Storage
        
        Args:
            prefix: Directory prefix to search in
            max_files: Maximum number of files to return
            
        Returns:
            List of blob objects
        """
        try:
            blobs = self.client.list_blobs(
                self.bucket_name, 
                prefix=prefix,
                max_results=max_files
            )
            return [blob for blob in blobs if self._is_transcript_file(blob.name)]
        except Exception as e:
            print(f"Error listing transcripts: {e}")
            return []
    
    def download_transcript(self, blob_name: str) -> str:
        """
        Download a transcript file from Cloud Storage
        
        Args:
            blob_name: Name of the blob to download
            
        Returns:
            Content of the file as string
        """
        try:
            blob = self.bucket.blob(blob_name)
            if not blob.exists():
                raise FileNotFoundError(f"File not found: {blob_name}")
            
            content = blob.download_as_text(encoding='utf-8')
            return content
        except Exception as e:
            print(f"Error downloading transcript {blob_name}: {e}")
            raise
    
    def download_to_temp_file(self, blob_name: str) -> Path:
        """
        Download a file to a temporary local file
        
        Args:
            blob_name: Name of the blob to download
            
        Returns:
            Path to temporary file
        """
        try:
            blob = self.bucket.blob(blob_name)
            
            # Create temporary file with same extension
            suffix = Path(blob_name).suffix
            with tempfile.NamedTemporaryFile(mode='w+b', suffix=suffix, delete=False) as f:
                blob.download_to_file(f)
                temp_path = Path(f.name)
            
            return temp_path
        except Exception as e:
            logger.error(f"Error downloading to temp file {blob_name}: {e}", exc_info=True)
            raise
    
    def upload_results(self, results: Dict[Any, Any], path: str) -> str:
        """
        Upload results to Cloud Storage
        
        Args:
            results: Dictionary to upload as JSON
            path: Destination path in Cloud Storage
            
        Returns:
            Public URL of uploaded file
        """
        try:
            blob = self.bucket.blob(path)
            
            # Upload as JSON
            blob.upload_from_string(
                json.dumps(results, indent=2, default=str),
                content_type='application/json'
            )
            
            return f"gs://{self.bucket_name}/{path}"
        except Exception as e:
            print(f"Error uploading results to {path}: {e}")
            raise
    
    def upload_file(self, local_path: Path, destination_path: str) -> str:
        """
        Upload a local file to Cloud Storage
        
        Args:
            local_path: Path to local file
            destination_path: Destination path in Cloud Storage
            
        Returns:
            Public URL of uploaded file
        """
        try:
            blob = self.bucket.blob(destination_path)
            
            # Detect content type
            content_type = self._get_content_type(local_path)
            
            blob.upload_from_filename(str(local_path), content_type=content_type)
            return f"gs://{self.bucket_name}/{destination_path}"
        except Exception as e:
            print(f"Error uploading file {local_path} to {destination_path}: {e}")
            raise
    
    def file_exists(self, blob_name: str) -> bool:
        """
        Check if a file exists in Cloud Storage
        
        Args:
            blob_name: Name of the blob to check
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            blob = self.bucket.blob(blob_name)
            return blob.exists()
        except Exception as e:
            print(f"Error checking if file exists {blob_name}: {e}")
            return False
    
    def get_file_metadata(self, blob_name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a file in Cloud Storage
        
        Args:
            blob_name: Name of the blob
            
        Returns:
            Dictionary with file metadata or None if not found
        """
        try:
            blob = self.bucket.blob(blob_name)
            blob.reload()
            
            return {
                'name': blob.name,
                'size': blob.size,
                'created': blob.time_created.isoformat() if blob.time_created else None,
                'updated': blob.updated.isoformat() if blob.updated else None,
                'content_type': blob.content_type,
                'etag': blob.etag,
                'md5_hash': blob.md5_hash
            }
        except NotFound:
            return None
        except Exception as e:
            print(f"Error getting metadata for {blob_name}: {e}")
            return None
    
    def create_cache_key(
        self, meeting_id: str, model: str, source: str, variant: Optional[str] = None
    ) -> str:
        """
        Create a cache key for scored results.

        `source` is part of the key so that cache lookups for the same
        meeting_id+model but different scorer domains (client vs talent)
        don't collide. Without this, a client-scored result would be
        silently returned for a talent re-run, bypassing the router.

        `variant` is an optional extra key component for scoring behaviour that
        changes the OUTPUT but isn't captured by source/model — e.g. the talent
        Article 9 mode (flag vs redact). Including it means flipping the mode is
        a cache MISS, forcing a clean re-score rather than serving a stale row.
        Client cache keys pass variant=None, so their paths are unchanged.
        """
        today = datetime.now().strftime('%Y-%m-%d')
        suffix = f"-{variant}" if variant else ""
        return f"cache/{today}/{meeting_id}-{model}-{source}{suffix}.json"

    def get_cached_score(
        self, meeting_id: str, model: str, source: str, variant: Optional[str] = None
    ) -> Optional[Dict[Any, Any]]:
        """
        Get cached score results for the given meeting/model/source(/variant) key.
        """
        cache_key = self.create_cache_key(meeting_id, model, source, variant)

        try:
            if self.file_exists(cache_key):
                content = self.download_transcript(cache_key)
                return json.loads(content)
            return None
        except Exception as e:
            print(f"Error getting cached score: {e}")
            return None

    def cache_score(
        self, meeting_id: str, model: str, source: str, results: Dict[Any, Any],
        variant: Optional[str] = None,
    ) -> str:
        """
        Cache score results under the meeting/model/source(/variant) key.
        """
        cache_key = self.create_cache_key(meeting_id, model, source, variant)

        # Add caching metadata
        cache_data = {
            'meeting_id': meeting_id,
            'model': model,
            'source': source,
            'cached_at': datetime.now().isoformat(),
            'results': results
        }

        return self.upload_results(cache_data, cache_key)

    def _claim_key(self, meeting_id: str, model: str, source: str) -> str:
        """Date-scoped claim marker path (mirrors the cache key)."""
        today = datetime.now().strftime('%Y-%m-%d')
        return f"claims/{today}/{meeting_id}-{model}-{source}.claim"

    def claim_meeting(self, meeting_id: str, model: str, source: str) -> bool:
        """
        Atomically claim a meeting for processing.

        Returns True if THIS caller won the claim (should process), False if it
        was already claimed (another concurrent delivery is handling it — skip).

        Uses GCS create-if-not-exists (`if_generation_match=0`), which is atomic
        and cross-instance, so two CloudEvent deliveries for the same meeting
        arriving within the MERGE window can't both proceed and double-insert.
        The claim is date-scoped (auto-expires daily) like the result cache.

        Fails OPEN: if the claim mechanism itself errors, return True (proceed)
        rather than block scoring — the dedupe pass is the backstop.
        """
        from google.api_core.exceptions import PreconditionFailed
        key = self._claim_key(meeting_id, model, source)
        try:
            blob = self.bucket.blob(key)
            blob.upload_from_string(
                json.dumps({'meeting_id': meeting_id, 'claimed_at': datetime.now().isoformat()}),
                content_type='application/json',
                if_generation_match=0,  # create-only: raises PreconditionFailed if it already exists
            )
            return True
        except PreconditionFailed:
            return False
        except Exception as e:
            print(f"claim_meeting error for {meeting_id} (failing open, proceeding): {e}")
            return True

    def release_claim(self, meeting_id: str, model: str, source: str) -> None:
        """
        Release a claim so the meeting can be retried. Called on processing
        FAILURE (a successful run leaves the claim + result cache in place so
        same-day re-deliveries short-circuit). Non-fatal on error.
        """
        key = self._claim_key(meeting_id, model, source)
        try:
            self.bucket.blob(key).delete()
        except Exception as e:
            print(f"release_claim error for {meeting_id} (non-fatal): {e}")
    
    def cleanup_temp_files(self, temp_paths: List[Path]):
        """
        Clean up temporary files
        
        Args:
            temp_paths: List of temporary file paths to delete
        """
        for path in temp_paths:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                print(f"Warning: Could not delete temp file {path}: {e}")
    
    def _is_transcript_file(self, filename: str) -> bool:
        """Check if file is a transcript based on extension"""
        return filename.lower().endswith(('.md', '.txt'))
    
    def _get_content_type(self, file_path: Path) -> str:
        """Get content type based on file extension"""
        extension = file_path.suffix.lower()
        content_types = {
            '.json': 'application/json',
            '.csv': 'text/csv',
            '.md': 'text/markdown',
            '.txt': 'text/plain',
            '.jsonl': 'application/x-jsonlines'
        }
        return content_types.get(extension, 'text/plain')

# Convenience function for getting GCS client
def get_gcs_client() -> GCSClient:
    """Get a configured GCS client instance"""
    return GCSClient()