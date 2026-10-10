"""Actual pre-feature schema-two reader against current writer bytes."""

import io
import json
import subprocess
import tarfile
from pathlib import Path

from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import ProviderName
from tests.compat.released_runner import REPOSITORY_ROOT, run_released_slo


def test_pre_feature_reader_accepts_actual_writer_bytes(tmp_path: Path) -> None:
    """Extract the fixed baseline, never current files, and parse every provider slice."""
    target = tmp_path / "baseline"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.mkdir()
    archive = subprocess.run(
        args=[
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "archive",
            "--format=tar",
            "ea8601c53f04fa06a0baeeb47d385c44cc9a5364",
            "slo",
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
        for member in bundle.getmembers():
            assert (target / member.name).resolve().is_relative_to(target.resolve())
            assert member.isfile() or member.isdir()
        bundle.extractall(path=target, filter="data")
    entry = SeedModelCatalog.load().entries["gpt-6-luna"]
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(provider=provider, entries=[entry]) for provider in ProviderName
        ]
    )
    path = tmp_path / "model_catalog_cache.v2.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert ModelCatalogStore.write_provider_cache(cache=cache, override_path=path).committed
    script = """
import json, os
from pathlib import Path
from src.agents.model_catalog.dao import ModelCatalogCacheDAO
path = Path(os.environ['COMPAT_CACHE_PATH']).resolve()
assert path.is_relative_to(Path(os.environ['SLO_HOME']).resolve())
cache = ModelCatalogCacheDAO.model_validate_json(path.read_text())
print(json.dumps({'schema_version': cache.schema_version,
                  'entries': [[row.model_name for row in part.entries] for part in cache.provider_slices]}))
"""
    result = run_released_slo(
        source=target / "slo",
        slo_home=tmp_path.resolve(),
        script=script,
        extra_env={"COMPAT_CACHE_PATH": str(path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.result == {"schema_version": "2", "entries": [["gpt-6-luna"] for _ in ProviderName]}
    assert "ValidationError" not in result.stdout + result.stderr
    legacy = run_released_slo(
        source=target / "slo",
        slo_home=tmp_path.resolve(),
        script="""
import json
from src.agents.model_catalog.seed import SeedModelCatalog
print(json.dumps(SeedModelCatalog.load().model_dump(mode='json')))
""",
    )
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    current = SeedModelCatalog.load().model_dump(mode="json")
    old_entries = legacy.result["entries"]
    assert isinstance(old_entries, dict)
    for name, old_entry in old_entries.items():
        new_entry = current["entries"][name]
        assert {
            key: value
            for key, value in new_entry.items()
            if key not in {"supports_chatgpt_codex", "requires_responses_api"}
        } == old_entry
        assert new_entry["supports_chatgpt_codex"] is True
        assert new_entry["requires_responses_api"] is False
    assert current["aliases"] == legacy.result["aliases"]
    assert current["templates"] == legacy.result["templates"]
    reasoning = run_released_slo(
        source=target / "slo",
        slo_home=tmp_path.resolve(),
        script="""
import json
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.reasoning_capabilities import resolve_reasoning_config
snapshot = SeedModelCatalog.load()
print(json.dumps({name: {level: resolve_reasoning_config(model_name=name,
    requested_level=level, snapshot=snapshot).model_dump(mode='json')
    for level in ('off','minimal','low','medium','high','xhigh','max')}
    for name in snapshot.entries}))
""",
    )
    assert reasoning.returncode == 0, reasoning.stdout + reasoning.stderr
    from src.agents.reasoning_capabilities import resolve_reasoning_config
    from src.agents.model_catalog.dao import ReasoningLevel
    from typing import cast

    snapshot = SeedModelCatalog.load()
    for name, levels in reasoning.result.items():
        assert isinstance(levels, dict)
        for level, expected in levels.items():
            assert (
                resolve_reasoning_config(
                    model_name=name, requested_level=cast(ReasoningLevel, level), snapshot=snapshot
                ).model_dump(mode="json")
                == expected
            )
    temperature = run_released_slo(
        source=target / "slo",
        slo_home=tmp_path.resolve(),
        script="""
import asyncio, json, httpx, os
os.environ["SLO_OPENAI_API_KEY"] = "fixture-openai-89"
from src.agents.base import LLMFactory
async def main():
    observations = []
    for temperature, extras in [(None, {"temperature": 0.3}), (1.0, {"temperature": 0.3}), (0.4, {}), (1.0, {})]:
        bodies = []
        def respond(request):
            assert str(request.url) == "https://api.openai.com/v1/chat/completions"
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"id":"chat_89_legacy","object":"chat.completion","created":1,
                "model":"gpt-5.4","choices":[{"index":0,"message":{"role":"assistant","content":"complete-89"},
                "finish_reason":"stop","logprobs":None}],"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            try:
                result = LLMFactory.create(model_name="gpt-5.4", reasoning_level="off", streaming=False,
                    temperature=temperature, model_kwargs=extras, http_async_client=client)
            except ValueError as error:
                assert "Found temperature supplied twice." in str(error)
                assert not bodies
                observations.append("collision")
                continue
            answer = await result.llm.ainvoke(input="hello")
            assert answer.content == "complete-89" and len(bodies) == 1
            assert bodies[0]["stream"] is False and "reasoning" not in bodies[0]
            observations.append([result.llm.temperature, bodies[0].get("temperature"), "temperature" in bodies[0]])
    print(json.dumps({"observations": observations}))
asyncio.run(main())
""",
    )
    assert temperature.returncode == 0, temperature.stdout + temperature.stderr
    assert temperature.result == {
        "observations": [[0.3, 0.3, True], "collision", [None, None, False], [1.0, 1.0, True]]
    }
    raw = json.loads(path.read_text())
    for part in raw["provider_slices"]:
        assert "supports_chatgpt_codex" not in part["entries"][0]
        assert "requires_responses_api" not in part["entries"][0]
