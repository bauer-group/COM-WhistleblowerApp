#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════
# Whistleblower-App (GlobaLeaks) - Upstream Patch Applier
# BAUER GROUP | Compliance Reporting Platform
# ═══════════════════════════════════════════════════════════
#
# Applies BAUER-GROUP-spezifische Patches idempotent auf das Upstream-Image.
# Ausgeführt einmalig im Docker-Build-Step, nicht zur Laufzeit.
#
# Idempotent: Reruns sind safe (prüft ob Patch bereits angewendet).
# Fail-fast:  Bricht Build ab wenn Upstream-Kontext sich geändert hat →
#             zwingt zu explizitem Review + Patch-Update.
# ═══════════════════════════════════════════════════════════

import pathlib
import sys

PATCHES = [
    {
        "name": "trust-xforwarded-proto",
        "target": "/usr/lib/python3/dist-packages/globaleaks/rest/api.py",
        "rationale": (
            "GlobaLeaks redirected jeden HTTP-Request auf HTTPS, ignoriert "
            "aber X-Forwarded-Proto — in Reverse-Proxy-Setups (Traefik/Coolify) "
            "entsteht dadurch ein endloser Redirect-Loop, weil der Proxy HTTPS "
            "terminiert und intern plain HTTP weiterleitet. Wir lehren "
            "GlobaLeaks den Header zu respektieren. Sicher in unserem Setup: "
            "Container ist nur im internen Proxy-Netz erreichbar, der Proxy "
            "überschreibt X-Forwarded-Proto bei jedem Request, client-seitig "
            "gesetzte Werte werden verworfen."
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
    },
]


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
    failed = False
    for patch in PATCHES:
        result = apply(patch)
        marker = "✗" if result.isupper() or result.startswith(("MISSING", "CONTEXT")) else "✓"
        print(f"  {marker} {patch['name']}: {result}")
        if marker == "✗":
            failed = True

    if failed:
        print("\nPATCH FAILED — Upstream hat sich geändert. Patch-Kontext in")
        print("src/apply-patches.py gegen aktuelle Upstream-Version verifizieren.")
        return 1

    print("\nAlle Patches OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
