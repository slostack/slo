---
name: auth-security-patterns
description: Mandatory security rules for password hashing (bcrypt + SHA-256 pre-hash)
  and JWT session design (session_id only, never user identity in token).
when_to_use: Use when writing or reviewing any authentication, credential storage,
  session management, or JWT-related code.
group: coding
kind: skill
source_prompt: auth-security-patterns.md
---

# Auth Security Patterns

## Skill summary

- **Name:** `auth-security-patterns`
- **Description:** Mandatory security rules for password hashing (bcrypt + SHA-256 pre-hash) and JWT session design (session_id only, never user identity in token).
- **When to use:** Use when writing or reviewing any authentication, credential storage, session management, or JWT-related code.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `auth-security-patterns.md`

## Examples

- The user asks: "Add password hashing to the user signup flow."
- The user asks: "Implement login and return a JWT."
- The user asks: "How should we structure JWT tokens for this service?"
- The user asks: "Add a logout endpoint."
- You are reviewing auth code and need the canonical patterns before commenting.

## Guidance

Two mandatory security rules derived from code review. Apply both whenever
authentication or credential storage is involved.

---

## Rule 1 — Password Hashing: bcrypt with SHA-256 pre-hash

Always use **bcrypt** with a **SHA-256 pre-hash**. Never use PBKDF2,
MD5, SHA alone, or reversible encoding. Never store raw passwords.

### The 72-byte truncation problem

bcrypt truncates its input at **72 bytes by design**. A plaintext password
longer than 72 bytes is silently treated as its first 72 bytes only. Two
different passwords sharing the same first 72 bytes would hash identically.

**Fix:** SHA-256 hash the plaintext first (always 32 bytes, always under the
limit). bcrypt still provides all its cost-factor hardness.

### Required pattern

```python
import base64
import hashlib
import bcrypt


def _pre_hash(plain: str) -> bytes:
    """SHA-256 hash then base64-encode plaintext to avoid bcrypt 72-byte truncation."""
    digest: bytes = hashlib.sha256(plain.encode()).digest()
    return base64.b64encode(digest)


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt (work factor 12)."""
    pre_hashed: bytes = _pre_hash(plain=plain)
    salt: bytes = bcrypt.gensalt(rounds=12)
    hashed: bytes = bcrypt.hashpw(password=pre_hashed, salt=salt)
    return hashed.decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    pre_hashed: bytes = _pre_hash(plain=plain)
    return bcrypt.checkpw(
        password=pre_hashed,
        hashed_password=hashed.encode(),
    )
```

### Rules table

| Rule | Detail |
|---|---|
| Algorithm | bcrypt only. No PBKDF2, MD5, SHA-alone |
| Pre-hash | `base64.b64encode(hashlib.sha256(plain.encode()).digest())` before `bcrypt.hashpw` |
| Work factor | `bcrypt.gensalt(rounds=12)` — never lower in production |
| Verification | `bcrypt.checkpw` always — never `==` comparison (not timing-safe) |
| Storage | Store the bcrypt hash string only — never plaintext, never an intermediate encoding |

### Bad / Good

```python
# ❌ Bad — no pre-hash, vulnerable to 72-byte truncation
hashed = bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12))

# ❌ Bad — wrong algorithm
hashed = hashlib.sha256(plain.encode()).hexdigest()

# ❌ Bad — reversible encoding, not a hash
stored = base64.b64encode(plain.encode()).decode()

# ✅ Good — SHA-256 pre-hash then bcrypt, checkpw for verification
pre_hashed = base64.b64encode(hashlib.sha256(plain.encode()).digest())
hashed = bcrypt.hashpw(password=pre_hashed, salt=bcrypt.gensalt(rounds=12))
is_valid = bcrypt.checkpw(password=pre_hashed, hashed_password=stored_hash)
```

---

## Rule 2 — JWT Session Design: session_id only, never user identity

Never put `user_id`, `email`, `username`, or any identity field in a JWT
payload. Store a `session_id` (UUID) instead. Resolve the user by loading
the session row from the database on every request.

### Why

- **Compromised token exposes nothing** — attacker learns an opaque UUID only.
- **Instant revocation** — deactivate session row; token is dead on next request before `exp` fires.
- **Single source of truth** — user data lives in the DB, not baked into tokens.

### Authentication flow

```
1. User authenticates (credentials / OAuth2 / magic link / etc.)
2. Create session row: { id: UUID, user_id: FK, is_active: true, expires_at }
3. Sign two JWTs (same session):
       access_token:  { session_id: UUID, token_type: "access",  exp: now+15m }
       refresh_token: { session_id: UUID, token_type: "refresh", exp: now+7d  }
4. Return { access_token, refresh_token } to client.
```

### Request authentication flow

```
1. Decode JWT → session_id
2. Load session row from DB; assert is_active and not expired
3. Load User from DB using session.user_id
4. Attach to request context → request.state.ctx.current_user
```

### Token payloads

```python
# ❌ Bad — user identity in token
payload = {
    "user_id": user.id,
    "email": user.email,
    "exp": ...,
}

# ✅ Good — opaque session reference only
access_payload: dict = {
    "session_id": str(session.id),
    "token_type": "access",
    "exp": int((datetime.utcnow() + timedelta(minutes=15)).timestamp()),
}
```

### Request authentication dependency

```python
async def get_current_user(
    token: str,
    db_session: AsyncSession,
) -> User:
    """Decode JWT, load active session, load and return the user."""
    payload: dict = _decode_jwt(token=token)
    session_id: UUID = UUID(payload["session_id"])
    session: Session = await SessionService.get_active(
        session_id=session_id,
        db_session=db_session,
    )
    user: User = await UserService.get(
        id=session.user_id,
        db_session=db_session,
    )
    return user
```

### Revocation

```python
# Single session logout
await SessionService.deactivate(session_id=session_id, db_session=db_session)

# All sessions for a user (credential reset / security incident)
await SessionService.deactivate_all_for_user(user_id=user.id, db_session=db_session)
```

---

## Checklist

- [ ] Passwords hashed with bcrypt only (no PBKDF2, MD5, SHA-alone)
- [ ] SHA-256 pre-hash applied before `bcrypt.hashpw`
- [ ] Work factor is `rounds=12` or higher
- [ ] Verification uses `bcrypt.checkpw` — never `==`
- [ ] JWT payload contains `session_id` only — no `user_id`, `email`, or identity fields
- [ ] `sessions` table exists with `user_id` FK, `is_active`, `expires_at`
- [ ] Request auth: decode JWT → load session → load user (all three steps hit DB)
- [ ] Logout deactivates session row (not just client-side token discard)
- [ ] Revoke-all path exists for forced logout and credential resets
