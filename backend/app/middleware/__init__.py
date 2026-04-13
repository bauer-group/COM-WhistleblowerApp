"""Hinweisgebersystem -- Middleware Package.

Contains ASGI middleware for:

- **Tenant resolution** (``tenant_resolver``): Extracts the current
  tenant from subdomain, path prefix, or header and stores the tenant
  UUID in request state for downstream RLS enforcement.
- **Anonymity protection** (``anonymity``): Strips identifying headers,
  rounds timestamps, pads response times, and prevents tracking for
  reporter-facing endpoints.
- **Audit logging** (``audit_logger``): Append-only audit trail for all
  state-changing requests with auto-detected actions and old/new values.
- **Rate limiting** (``rate_limiter``): Redis-based sliding-window rate
  limiting per endpoint with configurable limits and 429 responses.
"""
