# 96.a.2 executable-fixture safety audit (retry 1)

**Status:** read-only audit. No test, collection, lint, or runtime command was
executed. No fixture was created. No product or test file was edited. This is
**not** a safety certification of the whole suite.

**Baseline:** `message-queue` / `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
All line references are at this HEAD.

**Scope read:** `routing.md`, `acceptance.md`, `preflight-blocker.md` (byte-preserved,
SHA-256 `10fe2372…183638`), `tests/conftest.py`, `tests/state_isolation.py`,
targeted fixture searches in `tests/cli/test_install.py`,
`test_update.py`, `test_isolated_launcher.py`, the Herdr fixtures, and a
repo-wide `chmod`/`write_regular_executable`/`/bin` search. Nothing else.

## 1. The only authorized executable fixture

The operator authorizes exactly one existing executable fixture:
`tests/cli/test_deploy_install_worker.py:15–30` creates
`<tmp_path>/bin/curl`, writes a shell stub, and calls `chmod(0o755)`; `:46–50`
prepends that directory to a **child-only** `PATH` inside a verified
test-owned temp root.

This does **not** authorize any other bin directory, executable fixture,
installer fixture, `deploy-install-worker.sh`, system `curl`, or any system /
installed artifact. Mutation of any other executable artifact — directly or
indirectly through a test or script — remains forbidden.

## 2. Containment facts verified (consent is still required)

These mechanisms show the inspected fixtures intend to stay in temp roots.
They are facts about the code, not permission.

- Per-test roots are pytest `tmp_path`; the path resolves below pytest's
  basetemp (normally `/tmp/pytest-of-<user>/pytest-<n>/<test>0`).
- Suite state is redirected before collection to
  `tempfile.mkdtemp(prefix="slo-test-home-")` (`tests/state_isolation.py:110–128`)
  and removed in `pytest_unconfigure` (`tests/conftest.py:26–29`).
- `FakeBin._assert_path_is_within_root` rejects any resolved path outside the
  fixture root; `write_regular_executable` rejects symlinks, unlinks only a
  regular file, writes a **new regular file**, then chmods
  (`tests/cli/test_install.py:295–327`).
- `FakeHerdrSpawnGuard` requires an absolute, non-symlink, single-link regular
  file below its root, an executable bit, and revalidates inode identity before
  spawn (`tests/state_isolation.py:58–99`); `fake_herdr` creates only
  `tmp_path/fake-herdr`, `capture.jsonl`, `barrier`
  (`tests/conftest.py:186–215`).
- No inspected fixture writes to `/usr`, `/etc`, `~/.local/bin`, or any
  PATH/system directory. `_add_passthrough_wrapper`
  (`tests/cli/test_install.py:329–342`) writes a temp-local regular wrapper
  that `exec`s the absolute real tool; it never symlinks a system binary.

Audit limit: the repository has 172 `chmod` call sites. This audit covered the
named test families plus a repo-wide search, not every site individually. Any
unlisted site must be treated as unauthorized until separately audited.

## 3. Other fixtures requiring explicit consent (default non-E2E suite)

`make test PYTEST_WORKERS=6` collects all of these (`tests/integration/` is not
E2E-marked; `pyproject.toml:129` excludes only `e2e`). Each row creates or
changes an executable regular file inside a test-owned temp root.

| # | Source (line refs) | Operation | Runtime temp path |
|---|---|---|---|
| 1 | `tests/conftest.py:186–215` (`fake_herdr`) | shebang script `0o700`; capture/barrier `0o600` | `<tmp_path>/fake-herdr`, `capture.jsonl`, `barrier` |
| 2 | `tests/cli/test_install.py:112–130, 452–453` | creates `<root>/bin`, fake HOME, call log | `<tmp_path>/bin`, `<tmp_path>/home with ' spaces` |
| 3 | `tests/cli/test_install.py:310–327` (`write_regular_executable`) | unlink + new regular script + `0o755` | any validated path below `FakeBin` root (e.g. `<tmp_path>/bin/<tool>`) |
| 4 | `tests/cli/test_install.py:329–342` (`_add_passthrough_wrapper`) | `0o755` wrapper exec'ing absolute host tool | `<tmp_path>/bin/{mkdir,grep,python3,…}` |
| 5 | `tests/cli/test_install.py:344–362` (`add`, `add_uname`) | `0o755` fake commands | `<tmp_path>/bin/<name>` |
| 6 | `tests/cli/test_install.py:175–208` (`make_pipx_venv`) | `0o755` python + `slo`/`slo-entry` launchers | `<tmp_path>/pipx-home/venvs/slo/bin/…` |
| 7 | `tests/cli/test_install.py:557–571` | `0o755` `apt-get` stub | `<tmp_path>/bin/apt-get` |
| 8 | `tests/cli/test_install.py:741–746` | `0o755` interpreter + `pyenv` stub | `<tmp_path>/pyenv/versions/3.11.7/bin/python3.11`, `<tmp_path>/bin/pyenv` |
| 9 | `tests/cli/test_install.py:848, 858, 1272` | `0o755` `pipx` stub | `<tmp_path>/bin/pipx` |
| 10 | `tests/cli/test_update.py:116–119` | `0o755` interpreter | `<tmp_path>/versions/3.11.7/bin/python3.11` |
| 11 | `tests/cli/test_update.py:538–565` | `0o755` `pipx` + `mktemp`; child-only PATH | `<tmp_path>/bin/{pipx,mktemp}` |
| 12 | `tests/cli/test_update.py:385–396` | refuses missing/symlinked installer; creates temp symlink | `<tmp_path>/…` |
| 13 | `tests/cli/test_isolated_launcher.py:13–47, 50–97, 114–119` | `0o755` entry launcher, wrapper, venv launchers, probe; child process | `<tmp_path>/pipx-home/venvs/slo/bin/…`, `<tmp_path>/pre-82/bin/…`, `<tmp_path>/fixture/…` |
| 14 | `tests/cli/test_isolated_launcher_layout.py:75, 178, 219, 296, 322, 337` | `0o755` pipx/python/mktemp fakes | `FakeBin` roots = `<tmp_path>` or `<tmp_path>/fixture` |
| 15 | `tests/cli/test_isolated_launcher_writer.py:47, 205` | launcher `0o755`; external data `0o640` | `FakeBin(root=tmp_path)`; `<tmp_path>/external` |
| 16 | `tests/cli/test_install_mirror.py:23, 32, 36` | `write_regular_executable` for pipx/git/python3.11 | shared `fake_bin` root = `<tmp_path>/bin` |
| 17 | `tests/cli/test_install_smoke_source.py:27–33` | `0o700` docker stub; child PATH `<tmp_path>:/usr/bin:/bin` | `<tmp_path>/docker`, `<tmp_path>/argv.json` |
| 18 | `tests/scheduling/test_runtime_helpers.py:215–224, 300–308` | wrapper `0o755`; scheduled child `0o700` | `<tmp_path>/venv/bin/slo`, `<tmp_path>/scheduled-child` |
| 19 | `tests/scheduling/test_os_integration.py:253–258` | `0o755` fake `slo` | `<tmp_path>/bin/slo` |
| 20 | `tests/tui/test_herdr_activation_composed.py:28–34` | `0o700` plain-slo candidate; PATH prefix | `<tmp_path>/slo` |
| 21 | `tests/tui/test_code_validation.py:78–90` | `0o700` editor wrapper + `nvim` symlink | `<tmp_path>/…/bin/editor-wrapper`, `…/bin/nvim` |
| 22 | `tests/integration/test_herdr_two_process_restore.py:44–61`; `herdr_restore_process_entry.py:78` | `0o700` shim/executable; supervised child | `<tmp_path>/slo` below `ProcessSafety` root |
| 23 | `tests/integration/test_herdr_restore_harness_safety.py:150, 153, 168, 428, 481, 569, 804, 847, 857–859, 912, 929` | `0o700`/`0o600`/`0o400` on shims, captures, victims | `<tmp_path>/…` and `ProcessSafety`-contained paths |
| 24 | `tests/cli/test_install_mirror_e2e.py:35–44` | `0o755` git wrapper (E2E-marked, excluded by default) | `<tmp_path>/bin/git` |

Non-executable mode changes also occur in the default suite (data files or
directories, still temp-owned): `tests/auth/test_credential_store.py:149`,
`tests/auth/test_credential_file_split.py:304–305`,
`tests/tui/test_messaging_failure_matrix.py:94`,
`tests/integrations/connectors/test_store.py:151`.

Real subprocess execution with a child-only fixture PATH (no mutation of the
real binary) occurs at `tests/cli/test_install.py:23, 258, 393–416, 1345`,
`tests/cli/test_update.py:572–579`, and
`tests/cli/test_isolated_launcher.py:149–158`.

## 4. Consent questions (blocking)

1. **C1:** Authorize the existing non-E2E modules in §3 rows 1–23 to create and
   `chmod` disposable fake executables and `bin/` directories **only** inside
   their verified pytest temp roots, with the child-only PATH prefix pattern?
2. **C2:** Authorize row 24 only if the E2E suite is explicitly run (the
   default `make test` excludes it)?
3. **C3:** Authorize the non-executable data/directory mode changes listed in
   §3 (still temp-owned)?
4. **C4:** Authorize the listed child-process executions of real `bash` against
   fixture PATHs (no real-system binary mutation)?

A “no” to any needed item leaves the affected gate **BLOCKED**. No test may be
excluded, re-marked, skipped, xfailed, or replaced by a focused total, and no
model change may be used to bypass consent.

## 5. Gate disposition

| Gate | Status |
|---|---|
| `make test PYTEST_WORKERS=6` | **BLOCKED** pending C1/C3/C4 |
| `make test-serial` | **BLOCKED** (same complete suite) |
| Focused A.2 tests | NOT YET WRITTEN / NOT YET AUDITED; must create no executable fixture |
| Any fixture or product edit | NOT AUTHORIZED here; none made |

This audit identifies proven blockers and its own limits. It does not certify
the suite, any fixture, or the system state beyond the inspected paths.
