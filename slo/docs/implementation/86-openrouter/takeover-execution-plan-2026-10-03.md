# Step 1 capture takeover — executable sequence

Requested model: gpt-6-astra medium; actual backend unattested.

1. Add a failing containment test for the exact production writer launch: require child-local descriptor provenance and write admission, rather than assuming parent monkeypatches cross isolated exec. Keep the existing control-FD protocol and production writer/reporter source unchanged.
2. Extend only the finite capture helper with owned child bootstrap scripts. Validate production argv before delegation; execute unchanged writer/reporter code after child-local checks. Default deny other processes/network; resolve file/FD destinations before writes. Use a child-local file-size limit for a genuine late capture write failure, never substitute a writer exception or record failure from pytest.
3. Run a finite production launch with exactly two writers, durable workload adoption, parent exit/reap, then release output. Check populated redacted captures and safe health via fresh store/status while workload identity survives; record actual refusal/assertion if the exact topology cannot pass containment. Reap only ledger-owned descendants.
4. Only after that acceptance passes, add barrier-driven old-tail/new-first-byte ordering and independent two-process resume reservation tests; implement the narrow destination drain lease at the existing capture owner.
5. Then test actual admitted old-key rotation/resolver failure at existing serialization owners. Do not repeat the already-covered auth/picker happy path. Run affected partitions before considering global gates.

No Git mutations, source-spec/other-worktree edits, installs, shared environment/interpreter/skill changes, system/PATH writes, live credentials or network. Python execution uses only the authorized slo-harness 3.11.7 interpreter with bytecode/cache disabled and fresh checkout-contained basetemps. No independent review or completion assessment is part of this work.
