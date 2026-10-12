---
name: go-auth-security
description: Go authentication/authorization boundary recipe with typed principals, named policy, credential
  redaction and negative security tests.
when_to_use: Go authentication/authorization boundary recipe with typed principals, named policy, credential
  redaction and negative security tests.
group: languages
kind: skill
---

# Go Auth Security

## Skill summary

Go authentication/authorization boundary recipe with typed principals, named policy, credential redaction and negative security tests.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

Keep credential parsing/verification in the adapter and authorization in a named domain/application policy. A verified principal is a resolved model; raw token/claims input is a transient DAO. A consumer receives only required identity/permission fields, not arbitrary maps or a whole HTTP context.

For an existing JWT stack validate signature algorithm allow-list, issuer, audience, expiry/not-before and key rotation through the approved library; never trust unverified claims or introduce a new dependency silently. Distinguish unauthenticated from authenticated-but-forbidden errors, map sentinels at transport boundaries, and avoid leaking internal diagnostics. Session/cookie APIs preserve CSRF, secure/httpOnly/sameSite and revocation contracts.

Authorization step example contract: `Authorize(ctx, AccessDAO{Principal: principal, ResourceID: id, Action: action}) error`; injected consumer-local owner returns ErrForbidden. The orchestration gateway calls this named step before reading or mutating protected state. Tests must assert no protected collaborator is called on failure, not just an HTTP 403.

Test absent/malformed/expired/wrong-issuer/wrong-audience credentials, disallowed algorithm, key rotation, cross-tenant ID access, ownership failures, revoked privileges and redaction in logs/errors. Test authorization at the real externally reachable handler too; a unit test alone does not prove middleware registration. Propagate deadlines, bound payloads and retries, close response bodies, and keep secrets out of fixtures/artifacts.

