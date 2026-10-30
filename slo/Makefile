.PHONY: help tui test test-serial smoke install-smoke lint format build-skill-index refresh-skills kb-snapshot install publish-installer release release-installer-smoke

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' | \
	  sort
	@echo ""
	@echo "  Usage: make <target> [VAR=value]"

# Open the Textual TUI (sub-spec 02.a). Equivalent to running `slo` directly.
tui:  ## Open the Textual TUI
	poetry run slo

# Tests source the dedicated test environment (environments/tests.env) when it
# exists locally. CI and clean checkouts reconstruct the same non-secret test
# contract through environment variables, so the default gate remains usable
# without creating a gitignored environment file.
PYTEST_WORKERS ?= auto

test-serial: PYTEST_WORKERS = 0
test-serial: test  ## Run the full non-E2E test suite without workers

test:  ## Run the full non-E2E test suite in parallel (PYTEST_WORKERS=0 for serial)
	@if [ -r ./environments/tests.env ]; then \
		set -a && . ./environments/tests.env && set +a; \
	else \
		export SLO_ENV=test SLO_ROOT_DIR="$(PWD)" SLO_APP_DIR="$(PWD)" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40; \
	fi; \
	export SLO_HERDR_DISABLED=1; \
	PYTHONPATH="$(PWD)" poetry run pytest -n $(PYTEST_WORKERS) -m "not e2e"

test-env:  ## Print whether make test will load tests.env or its clean-checkout fallback
	@if [ -r ./environments/tests.env ]; then echo "tests.env"; else echo "fallback"; fi

smoke:  ## Run smoke tests only
	@if [ -r ./environments/tests.env ]; then \
		set -a && . ./environments/tests.env && set +a; \
	else \
		export SLO_ENV=test SLO_ROOT_DIR="$(PWD)" SLO_APP_DIR="$(PWD)" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40; \
	fi; \
	export SLO_HERDR_DISABLED=1; \
	PYTHONPATH="$(PWD)" poetry run pytest -m "not e2e" tests/test_smoke.py -v

install-smoke:  ## Real public-installer Ubuntu/Debian smoke (needs Docker)
	SLO_INSTALL_E2E=1 poetry run pytest tests/cli/test_install_smoke.py -m e2e -v

lint:  ## Type-check src/ and tests/ with mypy
	poetry run mypy src/ tests/

format:  ## Auto-format src/ and tests/ with black
	poetry run black src/ tests/

# Regenerate skills/INDEX.md from the current skills/**/SKILL.md tree.
# Run by a developer after adding/editing a skill — never at runtime.
build-skill-index:  ## Regenerate skills/INDEX.md from committed skill files
	PYTHONPATH=$(PWD) poetry run python scripts/build_skill_index.py

# The authored tree is the source of truth. Refresh only its generated index;
# skill bodies, workflow definitions, samples and assets are never rewritten.
refresh-skills:  ## Rebuild INDEX.md from the current skills tree (preserves content)
	PYTHONPATH=$(PWD) poetry run python scripts/refresh_skills.py

# Install slo's code via pipx through install.sh (sub-spec 01.n), then
# finalise the non-secret managed environment file under ~/.slo/shell/ (spec 80).
# Code is never installed into ~/.slo — that directory is runtime data.
install:  ## Install slo locally via install.sh
	bash install.sh

# Publish install.sh to Cloudflare Worker on get-slo.sh.
# Reads CF credentials from environments/development.env.
# Caller-supplied source/publish refs are preserved. Release mode requires both
# to name the same tag and fetches `slo/install.sh` from that public tagged source.
#
# SLO_SOURCE_PATH is repo-root-relative, not relative to this Makefile. The
# Python project lives in the repo's `slo/` subdirectory, so the committed
# installer is at `slo/install.sh`. deploy-install-worker.sh defaults the path
# to a bare `install.sh`, which 404s against the raw GitLab URL and aborts the
# publish — pin it here so the target works without a manual override.
publish-installer:  ## Push install.sh to Cloudflare Worker (development publication unless release mode)
	set -e; set -a && . ./environments/development.env && set +a && \
	CF_ZONE_NAME="get-slo.sh" \
	SLO_HOSTNAME="get-slo.sh" \
	SLO_SOURCE_PATH="$${SLO_SOURCE_PATH:-slo/install.sh}" \
	SLO_SOURCE_REF="$${SLO_SOURCE_REF:-$$(t=$$(git tag --sort=-version:refname | head -1); echo "$${t:-main}")}" \
	PUBLISH_SLO_REF="$${PUBLISH_SLO_REF:-$$(t=$$(git tag --sort=-version:refname | head -1); echo "$${t:-main}")}" \
	bash deploy-install-worker.sh

release-installer-smoke:  ## Verify a tagged hosted installer after publication
	@test -n "$(VERSION)" || (echo "error: VERSION is required" >&2; exit 1)
	@SLO_HOSTED_INSTALL_E2E=1 SLO_RELEASE_TAG="$(VERSION)" SLO_INSTALL_URL="https://get-slo.sh/install.sh" poetry run pytest tests/cli/test_hosted_installer_smoke.py -m e2e -v

# Create and push a release tag. The GitLab tag pipeline is the only authority
# that publishes the installer, runs hosted release evidence, and creates the
# GitLab release after all required gates pass.
# Usage: make release VERSION=v0.5.0
release:  ## Tag and push a GitLab pipeline release candidate (usage: make release VERSION=vX.Y.Z)
	@test -n "$(VERSION)" || (echo "error: VERSION is required. Usage: make release VERSION=v0.x.y" >&2; exit 1)
	@bash -c '[[ "$$1" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)\.)*(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))?$$ ]]' -- "$(VERSION)" || (echo "error: VERSION must be a strict SemVer tag: vMAJOR.MINOR.PATCH with an optional prerelease; build metadata is not allowed." >&2; exit 1)
	@echo "→ tagging $(VERSION) on main"
	git checkout main && git pull origin main
	git tag -a "$(VERSION)" -m "Release $(VERSION)"
	git push origin "$(VERSION)"
	@echo "→ GitLab tag pipeline owns publication, hosted verification, and release creation for $(VERSION)"

# One-way mirror from the canonical KB source to SLO_KB_DIR. Run manually.
# Slo reads/writes only SLO_KB_DIR; edits to the local copy are NOT pushed back.
kb-snapshot:  ## Mirror canonical KB source into SLO_KB_DIR
	@test -n "$$SLO_KB_SOURCE" || (echo "SLO_KB_SOURCE not set" >&2; exit 1)
	@test -n "$$SLO_KB_DIR" || (echo "SLO_KB_DIR not set" >&2; exit 1)
	rsync -a --delete "$$SLO_KB_SOURCE/" "$$SLO_KB_DIR/"
