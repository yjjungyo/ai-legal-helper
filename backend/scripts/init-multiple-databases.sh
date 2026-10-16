#!/bin/bash
set -e

if [ -n "$POSTGRES_TEST_DB" ]; then
	echo "Creating test database: $POSTGRES_TEST_DB"
	psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	    CREATE DATABASE $POSTGRES_TEST_DB;
	    GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_TEST_DB TO $POSTGRES_USER;
	EOSQL
fi

echo "Creating langfuse database: langfuse"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE langfuse;
    GRANT ALL PRIVILEGES ON DATABASE langfuse TO $POSTGRES_USER;
EOSQL
