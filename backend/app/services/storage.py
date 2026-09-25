import io
from typing import BinaryIO
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings
from app.core.logging import logger


class StorageService:
    """S3 and MinIO compatible object storage service."""

    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        self.endpoint_url = settings.S3_ENDPOINT_URL
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4"),
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it does not already exist."""
        try:
            self._client.head_bucket(Bucket=self.bucket_name)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self.bucket_name)
                logger.info(f"Created S3/MinIO bucket '{self.bucket_name}'")
            except Exception as e:
                logger.warning(f"Could not verify/create bucket '{self.bucket_name}': {e}")
        except Exception as e:
            logger.warning(f"Storage connection notice: {e}")

    def upload_file(self, file_obj: BinaryIO, s3_key: str, content_type: str) -> str:
        """Upload a file-like object to S3/MinIO."""
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
            logger.error(f"Failed to upload file to S3 at key '{s3_key}': {e}")
            raise

    def download_file(self, s3_key: str) -> bytes:
        """Download raw object bytes from S3/MinIO."""
        try:
            buf = io.BytesIO()
            self._client.download_fileobj(self.bucket_name, s3_key, buf)
            buf.seek(0)
            return buf.read()
        except Exception as e:
            logger.error(f"Failed to download object '{s3_key}' from S3: {e}")
            raise

    def delete_file(self, s3_key: str) -> None:
        """Delete an object from S3/MinIO."""
        try:
            self._client.delete_object(Bucket=self.bucket_name, Key=s3_key)
        except Exception as e:
            logger.warning(f"Failed to delete S3 object '{s3_key}': {e}")


storage_service = StorageService()
