---
name: go-recipe-api-response-conventions
description: 'Go HTTP API envelope: data/api_version/errors, nested pagination, typed error/status mapping,
  Gin helpers and contract tests; preserve approved wire contracts.'
when_to_use: 'Go HTTP API envelope: data/api_version/errors, nested pagination, typed error/status mapping,
  Gin helpers and contract tests; preserve approved wire contracts.'
group: languages
kind: skill
---

# Go Recipe Api Response Conventions

## Skill summary

Go HTTP API envelope: data/api_version/errors, nested pagination, typed error/status mapping, Gin helpers and contract tests; preserve approved wire contracts.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Authority and reconciliation

Load `skills/coding/api-response-conventions/SKILL.md` for the language-independent envelope semantics. This recipe is the sole Go implementation/profile owner: it owns Go types, JSON tags, status mapping, Gin/net/http response helpers, and Go contract tests. The installed Go, Python and TypeScript recipes agree on `data`, `api_version`, and `errors` with `errors.msg` and `errors.code` for the approved envelope family, but their version values and pagination defaults are not automatically interchangeable. The older Go response recipe's singular error plus top-level meta is superseded, not an alternative for new code. An existing deployed divergent API needs an explicit compatibility/version migration decision; never silently change its bytes. Handlers/middleware/docs summarize or link this adapter and the shared contract; they do not define a second envelope.

## Complete typed wire shapes

```go
// Package envelope owns the service HTTP response contract.
package envelope

// APIVersion is the approved API contract version.
const APIVersion = "v1.0"
// ResponseErrors contains public, redacted error details.
type ResponseErrors struct {
    Msg []string `json:"msg"`
    Code *string `json:"code"`
}
// SuccessResponse carries a typed successful payload.
type SuccessResponse[T any] struct {
    Data T `json:"data"`
    APIVersion string `json:"api_version"`
    Errors ResponseErrors `json:"errors"`
}
// FailureResponse carries null data and public error details.
// The pointer guarantees data:null without an untyped payload bag.
type FailureResponse struct {
    Data *struct{} `json:"data"`
    APIVersion string `json:"api_version"`
    Errors ResponseErrors `json:"errors"`
}
// PageResponse keeps all pagination inside data.
type PageResponse[T any] struct {
    Page int `json:"page"`
    Size int `json:"size"`
    Total int `json:"total"`
    Items []T `json:"items"`
}
// Success constructs a success envelope with [] messages and null error code.
func Success[T any](data T) SuccessResponse[T] {
    return SuccessResponse[T]{Data: data, APIVersion: APIVersion,
        Errors: ResponseErrors{Msg: []string{}, Code: nil}}
}
// Failure constructs a failure envelope using a stable public error code.
func Failure(message string, code string) FailureResponse {
    return FailureResponse{Data: nil, APIVersion: APIVersion,
        Errors: ResponseErrors{Msg: []string{message}, Code: &code}}
}
```

Success JSON: `{"data":{"id":"u1"},"api_version":"v1.0","errors":{"msg":[],"code":null}}`.
Failure JSON: `{"data":null,"api_version":"v1.0","errors":{"msg":["not found"],"code":"NOT_FOUND"}}`.
No success boolean, singular error, root meta or root pagination. Lists have uniform item DAO shapes, not discriminated wire unions; page is zero-indexed, default size 25, cap 100 and total retains the approved unfiltered-total meaning. Normalize empty item/message slices to [] rather than null. Intrinsic pagination validation belongs to its DAO; never silently overflow an offset.

## Error/status boundary

Domain packages own known-condition sentinels/typed errors; they do not carry HTTP status. The transport mapper uses errors.Is/As: invalid shape → project 400/422 contract, unauthenticated 401, forbidden 403, not found 404, conflict 409, rate limit 429, unexpected 500. Stable SCREAMING_SNAKE_CASE codes are a reviewed API taxonomy. Redact unexpected failure messages; log contextual detail without secrets and preserve the cause internally. Validation can aggregate multiple messages using a named validation-error DAO; do not expose raw driver or token errors.

For Gin, a thin response helper calls `c.JSON(status, envelope.Success(payload))` or `c.AbortWithStatusJSON(status, envelope.Failure(message, code))`. Either the handler maps/responds or it calls c.Error and central middleware maps/responds after c.Next; select one ownership model so responses are never written twice. Middleware recovery must use the same envelope. For net/http, encode to a buffer first to catch serialization failure before writing headers; handle writer errors with the project's logged disconnect policy. No raw map/struct/slice responses.

## Documentation and testing

The API documentation recipe describes these exact types. Where swaggo cannot instantiate generics, a concrete docs wrapper may mirror this wire schema and is checked for drift; it is not a second normative definition.

Using httptest, assert status, Content-Type, all three root keys and absence of extras, data shape, [] messages/null code on success, null data/stable code on failure. Cover validation, auth, forbidden, missing, conflict, unexpected errors, empty/nonempty lists, pagination limits and exact total meaning. Test the registered middleware stack—not only helper functions. Preserve prior exact boundary rendering where specified and add golden JSON/schema checks for frontend/backend compatibility.

