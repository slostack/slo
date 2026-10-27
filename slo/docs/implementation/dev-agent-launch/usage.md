# Explicit development agent launches

This checkout supports **exactly `SLO_DEV_MODE=1`** for managed agent launches.
Start the parent using the intended checkout and interpreter, for example from
this application directory:

```sh
SLO_DEV_MODE=1 /root/.pyenv/versions/slo-harness/bin/python -m src.cli
```

This is usage documentation, not an instruction to run a paid workflow for testing.
The source-only interpreter must already have the application's dependencies.

- Managed children, detached orchestrators and both resume paths use the same
  interpreter with `-P -s -m src.cli`. Their `PYTHONPATH` is exactly the resolved
  import root of the **running Slo module**, not task cwd or ambient PYTHONPATH.
- Descendants inherit the explicit mode. Resume uses the **current parent's** mode
  and running source. This is the orchestrator's interpretation of the original
  explicit opt-in, not additional user approval. Nothing persists mode/root in
  workflow handles; a later parent without opt-in uses normal isolation.
- Unset, empty, `0`, `true`, `yes`, padded `1`, and `DEV=1` do not opt in.
  Normal launches retain `sys.executable -I -m src.cli`; Slo must be installed in
  that interpreter. Development support does not repair a missing installation.
- Caller identity extras cannot override `SLO_DEV_MODE`, `PYTHONHOME`, or
  `PYTHONPATH`. Existing sanctioned identity/credential forwarding remains intact.
- Capture writers/reporters keep their dedicated isolated commands and environments.
  Project commands are not switched into this policy.

Development mode trusts the running checkout and interpreter; it is not a sandbox.
An installed parent does not select a different checkout merely because its cwd
points there. Remove the explicit opt-in to return future launches to default mode.

Verification status and unwaived blockers: [implementation-evidence.md](implementation-evidence.md).
