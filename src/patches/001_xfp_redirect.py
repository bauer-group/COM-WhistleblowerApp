# ═══════════════════════════════════════════════════════════
# Patch 001: X-Forwarded-Proto im HTTPS-Redirect respektieren
# Applies: production (BEHIND_PROXY=true)
# ═══════════════════════════════════════════════════════════
#
# GlobaLeaks redirected jeden HTTP-Request auf HTTPS, ignoriert aber
# X-Forwarded-Proto → hinter einem HTTPS-terminierenden Proxy entsteht
# ein endloser Redirect-Loop.
#
# Sicher in unserem Setup: Container nur im internen Proxy-Netz,
# der Proxy überschreibt den Header bei jedem Request, client-seitig
# gesetzte Werte werden verworfen.
# ═══════════════════════════════════════════════════════════

APPLIES_WHEN = "production"

PATCHES = [
    {
        "name": "trust-xforwarded-proto-redirect",
        "target": "/usr/lib/python3/dist-packages/globaleaks/rest/api.py",
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
