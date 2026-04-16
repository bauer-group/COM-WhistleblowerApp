# ═══════════════════════════════════════════════════════════
# Patch 003: HTTPS-Redirect komplett deaktivieren (Dev-Build)
# Applies: development (BEHIND_PROXY=false)
# ═══════════════════════════════════════════════════════════
#
# Dev-Build ohne TLS/Proxy: jeder Redirect würde auf eine nicht-existente
# HTTPS-URL zeigen. Zusätzlich würde GlobaLeaks bei HTTPS-Zugriff HSTS mit
# preload=1-Jahr auf localhost senden und damit den Browser für alle
# anderen lokalen Dev-Services kontaminieren.
#
# Daher: Redirect hart deaktiviert. set_headers() bleibt unverändert und
# setzt kein HSTS (weil isSecure()=False im Dev-HTTP-Direktzugriff).
# ═══════════════════════════════════════════════════════════

APPLIES_WHEN = "development"

PATCHES = [
    {
        "name": "disable-https-redirect-dev",
        "target": "/usr/lib/python3/dist-packages/globaleaks/rest/api.py",
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
    },
]
