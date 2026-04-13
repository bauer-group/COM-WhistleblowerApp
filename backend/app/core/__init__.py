"""Hinweisgebersystem – Core Package.

This package contains foundational modules shared across the application:
- config    – Pydantic Settings for all environment variables
- database  – Async SQLAlchemy engine, session factory, RLS tenant context
- security  – JWT validation, password hashing, OIDC helpers
- oidc      – OIDC client for Microsoft Entra ID
- smtp      – Async SMTP service
- encryption – AES-256-GCM file encryption, envelope encryption
- storage   – MinIO client wrapper
- passphrase – BIP-39 inspired passphrase generation
"""
