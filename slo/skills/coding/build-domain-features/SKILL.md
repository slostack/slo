---
name: build-domain-features
description: Creating domain entities — the 3-file dao.py / model.py / service.py
  pattern with Pydantic models.
when_to_use: Use when adding a new domain concept under src/domains/.
group: coding
kind: skill
source_prompt: build-domain-features.md
---

# Domain Features

## Skill summary

- **Name:** `build-domain-features`
- **Description:** Creating domain entities — the 3-file dao.py / model.py / service.py pattern with Pydantic models.
- **When to use:** Use when adding a new domain concept under src/domains/.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-domain-features.md`

## Examples

- The user asks: "Add or revise the domain features for this feature."
- You want the canonical build pattern before touching domain features.

## Guidance

A domain consists of 3 files and in some cases additional files. 

The three most commonly seen files are 

1. dao.py
2. model.py
3. service.py

The `dao.py` is a pydantic object file which is used to store transient data and perform model validations. 

## A Sample `User` Domain

The sample user domain is usually stored under `src/domains/users` and would contain the 3 files described above. 

### `dao.py`

Here is a sample `dao.py` from a different project used for the `src/domains/users`.

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from utils.datetime_support import date, datetime
from utils.datetime_support import TIMEZONE_ASIA_KOLKATA, date_to_datetime, asia_kolkata


class UserDAO(BaseModel):
    model_config = ConfigDict(
        title="user",
        extra="ignore",
        from_attributes=True,
        json_encoders={
            date: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )
    id: Optional[int] = Field(
        default=None,
        description="Primary key. None until the row is persisted.",
    )
    first_name: Optional[str] = Field(
        default=None,
        description="User's given name; absent until the profile is completed.",
    )
    last_name: Optional[str] = Field(
        default=None,
        description="User's family name; absent until the profile is completed.",
    )
    email: str = Field(
        ...,
        description="User's primary email; the natural-key login identifier.",
    )
    encrypted_password: Optional[str] = Field(
        default=None,
        description="bcrypt hash. None for SSO-only accounts.",
    )
    is_blocked: Optional[bool] = Field(
        default=False,
        description="True when an admin has suspended the account.",
    )
    timezone: Optional[str] = Field(
        default=TIMEZONE_ASIA_KOLKATA,
        description="Olson timezone id used for date display and scheduling.",
    )
    verified_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of email verification; None until verified.",
    )
    user_metadata: Optional[dict] = Field(
        default_factory=dict,
        description="Free-form metadata bag for feature flags + UI hints.",
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Row creation timestamp. Set by the DB on insert.",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Row last-modified timestamp. Set by the DB on update.",
    )


class UserProfileDAO(BaseModel):
    model_config = ConfigDict(
        title="user_profile",
        extra="ignore",
        from_attributes=True,
        json_encoders={
            date: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )
    id: Optional[int] = Field(
        default=None,
        description="Primary key. None until the row is persisted.",
    )
    first_name: Optional[str] = Field(
        default=None,
        description="User's given name.",
    )
    last_name: Optional[str] = Field(
        default=None,
        description="User's family name.",
    )
    email: str = Field(
        ...,
        description="User's primary email; the natural-key login identifier.",
    )
    timezone: Optional[str] = Field(
        default=TIMEZONE_ASIA_KOLKATA,
        description="Olson timezone id used for date display and scheduling.",
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Row creation timestamp. Set by the DB on insert.",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Row last-modified timestamp. Set by the DB on update.",
    )
```

The `UserDAO` always backs the model and usually looks exactly like the attributes in the model. 

The other daos are used for different purposes like accepting a value from the controller with validations. **All request body parameter DAOs (e.g., `CreateConversationParams`, `UpdateConversationParams`, `QueryRequest`) MUST be defined in the domain's `dao.py` file — never in controller/router files.** Controllers import these DAOs and use them as FastAPI request body types.

For example, a `CreateConversationParams` DAO belongs in `src/domains/conversation/dao.py` alongside the primary `ConversationDAO`, not inside `src/routers/conversations_controller.py`. This ensures reusability across controllers, services, and tests without circular imports.

**Domain naming — never alias domain entities.** When creating DAOs that represent a domain entity in a different context (e.g., a message used for AI context), name the DAO after the domain entity — `MessageContextDAO`, not `ConversationContextItemDAO`. Messages are messages. Conversations are conversations. Never invent new names for existing domain concepts.

### `service.py`

The service file is responsible for interacting with the data layer. Here is a sample `service.py` for the same user domain

The service methods follow a consistent CRUD pattern with additional domain specific methods. But expect to see the following on a consistent basis

1. create
2. build
3. build_and_create
4. update
5. get
6. delete/destroy
7. and other domain specific methods. 

Similarly the unit test file for this will contain a test for each of these methods testing each functionality specifically. 


```python
from typing import Any, Optional, Dict, List
from uuid import UUID
from utils.datetime_support import TIMEZONE_UTC, datetime
from src.domains.users.dao import UserDAO
from src.domains.users.model import User
from connectors.async_postgres import AsyncSession, get_async_session
import sqlalchemy as sa
from sqlalchemy.sql import Select, Update, and_
from sqlalchemy.engine.result import ChunkedIteratorResult
from src.domains.exceptions import DomainErrors


class UserAlreadyDeactivatedError(DomainErrors):
    pass


class UserAlreadyActiveError(DomainErrors):
    pass


class UserService:
    @staticmethod
    async def build(
        first_name: str,
        last_name: str,
        email: str,
        timezone: str = TIMEZONE_UTC,
        user_metadata: Optional[dict] = {},
        is_blocked: bool = False,
    ) -> UserDAO:
        """
        Build a UserDAO object with the given parameters.

        Args:
            first_name (str): The first name of the user.
            last_name (str): The last name of the user.
            email (str): The email address of the user.
            timezone (str, optional): The timezone of the user. Defaults to TIMEZONE_UTC.

        Returns:
            UserDAO: The UserDAO object with the given parameters.
        """
        user_dao: UserDAO = UserDAO(
            first_name=first_name,
            last_name=last_name,
            email=email,
            timezone=timezone,
            user_metadata=user_metadata,
            is_blocked=is_blocked,
        )
        return user_dao

    @staticmethod
    async def create(
        user_dao: UserDAO, db_session: AsyncSession = None, autocommit: bool = True
    ) -> User:
        """
        Create a new user in the database.

        Args:
            user_dao (UserDAO): The data access object containing user information.
            db_session (AsyncSession, optional): The database session. Defaults to None.
            autocommit (bool, optional): Flag indicating whether to commit the transaction automatically. Defaults to True.

        Returns:
            User: The created user object.
        """
        user: User = User(**user_dao.model_dump(mode="python", exclude_none=True))

        db_session.add(user)

        if autocommit:
            await db_session.commit()
        else:
            await db_session.flush()
        return user

    @staticmethod
    async def build_and_create(
        first_name: str,
        last_name: str,
        email: str,
        timezone: str = TIMEZONE_UTC,
        db_session: Optional[AsyncSession] = None,
        autocommit: bool = True,
        as_dao: bool = False,
    ) -> User:
        """
        Build and create a new user.

        Args:
            first_name (str): The first name of the user.
            last_name (str): The last name of the user.
            email (str): The email address of the user.
            timezone (str, optional): The timezone of the user. Defaults to TIMEZONE_UTC.
            db_session (Optional[AsyncSession], optional): The database session. Defaults to None.
            autocommit (bool, optional): Flag indicating whether to autocommit the transaction. Defaults to True.

        Returns:
            User: The created user object.
        """
        user_dao: UserDAO = await UserService.build(
            first_name=first_name,
            last_name=last_name,
            email=email,
            timezone=timezone,
        )

        user: User = await UserService.create(
            user_dao=user_dao, db_session=db_session, autocommit=autocommit
        )
        if as_dao:
            return UserDAO.from_orm(user)
        return user

    @staticmethod
    async def get(id: UUID, db_session: AsyncSession) -> User:
        """
        Retrieve a user by ID from the database.

        Args:
            id (UUID): The ID of the user to retrieve.
            db_session (AsyncSession): The database session.

        Returns:
            User: The retrieved user object, or None if not found.
        """
        stmt: Select = sa.select(User).where(
            and_(
                User.id == id,
                User.is_blocked == False,
            )
        )
        result: ChunkedIteratorResult = await db_session.execute(stmt)
        user: User = result.scalar_one_or_none()
        return user

    @staticmethod
    async def get_unscoped(id: UUID, db_session: AsyncSession) -> User:
        stmt: Select = sa.select(User).where(
            and_(
                User.id == id,
            )
        )
        result: ChunkedIteratorResult = await db_session.execute(stmt)
        user: User = result.scalar_one_or_none()
        return user

    @staticmethod
    async def get_by_email(
        email: str,
        db_session: AsyncSession,
        autocommit: bool = True,
        as_dao: bool = False,
    ) -> User:
        """
        Retrieve a user by their email address.

        Args:
            email (str): The email address of the user.
            db_session (AsyncSession): The database session.
            autocommit (bool, optional): Whether to automatically commit the transaction. Defaults to True.

        Returns:
            User: The user object if found, otherwise None.
        """
        stmt: Select = sa.select(User).where(
            and_(
                User.email == email,
            )
        )
        result: ChunkedIteratorResult = await db_session.execute(stmt)
        user: User = result.scalar_one_or_none()
        if autocommit:
            await db_session.commit()

        if user and as_dao:
            return UserDAO.from_orm(user)
        return user

    @staticmethod
    async def mark_as_verified(
        user: User, db_session: AsyncSession, autocommit: bool = True
    ) -> User:
        """
        Marks the user as verified by updating the 'verified_at' attribute with the current UTC datetime.

        Args:
            user (User): The user to mark as verified.
            db_session (AsyncSession): The database session.
            autocommit (bool, optional): Flag indicating whether to automatically commit the changes to the database. Defaults to True.

        Returns:
            User: The updated user object.
        """
        update_attributes: Dict[str, datetime] = {"verified_at": datetime.utcnow()}
        stmt: Update = (
            sa.update(User)
            .where(User.id == user.id)
            .values(update_attributes)
            .execution_options(synchronize_session="fetch")
        )
        result: ChunkedIteratorResult = await db_session.execute(stmt)
        _user: User = result.scalar_one_or_none()

        if autocommit:
            await db_session.commit()
        else:
            await db_session.flush()

        await db_session.refresh(user)
        return user

    @staticmethod
    async def update(
        user: User,
        attrs: Dict[str, Any],
        db_session: AsyncSession,
        autocommit: bool = True,
    ) -> User:
        """
        Update the attributes of a user object and save the changes to the database.

        Args:
            user (User): The user object to be updated.
            attrs (dict[str, Any]): A dictionary containing the attributes to be updated.
            db_session (AsyncSession): The database session to be used for the update operation.
            autocommit (bool, optional): Flag indicating whether to automatically commit the changes to the database. Defaults to True.

        Returns:
            User: The updated user object.

        """
        updateable_attrs: List[str] = [
            "first_name",
            "last_name",
            "timezone",
            "encrypted_password",
            "user_metadata",
        ]

        for key, val in attrs.items():
            if hasattr(user, key) and key in updateable_attrs and val is not None:
                setattr(user, key, val)

        db_session.add(user)

        if autocommit:
            await db_session.commit()
        else:
            await db_session.flush()
        return user

    @staticmethod
    async def deactivate(
        user: User, db_session: AsyncSession, autocommit: bool = True
    ) -> User:
        """
        Deactivates a user by setting the 'is_blocked' attribute to True.

        Args:
            user (User): The user to be deactivated.
            db_session (AsyncSession): The database session.
            autocommit (bool, optional): Flag to indicate whether to automatically commit the changes to the database. Defaults to True.

        Returns:
            User: The deactivated user.

        Raises:
            UserAlreadyDeactivatedError: If the user is already deactivated.
        """
        if user.is_blocked:
            raise UserAlreadyDeactivatedError(
                msg=f"User already deactivated",
                code="error_user_already_deactivated",
                http_error_code=400,
            )

        user.is_blocked = True
        db_session.add(user)
        if autocommit:
            await db_session.commit()
        else:
            await db_session.flush()
        return user

    @staticmethod
    async def activate(
        user: User, db_session: AsyncSession, autocommit: bool = True
    ) -> User:
        """
        Activate a user.

        Args:
            user (User): The user to activate.
            db_session (AsyncSession): The database session.
            autocommit (bool, optional): Whether to automatically commit the changes to the database. Defaults to True.

        Returns:
            User: The activated user.

        Raises:
            UserAlreadyActiveError: If the user is already active.
        """
        if not user.is_blocked:
            raise UserAlreadyActiveError(
                msg=f"User already activated",
                code="error_user_already_activated",
                http_error_code=400,
            )

        user.is_blocked = False
        db_session.add(user)
        if autocommit:
            await db_session.commit()
        else:
            await db_session.flush()
        return user
```

The domain service usually only deals with a single domain. If our tasks involve application logic or dealing with multiple domains we use them in the application service. More on this later. 

### `model.py`

THis model.py is used to integrate with SQLALchemy and the PostgresSQL database

Here is the code for the same user domain model

```python
from src.models.base import Base
from sqlalchemy.orm import relationship
from sqlalchemy import Boolean, Column, String
from sqlalchemy.dialects.postgresql import BIGINT, JSONB, TIMESTAMP
from utils.datetime_support import utc_now


class User(Base):
    __tablename__ = "users"

    id = Column(
        BIGINT(),
        primary_key=True,
        index=True,
        nullable=False,
        autoincrement=True,
    )
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True, unique=True)
    encrypted_password = Column(String(255), nullable=True)
    is_blocked = Column(Boolean(), index=True, default=False)
    timezone = Column(String(90), default="UTC", nullable=False)
    verified_at = Column(TIMESTAMP(timezone=True), nullable=True, default=None)
    user_metadata = Column(JSONB(), nullable=True, default=lambda: {})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Adding relationships
    documents = relationship("Document", back_populates="user", uselist=True)
    verifications = relationship("Verification", back_populates="user", uselist=True)
    sessions = relationship("Session", back_populates="user", uselist=True)
    reviews = relationship("Review", back_populates="user", uselist=True)
    
    def __repr__(self):
        return self._repr(fields=self.dict())

    __mapper_args__ = {"eager_defaults": True}

```

Now in order to ensure the model is loaded correctly we add the model name to the `src/domains/models.py` file

```python
from src.domains.reviews.model import Review
from src.domains.session.model import Session
from src.domains.audio.model import Audio
from src.domains.classification.model import Classification
from src.domains.summary.model import Summary
from src.domains.verifications.model import Verification
from src.domains.document.model import Document

# The models defined above are the ones added later. 
# The oldest inclusion is expected at the bottom

# In some cases these are reorganized to ensure imports are managed correctly 
# and in the right order. 
from src.domains.user.model import User
```

## Events. 
In some cases the system has events which are triggered to manage 
1. Asynchronous processing
2. Event sourcing
3. Create a causally ordered sequence of facts in the system. 

So in these scenarios the domain folder would also contain an `event.py` file. The following is a sample of an `event.py`

The event example in this case is from a different codebase but should be indicate of the structure of the event

```python
from sqlalchemy.orm.session import Session
from sqlalchemy import event, inspect
from bushido.domains.otp_verifications.dao import (
    OtpVerificationDAO,
    SignupVerificationDAO,
)
from bushido.domains.user.model import User
from config import log_info
from typing import Union, List
from bushido.domains.system_event.dao import SystemEventDAO
from bushido.domains.user.dao import UserDAO
from bushido.domains.product.product_dao import ProductDAO
from bushido.domains.food_logs.dao import FoodLogDAO
from fastapi.encoders import jsonable_encoder
import json


class UserSignedUpEventDAO(SystemEventDAO):
    def __init__(
        self,
        phone_number: Union[str, None] = None,
        otp_verification: Union[SignupVerificationDAO, None] = None,
        errors: Union[List, None] = [],
        error_code: Union[str, None] = None,
    ):
        version = "1.0"
        payload = {
            "phone_number": phone_number if phone_number else None,
            "otp_verification": otp_verification.dict() if otp_verification else {},
            "errors": errors,
            "error_code": error_code,
        }
        payload = jsonable_encoder(payload)
        super().__init__(
            event_name=self.__class__.__name__.replace("DAO", ""),
            payload=json.dumps(payload),
            version=version,
        )


class UserSignUpFailedEventDAO(UserSignedUpEventDAO):
    pass


class UserCreatedEventDAO(SystemEventDAO):
    def __init__(
        self,
        user: Union[UserDAO, None] = None,
        otp_verification: Union[OtpVerificationDAO, None] = None,
        errors: Union[List, None] = [],
        error_code: Union[str, None] = None,
    ):
        version = "1.0"
        payload = {
            "user": user.dict() if user else {},
            "otp_verification": otp_verification.dict() if otp_verification else {},
            "errors": errors,
            "error_code": error_code,
        }
        payload = jsonable_encoder(payload)
        super().__init__(
            event_name=self.__class__.__name__.replace("DAO", ""),
            payload=json.dumps(payload),
            version=version,
        )


class UserCreationFailedEventDAO(UserCreatedEventDAO):
    pass
```

Each event indicates the nature of the operation. The event name is usually a fact that has occurred in the system. 

### System Events

The system events domain is a database backed domain that is created as such under `src/domains/system_events`

This stores all the events that happen in the system onto a database or persistent store. 

Here are how the files look


```python
# dao.py

from typing import Optional, Dict
from pydantic import BaseModel, Json, Field, validator
from datetime import datetime
from uuid import UUID


class SystemEventDAO(BaseModel):
    time: Optional[datetime] = Field(default_factory=datetime.utcnow)
    id: Optional[UUID]
    event_name: Optional[str]
    version: Optional[str]
    payload: Optional[Json[Dict]]
    logged_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

    class Config:
        title = "system_events"
        orm_mode = True
        arbitrary_types_allowed = True
        anystr_strip_whitespace = True
        json_encoders = {UUID: lambda o: str(o)}

    @validator("event_name", "version", "payload", pre=True)
    def validate_presence_of(cls, value):
        if not value:
            raise ValueError("event_name cannot be null")
        return value


class SystemEventPartitionConfig(BaseModel):
    hostname: str
    worker_name: str
    partition_id: Optional[str]
    partition_key: Optional[str]
```

The `model.py`
```python
from sqlalchemy.sql.schema import Index
from sqlalchemy.sql.sqltypes import TIMESTAMP, Numeric
from bushido.models.base import Base

import sqlalchemy
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, DateTime, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=sqlalchemy.text("uuid_generate_v4()"),
    )
    time = Column(TIMESTAMP(timezone=True), index=True, nullable=False)
    event_name = Column(String, index=True, nullable=False)
    version = Column(String, index=True, nullable=False)
    payload = Column(JSONB(none_as_null=True), nullable=False)
    logged_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return self._repr(fields=self.dict())
```

The `service.py`

```python
from connectors.postgres import get_session
from sqlalchemy.orm.session import Session
from bushido.domains.system_event.dao import SystemEventDAO, SystemEventPartitionConfig
from bushido.domains.system_event.model import SystemEvent
from bushido.domains.system_event.partition_config import ring, continuum
from kombu.exceptions import OperationalError, ConnectionError

from config import log_error, log_info


class SystemEventsService:
    @staticmethod
    async def create(event_dao: SystemEventDAO, db_session: Session = None):
        if not db_session:
            db_session = get_session()

        try:
            event = SystemEvent(**event_dao.dict())
            db_session.add(event)
            db_session.commit()
            return event
        except Exception as e:
            log_error(
                msg=f"Event logging failed for {event_dao.dict()}",
                loc=f"{__name__}",
                method="create",
                e=e,
            )
        return None

    @staticmethod
    async def trigger(
        partition_key: str, event_dao: SystemEventDAO, db_session: Session = None
    ):
        import bushido.workers.system_events_worker as system_events_workers

        if not db_session:
            db_session: Session = get_session()

        try:
            worker: SystemEventPartitionConfig = await SystemEventsService._get_worker(
                partition_key=partition_key
            )
            worker_func = getattr(system_events_workers, worker.worker_name)
            log_info(msg=f"Trigger called with worker: {worker.worker_name}")
            worker_func.delay(event_dao=event_dao.json())
        except (OperationalError, ConnectionError) as e:
            log_error(msg=f"[RedisError] {e}", e=e, method="trigger", loc=f"{__name__}")
        except Exception as e:
            log_error(
                msg=f"SystemEventError: {e}", e=e, method="trigger", loc=f"{__name__}"
            )
        return

    @staticmethod
    async def _get_worker(partition_key: str) -> SystemEventPartitionConfig:
        """For a given string it returns the worker that should process the event by running it through a murmurr hashing
        function and uses that to fetch the nodes from the continuum"""

        node = ring.get(key=partition_key)
        nodename = node.get("nodename", None)

        if not nodename:
            raise ValueError("Could not find a node in the continuum for key {node}")

        node_config = continuum.get(nodename, None)
        if not node_config:
            raise ValueError(
                "Could not find a node in the continuum for key {nodename}"
            )

        config_attrs = {"partition_key": partition_key, "partition_id": nodename}
        config_attrs = {**node_config, **config_attrs}
        return SystemEventPartitionConfig(**config_attrs)
```

Most models are backed by an alembic migration and the migration for the `system_events` table is 

```python
"""create_events

Revision ID: cf92dce07286
Revises: 6aa0029d28be
Create Date: 2022-11-25 01:28:24.301064

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.sql.schema import ForeignKey


# revision identifiers, used by Alembic.
revision = 'cf92dce07286'
down_revision = '6aa0029d28be'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "entity_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "entity_type",
            sa.String(40),
            nullable=False,
            default="Challenge",
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.String(40),
            nullable=False,
            default="CompanionLiveSession",
        ),
        sa.Column(
            "platform",
            sa.String(40),
            nullable=False,
            default="Zoom",
        ),
        sa.Column(
            "platform_meeting_id",
            sa.String(80),
            nullable=True,
        ),
        sa.Column(
            "start_url",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "agenda",
            sa.String(400),
            nullable=True,
        ),
        sa.Column(
            "registration_url",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "start_time", 
            TIMESTAMP(timezone=True),
            nullable=True,            
        ),
        sa.Column(
            "end_time", 
            TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "duration_in_mins", 
            sa.Integer(),
            nullable=True,
            default=60,
        ),
        sa.Column(
            "metadata",
            JSONB(none_as_null=True),
            nullable=True,
            default=lambda: {},
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
            server_onupdate=sa.text("now()"),
        ),
    )
    op.execute("COMMIT")

    op.create_index(
        index_name="name_events_idx",
        columns=["name"],
        table_name="events",
        postgresql_concurrently=True,
    )
    op.create_index(
        index_name="entity_id_events_idx",
        columns=["entity_id"],
        table_name="events",
        postgresql_concurrently=True,
    )
    op.create_index(
        index_name="entity_type_events_idx",
        columns=["entity_type"],
        table_name="events",
        postgresql_concurrently=True,
    )
    op.create_index(
        index_name="user_id_events_idx",
        columns=["user_id"],
        table_name="events",
        postgresql_concurrently=True,
    )
    op.create_index(
        index_name="start_time_events_idx",
        columns=["start_time"],
        table_name="events",
        postgresql_using="brin"
    )
    op.create_index(
        index_name="end_time_events_idx",
        columns=["end_time"],
        table_name="events",
        postgresql_using="brin"
    )
    op.create_unique_constraint(
        constraint_name="unq_user_id_entity_id_entity_type_events",
        table_name="events",
        columns=["entity_type", "entity_id", "user_id"],
    )


def downgrade():
    op.drop_table("events")
```

Important Notes
-----------------
1. Note this system uses UUID but you should decide based on the primary key ids specified and used in the current project.
2. The table names are always the pluralized version of the model name. FOr example `SystemEvent` will have a table called `system_events`
3. The folder for the domain would be the singluar version of the table_name `system_event`
4. There would be a corressponding folder in the `tests` under `tests/domains/system_event/` and we'd test the domain service as such `tests/domains/system_events/test_system_event_service.py`
5. **One domain per database table.** Each table MUST have its own separate domain directory with its own `model.py`, `dao.py`, and `service.py`. Never combine multiple tables into a single domain directory. For example, `conversations` and `messages` are two separate tables and must live under `src/domains/conversation/` and `src/domains/message/` respectively — never combined into a single `src/domains/conversations/` directory.
6. **One migration file per table.** Each Alembic migration file should create or alter a single table. Do not combine multiple table creations into a single migration file.
7. **Updates use `attrs: Dict[str, Any]` + `updatable_attrs: List[str]` allow-list.** See "Update Convention" below.
8. **State transitions get dedicated `mark_as_<state>()` methods**, never a generic `update_status` / `transition_status` / `set_state`. See "State-Transition Convention" below.
9. **Boolean toggles get dedicated `toggle_<field_name>()` methods.** See "Boolean-Toggle Convention" below.
10. **Validation lives in Pydantic DAO `@field_validator`s**, never in service-layer imperative guards. See "Validation Convention" below.
11. **Every Pydantic field is declared with `Field(default=..., description=...)`** — never a bare `= value` default and never an undocumented field. See "Field-Declaration Convention" below.

---

## Field-Declaration Convention — `Field(default=..., description=...)` on every field

Every field on every Pydantic `BaseModel` in this codebase MUST be
declared with `Field(default=..., description=...)`. This applies to
domain DAOs (`UserDAO`, `MessageDAO`, etc.), request bodies
(`QueryRequest`, `CreateConversationParams`), response payloads,
internal value-holding models (`_StreamTracker`, `ProgressEvent`,
`ModeTokenBudgetDAO`), and every other class that subclasses
`BaseModel`. **No exceptions.**

### Why

The bare assignment pattern (`name: str = "Alice"`) works at runtime
but produces silently undocumented code. The `Field(...)` pattern
makes four wins available for free:

1. **Self-documenting source.** A reader sees the description next
   to the field, in the place they're most likely to look.
   Searching the codebase for `"description"` finds every field's
   intent in one query.
2. **JSON Schema generation.** `model.model_json_schema()` emits a
   schema with `"description"` populated on every field. FastAPI
   uses this to render rich `/docs` pages; Pydantic uses it for
   error messages; downstream tooling (OpenAPI clients, validators)
   consumes it.
3. **IDE tooltips.** PyCharm, VS Code (via Pylance / Pyright), and
   most editors surface the description on hover. A maintainer
   touching a field sees its purpose without leaving the call site.
4. **Schema diffing.** Reviewing a PR that touches a DAO is easier
   when every field carries a description — the diff shows whether
   intent changed, not just the type or default.

The bare-assignment pattern gives you none of these. **It is
forbidden** even when the field name appears self-evident — a
`first_name: str = ""` looks obvious to today's reader and
mysterious to next year's reader trying to understand whether
empty string means "not provided" or "explicitly blank."

### Rules

| Situation | Pattern |
|---|---|
| Field with a simple default | `name: str = Field(default="Alice", description="…")` |
| Field with a mutable / computed default | `tags: list[str] = Field(default_factory=list, description="…")` — never `= []`, never `= {}` |
| Required field (no default) | `email: str = Field(..., description="…")` or `email: str = Field(description="…")` |
| Field with `min_length` / `ge` / `pattern` constraint | `count: int = Field(default=0, ge=0, description="…")` — constraints go on `Field`, not on the type annotation |
| Field that may be `None` | `nickname: Optional[str] = Field(default=None, description="…")` — `None` is still a value; declare it explicitly |

### Description writing

| Rule | Detail |
|---|---|
| One short sentence | A line that reads top-down and stops at the period. No bullet points. |
| Present tense, third-person | "Carries the user's preferred timezone." not "Will be carrying…" or "I store…" |
| State **purpose**, not **type** | "Cap on per-LLM-call output tokens for the synthesis node." not "An integer for max tokens." |
| Mention **units** when applicable | "Time-to-live in seconds." |
| Mention **enumeration** when applicable | "One of `'instant'`, `'thinking'`, `'professional'`." |
| Skip the word "The" if the sentence is grammatical without it | "User's primary email." not "The user's primary email." |

### Examples — Before / After

#### Domain DAO field

```python
# Bad — bare default, no documentation
class UserDAO(BaseModel):
    first_name: Optional[str] = None
    is_blocked: Optional[bool] = False
    timezone: Optional[str] = Field(default=TIMEZONE_ASIA_KOLKATA)  # missing description


# Good — every field carries default + description
class UserDAO(BaseModel):
    first_name: Optional[str] = Field(
        default=None,
        description="User's given name; absent until the profile is completed.",
    )
    is_blocked: Optional[bool] = Field(
        default=False,
        description="True when an admin has suspended the account.",
    )
    timezone: Optional[str] = Field(
        default=TIMEZONE_ASIA_KOLKATA,
        description="Olson timezone id used for date display and scheduling.",
    )
```

#### Request body field

```python
# Bad
class QueryRequest(BaseModel):
    content: str = Field(..., min_length=1, description="The user query text")
    agent_speed_mode: str = DEFAULT_AGENT_SPEED_MODE  # no Field, no description


# Good
class QueryRequest(BaseModel):
    content: str = Field(
        ...,
        min_length=1,
        description="User's chat query text. Non-empty.",
    )
    agent_speed_mode: str = Field(
        default=DEFAULT_AGENT_SPEED_MODE,
        description=(
            "One of 'instant', 'thinking', 'professional'. Controls "
            "per-LLM-call token budgets for this single turn."
        ),
    )
```

#### Internal value-holding model

```python
# Bad — bare defaults, no description
class _StreamTracker(BaseModel):
    iteration: int = 0
    phase: str = PHASE_DISCOVERY
    is_medical: bool = True


# Good
class _StreamTracker(BaseModel):
    iteration: int = Field(
        default=0,
        description=(
            "Current iteration number, surfaced by the agent / assess "
            "node. Zero until the first iteration completes."
        ),
    )
    phase: str = Field(
        default=PHASE_DISCOVERY,
        description=(
            "Current search phase. One of PHASE_DISCOVERY / "
            "PHASE_GAP_FILLING / PHASE_VERIFICATION."
        ),
    )
    is_medical: bool = Field(
        default=True,
        description=(
            "Whether the query is medical. Defaults to True until the "
            "classifier proves otherwise."
        ),
    )
```

### What does NOT need `Field(...)`

- **`ClassVar[...]` constants** — Pydantic skips them entirely; they
  are not validated fields.
- **`model_config = ConfigDict(...)`** — Pydantic config, not a
  field.
- **Private attributes prefixed with `_`** — Pydantic v2 does not
  validate them; if you need a private instance attribute, prefer a
  proper field with `Field(default=..., description="…")` and
  consider whether it belongs on the model at all.

### Lint check

A reviewer can verify the convention with a single grep on any
touched DAO file:

```bash
# Returns 0 lines if the rule holds. Any non-zero output is a
# violation: a typed field assigned a bare default without Field().
grep -nE '^\s+[a-z_]+: [A-Za-z\[\], ]+\s*=\s*[^F]' src/domains/**/dao.py
```

(The regex above is approximate; review the matches manually
because legitimate `Field(...)`, `Field(default=...)`,
`Field(default_factory=...)`, and `ClassVar = …` patterns all use
the `=` sign.)

---

## Update Convention — `attrs: Dict[str, Any]` + allow-list

Domain services expose **one** `update(...)` method that takes the persisted row, an `attrs` dictionary of intended changes, and the session. Inside the method, an explicit `updatable_attrs: List[str]` allow-list filters which keys may be written. Anything not on the allow-list is silently ignored — never raised, never written.

```python
@staticmethod
async def update(
    document: Document,
    attrs: Dict[str, Any],
    db_session: AsyncSession,
    autocommit: bool = True,
) -> Document:
    updatable_attrs: List[str] = [
        "slug",
        "title",
        "status",
        "document_type",
        "document_subtype",
        "audio_path",
        "audio_generated_at",
        "updated_at",
    ]
    for key, value in attrs.items():
        if key in updatable_attrs:
            setattr(document, key, value)
    db_session.add(document)
    if autocommit:
        await db_session.commit()
    else:
        await db_session.flush()
    return document
```

**Why:**

- The allow-list is reviewable in one place. Adding a new updatable field is a one-line change visible in code review; nothing is implicit.
- Per-field positional params (`title: Optional[str] = None`, `summary: Optional[str] = None`, ...) bloat the signature, encourage `if x is not None` ladders, and force every caller to know every column name. The `attrs` dict pushes that decision to the caller.
- Updates that should NOT happen here (status transitions, boolean toggles, embedding regeneration) get their own methods (see below) — `update()` becomes a small predictable gateway for the boring writes only.
- Tests that drive the API (router → service) can pass through the request DAO's `model_dump(exclude_unset=True)` directly without re-mapping fields.

---

## State-Transition Convention — `mark_as_<state>()`

When a domain has a `status` column with a state machine (e.g. `UPLOADING → UPLOADED → PROCESSING → PROCESSED|FAILED`), each transition gets its **own** static-async method named `mark_as_<state>()`. **Never** ship a generic `transition_status(to_status=X)` / `update_status(new_status=X)` / `set_state(state=X)`.

```python
@staticmethod
async def mark_as_processed(
    reference_document: ReferenceDocument,
    db_session: AsyncSession,
    autocommit: bool = True,
) -> ReferenceDocument:
    """Move the row from PROCESSING -> PROCESSED.

    Side effects: flips ``is_available=True`` and stamps
    ``processing_completed_at``.

    Raises:
        InvalidStatusTransitionError: when the row is not currently in
            PROCESSING.
    """
    if reference_document.status != STATUS_PROCESSING:
        raise InvalidStatusTransitionError(
            f"mark_as_processed requires current status PROCESSING, "
            f"got {reference_document.status!r}"
        )

    reference_document.status = STATUS_PROCESSED
    reference_document.is_available = True
    reference_document.processing_completed_at = utc_now()
    db_session.add(reference_document)
    if autocommit:
        await db_session.commit()
    else:
        await db_session.flush()
    return reference_document
```

**Why:**

- Reading `await ReferenceDocumentService.mark_as_processed(row, session)` tells the reader exactly what happens — no need to look up which constant maps to which side effects.
- Each method's guard clause is the natural home for "what state must the row be in before this transition fires". `transition_status(to_status="PROCESSED")` either has to look up the rule in a separate dict (cleverness over clarity) or accept any source state (silent corruption).
- Side effects (timestamp stamping, flag flipping) live next to the transition that triggers them, not in a switch on `to_status`.
- Tests read as a sentence: `await svc.mark_as_failed(row, session)` is self-documenting.

---

## Boolean-Toggle Convention — `toggle_<field_name>()`

Boolean columns like `is_active`, `is_allowed`, `is_blocked`, `is_verified` get their own `toggle_<field_name>()` method. **Never** flip booleans via `update()` or via a generic `set_flag(name=..., value=...)`.

```python
@staticmethod
async def toggle_is_allowed(
    reference_document: ReferenceDocument,
    db_session: AsyncSession,
    value: Optional[bool] = None,
    autocommit: bool = True,
) -> ReferenceDocument:
    """Toggle ``is_allowed`` on the row.

    When ``value`` is ``None`` the current state is flipped; when
    supplied, the column is set to that value.

    Args:
        reference_document: The row to mutate.
        db_session: The async database session.
        value: Optional explicit boolean. ``None`` flips the current
            value.
        autocommit: When ``True`` (default), commit; when ``False``,
            ``flush`` only.
    """
    new_value: bool = (
        not reference_document.is_allowed if value is None else value
    )
    reference_document.is_allowed = new_value
    db_session.add(reference_document)
    if autocommit:
        await db_session.commit()
    else:
        await db_session.flush()
    return reference_document
```

If the toggle needs a guard (e.g. "cannot allow a row that is_available=False"), the guard lives at the top of this method.

**Why:** same family of arguments as state transitions — clarity over cleverness, side effects co-located with the trigger, tests that read as English.

---

## Validation Convention — Pydantic DAO `@field_validator`s

Validation against allow-lists, regex patterns, range checks, structural shape — **always** in the DAO via `@field_validator` (or `model_validator` for cross-field rules). The service layer does NOT carry imperative `_require_*` / `_validate_*` static methods that re-implement what Pydantic gives you for free.

```python
# bad — service-layer imperative validation
class ReferenceDocumentService:
    @staticmethod
    async def build(category: str, ...) -> ReferenceDocumentDAO:
        ReferenceDocumentService._require_known_category(category=category)
        ReferenceDocumentService._require_known_status(status=status)
        return ReferenceDocumentDAO(category=category, ...)

    @staticmethod
    def _require_known_category(category: str) -> None:
        if category not in ALLOWED_CATEGORIES:
            raise InvalidCategoryError(...)
```

```python
# good — validation lives in the DAO
class ReferenceDocumentDAO(BaseModel):
    reference_document_category: str
    status: str

    @field_validator("reference_document_category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        if value not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"reference_document_category {value!r} not in {sorted(ALLOWED_CATEGORIES)!r}"
            )
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in ALLOWED_STATUSES:
            raise ValueError(f"status {value!r} not in {sorted(ALLOWED_STATUSES)!r}")
        return value


class ReferenceDocumentService:
    @staticmethod
    async def build(category: str, ...) -> ReferenceDocumentDAO:
        return ReferenceDocumentDAO(category=category, ...)
```

**Why:**

- Pydantic's `ValidationError` integrates with FastAPI — the controller automatically returns 422 with structured error detail. Custom typed exceptions (`InvalidCategoryError`) require manual handler wiring.
- The DAO is the single source of truth for the field's contract. Constructing the DAO anywhere — from the router, from tests, from a script — runs the same validation.
- Service code becomes data-shaped: take args, build DAO, persist, return. No imperative validation prologue.
- For optional fields (e.g. classification fields that the indexing pipeline populates later), the validator early-returns on `None` and only checks supplied values.

```python
@field_validator("reference_document_classification")
@classmethod
def _validate_classification(cls, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in ALLOWED_CLASSIFICATIONS:
        raise ValueError(
            f"reference_document_classification {value!r} not in the medical-taxonomy allow-list"
        )
    return value
```

Cross-field rules (e.g. "if `is_available=True` then `processing_completed_at` must be set") use `@model_validator(mode="after")`. State-machine transitions are NOT cross-field rules — they are temporal and live in `mark_as_<state>()` methods (see above).

Here is how the unit tests for the domain would like. 

> **Note**
This example uses synchronous SQLAlchemy. Your application may be using the async version. You should use the relevant database connection or session objects. 


```python
import pytest
from tests.db import db_session
from sqlalchemy.orm.session import Session


class TestSystemEventService:
    @pytest.mark.asyncio
    async def test_create(self, db_session: Session):
        from bushido.models import models
        from bushido.domains.user.dao import UserDAO
        from bushido.domains.weight_log.dao import WeightLogDAO
        from bushido.domains.weight_log.event import WeightLoggedEventDAO
        from bushido.domains.product.product_dao import ProductDAO
        from bushido.domains.personal_attributes.dao import PersonalAttributesDAO
        from bushido.domains.system_event.service import SystemEventsService
        from decimal import Decimal
        from uuid import uuid4

        user = UserDAO(
            id=uuid4(),
            phone_number="9920837799",
            first_name="first_name",
            last_name="last_name",
        )
        weight_log = WeightLogDAO(
            product_id=uuid4(), user_id=user.id, weight_in_kgs=Decimal("76.10")
        )
        personal_attributes = PersonalAttributesDAO(
            id=uuid4(), user_id=user.id, gender="male", weight_in_kgs=Decimal("72.80")
        )

        product = ProductDAO(
            id="0fb6a4d4-ae65-4f18-be44-edb9ace6b5bb", name="alphacoach-fit"
        )
        weight_log_event = WeightLoggedEventDAO(
            user=user,
            weight_log=weight_log,
            product=product,
            personal_attributes=personal_attributes,
        )
        system_event = await SystemEventsService.create(
            event_dao=weight_log_event, db_session=db_session
        )
        assert system_event.id is not None
        assert system_event.time is not None
        assert system_event.payload.get("user") is not None
        assert system_event.payload.get("personal_attributes") is not None
        assert system_event.payload.get("weight_log") is not None
        assert system_event.payload.get("product") is not None
```

Here is an example of unit tests for the original user domain that started the series of examples

> **Note**
This example uses async database sessions. 

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

    @pytest.mark.asyncio
    async def test_get(self, async_db_session: AsyncSession):
        from src.domains.user.service import UserService, User

        user: User = await UserService.build_and_create(
            email="ada.lovelace@example.com",
            db_session=async_db_session,
            password="password",
            first_name="Ada",
            last_name="Lovelace",
        )
        user = await UserService.get(id=int(user.id), db_session=async_db_session)
        assert user is not None

    @pytest.mark.asyncio
    async def test_update(self, async_db_session: AsyncSession):
        from src.domains.user.service import UserService, User

        user: User = await UserService.build_and_create(
            email="ada.lovelace@example.com",
            db_session=async_db_session,
            password="password",
            first_name="Ada",
            last_name="Lovelace",
        )
        user = await UserService.get(id=int(user.id), db_session=async_db_session)
        assert user is not None

        updated_user: User = await UserService.update(
            user=user,
            attrs={
                "first_name": "Grace",
                "last_name": "Hopper",
                "email": "grace.hopper@example.com",
                "is_blocked": False,
            },
            db_session=async_db_session,
        )  # type: ignore

        assert updated_user.id is not None
        assert updated_user.email == "grace.hopper@example.com"
        assert updated_user.first_name == "Grace"
        assert updated_user.last_name == "Hopper"
        assert updated_user.timezone == "Asia/Kolkata"
        assert updated_user.is_blocked is False
        assert updated_user.verified_at is None
        assert updated_user.user_metadata == {}
        assert updated_user.created_at is not None
        assert updated_user.encrypted_password is not None
        assert updated_user.updated_at is not None
```
