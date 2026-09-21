# Slotui Candidate Adapter Consumer Integration (v2)

## Status and safety boundary

`textual_current` remains Slo's default and only normally supported interactive
presentation. `slotui_core` is a protected-release, explicit, fail-closed lane.
There is no candidate reference in this checkout, so:

```bash
slo --presentation slotui_core
```

fails before Slo creates a session, imports Slotui, installs anything, reaches a
registry/VCS/source checkout, or launches Textual as a fallback.

Slo does **not** know Slotui constructors. It does not construct a terminal,
root/container, editor, renderer, or transcript. A candidate must supply one
versioned adapter function which owns all of them.

## Exact release reference and manifest

`--slotui-core-reference` must name an **absolute regular** JSON file that pins
both the adapter manifest and the complete local dependency closure:

```json
{
  "schema_version": "slo-slotui-candidate-adapter-v2",
  "candidate_label": "protected-release-ci",
  "manifest_path": "/absolute/path/slotui-slo-adapter.manifest.json",
  "manifest_sha256": "<sha256 exact manifest bytes>",
  "bundle_path": "/absolute/path/slotui-local-core-candidate.bundle.json",
  "bundle_sha256": "<sha256 exact bundle bytes>"
}
```

The bundle is canonical `slotui-local-core-bundle-v2` JSON. Its path and
SHA-256 are required on the release reference; Slo never derives a bundle from a
manifest directory or conventional filename. It must be colocated with the
manifest, repeat the manifest filename/schema/hash, pin the source commit and
supported Python range, and declare the **entire** wheel closure:
one `slotui` core wheel plus every runtime dependency, with unique normalized
distribution names, exact filenames, roles, and SHA-256 values. Slo verifies all
of those files as regular non-symlink files in the bundle directory before it
can create a venv. It parses every wheel's sole `METADATA` with
`packaging.requirements.Requirement`, evaluates markers for the candidate venv's
Python 3.11/Linux target, recursively derives the active `Requires-Dist` graph
from `slotui`, and rejects missing, version-incompatible, or unreachable declared
wheels. The receipt retains only those exact verified wheel paths; setup uses
`pip install --no-index --no-deps <each-verified-wheel-path>`, never `--find-links`
over the artifact directory. Thus an arbitrary colocated wheel cannot be selected
by pip. A modified manifest, bundle, wheel, source identity, `Requires-Python`,
filename, or dependency declaration fails closed.

The pinned canonical manifest must declare exact local wheel filename/version,
SHA-256, `Requires-Python`, protected source identity with `clean: true`, generic
b.0/b.0.1 evidence, generic static capabilities, and this v2 adapter contract:

```json
{
  "candidate_adapter": {
    "module": "slotui.slo_adapter",
    "symbol": "launch_tui_app",
    "callable_kind": "async_function",
    "keyword_parameters": ["launch", "control"],
    "protocol_version": "slo-slotui-host-control-v2",
    "capabilities": [
      "terminal", "root", "editor", "mounted_live_transcript",
      "control_channel", "isolation_attestation", "protocol_test_hook"
    ],
    "signature_sha256": "<sha256 of: async def adapter(*, launch, control)>"
  }
}
```

The actual module/symbol may differ, but the signature and capability set cannot.
The wheel must also declare a candidate-owned v2 runner in the manifest:

```json
{
  "candidate_runner": {
    "module": "slotui._slo_candidate_adapter_runner",
    "symbol": "run_candidate",
    "callable_kind": "async_function",
    "keyword_parameters": [
      "control_socket", "adapter_module", "adapter_symbol", "protocol_version"
    ],
    "protocol_version": "slo-slotui-host-control-v2",
    "signature_sha256": "<sha256 of canonical runner signature>"
  }
}
```

Static verification ZIP/AST-checks that exact keyword-only async runner signature,
its direct adapter/control references, and its call with `launch=` and `control=`.
It also proves the exact candidate-owned executable bridge that Slo actually
spawns: a unique `if __name__ == "__main__"` branch must construct an
`argparse.ArgumentParser`, require `--control-socket`, `--adapter-module`,
`--adapter-symbol`, and `--protocol-version`, parse `sys.argv[1:]`, and call
`asyncio.run(<manifested-runner>(...))` with the matching parsed values as
keywords. An inert module-level `asyncio.run(...)` launcher is rejected. Generic
exports are never used as a runtime constructor recipe.

Slo launches the proved bridge exactly as:

```bash
<isolated-venv>/bin/python -I -m <candidate_runner.module> \
  --control-socket <private-unix-socket> \
  --adapter-module <candidate_adapter.module> \
  --adapter-symbol <candidate_adapter.symbol> \
  --protocol-version slo-slotui-host-control-v2
```

The candidate function contract is:

```python
async def <manifested-symbol>(* , launch, control) -> None:
    ...
```

- `launch` provides resolved `workdir`, parent `session_id`, optional resolved
  resume ID, protocol version, and adapter declaration.
- `control` is the candidate's v2 control connection abstraction.
- The adapter constructs and owns its `TuiApp` lifecycle: terminal, root, editor,
  mounted live transcript.
- It emits an **attestation** then `host_active` only after all four pieces are
  ready. `host_active` requires all readiness booleans true.
- Attestation reports the manifested adapter declaration, installed module path
  under its venv `site-packages`, and that `/root/Code/slo-tui/src` and all
  candidate source paths are absent.
- The candidate-owned `protocol_test_hook` supports release-CI's candidate-gated
  lifecycle test; no Slo fake/toy wheel is runtime evidence.

## Control channel and process isolation

The candidate process retains its terminal stdin/stdout. Control JSON **never**
shares those descriptors. The installed host allocates a private PTY for the candidate
(`pty.openpty()`), passes its slave as child stdin/stdout, and closes both descriptors
after candidate terminal teardown; this makes the candidate-gated runtime test valid
from a noninteractive pytest worker while preserving candidate terminal ownership. The parent creates a private Unix-domain socket inside
a temporary runtime directory; candidate runner connects to it. JSONL frames move
only over that socket:

```text
terminal stdin/stdout <---- candidate TuiApp ----> terminal
                                  |
                         private Unix socket
                                  |
Slo parent session <--- JSONL control commands/events ---> candidate adapter
```

Startup is transactional and bounded: fresh venv creation, then an offline
complete-closure install:

```bash
<isolated-venv>/bin/python -I -m pip install --no-index --no-input --no-deps \
  <verified-core-wheel> <verified-runtime-dependency-wheel> ...
<isolated-venv>/bin/python -I -m pip check
```

Slo never uses `--no-deps`, an index, a VCS URL, a source checkout, editable
installation, or a fallback package location. The install source is only the
verified bundle directory. Socket connect, a typed `launch` command,
matching `launch_ack`, adapter attestation, and TuiApp readiness all time out. A
candidate may not attest before acknowledging the exact manifested adapter
launch. Any failure closes socket/server, drains bounded stderr, terminates then
kills/reaps the child when needed, and removes the temp root. EOF reports return
code plus a capped stderr tail. Parent stderr is drained continuously to avoid
pipe deadlock.

The closed protocol validates payload ownership per message kind: `launch` carries
only `launch`, `stream_event` carries only `mutation` plus `mutation_id`, notices
and failures carry only `notice`, and shutdown carries no payload. Candidate events
likewise reject cross-kind fields. Every parent stream mutation requires the real
candidate to emit a matching `transcript_ack`; acknowledgements are routed separately
from editor/lifecycle events, so they cannot consume a submit frame.

The child environment is a minimal allowlist (`HOME`, locale, terminal values,
`TZ`, system `PATH`) plus `PIP_CONFIG_FILE=/dev/null`, `PIP_NO_INDEX=1`, and
`PYTHONNOUSERSITE=1`. The documented `SLO_SLOTUI_PROTOCOL_TEST_PROMPT` is forwarded
only when present so the candidate-owned release-CI hook can submit after `host_active`. `PYTHONPATH` rejects startup. Runtime root derives Slo's
source root from `host.py`, never from cwd, and is checked outside Slo and
`/root/Code/slo-tui/src`; the candidate additionally attests its import location.

## Real Slo session and one-prompt policy

Only after static proof succeeds, Slo constructs its ordinary in-process
`SloAgentSession` using resolved workdir, workspace, plugins, and resume ID.
Editor submissions arrive at the parent through the control socket. The parent
forwards actual `AgentStreamEventDAO` events exhaustively, retaining iteration,
content/block/tool identities, tool arguments, metadata, and sub-agent fields.

Policy is **reject while busy**: only one `session.invoke()` task can exist. A
rapid second editor submit receives a visible transcript notice; it is not queued
or silently replaced. Parent session exceptions are caught and sent as explicit
`session_failed` transcript failures, never left as background task exceptions.

Tool lifecycle maps explicitly: `tool_call_start` creates, delta/output updates
append, and `tool_call_end`/`tool_result` end. Every `StreamEventKind` has a
mapped create/append/end/failed/notice operation. This is a protocol mapping,
not a claim that the unavailable candidate renders them correctly.

## Launch and limitations

A legacy reference that omits `bundle_path` or `bundle_sha256` is **not** a fully
pinned v2 release reference and Slo rejects it. Do not edit a protected candidate
directory to upgrade it. Instead, create a separate reference, pinning the exact
existing bundle explicitly:

```bash
python - <<'PY'
from pathlib import Path
from src.integrations.slotui.reference import SlotuiCoreReferenceDerivationService

SlotuiCoreReferenceDerivationService.derive(
    legacy_reference_path=Path("/absolute/candidate/legacy-reference.json"),
    bundle_path=Path("/absolute/candidate/slotui-local-core-candidate.bundle.json"),
    output_path=Path("/secure/operator-output/slotui-core-reference.v2.json"),
)
PY
```

The output must be a new path; derivation refuses to overwrite the legacy
reference. It retains the legacy manifest facts while adding the independently
calculated bundle SHA-256, so only the resulting v2 reference is valid for
launch:

```bash
slo --presentation slotui_core \
  --slotui-core-reference /secure/operator-output/slotui-core-reference.v2.json \
  --workspace /absolute/path/project.code-workspace \
  --resume existing-session
```

Headless never accepts presentation selection. There is no normal Slo Slotui
import, dependency, package registry lookup, source fallback, or default switch.

This lane does **not** claim implementation or parity for resume behavior,
editor queue/latest-wins behavior, copy, history, replay, slash commands, auth,
`/diff`, history tree, fleet/workflow overlays, or Rich rendering. Images, LaTex,
and Mermaid are only declared raw/literal fallbacks. Candidate implementation
and protected release-CI evidence are required before any stronger claim.

## Verification

- `tests/integrations/slotui/test_core_contract.py`: static archive/manifest/
  adapter signature rejection and acceptance; no import/install.
- `tests/integrations/slotui/test_host.py`: faked **control ports only** test
  parent lifecycle, rapid submit rejection, failure rendering, and exhaustive
  `StreamEventKind` mapping. They are not candidate runtime evidence.
- `tests/integrations/slotui/test_runtime.py`: e2e, skipped unless
  `SLO_SLOTUI_CANDIDATE_REFERENCE` is supplied. It uses the actual protected
  installed wheel plus the documented strict test hook
  `SLO_SLOTUI_PROTOCOL_TEST_PROMPT`: candidate readiness → real candidate editor
  submit → an actual deterministic `SloAgentSession` built with `FauxChatModel`
  → parent event mutation → candidate mount/`transcript_ack` → orderly close.
  It contains no toy wheel or fake candidate runtime evidence.

The architecture and pure control-port tests are delivered in this checkout. The
candidate-gated runtime test uses the supplied local bundle when
`SLO_SLOTUI_CANDIDATE_REFERENCE` names its absolute release reference. If that
environment reference is legacy/unpinned, the E2E test creates a test-local,
separate derived v2 reference from its explicit colocated bundle; it never edits
candidate artifacts. It creates a real `SloAgentSession` with `FauxChatModel`, sets the candidate-defined
`SLO_SLOTUI_PROTOCOL_TEST_PROMPT`, and runs the actual installed wheel in a fresh venv
with `python -I` and a private PTY. The test requires test-hook editor submission,
actual parent response mutations, exact post-apply acknowledgements, candidate-initiated
orderly close, reaped child, removed isolated venv/socket root, and closed PTY descriptors.
It is skipped only when no candidate reference is supplied; it never skips merely because
pytest has no TTY. No general Slotui parity claim follows from this control-path coverage.
