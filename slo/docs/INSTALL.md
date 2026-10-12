# Installing, Updating & Hosting Slo

This guide is the **authoritative reference** for getting Slo onto a machine,
keeping it up to date, and hosting the one-line installer for end users. It
documents the real flags in [`install.sh`](../install.sh) and the `slo update`
command (`src/cli/update.py`).

> The narrative "Chapter 1" in [`README.md`](../README.md) predates the current
> installer (it describes an older clone-into-`~/.slo` editable flow). **This
> document supersedes it** for anything install-related.

---

## 1. Mental model

Slo installs as an **isolated [pipx](https://pipx.pypa.io) application**, built
straight from the public GitLab repo:

```
pipx install --force --python <python3.11> "git+https://gitlab.com/core-27/slo.git@<ref>#subdirectory=slo"
```

Two things follow from this:

- **Code vs. data are separate.** pipx owns the *code* (an isolated venv plus
  the `slo` binary on your `PATH`). `~/.slo` (a.k.a. `SLO_HOME`) is *runtime
  data only* — sessions, logs, and `global/authentication.json`. Install,
  upgrade, and uninstall never modify those. The installer creates the
  directory if missing; after a successful install it additionally owns
  **one non-secret file** there — the managed environment file
  `$HOME/.slo/shell/environment.sh` (see §2.1) — and bounded source blocks
  in your shell startup files. It never creates a checkout, never copies
  vendored skills into `~/.slo`, and never touches sessions, credentials,
  user skills, user workflows, or a legacy `~/.slo/skills` tree.
- **The project lives in a subdirectory.** The repo root has no
  `pyproject.toml`; the Python package is under `slo/`. That is why the pip
  requirement carries `#subdirectory=slo`.

---

## 2. `install.sh`

The installer is self-bootstrapping and idempotent — re-running it upgrades in
place, and every step is a no-op when already satisfied.

**What it does**

1. Ensures the toolchain pipx needs, using the native provider for the current OS:
   - **macOS:** **Homebrew → pipx → pyenv → Python 3.11.x → git**
   - **Debian / Ubuntu:** **apt (git + pyenv build deps) → pyenv (git clone) → Python 3.11.x → pipx (apt, with a `pip --user` fallback on older distros)**
   Each step installs only when absent; git is needed for pip's VCS fetch.
2. Resolves `SLO_HOME` (default `~/.slo`) and ensures it exists — as the data
   dir, not a checkout.
3. Runs `pipx install --force --python <interpreter> "git+…@<ref>#subdirectory=slo"`.
4. Finalises the persistent shell environment (only after a successful pipx
   install — see §2.1), then finalises the isolated user launcher. The launcher
   finalizer retains `<venv>/bin/python` in the wrapper even when a normal POSIX
   venv links it to a base interpreter outside the venv, but accepts that path
   only after executing it proves `sys.prefix` is exactly the validated venv
   root. It refuses outer venv-root symlinks, malformed or cyclic interpreter
   chains, altered launchers, and unsafe artifacts rather than overwriting them.

### 2.1 Persistent shell environment (the managed environment file)

A child process cannot export variables into the shell that ran
`curl … | bash`, so durable defaults need startup-file integration. After the
pipx install succeeds, the installer:

1. Resolves the installed package's **vendored skills directory** from
   distribution metadata — `pipx runpip slo show slo` → its `Location:` field →
   `<Location>/skills` — and requires a readable `INDEX.md` there. No Python
   version, pipx root, or checkout path is ever guessed; a metadata or
   validation failure aborts finalisation non-zero *before* any file changes.
2. Atomically writes the **managed environment file**
   `$HOME/.slo/shell/environment.sh` (mode `0644`, non-secret, marked
   `# >>> slo managed environment >>>` / `# <<< slo managed environment <<<`).
   It supplies *defaults only*:
   - `SLO_HOME` defaults to `$HOME/.slo`;
   - `SLO_SKILLS_DIR` defaults to the validated absolute vendored skills path;
   - `SLO_KB_DIR` defaults to `$KB_DIR`, else `$SLO_HOME/KnowledgeBase/KB`
     (the variable only — the directory is never created).
   A value you exported *before* the shell sources the file always wins —
   `config/cfg.py` keeps its explicit-environment-first precedence.
3. Reconciles one bounded **shell source block** in each supported startup
   file — `.bash_profile` (login Bash), `.bashrc` (interactive non-login
   Bash), `.zshenv` (all Zsh), and `.profile` (POSIX login fallback). The
   block only sources the managed file behind a readable guard; it never
   contains the resolved path. Unrecognised files, symlinks, and malformed or
   duplicate marker states are *refused, never overwritten*.

**Coverage boundary (deliberate):** supported interactive shells get the
defaults on their next start, and any shell they spawn inherits the exports.
Sterile processes — `env -i sh -c …`, `bash --noprofile --norc -c …`, cron,
services, GUI launchers — cannot be configured by an installer; they keep
`config/cfg.py`'s fallback resolution (explicit env → populated legacy
`$SLO_HOME/skills` → package-adjacent tree; KB: `SLO_KB_DIR` → `KB_DIR` →
`$SLO_HOME/KnowledgeBase/KB`) or need an explicit
`SLO_HOME` / `SLO_SKILLS_DIR`.

**Configuration (environment variables)**

| Variable | Default | Purpose |
|---|---|---|
| `SLO_REPO_URL` | `https://gitlab.com/core-27/slo.git` | Primary Git URL to install/update from |
| `SLO_REPO_FALLBACK_URL` | `https://github.com/slostack/slo.git` for the official primary | Mirror used when the primary is inaccessible; set empty to disable. Custom primaries have no default mirror. |
| `SLO_REF` | `main` | Branch / tag / commit to install — the source-of-truth ref selector |
| `SLO_VERSION` | unset | Compatibility selector: `dev` → `main`; any other value overrides `SLO_REF` |
| `SLO_REPO_SUBDIR` | `slo` | Subdirectory holding `pyproject.toml` (set empty for a root-level project) |
| `SLO_PYTHON_VERSION` | `3.11.7` | Pinned interpreter version |
| `SLO_OS_RELEASE_FILE` | `/etc/os-release` | Linux distro-detection file (test-only override) |

`bash install.sh --development` is an explicit alias for `SLO_REF=main`.

### 2.2 Public repository installation

The installer tries GitLab first. If pipx fails and a bounded `git ls-remote`
probe confirms that the primary is inaccessible, it retries **once** from
`https://github.com/slostack/slo.git`, keeping the same ref, Python interpreter,
and package subdirectory. If GitLab remains reachable, build, dependency and
missing-ref failures are returned without a mirror retry. If both attempts fail,
installation fails and launcher/shell finalization does not run.

Git probes have a 30-second deadline. Git HTTP fetches default to aborting after
30 seconds below one byte/second; existing `GIT_HTTP_LOW_SPEED_LIMIT` and
`GIT_HTTP_LOW_SPEED_TIME` overrides are respected. Git terminal prompting is
disabled so unattended installs do not wait for credentials.

Neither installation path reads API tokens, embeds them in VCS URLs, or persists
repository credentials. Existing Git credential helpers continue to work; legacy
Slo deploy-token variables and `GITHUB_SLOSTACK_TOKEN` are not automatically used
for Git fetches.

**Mirror access prerequisite:** anonymous fallback requires `slostack/slo` to be
public. If an operator keeps the mirror private, each installing machine must
already have Git authentication with read access (for example, an appropriately
scoped token configured through a secure Git credential helper). The GitLab
mirror's deploy key authorizes GitLab's pushes only, not end-user installations.

`SLO_REPO_FALLBACK_URL=''` disables fallback. A custom `SLO_REPO_URL` does not
fall back to the official mirror unless you explicitly configure a mirror URL.
An identical primary and fallback URL is never retried. A mirror may lag GitLab;
a missing ref on GitHub is an error, not permission to install another version.

This fallback applies to the code fetch after `install.sh` is available. It does
not make a GitLab-hosted installer download or third-party toolchain/dependency
services resilient. The supported hosted entry point remains `get-slo.sh`.

**Verification:** deterministic tests cover source switches and failure cutoffs.
For a real Git/pipx fetch/build/update smoke in disposable HOME and pipx roots:

```bash
SLO_MIRROR_INSTALL_E2E=1 poetry run pytest -o addopts='' \
  tests/cli/test_install_mirror_e2e.py -m e2e -v
```

This explicitly requested smoke uses network access, simulates GitLab failure at
the Git command boundary, and delegates GitHub operations to real Git. Python
3.11 and pipx must already be installed. A private mirror requires external Git
read authentication; no token is embedded by the test. It exercises code
installation, finalization, updater retries, CLI startup and release lookup,
not bare-machine provisioning or a published hosted installer.

### 2.3 Direct local run (operator / testing)

```bash
bash install.sh
```

Pin a release by adding `SLO_REF=v0.3.2`.

---

## 3. Production install: `curl | bash`

End users install with a single line. Both the bootstrap script and its Git
source are public, so installation requires no repository credentials.

### 3.1 Hosted at `get-slo.sh` (Cloudflare Worker)

`install.sh` is published as a Cloudflare Worker bound to `get-slo.sh`, serving
the script at both `/` and `/install.sh`. End users run:

```bash
curl -fsSL https://get-slo.sh/install.sh | bash
```

`curl -fsSL https://get-slo.sh | … bash` (no path) works too.

### 3.2 Pinning a release

- **Per install:** the user adds `SLO_REF=v0.3.2` to the command above.
- **Hosted default:** the deploy step can bake a default `SLO_REF` into the
  served script (`PUBLISH_SLO_REF=v0.3.2`), so `curl … | bash` installs that
  release by default while a user can still override `SLO_REF`. Bump the
  "stable channel" by re-deploying with a newer tag.

### 3.3 The deploy helper

`deploy-install-worker.sh` (operator tool) publishes the Worker via the
Cloudflare API with `curl` (no `wrangler`/Node needed). At a high level it:

1. Verifies the Cloudflare token can reach the account's Workers.
2. Fetches the **canonical public** `install.sh` from GitLab
   `core-27/slo@<SLO_SOURCE_REF>` (default `main`) — or publishes a local file
   when `INSTALL_SH` is set (testing).
3. Optionally pins the hosted default install ref (`PUBLISH_SLO_REF`).
4. base64-embeds the script in a Worker and uploads it.
5. Binds it to your hostname (auto-creating proxied DNS) or enables a
   `*.workers.dev` URL.

**Credential required:** `CF_API_TOKEN`, used only by the operator to deploy
the Worker. The deploy helper fetches the public source without a repository
token, and the generated installer contains no credentials.

Required Cloudflare API token permissions: **Account → Workers Scripts: Edit**,
and for a custom domain also **Zone → Zone: Read, DNS: Edit, Workers Routes:
Edit** scoped to the target zone.

---

## 4. Updating

`slo update` reinstalls via pipx using the **same mechanism and auth** as
`install.sh` (no git checkout in `~/.slo`):

| Command | Installs |
|---|---|
| `slo update` | The latest release tag (`vX.Y.Z`), resolved via `git ls-remote --tags` |
| `slo update --development` | `main` |
| `slo update --ref <ref>` | An explicit branch / tag / commit |

It uses GitLab first and the same GitHub fallback policy as the installer.
`SLO_REPO_URL` and `SLO_REPO_FALLBACK_URL` also apply to `slo update`. Latest-release
lookup retries `git ls-remote --tags --refs` on the mirror when the primary fails
or times out, then selects the highest numeric release tag. A reachable primary
with no release tags is an error, not an outage. Development and explicit-ref
updates retain their requested ref when switching sources. Your `~/.slo` data is
untouched. The private-mirror authentication prerequisite in §2.2 also applies.

**`slo update` finalizes the isolated launcher, then sets missing environment defaults.**
After a successful pipx reinstall, every mode runs the packaged
`<Location>/install.sh --finalize-launcher` before checking whether `SLO_HOME`,
`SLO_SKILLS_DIR`, and `SLO_KB_DIR` (or `KB_DIR`) exist. If any is missing, it
runs the just-installed `<Location>/install.sh --finalize-environment`, so the
installer stays the single writer of launcher and shell state. If all exist, shell files
are left untouched.

The user-facing `slo` launcher is a generated POSIX wrapper around the validated
pipx interpreter and `slo-entry` trampoline: it runs Python with `-I`, so hostile
`PYTHONPATH` and `PYTHONHOME` cannot select project modules before Slo imports.
This is import isolation, not environment scrubbing: ordinary `os.environ` values,
including `SLO_*` configuration and credentials, remain available to the initial
wrapped CLI process. Slo never requires, reads, or changes a target project's `.envrc`.

The installed scheduler consumes that same wrapper. This guarantee does not extend
unchanged to internal headless module launches: those use a **sanitized child
environment** and intentionally do not add `-I`. Likewise, the visualizer's
**trusted source fallback** is checkout-only and does not forward `PYTHONPATH`; it
is not a replacement for the installed product wrapper.

Direct `pipx install`, `upgrade`, or `reinstall` regenerates plain scripts and does
not run Slo launcher finalization. It is not a supported repair path. Re-run the
matching tagged public installer to restore the wrapper. A downgrade to a pre-82.a
release intentionally restores its historic plain launcher because it has no
`slo-entry`; isolation is restored only by reinstalling an 82.a+ release.

Existing variables are never changed. When an existing `SLO_SKILLS_DIR` has no
`INDEX.md` or differs from the skills just installed, `slo update` prints a
warning with the installed path; update or remove your own export. To refresh
the managed file by hand, run `bash <Location>/install.sh --finalize-environment`
(`pipx runpip slo show slo` prints `Location`).

You can always upgrade by simply re-running the installer
(`curl -fsSL https://get-slo.sh/install.sh | … bash`) instead.

> An already-installed copy carries whatever `update.py` shipped with it; after
> a launcher change, re-run the matching tagged public installer once to pick up the
> hardened updater and wrapper. Do not use a direct pipx command as repair.

---

## 5. Uninstalling

```bash
pipx uninstall slo
```

This removes the code venv and the `slo` binary. **Your `~/.slo` runtime data
(sessions, logs, credentials) survives** — delete it manually if you truly
want a clean slate. The managed environment file and shell source blocks are
inert once Slo is gone (the block guards on readability), and may be removed
by hand if desired.

> **pyenv shim shadowing.** If you also have a `slo` installed inside a pyenv
> virtualenv (e.g. a developer checkout), `which slo` may resolve to
> `~/.pyenv/shims/slo` *ahead* of pipx's `~/.local/bin/slo`, because pyenv's
> shims sit earlier on `PATH`. To run the pipx install explicitly, use
> `~/.local/bin/slo`, or remove the venv copy
> (`<venv>/bin/pip uninstall slo && pyenv rehash`).

---

## 6. Troubleshooting

Real failure modes (and fixes) seen while building this:

| Symptom | Cause | Fix |
|---|---|---|
| `Could not parse uv version … (rc=127)` | pipx auto-selects a `uv` backend but the `uv` on `PATH` is a broken pyenv shim | `install.sh`/`update.py` auto-fall back to `PIPX_DEFAULT_BACKEND=pip`; or set it yourself |
| `pyenv: python3.11: command not found` during install | The bare `python3.11` shim only resolves when 3.11.x is the *active* pyenv version | Handled — the installer passes the **absolute** interpreter (`$(pyenv root)/versions/<ver>/bin/python3.11`) |
| `ERROR: The Python ssl extension was not compiled` during `pyenv install` on Linux | pyenv build headers missing | Handled on Debian / Ubuntu — `slo_ensure_build_deps` apt-installs `libssl-dev` et al. before `pyenv install`; on non-Debian Linux, install pyenv's suggested build deps manually |
| `does not appear to be a Python project: neither setup.py nor pyproject.toml found` | The package is in the `slo/` subdirectory, not the repo root | Handled by `#subdirectory=slo`; override via `SLO_REPO_SUBDIR` |
| Cloudflare API `10000 Authentication error` on `/accounts/<id>/workers/...` | Valid token, but missing **Account → Workers Scripts: Edit** or the account isn't in the token's Account Resources | Add the permission + account scope to the token |
| Installed but `slo` runs the wrong build | pyenv shim shadows pipx on `PATH` | See §5 |

---

## 7. Quick reference

```bash
# End user, public install pinned to a release:
curl -fsSL https://get-slo.sh/install.sh | SLO_REF=v0.3.2 bash

# Update to the latest release:
slo update

# Update to main:
slo update --development

# Uninstall (keeps ~/.slo data):
pipx uninstall slo
```
