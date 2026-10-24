"""Independent interpreter acceptance for native restore (not installed/live compatibility)."""

from pathlib import Path
import sys

import pytest

from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, ProcessSafety


def test_child_safety_bootstrap(tmp_path: Path) -> None:
    """A fresh interpreter must reject external writes, network and unregistered spawn."""
    safety = ProcessSafety(root=tmp_path)
    allowed = tmp_path / "child"
    safety.contained(path=allowed)
    allowed.mkdir()
    victim = tmp_path / "forbidden-write"
    safety.contained(path=victim)
    victim.write_bytes(b"parent-owned sentinel")
    before = victim.stat()
    probe = tmp_path / "probe.py"
    safety.contained(path=probe)
    probe.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"safety=ProcessSafety(root=Path({str(allowed)!r}), stdio=(1,2))\n"
        "safety.install()\n"
        f"safety.probe(victim=Path({str(victim)!r}))\n",
        encoding="utf-8",
    )
    result = OwnedProcessRun(root=tmp_path).run_supervised(
        args=[sys.executable, "-I", "-B", str(probe)],
        env={},
        timeout=20,
    )
    after = victim.stat()
    assert victim.read_bytes() == b"parent-owned sentinel"
    assert (after.st_dev, after.st_ino, after.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "safety-probe-ok" in result.stdout


def prepare_restore_process(*, root: Path, helper: Path) -> tuple[Path, dict[str, str], OwnedProcessRun]:
    """Prepare the parent-owned source shim and explicit child environment without executing it."""
    tmp_path = root
    safety = ProcessSafety(root=tmp_path)
    home = tmp_path / "state"
    safety.contained(path=home)
    home.mkdir(mode=0o700)
    shim = tmp_path / "slo"
    safety.contained(path=shim)
    shim.write_text(
        f"#!{sys.executable} -IB\nimport runpy,sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})\n"
        f"runpy.run_path({str(helper)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    safety.contained(path=shim)
    shim.chmod(0o700)
    owner = OwnedProcessRun(root=tmp_path)
    owner.safety.register_shim(path=shim)
    environment = {
        "HOME": str(home / "home"),
        "SLO_HOME": str(home),
        "T6_ROOT": str(tmp_path),
        "PATH": str(tmp_path),
    }
    owner.safety.validate_environment(env=environment)
    return shim, environment, owner


@pytest.mark.parametrize("policy", ["single", "pool"])
@pytest.mark.parametrize("capability", ["available", "refused", "trust_changed", "model_changed"])
def test_native_restore_in_independent_processes(tmp_path: Path, policy: str, capability: str) -> None:
    """Publish in one interpreter, consume its literal argv in another."""
    import json

    helper = Path(__file__).with_name("herdr_restore_process_entry.py").resolve()
    shim, environment, first_owner = prepare_restore_process(root=tmp_path, helper=helper)
    home = Path(environment["SLO_HOME"])
    environment["T6_POLICY"] = policy
    if capability == "model_changed":
        environment["T6_CAPABILITY"] = "model_supported"
    if capability == "trust_changed":
        from src.agents.slo_agent.plugins.trust import PluginTrustDAO

        trust_path = home / "home/.slo/trust.json"
        first_owner.safety.contained(path=trust_path)
        trust_path.parent.mkdir(parents=True)
        trust_path.write_text(PluginTrustDAO(trusted_projects=[str(home)]).model_dump_json())
    first = first_owner.run_supervised(
        args=[sys.executable, "-I", "-B", str(shim), "publish"],
        env=environment,
        timeout=60,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    argv = json.loads((tmp_path / "advertised.json").read_text())
    assert argv[0:2] == ["slo", "--resume"]
    assert len(argv) == 5 and argv[3] == "--herdr-restore"
    if capability == "trust_changed":
        assert (home / "untrusted-executed").exists(), "publisher must actually load trusted project code"
        first_owner.safety.contained(path=home / "untrusted-executed")
        (home / "untrusted-executed").unlink()
        first_owner.safety.contained(path=trust_path)
        trust_path.write_text(PluginTrustDAO(trusted_projects=[]).model_dump_json())
    environment.pop("T6_POLICY")
    environment["T6_CAPABILITY"] = capability
    second_owner = OwnedProcessRun(root=tmp_path)
    second_owner.safety = first_owner.safety
    second = second_owner.run_supervised(
        args=[sys.executable, "-I", "-B", str(shim), *argv[1:]],
        env=environment,
        timeout=60,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    published = json.loads((tmp_path / "published.json").read_text())
    restored = json.loads((tmp_path / "restored.json").read_text())
    assert published["pid"] != restored["pid"]
    assert restored["argv"] == argv
    expected_pool = None
    if policy == "pool":
        expected_pool = {
            "entries": [
                {
                    "model_name": "gpt-5.4",
                    "provider": "openai",
                    "priority": 9,
                    "cooldown_seconds": 77,
                    "rate_limit_cooldown_seconds": 13,
                },
                {
                    "model_name": "gpt-5.5",
                    "provider": "openai",
                    "priority": 2,
                    "cooldown_seconds": 91,
                    "rate_limit_cooldown_seconds": 17,
                },
            ]
        }
    expected_policy = {
        "session_id": argv[2],
        "model_name": "gpt-5.4",
        "reasoning_level": "high",
        "workdir": str(home),
        "workspace_file": str(home / "saved.code-workspace"),
        "plugin_paths": [str(home / "first.py"), str(home / "second.py")],
        "model_pool_dao": expected_pool,
    }
    assert restored["policy"] == expected_policy
    assert published["policy"] == expected_policy
    assert restored["public_admission"] == (
        "model_refused"
        if capability == "model_changed"
        else "credential_refused" if capability == "refused" else "not_attempted"
    )
    if capability == "model_changed":
        assert restored["reporting_state"] == {"state": "blocked", "block_reason": "Run failed; review Slo"}
        assert (
            "This model requires an OpenAI Platform API key; unavailable for ChatGPT/Codex. Run /auth."
            in restored["painted_error"]
        )
        assert "synthetic-offline-key" not in restored["painted_error"]
        assert str(home) not in restored["painted_error"]
    assert restored["events"] == published["events"]
    assert restored["model_calls"] == 0
    assert restored["visible_prompts"] == ["first offline prompt", "current history after advertisement"] + (
        ["explicit capability refusal probe"] if capability == "model_changed" else []
    )
    assert published["tool_results"] == 1
    assert published["factory_credentials_checked"] >= 1
    assert published["mutable_policy_changed"] is True
    assert restored["record_bytes"] == published["record_bytes"]
    history_path = home / "sessions/history" / argv[2] / "events.jsonl"
    assert [json.loads(line) for line in history_path.read_text().splitlines()] == restored["events"]
    commands = (tmp_path / "commands.jsonl").read_text()
    assert str(home) not in commands
    assert "synthetic-offline-key" not in commands
    assert restored["policy"]["reasoning_level"] == "high"
    assert restored["policy"]["workspace_file"] is not None
    assert len(restored["policy"]["plugin_paths"]) == 2
    assert restored["project_plugin_refused"] is True
    assert restored["capability"] == capability
    if policy == "pool":
        assert [entry["model_name"] for entry in restored["policy"]["model_pool_dao"]["entries"]] == [
            "gpt-5.4",
            "gpt-5.5",
        ]
