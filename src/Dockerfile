# ═══════════════════════════════════════════════════════════
# Whistleblower-App (GlobaLeaks) - BAUER GROUP Edition
# ═══════════════════════════════════════════════════════════
# Abgeleitet vom Upstream-Image mit BAUER-GROUP-spezifischen Patches
# für Reverse-Proxy-Kompatibilität (siehe apply-patches.py).
#
# Upstream:  https://hub.docker.com/r/globaleaks/globaleaks
# Build:     docker compose -f docker-compose.<variant>.yml build
# ═══════════════════════════════════════════════════════════

ARG BASE_VERSION=latest
FROM globaleaks/globaleaks:${BASE_VERSION}

ARG BASE_VERSION

# BEHIND_PROXY steuert das Patch-Set:
#   true  (default, production) → X-Forwarded-Proto-Trust für Redirect + HSTS
#   false (development)         → HTTPS-Redirect hart aus, kein HSTS auf localhost
ARG BEHIND_PROXY=true

# ───────────────────────────────────────────────────────────
# Patches anwenden (idempotent, fail-fast bei Upstream-Changes)
# Root-User nötig für Zugriff auf /usr/lib/python3/dist-packages/
# ───────────────────────────────────────────────────────────
USER root
COPY apply-patches.py /tmp/apply-patches.py
RUN BEHIND_PROXY=${BEHIND_PROXY} python3 /tmp/apply-patches.py && rm /tmp/apply-patches.py
USER globaleaks

# ───────────────────────────────────────────────────────────
# Port-Deklaration: Nur HTTP (8080)
# GlobaLeaks bindet intern zwar noch 8443 mit self-signed, aber diese
# Variante ist durch den Patch nicht mehr nötig — Proxy spricht HTTP.
# ───────────────────────────────────────────────────────────
EXPOSE 8080

# ───────────────────────────────────────────────────────────
# OCI Image Spec Labels
# https://github.com/opencontainers/image-spec/blob/main/annotations.md
# Custom-Labels in reverse-DNS Notation (com.bauer-group.*) per Spec-Vorgabe.
# ───────────────────────────────────────────────────────────
LABEL org.opencontainers.image.title="Whistleblower-App (GlobaLeaks)" \
      org.opencontainers.image.description="BAUER GROUP Compliance Reporting Platform (HinSchG / EU 2019/1937)" \
      org.opencontainers.image.version="${BASE_VERSION}+bg" \
      org.opencontainers.image.vendor="BAUER GROUP" \
      org.opencontainers.image.authors="Karl Bauer <karl.bauer@bauer-group.com>" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/bauer-group/Whistleblower-App" \
      org.opencontainers.image.url="https://github.com/bauer-group/Whistleblower-App" \
      org.opencontainers.image.documentation="https://github.com/bauer-group/Whistleblower-App/blob/main/README.md" \
      org.opencontainers.image.base.name="globaleaks/globaleaks:${BASE_VERSION}" \
      com.bauer-group.compliance.framework="HinSchG,EU-2019-1937" \
      com.bauer-group.build.behind-proxy="${BEHIND_PROXY}"
