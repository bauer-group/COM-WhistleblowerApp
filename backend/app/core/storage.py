"""Hinweisgebersystem – MinIO Storage Client Wrapper.

Provides a thin wrapper around the ``minio`` Python client for
S3-compatible object storage.  All file encryption is performed
**before** upload using :mod:`app.core.encryption` — MinIO SSE is
not used.

Features:
- **Bucket management**: ensure the default bucket exists on startup.
- **File upload**: upload raw (pre-encrypted) bytes to a storage key.
- **File download**: download an object by key and return its bytes.
- **Presigned URLs**: generate time-limited download URLs.
- **Delete**: remove an object by key.

Usage::

    from app.core.storage import init_storage, get_storage

    # During application startup (lifespan):
    await init_storage()

    # In a service or route handler:
    client = get_storage()
    await client.upload("tenant-uuid/report-uuid/file.enc", encrypted_bytes)
    data = await client.download("tenant-uuid/report-uuid/file.enc")
    url = await client.presigned_url("tenant-uuid/report-uuid/file.enc")
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import partial
from io import BytesIO
from typing import TYPE_CHECKING

import structlog
from minio import Minio
from minio.error import S3Error

if TYPE_CHECKING:
    from app.core.config import Settings

logger = structlog.get_logger(__name__)


# ── Storage client singleton ──────────────────────────────────

_storage: StorageClient | None = None


class StorageClient:
    """Async-friendly wrapper around the synchronous ``minio.Minio`` client.

    The ``minio`` Python SDK is synchronous, so all I/O-bound operations
    are dispatched to a thread-pool executor via
    :func:`asyncio.get_running_loop().run_in_executor`.

    Parameters
    ----------
    client:
        Configured ``minio.Minio`` instance.
    default_bucket:
        Name of the default bucket for file attachments.
    """

    def __init__(self, client: Minio, default_bucket: str) -> None:
        self._client = client
        self._default_bucket = default_bucket

    @property
    def default_bucket(self) -> str:
        """Return the configured default bucket name."""
        return self._default_bucket

    # ── Bucket management ────────────────────────────────────

    async def ensure_bucket(self, bucket: str | None = None) -> None:
        """Create the bucket if it does not already exist.

        Parameters
        ----------
        bucket:
            Bucket name.  Defaults to :attr:`default_bucket`.
        """
        bucket = bucket or self._default_bucket
        loop = asyncio.get_running_loop()
        exists = await loop.run_in_executor(
            None,
            partial(self._client.bucket_exists, bucket),
        )
        if not exists:
            await loop.run_in_executor(
                None,
                partial(self._client.make_bucket, bucket),
            )
            logger.info("storage_bucket_created", bucket=bucket)
        else:
            logger.debug("storage_bucket_exists", bucket=bucket)

    # ── Upload ───────────────────────────────────────────────

    async def upload(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        bucket: str | None = None,
    ) -> None:
        """Upload bytes to an object storage key.

        Files should be encrypted **before** calling this method.
        MinIO SSE is not used.

        Parameters
        ----------
        key:
            Object key (path within the bucket), e.g.
            ``"<tenant_id>/<report_id>/<filename>.enc"``.
        data:
            Raw bytes to upload (typically AES-256-GCM encrypted).
        content_type:
            MIME type for the stored object.  Defaults to
            ``application/octet-stream`` for encrypted blobs.
        bucket:
            Target bucket.  Defaults to :attr:`default_bucket`.
        """
        bucket = bucket or self._default_bucket
        loop = asyncio.get_running_loop()
        stream = BytesIO(data)
        length = len(data)

        await loop.run_in_executor(
            None,
            partial(
                self._client.put_object,
                bucket,
                key,
                stream,
                length,
                content_type=content_type,
            ),
        )
        logger.info(
            "storage_object_uploaded",
            bucket=bucket,
            key=key,
            size_bytes=length,
        )

    # ── Download ─────────────────────────────────────────────

    async def download(
        self,
        key: str,
        *,
        bucket: str | None = None,
    ) -> bytes:
        """Download an object and return its raw bytes.

        Parameters
        ----------
        key:
            Object key within the bucket.
        bucket:
            Source bucket.  Defaults to :attr:`default_bucket`.

        Returns
        -------
        bytes
            The object's raw content.

        Raises
        ------
        S3Error
            If the object does not exist or cannot be retrieved.
        """
        bucket = bucket or self._default_bucket
        loop = asyncio.get_running_loop()

        response = await loop.run_in_executor(
            None,
            partial(self._client.get_object, bucket, key),
        )
        try:
            data = await loop.run_in_executor(None, response.read)
        finally:
            response.close()
            response.release_conn()

        logger.debug(
            "storage_object_downloaded",
            bucket=bucket,
            key=key,
            size_bytes=len(data),
        )
        return data

    # ── Presigned URL ────────────────────────────────────────

    async def presigned_url(
        self,
        key: str,
        *,
        bucket: str | None = None,
        expires: timedelta | None = None,
    ) -> str:
        """Generate a presigned download URL for an object.

        Parameters
        ----------
        key:
            Object key within the bucket.
        bucket:
            Source bucket.  Defaults to :attr:`default_bucket`.
        expires:
            URL validity duration.  Defaults to 1 hour.

        Returns
        -------
        str
            Presigned HTTP(S) URL.
        """
        bucket = bucket or self._default_bucket
        if expires is None:
            expires = timedelta(hours=1)

        loop = asyncio.get_running_loop()
        url: str = await loop.run_in_executor(
            None,
            partial(
                self._client.presigned_get_object,
                bucket,
                key,
                expires=expires,
            ),
        )
        logger.debug(
            "storage_presigned_url_generated",
            bucket=bucket,
            key=key,
            expires_seconds=int(expires.total_seconds()),
        )
        return url

    # ── Delete ───────────────────────────────────────────────

    async def delete(
        self,
        key: str,
        *,
        bucket: str | None = None,
    ) -> None:
        """Delete an object from storage.

        Parameters
        ----------
        key:
            Object key within the bucket.
        bucket:
            Target bucket.  Defaults to :attr:`default_bucket`.
        """
        bucket = bucket or self._default_bucket
        loop = asyncio.get_running_loop()

        await loop.run_in_executor(
            None,
            partial(self._client.remove_object, bucket, key),
        )
        logger.info("storage_object_deleted", bucket=bucket, key=key)

    # ── Object existence check ───────────────────────────────

    async def exists(
        self,
        key: str,
        *,
        bucket: str | None = None,
    ) -> bool:
        """Check whether an object exists in storage.

        Parameters
        ----------
        key:
            Object key within the bucket.
        bucket:
            Target bucket.  Defaults to :attr:`default_bucket`.

        Returns
        -------
        bool
            ``True`` if the object exists, ``False`` otherwise.
        """
        bucket = bucket or self._default_bucket
        loop = asyncio.get_running_loop()

        try:
            await loop.run_in_executor(
                None,
                partial(self._client.stat_object, bucket, key),
            )
            return True
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return False
            raise


# ── Initialisation / accessors ──────────────────────────────


def _create_minio_client(settings: Settings) -> Minio:
    """Create a ``minio.Minio`` client from application settings.

    Parameters
    ----------
    settings:
        Application settings containing S3/MinIO configuration.

    Returns
    -------
    Minio
        Configured MinIO client instance.
    """
    return Minio(
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_secure,
    )


async def init_storage(settings: Settings | None = None) -> StorageClient:
    """Initialise the storage client singleton and ensure the default bucket.

    Called once during application startup (lifespan).

    Parameters
    ----------
    settings:
        Application settings.  If ``None``, loaded via
        :func:`app.core.config.get_settings`.

    Returns
    -------
    StorageClient
        The initialised storage client.
    """
    global _storage  # noqa: PLW0603

    if settings is None:
        from app.core.config import get_settings  # noqa: PLC0415

        settings = get_settings()

    client = _create_minio_client(settings)
    _storage = StorageClient(client, default_bucket=settings.s3_bucket)
    await _storage.ensure_bucket()

    logger.info(
        "storage_client_initialised",
        endpoint=settings.s3_endpoint,
        bucket=settings.s3_bucket,
        secure=settings.s3_secure,
    )
    return _storage


def get_storage() -> StorageClient:
    """Return the initialised storage client singleton.

    Raises
    ------
    RuntimeError
        If :func:`init_storage` has not been called yet.
    """
    if _storage is None:
        raise RuntimeError(
            "Storage client not initialised. Call init_storage() first."
        )
    return _storage


async def dispose_storage() -> None:
    """Reset the storage client singleton.

    Called during application shutdown.  The ``minio`` client does not
    maintain persistent connections, so this simply clears the reference.
    """
    global _storage  # noqa: PLW0603

    _storage = None
    logger.info("storage_client_disposed")
