# ═══════════════════════════════════════════════════════════
# Patch 004: Certificate-Check härten gegen kaputte PEM-Daten
# Applies: production + development (always)
# ═══════════════════════════════════════════════════════════
#
# Upstream-Bug:
#   certificate_check.py ruft load_certificate(FILETYPE_PEM, cache['https_cert'])
#   ohne Fehlerbehandlung auf. Wenn ein Admin im UI https_enabled=true gesetzt
#   hat, aber das Cert-Blob leer/malformed ist, wirft OpenSSL:
#     OpenSSL.crypto.Error: [('PEM routines', '', 'no start line')]
#   Das triggert als DailyJob den Unhandled-Exception-Mailer in job.py —
#   Admin bekommt jede Nacht eine Mail.
#
# In unserer Architektur (Coolify terminiert TLS, Container exposed nur HTTP):
#   GlobaLeaks' interner HTTPS-Stack ist irrelevant → der Fehler ist purer
#   Log-/Mail-Spam ohne funktionalen Impact.
#
# Fix:
#   load_certificate-Aufruf in try/except wrappen. Bei Fehler → Tenant in
#   dieser Runde überspringen, via log.err() ins Container-Log schreiben,
#   aber KEINE Exception propagieren → kein on_error → keine Mail.
#   Admin kann via `docker logs` nachsehen falls er den Zustand verfolgen will.
# ═══════════════════════════════════════════════════════════

APPLIES_WHEN = "always"

PATCHES = [
    {
        "name": "guard-certificate-check-malformed-pem",
        "target": "/usr/lib/python3/dist-packages/globaleaks/jobs/certificate_check.py",
        "find": (
            "            if not self.state.tenants[tid].cache['https_enabled']:\n"
            "                continue\n"
            "\n"
            "            cert = load_certificate(FILETYPE_PEM, self.state.tenants[tid].cache['https_cert'])\n"
        ),
        "replace": (
            "            if not self.state.tenants[tid].cache['https_enabled']:\n"
            "                continue\n"
            "\n"
            "            try:\n"
            "                cert = load_certificate(FILETYPE_PEM, self.state.tenants[tid].cache['https_cert'])\n"
            "            except Exception as e:\n"
            "                log.err('Skipping cert-check for tid=%d: malformed https_cert (%s)', tid, e)\n"
            "                continue\n"
        ),
    },
]
