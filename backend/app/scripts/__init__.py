"""Hinweisgebersystem -- Management Scripts.

Standalone scripts for database initialisation, seeding, and
maintenance tasks.  These scripts are designed to be run via
``python -m app.scripts.<script_name>`` inside the API container.

Available scripts:

- ``init_db``: Initialise the database with the system admin tenant,
  first system_admin user, MinIO bucket, and pgcrypto verification.

Usage::

    docker compose exec api python -m app.scripts.init_db
"""
