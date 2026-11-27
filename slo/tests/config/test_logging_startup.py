"""Fresh-process logging configuration through the CLI, TUI and headless sinks."""

from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

ROOT: Path = Path(__file__).resolve().parents[2]
PROBE: str = '''
import json
import logging
from contextlib import nullcontext
from pathlib import Path
import sys
import httpx
from config.logger import configure_app_file_logging, interactive_logging, log_debug
from src.cli.headless_logging import headless_logging
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.integrations.openrouter.exceptions import OpenRouterAPIError

home = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
assert home.is_dir()
context = nullcontext()
if mode == "cli":
    configure_app_file_logging(slo_home=home)
elif mode == "tui":
    context = interactive_logging(slo_home=home)
else:
    context = headless_logging(slo_home=home)

def respond(request: httpx.Request) -> httpx.Response:
    """Reject at the external HTTP boundary with synthetic private content."""
    return httpx.Response(400, json={"error": {"message": "PRIVATE_PAYLOAD", "type": "bad_request"}})

with context:
    logging.getLogger("slo").info("ordinary-info-marker")
    logging.getLogger("startup_probe").debug("root-debug-marker")
    log_debug(msg="explicit-debug-marker")
    logging.getLogger("uvicorn").debug("server-debug-marker")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model", model="vendor/model",
            api_key="PRIVATE_KEY", http_client=client, max_retries=0,
        )
        try:
            model.invoke(input="PRIVATE_PROMPT")
        except OpenRouterAPIError as error:
            print(json.dumps({"diagnostic_id": error.diagnostic_id}))
        else:
            raise AssertionError("expected provider rejection")
    for handler in logging.getLogger().handlers:
        handler.flush()
logging.shutdown()
'''


@pytest.mark.parametrize("mode", ["cli", "tui", "headless"])
@pytest.mark.parametrize("level", [None, "DEBUG"])
def test_startup_defaults_to_info_and_respects_explicit_debug(
    tmp_path: Path, mode: str, level: str | None
) -> None:
    """Real sinks retain safe provider diagnostics without leaking SDK payloads."""
    home: Path = tmp_path.resolve()
    environment: dict[str, str] = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "SLO_HOME": str(home),
        "SLO_ENV": "prod",
        "SLO_LOG_FORMAT": "text",
        "SLO_HERDR_DISABLED": "1",
        "SLO_AUTO_VISUALIZE": "0",
    }
    if level is not None:
        environment["SLO_LOG_LEVEL"] = level
    result = subprocess.run(
        args=[sys.executable, "-c", PROBE, str(home), mode],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    receipt: dict[str, str] = json.loads(result.stdout)
    log_path: Path = home / "logs" / "app.log"
    assert log_path.resolve().is_relative_to(home)
    content: str = log_path.read_text(encoding="utf-8")
    assert "ordinary-info-marker" in content
    assert ("explicit-debug-marker" in content) is (level == "DEBUG")
    assert ("server-debug-marker" in content) is (level == "DEBUG")
    assert ("root-debug-marker" in content) is (level == "DEBUG")
    assert receipt["diagnostic_id"] in content
    assert "OpenRouter failure" in content
    assert "ERROR" in content
    if mode == "tui":
        tui_log_path: Path = home / "logs" / "tui.log"
        assert tui_log_path.resolve().is_relative_to(home)
        tui_content: str = tui_log_path.read_text(encoding="utf-8")
        assert receipt["diagnostic_id"] in tui_content
        assert "OpenRouter failure" in tui_content
        assert "ERROR" in tui_content
        content += tui_content
    for secret in ("PRIVATE_PAYLOAD", "PRIVATE_KEY", "PRIVATE_PROMPT"):
        assert secret not in content + result.stdout + result.stderr
