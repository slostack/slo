---
name: setup-dependencies-and-tests
description: 'Python: Setting up Postgres, Docker, conftest.py, and the test infra.'
when_to_use: For Python projects only. Use when bootstrapping a new repo's test environment.
group: languages
kind: skill
source_prompt: setup-dependencies-and-tests.md
---

# Setup

## Skill summary

- **Name:** `setup-dependencies-and-tests`
- **Description:** Setting up Postgres, Docker, conftest.py, and the test infra.
- **When to use:** Use when bootstrapping a new repo's test environment.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `setup-dependencies-and-tests.md`

## Examples

- The user asks: "Set up dependencies and tests for this project."
- You are bootstrapping project infrastructure and need the setup checklist first.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

## Managing PostgreSQL dependencies

```bash
sudo apt update
sudo apt install -y build-essential python3-dev libpq-dev
```

### Creating a Postgres Docker Container

1. Create a folder under `/home/ubuntu/repos/orders-platform/orders_service/docker` called postgres
2. Create a file called `Dockerfile` with the following contents in it. 

```Dockerfile
ARG PG_MAJOR=16
FROM pgvector/pgvector:pg${PG_MAJOR}


RUN apt-get update -y && apt-get install -y \
    curl \
    build-essential \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    procps \
    git \
    telnet \
    net-tools  

ADD ./docker/postgres/init.sh /docker-entrypoint-initdb.d/init.sh
RUN chown postgres:postgres /docker-entrypoint-initdb.d/init.sh
# Pass them as build args
# ENV POSTGRES_PASSWORD=${POSTGRES_USER}
# ENV POSTGRES_USER=${POSTGRES_USER}
# ENV POSTGRES_DB=${POSTGRES_DB}

EXPOSE 5432
```
3. Create an `init.sh` file under the `/home/ubuntu/repos/orders-platform/orders_service/docker/postgres` folder with the following contents

```bash
#!/bin/bash
set -e

# Wait for PostgreSQL to start
until psql -c '\l'; do
  echo "Postgres is unavailable - sleeping"
  sleep 1
done


# Run SQL commands
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER $ORDERS_APP_DB_USER WITH PASSWORD '$ORDERS_APP_DB_PASS';
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE $ORDERS_APP_DB_NAME;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    GRANT ALL PRIVILEGES ON SCHEMA public TO $ORDERS_APP_DB_USER;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    GRANT CREATE ON DATABASE $ORDERS_APP_DB_NAME TO $ORDERS_APP_DB_USER;
    ALTER DATABASE $ORDERS_APP_DB_NAME OWNER TO $ORDERS_APP_DB_USER;
    GRANT USAGE ON SCHEMA public TO $ORDERS_APP_DB_USER;
    GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO $ORDERS_APP_DB_USER;
    GRANT USAGE, CREATE ON SCHEMA public TO $ORDERS_APP_DB_USER;
    GRANT CONNECT ON DATABASE $ORDERS_APP_DB_NAME TO $ORDERS_APP_DB_USER;
    GRANT ALL PRIVILEGES ON DATABASE $ORDERS_APP_DB_NAME TO $ORDERS_APP_DB_USER;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    \c $ORDERS_APP_DB_NAME
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "vector";
EOSQL
```

### Create An Environment File
1. Now set the environment variables needed to launch postgres. The folder path should be relative to the PYTHONPATH value in the application. 
2. Create a file under `src/environments/development.env` and add the environment variables to it.You can use the password in this example but the values for `ORDERS_ROOT_DIR`, `ORDERS_APP_DIR` would depend on your root path. 
3. First change directories into the orders_service application directory and run pwd. Use that value to set your `PYTHONPATH` variable. 


```env
PYTHONPATH=<workspace>/orders-platform/orders_service
ORDERS_ENV=development
ORDERS_ROOT_DIR=<workspace>/orders-platform/orders_service
ORDERS_APP_DIR=<workspace>/orders-platform/orders_service
ORDERS_DOMAIN=localhost:9001
ORDERS_DB_URL_ASYNC=postgresql+asyncpg://orders_app:localdev-password@localhost:5432/orders_development
ORDERS_DB_URL=postgresql+psycopg2://orders_app:localdev-password@localhost:5432/orders_development
ORDERS_REDIS_URL=redis://localhost:6379/0
# ORDERS_OPENAI_KEY=<your-openai-api-key>
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
ORDERS_APP_DB_USER=orders_app
ORDERS_APP_DB_PASS=localdev-password
ORDERS_APP_DB_NAME=orders_development
```
### Create The `loadenv` Helper In Bashrc

Add this snippet to bashrc and reload the shell. 

```bash
loadenv()
{
         echo "Loading $1"
         for i in $(cat $1 | grep "^[^#;]"); do
            export $i
          done
}
```
1. `cd` into the application folder and run `loadenv environments/development.env`. 
2. Check the values of the environment variable match the values in the `development.env`

## Steps To Setup The Application

```bash
$ cd /home/ubuntu/repos/orders-platform/orders_service
orders_service $ pyenv install python 3.14.2
orders_service $ pyenv virtualenv 3.14.2 orders
orders_service $ pyenv activate orders
orders_service $ pip install poetry 
orders_service $ poetry install
```
## Setup A Docker Compose File To Run Supporting Services
1. Create a `docker-compose.dev.yml` under the `docker` folder
2. Create a data folder to keep postgres data persistent between sessions under `data/postgres`
3. The `docker-compose.dev.yml` contents should look like this

```yml
version: '3'
services:  
  postgres:
    image: orders_postgres
    build:
      context: .
      dockerfile: postgres/Dockerfile
    env_file:
      - ./../environments/development.env
    expose:
      - 5432
    ports:
      - "5432:5432"
    volumes:
      - ./../data/postgres/db_data/:/var/lib/postgresl/data/
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 5s
      retries: 3
      
  redis:
    image: orders_redis
    build:
      context: .
      dockerfile: redis/Dockerfile
    env_file:
      - ./../environments/development.env
    volumes:
      - ./../data/redis/dump.rdb/:/var/lib/redis/dump.rdb/
    expose:
      - 6379
    ports:
      - "6379:6379"
```

## Let's Build The Postgres Image

1. Run the following command 

```bash
$ docker build --build-arg POSTGRES_USER="${POSTGRES_USER}" --build-arg POSTGRES_DB="${POSTGRES_DB}" --build-arg POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" -t orders_postgres -f docker/postgres/Dockerfile .
```
2. Verify if the image is built correctly

## Let's Try To Run The `docker-compose.dev.yml` File To Test Launch Our Service

The application depends on PostgreSQL and Redis to run. 

1. Launch the `docker-compose.dev.yml` file with the environment file using the command given below. 

```bash
orders_service $ docker compose -f docker/docker-compose.dev.yml --env-file environments/development.env up -d
```
2. Let's verify if our services are running 

## Setting Up Tests

### Transactional Unit Tests

#### Understanding Transactional Tests
1. We use transactional tests instead of resetting the database on each call. This is managed by the code in `tests/conftest.py`
2. if a test needs database access ensure the fixture `async_db_session` is passed as an argument after import the tests/conftest.py file.

The `db_session` method does the following things

1. It launches a database transaction before starting a test.
2. It launches a nested-transaction to allow us to call commit within our code.
3. It keeps an event handler looking for closing of a nested-transaction and re-launches a new nest-transaction
4. It closes the transaction and the session at the end of each test function.

```python
@pytest.fixture(scope="function")
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingLocalSession(bind=connection)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def end_savepoint(session, transaction):
        nonlocal nested

        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    if nested.is_active:
        nested.rollback()
    transaction.rollback()
    connection.close()
```

A sample test looks like this

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import model


class TestUserService:
    @pytest.mark.asyncio
    async def test_build_and_create(self, async_db_session: AsyncSession):
        from src.domains.user.service import UserService, User

        user: User = await UserService.build_and_create(
            email="ada.lovelace@example.com",
            db_session=async_db_session,
            password="password",
            first_name="Ada",
            last_name="Lovelace",
        )

        assert user.id is not None
        assert user.email == "ada.lovelace@example.com"
        assert user.first_name == "Ada"
        assert user.last_name == "Lovelace"
        assert user.timezone == "Asia/Kolkata"
        assert user.is_blocked is False
        assert user.verified_at is None
        assert user.user_metadata == {}
        assert user.created_at is not None
        assert user.encrypted_password is not None
```

#### Async Controller Tests and Database Session Middleware management
The app uses dependency injection to inject a connection object at the start of each request using an middleware. In `web_app.py`

```python
from time import time
from typing import Callable, Any, Optional
from fastapi.requests import Request
from starlette.types import ASGIApp
from starlette.middleware.base import BaseHTTPMiddleware
from connectors.async_postgres import get_async_session, async_scoped_session
from sqlalchemy.ext.asyncio import AsyncSession


class DbMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Dispatches the request to the next middleware or endpoint, while managing the database session.

        Args:
            request (Request): The incoming request.
            call_next (Callable): The next middleware or endpoint to call.

        Returns:
            Any: The response from the next middleware or endpoint.
        """
        db: AsyncSession = await get_async_session()
        try:
            request.state.db = db
            response: Any = await call_next(request)
        finally:
            # Uncomment for async API
            if request.state.db and request.state.db.is_active:
                if isinstance(request.state.db, AsyncSession):
                    db_session: AsyncSession = request.state.db
                    await db_session.close()
                else:
                    request.state.db.close()
        return response
```        

1. This ensures a database connection object is created and closed at the end of each request.

### Transactional Tests

However, our tests use transactional tests so we need to ensure that while running tests the application loads a test db connection and lets the test fixture manage the opening and closing of the connection.

As before we manage transactional tests using the `db_session` fixture in tests/conftest.py

## Setting Up Tests

### Setup `conftest.py`

1. Check if `conftest.py` exists. If not create the file under `tests/conftest.py` with the application root. 
2. Here is the code to place within it

```python
import asyncio
import pytest
import pytest_asyncio
import sqlalchemy
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker, scoped_session
from config.cfg import cfg


metadata = sqlalchemy.MetaData()

async_engine = create_async_engine(
    cfg("DB_URL_ASYNC"),
    pool_size=10,
    echo=False,
    max_overflow=10,
    pool_use_lifo=True,
    pool_recycle=100,
)
TestingAsyncSessionLocal = sessionmaker(
    async_engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
    class_=AsyncSession,
)  # type: ignore


@pytest.fixture(scope="session")
def event_loop():
    """
    Creates an instance of the default event loop for the test session.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def async_db_session():
    """The expectation with async_sessions is that the
    transactions be called on the connection object instead of the
    session object.

    Detailed explanation of async transactional tests
    https://github.com/sqlalchemy/sqlalchemy/issues/5811
    """
    async with async_engine.connect() as connection:
        trans = await connection.begin()
        async_session = TestingAsyncSessionLocal(bind=connection)
        nested = await connection.begin_nested()

        @event.listens_for(async_session.sync_session, "after_transaction_end")
        def end_savepoint(session, transaction):
            nonlocal nested

            if connection.closed:
                return

            if not connection.in_nested_transaction():
                nested = connection.sync_connection.begin_nested()

        yield async_session
        await trans.rollback()
        await async_session.close()
        await connection.close()
```
3. Create the following folders within the `tests` folder

```bash
orders_service $ mkdir -p tests/domains tests/services tests/routers
```
4. Create a sample test under `src/domains/` called `test_sample.py`
5. Add the following code within it

```python
from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

class TestSampleService:
    @pytest.mark.asyncio
    async def test_sample(db_session: AsyncSession): 
        assert 1==1
```

### Create A Test Database


#### Run the following commands to create a scripts for the testing

```bash
orders_service $ mkdir -p scripts/local_tests
orders_service $ touch scripts/local_tests/template_test_db_setup.sql
orders_service $ touch scripts/local_Tests/setup_test_db.sql
```

### `template_test_db_setup.sql`

```sql
-- Create a new database
CREATE DATABASE ${ORDERS_APP_DB_NAME};

-- Grant all privileges on the new database to the new user
GRANT ALL PRIVILEGES ON DATABASE ${ORDERS_APP_DB_NAME} TO ${ORDERS_APP_DB_USER};

-- Grant CREATE permission on the database (required for schema operations)
GRANT CREATE ON DATABASE ${ORDERS_APP_DB_NAME} TO ${ORDERS_APP_DB_USER};

ALTER DATABASE ${ORDERS_APP_DB_NAME} OWNER TO ${ORDERS_APP_DB_USER};

-- Connect to the new database and create extensions
-- Note: Extensions must be created by superuser (postgres) before running migrations
-- The 'vector' extension (pgvector) requires superuser privileges to install
\c ${ORDERS_APP_DB_NAME}
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

### `setup_test_db.sql`

```sql
-- Create a new database
CREATE DATABASE orders_test;

-- Grant all privileges on the new database to the new user
GRANT ALL PRIVILEGES ON DATABASE orders_test TO orders_app;

-- Grant CREATE permission on the database (required for schema operations)
GRANT CREATE ON DATABASE orders_test TO orders_app;

ALTER DATABASE orders_test OWNER TO orders_app;

-- Connect to the new database and create extensions
-- Note: Extensions must be created by superuser (postgres) before running migrations
-- The 'vector' extension (pgvector) requires superuser privileges to install
\c orders_test
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

### Important: PostgreSQL Extension Permissions

The `uuid-ossp` and `vector` (pgvector) extensions require superuser privileges to install. This is why the setup scripts create these extensions as the `postgres` user before transferring ownership to the application user.

If you encounter the error `permission denied to create extension "vector"` when running Alembic migrations, it means the extensions were not created during database setup. To fix this:

1. Connect to PostgreSQL as the superuser:
```bash
PGPASSWORD="${POSTGRES_PASSWORD}" psql -U postgres -h localhost -p 5437 -d orders_test
```

2. Create the extensions manually:
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

3. Then run your Alembic migrations:
```bash
loadenv environments/test.env
poetry run alembic upgrade head
```

### Create A Script To Execute The Commands In The Files

1. Create a file called `setup.sh` with the following code

```bash
#!/bin/bash
echo "Setting up the setup.sql file for database configurations at URL: ${ORDERS_DB_URL_ASYNC}"
export PGPASSWORD=$POSTGRES_PASSWORD
envsubst < ./scripts/local_tests/template_setup.sql > ./scripts/local_tests/setup.sql
psql -U $POSTGRES_USER -h localhost -d $POSTGRES_DB -f ./scripts/local_tests/setup.sql
```
2. Make the file executable
3. Copy the contents of the `environments/development.env` into `environments/test.env`
4. Change the database name to `orders_test` in the relevant places. 
6. Load the environment file and execute `setup.sh` file
6. Run tests with the following command to verify


```bash
orders_service $ pytest -sv tests
```
6. Verify if the one test we wrote passed.
