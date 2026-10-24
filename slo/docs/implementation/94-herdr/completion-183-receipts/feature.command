cwd=/root/Code/slo-94-herdr-integration/slo
python=/root/.pyenv/versions/slo-harness/bin/python
Python 3.11.7
test-env=fallback
command: poetry run pytest -m not\ e2e tests/agents/slo_agent/herdr tests/agents/slo_agent/test_token_format.py tests/agents/slo_agent/test_session_identity.py tests/agents/slo_agent/orchestrator/test_context_reader.py tests/cli/test_herdr_restore.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_visualizer.py tests/tui/test_startup_notice_cutoff.py tests/implementation_checks/test_conventions_audit_paths.py tests/integration/test_herdr_full_flow.py tests/integration/test_herdr_lifetime_matrix.py tests/integration/test_herdr_two_process_restore.py 
