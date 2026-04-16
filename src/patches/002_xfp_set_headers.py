# ═══════════════════════════════════════════════════════════
# Patch 002: X-Forwarded-Proto für HSTS + Onion-Location respektieren
# Applies: production (BEHIND_PROXY=true)
# ═══════════════════════════════════════════════════════════
#
# set_headers() koppelt HSTS und Onion-Location an isSecure() — hinter
# HTTPS-Proxy wäre isSecure()=False, beide Header würden fehlen:
#
#   - HSTS fehlt → Downgrade-Attack-Fenster
#   - Onion-Location fehlt → Tor-Browser-User werden nicht automatisch
#     zur .onion-Variante der Plattform umgeleitet
#
# Symmetrisch zum Redirect-Patch (001).
# ═══════════════════════════════════════════════════════════

APPLIES_WHEN = "production"

PATCHES = [
    {
        "name": "trust-xforwarded-proto-hsts-onion",
        "target": "/usr/lib/python3/dist-packages/globaleaks/rest/api.py",
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
    },
]
