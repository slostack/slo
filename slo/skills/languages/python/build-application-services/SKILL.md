---
name: build-application-services
description: 'Python: Building orchestration logic — the invoke() pattern, router → service → domain control
  flow.'
when_to_use: For Python projects only. Use when adding a new application service (one operation per service,
  declarative invoke method).
group: languages
kind: skill
source_prompt: build-application-services.md
---

# Build Application Services

## Skill summary

- **Name:** `build-application-services`
- **Description:** Building orchestration logic — the invoke() pattern, router → service → domain control flow.
- **When to use:** Use when adding a new application service (one operation per service, declarative invoke method).
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-application-services.md`

## Examples

- The user asks: "Add or revise the application services for this feature."
- You want the canonical build pattern before touching application services.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

Application services contain the meat of the application logic. THe control flow is usually from a router -> application service -> domain service or worker -> application service -> domain service. 

1. An application service is built for a specific workflow. And is placed under the `src/services` folder

2. For instance all code relating to the user creation would be under `src/services/users`. 

3. Each file is suffixed with `_app_service`. For example `src/services/users/create_app_service.py`

4. Application services are always declarative and respond to the `invoke` method which acts as the gateway to the application service after initialization. THe invoking service usually does the following to invoke them. 

```python
 svc: ApplicationService = ApplicationServiceName()
 await svc.invoke() 
```

---

## Mandatory Rules

### `invoke()` is NON-NEGOTIABLE

Every application service (`_app_service.py`) MUST expose a single `invoke()` method as the entry point. The `invoke()` method orchestrates the workflow by calling private declarative methods in sequence:

```python
async def invoke(self) -> ReturnType:
    await self._step_one()
    await self._step_two()
    await self._step_three()
    return self.result
```

- Each private method performs exactly one step — no conditional branching in `invoke()`.
- Early exits are handled via **exceptions**, not conditional returns in the caller.
- The controller calls `invoke()` and handles the result. Controllers NEVER orchestrate multi-step workflows themselves.

### Application Services vs Repository Services

| Type | Suffix | Has `invoke()`? | Purpose |
|---|---|---|---|
| **Application Service** | `_app_service.py` | **YES** — mandatory | Orchestrates a workflow end-to-end via `invoke()` |
| **Repository Service** | `_repo_service.py` | **NO** | Provides utility/coordination methods that cannot live in a domain service (e.g., cross-domain reads, DBOS enqueuing). Consumed by application services as dependencies. |

**When to use each:**
- If the service represents a **workflow** (load → transform → persist → notify), it is an **application service** with `invoke()`.
- If the service provides **reusable utility methods** that are called at different points by an app service (e.g., `load_conversation_messages()`, `enqueue_persist_message()`), it is a **repository service** with individual public methods.

### Controllers MUST NOT contain application logic

Controllers are thin routing layers. They:
1. Parse the request
2. Instantiate the application service
3. Call `invoke()`
4. Return the response

Controllers MUST NOT:
- Build async generators
- Massage data (convert DAOs to dicts, accumulate responses)
- Orchestrate multi-step flows (load context → enqueue → stream → enqueue again)
- Contain business logic conditionals

All of that belongs in the application service.

### Domain naming — never alias domain entities

When a service loads messages, the DAO should be named after the domain entity — `MessageContextDAO`, not `ConversationContextItemDAO`. Never invent new names for existing domain concepts. Messages are messages, conversations are conversations.

---

Here is a sample application service for signups under `src/services/signup/signup_app_service.py`

```python
from typing import Optional, Type, Dict
from src.domains.email.templates import SIGNUP_BODY_TEMPLATE, SIGNUP_TITLE
from src.domains.email.service import EmailService
from config.logger import log_error, log_info
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.signup.dao import SignupDAO
from src.domains.user.service import UserService, User
from src.domains.verifications.service import VerificationService, Verification
from src.exceptions import ApiException
from src.domains.verifications.dao import (
    DEFAULT_EXPIRES_AT_IN_MINUTES,
    VERIFICATION_TYPES,
)
from string import Template
from config.cfg import cfg


class SignupAppService:
    def __init__(
        self,
        params: SignupDAO,
        db_session: AsyncSession,
        user_service: Optional[Type[UserService]] = None,
        verification_service: Optional[Type[VerificationService]] = None,
        email_service: Optional[Type[EmailService]] = None,
    ):
        self.db_session: AsyncSession = db_session
        self.password: str = params.password
        self.email: str = params.email
        self.first_name: Optional[str] = params.first_name
        self.last_name: Optional[str] = params.last_name
        self.user: Optional[User] = None
        self.user_service: Type[UserService] = user_service or UserService
        self.verification: Optional[Verification] = None
        self.verification_service: Type[VerificationService] = (
            verification_service or VerificationService
        )
        self.verification_type: str = VERIFICATION_TYPES["SIGNUP"]
        self.email_service: Type[EmailService] = email_service or EmailService

    async def invoke(self) -> User:
        await self._create_user()
        await self._generate_verification()
        await self._send_verification_email()
        await self._trigger_event()
        return self.user

    async def _create_user(self) -> User:
        try:
            log_info(
                msg="Creating user record.", loc=f"{__file__}", method="_create_user"
            )
            self.user: User = await self.user_service.build_and_create(
                email=self.email,
                first_name=self.first_name,
                last_name=self.last_name,
                password=self.password,
                db_session=self.db_session,
            )
        except Exception as e:
            log_error(
                msg=f"Error creating user: {e}",
                loc=f"{__file__}",
                method="_create_user",
            )
            raise ApiException(
                msg=f"Error creating user: {e}",
                code="user_creation_error",
                http_error_code=500,
            )
        return self

    async def _generate_verification(self) -> Verification:
        log_info(
            msg="Generating signup verification code",
            loc=f"{__file__}",
            method="_generate_verification",
        )
        try:
            self.verification: Verification = (
                await self.verification_service.build_and_create(
                    user_id=self.user.id,
                    verification_type=self.verification_type,
                    db_session=self.db_session,
                )
            )
        except Exception as e:
            log_error(
                msg=f"Error generating verification code: {e}",
                loc=f"{__file__}",
                method="_generate_verification",
            )
            raise ApiException(
                msg=f"Error generating verification code: {e}",
                code="verification_code_generation_error",
                http_error_code=500,
            )
        return self

    async def _send_verification_email(self):
        log_info(
            msg="Preparing to send email to user",
            loc=f"{__file__}",
            method="_send_verification_email",
        )
        try:
            user_email: str = self.user.email
            user_name: str = self.user.first_name or user_email
            app_name: str = cfg("APP_NAME")
            domain: str = cfg("FRONTEND_DOMAIN_NAME")
            token: str = self.verification.token
            protocol: str = "https" if cfg("ENV") in ["prod"] else "http"

            self.email_response: Dict = await self.email_service.send_email(
                to_addresses=[{"address": user_email, "name": user_name}],
                subject=Template(SIGNUP_TITLE).substitute({"app_name": app_name}),
                html_body=Template(SIGNUP_BODY_TEMPLATE).substitute(
                    {
                        "app_name": app_name,
                        "user_name": user_name,
                        "verification_link": f"{protocol}://{domain}/signup_verification/{token}",
                        "expiration_time": DEFAULT_EXPIRES_AT_IN_MINUTES,
                    }
                ),
            )
            log_info(
                msg=f"Email sent successfully, email provider API response: {self.email_response}",
                loc=f"{__file__}",
                method="_send_verification_email",
            )
        except Exception as e:
            log_error(
                msg=f"Error sending email: {e}",
                loc=f"{__file__}",
                method="_send_verification_email",
            )
            raise ApiException(
                msg=f"Error sending email: {e}",
                code="email_send_error",
                http_error_code=500,
            )
        return self

    async def _trigger_event(self) -> None: 
        # truncated for brevity
```


And the corresponding test file for this would look like under `tests/services/signup/test_signup_app_service.py`

- Follow `skills/coding/test-verification-policy/SKILL.md`: real `async_db_session`, real domain services, persisted state read back.
- `EmailService` wraps the third-party email provider, so it is the client boundary. Replace it with a hand-written `RecordingEmailService` passed through the `email_service=` constructor parameter. No `AsyncMock`, no `patch`.

```python
from string import Template

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from config.cfg import cfg
from src.domains.email.templates import SIGNUP_BODY_TEMPLATE, SIGNUP_TITLE
from src.domains.user.service import User, UserService
from src.domains.verifications.dao import DEFAULT_EXPIRES_AT_IN_MINUTES, VERIFICATION_TYPES
from src.domains.verifications.service import Verification, VerificationService
from src.services.signup.dao import SignupDAO
from src.services.signup.signup_app_service import SignupAppService


class RecordingEmailService:
    """Third-party boundary stub: records every email instead of calling the provider."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_email(self, *, to_addresses: list[dict[str, str]], subject: str, html_body: str) -> dict[str, str]:
        """Record the email and return a canned provider response."""
        self.sent.append({"to_addresses": to_addresses, "subject": subject, "html_body": html_body})
        return {"status": "queued"}


class TestSignupAppService:
    @pytest.mark.asyncio
    async def test_invoke_persists_user_and_verification_and_sends_email_when_params_are_valid(
        self, async_db_session: AsyncSession
    ) -> None:
        """Valid signup persists a user and a signup verification, then emails the verification link."""
        signup_params: SignupDAO = SignupDAO(
            db_session=async_db_session,
            email="ada.lovelace@example.com",
            password="password",
            password_confirmation="password",
            first_name="ada",
            last_name="lovelace",
        )
        email_service: RecordingEmailService = RecordingEmailService()

        await SignupAppService(
            params=signup_params,
            db_session=async_db_session,
            email_service=email_service,
        ).invoke()

        # Then the user and verification can be read back through the domain services
        user: User = await UserService.get_by_email(email="ada.lovelace@example.com", db_session=async_db_session)
        assert (user.first_name, user.last_name) == ("ada", "lovelace")
        verification: Verification = await VerificationService.get_by_user_id(
            user_id=user.id, db_session=async_db_session
        )
        assert verification.verification_type == VERIFICATION_TYPES["SIGNUP"]

        # And exactly one email carrying the persisted token reached the provider boundary
        protocol: str = "https" if cfg("ENV") in ["prod"] else "http"
        assert email_service.sent == [
            {
                "to_addresses": [{"address": user.email, "name": user.first_name}],
                "subject": Template(SIGNUP_TITLE).substitute({"app_name": cfg("APP_NAME")}),
                "html_body": Template(SIGNUP_BODY_TEMPLATE).substitute(
                    {
                        "app_name": cfg("APP_NAME"),
                        "user_name": user.first_name,
                        "verification_link": f"{protocol}://{cfg('FRONTEND_DOMAIN_NAME')}/signup_verification/{verification.token}",
                        "expiration_time": DEFAULT_EXPIRES_AT_IN_MINUTES,
                    }
                ),
            }
        ]
```

### Triggering Events
Events are triggered to denote key facts in the system usually associated with a critical state change. These events are domain specific and here is an example
from a different code base to illustrate this


```python
from typing import List, Union
from config import log_info, log_error
from sqlalchemy.orm.session import Session
from bushido.domains.user.dao import UserDAO
from bushido.services.base import ServiceBase
from bushido.domains.body_type_logs.service import BodyTypeLogService
from bushido.domains.body_type_logs.dao import BodyTypeLogDAO
from bushido.domains.body_type_logs.model import BodyTypeLog
from bushido.domains.body_type_logs.event import (
    BodyTypeLoggedEventDAO,
    BodyTypeLoggingFailedEvent,
)
from bushido.domains.system_event.service import SystemEventsService
from bushido.domains.user.model import User
from bushido.domains.product.product_dao import ProductDAO
from pydantic.error_wrappers import ValidationError
from bushido.domains.lifestyle_attributes.service import LifestyleAttributesService

ERROR_CREATING_BODY_TYPE_LOG = "Error creating Body type log."
ERROR_USER_NOT_FOUND = "Invalid user"
ERROR_INVALID_PRODUCT = "Invalid product"


class BodyTypeLogAppService(ServiceBase):
    def __init__(
        self,
        user: User,
        product: ProductDAO,
        body_fat_percentage: str,
        db_session: Session = None,
    ):
        self.user = user
        self.product = product
        self.body_fat_percentage = body_fat_percentage
        self.db_session = db_session
        self.errors: List[str] = []
        self.error_code: Union[str, None] = None
        self.http_error_code: Union[int, None] = None
        self.body_type_log: Union[BodyTypeLog, None] = None

    async def __call__(self):
        return await self.invoke()

    async def invoke(self):
        await self.check_user()
        await self.check_product()
        await self.create_body_type_log()
        await self.update_lifestyle_attributes()
        await self.to_dao()
        await self.trigger_event()
        if await self.has_errors:
            user_id = self.user.id if self.user and self.user.id else ""
            log_error(
                msg=f"BodyTypeLog Failed for user_id: {user_id}",
                method="invoke",
                loc=f"{__name__}",
            )
        else:
            log_info(
                msg=f"BodyTypeLog Success for user_id: {self.user.id}",
                method="invoke",
                loc=f"{__name__}",
            )
        return self

    async def check_user(self):
        if await self.has_errors:
            return self

        if not (self.user and self.user.id):
            self.errors.append(ERROR_USER_NOT_FOUND)
            self.error_code = "bad_request"
            self.http_error_code = 400
            return self
        return self

    async def check_product(self):
        if await self.has_errors:
            return self

        if not (self.product and self.product.id):
            self.errors.append(ERROR_INVALID_PRODUCT)
            self.error_code = "bad_request"
            self.http_error_code = 400
            return self
        return self

    async def create_body_type_log(self):
        if await self.has_errors:
            return self

        try:
            self.body_type_log = await BodyTypeLogService.build_and_create(
                user_id=self.user.id,
                body_fat_percentage=self.body_fat_percentage,
                product_id=self.product.id,
                db_session=self.db_session,
            )
        except (ValidationError, ValueError) as e:
            self.errors.append(ERROR_CREATING_BODY_TYPE_LOG)
            self.error_code = "bad_request"
            self.http_error_code = 400
            return self
        return self

    async def update_lifestyle_attributes(self):
        if await self.has_errors:
            return self

        update_status = await LifestyleAttributesService.update_from_attributes(
            db_session=self.db_session,
            user_id=str(self.user.id),
            attributes={
                "body_type_log_id": str(self.body_type_log.id),
                "body_fat_percentage": str(self.body_fat_percentage),
            },
        )

        if not update_status:
            log_error(
                msg=f"Unable to update lifestyle attributes for {self.user.id}",
                loc=f"{__name__}",
                method="update_lifestyle_attributes",
            )
        return self

    async def to_dao(self):
        if await self.has_errors:
            return self

        self.body_type_log_dao = BodyTypeLogDAO.from_orm(self.body_type_log)
        return self

    async def trigger_event(self):
        user_dao = UserDAO.from_orm(self.user) if self.user and self.user.id else None
        body_type_log_dao = (
            BodyTypeLogDAO.from_orm(self.body_type_log) if self.body_type_log else None
        )

        if await self.has_errors:
            event_dao = BodyTypeLoggingFailedEvent(
                user=user_dao,
                product=self.product,
                body_type_log=body_type_log_dao,
            )
        else:
            event_dao = BodyTypeLoggedEventDAO(
                user=user_dao,
                product=self.product,
                body_type_log=self.body_type_log_dao,
            )
        partition_key = (
            str(user_dao.id)
            if self.user and self.user.id
            else "BodyTypeLoggingFailedEvent"
        )
        await SystemEventsService.trigger(
            partition_key=partition_key, event_dao=event_dao, db_session=self.db_session
        )
        return self
```

The partition key is the key based on which the events are ordered.
