env PYTHONPATH=/root/Code/slo-94-herdr-integration/slo poetry run pytest -m not\ e2e -q tests/agents/slo_agent/herdr tests/cli/test_herdr_restore.py tests/tui/test_herdr_session_lifecycle.py 
