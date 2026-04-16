# Whistleblower-App (GlobaLeaks)

Compliance Reporting Platform für die BAUER GROUP — basierend auf [GlobaLeaks](https://www.globaleaks.org/), zur Erfüllung der Hinweisgeber-Meldepflichten gemäß **EU-Richtlinie 2019/1937** und dem deutschen **Hinweisgeberschutzgesetz (HinSchG)**.

## Überblick

Self-hosted, anonyme Meldeplattform für Compliance-Verstöße. Whistleblower können verschlüsselt und (optional über Tor) absolut anonym Hinweise einreichen. Compliance-Officer empfangen die Meldungen über ein Web-Dashboard.

**Features:**

- Anonymes Melde-Frontend (mehrsprachig, 80+ Sprachen via GlobaLeaks-i18n)
- Verschlüsselter Datenaustausch zwischen Hinweisgeber & Empfänger
- Optionaler Tor-Onion-Service für maximale Anonymität
- BAUER-GROUP-Branding (Logo, Favicon, CI-Farben, entschärfter Tor-Hinweis)
- Reverse-Proxy-kompatibles Image (patcht `X-Forwarded-Proto`-Handling)
- Drei Deployment-Modi: Development, Traefik, Coolify

## Architektur-Entscheidung: TLS-Terminierung + Image-Patch

Der Reverse Proxy (Traefik bzw. Coolify) terminiert öffentliches TLS und leitet intern **Plain-HTTP** an `globaleaks:8080` weiter.

Damit das mit GlobaLeaks funktioniert, bauen wir ein eigenes, minimal abgeleitetes Image aus [`src/Dockerfile`](src/Dockerfile). Der Patch-Runner ([`src/patches/runner.py`](src/patches/runner.py)) lädt alle Patch-Module aus [`src/patches/`](src/patches/) (Namensmuster `NNN_*.py`) und wendet sie abhängig vom Build-ARG `BEHIND_PROXY` an:

| `BEHIND_PROXY` | Nutzung | Verhalten |
| --- | --- | --- |
| `true` (Compose: traefik/coolify) | Production | GlobaLeaks respektiert `X-Forwarded-Proto` → kein Redirect-Loop, HSTS + Onion-Location werden gesetzt |
| `false` (Compose: development) | Development | HTTPS-Redirect hart deaktiviert, **kein HSTS auf localhost** (verhindert Browser-Pollution mit preload=1-Jahr) |

**Sicherheit des `X-Forwarded-Proto`-Trusts**: Der Header wird nur respektiert weil der Container ausschließlich im internen Proxy-Netz erreichbar ist und der Proxy den Header bei jedem Request überschreibt (client-seitige Werte werden verworfen). Bei direkter Exposition des Containers wäre der Patch unsicher — in unserem Deployment-Modell ist er es nicht.

> **Hinweis zur Compliance**: Submissions sind client-seitig (PGP) verschlüsselt; der Proxy sieht nur Transport-Klartext. Für ein Single-Host-Deployment ohne Multi-Tenant-Proxy-Netz akzeptabel. Patch-Rationale wird in diesem README und in der Commit-History für Audits dokumentiert.

## Quick Start

### Voraussetzungen

- Docker & Docker Compose
- Production: Traefik mit Let's Encrypt, oder Coolify
- DNS: A-Record für `speakup.bauer-group.com` auf den Host

### Installation

1. Repository klonen:

   ```bash
   git clone https://github.com/bauer-group/COM-WhistleblowerApp.git
   cd COM-WhistleblowerApp
   ```

2. Environment-Datei anlegen:

   ```bash
   cp .env.example .env
   ```

3. `.env` anpassen:

   ```bash
   STACK_NAME=speakup_bauer-group_com
   GLOBALEAKS_HOSTNAME=speakup.bauer-group.com
   ```

4. Container starten (bei Erstdeployment: mit `--build` um Image aus `src/` zu bauen):

   ```bash
   # Production hinter Traefik
   docker compose -f docker-compose.traefik.yml up -d --build
   ```

5. Erste Konfiguration: siehe [First-Boot Setup](#first-boot-setup).

## Deployment-Optionen

### Development

Direkter Port-Zugriff, plain HTTP (Image wird lokal gebaut):

```bash
docker compose -f docker-compose.development.yml up -d --build
# → http://localhost:8080  (Wizard + Plattform)
```

### Production (Traefik)

TLS via Traefik + Let's Encrypt, Security-Headers, Rate-Limiting:

```bash
docker compose -f docker-compose.traefik.yml up -d --build
# → https://speakup.bauer-group.com
```

### Production (Coolify)

Coolify cloned das Git-Repo und baut das Image selbst:

- In Coolify: **Docker Compose**-Resource mit Git-URL auf dieses Repo anlegen
- Compose-File: `docker-compose.coolify.yml` auswählen
- Domain im Coolify-UI auf `GLOBALEAKS_HOSTNAME` setzen
- Deploy klicken — Coolify baut aus `src/Dockerfile` und routet Port 8080

## First-Boot Setup

Nach dem ersten Start ruft man die URL auf und durchläuft den Wizard. Direkt danach:

| Schritt | Pfad in Admin-UI | Wert |
| --- | --- | --- |
| 1 | Settings → HTTPS → "Let's Encrypt" | **OFF** (Proxy macht das public TLS) |
| 2 | Settings → Network → "Tor" | **ON** falls Onion Service gewünscht |
| 3 | Notifications → SMTP | Konfigurieren für Empfänger-Alerts |
| 4 | Users → Recipient | Compliance-Officer einrichten |

> Ohne Schritt 1 versucht GlobaLeaks selbst Port 80/443 zu öffnen → Konflikt mit dem Reverse Proxy.
>
> **Kein "Behind reverse proxy"-Toggle mehr nötig** — unser Image-Patch regelt das X-Forwarded-Proto-Handling in GlobaLeaks direkt.

## Konfiguration

### Environment-Variablen

| Variable | Default | Beschreibung |
| --- | --- | --- |
| `STACK_NAME` | `speakup_bauer-group_com` | Container-Naming-Prefix |
| `TIME_ZONE` | `Etc/UTC` | Container-Zeitzone |
| `GLOBALEAKS_HOSTNAME` | `speakup.bauer-group.com` | Public Hostname |
| `GLOBALEAKS_BASE_VERSION` | `latest` | Upstream-Tag auf dem das lokale Image baut |
| `PROXY_NETWORK` | `EDGEPROXY` | Traefik-Netzwerk |
| `GLOBALEAKS_CPU_LIMIT` | `2.0` | CPU-Limit |
| `GLOBALEAKS_MEM_LIMIT` | `1024M` | Memory-Limit |

### Firewall (Production)

| Port | Protokoll | Service |
| --- | --- | --- |
| 80 | TCP | HTTP → Redirect via Traefik |
| 443 | TCP | HTTPS via Traefik |

(Tor läuft nur outbound über Port 9001/9030/9050 zu den Tor Directory Authorities.)

## Backup & Restore

GlobaLeaks bringt ein eigenes Backup-Tool (`gl-admin`) das DB-Konsistenz garantiert. Pures Volume-Snapshot ist **nicht** sicher — der Container kann gerade in die SQLite schreiben.

### Backup

```bash
docker exec -it speakup_bauer-group_com_SERVER gl-admin backup
docker cp speakup_bauer-group_com_SERVER:/tmp/globaleaks_backup_$(date +%Y_%m_%d).tar.gz ./
```

### Restore

```bash
docker cp ./globaleaks_backup_YY_MM_DD.tar.gz speakup_bauer-group_com_SERVER:/tmp/
docker exec -it speakup_bauer-group_com_SERVER gl-admin restore /tmp/globaleaks_backup_YY_MM_DD.tar.gz
```

> **Empfehlung**: Backup-Aufruf in den vorhandenen BAUER-GROUP-Backup-Job (n8n / cron auf dem Host) einhängen — siehe Container-Solution Backup-Strategie.

## Update-Strategie

```bash
# Upstream-Base-Image aktualisieren und Image neu bauen
docker compose -f docker-compose.traefik.yml build --pull --no-cache
docker compose -f docker-compose.traefik.yml up -d

# DB-Migration läuft beim GlobaLeaks-Start automatisch.
# Vor jedem Update: Backup machen!
```

Der Patch-Runner ([`src/patches/runner.py`](src/patches/runner.py)) ist **fail-fast** — wenn Upstream eine gepatchte Funktion strukturell ändert, bricht der Build mit `CONTEXT-MISMATCH`. Dann in dem betroffenen Patch-Modul (`src/patches/NNN_*.py`) die `find`/`replace`-Strings an die neue Upstream-Version anpassen.

Für reproduzierbare Production-Deployments einen konkreten Upstream-Tag in `.env` pinnen:

```bash
GLOBALEAKS_BASE_VERSION=5.0.89
```

## Architektur

```text
                    ┌──────────────────────────────────┐
                    │           INTERNET               │
                    └──────────────┬───────────────────┘
                                   │
                          ┌────────▼─────────┐
                          │     Traefik      │
                          │  (TLS Terminate) │
                          │  :80 → redirect  │
                          │  :443 HTTPS      │
                          └────────┬─────────┘
                                   │ HTTP plain
                                   │ (intern, EDGEPROXY-Netz)
                                   │
                          ┌────────▼─────────┐
                          │   GlobaLeaks     │
                          │   :8080 (HTTP)   │
                          │   /var/globaleaks│
                          │   ├─ SQLite DB   │
                          │   ├─ Attachments │
                          │   └─ Tor keys    │
                          └──────────────────┘
                                   │
                                   │ (optional outbound)
                                   ▼
                          ┌──────────────────┐
                          │   Tor Network    │
                          │  (.onion service)│
                          └──────────────────┘
```

## Sicherheit & Compliance

### HinSchG-Mapping

| Anforderung (HinSchG § 16/17) | Umsetzung |
| --- | --- |
| Vertrauliche Bearbeitung | TLS extern, Submissions PGP-verschlüsselt |
| Anonyme Meldekanäle | Tor Onion Service + anonymer Web-Zugang |
| Zugriff nur für berechtigte Personen | GlobaLeaks Recipient-Rollen |
| Datenminimierung | Logs ohne PII, kurze Retention |
| Schutz vor unbefugtem Zugriff | TLS, CSP, HSTS, Frame-Deny |
| Bestätigung Eingang innerhalb 7 Tagen | GlobaLeaks Auto-Notification |
| Rückmeldung innerhalb 3 Monaten | Workflow im Recipient-Dashboard |

### Threat Model

- **In-Scope**: Anonymität des Hinweisgebers, Vertraulichkeit der Meldung, Integrität der Empfängerliste.
- **Out-of-Scope**: Kompromittierung des Host-Servers (separate Hardening-Aufgabe), Endgerät des Hinweisgebers.

### Bekannte Trade-offs

- **TLS-Terminierung am Proxy**: Klartext im Docker-Netz akzeptiert. Mitigation: Single-Host, kein Multi-Tenant im `EDGEPROXY`-Netz.
- **Image-Patch für `X-Forwarded-Proto`**: Zwei Stellen in GlobaLeaks gepatched — `should_redirect_https` (verhindert Redirect-Loop) und `set_headers` (stellt sicher dass HSTS und `Onion-Location` weiterhin gesetzt werden, obwohl der interne Request Plain-HTTP ist). Mitigation: Container nur im internen Proxy-Netz, Proxy überschreibt den Header bei jedem Request. Patch-Rationale in den jeweiligen Modulen [`src/patches/001_xfp_redirect.py`](src/patches/001_xfp_redirect.py) + [`002_xfp_set_headers.py`](src/patches/002_xfp_set_headers.py) dokumentiert.
- **HSTS-Quelle hängt vom Deployment ab**: Traefik-Compose setzt HSTS zusätzlich via Middleware (doppelt gemoppelt, schadet nicht). Coolify setzt HSTS **nicht** automatisch — dort stellt ausschließlich unser Patch HSTS sicher. Daher ist Patch #2 (`set_headers`) für Coolify-Deployments **Pflicht**, nicht Luxus.
- **`:latest` Tag default**: Erleichtert Updates, schwächt Reproduzierbarkeit. Mitigation: In Production digest pinnen.
- **Kein Auto-Backup**: Bewusste Entscheidung (geringe Meldefrequenz). Manuelle/cron-basierte Backups dokumentiert.

## Troubleshooting

### "Wizard nicht erreichbar"

```bash
docker logs speakup_bauer-group_com_SERVER -f
docker exec -it speakup_bauer-group_com_SERVER gl-admin status
```

### "Falsche Redirect-URL nach Login"

→ Falsches Image gestartet (upstream statt gepatched). `docker compose ... up -d --build` mit `--build`-Flag ausführen und im Build-Log sicherstellen dass alle Patches angewendet wurden (`✓ trust-xforwarded-proto-redirect: applied`, `✓ trust-xforwarded-proto-hsts-onion: applied`, etc., am Ende `Alle Patches OK.`).

### "Cert-Loop / GlobaLeaks versucht ACME"

→ Schritt 2 des First-Boot Setups vergessen (Let's Encrypt in GlobaLeaks deaktivieren).

### "Tor .onion nicht erreichbar"

```bash
docker exec -it speakup_bauer-group_com_SERVER cat /var/globaleaks/backend/tor/onion_service/hostname
```

## Dokumentation

- [GlobaLeaks Documentation](https://docs.globaleaks.org/)
- [GlobaLeaks Threat Model](https://docs.globaleaks.org/en/stable/security/ThreatModel.html)
- [HinSchG (Hinweisgeberschutzgesetz)](https://www.gesetze-im-internet.de/hinschg/)
- [EU-Richtlinie 2019/1937](https://eur-lex.europa.eu/eli/dir/2019/1937/oj)

## Branding

Das Image bringt BAUER-GROUP-Branding als Default mit — **kein Admin-Upload nötig** für frische Deployments. Quell-Assets in [`src/branding/`](src/branding/):

| Asset | Quelle | Ziel im Image |
| --- | --- | --- |
| Favicon (multi-res .ico 16/32/48/64px) | `logo-square.png` | `/usr/share/globaleaks/client/images/favicon.ico` |
| Default-Logo (.webp) | `logo-wide.png` | `/usr/share/globaleaks/client/images/logo.webp` |
| Brand-CSS (Orange-CI, System-Fonts, entschärfter Tor-Hinweis) | `bg-brand.css` | `/usr/share/globaleaks/client/css/bg-brand.css` |

Favicon und Logo werden beim Build über einen Multi-Stage-Builder (Python+Pillow) aus den PNG-Quellen generiert. Das Brand-CSS wird per Patch-Modul [`010_inject_brand_css.py`](src/patches/010_inject_brand_css.py) in die `index.html` eingebunden (Cache-Busting über `?v=N`-Querystring).

Admin-Uploads via GlobaLeaks-UI (`Admin → Files`) **überschreiben** die Defaults — saisonales oder abweichendes Branding jederzeit ohne Rebuild möglich.

## Lizenz

| Artefakt | Lizenz |
| --- | --- |
| Glue-Code in diesem Repo (Dockerfile, Patches, CSS, Compose) | **MIT** — siehe [LICENSE](LICENSE) |
| Gebautes Docker-Image | **AGPL-3.0-or-later** (abgeleitet von [GlobaLeaks](https://github.com/globaleaks/GlobaLeaks)) |

Die AGPL-Pflicht zur Source-Code-Bereitstellung ist durch die öffentliche Verfügbarkeit dieses Repos (enthält Dockerfile + Patches) und den Upstream-GitHub-Link in den [OCI-Image-Labels](src/Dockerfile) (`org.opencontainers.image.source`, `org.opencontainers.image.base.name`) erfüllt.

---

**BAUER GROUP** | Building Better Software Together
