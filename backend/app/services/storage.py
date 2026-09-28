import io
import os
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings
from app.core.logging import logger


class StorageService:
    """S3, MinIO and SeaweedFS compatible object storage service with local persistent fallback."""

    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        self.endpoint_url = settings.S3_ENDPOINT_URL
        self.local_storage_dir = os.environ.get(
            "STORAGE_DATA_DIR",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage_data")),
        )
        try:
            os.makedirs(self.local_storage_dir, exist_ok=True)
        except Exception:
            self.local_storage_dir = "/tmp/docintel_storage"
            os.makedirs(self.local_storage_dir, exist_ok=True)
        try:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION,
                config=Config(signature_version="s3v4"),
            )
            self._ensure_bucket_exists()
        except Exception as e:
            logger.warning(f"S3 client initialization notice: {e}")
            self._client = None

    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it does not already exist."""
        if not self._client:
            return
        try:
            self._client.head_bucket(Bucket=self.bucket_name)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self.bucket_name)
                logger.info(f"Created S3 bucket '{self.bucket_name}'")
            except Exception as e:
                logger.warning(f"Could not verify/create bucket '{self.bucket_name}': {e}")
        except Exception as e:
            logger.warning(f"Storage connection notice: {e}")

    def upload_file(self, file_obj: BinaryIO, s3_key: str, content_type: str) -> str:
        """Upload a file-like object to S3/SeaweedFS with local fallback."""
        if self._client:
            try:
                file_obj.seek(0)
                self._client.upload_fileobj(
                    file_obj,
                    self.bucket_name,
                    s3_key,
                    ExtraArgs={"ContentType": content_type},
                )
                return s3_key
            except Exception as e:
                logger.warning(f"S3 upload notice ({e}); writing to persistent local storage.")

        # Local fallback
        local_path = os.path.join(self.local_storage_dir, s3_key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        file_obj.seek(0)
        with open(local_path, "wb") as f:
            f.write(file_obj.read())
        return s3_key

    def download_file(self, s3_key: str) -> bytes:
        """Download raw object bytes from S3/SeaweedFS or local fallback."""
        if self._client:
            try:
                buf = io.BytesIO()
                self._client.download_fileobj(self.bucket_name, s3_key, buf)
                buf.seek(0)
                return buf.read()
            except Exception as e:
                logger.warning(f"S3 download notice ({e}); attempting local storage read.")

        local_path = os.path.join(self.local_storage_dir, s3_key)
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                return f.read()

        raise FileNotFoundError(f"Object '{s3_key}' not found in S3 or local storage.")

    def delete_file(self, s3_key: str) -> None:
        """Delete an object from S3 or local storage."""
        if self._client:
            try:
                self._client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            except Exception as e:
                logger.warning(f"Failed to delete S3 object '{s3_key}': {e}")
        local_path = os.path.join(self.local_storage_dir, s3_key)
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logger.warning(f"Failed to delete local object '{s3_key}': {e}")


storage_service = StorageService()
