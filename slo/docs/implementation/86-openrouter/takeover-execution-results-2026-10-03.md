# Step 1 takeover execution — REVISE

Requested gpt-6-astra medium; backend unattested. No independent review or completion assessment performed.

## Implemented attempt

Modified only the existing finite capture containment helper and its test module (plus this execution record/plan and ledger pointers). Production code and the already-wired post-adoption control FD are unchanged.

The helper now requires explicit writer bootstrap registration. Owned regular scripts execute the unchanged production writer through runpy, check actual inherited descriptor tuples, check capture FD inode/path before writes, and execute the exact production reporter body in a separate isolated interpreter after child-local path checks. Writer-local RLIMIT_FSIZE (soft 128 bytes; SIGXFSZ ignored locally) produces a genuine kernel write failure after the reaped-launcher release barrier. Reporter setup restores the writer's soft limit before spawning, so durable store writes are not capped. The workload retains its real PID/process group and waits on a second owned release FD while fresh store/status are asserted. Owned workload/writers are reaped without external signals; child-local alarms bound the experiments.

**This is an instrumented-body experiment, not the requested exact unmodified topology acceptance.** The helper substitutes writer and reporter entry argv and replaces stdout's raw IO wrapper for pre-write checking. The exact-argv qualification test fails. The reporter body is unchanged, but its exec representation is not. No raw-body normalization sentinel proof was completed. No outer manual capture-failure record is used.

## Executed commands/results

Every pytest run used `PYTHONDONTWRITEBYTECODE=1 /root/.pyenv/versions/slo-harness/bin/python -B -c` with a driver that resolves cwd, creates `tempfile.mkdtemp(prefix=PREFIX, dir=root)`, asserts resolved ancestry, and invokes `pytest.main(['-q','-p','no:cacheprovider','--basetemp='+str(base/'tests'),*NODES,'--tb=short'])`. Python 3.11.7 asserted on first run.

All nodes below are under `tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py`:

- `.f86-capture-takeover-red-ydy_hs9a`, `::test_production_writer_requires_child_local_registration`: 1 failed, DID NOT RAISE.
- `.f86-capture-takeover-green-_wsnb26m`, same node: 1 passed.
- `.f86-capture-topology-ybr1f445`, `::test_separate_launcher_clean_drain`: 1 passed.
- `.f86-capture-late-red-s3ha10p4`, `::test_reaped_launcher_late_capture_failure_requires_durable_health`: 1 failed, `late writer failure lacks durable health`; reporter deliberately denied at this first stage.
- `.f86-capture-late-green-r70381_4`, same node after reporter bootstrap: 1 failed, same assertion. Child audit denied opening real DEVNULL for writing. Corrected only the helper to use the existing owned null file.
- `.f86-capture-late-retry-7ynpgwfk`, same node: 1 passed.
- `.f86-capture-assertions-c3te0lf_`, late-failure plus clean-drain nodes: 2 passed; fixed-safe health/status and two nonempty redacted captures checked.
- `.f86-capture-live-workload-uh_ket9c`, late node with second workload release barrier: 1 passed.
- `.f86-capture-surrounding-az5lmegk`, entire module before exact-argv qualification added: 35 passed. Includes non-zombie workload assertion.
- `.f86-capture-exact-contract-o80fu8uk`, `::test_exact_production_writer_argv_is_preserved_by_containment`: **1 failed**, `containment substituted production entry argv`; index 3 is the owned `writer-bootstrap.py`, not production `capture_writer.py`. Retained as an ordinary failing test, not skipped/xfail or renamed success.
- Same interpreter `-B -m black --no-cache` on the two modified Python files: 2 reformatted. No current all-module green claim after adding the exact-contract test; no full suite/mypy/global gate run.

## Concrete blocker and next action

F86-03/22/37 remain open. The materially changed executable approach reaches late kernel failure and fresh durable reporter health after parent reap, but **fails the exact topology requirement at subprocess argv**, as demonstrated above. Child-local Python instrumentation cannot be assumed to survive the original isolated exec; the attempted bootstrap changes that exec. This is not a claim that all possible containment techniques are impossible.

Further qualification is also needed for pre-identity descendant cleanup, reporter FD writes (audit hooks primarily cover path opens/mutations), full default-deny process escape, and raw-body normalization sentinel inputs. The guard is not a universal sandbox. Earlier helper consumers that launch bare writers now require explicit bootstrap registration; the wider capture partition has not been run and must not be assumed compatible.

Do not proceed to Plan B or claim primary acceptance from the 35-pass instrumented module. Next implementation must preserve exact writer/reporter invocation while establishing child-local containment, or obtain an explicit contract decision that the owned bootstrap representation is acceptable. No system/interpreter/PATH modifications were attempted to inject startup hooks. Plan B drain, independent two-OS-process resume admission, operation-owned old-key artifacts and global gates remain pending. Step 2 eligibility: **no**.
