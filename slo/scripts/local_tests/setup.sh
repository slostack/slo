#!/bin/bash
set -e

echo "Setting up the setup.sql file for database configurations"
export PGPASSWORD=$POSTGRES_PASSWORD
envsubst < ./scripts/local_tests/template_setup.sql > ./scripts/local_tests/setup_test_db.sql
psql -U "$POSTGRES_USER" -h localhost -p 5437 -d "$POSTGRES_DB" -f ./scripts/local_tests/setup_test_db.sql
