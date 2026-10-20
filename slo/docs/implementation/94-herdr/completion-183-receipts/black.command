cwd=/root/Code/slo-94-herdr-integration/slo
python=/root/.pyenv/versions/slo-harness/bin/python
Python 3.11.7
test-env=fallback
command: poetry run black --check src/agents/slo_agent/herdr src/agents/slo_agent/sessions/identity.py src/agents/slo_agent/sessions/token_format.py src/agents/slo_agent/sessions/service.py src/agents/slo_agent/orchestrator/context_reader.py src/cli/app.py src/cli/typer_dispatch.py src/cli/headless.py src/tui/app.py src/tui/visualizer_launcher.py src/tui/workflows/renderer.py tests/agents/slo_agent/herdr tests/integration/test_herdr_full_flow.py tests/tui/test_startup_notice_cutoff.py tests/implementation_checks/test_conventions_audit_paths.py 
