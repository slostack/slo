---
name: go-test-orchestration
description: Go isolated orchestration tests with consumer-interface recording fakes, exact call order,
  arguments, failure cutoffs and sentinels; no database required.
when_to_use: Go isolated orchestration tests with consumer-interface recording fakes, exact call order,
  arguments, failure cutoffs and sentinels; no database required.
group: languages
kind: skill
---

# Go Test Orchestration

## Skill summary

Go isolated orchestration tests with consumer-interface recording fakes, exact call order, arguments, failure cutoffs and sentinels; no database required.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Harness

Use the compilable activation package in go-build-application-services. Place this companion test in the same package. A table row is one behavior; record both expected calls and forbidden subsequent calls. No Docker, Gin or real database belongs in this test category.

```go
package activation

import (
    "context"
    "errors"
    "reflect"
    "testing"
)

type accountRecorder struct {
    calls *[]string
    failure error
}
func (r accountRecorder) Activate(_ context.Context, in ActivateDAO) (ResultDAO, error) {
    *r.calls = append(*r.calls, "activate:"+in.AccountID)
    return ResultDAO{AccountID: in.AccountID}, r.failure
}
type noticeRecorder struct { calls *[]string }
func (r noticeRecorder) Send(_ context.Context, in NoticeDAO) error {
    *r.calls = append(*r.calls, "notify:"+in.AccountID)
    return nil
}
func TestExecute(t *testing.T) {
    failed := errors.New("account failed")
    cases := []struct {
        name string
        failure error
        want []string
    }{
        {name: "success", want: []string{"activate:a1", "notify:a1"}},
        {name: "activation cutoff", failure: failed, want: []string{"activate:a1"}},
    }
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            calls := []string{}
            service := New(DependenciesDAO{
                Accounts: accountRecorder{calls: &calls, failure: tc.failure},
                Notices: noticeRecorder{calls: &calls},
            })
            result, err := service.Execute(context.Background(), ActivateDAO{AccountID: "a1"})
            if !errors.Is(err, tc.failure) { t.Fatalf("error: %v", err) }
            if !reflect.DeepEqual(calls, tc.want) { t.Fatalf("calls: %v", calls) }
            if err == nil && result.AccountID != "a1" { t.Fatalf("result: %+v", result) }
        })
    }
}
```

Extend this harness before implementation with notification failure, context identity/deadline propagation, second execution using a different input and no state leakage. Assert exact error text only at a compatibility boundary alongside errors.Is, not as a substitute for sentinel identity. Concurrency-safe recorders need a mutex/channel; do not add t.Parallel when sharing a mutable call slice across cases. Parallel table cases with independent fixtures are fine.

A fake-based success does not prove a real transaction committed. Pair with go-test-application-services for database-backed workflows, and go-test-lifecycle for background ownership. Every failure row asserts the later calls and side effects are absent.

