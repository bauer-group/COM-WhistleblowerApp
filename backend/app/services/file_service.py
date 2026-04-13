"""Hinweisgebersystem -- File Upload / Download Business Service.

Orchestrates secure file attachment operations including:
- **Upload**: AES-256-GCM encryption before MinIO upload with per-file
  key generation, SHA-256 integrity hash, and envelope encryption of
  the file key via the tenant DEK.
- **Download**: MinIO download with decryption and SHA-256 integrity
  verification before returning the plaintext.
- **Validation**: 50 MB max file size, 10 files max per message,
  content-type allow-listing.
- **Metadata**: stores the MinIO object key, encrypted file key,
  content type, original filename, and SHA-256 hash in the
  ``attachments`` table.

The service delegates storage I/O to :mod:`app.core.storage` and
cryptographic operations to :mod:`app.core.encryption`.  All actions
are logged to the immutable audit trail.

Usage::

    from app.services.file_service import FileService

    service = FileService(session, tenant_id, encryption_master_key)
    attachment = await service.upload_file(
        report_id=report_id,
        filename="evidence.pdf",
        content_type="application/pdf",
        data=file_bytes,
        tenant_dek_ciphertext=tenant.dek_ciphertext,
    )
    plaintext = await service.download_file(attachment_id)
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import (
    compute_sha256,
    decrypt_dek,
    decrypt_file,
    encrypt_dek,
    encrypt_file,
    generate_file_key,
    verify_sha256,
)
from app.core.storage import get_storage
from app.models.attachment import Attachment
from app.models.audit_log import AuditAction
from app.repositories.audit_repo import AuditRepository

logger = structlog.get_logger(__name__)

# ── Limits ───────────────────────────────────────────────────
# Per spec: 50 MB max file size, 10 files max per message.

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_FILES_PER_MESSAGE = 10


class FileService:
    """Business logic for file attachments with client-side encryption.

    All files are encrypted with AES-256-GCM *before* upload to MinIO.
    Each file gets a unique 256-bit key that is itself encrypted via
    envelope encryption using the tenant's Data Encryption Key (DEK).

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    tenant_id:
        UUID of the current tenant (from middleware).
    encryption_master_key:
        Hex-encoded 256-bit master key for envelope encryption
        (from application settings).
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        encryption_master_key: str,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._master_key = encryption_master_key
        self._audit_repo = AuditRepository(session)

    # ── Upload ───────────────────────────────────────────────────

    async def upload_file(
        self,
        *,
        report_id: uuid.UUID,
        filename: str,
        content_type: str,
        data: bytes,
        tenant_dek_ciphertext: bytes,
        message_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "reporter",
    ) -> Attachment:
        """Encrypt and upload a file attachment to MinIO.

        The upload pipeline is:
        1. Validate file size against ``MAX_FILE_SIZE_BYTES``.
        2. Compute SHA-256 hash of the plaintext for integrity.
        3. Generate a per-file AES-256-GCM key.
        4. Encrypt the file with the per-file key.
        5. Encrypt the per-file key with the tenant DEK (envelope
           encryption).
        6. Upload the encrypted blob to MinIO.
        7. Persist attachment metadata to the database.
        8. Log the upload to the audit trail.

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        filename:
            Original filename (user-provided, for download).
        content_type:
            MIME type of the original file.
        data:
            Raw plaintext file contents.
        tenant_dek_ciphertext:
            Envelope-encrypted tenant DEK (from ``tenant.dek_ciphertext``).
        message_id:
            Optional UUID of the parent message.  ``None`` for
            attachments uploaded with the initial report submission.
        actor_id:
            UUID of the acting user (``None`` for anonymous reporters).
        actor_type:
            ``"reporter"`` or ``"user"``.

        Returns
        -------
        Attachment
            The persisted attachment metadata.

        Raises
        ------
        ValueError
            If the file exceeds the maximum allowed size.
        """
        # ── 1. Validate file size ────────────────────────────────
        file_size = len(data)
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File size ({file_size:,} bytes) exceeds the maximum "
                f"allowed size ({MAX_FILE_SIZE_BYTES:,} bytes / "
                f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB)."
            )

        # ── 2. Compute SHA-256 hash of plaintext ────────────────
        sha256_hash = compute_sha256(data)

        # ── 3. Generate per-file AES-256-GCM key ────────────────
        file_key = generate_file_key()

        # ── 4. Encrypt file data ─────────────────────────────────
        encrypted_data = encrypt_file(data, file_key)

        # ── 5. Envelope-encrypt the per-file key ────────────────
        # Decrypt the tenant DEK from envelope, then use it to
        # encrypt the per-file key.
        tenant_dek = decrypt_dek(tenant_dek_ciphertext, self._master_key)
        encrypted_file_key = encrypt_dek(file_key, tenant_dek.hex())
        # Store as hex string for database persistence
        encrypted_file_key_hex = encrypted_file_key.hex()

        # ── 6. Upload encrypted blob to MinIO ────────────────────
        storage_key = (
            f"{self._tenant_id}/{report_id}/{uuid.uuid4().hex}_{filename}.enc"
        )
        storage = get_storage()
        await storage.upload(storage_key, encrypted_data)

        # ── 7. Persist attachment metadata ───────────────────────
        attachment = Attachment(
            report_id=report_id,
            message_id=message_id,
            tenant_id=self._tenant_id,
            storage_key=storage_key,
            original_filename=filename,
            content_type=content_type,
            file_size=file_size,
            encryption_key_ciphertext=encrypted_file_key_hex,
            sha256_hash=sha256_hash,
        )
        self._session.add(attachment)
        await self._session.flush()
        await self._session.refresh(attachment)

        # ── 8. Audit log ─────────────────────────────────────────
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.ATTACHMENT_UPLOADED,
            resource_type="attachment",
            resource_id=str(attachment.id),
            actor_id=actor_id,
            actor_type=actor_type,
            details={
                "report_id": str(report_id),
                "message_id": str(message_id) if message_id else None,
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
                "sha256_hash": sha256_hash,
            },
        )

        logger.info(
            "file_uploaded",
            attachment_id=str(attachment.id),
            report_id=str(report_id),
            filename=filename,
            file_size=file_size,
        )

        return attachment

    # ── Download ─────────────────────────────────────────────────

    async def download_file(
        self,
        attachment_id: uuid.UUID,
        *,
        tenant_dek_ciphertext: bytes,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "reporter",
    ) -> tuple[bytes, Attachment]:
        """Download and decrypt a file attachment from MinIO.

        The download pipeline is:
        1. Fetch attachment metadata from the database.
        2. Download the encrypted blob from MinIO.
        3. Decrypt the per-file key via envelope encryption.
        4. Decrypt the file data.
        5. Verify SHA-256 integrity of the decrypted plaintext.
        6. Log the download to the audit trail.

        Parameters
        ----------
        attachment_id:
            UUID of the attachment to download.
        tenant_dek_ciphertext:
            Envelope-encrypted tenant DEK (from ``tenant.dek_ciphertext``).
        actor_id:
            UUID of the acting user (``None`` for anonymous reporters).
        actor_type:
            ``"reporter"`` or ``"user"``.

        Returns
        -------
        tuple[bytes, Attachment]
            ``(plaintext_data, attachment_metadata)``.

        Raises
        ------
        ValueError
            If the attachment is not found or integrity verification
            fails.
        """
        # ── 1. Fetch attachment metadata ─────────────────────────
        from sqlalchemy import select  # noqa: PLC0415

        stmt = select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        attachment = result.scalar_one_or_none()

        if attachment is None:
            raise ValueError(
                f"Attachment {attachment_id!r} not found or does not "
                f"belong to the current tenant."
            )

        # ── 2. Download encrypted blob from MinIO ────────────────
        storage = get_storage()
        encrypted_data = await storage.download(attachment.storage_key)

        # ── 3. Decrypt per-file key via envelope encryption ──────
        tenant_dek = decrypt_dek(tenant_dek_ciphertext, self._master_key)
        encrypted_file_key = bytes.fromhex(attachment.encryption_key_ciphertext)
        file_key = decrypt_file(encrypted_file_key, tenant_dek)

        # ── 4. Decrypt file data ─────────────────────────────────
        plaintext = decrypt_file(encrypted_data, file_key)

        # ── 5. Verify SHA-256 integrity ──────────────────────────
        verify_sha256(plaintext, attachment.sha256_hash)

        # ── 6. Audit log ─────────────────────────────────────────
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.ATTACHMENT_DOWNLOADED,
            resource_type="attachment",
            resource_id=str(attachment.id),
            actor_id=actor_id,
            actor_type=actor_type,
            details={
                "report_id": str(attachment.report_id),
                "filename": attachment.original_filename,
            },
        )

        logger.info(
            "file_downloaded",
            attachment_id=str(attachment.id),
            report_id=str(attachment.report_id),
            filename=attachment.original_filename,
        )

        return plaintext, attachment

    # ── Delete ───────────────────────────────────────────────────

    async def delete_file(
        self,
        attachment_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "system",
    ) -> bool:
        """Delete a file attachment from both MinIO and the database.

        Used during data retention cleanup.  Removes the encrypted blob
        from MinIO and the metadata row from the database.

        Parameters
        ----------
        attachment_id:
            UUID of the attachment to delete.
        actor_id:
            UUID of the acting user (``None`` for system tasks).
        actor_type:
            ``"user"`` or ``"system"``.

        Returns
        -------
        bool
            ``True`` if the attachment was deleted, ``False`` if not found.
        """
        from sqlalchemy import select  # noqa: PLC0415

        stmt = select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        attachment = result.scalar_one_or_none()

        if attachment is None:
            return False

        # Remove from MinIO
        storage = get_storage()
        try:
            await storage.delete(attachment.storage_key)
        except Exception:
            logger.warning(
                "file_delete_storage_error",
                attachment_id=str(attachment_id),
                storage_key=attachment.storage_key,
                exc_info=True,
            )

        # Remove from database
        await self._session.delete(attachment)
        await self._session.flush()

        logger.info(
            "file_deleted",
            attachment_id=str(attachment_id),
            report_id=str(attachment.report_id),
            filename=attachment.original_filename,
        )

        return True

    # ── Listing ──────────────────────────────────────────────────

    async def list_attachments_for_report(
        self,
        report_id: uuid.UUID,
    ) -> list[Attachment]:
        """List all attachments for a report.

        Parameters
        ----------
        report_id:
            UUID of the parent report.

        Returns
        -------
        list[Attachment]
            All attachment metadata for the report.
        """
        from sqlalchemy import select  # noqa: PLC0415

        stmt = (
            select(Attachment)
            .where(
                Attachment.report_id == report_id,
                Attachment.tenant_id == self._tenant_id,
            )
            .order_by(Attachment.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_attachments_for_message(
        self,
        message_id: uuid.UUID,
    ) -> list[Attachment]:
        """List all attachments for a specific message.

        Parameters
        ----------
        message_id:
            UUID of the parent message.

        Returns
        -------
        list[Attachment]
            All attachment metadata for the message.
        """
        from sqlalchemy import select  # noqa: PLC0415

        stmt = (
            select(Attachment)
            .where(
                Attachment.message_id == message_id,
                Attachment.tenant_id == self._tenant_id,
            )
            .order_by(Attachment.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_attachments_for_message(
        self,
        message_id: uuid.UUID,
    ) -> int:
        """Count attachments for a specific message.

        Used to enforce the ``MAX_FILES_PER_MESSAGE`` limit.

        Parameters
        ----------
        message_id:
            UUID of the parent message.

        Returns
        -------
        int
            Number of attachments linked to the message.
        """
        from sqlalchemy import func, select  # noqa: PLC0415

        stmt = select(func.count()).select_from(Attachment).where(
            Attachment.message_id == message_id,
            Attachment.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    # ── Validation helpers ───────────────────────────────────────

    async def validate_upload(
        self,
        *,
        file_size: int,
        message_id: uuid.UUID | None = None,
    ) -> None:
        """Validate file upload constraints before processing.

        Checks:
        - File size does not exceed ``MAX_FILE_SIZE_BYTES``.
        - If a ``message_id`` is provided, the current attachment count
          does not exceed ``MAX_FILES_PER_MESSAGE``.

        Parameters
        ----------
        file_size:
            Size of the file to upload in bytes.
        message_id:
            Optional UUID of the message.  If provided, the per-message
            file count limit is enforced.

        Raises
        ------
        ValueError
            If any validation constraint is violated.
        """
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File size ({file_size:,} bytes) exceeds the maximum "
                f"allowed size ({MAX_FILE_SIZE_BYTES:,} bytes / "
                f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB)."
            )

        if file_size == 0:
            raise ValueError("File is empty (0 bytes).")

        if message_id is not None:
            current_count = await self.count_attachments_for_message(message_id)
            if current_count >= MAX_FILES_PER_MESSAGE:
                raise ValueError(
                    f"Maximum number of files per message "
                    f"({MAX_FILES_PER_MESSAGE}) has been reached."
                )
