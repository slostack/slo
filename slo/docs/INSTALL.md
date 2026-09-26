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
4. **Finalises the persistent shell environment** (only after a successful
   pipx install — see §2.1).

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
| `SLO_REPO_URL` | `https://gitlab.com/core-27/slo.git` | Public Git URL to install from |
| `SLO_REF` | `main` | Branch / tag / commit to install — the source-of-truth ref selector |
| `SLO_VERSION` | unset | Compatibility selector: `dev` → `main`; any other value overrides `SLO_REF` |
| `SLO_REPO_SUBDIR` | `slo` | Subdirectory holding `pyproject.toml` (set empty for a root-level project) |
| `SLO_PYTHON_VERSION` | `3.11.7` | Pinned interpreter version |
| `SLO_OS_RELEASE_FILE` | `/etc/os-release` | Linux distro-detection file (test-only override) |

`bash install.sh --development` is an explicit alias for `SLO_REF=main`.

### 2.2 Public repository installation

The installer installs from the public repository and does not read, inject,
or persist repository credentials. Existing deploy-token or personal-access-token
variables in the environment are ignored by `install.sh`.

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

It uses the public repository URL, like the installer. Your `~/.slo` data is
untouched.

**`slo update` sets missing environment defaults (supersedes 80.a.2).** After a
successful pipx reinstall, every mode checks whether `SLO_HOME`,
`SLO_SKILLS_DIR`, and `SLO_KB_DIR` (or `KB_DIR`) exist. If any is missing, it
runs the just-installed `<Location>/install.sh --finalize-environment`, so the
installer stays the single writer of shell state. If all exist, shell files
are left untouched.

Existing variables are never changed. When an existing `SLO_SKILLS_DIR` has no
`INDEX.md` or differs from the skills just installed, `slo update` prints a
warning with the installed path; update or remove your own export. To refresh
the managed file by hand, run `bash <Location>/install.sh --finalize-environment`
(`pipx runpip slo show slo` prints `Location`).

You can always upgrade by simply re-running the installer
(`curl -fsSL https://get-slo.sh/install.sh | … bash`) instead.

> An already-installed copy carries whatever `update.py` shipped with it; after
> a major installer change, run the installer once to pick up the new updater.
> In particular, the first `slo update` from 0.18.x or older still runs the old
> pipx-only updater; the environment check starts with the update after that,
> or run `bash <Location>/install.sh --finalize-environment` once.

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
