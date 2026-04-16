# ═══════════════════════════════════════════════════════════
# Patch 010: BAUER-GROUP-Brand-CSS in index.html injizieren
# Applies: always
# ═══════════════════════════════════════════════════════════
#
# Die Datei /usr/share/globaleaks/client/css/bg-brand.css wird vom
# Dockerfile aus src/branding/ kopiert. Dieser Patch fügt einen
# <link rel="stylesheet">-Verweis in index.html ein, sodass das
# Custom-CSS nach dem Upstream-Stylesheet geladen wird (Cascade-Override).
#
# Zusätzlich wird `lang="en"` → `lang="de"` gesetzt als Default — sonst
# rendert der HTML-Root fälschlich mit englischer Sprachauszeichnung,
# was Screenreader verwirren würde.
# ═══════════════════════════════════════════════════════════

APPLIES_WHEN = "always"

# Cache-Busting: Query-Suffix bei jeder signifikanten bg-brand.css-Änderung
# hochzählen, damit Browser/Tor-Browser die aktualisierte CSS nachladen und
# nicht aus dem Disk-Cache ausliefern (keine Cache-Control-Header auf dem
# Static-Path). Version folgt dem Build-State, nicht SemVer.
CSS_CACHE_VERSION = "4"

PATCHES = [
    {
        "name": "inject-bg-brand-css",
        "target": "/usr/share/globaleaks/client/index.html",
        "find": '<link rel="stylesheet" href="css/styles.css"></head>',
        "replace": (
            '<link rel="stylesheet" href="css/styles.css">'
            f'<link rel="stylesheet" href="css/bg-brand.css?v={CSS_CACHE_VERSION}"></head>'
        ),
    },
]
