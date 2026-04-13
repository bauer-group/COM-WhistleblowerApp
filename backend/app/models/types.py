"""Hinweisgebersystem – Custom SQLAlchemy Type Decorators.

Provides the ``PGPString`` TypeDecorator for transparent field-level
encryption via PostgreSQL's pgcrypto extension.

Pattern reference:
    Spec Pattern #2 – pgcrypto Field-Level Encryption

Usage::

    from app.models.types import PGPString

    class Report(Base):
        __tablename__ = "reports"

        subject_encrypted = mapped_column(
            PGPString("per_tenant_dek"),
            nullable=True,
        )
"""

from __future__ import annotations

from sqlalchemy import String, TypeDecorator, func, type_coerce
from sqlalchemy.dialects.postgresql import BYTEA


class PGPString(TypeDecorator):
    """Transparent pgcrypto symmetric encryption for text columns.

    Uses ``pgp_sym_encrypt`` on INSERT/UPDATE and ``pgp_sym_decrypt``
    on SELECT.  The underlying column type is BYTEA (pgcrypto stores
    encrypted data as binary).

    Parameters
    ----------
    passphrase : str
        The symmetric encryption key (per-tenant DEK).  At model
        definition time this may be a placeholder; the actual DEK is
        resolved at runtime by the encryption service layer.

    Notes
    -----
    - ``cache_ok = True`` is required for SQLAlchemy's query cache.
    - ``type_coerce(bindvalue, String)`` prevents Binary wrapper issues.
    """

    impl = BYTEA
    cache_ok = True

    def __init__(self, passphrase: str) -> None:
        super().__init__()
        self.passphrase = passphrase

    def bind_expression(self, bindvalue):  # type: ignore[override]
        """Encrypt the value on INSERT/UPDATE using pgp_sym_encrypt."""
        bindvalue = type_coerce(bindvalue, String)
        return func.pgp_sym_encrypt(bindvalue, self.passphrase)

    def column_expression(self, col):  # type: ignore[override]
        """Decrypt the value on SELECT using pgp_sym_decrypt."""
        return func.pgp_sym_decrypt(col, self.passphrase)
