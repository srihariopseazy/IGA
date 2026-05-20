import io
import logging
from datetime import timedelta
from typing import Optional, List

from minio import Minio
from minio.error import S3Error
from backend.config import settings

logger = logging.getLogger(__name__)


class MinIOClient:
    """Wrapper around the MinIO SDK providing async-compatible helpers."""

    def __init__(self) -> None:
        self._client: Optional[Minio] = None

    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
        return self._client

    def _ensure_bucket(self, bucket: str) -> None:
        client = self._get_client()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

    async def upload_file(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes to MinIO. Returns the object name on success."""
        try:
            self._ensure_bucket(bucket)
            client = self._get_client()
            stream = io.BytesIO(data)
            client.put_object(
                bucket_name=bucket,
                object_name=object_name,
                data=stream,
                length=len(data),
                content_type=content_type,
            )
            logger.info("Uploaded %s/%s (%d bytes)", bucket, object_name, len(data))
            return object_name
        except S3Error as exc:
            logger.error("MinIO upload error %s/%s: %s", bucket, object_name, exc)
            raise

    async def download_file(self, bucket: str, object_name: str) -> bytes:
        """Download an object from MinIO and return its bytes."""
        try:
            client = self._get_client()
            response = client.get_object(bucket_name=bucket, object_name=object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as exc:
            logger.error("MinIO download error %s/%s: %s", bucket, object_name, exc)
            raise

    async def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires: timedelta = timedelta(hours=1),
    ) -> str:
        """Generate a presigned GET URL for the object."""
        try:
            client = self._get_client()
            url = client.presigned_get_object(
                bucket_name=bucket,
                object_name=object_name,
                expires=expires,
            )
            return url
        except S3Error as exc:
            logger.error("MinIO presign error %s/%s: %s", bucket, object_name, exc)
            raise

    async def delete_file(self, bucket: str, object_name: str) -> bool:
        """Delete an object from MinIO."""
        try:
            client = self._get_client()
            client.remove_object(bucket_name=bucket, object_name=object_name)
            logger.info("Deleted %s/%s", bucket, object_name)
            return True
        except S3Error as exc:
            logger.error("MinIO delete error %s/%s: %s", bucket, object_name, exc)
            return False

    async def list_files(self, bucket: str, prefix: str = "") -> List[str]:
        """List object names in a bucket with optional prefix."""
        try:
            client = self._get_client()
            objects = client.list_objects(bucket_name=bucket, prefix=prefix, recursive=True)
            return [obj.object_name for obj in objects]
        except S3Error as exc:
            logger.error("MinIO list error %s/%s: %s", bucket, prefix, exc)
            return []

    async def upload_audit_evidence(
        self,
        tenant_id: str,
        campaign_id: str,
        data: bytes,
        filename: str,
    ) -> str:
        """Upload certification audit evidence. Returns the full object path."""
        bucket = settings.MINIO_BUCKET
        object_name = f"tenants/{tenant_id}/campaigns/{campaign_id}/evidence/{filename}"
        return await self.upload_file(bucket, object_name, data, content_type="application/octet-stream")

    async def upload_compliance_report(
        self,
        tenant_id: str,
        report_type: str,
        data: bytes,
    ) -> str:
        """Upload a compliance report PDF/CSV. Returns the full object path."""
        import datetime
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        bucket = settings.MINIO_BUCKET
        object_name = f"tenants/{tenant_id}/compliance/{report_type}_{timestamp}.pdf"
        return await self.upload_file(bucket, object_name, data, content_type="application/pdf")

    async def upload_avatar(
        self,
        user_id: str,
        image_data: bytes,
        content_type: str,
    ) -> str:
        """Upload a user avatar image. Returns the full object path."""
        ext = "jpg" if "jpeg" in content_type else content_type.split("/")[-1]
        bucket = settings.MINIO_BUCKET
        object_name = f"avatars/{user_id}/avatar.{ext}"
        return await self.upload_file(bucket, object_name, image_data, content_type=content_type)


minio_client = MinIOClient()
