# Whistleblower-App (GlobaLeaks)

Compliance Reporting Platform für die BAUER GROUP — basierend auf [GlobaLeaks](https://www.globaleaks.org/), zur Erfüllung der Hinweisgeber-Meldepflichten gemäß **EU-Richtlinie 2019/1937** und dem deutschen **Hinweisgeberschutzgesetz (HinSchG)**.

## Überblick

Self-hosted, anonyme Meldeplattform für Compliance-Verstöße. Whistleblower können verschlüsselt und (optional über Tor) absolut anonym Hinweise einreichen. Compliance-Officer empfangen die Meldungen über ein Web-Dashboard.

**Features:**

- Anonymes Melde-Frontend (mehrsprachig)
- Verschlüsselter Datenaustausch zwischen Hinweisgeber & Empfänger
- Optionaler Tor-Onion-Service für maximale Anonymität
- Drei Deployment-Modi: Development, Traefik, Coolify

## Architektur-Entscheidung: TLS-Terminierung

Wir nutzen **Variante B**: Traefik (bzw. Coolify-Proxy) terminiert TLS und leitet Klartext-HTTP intern an `globaleaks:8080` weiter.

> **Hinweis zur Compliance**: GlobaLeaks unterstützt eigentlich End-to-End-TLS via `:8443`. Variante B akzeptiert bewusst, dass im Docker-internen Netz Klartext fließt. Submissions selbst sind **client-seitig** (PGP) verschlüsselt — der Reverse Proxy sieht nur transportseitig Klartext. Das Risiko ist akzeptabel für ein Single-Host-Deployment ohne Mandantentrennung im Proxy-Netz.

## Quick Start

### Voraussetzungen

- Docker & Docker Compose
- Production: Traefik mit Let's Encrypt, oder Coolify
- DNS: A-Record für `compliance.app.bauer-group.com` auf den Host

### Installation

1. Repository klonen:

   ```bash
   git clone https://github.com/bauer-group/Whistleblower-App.git
   cd Whistleblower-App
   ```

2. Environment-Datei anlegen:

   ```bash
   cp .env.example .env
   ```

3. `.env` anpassen:

   ```bash
   STACK_NAME=compliance_app_bauer-group_com
   GLOBALEAKS_HOSTNAME=compliance.app.bauer-group.com
   ```

4. Container starten:

   ```bash
   # Production hinter Traefik
   docker compose -f docker-compose.traefik.yml up -d
   ```

5. Erste Konfiguration: siehe [First-Boot Setup](#first-boot-setup).

## Deployment-Optionen

### Development

Direkter Port-Zugriff, GlobaLeaks terminiert HTTPS selbst (self-signed):

```bash
docker compose -f docker-compose.development.yml up -d
# → http://localhost:8080  (Wizard)
# → https://localhost:8443 (Cert-Warnung erwartet)
```

### Production (Traefik)

TLS via Traefik + Let's Encrypt, Security-Headers, Rate-Limiting:

```bash
docker compose -f docker-compose.traefik.yml up -d
# → https://compliance.app.bauer-group.com
```

### Production (Coolify)

Coolify übernimmt Reverse Proxy & TLS automatisch:

```bash
# In Coolify: Docker-Compose-Resource anlegen, dieses File einfügen.
docker compose -f docker-compose.coolify.yml up -d
```

## First-Boot Setup

Nach dem ersten Start ruft man die URL auf und durchläuft den Wizard. **Direkt danach** (Pflicht für Variant B):

| Schritt | Pfad in Admin-UI | Wert |
|---|---|---|
| 1 | Settings → Network → "Behind a reverse proxy" | **ON** |
| 2 | Settings → HTTPS → "Let's Encrypt" | **OFF** (Traefik macht das) |
| 3 | Settings → Network → "Tor" | **ON** falls gewünscht |
| 4 | Notifications → SMTP | Konfigurieren für Empfänger-Alerts |
| 5 | Users → Recipient | Compliance-Officer einrichten |

> Ohne Schritt 1 generiert GlobaLeaks falsche Redirect-URLs. Ohne Schritt 2 versucht GlobaLeaks selbst Port 80/443 zu öffnen → Konflikt mit Traefik.

## Konfiguration

### Environment-Variablen

| Variable | Default | Beschreibung |
|---|---|---|
| `STACK_NAME` | `compliance_app_bauer-group_com` | Container-Naming-Prefix |
| `TIME_ZONE` | `Etc/UTC` | Container-Zeitzone |
| `GLOBALEAKS_HOSTNAME` | `compliance.app.bauer-group.com` | Public Hostname |
| `GLOBALEAKS_IMAGE` | `globaleaks/globaleaks:latest` | Image-Tag (Production: pinned digest) |
| `ENABLE_TOR` | `true` | Doku-Flag — toggle in Admin-UI |
| `PROXY_NETWORK` | `EDGEPROXY` | Traefik-Netzwerk |
| `GLOBALEAKS_CPU_LIMIT` | `2.0` | CPU-Limit |
| `GLOBALEAKS_MEM_LIMIT` | `1024M` | Memory-Limit |

### Firewall (Production)

| Port | Protokoll | Service |
|---|---|---|
| 80 | TCP | HTTP → Redirect via Traefik |
| 443 | TCP | HTTPS via Traefik |

(Tor läuft nur outbound über Port 9001/9030/9050 zu den Tor Directory Authorities.)

## Backup & Restore

GlobaLeaks bringt ein eigenes Backup-Tool (`gl-admin`) das DB-Konsistenz garantiert. Pures Volume-Snapshot ist **nicht** sicher — der Container kann gerade in die SQLite schreiben.

### Backup

```bash
docker exec -it compliance_app_bauer-group_com_SERVER gl-admin backup
docker cp compliance_app_bauer-group_com_SERVER:/tmp/globaleaks_backup_$(date +%Y_%m_%d).tar.gz ./
```

### Restore

```bash
docker cp ./globaleaks_backup_YY_MM_DD.tar.gz compliance_app_bauer-group_com_SERVER:/tmp/
docker exec -it compliance_app_bauer-group_com_SERVER gl-admin restore /tmp/globaleaks_backup_YY_MM_DD.tar.gz
```

> **Empfehlung**: Backup-Aufruf in den vorhandenen BAUER-GROUP-Backup-Job (n8n / cron auf dem Host) einhängen — siehe Container-Solution Backup-Strategie.

## Update-Strategie

```bash
# Image aktualisieren (latest)
docker compose -f docker-compose.traefik.yml pull
docker compose -f docker-compose.traefik.yml up -d

# DB-Migration läuft beim Start automatisch.
# Vor jedem Update: Backup machen!
```

Für reproduzierbare Production-Deployments den Image-Digest in `.env` pinnen:

```bash
docker pull globaleaks/globaleaks:latest
docker inspect globaleaks/globaleaks:latest --format='{{index .RepoDigests 0}}'
# → globaleaks/globaleaks@sha256:abc123...
# In .env: GLOBALEAKS_IMAGE=globaleaks/globaleaks@sha256:abc123...
```

## Architektur

```
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
|---|---|
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

- **Variant B (TLS bei Traefik)**: Klartext im Docker-Netz akzeptiert. Mitigation: Single-Host, kein Multi-Tenant im `EDGEPROXY`-Netz.
- **`:latest` Tag default**: Erleichtert Updates, schwächt Reproduzierbarkeit. Mitigation: In Production digest pinnen.
- **Kein Auto-Backup**: Bewusste Entscheidung (geringe Meldefrequenz). Manuelle/cron-basierte Backups dokumentiert.

## Troubleshooting

### "Wizard nicht erreichbar"

```bash
docker logs compliance_app_bauer-group_com_SERVER -f
docker exec -it compliance_app_bauer-group_com_SERVER gl-admin status
```

### "Falsche Redirect-URL nach Login"

→ Schritt 1 des First-Boot Setups vergessen ("Behind reverse proxy: ON").

### "Cert-Loop / GlobaLeaks versucht ACME"

→ Schritt 2 des First-Boot Setups vergessen (Let's Encrypt in GlobaLeaks deaktivieren).

### "Tor .onion nicht erreichbar"

```bash
docker exec -it compliance_app_bauer-group_com_SERVER cat /var/globaleaks/backend/tor/onion_service/hostname
```

## Dokumentation

- [GlobaLeaks Documentation](https://docs.globaleaks.org/)
- [GlobaLeaks Threat Model](https://docs.globaleaks.org/en/stable/security/ThreatModel.html)
- [HinSchG (Hinweisgeberschutzgesetz)](https://www.gesetze-im-internet.de/hinschg/)
- [EU-Richtlinie 2019/1937](https://eur-lex.europa.eu/eli/dir/2019/1937/oj)

## License

MIT License — siehe [LICENSE](LICENSE).

---

**BAUER GROUP** | Building Better Software Together
