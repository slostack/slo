---
name: setup-alembic
description: Initialising or managing Alembic migrations.
when_to_use: Use when setting up DB migrations for a new service or adding a non-trivial
  migration.
group: coding
kind: skill
source_prompt: setup-alembic.md
---

# Setup Alembic For Migrations

## Skill summary

- **Name:** `setup-alembic`
- **Description:** Initialising or managing Alembic migrations.
- **When to use:** Use when setting up DB migrations for a new service or adding a non-trivial migration.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `setup-alembic.md`

## Examples

- The user asks: "Set up alembic for this project."
- You are bootstrapping project infrastructure and need the setup checklist first.

## Guidance

This guide documents the complete setup process for Alembic database migrations in the orders_service application. Alembic is a lightweight database migration tool for SQLAlchemy that allows you to manage database schema changes in a version-controlled manner.

## Prerequisites

Before setting up Alembic, ensure you have completed the following from the main setup guide:

1. Python 3.14.2 installed via pyenv
2. The `orders` virtual environment created and activated
3. Poetry installed for dependency management
4. PostgreSQL running (via Docker Compose)
5. The `loadenv` helper function configured in your `.bashrc`

Refer to `skills/orientation/readme/SKILL.md` and `setup-readme.md` for detailed instructions on these prerequisites.

## Install Alembic

All commands should be executed within the `orders_service` folder (the application root) with the `orders` virtual environment activated.

### Step 1: Activate the Environment

```bash
orders_service $ source ~/.bashrc
orders_service $ pyenv activate orders
orders_service $ loadenv environments/development.env
```

### Step 2: Install Alembic Using Poetry

```bash
orders_service $ poetry add alembic
```

This will add Alembic to your `pyproject.toml` and update the `poetry.lock` file.

## Initialize Alembic

### Step 3: Initialize Alembic Directory Structure

Run the following command to create the Alembic directory structure. We use `db` as the migrations folder name:

```bash
orders_service $ poetry run alembic init db
```

This creates the following structure:

```
orders_service/
├── alembic.ini          # Alembic configuration file
└── db/
    ├── README           # Alembic readme
    ├── env.py           # Environment configuration for migrations
    ├── script.py.mako   # Template for new migrations
    └── versions/        # Directory containing migration scripts
```

## Configure Alembic

### Step 4: Set Up the Models Directory

Create the models directory structure under `src/models/` with three files:

```bash
orders_service $ mkdir -p src/models
orders_service $ touch src/models/__init__.py
orders_service $ touch src/models/model_base.py
orders_service $ touch src/models/model.py
orders_service $ touch src/models/base.py
```

#### `src/models/model_base.py`

This file contains the SQLAlchemy declarative base with custom functionality for automatic table naming and improved string representations:

```python
import typing
import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.orm import as_declarative, declared_attr
import re


def resolve_table_name(name):
    """Resolves table names to their mapped names."""
    names = re.split("(?=[A-Z])", name)  # noqa
    return "_".join([x.lower() for x in names if x])


class CustomBase:
    __repr_attrs__: list = []
    __repr_max_length__ = 15

    @declared_attr
    def __tablename__(self):
        return resolve_table_name(self.__name__)

    def dict(self):
        """Returns a dict representation of a model."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    @property
    def _id_str(self):
        ids = inspect(self).identity
        if ids:
            return "-".join([str(x) for x in ids]) if len(ids) > 1 else str(ids[0])
        else:
            return "None"

    @property
    def _repr_attrs_str(self):
        max_length = self.__repr_max_length__

        values = []
        single = len(self.__repr_attrs__) == 1
        for key in self.__repr_attrs__:
            if not hasattr(self, key):
                raise KeyError(
                    "{} has incorrect attribute '{}' in "
                    "__repr__attrs__".format(self.__class__, key)
                )
            value = getattr(self, key)
            wrap_in_quote = isinstance(value, str)

            value = str(value)
            if len(value) > max_length:
                value = value[:max_length] + "..."

            if wrap_in_quote:
                value = "'{}'".format(value)
            values.append(value if single else "{}:{}".format(key, value))

        return " ".join(values)

    def __repr__(self):
        # get id like '#123'
        id_str = ("#" + self._id_str) if self._id_str else ""
        # join class name, id and repr_attrs
        return "<{} {}{}>".format(
            self.__class__.__name__,
            id_str,
            " " + self._repr_attrs_str if self._repr_attrs_str else "",
        )


class_registry: typing.Dict = {}


@as_declarative(class_registry=class_registry)
class Base(CustomBase):
    id: typing.Any
    __name__: str

    def _repr(self, **fields: typing.Dict[str, typing.Any]) -> str:
        """Helper for __repr__"""

        field_strings = []
        at_least_one_attached_attribute = False
        for key, field in fields.items():
            try:
                field_strings.append(f"{key}={field!r}")
            except sqlalchemy.orm.exc.DetachedInstanceError:
                field_strings.append(f"{key}=DetachedInstanceError")
            else:
                at_least_one_attached_attribute = True
        if at_least_one_attached_attribute:
            return f"<{self.__class__.__name__}({','.join(field_strings)})>"
        return f"<{self.__class__.__name__} {id(self)}>"
```

#### `src/models/base.py`

This file re-exports the Base class for convenient importing throughout the application:

```python
from src.models.model_base import Base
```

#### `src/models/model.py`

This file imports all domain models for Alembic autogenerate support. When you create new domain models, add their imports here:

```python
# Import all domain models here for Alembic autogenerate support
# Example:
# from src.domains.user.model import User
# from src.domains.document.model import Document
# from src.domains.summary.model import Summary
```

### Step 5: Update the `env.py` File

Update the `db/env.py` file to configure the database URL from environment variables and import the Base metadata for autogenerate support.

Replace the contents of `db/env.py` with:

```python
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
import os

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None
from src.models.base import Base

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", os.environ.get("ORDERS_DB_URL"))

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Key configuration points:

1. The `ORDERS_DB_URL` environment variable is used for the database connection (this is the synchronous psycopg2 URL, not the async one)
2. The `Base.metadata` is imported from `src.models.base` for autogenerate support
3. The `config.set_main_option()` call overrides the default URL in `alembic.ini`

## Create Your First Migration

### Step 6: Create the Extensions Migration

Create a migration to enable the required PostgreSQL extensions (`uuid-ossp` for UUID generation and `vector` for pgvector support):

```bash
orders_service $ loadenv environments/development.env
orders_service $ poetry run alembic revision -m "create_extensions"
```

This creates a new migration file in `db/versions/` with a unique revision ID.

### Step 7: Edit the Migration File

Open the generated migration file (e.g., `db/versions/xxxx_create_extensions.py`) and update the `upgrade()` and `downgrade()` functions:

```python
"""create_extensions

Revision ID: xxxx
Revises: 
Create Date: 2026-01-25 08:45:42.249607

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'xxxx'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')


def downgrade() -> None:
    """Downgrade schema."""
    pass
```

Note: We don't drop the extensions in `downgrade()` as they may be used by other applications or schemas.

## Run Migrations

### Step 8: Apply Migrations

Ensure your PostgreSQL database is running and the environment is loaded:

```bash
orders_service $ docker compose -f docker/docker-compose.dev.yml --env-file environments/development.env up -d
orders_service $ loadenv environments/development.env
orders_service $ poetry run alembic upgrade head
```

Expected output:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> xxxx, create_extensions
```

### Step 9: Verify the Migration

Connect to the database and verify the extensions were created:

```bash
orders_service $ PGPASSWORD="${ORDERS_APP_DB_PASS}" psql -h localhost -p 5437 -U "${ORDERS_APP_DB_USER}" -d "${ORDERS_APP_DB_NAME}" -c "SELECT extname FROM pg_extension;"
```

Expected output:

```
  extname  
-----------
 plpgsql
 uuid-ossp
 vector
(3 rows)
```

## Common Alembic Commands

Here are the most commonly used Alembic commands:

### Check Current Migration Status

```bash
orders_service $ poetry run alembic current
```

### View Migration History

```bash
orders_service $ poetry run alembic history
```

### Create a New Migration (Manual)

```bash
orders_service $ poetry run alembic revision -m "description_of_changes"
```

### Create a New Migration (Autogenerate)

When you have models defined and want Alembic to detect changes automatically:

```bash
orders_service $ poetry run alembic revision --autogenerate -m "description_of_changes"
```

Note: For autogenerate to work, ensure all your models are imported in `src/models/model.py`.

### Apply All Pending Migrations

```bash
orders_service $ poetry run alembic upgrade head
```

### Apply a Specific Number of Migrations

```bash
orders_service $ poetry run alembic upgrade +1
```

### Rollback the Last Migration

```bash
orders_service $ poetry run alembic downgrade -1
```

### Rollback to a Specific Revision

```bash
orders_service $ poetry run alembic downgrade <revision_id>
```

### Rollback All Migrations

```bash
orders_service $ poetry run alembic downgrade base
```

## Environment-Specific Migrations

When running migrations in different environments, always load the appropriate environment file first:

### Development

```bash
orders_service $ loadenv environments/development.env
orders_service $ poetry run alembic upgrade head
```

### Test

```bash
orders_service $ loadenv environments/test.env
orders_service $ poetry run alembic upgrade head
```

## Adding New Domain Models

When you create a new domain model, follow these steps to ensure Alembic can detect and migrate it:

1. Create your model in `src/domains/<domain_name>/model.py` inheriting from `Base`:

```python
from sqlalchemy import Column, Integer, String, TIMESTAMP
from src.models.base import Base


class YourModel(Base):
    __tablename__ = "your_models"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    # ... other columns
```

2. Import the model in `src/models/model.py`:

```python
from src.domains.your_domain.model import YourModel
```

3. Generate the migration:

```bash
orders_service $ loadenv environments/development.env
orders_service $ poetry run alembic revision --autogenerate -m "add_your_model_table"
```

4. Review the generated migration file to ensure it's correct, then apply it:

```bash
orders_service $ poetry run alembic upgrade head
```

## Troubleshooting

### Migration Fails with "Target database is not up to date"

This means there are pending migrations. Run:

```bash
orders_service $ poetry run alembic upgrade head
```

### Autogenerate Doesn't Detect Model Changes

Ensure your models are imported in `src/models/model.py`. Alembic only detects models that are registered with the `Base.metadata`.

### Database URL Not Found

Ensure you've loaded the environment file before running Alembic commands:

```bash
orders_service $ loadenv environments/development.env
```

### Connection Refused

Ensure PostgreSQL is running:

```bash
orders_service $ docker compose -f docker/docker-compose.dev.yml --env-file environments/development.env up -d
```

### Permission Denied to Create Extension "vector"

This error occurs when running migrations on a database where the PostgreSQL extensions (`uuid-ossp` and `vector`) were not created during database setup:

```
psycopg2.errors.InsufficientPrivilege: permission denied to create extension "vector"
HINT:  Must be superuser to create this extension.
```

The `vector` extension (pgvector) requires superuser privileges to install. The extensions should be created by the `postgres` superuser during database setup, not by Alembic migrations.

To fix this issue:

1. Connect to PostgreSQL as the superuser:
```bash
PGPASSWORD="${POSTGRES_PASSWORD}" psql -U postgres -h localhost -p 5437 -d <your_database_name>
```

2. Create the extensions manually:
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

3. Then run your Alembic migrations:
```bash
loadenv environments/<your_env>.env
poetry run alembic upgrade head
```

For new database setups, ensure the setup scripts include extension creation. See `setup-readme.md` for the correct database setup workflow that includes extension creation.

## File Structure Summary

After completing the setup, your project should have the following structure:

```
orders_service/
├── alembic.ini                              # Alembic configuration
├── db/
│   ├── README
│   ├── env.py                               # Migration environment config
│   ├── script.py.mako                       # Migration template
│   └── versions/
│       └── xxxx_create_extensions.py        # First migration
├── src/
│   └── models/
│       ├── __init__.py
│       ├── base.py                          # Re-exports Base
│       ├── model.py                         # Imports all domain models
│       └── model_base.py                    # Base class definition
└── environments/
    ├── development.env
    └── test.env
```
