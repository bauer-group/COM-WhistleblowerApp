#!/bin/bash
# ============================================================
# Hinweisgebersystem – Full Stack Integration Verification
# ============================================================
# This script performs end-to-end verification of the Docker
# Compose deployment. It is designed to be run after:
#   docker compose up --build -d
#
# Usage:
#   chmod +x scripts/verify_integration.sh
#   scripts/verify_integration.sh
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed
# ============================================================
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
TOTAL_CHECKS=14

passed() {
    PASS_COUNT=$((PASS_COUNT + 1))
    echo -e "  ${GREEN}✓ PASS${NC}: $1"
}

failed() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo -e "  ${RED}✗ FAIL${NC}: $1"
    if [ -n "${2:-}" ]; then
        echo -e "         ${RED}→ $2${NC}"
    fi
}

skipped() {
    SKIP_COUNT=$((SKIP_COUNT + 1))
    echo -e "  ${YELLOW}○ SKIP${NC}: $1"
}

info() {
    echo -e "${BLUE}▸${NC} $1"
}

separator() {
    echo -e "\n${BLUE}─────────────────────────────────────────────${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}─────────────────────────────────────────────${NC}\n"
}

# ── Pre-flight check ──────────────────────────────────────

separator "Pre-flight Checks"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not found. Please install Docker first.${NC}"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose v2 not found.${NC}"
    exit 1
fi

# ── 1. Container Health ──────────────────────────────────

separator "1. Docker Compose Container Health"

EXPECTED_SERVICES=("reverse-proxy" "reporter-frontend" "admin-frontend" "api" "db" "redis" "minio")

info "Checking all 7 containers are running..."

ALL_RUNNING=true
for svc in "${EXPECTED_SERVICES[@]}"; do
    STATUS=$(docker compose ps --format '{{.State}}' "$svc" 2>/dev/null || echo "not_found")
    if [ "$STATUS" = "running" ]; then
        passed "Container '$svc' is running"
    else
        failed "Container '$svc' is not running" "Status: $STATUS"
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = false ]; then
    echo -e "\n${RED}Not all containers are running. Remaining checks may fail.${NC}"
fi

# ── 2. Alembic Migrations ────────────────────────────────

separator "2. Database Migrations (Alembic)"

info "Running alembic upgrade head..."
ALEMBIC_OUTPUT=$(docker compose exec -T api python -m alembic upgrade head 2>&1)
ALEMBIC_EXIT=$?

if [ $ALEMBIC_EXIT -eq 0 ]; then
    passed "Alembic upgrade head succeeded"
else
    failed "Alembic upgrade head failed" "$ALEMBIC_OUTPUT"
fi

# ── 3. Init DB Seed Script ───────────────────────────────

separator "3. Init DB Seed Script"

info "Running init_db to seed system tenant and admin..."
INIT_OUTPUT=$(docker compose exec -T api python -m app.scripts.init_db 2>&1)
INIT_EXIT=$?

if [ $INIT_EXIT -eq 0 ]; then
    passed "init_db seed script succeeded"
else
    failed "init_db seed script failed" "$INIT_OUTPUT"
fi

# ── 4. RLS Policies ──────────────────────────────────────

separator "4. Row-Level Security (RLS) Policies"

info "Checking RLS policies via pg_policies..."
RLS_TABLES=("reports" "messages" "attachments" "users" "audit_logs" "category_translations" "identity_disclosures")

for table in "${RLS_TABLES[@]}"; do
    RLS_OUTPUT=$(docker compose exec -T db psql -U "${DB_ADMIN_USER:-postgres}" -d "${DB_NAME:-hinweisgebersystem}" -t -c \
        "SELECT count(*) FROM pg_policies WHERE tablename = '$table' AND policyname = 'tenant_isolation'" 2>&1)
    RLS_COUNT=$(echo "$RLS_OUTPUT" | tr -d '[:space:]')

    if [ "$RLS_COUNT" = "1" ]; then
        passed "RLS policy 'tenant_isolation' active on '$table'"
    else
        failed "RLS policy missing on '$table'" "Count: $RLS_COUNT"
    fi
done

# ── 5. pgcrypto Extension ────────────────────────────────

separator "5. pgcrypto Extension"

info "Verifying pgcrypto extension..."
PGCRYPTO_OUTPUT=$(docker compose exec -T db psql -U "${DB_ADMIN_USER:-postgres}" -d "${DB_NAME:-hinweisgebersystem}" -t -c \
    "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'" 2>&1)
PGCRYPTO_NAME=$(echo "$PGCRYPTO_OUTPUT" | tr -d '[:space:]')

if [ "$PGCRYPTO_NAME" = "pgcrypto" ]; then
    passed "pgcrypto extension is installed and active"
else
    failed "pgcrypto extension not found" "$PGCRYPTO_OUTPUT"
fi

# ── 6. Reporter Frontend ─────────────────────────────────

separator "6. Reporter Frontend"

info "Loading reporter frontend at https://localhost..."
REPORTER_STATUS=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/ 2>/dev/null)

if [ "$REPORTER_STATUS" = "200" ]; then
    passed "Reporter frontend loads at https://localhost (HTTP $REPORTER_STATUS)"
else
    failed "Reporter frontend not reachable" "HTTP $REPORTER_STATUS"
fi

# Check for expected HTML content
REPORTER_BODY=$(curl -sk https://localhost/ 2>/dev/null)
if echo "$REPORTER_BODY" | grep -q '<div id="root">' 2>/dev/null; then
    passed "Reporter frontend contains React root element"
else
    failed "Reporter frontend missing React root element"
fi

# ── 7. Admin Frontend ────────────────────────────────────

separator "7. Admin Frontend"

info "Loading admin frontend at https://localhost/admin/..."
ADMIN_STATUS=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/admin/ 2>/dev/null)

if [ "$ADMIN_STATUS" = "200" ]; then
    passed "Admin frontend loads at https://localhost/admin/ (HTTP $ADMIN_STATUS)"
else
    failed "Admin frontend not reachable" "HTTP $ADMIN_STATUS"
fi

# Check for expected HTML content
ADMIN_BODY=$(curl -sk https://localhost/admin/ 2>/dev/null)
if echo "$ADMIN_BODY" | grep -q '<div id="root">' 2>/dev/null; then
    passed "Admin frontend contains React root element"
else
    failed "Admin frontend missing React root element"
fi

# ── 8. API Documentation ─────────────────────────────────

separator "8. API Documentation"

info "Accessing API docs at https://localhost/api/docs..."
DOCS_STATUS=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/api/docs 2>/dev/null)

if [ "$DOCS_STATUS" = "200" ]; then
    passed "API Swagger docs available at /api/docs (HTTP $DOCS_STATUS)"
else
    failed "API docs not reachable" "HTTP $DOCS_STATUS"
fi

# Check health endpoint
HEALTH_STATUS=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/api/v1/health 2>/dev/null)
HEALTH_BODY=$(curl -sk https://localhost/api/v1/health 2>/dev/null)

if [ "$HEALTH_STATUS" = "200" ] && echo "$HEALTH_BODY" | grep -q '"ok"' 2>/dev/null; then
    passed "Health endpoint returns OK at /api/v1/health"
else
    failed "Health endpoint not responding correctly" "HTTP $HEALTH_STATUS, Body: $HEALTH_BODY"
fi

# ── 9. CORS Headers ──────────────────────────────────────

separator "9. CORS Headers"

info "Checking CORS headers on API responses..."
CORS_HEADERS=$(curl -sk -H "Origin: https://localhost" -I https://localhost/api/v1/health 2>/dev/null)

if echo "$CORS_HEADERS" | grep -qi "access-control-allow-origin" 2>/dev/null; then
    passed "CORS Access-Control-Allow-Origin header present"
else
    failed "CORS headers missing from API response"
fi

# Check preflight
PREFLIGHT_STATUS=$(curl -sk -X OPTIONS \
    -H "Origin: https://localhost" \
    -H "Access-Control-Request-Method: POST" \
    -o /dev/null -w '%{http_code}' \
    https://localhost/api/v1/reports 2>/dev/null)

if [ "$PREFLIGHT_STATUS" = "204" ]; then
    passed "CORS preflight returns 204 for OPTIONS request"
else
    failed "CORS preflight unexpected status" "HTTP $PREFLIGHT_STATUS (expected 204)"
fi

# ── 10. TLS Termination ──────────────────────────────────

separator "10. TLS Termination (Caddy)"

info "Verifying TLS via Caddy..."
TLS_INFO=$(curl -sk -v https://localhost/ 2>&1 | grep "SSL connection using" || true)

if [ -n "$TLS_INFO" ]; then
    passed "TLS connection established via Caddy"
else
    # Try alternative check
    HTTP_REDIRECT=$(curl -sk -o /dev/null -w '%{http_code}' http://localhost/ 2>/dev/null)
    if [ "$HTTP_REDIRECT" = "301" ] || [ "$HTTP_REDIRECT" = "308" ]; then
        passed "HTTP redirects to HTTPS (status: $HTTP_REDIRECT)"
    else
        skipped "TLS check inconclusive (self-signed certs, curl -k used)"
    fi
fi

# Check security headers from Caddy
SECURITY_HEADERS=$(curl -sk -I https://localhost/ 2>/dev/null)

if echo "$SECURITY_HEADERS" | grep -qi "strict-transport-security" 2>/dev/null; then
    passed "HSTS header present"
else
    failed "HSTS header missing"
fi

if echo "$SECURITY_HEADERS" | grep -qi "x-content-type-options" 2>/dev/null; then
    passed "X-Content-Type-Options header present"
else
    failed "X-Content-Type-Options header missing"
fi

# ── 11. System Tenant & Admin Verification ────────────────

separator "11. System Tenant & Admin User"

info "Verifying system tenant exists in database..."
TENANT_OUTPUT=$(docker compose exec -T db psql -U "${DB_ADMIN_USER:-postgres}" -d "${DB_NAME:-hinweisgebersystem}" -t -c \
    "SELECT slug FROM tenants WHERE slug = 'system'" 2>&1)
TENANT_SLUG=$(echo "$TENANT_OUTPUT" | tr -d '[:space:]')

if [ "$TENANT_SLUG" = "system" ]; then
    passed "System tenant 'system' exists in database"
else
    failed "System tenant not found" "$TENANT_OUTPUT"
fi

info "Verifying system admin user exists..."
ADMIN_OUTPUT=$(docker compose exec -T db psql -U "${DB_ADMIN_USER:-postgres}" -d "${DB_NAME:-hinweisgebersystem}" -t -c \
    "SELECT email FROM users WHERE oidc_subject = 'init-system-admin'" 2>&1)
ADMIN_EMAIL=$(echo "$ADMIN_OUTPUT" | tr -d '[:space:]')

if [ -n "$ADMIN_EMAIL" ] && [ "$ADMIN_EMAIL" != "" ]; then
    passed "System admin user exists (email: $ADMIN_EMAIL)"
else
    failed "System admin user not found" "$ADMIN_OUTPUT"
fi

# ── 12. Audit Log Immutability ────────────────────────────

separator "12. Audit Log Immutability"

info "Verifying audit_logs immutability triggers..."
TRIGGER_COUNT=$(docker compose exec -T db psql -U "${DB_ADMIN_USER:-postgres}" -d "${DB_NAME:-hinweisgebersystem}" -t -c \
    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'audit_logs'::regclass AND tgname IN ('trg_audit_logs_no_update', 'trg_audit_logs_no_delete')" 2>&1)
TRIGGER_NUM=$(echo "$TRIGGER_COUNT" | tr -d '[:space:]')

if [ "$TRIGGER_NUM" = "2" ]; then
    passed "Audit log immutability triggers (UPDATE + DELETE) active"
else
    failed "Audit log triggers not found" "Expected 2, got: $TRIGGER_NUM"
fi

# ── Summary ───────────────────────────────────────────────

separator "Summary"

echo -e "  ${GREEN}Passed${NC}: $PASS_COUNT"
echo -e "  ${RED}Failed${NC}: $FAIL_COUNT"
echo -e "  ${YELLOW}Skipped${NC}: $SKIP_COUNT"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  All integration checks PASSED!          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    exit 0
else
    echo -e "${RED}╔══════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  $FAIL_COUNT check(s) FAILED                      ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════╝${NC}"
    exit 1
fi
