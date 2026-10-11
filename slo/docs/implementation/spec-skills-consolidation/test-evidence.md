# Step 1 test evidence

Application cwd: `/root/Code/slo/.worktrees/slo-spec-skills/slo`.
Baseline `ea8601c`, branch `feature-consolidate-spec-skills`.
Interpreter: `.python-version` selects `slo-harness`; `pyenv which python` returns
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. The older AGENTS venv
spelling `slo` is absent; no environment installation or system change was needed.
Commands use the repository Poetry entrypoint and `make test` test-env/fallback.
Full gates exported parent 10800 / child 7200; no agents were spawned.

## Exact commands and persistent logs

All logs below are in this directory. Each focused invocation used
`PYTHONPATH="$PWD" poetry run pytest -q <selection> > <log> 2>&1` and captured the
exit status before tailing. Full gates used the explicit command below.

| Selection / operation | Log | Result |
|---|---|---|
| tests/agents/skills/test_specification_authoring.py | depth-red.log | 1 failed, missing canonical depth section; expected RED |
| tests/agents/skills | depth-green.log | 1 failed, 17 passed; exact wording assertion exposed `or an` vs `not an`; corrected prose |
| tests/agents/skills | depth-green-final.log | 18 passed |
| tests/agents/skills/test_specification_authoring.py | author-red.log | 1 failed, 1 passed; missing ordered lifecycle; expected RED |
| tests/agents/skills | author-green.log | 19 passed |
| tests/agents/skills/test_specification_authoring.py | routing-red.log | 3 failed, 2 passed; redirects/workflow/depth-consumer absent; expected RED |
| tests/agents/skills | routing-green.log | 22 passed |
| tests/agents/skills/test_specification_authoring.py | refresh-red.log | 1 failed, 5 passed; actual writer deleted local files; expected RED |
| tests/agents/skills | refresh-green.log | 23 passed |
| tests/agents/skills | contracts.log | 25 passed |
| tests/agents/skills tests/agents/slo_agent/test_skills_loader.py | surrounding.log | 49 passed |
| tests/agents/skills/test_specification_authoring.py | final-contracts.log | 1 failed, 8 passed; added test mistakenly used `body` rather than existing `manual_body`; fixture corrected, no production workaround |
| tests/agents/skills tests/agents/slo_agent/test_skills_loader.py | surrounding-final.log | 50 passed, 2 warnings |
| make build-skill-index | index.log | 117 skills generated successfully |
| poetry run black scripts/refresh_skills.py tests/agents/skills/test_specification_authoring.py | format.log | completed |
| poetry run black --line-length 110 tests/agents/skills/test_specification_authoring.py scripts/refresh_skills.py | format-final.log | completed |
| make test | full.log + full.exit | 5310 passed, 18 deselected, 203 warnings, 360.16s; exit 0 |
| make test (after final source/test/documentation changes) | full-final.log + full-final.exit | **5311 passed, 18 deselected, 199 warnings, 354.30s; exit 0** |

Full command:

```bash
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200
make test > docs/implementation/spec-skills-consolidation/full-final.log 2>&1
result=$?
printf '%s\n' "$result" > docs/implementation/spec-skills-consolidation/full-final.exit
exit "$result"
```

`make test` sources `environments/tests.env` if present, otherwise its committed
clean-checkout fallback, then runs `PYTHONPATH="$PWD" poetry run pytest -m "not e2e"`.
18 existing E2E/default-disabled tests are deselected by that supported gate; none
were newly skipped, disabled or weakened. Warnings remain visible in full logs.

## Coverage map

- Canonical lifecycle order and retained report/gap artifacts: authoring contract test.
- Redirect paths, non-duplicated procedure and independent workflow handoff: hook/workflow tests.
- Advisory depth, caller obligations, hard extraction and language boundaries: depth and code-review tests.
- Refresh protected path plus ordinary upstream path: real `_write_skills` tests,
  using only resolved pytest temporary paths; no system binaries stubbed by new tests.
- Discovery and generated metadata: exact index equality against real SkillRegistry.
- Relative links and anchors: canonical author/reviewer/redirect destinations checked.
- Surrounding runtime discovery: actual SkillsLoader tests.
- Semantic preservation: manual baseline instruction inventory and final heading map
  in preservation-mapping.md; string assertions are NOT semantic proof.

## Limitations and disposition

No live provider calls, deployment, full upstream refresh, personal-skill edits,
commits or external publication. Packaging glob inspected (`skills/**/*` includes
all changed skills); opt-in wheel-build E2E was not run. No new runtime architecture.
Independent review and completion files are deliberately not authored by Step 1.
KB consulted read-only; durable notes recorded inside the worktree because user
prohibits writes outside it. Final receipt/checklist edits only follow the final gate.
