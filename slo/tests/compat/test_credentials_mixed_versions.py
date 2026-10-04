"""Real alternating credential stores preserve the other version's owned rows."""

from pathlib import Path

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from tests.compat.released_runner import run_released_slo
from tests.compat.released_scripts import RELEASED_LOAD_CREDENTIALS, RELEASED_PERSIST_CREDENTIAL


def test_load_when_new_slo_saved_openrouter_key_released_slo_keeps_working(
    released_slo_source: Path, isolated_slo_home: Path
) -> None:
    """Released Anthropic -> new OpenRouter -> released OpenAI preserves all keys."""
    saved = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script=RELEASED_PERSIST_CREDENTIAL,
        extra_env={"COMPAT_PROVIDER": "anthropic"},
    )
    assert saved.returncode == 0, saved.stderr
    store = CredentialStore()
    assert store.path == isolated_slo_home / "global/authentication.json"
    assert store.additional_providers_path.resolve().is_relative_to(isolated_slo_home)
    released_bytes = store.path.read_bytes()
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="or-new"
        )
    )
    assert store.path.read_bytes() == released_bytes
    additional_bytes = store.additional_providers_path.read_bytes()
    loaded = run_released_slo(
        source=released_slo_source, slo_home=isolated_slo_home, script=RELEASED_LOAD_CREDENTIALS
    )
    assert loaded.returncode == 0, loaded.stderr
    assert loaded.result == {"providers": ["anthropic"]}
    resaved = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script=RELEASED_PERSIST_CREDENTIAL,
        extra_env={"COMPAT_PROVIDER": "openai"},
    )
    assert resaved.returncode == 0, resaved.stderr
    assert store.additional_providers_path.read_bytes() == additional_bytes
    assert {provider.value: cred.access_token for provider, cred in store.load().providers.items()} == {
        "anthropic": "anthropic-released",
        "openai": "openai-released",
        "openrouter": "or-new",
    }
