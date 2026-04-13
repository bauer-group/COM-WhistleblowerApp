"""Hinweisgebersystem -- Business Service Layer.

Service classes encapsulate business logic and orchestrate
interactions between repositories, core modules, and external
integrations.  Services are the primary entry point for API route
handlers -- they accept validated Pydantic schemas and return
domain-level results.

Each service receives the RLS-scoped async session (from the
``get_db()`` dependency) and instantiates the necessary repositories
internally, keeping the API layer thin and testable.

Available services:

- **ReportService**: case lifecycle (create, status workflow, assign,
  authenticate mailbox, KPI statistics).
- **MessageService**: bidirectional mailbox communication (reporter,
  handler, system messages, read tracking).
- **UserService**: OIDC provisioning, RBAC role management,
  activation/deactivation, custodian toggle.
- **TenantService**: multi-tenant CRUD, branding, SMTP config,
  language settings, retention periods, category management.
- **FileService**: file upload with AES-256-GCM encryption before
  MinIO upload, per-file key generation, SHA-256 integrity, download
  with decryption and verification.
- **NotificationService**: email orchestration for all notification
  types with per-tenant SMTP config and language-specific templates.
- **CustodianService**: 4-eyes identity disclosure workflow
  (handler request -> custodian approve -> identity reveal).
"""
