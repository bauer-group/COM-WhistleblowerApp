#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════
# Whistleblower-App (GlobaLeaks) - Upstream Patch Applier
# BAUER GROUP | Compliance Reporting Platform
# ═══════════════════════════════════════════════════════════
#
# Wendet BAUER-GROUP-Patches idempotent auf das Upstream-Image an.
# Gesteuert via Build-ARG BEHIND_PROXY (default: true).
#
#   BEHIND_PROXY=true  (Production: Traefik, Coolify)
#       → X-Forwarded-Proto-Patches für Redirect + HSTS/Onion
#         GlobaLeaks akzeptiert HTTPS vom Proxy, setzt HSTS+Onion korrekt.
#
#   BEHIND_PROXY=false (Development: direkter Port-Zugriff ohne TLS)
#       → HTTPS-Redirect komplett deaktiviert
#         GlobaLeaks antwortet direkt auf HTTP, sendet KEIN HSTS
#         (verhindert Browser-Pollution auf localhost mit preload=1 Jahr).
#
# Fail-fast: Bricht Build ab wenn Upstream-Kontext sich geändert hat.
# ═══════════════════════════════════════════════════════════

import os
import pathlib
import sys

API_FILE = "/usr/lib/python3/dist-packages/globaleaks/rest/api.py"

# ───────────────────────────────────────────────────────────
# Production-Patches (BEHIND_PROXY=true)
# ───────────────────────────────────────────────────────────

PATCH_REDIRECT_TRUST_XFP = {
    "name": "trust-xforwarded-proto-redirect",
    "target": API_FILE,
    "rationale": (
        "GlobaLeaks redirected jeden HTTP-Request auf HTTPS, ignoriert "
        "aber X-Forwarded-Proto → Redirect-Loop hinter Reverse Proxy. "
        "Sicher in unserem Setup: Container nur im internen Proxy-Netz, "
        "der Proxy überschreibt den Header bei jedem Request."
    ),
    "find": (
        "    def should_redirect_https(self, request):\n"
        "        if request.isSecure() or \\\n"
        "                request.hostname.endswith(b'.onion') or \\\n"
        "                b'acme-challenge' in request.path:\n"
    ),
    "replace": (
        "    def should_redirect_https(self, request):\n"
        "        if request.isSecure() or \\\n"
        "                request.getHeader(b'X-Forwarded-Proto') == b'https' or \\\n"
        "                request.hostname.endswith(b'.onion') or \\\n"
        "                b'acme-challenge' in request.path:\n"
    ),
}

PATCH_SETHEADERS_TRUST_XFP = {
    "name": "trust-xforwarded-proto-hsts-onion",
    "target": API_FILE,
    "rationale": (
        "set_headers() koppelt HSTS + Onion-Location an isSecure() — "
        "hinter HTTPS-Proxy wäre isSecure()=False, beide Header würden "
        "fehlen. Symmetrisch zum Redirect-Patch."
    ),
    "find": (
        "    def set_headers(self, request):\n"
        "        request.setHeader(b'Server', b'GlobaLeaks')\n"
        "\n"
        "        if request.isSecure():\n"
        "            request.setHeader(b'Strict-Transport-Security',\n"
    ),
    "replace": (
        "    def set_headers(self, request):\n"
        "        request.setHeader(b'Server', b'GlobaLeaks')\n"
        "\n"
        "        if request.isSecure() or request.getHeader(b'X-Forwarded-Proto') == b'https':\n"
        "            request.setHeader(b'Strict-Transport-Security',\n"
    ),
}

# ───────────────────────────────────────────────────────────
# Development-Patch (BEHIND_PROXY=false)
# ───────────────────────────────────────────────────────────

PATCH_DISABLE_REDIRECT_DEV = {
    "name": "disable-https-redirect-dev",
    "target": API_FILE,
    "rationale": (
        "Dev-Build ohne TLS/Proxy: jeder Redirect würde auf eine nicht-"
        "existente HTTPS-URL zeigen. Zusätzlich würde GlobaLeaks bei "
        "HTTPS-Zugriff HSTS mit preload auf localhost senden und damit "
        "den Browser für alle anderen lokalen Dev-Services kontaminieren. "
        "Daher: Redirect komplett deaktiviert — set_headers() setzt dann "
        "auch kein HSTS (weil isSecure()=False im Dev-HTTP-Direktzugriff)."
    ),
    "find": (
        "    def should_redirect_https(self, request):\n"
        "        if request.isSecure() or \\\n"
        "                request.hostname.endswith(b'.onion') or \\\n"
        "                b'acme-challenge' in request.path:\n"
        "            return False\n"
        "\n"
        "        return True\n"
    ),
    "replace": (
        "    def should_redirect_https(self, request):\n"
        "        # DEV-BUILD: Redirect hart disabled (BEHIND_PROXY=false)\n"
        "        return False\n"
    ),
}


def apply(patch: dict) -> str:
    target = pathlib.Path(patch["target"])
    if not target.exists():
        return f"MISSING ({target})"

    content = target.read_text(encoding="utf-8")

    if patch["replace"] in content:
        return "already-applied"

    if patch["find"] not in content:
        return "CONTEXT-MISMATCH (upstream changed?)"

    target.write_text(content.replace(patch["find"], patch["replace"], 1), encoding="utf-8")
    return "applied"


def main() -> int:
    behind_proxy = os.environ.get("BEHIND_PROXY", "true").strip().lower()

    if behind_proxy == "true":
        patches = [PATCH_REDIRECT_TRUST_XFP, PATCH_SETHEADERS_TRUST_XFP]
        print("Build mode: BEHIND_PROXY=true (production)")
    elif behind_proxy == "false":
        patches = [PATCH_DISABLE_REDIRECT_DEV]
        print("Build mode: BEHIND_PROXY=false (development)")
    else:
        print(f"ERROR: BEHIND_PROXY must be 'true' or 'false', got: {behind_proxy!r}")
        return 1

    failed = False
    for patch in patches:
        result = apply(patch)
        ok = not (result.startswith(("MISSING", "CONTEXT")) or result == result.upper() and " " not in result)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {patch['name']}: {result}")
        if not ok:
            failed = True

    if failed:
        print("\nPATCH FAILED — Upstream hat sich geändert. Kontext in")
        print("src/apply-patches.py gegen aktuelle Upstream-Version verifizieren.")
        return 1

    print("\nAlle Patches OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
