# ═══════════════════════════════════════════════════════════
# Whistleblower-App (GlobaLeaks) - BAUER GROUP Edition
# ═══════════════════════════════════════════════════════════
# Abgeleitet vom Upstream-Image. Wendet BAUER-GROUP-Patches (Reverse-Proxy-
# Kompatibilität, Branding) und CI-CSS an.
#
# Upstream:  https://hub.docker.com/r/globaleaks/globaleaks
# Build:     docker compose -f docker-compose.<variant>.yml build
# ═══════════════════════════════════════════════════════════

ARG BASE_VERSION=latest
FROM globaleaks/globaleaks:${BASE_VERSION}

ARG BASE_VERSION

# BEHIND_PROXY steuert das Patch-Set (via src/patches/runner.py):
#   true  (production) → X-Forwarded-Proto-Trust für Redirect + HSTS
#   false (development) → HTTPS-Redirect hart aus, kein HSTS auf localhost
ARG BEHIND_PROXY=true

# ───────────────────────────────────────────────────────────
# Branding-Assets + Patches kopieren
# Root-User nötig für Zugriff auf /usr/lib/python3/dist-packages/
# ───────────────────────────────────────────────────────────
USER root

COPY branding/bg-brand.css /usr/share/globaleaks/client/css/bg-brand.css
COPY patches/ /tmp/patches/

RUN BEHIND_PROXY=${BEHIND_PROXY} python3 /tmp/patches/runner.py \
    && rm -rf /tmp/patches

USER globaleaks

# ───────────────────────────────────────────────────────────
# Port-Deklaration: Nur HTTP (8080)
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
      org.opencontainers.image.source="https://github.com/bauer-group/COM-WhistleblowerApp" \
      org.opencontainers.image.url="https://github.com/bauer-group/COM-WhistleblowerApp" \
      org.opencontainers.image.documentation="https://github.com/bauer-group/COM-WhistleblowerApp/blob/main/README.md" \
      org.opencontainers.image.base.name="globaleaks/globaleaks:${BASE_VERSION}" \
      com.bauer-group.compliance.framework="HinSchG,EU-2019-1937" \
      com.bauer-group.build.behind-proxy="${BEHIND_PROXY}"
