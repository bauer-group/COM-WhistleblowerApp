# ═══════════════════════════════════════════════════════════
# Whistleblower-App (GlobaLeaks) - BAUER GROUP Edition
# ═══════════════════════════════════════════════════════════
# Abgeleitet vom Upstream-Image. Wendet BAUER-GROUP-Patches (Reverse-Proxy-
# Kompatibilität, UI-Branding) + CI-Assets (Favicon, Logo, Brand-CSS).
#
# Upstream:  https://hub.docker.com/r/globaleaks/globaleaks
# Build:     docker compose -f docker-compose.<variant>.yml build
# ═══════════════════════════════════════════════════════════

ARG BASE_VERSION=latest

# ───────────────────────────────────────────────────────────
# Stage 1: Asset-Builder
# Generiert favicon.ico (multi-res) + logo.webp aus den CI-PNG-Assets.
# Läuft nur zur Build-Zeit, produziert keine Ebenen im finalen Image.
# ───────────────────────────────────────────────────────────
FROM python:3-alpine AS asset-builder

RUN pip install --no-cache-dir --quiet pillow

COPY branding/logo-square.png /src/logo-square.png
COPY branding/logo-wide.png   /src/logo-wide.png

RUN mkdir -p /out && python3 - <<'PY'
from PIL import Image
import os

# Favicon: Multi-Resolution-ICO aus Square-Logo
sq = Image.open('/src/logo-square.png').convert('RGBA')
sq.save('/out/favicon.ico',
        format='ICO',
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

# Logo: WebP aus Wide-Logo (GlobaLeaks erwartet .webp als Default)
wide = Image.open('/src/logo-wide.png').convert('RGBA')
wide.save('/out/logo.webp', format='WEBP', quality=92, method=6)

print('Assets generated:')
for f in sorted(os.listdir('/out')):
    print(f'  {f}: {os.path.getsize(f"/out/{f}")} bytes')
PY

# ───────────────────────────────────────────────────────────
# Stage 2: Final Image (abgeleitet von Upstream)
# ───────────────────────────────────────────────────────────
FROM globaleaks/globaleaks:${BASE_VERSION}

ARG BASE_VERSION

# BEHIND_PROXY steuert das Patch-Set (via src/patches/runner.py):
#   true  (production)  → X-Forwarded-Proto-Trust für Redirect + HSTS
#   false (development) → HTTPS-Redirect hart aus, kein HSTS auf localhost
ARG BEHIND_PROXY=true

# ───────────────────────────────────────────────────────────
# Branding-Assets + Patches kopieren (Root-User nötig)
# ───────────────────────────────────────────────────────────
USER root

# Custom CSS
COPY branding/bg-brand.css /usr/share/globaleaks/client/css/bg-brand.css

# Favicon + Logo — überschreiben die Upstream-Defaults. Wenn kein Admin-Upload
# in /s/favicon bzw. /s/logo existiert, fällt GlobaLeaks auf diese Files zurück
# (siehe handlers/file.py: 'favicon'/'logo'-Eintrag, 3. Tupel-Element).
COPY --from=asset-builder /out/favicon.ico /usr/share/globaleaks/client/images/favicon.ico
COPY --from=asset-builder /out/logo.webp   /usr/share/globaleaks/client/images/logo.webp

# Patches-Runner anwenden
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
