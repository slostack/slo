# Exact capture-entry qualification — blocked, not delivered

Requested execution: gpt-6-astra medium; backend identity unavailable. Sole-owner bounded call, 2026-10-03. F86-03/22/35/37/38/39 remain open. No Step 1 readiness or Step 2 eligibility.

## Source-level causal verdict

The specification requires safe errors/captures and preserved headless lifecycle, not literal test argv equality: overview error policy; 86.a.3 sections on normalized failure/audit; 86.a.4 §§7.6–7.8; 86.a.6 §7.2. Exact argv is nevertheless an explicit qualification requirement in this task. It cannot be waived solely because a wrapper eventually executes the same source.

Production chain:

- `launch_tool.py::_spawn_and_patch` opens two captures, spawns the actual workload, awaits durable PID write, activates both private control endpoints, then closes parent capture ownership.
- `spawn_env.py::open_capture_file_append` executes `[sys.executable, '-I', '-B', capture_writer.py]`, with disk destination on stdout, input pipe on stdin, ACK/control FDs and captured synthetic credential in the writer environment.
- `StreamingCredentialRedactor.invoke` acknowledges readiness, starts the independent control reader, drains input, and on failure waits for activation before `_report_serialized_failure`.
- Reporter is `[sys.executable, '-I', '-B', '-c', script, serialized_context]`, empty environment, closed inherited FDs, and the normal synchronous `WorkflowHandleStore.record_capture_failure_sync` path.

Current instrumented chain:

- `_guarded_popen` substitutes `writer-bootstrap.py` while retaining process options and pipes.
- Bootstrap installs guards, replaces `os.write` and `sys.stdout` with a custom raw IO implementation, applies RLIMIT_FSIZE, then uses `runpy.run_path` for the production writer.
- Reporter interception restores the writer soft size limit, creates an owned script, substitutes script argv for `-c`, and that child installs guards before `exec(compile(production_script,...))`.
- Production activation, control reader, capture loop and store body are delegated, not replaced. However interpreter entry, stdout raw IO implementation, inherited resource state and pre-reporter effects differ. This is useful instrumented-body evidence, not independently sufficient exact-entry/failure-ordering evidence.

## Concrete startup constraint

Read-only execution of the requested interpreter with `-I -B` verified Python 3.11.7, isolated=1, ignore_environment=1, no_user_site=1, safe_path=True. Its startup search contains only the shared Python standard library and slo-harness site-packages. Checkout-local PYTHONPATH/sitecustomize/user-site injection cannot install guards for these commands. The reporter additionally has env={}. Parent Python audit hooks do not survive exec. Existing ACK/control startup accepts identity data, not executable safety instrumentation.

Changing shared site-packages/interpreter is prohibited. Removing `-I`, substituting an executable, or accepting an arbitrary hook from env/control would not satisfy the requested exact shipped invocation and security scope. No compliant existing child startup mechanism was identified in this call. This is not a claim that kernel containment is impossible; introducing an unreviewed OS sandbox here would exceed the explicitly narrow task and is not attempted.

## Executed evidence

All pytest commands used `PYTHONDONTWRITEBYTECODE=1 /root/.pyenv/versions/slo-harness/bin/python -B -c` with this driver (1200-second tool timeout):

```python
from pathlib import Path
import tempfile, pytest
root = Path.cwd().resolve()
base = Path(tempfile.mkdtemp(prefix=PREFIX, dir=root)).resolve()
assert base.is_relative_to(root)
print(base)
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider',
    '--basetemp=' + str(base / 'tests'), *NODES, '--tb=short']))
```

Module M = `tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py`.

1. PREFIX `.f86-entry-qualification-red-`, NODES the two `M::test_exact_production_{writer,reporter}_argv_is_preserved_by_containment` nodes: **2 failed**, 2 warnings. Root `.f86-entry-qualification-red-jc3mrp3k`. Exact failures: `containment substituted production entry argv` and `containment substituted production reporter argv`.
2. Added independent no-spawn production opener wiring/cleanup test; did not weaken either retained RED assertion. PREFIX `.f86-entry-wiring-`, NODES `M::test_production_capture_opener_uses_exact_isolated_entry_without_spawn`: **1 passed**, 2 warnings. Root `.f86-entry-wiring-geafznmf`. Checks real opener argv, environment, six real pipe descriptors, inherited tuple, disk destination, and all six descriptors closed after refused spawn. This new evidence is not a red-to-green implementation fix.
3. PREFIX `.f86-entry-no-spawn-partition-`, NODES `[M, '-k', 'setup_failure or reap_restores or exact_production or production_capture_opener or production_writer_requires or reporter_precondition_rejects']`: **17 passed, 2 failed, 19 deselected**, 2 warnings. Root `.f86-entry-no-spawn-partition-n21gbeby`. Same two qualification failures retained.
4. `-m black --check --no-cache M`: one file unchanged.
5. `mypy.api.run(['--follow-imports=silent', '--cache-dir='+fresh_checkout_root+'/mypy', M])`: **2 errors** in retained reporter qualification test, at list(call['args']) and subprocess.Popen(**call), object-shaped inputs. Not corrected or suppressed. No new test diagnostic reported.
6. `git diff --check`: exit 0 before documentation edits; rerun at handoff.

Whole module/real late-failure rerun was withheld because exact child-local safety remains unqualified; no fresh acceptance claim. Historical instrumented acceptance remains historical. No Plan B, contention, full suite, review, or completion assessment performed.

## Remaining finite matrix

| Item | Result / next action |
|---|---|
| Direct production opener wiring | New no-spawn test passes; reporter production argv already captured by existing helper |
| Exact writer and reporter entry | Both RED; requires a concrete approved exact-entry containment arrangement, not an arbitrary production hook |
| Reaped launcher / late kernel fault | Historical instrumented pass only; rerun only after child-local safety is established |
| Credential/raw-body controls | Credential literal FD redactor is not a generic raw-body scrubber; meaningful raw-body normalizer source plus positive populated artifact controls still required |
| Cleanup / child writes | Pre-identity descendant cleanup and complete descriptor/process safety still unqualified |
| Static checks | Black passes touched test; two reporter-test typing errors remain |
| Later work | Plan B, OS contention and full gates explicitly not run |

No production file changed. Existing dirty/untracked work preserved; no Git mutations, installs, credentials, live network, shared environment or spec edits. One initial oversized context read caused tool-managed `/tmp/slo-bash-s35t9_3g.txt` spill, contrary to the requested checkout-only write boundary; it was not edited or removed. Subsequent output was bounded. Test artifacts and mypy cache were explicitly checkout-owned. KB was consulted read-only and not edited.
