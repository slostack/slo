# Owner B — capture lifecycle corrective evidence — 2026-10-03

## Scope and result

**READY for the assigned Owner B correction only.** This report does not claim
Feature 86, a full non-E2E suite, live provider availability, or other owners'
work is complete.

Owned production files changed:

- `src/agents/slo_agent/orchestrator/spawn_env.py`
- `src/agents/slo_agent/orchestrator/relaunch.py`
- `src/agents/slo_agent/orchestrator/workflow_registry.py`
- `src/agents/slo_agent/orchestrator/capture_writer.py` was inspected; its existing
  writer-side final close remains the lease-release owner and did not require a
  behavior change.

Owned test support/tests changed:

- `tests/agents/slo_agent/orchestrator/test_capture_control_protocol.py`
- `tests/agents/slo_agent/orchestrator/test_capture_writer.py`
- `tests/agents/slo_agent/orchestrator/test_relaunch.py`
- `tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py`
- `tests/agents/slo_agent/orchestrator/capture_test_safety.py`

All test filesystem writes used pytest `--basetemp` directories below this checkout,
and tests asserted their resolved roots. No network, credentials, installation,
specification, Git, or system/PATH mutation was performed.

## Corrected behavior

### 1. Writer-lifetime append lease

`open_capture_file_append()` now transfers the existing append-lease FD through
`pass_fds` to the isolated writer. The parent closes only its duplicate after writer
readiness and endpoint ownership transfer. `StreamingCredentialRedactor.invoke()`
already closes that inherited FD only in its final-drain cleanup, so the lease remains
held after the launcher exits and until workload EOF/redaction/flush completes.

`test_reaped_launcher_transfers_append_lease_until_old_writer_final_drain` uses a
real finite intermediary process and production opener/writer. The intermediary exits
before the old child releases its output tail; a replacement opener cannot become
ready before that release. Final bytes are exactly:

```text
old-prefixold-tailnew-first-byte
```

The existing contained-lifetime native-I/O/reporter tests were retained and passed,
including workload PID/process-group/control/reporter health assertions.

### 2. Late off-loop capture ownership and cancellation

`WorkflowRelauncher._open_capture_for_adoption()` retains the `asyncio.to_thread`
operation in a task. If the awaiting task is cancelled, it waits for the opener's
actual result and closes a successful late endpoint off-loop. That endpoint's normal
close path owns data, ACK, control, append lease, and writer reaping. No workload is
spawned before both captures are adopted.

`WorkflowCommandService._resume_locked()` now rolls back a pre-adoption durable
reservation on cancellation even when no context ownership has yielded. Its existing
post-adoption branch remains unchanged: adopted PID/launching state is retained and a
capture error records safe degradation rather than stopping/replacing the workload.

The focused parameterized test covers both `stdout.jsonl` and `stderr.log` late
endpoint cleanup. Existing command-service cancellation tests cover reservation
rollback before durable adoption and the no-kill post-adoption case.

### 3. Allocation and flock cleanup

`spawn_env.py` now has named ownership-transfer helpers. Once acquired, the append
lease immediately belongs to a cleanup set; each data/ACK/control pipe pair joins the
same set atomically. Any first/second/third pipe failure, destination failure, spawn/
ack failure, or unexpected `flock` exception closes all remaining owned descriptors.

The flock branch now has an enclosing cleanup boundary, rather than only closing on
bounded contention. Tests include every pipe allocation point with the lease FD,
destination failure, unexpected flock failure followed by nonblocking reacquisition,
and existing writer/ack cleanup paths.

### 4. Private creation modes

The existing private creation functions were verified and exercised under an owned
`umask(0)` test:

- newly created capture ancestors: `0700`
- new capture data file: `0600`
- new sibling append lock: `0600`

The test also verifies an existing `0755` ancestor and existing `0644` external file
are unchanged while append content is preserved. No chmod is used for an existing
path.

### 5. Structure

The capture opener is split into explicit allocation, spawn, capture-pipe transfer,
and descriptor cleanup steps. New methods have typed signatures and Google-style
purpose/lifetime documentation. No new registry, sandbox, generic raw-body filter,
argv-equality rule, or native-startup requirement was introduced.

## Test-first record

Initial focused runs exposed the required test/implementation integration failures:

1. `test_unexpected_flock_failure...` first hit the fixture's credential tripwire;
   the test was corrected to use a synthetic explicit credential.
2. The reaped-launcher test first failed with escaped source newlines, then a missing
   flush of `old-prefix`; it became green after using actual newlines and flushing the
   production pipe before intermediary exit.
3. The surrounding contained-lifetime suite first rejected the newly required lease
   FD in its explicit child allowlist; its test-only exact FD contract was updated.

These are red-to-green corrections, not skipped or weakened assertions.

Focused green commands/results:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q \
  --basetemp="$PWD/.owner-b-one" \
  tests/agents/slo_agent/orchestrator/test_capture_control_protocol.py
# 34 passed, 1 warning

PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q \
  --basetemp="$PWD/.owner-b-new-relaunch9" \
  tests/agents/slo_agent/orchestrator/test_relaunch.py::test_cancelled_late_capture_open_closes_endpoint_without_workload_spawn
# 2 passed, 2 warnings

PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q \
  --basetemp="$PWD/.owner-b-writer5" \
  tests/agents/slo_agent/orchestrator/test_capture_writer.py::test_reaped_launcher_transfers_append_lease_until_old_writer_final_drain
# 1 passed, 2 warnings

PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q \
  --basetemp="$PWD/.owner-b-contained5" \
  tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py
# 38 passed, 2 warnings
```

Final surrounding partition:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q \
  --basetemp="$PWD/.owner-b-final" \
  tests/agents/slo_agent/orchestrator/test_capture_ack_cleanup.py \
  tests/agents/slo_agent/orchestrator/test_capture_control_protocol.py \
  tests/agents/slo_agent/orchestrator/test_capture_guard_lifetime.py \
  tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py \
  tests/agents/slo_agent/orchestrator/test_capture_writer.py \
  tests/agents/slo_agent/orchestrator/test_detached_fd_capture.py \
  tests/agents/slo_agent/orchestrator/test_openrouter_capture_secrecy.py \
  tests/agents/slo_agent/orchestrator/test_relaunch.py \
  tests/agents/slo_agent/orchestrator/test_workflow_registry.py \
  tests/agents/slo_agent/orchestrator/test_workflow_command_service.py
# 243 passed, 2 warnings in 32.42s
```

Static hygiene for the assigned paths:

```bash
python -B -m black --check <9 owned source/test paths>
git diff --check -- <owned orchestrator paths>
# both passed
```

## Limits

- This was deliberately not a full test suite.
- The two warnings are third-party LangGraph/pythonjsonlogger deprecations.
- Capture tests use synthetic credentials and local finite subprocesses only; they do
  not establish live OpenRouter behavior.
- Other Feature 86 owners and the broader Step 1/2/3 gates remain outside this owner
  report.
