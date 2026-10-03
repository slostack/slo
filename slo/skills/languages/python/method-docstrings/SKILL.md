---
name: method-docstrings
description: 'Python: Google-style docstrings on every method and function.'
when_to_use: For Python projects only. Apply whenever defining or revising a method/function.
group: languages
kind: skill
source_prompt: method-docstrings.md
---

# Method Docstrings

## Skill summary

- **Name:** `method-docstrings`
- **Description:** Google-style docstrings on every method and function.
- **When to use:** Apply whenever defining or revising a method/function.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `method-docstrings.md`

## Examples

- The user asks for help with: Google-style docstrings on every method and function.
- Apply whenever defining or revising a method/function.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

All methods must be documented using the Google docstring style. This applies to every `def` and `async def` in `service.py`, `dao.py`, `client.py`, `rpc.py`, application services, workers, and event handlers.

---

## Rich Docs: WHAT, WHO, WHEN

A documentation comment earns its place by answering three questions the signature cannot:

- **WHAT** the function does — the observable behaviour, not the implementation.
- **WHO** calls it — the caller(s) or layer that invokes it, especially for non-obvious entry points (a worker, an RPC handler, a producer/consumer pair, a lifecycle hook).
- **WHEN** in the flow it runs — its place in the sequence (e.g. "after the session is admitted", "on every reconnect", "spawned once at startup").

Clarity over cleverness applies to prose as much as to names: describe the behaviour plainly rather than gesturing at it. This standard pairs with the `naming-and-clarity` skill (`skills/coding/naming-and-clarity/SKILL.md`) — a self-describing name plus a WHAT/WHO/WHEN comment means the reader never has to reverse-engineer the body.

```python
async def consume_relay_data_frames(self) -> None:
    """Read relay data frames off the persistent connection and hand them to the demux queue.

    WHAT: Loops reading length-prefixed frames from the relay socket until the
        connection closes, decoding each into a RelayDataFrame.
    WHO: Started once by the transport layer's start_relay() after a session is admitted;
        it is the consumer half of the publish_relay_data_frames / consume_relay_data_frames pair.
    WHEN: Runs for the lifetime of the session, after admission and before teardown.

    Raises:
        RelayConnectionClosedError: If the peer closes the connection mid-frame.
    """
```

The `Args` / `Returns` / `Raises` blocks below remain mandatory where applicable; WHAT/WHO/WHEN is the narrative that precedes them for any function whose caller or timing is not obvious from the signature.

---

## Rich Docs Extend to Data Flow and Lifetime

Every function carries a rich doc comment stating WHAT it does, WHO calls it, the DATA FLOW it participates in, and its LIFETIME/teardown. For a long-running loop, a producer/consumer half, or a spawned goroutine, WHO and WHEN are not enough on their own — the reader also needs to know *which channel/stream the data moves along* and *when the function stops and how it is torn down*.

- **DATA FLOW** — name the channel, stream, queue, or connection the function reads from or writes to, and its partner on the other side (e.g. "reads frames off the relay socket and hands them to the demux queue that `publish_relay_data_frames` drains").
- **LIFETIME/teardown** — say when the function is spawned, how long it runs, and what closes it (e.g. "spawned once at startup; runs until the session is torn down; exits when the connection closes").

Clarity over cleverness applies here too: a self-describing name (see the naming vocabulary in `skills/design-and-analysis/ubiquitous-language/SKILL.md` — `publish…` / `consume…` pairs, `build…` vs `start…`) plus a WHAT/WHO/DATA-FLOW/LIFETIME comment means the reader never has to reverse-engineer the body to learn how the piece is wired or when it dies.

---

## Format

```python
async def method_name(self, param_one: Type, param_two: Type) -> ReturnType:
    """One-line summary ending with a period.

    Optional: one or two sentences of additional context if the summary
    is not sufficient on its own.

    Args:
        param_one (Type): Description of the parameter.
        param_two (Type, optional): Description. Defaults to <value>.

    Returns:
        ReturnType: Description of what is returned.

    Raises:
        ExceptionType: Condition that triggers this exception.
    """
```

Rules:
- The first line is a short imperative summary ending with a period — no blank line before it
- A blank line separates the summary from `Args`
- `Args`, `Returns`, and `Raises` are present only when applicable — omit sections that do not apply
- Parameter type in parentheses matches the type annotation exactly
- Optional parameters are marked `(Type, optional)` and include `Defaults to <value>`
- `Returns` describes the value, not just the type — say what it represents
- `Raises` lists every exception the caller must handle

---

## Examples

### Domain `service.py`

```python
@staticmethod
async def create(user_dao: UserDAO, db_session: AsyncSession, autocommit: bool = True) -> User:
    """Create a new user in the database.

    Args:
        user_dao (UserDAO): The data access object containing user information.
        db_session (AsyncSession): The database session.
        autocommit (bool, optional): Whether to commit the transaction automatically. Defaults to True.

    Returns:
        User: The created user object.
    """

@staticmethod
async def get(id: int, db_session: AsyncSession) -> Optional[User]:
    """Fetch a user by primary key.

    Args:
        id (int): The user's primary key.
        db_session (AsyncSession): The database session.

    Returns:
        Optional[User]: The user if found, None otherwise.
    """

@staticmethod
async def update(user: User, updates: UserDAO, db_session: AsyncSession) -> User:
    """Apply field updates to an existing user and persist them.

    Args:
        user (User): The SQLAlchemy model instance to update.
        updates (UserDAO): DAO containing the fields and values to apply.
        db_session (AsyncSession): The database session.

    Returns:
        User: The updated user object.
    """
```

### Application Service (`invoke()` and private steps)

```python
async def invoke(self) -> MakePaymentResponsePayloadDAO:
    """Execute the payment flow end-to-end.

    Loads account, vendor, customer, and debt details, then delegates
    each payment item to the vendor integration layer.

    Returns:
        MakePaymentResponsePayloadDAO: Consolidated results for all payment items.

    Raises:
        ConciergeRequestHandlerNotFoundException: If the account or vendor is not found.
        ConciergeRequestHandlerBadRequestException: If the vendor is not first-party.
    """

async def _fetch_and_validate_account(self) -> None:
    """Load the account by ID and store it on self.account.

    Raises:
        ConciergeRequestHandlerNotFoundException: If no account exists for self.account_id.
    """
```

### API Client (`client.py`)

```python
async def make_request(
    self,
    method: str,
    path: str,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an authenticated HTTP request to the vendor API.

    Args:
        method (str): HTTP method — one of METHOD_GET, METHOD_POST, METHOD_PUT, METHOD_DELETE.
        path (str): API endpoint path, appended to self.base_url.
        headers (Dict[str, Any], optional): Additional request headers. Defaults to None.
        params (Dict[str, Any], optional): URL query parameters. Defaults to None.
        payload (Dict[str, Any], optional): JSON request body. Defaults to None.

    Returns:
        Dict[str, Any]: Parsed JSON response body.

    Raises:
        ValueError: If the base URL is not configured.
        PartnerApiError: If the vendor returns a non-2xx response.
    """

async def phone_pin_challenge(self, request: PhonePinChallengeRequestDAO) -> PhonePinChallengeResponseDAO:
    """Initiate the phone PIN challenge flow with the fulfillment partner API.

    Args:
        request (PhonePinChallengeRequestDAO): Phone number, conversation ID, and retry count.

    Returns:
        PhonePinChallengeResponseDAO: Opaque challenge identifiers to be stored and
            passed back in the subsequent verify_pin call.

    Raises:
        PartnerApiError: If the fulfillment partner API rejects the challenge request.
    """
```

### RPC Method (`rpc.py`)

```python
async def start_verification(
    phone_number: str,
    conversation_id: str,
    pin_request_count: int = 0,
) -> dict:
    """Initiate the vendor's phone PIN challenge.

    Args:
        phone_number (str): Customer phone number in E.164 format.
        conversation_id (str): Unique call identifier used as the vendor conversation ID.
        pin_request_count (int, optional): Number of prior PIN requests in this session. Defaults to 0.

    Returns:
        dict: Opaque verification args (challenge_ari, session_ari, attempt_id,
            requirement_id) to be stored and returned in complete_verification.

    Raises:
        AuthenticationFailedError: If the vendor rejects the challenge initiation.
    """
```

### Celery Worker

```python
async def partner_fetch_payment_instrument_worker_async(
    account_id: int,
    loan_id: str,
    vendor_id: int,
    verified_session_request_id: str,
) -> bool:
    """Fetch fulfillment partner payment instruments for a loan and persist them.

    Loads the verified session, calls VendorRpcGateway.get_payment_instruments(),
    stores the result in line_item and mapped_order, and emits
    PartnerPaymentInstrumentFetchedEvent.

    Args:
        account_id (int): The order ID.
        loan_id (str): The vendor-side loan identifier.
        vendor_id (int): The partner ID.
        verified_session_request_id (str): UUID of the active VerifiedSessionRequest
            used to retrieve the session token.

    Returns:
        bool: True on success.
    """
```

---

## Class Docstrings

Class-level docstrings describe what the class represents, not how to use it. One or two sentences is sufficient.

```python
class PartnerVerificationApiClient:
    """HTTP client for the fulfillment partner's authentication and PIN verification endpoints."""


class MakePaymentAppService:
    """Application service to process mid-call payments for a fulfillment partner order."""


class PartnerVerificationService:
    """Orchestrates the fulfillment partner phone PIN challenge and verification flow."""
```

---

## When to Omit Docstrings

Skip the docstring only when the method name and type annotations together make the intent unambiguous to any reader:

```python
# Acceptable — name, types, and return type are self-explanatory
@staticmethod
def is_active(user: User) -> bool:
    return user.is_active

# Acceptable — single-line property
@property
def full_name(self) -> str:
    return f"{self.first_name} {self.last_name}"
```

If there is any ambiguity — non-obvious defaults, domain-specific side effects, exception conditions — write the docstring.

---

## What NOT to Write

```python
# Bad — restates the signature, adds no information
async def create(self, user_dao: UserDAO) -> User:
    """Creates a user."""

# Bad — describes implementation, not behaviour
async def get_session_token(self, account_id: int) -> str:
    """Queries the verified_session_request table and returns the token field."""

# Good — describes what it means and when it raises
async def get_session_token(self, account_id: int) -> str:
    """Return the active session token for the most recent succeeded verification.

    Args:
        account_id (int): The order ID.

    Returns:
        str: The raw session token string from verification_response.

    Raises:
        ConciergeRequestHandlerBadRequestException: If no succeeded session exists
            for this account, meaning verification must be re-initiated.
    """
```
