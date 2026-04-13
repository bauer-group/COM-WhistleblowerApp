#!/bin/bash
# ============================================================
# PostgreSQL initialisation script – runs once on first start.
# Creates the non-superuser application role (app_user) used
# at runtime so that Row-Level Security (RLS) policies are
# enforced.  Superusers bypass ALL RLS – the application MUST
# connect as app_user.
# ============================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-EOSQL
    -- Enable pgcrypto extension (needed for field-level encryption)
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    -- Create non-superuser application role
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_APP_USER:-app_user}') THEN
            CREATE ROLE ${DB_APP_USER:-app_user}
                LOGIN
                PASSWORD '${DB_APP_PASSWORD:-changeme}'
                NOSUPERUSER
                NOCREATEDB
                NOCREATEROLE;
        END IF;
    END
    \$\$;

    -- Grant connect privilege
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${DB_APP_USER:-app_user};

    -- Grant schema usage
    GRANT USAGE ON SCHEMA public TO ${DB_APP_USER:-app_user};

    -- Default privileges so future tables created by migrations are accessible
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${DB_APP_USER:-app_user};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO ${DB_APP_USER:-app_user};
EOSQL
