.PHONY: help tui test smoke install-smoke lint format build-skill-index refresh-skills kb-snapshot install publish-installer release

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' | \
	  sort
	@echo ""
	@echo "  Usage: make <target> [VAR=value]"

# Open the Textual TUI (sub-spec 02.a). Equivalent to running `slo` directly.
tui:  ## Open the Textual TUI
	poetry run slo

# Tests source the dedicated test environment (environments/tests.env).
test:  ## Run the full test suite
	set -a && . ./environments/tests.env && set +a && PYTHONPATH=$(PWD) poetry run pytest

smoke:  ## Run smoke tests only
	set -a && . ./environments/tests.env && set +a && PYTHONPATH=$(PWD) poetry run pytest tests/test_smoke.py -v

install-smoke:  ## Real public-installer Ubuntu/Debian smoke (needs Docker)
	SLO_INSTALL_E2E=1 poetry run pytest tests/cli/test_install_smoke.py -m e2e -v

lint:  ## Type-check src/ and tests/ with mypy
	poetry run mypy src/ tests/

format:  ## Auto-format src/ and tests/ with black
	poetry run black src/ tests/

# Regenerate skills/INDEX.md from the committed skills/<group>/<slug>/SKILL.md tree.
# Run by a developer after adding/editing a skill — never at runtime.
build-skill-index:  ## Regenerate skills/INDEX.md from committed skill files
	PYTHONPATH=$(PWD) poetry run python scripts/build_skill_index.py

# Refresh committed skills from the upstream awesome-agi prompt library, then
# rebuild the grouped index. Override SLO_CODE_PROMPTS_DIR when the upstream
# clone lives somewhere other than ~/Code/TS/awesome-agi/claude-md/code-prompts.
refresh-skills:  ## Pull upstream skills and rebuild INDEX.md
	PYTHONPATH=$(PWD) poetry run python scripts/refresh_skills.py
	$(MAKE) build-skill-index

# Install slo's code via pipx through install.sh (sub-spec 01.n), then
# finalise the non-secret managed environment file under ~/.slo/shell/ (spec 80).
# Code is never installed into ~/.slo — that directory is runtime data.
install:  ## Install slo locally via install.sh
	bash install.sh

# Publish install.sh to Cloudflare Worker on get-slo.sh.
# Reads CF credentials from environments/development.env.
# Automatically pins the latest release tag as the default SLO_VERSION.
# Re-run after any change to install.sh or after a new release to push the update.
#
# SLO_SOURCE_PATH is repo-root-relative, not relative to this Makefile. The
# Python project lives in the repo's `slo/` subdirectory, so the committed
# installer is at `slo/install.sh`. deploy-install-worker.sh defaults the path
# to a bare `install.sh`, which 404s against the raw GitLab URL and aborts the
# publish — pin it here so the target works without a manual override.
publish-installer:  ## Push install.sh to Cloudflare Worker (pins latest tag)
	set -a && . ./environments/development.env && set +a && \
	CF_ZONE_NAME="get-slo.sh" \
	SLO_HOSTNAME="get-slo.sh" \
	SLO_SOURCE_PATH="$${SLO_SOURCE_PATH:-slo/install.sh}" \
	PUBLISH_SLO_REF="$$(t=$$(git tag --sort=-version:refname | head -1); echo "$${t:-main}")" \
	bash deploy-install-worker.sh

# Create a new release tag off of main and publish it to GitLab.
# Usage: make release VERSION=v0.5.0
release:  ## Tag and publish a GitLab release  (usage: make release VERSION=vX.Y.Z)
	@test -n "$(VERSION)" || (echo "error: VERSION is required. Usage: make release VERSION=v0.x.y" >&2; exit 1)
	@echo "→ tagging $(VERSION) on main"
	git checkout main && git pull origin main
	git tag -a "$(VERSION)" -m "Release $(VERSION)"
	git push origin "$(VERSION)"
	@echo "→ creating GitLab release $(VERSION)"
	set -a && . ./environments/development.env && set +a && \
	curl -fsS -X POST \
	  --header "PRIVATE-TOKEN: $$SLO_GITLAB_PERSONAL_ACCESS_TOKEN" \
	  --header "Content-Type: application/json" \
	  --data "{\"name\":\"$(VERSION)\",\"tag_name\":\"$(VERSION)\",\"description\":\"Release $(VERSION)\"}" \
	  "https://gitlab.com/api/v4/projects/core-27%2Fslo/releases" \
	  | python3 -c "import json,sys; r=json.load(sys.stdin); print('✅ Release', r.get('tag_name'), 'created:', r.get('_links',{}).get('self',''))"

# One-way mirror from the canonical KB source to SLO_KB_DIR. Run manually.
# Slo reads/writes only SLO_KB_DIR; edits to the local copy are NOT pushed back.
kb-snapshot:  ## Mirror canonical KB source into SLO_KB_DIR
	@test -n "$$SLO_KB_SOURCE" || (echo "SLO_KB_SOURCE not set" >&2; exit 1)
	@test -n "$$SLO_KB_DIR" || (echo "SLO_KB_DIR not set" >&2; exit 1)
	rsync -a --delete "$$SLO_KB_SOURCE/" "$$SLO_KB_DIR/"
