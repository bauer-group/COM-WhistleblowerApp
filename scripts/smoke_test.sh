#!/bin/bash
# ============================================================
# Hinweisgebersystem – Quick Smoke Test
# ============================================================
# Lightweight health check for all services. Use this after
# docker compose up to quickly verify all services respond.
#
# Usage:
#   chmod +x scripts/smoke_test.sh
#   scripts/smoke_test.sh
# ============================================================
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"

    STATUS=$(curl -sk -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)

    if [ "$STATUS" = "$expected_status" ]; then
        echo -e "  ${GREEN}✓${NC} $name (HTTP $STATUS)"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗${NC} $name (HTTP $STATUS, expected $expected_status)"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "  Hinweisgebersystem – Smoke Test"
echo "  ════════════════════════════════"
echo ""

# Wait for services to be ready
echo "  Waiting for services..."
for i in $(seq 1 30); do
    if curl -sk -o /dev/null https://localhost/api/v1/health 2>/dev/null; then
        break
    fi
    if [ "$i" = "30" ]; then
        echo -e "  ${RED}Services not ready after 30s. Aborting.${NC}"
        exit 1
    fi
    sleep 1
done
echo ""

# Service checks
check "API Health"          "https://localhost/api/v1/health"
check "API Docs (Swagger)"  "https://localhost/api/docs"
check "API OpenAPI Schema"  "https://localhost/api/openapi.json"
check "Reporter Frontend"   "https://localhost/"
check "Admin Frontend"      "https://localhost/admin/"

# Security headers
echo ""
echo "  Security Headers:"
HEADERS=$(curl -sk -I https://localhost/ 2>/dev/null)

for header in "x-frame-options" "x-content-type-options" "referrer-policy"; do
    if echo "$HEADERS" | grep -qi "$header"; then
        echo -e "  ${GREEN}✓${NC} $header present"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗${NC} $header missing"
        FAIL=$((FAIL + 1))
    fi
done

# Anonymity check: response time padding
echo ""
echo "  Anonymity Protection:"
START_MS=$(date +%s%N | cut -c1-13)
curl -sk -o /dev/null https://localhost/api/v1/health 2>/dev/null
END_MS=$(date +%s%N | cut -c1-13)
DURATION_MS=$((END_MS - START_MS))

if [ "$DURATION_MS" -ge 200 ]; then
    echo -e "  ${GREEN}✓${NC} Response time >= 200ms ($DURATION_MS ms) — timing padding active"
    PASS=$((PASS + 1))
else
    echo -e "  ${YELLOW}○${NC} Response time < 200ms ($DURATION_MS ms) — health endpoint may be exempt"
fi

# Summary
echo ""
echo "  ────────────────────────────────"
if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}All $PASS checks passed!${NC}"
else
    echo -e "  ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
fi
echo ""

exit $FAIL
