"""Safe guard units: never import the entry shim or execute the legacy probe."""

import os
from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
from unittest.mock import patch
from pathlib import Path

import pytest

from tests.integration.herdr_restore_process_bootstrap import ProcessSafety


@pytest.mark.parametrize(
    "operation",
    ["write_text", "touch", "chmod", "unlink", "replace_source", "replace_destination", "mkdir", "rmdir"],
)
def test_used_mutations_installed_guard(tmp_path: Path, operation: str) -> None:
    """Exercise actual entry/persistence syscalls; a broken guard touches only owned victims."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    parent = ProcessSafety(root=tmp_path)
    allowed, victim, directory = tmp_path / "allowed", tmp_path / "victim", tmp_path / "directory"
    for target in (allowed, victim, directory):
        parent.contained(path=target)
    allowed.mkdir()
    directory.mkdir()
    victim.write_bytes(b"sentinel")
    before = victim.stat()
    own = allowed / "own"
    parent.contained(path=own)
    own.write_bytes(b"owned")
    statements = {
        "write_text": "victim.write_text('bad')",
        "touch": "victim.touch()",
        "chmod": "victim.chmod(0o000)",
        "unlink": "victim.unlink()",
        "replace_source": "victim.replace(own)",
        "replace_destination": "own.replace(victim)",
        "mkdir": "(directory/'new').mkdir()",
        "rmdir": "directory.rmdir()",
    }
    script = tmp_path / "mutation.py"
    parent.contained(path=script)
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"victim=Path({str(victim)!r}); own=Path({str(own)!r}); directory=Path({str(directory)!r})\n"
        f"ProcessSafety(root=Path({str(allowed)!r}), stdio=(1,2)).install()\n"
        f"try:\n    {statements[operation]}\n"
        "except PermissionError: print('REFUSED')\n"
        "else: raise AssertionError('mutation admitted')\n",
        encoding="utf-8",
    )
    owner = OwnedProcessRun(root=tmp_path)
    result = owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=5)
    assert result.returncode == 0 and result.stdout == "REFUSED\n", result.stderr
    assert victim.read_bytes() == b"sentinel" and own.read_bytes() == b"owned"
    after = victim.stat()
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_mtime_ns,
    )
    assert directory.is_dir() and not (directory / "new").exists()


def test_generated_fake_disables_bytecode_before_guard_import(tmp_path: Path) -> None:
    """A fresh fake must not create repository pyc files before installing its guard."""
    import sys

    safety = ProcessSafety(root=tmp_path)
    capture = tmp_path / "capture"
    safety.contained(path=capture)
    capture.write_bytes(b"")
    source = safety.capture_script(path=capture)
    assert source.splitlines()[0] == f"#!{sys.executable} -IB"


@pytest.mark.parametrize("include_path", [True, False], ids=["owned-path", "old-missing-path"])
def test_parent_path_reaches_real_plain_slo_probe(tmp_path: Path, include_path: bool) -> None:
    """Use parent preparation and a guarded record-only child, never the product entry."""
    import sys
    from tests.integration.test_herdr_two_process_restore import prepare_restore_process

    safety = ProcessSafety(root=tmp_path)
    probe = tmp_path / "path_probe.py"
    safety.contained(path=probe)
    probe.write_text(
        "import os,sys,shutil\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"root=Path({str(tmp_path)!r})\n"
        "safety=ProcessSafety(root=root,stdio=(1,2))\nsafety.install()\n"
        "from src.agents.slo_agent.herdr.reporter import HerdrReporter\n"
        "available=HerdrReporter._plain_slo_available()\n"
        "discovered=shutil.which('slo')\n"
        "assert available and discovered==str(root/'slo')\n"
        "assert os.environ['PATH']==str(root)\n"
        "assert safety.executable is None\n"
        "try: safety.audit(event='subprocess.Popen',arguments=('slo',))\n"
        "except PermissionError: pass\n"
        "else: raise AssertionError('PATH granted execution')\n"
        "print('PLAIN_SLO_OK')\n",
        encoding="utf-8",
    )
    shim, environment, owner = prepare_restore_process(root=tmp_path, helper=probe)
    if not include_path:
        environment.pop("PATH")
    result = owner.run_supervised(args=[sys.executable, "-I", "-B", str(shim)], env=environment, timeout=10)
    if not include_path:
        assert result.returncode == 1 and "AssertionError" in result.stderr
        assert "PLAIN_SLO_OK" not in result.stdout
        return
    assert result.returncode == 0 and result.stdout == "PLAIN_SLO_OK\n", result.stderr
    assert shim.read_text().splitlines()[0] == f"#!{sys.executable} -IB"


@pytest.mark.parametrize(
    "case",
    ["outside", "relative", "empty", "multiple", "symlink", "substituted", "missing", "mode", "unregistered"],
)
def test_shim_path_refuses_before_discovery_or_spawn(tmp_path: Path, case: str) -> None:
    """All invalid PATH capabilities fail without launching even a contained child."""
    import subprocess
    import sys
    from tests.integration.test_herdr_two_process_restore import prepare_restore_process

    shim, environment, owner = prepare_restore_process(root=tmp_path, helper=Path(__file__))
    values = {
        "outside": str(tmp_path.parent),
        "relative": ".",
        "empty": "",
        "multiple": str(tmp_path) + ":/usr/bin",
    }
    if case in values:
        environment["PATH"] = values[case]
    if case in {"symlink", "substituted", "missing"}:
        saved = tmp_path / "saved"
        owner.safety.contained(path=saved)
        shim.rename(saved)
        if case == "symlink":
            shim.symlink_to(saved)
        if case == "substituted":
            owner.safety.contained(path=shim)
            shim.write_text("pass\n")
            shim.chmod(0o700)
    if case == "mode":
        owner.safety.contained(path=shim)
        shim.chmod(0o600)
    if case == "unregistered":
        owner.safety = ProcessSafety(root=tmp_path)
    with patch.object(subprocess, "Popen", side_effect=AssertionError("spawn reached")):
        with pytest.raises((PermissionError, AssertionError, FileNotFoundError)) as caught:
            owner.run_supervised(args=[sys.executable, "-I", "-B", str(shim)], env=environment, timeout=1)
    assert str(caught.value) != "spawn reached"


def test_wrong_named_shim_does_not_grant_path(tmp_path: Path) -> None:
    """A regular executable with another name is not a plain-slo capability."""
    safety = ProcessSafety(root=tmp_path)
    target = tmp_path / "other"
    safety.contained(path=target)
    target.write_text("pass\n")
    target.chmod(0o700)
    with pytest.raises(PermissionError, match="unexpected shim pathname"):
        safety.register_shim(path=target)
    with pytest.raises(PermissionError, match="unregistered shim PATH"):
        safety.validate_environment(env={"PATH": str(tmp_path)})


def test_safe_parent_probe_is_supervised(tmp_path: Path) -> None:
    """Run only the contained probe; no application entry or positive family."""
    import subprocess
    from tests.integration.test_herdr_two_process_restore import test_child_safety_bootstrap

    with patch.object(subprocess, "run", side_effect=AssertionError("legacy probe spawn")):
        test_child_safety_bootstrap(tmp_path=tmp_path)


def test_entry_preserves_parent_registered_shim() -> None:
    """The child must not overwrite the parent's admitted source-entry capability."""
    import ast

    source = Path(__file__).with_name("herdr_restore_process_entry.py").read_text()
    tree = ast.parse(source)
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "shim"
        and node.func.attr in {"write_text", "chmod", "unlink", "rename", "replace"}
    ]
    assert writes == []


@pytest.mark.parametrize("policy", ["single", "pool"])
def test_positive_parent_uses_supervised_requests_only(tmp_path: Path, policy: str) -> None:
    """Record both parent requests; never execute the positive entry or a provider."""
    import json
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun
    from tests.integration.test_herdr_two_process_restore import test_native_restore_in_independent_processes

    requests: list[tuple[list[str], dict[str, str], float]] = []
    advertised = [
        "slo",
        "--resume",
        "11111111-1111-4111-8111-111111111111",
        "--herdr-restore",
        "r1-" + "a" * 32,
    ]

    class RecordedRestore(Exception):
        """Stop before positive observations without starting a child."""

    def record(
        self: OwnedProcessRun, *, args: list[str], env: dict[str, str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Validate the real request and substitute only the publication observation."""
        self.validate_launch(args=args, env=env)
        requests.append((args.copy(), env.copy(), timeout))
        if len(requests) == 2:
            raise RecordedRestore
        target = tmp_path / "advertised.json"
        self.safety.contained(path=target)
        target.write_text(json.dumps(advertised), encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch.object(OwnedProcessRun, "run_supervised", new=record),
        patch.object(subprocess, "run", side_effect=AssertionError("legacy subprocess.run reached")),
        patch.object(subprocess, "Popen", side_effect=AssertionError("real child forbidden")),
    ):
        with pytest.raises(RecordedRestore):
            test_native_restore_in_independent_processes(
                tmp_path=tmp_path, policy=policy, capability="available"
            )
    first, second = requests
    shim = tmp_path / "slo"
    assert first[0] == [sys.executable, "-I", "-B", str(shim), "publish"]
    assert second[0] == [sys.executable, "-I", "-B", str(shim), *advertised[1:]]
    assert first[1] == {
        "HOME": str(tmp_path / "state/home"),
        "SLO_HOME": str(tmp_path / "state"),
        "T6_ROOT": str(tmp_path),
        "T6_POLICY": policy,
        "PATH": str(tmp_path),
    }
    assert second[1] == {key: value for key, value in first[1].items() if key != "T6_POLICY"} | {
        "T6_CAPABILITY": "available"
    }
    assert first[2] == second[2] == 60
    assert shim.is_file() and not shim.is_symlink() and shim.stat().st_nlink == 1


@pytest.mark.parametrize("old_writer", [True, False], ids=["old-behavior-red", "current-green"])
def test_generated_capture_substitution_supervised(tmp_path: Path, old_writer: bool) -> None:
    """The same preservation oracle detects old behavior and accepts the real writer."""
    import json
    import sys
    import time
    from concurrent.futures import ThreadPoolExecutor
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    parent = ProcessSafety(root=tmp_path)
    allowed = tmp_path / "allowed"
    parent.contained(path=allowed)
    allowed.mkdir()
    capture, victim, saved = allowed / "capture", tmp_path / "victim", allowed / "saved"
    ready, release, script = allowed / "ready", allowed / "release", allowed / "fake.py"
    for path, content in ((capture, b"capture"), (victim, b"VICTIM"), (ready, b""), (release, b"")):
        parent.contained(path=path)
        path.write_bytes(content)
    safety = ProcessSafety(root=allowed)
    generated = safety.capture_script(path=capture)
    instrumentation = (
        "import os,time\n"
        f"capture=Path({str(capture)!r})\nready=Path({str(ready)!r})\nrelease=Path({str(release)!r})\n"
        "original_open=os.open\n"
        "def paused_open(path: str | Path, flags: int, mode: int=0o777, *, dir_fd: int | None=None) -> int:\n"
        '    """Pause the validated capture syscall until the parent swaps its inode."""\n'
        "    if Path(path)==capture:\n"
        "        ready.write_text('VALIDATED')\n"
        "        deadline=time.monotonic()+5\n"
        "        while release.read_text()!='SWAPPED':\n"
        "            if time.monotonic()>deadline: raise TimeoutError('barrier')\n"
        "            time.sleep(0.005)\n"
        "    return original_open(path=path, flags=flags, mode=mode, dir_fd=dir_fd)\n"
        "os.open=paused_open\n"
    )
    if old_writer:
        # Controlled old semantics: pathname identity first, then append without
        # fstat. Only this disposable dummy loses the opened-FD check.
        instrumentation += (
            "def old_append(self: ProcessSafety, *, path: Path, identity: tuple[int,int], payload: bytes) -> None:\n"
            '    """Reproduce the old check-before-open weakness only in this dummy."""\n'
            "    self.contained(path=path)\n"
            "    metadata=path.stat()\n"
            "    assert (metadata.st_dev,metadata.st_ino)==identity\n"
            "    fd=os.open(path=path, flags=os.O_WRONLY|os.O_APPEND)\n"
            "    try: os.write(fd,payload)\n"
            "    finally: os.close(fd)\n"
            "ProcessSafety.append_capture=old_append\n"
        )
    generated = generated.replace("safety.install()\n", instrumentation + "safety.install()\n", 1)
    prefix, invocation = generated.split("safety.append_capture(", 1)
    generated = (
        prefix + "try:\n    safety.append_capture(" + invocation + "except PermissionError as error:\n"
        "    assert str(error)=='substituted capture descriptor'\n"
        "    print('REFUSED_BEFORE_WRITE')\n"
        "else:\n    print('WRITE_OCCURRED')\n"
        "if capture.read_bytes()!=b'VICTIM':\n"
        "    print('PRESERVATION_ORACLE_RED')\n    raise SystemExit(41)\n"
    )
    parent.contained(path=script)
    script.write_text(generated, encoding="utf-8")
    owner = OwnedProcessRun(root=tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            owner.run_supervised, args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=8
        )
        try:
            deadline = time.monotonic() + 5
            while ready.read_bytes() != b"VALIDATED":
                assert not future.done(), future.result() if future.done() else ""
                assert time.monotonic() < deadline, "validation barrier not reached"
                time.sleep(0.005)
            for path in (capture, saved, victim):
                parent.contained(path=path)
            capture.rename(saved)
            victim.rename(capture)
        finally:
            parent.contained(path=release)
            release.write_text("SWAPPED", encoding="utf-8")
        result = future.result(timeout=10)
    expected_status = 41 if old_writer else 0
    assert result.returncode == expected_status, result.stderr
    assert result.stderr == ""
    assert result.stdout == (
        "WRITE_OCCURRED\nPRESERVATION_ORACLE_RED\n" if old_writer else "REFUSED_BEFORE_WRITE\n"
    )
    assert saved.read_bytes() == b"capture"
    assert capture.read_bytes() == (b"VICTIM[]\n" if old_writer else b"VICTIM")
    assert list(json.loads((tmp_path / "reaped.json").read_text()).values()) == [expected_status]
    assert owner._supervisor_ready and owner._process is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


@pytest.mark.parametrize("substitution", [False, True])
def test_capture_open_identity_before_write(tmp_path: Path, substitution: bool) -> None:
    """A between-check/open swap can only touch a sibling owned by this test."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    capture = allowed / "capture"
    capture.write_bytes(b"old-capture")
    victim = tmp_path / "victim"
    victim.write_bytes(b"parent-victim")
    saved = allowed / "saved"
    identity = (capture.stat().st_dev, capture.stat().st_ino)
    safety = ProcessSafety(root=allowed)
    real_open = os.open

    def swapped_open(path: Path, flags: int) -> int:
        """Swap after admission, before syscall; never introduce a host path."""
        if substitution:
            capture.rename(saved)
            victim.rename(capture)
        return real_open(path=path, flags=flags)

    with patch.object(os, "open", swapped_open):
        if substitution:
            with pytest.raises(PermissionError):
                safety.append_capture(path=capture, identity=identity, payload=b"new")
        else:
            safety.append_capture(path=capture, identity=identity, payload=b"new")
    if substitution:
        assert saved.read_bytes() == b"old-capture"
        assert capture.read_bytes() == b"parent-victim"
    else:
        assert capture.read_bytes() == b"old-capturenew"
        assert victim.read_bytes() == b"parent-victim"


def test_generated_capture_script_supervised(tmp_path: Path) -> None:
    """Execute the same generated writer as publish, without importing product entry."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    capture = tmp_path / "capture"
    capture.write_bytes(b"old\n")
    script = tmp_path / "fake.py"
    safety = ProcessSafety(root=tmp_path)
    safety.contained(path=script)
    script.write_text(safety.capture_script(path=capture), encoding="utf-8")
    owner = OwnedProcessRun(root=tmp_path)
    result = owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=3)
    assert result.returncode == 0, result.stderr
    assert capture.read_bytes() == b"old\n[]\n"
    assert owner._process is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


@pytest.mark.parametrize("surface", ["popen", "run", "asyncio"])
@pytest.mark.parametrize("substitute", [False, True], ids=["registered", "substituted"])
def test_registered_execution_identity_supervised(tmp_path: Path, surface: str, substitute: bool) -> None:
    """Actual APIs execute only the registered inode, with no shell or PATH lookup."""
    import json
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    safety = ProcessSafety(root=tmp_path)
    dummy, replacement, script = tmp_path / "dummy", tmp_path / "replacement", tmp_path / "entry.py"
    capture = tmp_path / "capture"
    safety.contained(path=capture)
    capture.write_bytes(b"")
    for path in (dummy, replacement):
        safety.contained(path=path)
        path.write_text(safety.capture_script(path=capture), encoding="utf-8")
        path.chmod(0o700)
    metadata = dummy.stat()
    operations = {
        "popen": "process=subprocess.Popen(args=[str(dummy), 'registered']); assert process.wait()==0",
        "run": "assert subprocess.run(args=[str(dummy), 'registered'], check=True).returncode==0",
        "asyncio": "asyncio.run(child())",
    }
    source = (
        "import os,sys,subprocess,asyncio\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"dummy=Path({str(dummy)!r})\n"
        f"safety=ProcessSafety(root=Path({str(tmp_path)!r}), stdio=(1,2))\n"
        "safety.executable=dummy\n"
        f"safety.identity={(metadata.st_dev, metadata.st_ino)!r}\n"
        "safety.install()\n"
        "async def child() -> None:\n"
        '    """Wait the registered fake before publishing the execution receipt."""\n'
        "    process=await asyncio.create_subprocess_exec(str(dummy), 'registered')\n"
        "    assert await process.wait()==0\n"
    )
    if substitute:
        source += f"Path({str(replacement)!r}).replace(dummy)\n"
    source += (
        "try:\n"
        f"    {operations[surface]}\n"
        "except PermissionError as error:\n"
        "    assert str(error)=='substituted child'\n"
        "    print('REFUSED')\n"
        "else:\n    print('EXECUTED')\n"
    )
    safety.contained(path=script)
    script.write_text(source, encoding="utf-8")
    owner = OwnedProcessRun(root=tmp_path)
    result = owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == ("REFUSED\n" if substitute else "EXECUTED\n")
    assert capture.read_bytes() == (b"" if substitute else b'["registered"]\n')
    assert list(json.loads((tmp_path / "reaped.json").read_text()).values()) == [0]
    assert owner._supervisor_ready and owner._process is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


@pytest.mark.parametrize("surface", ["popen", "run", "asyncio", "exec", "spawn"])
def test_installed_execution_refusal_supervised(tmp_path: Path, surface: str) -> None:
    """Even a missing guard executes only an inert contained script in a supervised child."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    dummy = tmp_path / "dummy"
    dummy.write_text(f"#!{sys.executable}\nprint('BYPASS')\n", encoding="utf-8")
    dummy.chmod(0o700)
    metadata = dummy.stat()
    script = tmp_path / "entry.py"
    repo = Path(__file__).resolve().parents[2]
    operations = {
        "popen": "subprocess.Popen(args=[str(dummy)]).wait()",
        "run": "subprocess.run(args=[str(dummy)], check=True)",
        "asyncio": "asyncio.run(child())",
        "exec": "os.execv(str(dummy), [str(dummy)])",
        "spawn": "os.posix_spawn(str(dummy), [str(dummy)], {})",
    }
    script.write_text(
        "import os,sys,subprocess,asyncio\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"dummy=Path({str(dummy)!r})\n"
        f"safety=ProcessSafety(root=Path({str(tmp_path)!r}), stdio=(1,2))\n"
        "safety.executable=dummy\n"
        f"safety.identity={(metadata.st_dev, metadata.st_ino + 1)!r}\n"
        "safety.install()\n"
        "async def child():\n"
        "    process=await asyncio.create_subprocess_exec(str(dummy))\n"
        "    await process.wait()\n"
        "try:\n"
        f"    {operations[surface]}\n"
        "except PermissionError:\n"
        "    print('REFUSED')\n"
        "else:\n"
        "    raise AssertionError('missing execution guard')\n",
        encoding="utf-8",
    )
    owner = OwnedProcessRun(root=tmp_path)
    result = owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=3)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "REFUSED\n"
    assert owner._process is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


@pytest.mark.parametrize("kind", ["missing", "directory", "hardlink", "symlink", "outside", "traversal"])
def test_capture_refuses_unsafe_target(tmp_path: Path, kind: str) -> None:
    """Every unsafe spelling is confined to this test's parent-owned files."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"sentinel")
    capture = allowed / "capture"
    if kind == "directory":
        capture.mkdir()
    elif kind == "hardlink":
        os.link(src=victim, dst=capture)
    elif kind == "symlink":
        capture.symlink_to(victim)
    elif kind == "outside":
        capture = victim
    elif kind == "traversal":
        capture = allowed / ".." / "victim"
    with pytest.raises((PermissionError, FileNotFoundError, IsADirectoryError)):
        ProcessSafety(root=allowed).append_capture(path=capture, identity=(0, 0), payload=b"bad")
    assert victim.read_bytes() == b"sentinel"


@pytest.mark.parametrize("fault", ["hardlink", "disappeared", "replaced", "mode"])
def test_capture_opened_path_decisions(tmp_path: Path, fault: str) -> None:
    """Mutate only contained regular files after open and before first write admission."""
    safety = ProcessSafety(root=tmp_path)
    capture, saved, victim = (tmp_path / name for name in ("capture", "saved", "victim"))
    for path in (capture, saved, victim):
        safety.contained(path=path)
    capture.write_bytes(b"original")
    victim.write_bytes(b"victim")
    metadata = capture.stat()
    real_open = os.open
    opened: list[int] = []

    def change_after_open(path: Path, flags: int) -> int:
        """Place the deterministic barrier immediately after the real open syscall."""
        fd = real_open(path=path, flags=flags)
        opened.append(fd)
        if fault == "hardlink":
            os.link(src=capture, dst=saved)
        elif fault == "disappeared":
            capture.unlink()
        elif fault == "replaced":
            capture.rename(saved)
            victim.replace(capture)
        else:
            capture.chmod(0o400)
        return fd

    with patch.object(os, "open", new=change_after_open):
        if fault == "mode":
            safety.append_capture(path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"new")
        else:
            with patch.object(os, "write", side_effect=AssertionError("write after refusal")):
                with pytest.raises((PermissionError, FileNotFoundError)):
                    safety.append_capture(
                        path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"never"
                    )
    if fault in {"hardlink", "replaced"}:
        assert saved.read_bytes() == b"original"
    if fault == "replaced":
        assert capture.read_bytes() == b"victim"
    else:
        assert victim.read_bytes() == b"victim"
    if fault == "mode":
        assert capture.read_bytes() == b"originalnew" and capture.stat().st_mode & 0o777 == 0o400
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_capture_admission_reused_slot_is_not_closed(tmp_path: Path) -> None:
    """Refusal after descriptor inspection must not close a substituted owned-test FD."""
    safety = ProcessSafety(root=tmp_path)
    capture, victim = tmp_path / "capture", tmp_path / "victim"
    for path in (capture, victim):
        safety.contained(path=path)
        path.write_bytes(b"sentinel")
    metadata = capture.stat()
    replacement: list[int] = []
    real_close = os.close

    def substitute(*, fd: int) -> Path:
        """Reuse the capture slot only with a contained regular test victim."""
        real_close(fd)
        new_fd = os.open(path=victim, flags=os.O_WRONLY)
        assert new_fd == fd
        replacement.append(new_fd)
        raise PermissionError("substituted during admission")

    try:
        with patch.object(safety, "descriptor_path", side_effect=substitute):
            with pytest.raises(PermissionError, match="substituted during admission"):
                safety.append_capture(
                    path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"never"
                )
        assert replacement and os.fstat(replacement[0]).st_ino == victim.stat().st_ino
        assert capture.read_bytes() == victim.read_bytes() == b"sentinel"
    finally:
        for fd in replacement:
            try:
                real_close(fd)
            except OSError:
                pass


@pytest.mark.parametrize("fault", ["fstat", "write", "zero", "partial"])
def test_capture_descriptor_cleanup(tmp_path: Path, fault: str) -> None:
    """Failure and short-write paths close the exact opened capture descriptor."""
    capture = tmp_path / "capture"
    capture.write_bytes(b"old")
    identity = (capture.stat().st_dev, capture.stat().st_ino)
    real_open, real_write = os.open, os.write
    opened: list[int] = []

    def record_open(path: Path, flags: int) -> int:
        """Retain the syscall result for post-failure EBADF verification."""
        fd = real_open(path=path, flags=flags)
        opened.append(fd)
        return fd

    def write_chunk(fd: int, data: memoryview) -> int:
        """Exercise bounded progress or a deterministic write failure."""
        if fault == "write":
            raise OSError("injected")
        if fault == "zero":
            return 0
        return real_write(fd, data[:1])

    with ExitStack() as stack:
        stack.enter_context(patch.object(os, "open", record_open))
        stack.enter_context(patch.object(os, "write", write_chunk))
        if fault == "fstat":
            stack.enter_context(patch.object(os, "fstat", side_effect=OSError("injected")))
        if fault == "partial":
            ProcessSafety(root=tmp_path).append_capture(path=capture, identity=identity, payload=b"new")
        else:
            with pytest.raises(OSError):
                ProcessSafety(root=tmp_path).append_capture(path=capture, identity=identity, payload=b"new")
    assert capture.read_bytes() == (b"oldnew" if fault == "partial" else b"old")
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_capture_refusal_preserves_primary_on_close_error(tmp_path: Path) -> None:
    """A close fault cannot replace admission refusal or lose the private FD owner."""
    safety = ProcessSafety(root=tmp_path)
    capture = tmp_path / "capture"
    safety.contained(path=capture)
    capture.write_bytes(b"original")
    metadata = capture.stat()
    primary = PermissionError("admission refused")
    real_close = os.close
    closed: list[int] = []

    def fail_close(fd: int) -> None:
        """Leave only this invocation's owned descriptor open, then fail."""
        closed.append(fd)
        raise OSError("close failed")

    try:
        with (
            patch.object(safety, "descriptor_path", side_effect=primary),
            patch.object(os, "close", side_effect=fail_close),
            patch.object(os, "write") as write,
        ):
            with pytest.raises(PermissionError) as caught:
                safety.append_capture(
                    path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"bad"
                )
        assert caught.value is primary
        write.assert_not_called()
        assert capture.read_bytes() == b"original"
        assert len(closed) == 1
    finally:
        for fd in closed:
            real_close(fd)


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_capture_opened_nonregular_substitution(tmp_path: Path, kind: str) -> None:
    """Return a preopened owned nonblocking FD; no FIFO open can block or touch the host."""
    safety = ProcessSafety(root=tmp_path)
    capture, special = tmp_path / "capture", tmp_path / "special"
    for path in (capture, special):
        safety.contained(path=path)
    capture.write_bytes(b"original")
    metadata = capture.stat()
    if kind == "directory":
        special.mkdir()
        fd = os.open(path=special, flags=os.O_RDONLY | os.O_DIRECTORY | os.O_NONBLOCK)
    else:
        os.mkfifo(path=special, mode=0o600)
        fd = os.open(path=special, flags=os.O_RDWR | os.O_NONBLOCK)
    real_close = os.close
    try:
        with patch.object(os, "open", return_value=fd), patch.object(os, "write") as write:
            with pytest.raises(PermissionError, match="unsafe capture descriptor"):
                safety.append_capture(
                    path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"bad"
                )
        write.assert_not_called()
        assert capture.read_bytes() == b"original"
        with pytest.raises(OSError):
            os.fstat(fd)
    finally:
        try:
            real_close(fd)
        except OSError:
            pass


@pytest.mark.parametrize("refused", [False, True])
@pytest.mark.parametrize("disposition", ["open", "closed", "reused"])
def test_capture_close_error_dispositions(tmp_path: Path, refused: bool, disposition: str) -> None:
    """Retain exact close ownership, preserve primary, and never retry a reused slot."""
    safety = ProcessSafety(root=tmp_path)
    capture, victim = tmp_path / "capture", tmp_path / "victim"
    for path in (capture, victim):
        safety.contained(path=path)
        path.write_bytes(b"original")
    metadata = capture.stat()
    primary, close_error = PermissionError("refused"), OSError("close fault")
    real_close, real_open = os.close, os.open
    slots: list[int] = []

    def close(fd: int) -> None:
        """Inject only at the invocation-owned close; reuse a contained regular victim."""
        slots.append(fd)
        if disposition != "open":
            real_close(fd)
        if disposition == "reused":
            assert real_open(path=victim, flags=os.O_RDONLY) == fd
        raise close_error

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, "close", side_effect=close))
            if refused:
                stack.enter_context(patch.object(safety, "descriptor_path", side_effect=primary))
            with pytest.raises(OSError) as caught:
                safety.append_capture(
                    path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"new"
                )
            assert caught.value is (primary if refused else close_error)
            assert len(safety.retained_captures) == 1
            retained = safety.retained_captures[0]
            assert retained.identity == (metadata.st_dev, metadata.st_ino) and retained.ambiguous
            if disposition == "open":
                with pytest.raises(RuntimeError, match="ambiguous"):
                    retained.close()
            else:
                retained.close()
                assert retained.fd is None
            assert len(slots) == 1
        assert capture.read_bytes() == (b"original" if refused else b"originalnew")
        assert victim.read_bytes() == b"original"
        if disposition == "reused":
            assert os.fstat(slots[0]).st_ino == victim.stat().st_ino
    finally:
        if slots and disposition != "closed":
            real_close(slots[0])


@pytest.mark.parametrize("role", ["executable", "capture", "barrier"])
@pytest.mark.parametrize(
    "fault", ["relative", "traversal", "outside", "root", "directory", "symlink", "hardlink", "missing"]
)
def test_capture_registration_refusal_inventory(tmp_path: Path, role: str, fault: str) -> None:
    """Exercise the actual root guard before any delegation; all victims are test-owned."""
    from tests.state_isolation import FakeHerdrSpawnGuard

    safety = ProcessSafety(root=tmp_path)
    root = tmp_path / "registered"
    safety.contained(path=root)
    root.mkdir()
    paths = {name: root / name for name in ("executable", "capture", "barrier")}
    outside = tmp_path / "outside"
    for path in (*paths.values(), outside):
        safety.contained(path=path)
        path.write_bytes(b"sentinel")
    paths["executable"].chmod(0o700)
    target = paths[role]
    alternate = root / "alternate"
    safety.contained(path=alternate)
    if fault == "relative":
        paths[role] = Path(role)
    elif fault == "traversal":
        paths[role] = root / ".." / "registered" / role
    elif fault == "outside":
        paths[role] = outside
    elif fault == "root":
        paths[role] = root
    elif fault == "directory":
        alternate.mkdir()
        paths[role] = alternate
    elif fault == "symlink":
        alternate.symlink_to(target)
        paths[role] = alternate
    elif fault == "hardlink":
        os.link(src=target, dst=alternate)
    else:
        paths[role] = alternate
    guard = FakeHerdrSpawnGuard(root=root)
    with pytest.raises((AssertionError, FileNotFoundError)):
        guard.register(executable=paths["executable"], files=(paths["capture"], paths["barrier"]))
    with pytest.raises(AssertionError, match="Unregistered"):
        guard.require_registered(path=paths["executable"])
    assert outside.read_bytes() == target.read_bytes() == b"sentinel"


@pytest.mark.parametrize("role", ["executable", "capture", "barrier"])
@pytest.mark.parametrize(
    "fault", ["identity", "mode", "missing", "stat_error", "hardlink", "directory", "symlink"]
)
def test_capture_registration_revalidation_inventory(tmp_path: Path, role: str, fault: str) -> None:
    """Revalidate all registered identities; only executable owner-execute mode is policy."""
    from tests.state_isolation import FakeHerdrSpawnGuard

    safety = ProcessSafety(root=tmp_path)
    paths = {name: tmp_path / name for name in ("executable", "capture", "barrier")}
    for path in paths.values():
        safety.contained(path=path)
        path.write_bytes(b"sentinel")
        path.chmod(0o700 if path == paths["executable"] else 0o600)
    guard = FakeHerdrSpawnGuard(root=tmp_path)
    guard.register(executable=paths["executable"], files=(paths["capture"], paths["barrier"]))
    guard.require_registered(path=paths["executable"])
    target, saved = paths[role], tmp_path / "saved"
    safety.contained(path=saved)
    if fault == "identity":
        target.rename(saved)
        safety.contained(path=target)
        target.write_bytes(b"replacement")
        target.chmod(0o700)
    elif fault == "mode":
        target.chmod(0o400)
    elif fault == "missing":
        target.rename(saved)
    elif fault == "hardlink":
        os.link(src=target, dst=saved)
    elif fault in {"directory", "symlink"}:
        target.rename(saved)
        safety.contained(path=target)
        if fault == "directory":
            target.mkdir()
        else:
            target.symlink_to(saved)
    real_stat = Path.stat

    def inspected(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        """Inject one boundary I/O failure, not a fabricated errno taxonomy."""
        if path == target and fault == "stat_error":
            raise OSError("inspection failed")
        return real_stat(path, follow_symlinks=follow_symlinks)

    with patch.object(Path, "stat", new=inspected):
        if fault == "mode" and role != "executable":
            guard.require_registered(path=paths["executable"])
        else:
            with pytest.raises((AssertionError, OSError)):
                guard.require_registered(path=paths["executable"])
    assert (
        saved if fault in {"identity", "missing", "directory", "symlink"} else target
    ).read_bytes() == b"sentinel"


@pytest.mark.parametrize(
    "fault",
    [
        "root_missing",
        "root_error",
        "mode",
        "wrong_executable",
        "executable_error",
        "capture_error",
        "barrier_error",
    ],
)
def test_capture_registration_boundary_errors(tmp_path: Path, fault: str) -> None:
    """Construction/registration errors grant no capability and never execute a fallback."""
    from tests.state_isolation import FakeHerdrSpawnGuard

    safety = ProcessSafety(root=tmp_path)
    paths = tuple(tmp_path / name for name in ("executable", "capture", "barrier"))
    for path in paths:
        safety.contained(path=path)
        path.write_bytes(b"sentinel")
    executable, capture, barrier = paths
    executable.chmod(0o700)
    if fault.startswith("root_"):
        if fault == "root_missing":
            with pytest.raises(FileNotFoundError):
                FakeHerdrSpawnGuard(root=tmp_path / "missing")
        else:
            with patch.object(Path, "resolve", side_effect=OSError("root inspection")):
                with pytest.raises(OSError, match="root inspection"):
                    FakeHerdrSpawnGuard(root=tmp_path)
        return
    guard = FakeHerdrSpawnGuard(root=tmp_path)
    if fault == "wrong_executable":
        guard.register(executable=executable, files=(capture, barrier))
        with pytest.raises(AssertionError, match="Unregistered"):
            guard.require_registered(path=capture)
        return
    if fault == "mode":
        executable.chmod(0o600)
    real_stat = Path.stat
    failed_path = {"executable_error": executable, "capture_error": capture}.get(fault, barrier)

    def inspected(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        """Fail only a private registered file inspection, preserving all other I/O."""
        if fault.endswith("_error") and path == failed_path:
            raise OSError("registration inspection")
        return real_stat(path, follow_symlinks=follow_symlinks)

    with patch.object(Path, "stat", new=inspected):
        with pytest.raises((AssertionError, OSError)):
            guard.register(executable=executable, files=(capture, barrier))
    with pytest.raises(AssertionError, match="Unregistered"):
        guard.require_registered(path=executable)
    assert all(path.read_bytes() == b"sentinel" for path in paths)


@pytest.mark.parametrize("boundary", ["initial_fstat", "partial_write"])
def test_capture_primary_io_failure_with_close_failure(tmp_path: Path, boundary: str) -> None:
    """Keep the first I/O error; partial append is not rolled back or advertised as atomic."""
    safety = ProcessSafety(root=tmp_path)
    capture = tmp_path / "capture"
    safety.contained(path=capture)
    capture.write_bytes(b"original")
    metadata = capture.stat()
    primary = OSError("primary I/O")
    real_close, real_write = os.close, os.write
    slots: list[int] = []
    writes = 0

    def close(fd: int) -> None:
        """Keep the owned descriptor open for independent teardown."""
        slots.append(fd)
        raise OSError("close failure")

    def write(fd: int, data: memoryview) -> int:
        """Commit one byte before the next write fails."""
        nonlocal writes
        writes += 1
        if writes > 1:
            raise primary
        return real_write(fd, data[:1])

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, "close", side_effect=close))
            stack.enter_context(patch.object(os, "write", side_effect=write))
            if boundary == "initial_fstat":
                stack.enter_context(patch.object(os, "fstat", side_effect=primary))
            with pytest.raises(OSError) as caught:
                safety.append_capture(
                    path=capture, identity=(metadata.st_dev, metadata.st_ino), payload=b"new"
                )
            assert caught.value is primary
        assert len(slots) == len(safety.retained_captures) == 1
        retained = safety.retained_captures[0]
        assert retained.fd == slots[0] and retained.ambiguous
        with patch.object(os, "close") as retry:
            with pytest.raises(RuntimeError, match="ambiguous"):
                retained.close()
            retry.assert_not_called()
        assert capture.read_bytes() == (b"original" if boundary == "initial_fstat" else b"originaln")
    finally:
        for fd in slots:
            real_close(fd)


@contextmanager
def patched_descriptors(*, safety: ProcessSafety) -> Iterator[None]:
    """Restore each syscall patch without ambiguous patch.multiple keywords."""
    with ExitStack() as stack:
        for name, wrapper in safety.descriptor_wrappers().items():
            stack.enter_context(patch.object(target=os, attribute=name, new=wrapper))
        yield


@pytest.mark.parametrize("event", ["open", "os.chmod", "os.truncate"])
def test_descriptor_mutation_refuses_parent_victim(tmp_path: Path, event: str) -> None:
    """Admission must refuse an already-open sibling without changing its bytes or mode."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"unchanged")
    before = victim.stat()
    with victim.open("r+b") as stream:
        arguments = (stream.fileno(), "w", os.O_WRONLY) if event == "open" else (stream.fileno(), 0)
        with pytest.raises(PermissionError):
            ProcessSafety(root=allowed).audit(event=event, arguments=arguments)
    assert victim.read_bytes() == b"unchanged"
    after = victim.stat()
    assert (after.st_dev, after.st_ino, after.st_mode) == (before.st_dev, before.st_ino, before.st_mode)


def test_owned_descriptor_is_admitted(tmp_path: Path) -> None:
    """A normal private regular descriptor retains write admission."""
    victim = tmp_path / "private"
    victim.write_bytes(b"owned")
    with victim.open("r+b") as stream:
        ProcessSafety(root=tmp_path).audit(event="open", arguments=(stream.fileno(), "w", os.O_WRONLY))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "traversal"])
def test_unsafe_path_is_refused(tmp_path: Path, kind: str) -> None:
    """All link targets are fresh temp-owned files, never host files."""
    victim = tmp_path / "victim"
    victim.write_bytes(b"owned")
    target = tmp_path / "alias"
    if kind == "symlink":
        target.symlink_to(victim)
    elif kind == "hardlink":
        os.link(src=victim, dst=target)
    else:
        target = tmp_path / ".." / tmp_path.name / "victim"
    with pytest.raises(PermissionError):
        ProcessSafety(root=tmp_path).audit(event="open", arguments=(str(target), "w", os.O_WRONLY))
    assert victim.read_bytes() == b"owned"


@pytest.mark.parametrize("event", ["os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.rename", "os.link"])
def test_dirfd_mutations_refuse_sibling(tmp_path: Path, event: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative names must use the syscall directory, not the current directory."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"sentinel")
    monkeypatch.chdir(allowed)
    fd = os.open(path=tmp_path, flags=os.O_RDONLY | os.O_DIRECTORY)
    try:
        arguments = {
            "os.mkdir": ("victim", 0o700, fd),
            "os.remove": ("victim", fd),
            "os.rmdir": ("victim", fd),
            "os.chmod": ("victim", 0o600, fd),
            "os.rename": ("victim", "destination", fd, fd),
            "os.link": ("victim", "destination", fd, fd),
        }[event]
        with pytest.raises(PermissionError):
            ProcessSafety(root=allowed).audit(event=event, arguments=arguments)
    finally:
        os.close(fd)
    assert victim.read_bytes() == b"sentinel"


@pytest.mark.parametrize(
    "event", ["os.exec", "os.posix_spawn", "os.fork", "os.forkpty", "os.system", "subprocess.Popen"]
)
def test_alternate_execution_denied(tmp_path: Path, event: str) -> None:
    """Audit decisions never execute the dummy script, even on a failing assertion."""
    dummy = tmp_path / "dummy"
    dummy.write_text("# inert regular fixture\n")
    with pytest.raises(PermissionError):
        ProcessSafety(root=tmp_path).audit(event=event, arguments=(str(dummy), [], None, {}))


@pytest.mark.parametrize("operation", ["write", "ftruncate", "fchmod"])
def test_fd_syscall_wrapper_denies_before_mutation(tmp_path: Path, operation: str) -> None:
    """Even a broken wrapper can affect only this newly created sibling victim."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"sentinel")
    before = victim.stat()
    safety = ProcessSafety(root=allowed)
    with victim.open("r+b") as stream, patched_descriptors(safety=safety):
        with pytest.raises(PermissionError):
            getattr(os, operation)(stream.fileno(), b"bad" if operation == "write" else 0)
    after = victim.stat()
    assert victim.read_bytes() == b"sentinel"
    assert (after.st_ino, after.st_mode) == (before.st_ino, before.st_mode)


def test_open_dirfd_wrapper_refuses_before_truncation(tmp_path: Path) -> None:
    """The open audit event omits dir_fd, so the syscall wrapper must supply it."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"sentinel")
    fd = os.open(path=tmp_path, flags=os.O_RDONLY | os.O_DIRECTORY)
    try:
        safety = ProcessSafety(root=allowed)
        with patch.object(os, "open", safety.open_wrapper()):
            with pytest.raises(PermissionError):
                os.open(path="victim", flags=os.O_WRONLY | os.O_TRUNC, dir_fd=fd)
    finally:
        os.close(fd)
    assert victim.read_bytes() == b"sentinel"


def test_stdio_permission_does_not_grant_file_mutation(tmp_path: Path) -> None:
    """Explicit stream identity allows writes only, not chmod/truncate."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    sink = tmp_path / "capture"
    sink.write_bytes(b"capture")
    with sink.open("ab") as stream:
        safety = ProcessSafety(root=allowed, stdio=(stream.fileno(),))
        with patched_descriptors(safety=safety):
            os.write(stream.fileno(), b"+")
            with pytest.raises(PermissionError):
                os.ftruncate(stream.fileno(), 0)
    assert sink.read_bytes() == b"capture+"


def test_registered_executable_link_substitution_refused(tmp_path: Path) -> None:
    """Same-inode symlink substitution must not satisfy executable registration."""
    dummy = tmp_path / "dummy"
    dummy.write_text("# inert fixture\n")
    safety = ProcessSafety(root=tmp_path)
    safety.executable = dummy
    metadata = dummy.stat()
    safety.identity = (metadata.st_dev, metadata.st_ino)
    safety.audit(event="subprocess.Popen", arguments=(str(dummy), [], None, {}))
    alias = tmp_path / "alias"
    os.link(src=dummy, dst=alias)
    with pytest.raises(PermissionError):
        safety.audit(event="subprocess.Popen", arguments=(str(dummy), [], None, {}))


def test_install_registers_guards_without_running_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture installation hooks reversibly; never install a permanent pytest audit hook."""
    import sys

    hooks: list[object] = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    safety = ProcessSafety(root=tmp_path)
    original_open = os.open
    with patch.object(os, "open"), patched_descriptors(safety=safety):
        safety.install()
        assert hooks == [safety.audit]
        assert os.open is not original_open


def test_relative_open_passes_absolute_path_to_audit(tmp_path: Path) -> None:
    """Exercise the real open wrapper with the audit callback at its syscall seam."""
    safety = ProcessSafety(root=tmp_path)
    fd = os.open(path=tmp_path, flags=os.O_RDONLY | os.O_DIRECTORY)
    original = os.open

    def audited_open(
        path: str | bytes | os.PathLike[str], flags: int, mode: int, *, dir_fd: int | None
    ) -> int:
        """Model CPython's omitted dir_fd audit arguments before a real safe syscall."""
        safety.audit(event="open", arguments=(path, None, flags))
        return original(path, flags, mode, dir_fd=dir_fd)

    try:
        with patch.object(os, "open", audited_open):
            wrapper = safety.open_wrapper()
        opened = wrapper("contained", os.O_CREAT | os.O_WRONLY, dir_fd=fd)
        os.close(opened)
    finally:
        os.close(fd)
    assert (tmp_path / "contained").is_file()


@pytest.mark.parametrize("event", ["os.chown", "os.utime", "os.setxattr", "os.removexattr"])
def test_metadata_mutation_refuses_sibling(tmp_path: Path, event: str) -> None:
    """Policy-only negatives never invoke privileged or unsupported metadata syscalls."""
    allowed = tmp_path / "child"
    allowed.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"unchanged")
    with pytest.raises(PermissionError):
        ProcessSafety(root=allowed).audit(event=event, arguments=(str(victim), 0, 0, -1))
    assert victim.read_bytes() == b"unchanged"


@pytest.mark.parametrize("case", ["command", "flags", "secret", "herdr", "missing"])
def test_process_launch_refused_before_spawn(tmp_path: Path, case: str) -> None:
    """Refuse unsafe inputs without executing any negative candidate."""
    import sys
    import subprocess
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    script = tmp_path / "dummy.py"
    ProcessSafety(root=tmp_path).contained(path=script)
    script.write_text("# inert\n")
    args = [sys.executable, "-I", "-B", str(script)]
    env: dict[str, str] = {}
    if case == "command":
        args[0] = "unapproved-dummy"
    elif case == "flags":
        args[1] = "-c"
    elif case == "secret":
        env["API_KEY"] = "synthetic-only"
    elif case == "herdr":
        env["hErDr_PANE_ID"] = "synthetic-only"
    else:
        args[3] = str(tmp_path / "missing.py")
    with patch.object(subprocess, "Popen") as spawn:
        with pytest.raises((PermissionError, FileNotFoundError)):
            OwnedProcessRun(root=tmp_path).run_supervised(args=args, env=env, timeout=1)
    spawn.assert_not_called()


@pytest.mark.parametrize("timeout_case", [False, True])
def test_actual_owned_python_child(tmp_path: Path, timeout_case: bool) -> None:
    """Run only a contained finite dummy; real waitpid proves direct-child reaping."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    script = tmp_path / "finite_dummy.py"
    safety = ProcessSafety(root=tmp_path)
    safety.contained(path=script)
    repo = Path(__file__).resolve().parents[2]
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"ProcessSafety(root=Path({str(tmp_path)!r}), stdio=(1,2)).install()\n"
        "assert not any(k.upper().startswith('HERDR_') for k in os.environ)\n"
        "assert os.environ.get('SLO_HERDR_DISABLED') == '1'\n"
        "print('dummy-out', flush=True)\nprint('dummy-err', file=sys.stderr, flush=True)\n"
        + ("time.sleep(2)\n" if timeout_case else "")
    )
    owner = OwnedProcessRun(root=tmp_path)
    args = [sys.executable, "-I", "-B", str(script)]
    if timeout_case:
        with pytest.raises(subprocess.TimeoutExpired) as failure:
            owner.run_supervised(args=args, env={}, timeout=1)
        assert failure.value.output == b"dummy-out\n"
        assert failure.value.stderr == b"dummy-err\n"
    else:
        result = owner.run_supervised(args=args, env={}, timeout=3)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "dummy-out\n"
        assert result.stderr == "dummy-err\n"
    assert owner._process is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


@pytest.mark.parametrize("startup_allowance", [0.0, 0.5])
def test_actual_owned_python_child_budget_ordering(tmp_path: Path, startup_allowance: float) -> None:
    """Release real guarded work only when its parent wait covers execution and cleanup."""
    import json
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    release = tmp_path / "release"

    class ReleaseOnEnclosingWait(OwnedProcessRun):
        """Make budget ordering, rather than scheduler speed, admit legitimate completion."""

        def wait_supervisor(self, *, process: subprocess.Popen[str], timeout: float) -> None:
            """Check the enclosing budget before releasing the contained workload."""
            assert timeout == 1 + startup_allowance + 5
            assert self.retained is not None
            wrapper = (self.retained.directory / "supervisor.py").read_text()
            assert f"timeout={1 + startup_allowance!r},ready_fd=" in wrapper
            self.safety.contained(path=release)
            release.touch()
            super().wait_supervisor(process=process, timeout=timeout)

    owner = ReleaseOnEnclosingWait(root=tmp_path)
    script = tmp_path / "budget.py"
    owner.safety.contained(path=script)
    script.write_text(
        "import sys,time,os\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"ProcessSafety(root=Path({str(tmp_path)!r}),stdio=(1,2)).install()\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(.005)\n"
        "print(os.getpid(),flush=True)\n"
    )
    allowance = {"startup_allowance": startup_allowance} if startup_allowance else {}
    result = owner.run_supervised(
        args=[sys.executable, "-I", "-B", str(script)],
        env={},
        timeout=1.0,
        **allowance,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "reaped.json").read_text())[result.stdout.strip()] == 0
    assert owner.retained is None
    assert owner._process is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


@pytest.mark.parametrize("mode", ["early", "timeout", "ignore"])
def test_supervisor_reaps_real_descendants(tmp_path: Path, mode: str) -> None:
    """Only disposable Python descendants run; wait receipts identify each reaped PID."""
    import json
    import subprocess
    import sys

    from tests.integration import herdr_restore_process_bootstrap as bootstrap

    assert hasattr(bootstrap, "OwnedSupervisor")
    safety = ProcessSafety(root=tmp_path)
    child, leader, wrapper = [tmp_path / name for name in ("child.py", "leader.py", "wrapper.py")]
    for path in (child, leader, wrapper):
        safety.contained(path=path)
    child.write_text(
        "import os,signal,time\nfrom pathlib import Path\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if mode == "ignore" else "")
        + f"Path({str(tmp_path / 'ready')!r}).write_text(str(os.getpid()))\n"
        + "time.sleep(4)\n"
    )
    leader.write_text(
        "import os,subprocess,sys,time\nfrom pathlib import Path\n"
        f"p=subprocess.Popen([sys.executable,'-I','-B',{str(child)!r}])\n"
        f"ready=Path({str(tmp_path / 'ready')!r})\n"
        "while not ready.exists(): time.sleep(.005)\n"
        "print('leader-ready',flush=True)\n" + ("time.sleep(4)\n" if mode != "early" else "")
    )
    repo = Path(__file__).resolve().parents[2]
    wrapper.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(repo)!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor\n"
        f"raise SystemExit(OwnedSupervisor(root=Path({str(tmp_path)!r})).invoke("
        f"args=[sys.executable,'-I','-B',{str(leader)!r}],timeout=.5))\n"
    )
    sentinel = tmp_path / "sentinel.py"
    safety.contained(path=sentinel)
    sentinel.write_text(
        "import os,time\nfrom pathlib import Path\n"
        f"Path({str(tmp_path / 'sentinel-ready')!r}).write_text(str(os.getpid()))\n"
        f"stop=Path({str(tmp_path / 'sentinel-stop')!r})\n"
        "deadline=time.monotonic()+8\n"
        "while not stop.exists() and time.monotonic()<deadline: time.sleep(.005)\n"
    )
    sentinel_process = subprocess.Popen(
        args=[sys.executable, "-I", "-B", str(sentinel)], env={}, start_new_session=True
    )
    try:
        result = subprocess.run(
            args=[sys.executable, "-I", "-B", str(wrapper)],
            env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=10,
        )
        assert int((tmp_path / "sentinel-ready").read_text()) == sentinel_process.pid
        assert os.getpgid(sentinel_process.pid) == sentinel_process.pid
        assert sentinel_process.poll() is None
    finally:
        stop = tmp_path / "sentinel-stop"
        safety.contained(path=stop)
        stop.touch()
        sentinel_process.wait(timeout=10)
    with pytest.raises(ChildProcessError):
        os.waitpid(sentinel_process.pid, os.WNOHANG)
    assert result.returncode == (0 if mode == "early" else 124), result.stderr
    evidence = json.loads((tmp_path / "reaped.json").read_text())
    descendant = int((tmp_path / "ready").read_text())
    assert str(descendant) in evidence
    assert evidence[str(descendant)] == (-9 if mode == "ignore" else -15)
    assert "leader-ready" in result.stdout


@pytest.mark.parametrize("startup_allowance", [0.0, 0.25])
def test_parent_timeout_joins_supervisor_and_descendant(tmp_path: Path, startup_allowance: float) -> None:
    """Noncompleting work stays fatal and the adopter reaps even a TERM-ignoring child."""
    import json
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    assert hasattr(owner, "run_supervised")
    leader = tmp_path / "leader.py"
    child = tmp_path / "child.py"
    for path in (leader, child):
        owner.safety.contained(path=path)
    child.write_text(
        "import os,time,signal\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f"Path({str(tmp_path / 'ready')!r}).write_text(str(os.getpid()))\n"
        "while True: signal.pause()\n"
    )
    leader.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable,'-I','-B',{str(child)!r}])\n"
        f"while not Path({str(tmp_path / 'ready')!r}).exists(): time.sleep(.005)\n"
        "print('ready',flush=True)\nwhile True: time.sleep(1)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        owner.run_supervised(
            args=[sys.executable, "-I", "-B", str(leader)],
            env={},
            timeout=0.5,
            startup_allowance=startup_allowance,
        )
    assert failure.value.output == b"ready\n"
    reaped = json.loads((tmp_path / "reaped.json").read_text())
    assert reaped[(tmp_path / "ready").read_text()] == -9
    assert failure.value.timeout == 0.5
    assert owner.retained is None
    assert owner._process is not None and owner._process.returncode == 124
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


def test_supervisor_nonlinux_refuses_before_spawn(tmp_path: Path) -> None:
    """Unsupported POSIX must not silently degrade into orphan-prone direct execution."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor

    with patch.object(sys, "platform", "darwin"), patch.object(subprocess, "Popen") as spawn:
        with pytest.raises(RuntimeError, match="adoption unavailable"):
            OwnedSupervisor(root=tmp_path).invoke(args=[], timeout=1)
    spawn.assert_not_called()


def test_supervisor_not_isolated_refuses_before_spawn(tmp_path: Path) -> None:
    """Do not enable adoption in the calling agent/pytest session."""
    import subprocess
    from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor

    with patch.object(os, "getsid", return_value=-1), patch.object(subprocess, "Popen") as spawn:
        with pytest.raises(RuntimeError, match="fresh isolated session"):
            OwnedSupervisor(root=tmp_path).invoke(args=[], timeout=1)
    spawn.assert_not_called()


def test_supervisor_retains_original_failure_and_live_resources(tmp_path: Path) -> None:
    """A failed bounded join must retain files and a recoverable exact owner."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("import time\ntime.sleep(.2)\n")
    from tests.integration.herdr_restore_process_bootstrap import RetainedResourceError

    original = KeyboardInterrupt("original interruption")
    try:
        with patch.object(owner, "await_supervisor_ready", side_effect=original):
            with patch.object(subprocess.Popen, "wait", side_effect=OSError("join fault")):
                with pytest.raises(RetainedResourceError) as failure:
                    owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=1)
        assert failure.value.first_error is original
        assert failure.value.__cause__ is original
        assert failure.value.resource is owner.retained
        assert failure.value.owner is owner
        assert owner.retained is not None
        assert owner.retained.directory.exists()
        directory = owner.retained.directory
        failure.value.release(timeout=10)
    finally:
        owner.drain_supervisor(timeout=10)
    assert owner.retained is None
    assert not directory.exists()


@pytest.mark.parametrize("payload", [b"", b"READY:wrong\n", b"READY:123\nextra"])
def test_supervisor_handshake_rejects_invalid_identity(tmp_path: Path, payload: bytes) -> None:
    """EOF and forged/extra startup bytes never authorize a signal."""
    from unittest.mock import Mock
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, payload)
        os.close(write_fd)
        with pytest.raises(RuntimeError, match="startup failed"):
            owner.await_supervisor_ready(process=Mock(pid=123), fd=read_fd, timeout=1)
        assert not owner._supervisor_ready
    finally:
        os.close(read_fd)


def test_supervisor_resource_cleanup_preserves_failure(tmp_path: Path) -> None:
    """Directory finalization failure cannot replace the initial exception."""
    import shutil
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    original = ValueError("original")
    try:
        with patch.object(shutil, "rmtree", side_effect=OSError("cleanup fault")):
            with pytest.raises(RetainedResourceError) as failure:
                with owner.supervisor_resources():
                    raise original
        assert failure.value.first_error is original
        assert failure.value.resource is owner.retained
        assert owner.retained is not None
    finally:
        owner.drain_supervisor(timeout=1)


def test_supervisor_spawn_failure_closes_handshake(tmp_path: Path) -> None:
    """A failed exec retains no anonymous pipe descriptors."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("pass\n")
    descriptors: list[int] = []
    original_pipe = os.pipe

    def capture_pipe() -> tuple[int, int]:
        """Record only descriptors allocated by this attempted run."""
        pair = original_pipe()
        descriptors.extend(pair)
        return pair

    try:
        with patch.object(os, "pipe", side_effect=capture_pipe):
            with patch.object(subprocess, "Popen", side_effect=OSError("spawn fault")):
                with pytest.raises(OSError, match="spawn fault"):
                    owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=1)
        for fd in descriptors:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        for fd in descriptors:
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.parametrize("fault", ["killpg", "waitid", "getpgid"])
def test_stop_fault_still_reaps_owned_supervisor(tmp_path: Path, fault: str) -> None:
    """An ordinary stop fault must not bypass the real child's bounded join."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "finite.py"
    owner.safety.contained(path=script)
    script.write_text("import time\ntime.sleep(.1)\n")
    original = ValueError("first failure")
    ready = owner.await_supervisor_ready

    def fail_after_ready(*, process: subprocess.Popen[str], fd: int, timeout: float) -> None:
        """Establish real handler ownership before injecting the first failure."""
        ready(process=process, fd=fd, timeout=timeout)
        raise original

    try:
        with patch.object(owner, "await_supervisor_ready", side_effect=fail_after_ready):
            with patch.object(os, fault, side_effect=OSError("stop fault")):
                with pytest.raises(ValueError) as failure:
                    owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=1)
        assert failure.value is original
        assert owner._process is not None
        assert owner._process.returncode is not None
        assert owner.retained is None
        with pytest.raises(ChildProcessError):
            os.waitpid(owner._process.pid, os.WNOHANG)
    finally:
        owner.drain_supervisor(timeout=10)


@pytest.mark.parametrize("fault", ["killpg", "waitid", "getpgid"])
def test_supervisor_fault_retains_until_barrier_release(tmp_path: Path, fault: str) -> None:
    """Inject only in an isolated adopter; even RED naturally exits and reaps its dummy."""
    import subprocess
    import sys

    safety = ProcessSafety(root=tmp_path)
    script, wrapper, barrier = [tmp_path / name for name in ("dummy.py", "fault.py", "release")]
    for path in (script, wrapper, barrier):
        safety.contained(path=path)
    script.write_text(
        "import time\nfrom pathlib import Path\n"
        f"barrier=Path({str(barrier)!r})\ndeadline=time.monotonic()+4\n"
        "while not barrier.exists() and time.monotonic()<deadline: time.sleep(.005)\n"
    )
    wrapper.write_text(
        "import os,sys,time\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor,RetainedResourceError\n"
        f"owner=OwnedSupervisor(root=Path({str(tmp_path)!r}))\noriginal=OSError('injected')\n"
        "reap=os.waitpid\nheld=None\n"
        "try:\n"
        f" with patch.object(os,{fault!r},side_effect=original), patch.object(os,'waitpid',wraps=reap) as waits:\n"
        "  try:\n"
        f"   owner.invoke(args=[sys.executable,'-I','-B',{str(script)!r}],timeout=.05)\n"
        "  except RetainedResourceError as error:\n"
        "   held=error\n"
        "   assert waits.call_count > 0\n"
        "   assert error.first_error is original and error.owner is owner\n"
        "   assert error.__cause__ is original\n"
        "   assert error.resource.process.returncode is None\n"
        "   assert error.resource.directory.exists()\n"
        "  else: raise AssertionError('missing retained capability')\n"
        f" Path({str(barrier)!r}).touch()\n held.release(timeout=3)\n"
        " assert held.resource.process.returncode == 0\n"
        " assert owner.retained is None\n"
        "finally:\n"
        f" Path({str(barrier)!r}).touch()\n"
        " deadline=time.monotonic()+6\n"
        " while time.monotonic()<deadline:\n"
        "  try: pid,status=os.waitpid(-1,os.WNOHANG)\n"
        "  except ChildProcessError: break\n"
        "  if pid==0: time.sleep(.005)\n"
        " else: raise AssertionError('dummy did not exit')\n"
    )
    result = subprocess.run(
        args=[sys.executable, "-I", "-B", str(wrapper)],
        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=12,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("fault", ["killpg", "waitid", "getpgid", "status"])
def test_generated_wrapper_retains_pending_owner(tmp_path: Path, fault: str) -> None:
    """Exercise generated entry bytes; RED cleanup also reaps every real descendant."""
    import json
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    leader, child, barrier = [tmp_path / name for name in ("leader.py", "child.py", "release")]
    for path in (leader, child, barrier):
        owner.safety.contained(path=path)
    child.write_text(
        "import time\nfrom pathlib import Path\n"
        f"stop=Path({str(barrier)!r})\ndeadline=time.monotonic()+20\n"
        "while not stop.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
    )
    leader.write_text(
        "import subprocess,sys\n" f"p=subprocess.Popen([sys.executable,'-I','-B',{str(child)!r}])\n"
    )
    sentinel = subprocess.Popen(
        args=[sys.executable, "-I", "-B", str(child)],
        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
        start_new_session=True,
    )
    original_write = Path.write_text
    injection = (
        "import atexit,os,time\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor\n"
        f"barrier=Path({str(barrier)!r})\n"
        "real_invoke=OwnedSupervisor.invoke\nreal_drain=OwnedSupervisor.drain_supervisor\n"
        "held=[]\nresources=[]\nattempts=0\n"
        "def invoke(self,**kw):\n held.append(self)\n return real_invoke(self,**kw)\n"
        "def deny(*a,**kw): raise OSError('private-payload-never-print')\n"
        "def drain(self,**kw):\n"
        " global attempts\n attempts+=1\n"
        " assert held[0] is self\n"
        " if not resources: resources.append(self.retained)\n"
        " assert resources[0] is self.retained\n"
        " assert attempts<160, 'local drain busy spin'\n"
        " if not barrier.exists(): raise OSError('private-payload-never-print')\n"
        " return real_drain(self,**kw)\n"
        "def cleanup():\n"
        " barrier.touch()\n"
        " for owner in held: real_drain(owner,timeout=5)\n"
        "atexit.register(cleanup)\n"
        "OwnedSupervisor.invoke=invoke\nOwnedSupervisor.drain_supervisor=drain\n"
        + (
            "real_write=os.write\n"
            "def write(fd,data):\n"
            " if fd==2: raise OSError('status unavailable')\n"
            " return real_write(fd,data)\n"
            "os.write=write\nos.killpg=deny\n"
            if fault == "status"
            else f"os.{fault}=deny\n"
        )
    )

    def instrument(path: Path, data: str, *args: object, **kwargs: object) -> int:
        """Insert faults only in the generated, contained child interpreter."""
        owner.safety.contained(path=path)
        if path.name == "supervisor.py":
            data = data.replace("raise SystemExit(", injection + "raise SystemExit(", 1)
        return original_write(path, data)

    try:
        with patch.object(Path, "write_text", new=instrument):
            with pytest.raises(RetainedResourceError) as caught:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(leader)], env={}, timeout=0.2)
        resource = caught.value.resource
        assert caught.value.owner is owner and owner.retained is resource
        assert resource.process is not None and resource.process.poll() is None
        assert resource.directory.exists()
        assert sentinel.poll() is None
        assert os.getpgid(sentinel.pid) == sentinel.pid
        assert (resource.directory / "stderr").read_text() == (
            "" if fault == "status" else "SUPERVISOR_RETAINED\n"
        )
        with pytest.raises(subprocess.TimeoutExpired):
            caught.value.release(timeout=0.1)
        assert owner.retained is resource and resource.directory.exists()
        barrier.touch()
        caught.value.release(timeout=5)
        assert resource.process.returncode == 125
        assert owner.retained is None and not resource.directory.exists()
        assert len(json.loads((tmp_path / "reaped.json").read_text())) == 2
    finally:
        barrier.touch()
        owner.drain_supervisor(timeout=10)
        sentinel.wait(timeout=10)
    with pytest.raises(ChildProcessError):
        os.waitpid(sentinel.pid, os.WNOHANG)


def test_supervisor_stop_requires_ready(tmp_path: Path) -> None:
    """An exact owned process is not evidence that its TERM handler exists."""
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun
    from unittest.mock import Mock

    owner = OwnedProcessRun(root=tmp_path)
    process = Mock(pid=123456)
    owner._process = process
    with patch.object(os, "killpg") as kill, patch.object(os, "waitid") as status:
        with pytest.raises(PermissionError, match="not ready"):
            owner.request_supervisor_stop(process=process)
    kill.assert_not_called()
    status.assert_not_called()


@pytest.mark.parametrize("fault", ["before", "after", "reused"])
def test_owned_fd_close_fault_never_retries_reused_slot(tmp_path: Path, fault: str) -> None:
    """Only fresh private regular FDs are closed/reused; unrelated identity survives."""
    from tests.integration.herdr_restore_process_bootstrap import OwnedDescriptor

    safety = ProcessSafety(root=tmp_path)
    paths = (tmp_path / "owned", tmp_path / "unrelated")
    for path in paths:
        safety.contained(path=path)
        path.write_bytes(b"unchanged")
    fd = os.open(paths[0], os.O_RDWR)
    replacement: int | None = None
    real_close = os.close
    try:
        descriptor = OwnedDescriptor.capture(fd=fd)
        original = OSError("close fault")

        def faulty_close(target: int) -> None:
            """Inject only at the exact owned slot, never host descriptors."""
            nonlocal replacement
            assert target == fd
            if fault != "before":
                real_close(target)
            if fault == "reused":
                replacement = os.open(paths[1], os.O_RDWR)
                assert replacement == fd
            raise original

        with patch.object(os, "close", side_effect=faulty_close):
            with pytest.raises(OSError) as failure:
                descriptor.close()
        assert failure.value is original
        with patch.object(os, "close", side_effect=AssertionError("blind retry")):
            if fault == "before":
                with pytest.raises(RuntimeError, match="ambiguous"):
                    descriptor.close()
            else:
                descriptor.close()
        if replacement is not None:
            assert os.fstat(replacement).st_ino == paths[1].stat().st_ino
        assert paths[1].read_bytes() == b"unchanged"
    finally:
        if fault == "before" or replacement is not None:
            real_close(fd)


def test_all_owned_fds_attempted_and_primary_retained(tmp_path: Path) -> None:
    """One failed close retains typed ownership without skipping the second FD."""
    from tests.integration.herdr_restore_process_bootstrap import (
        OwnedDescriptor,
        OwnedProcessRun,
        RetainedResourceError,
    )

    owner = OwnedProcessRun(root=tmp_path)
    original = ValueError("primary")
    real_close = os.close
    descriptors: list[OwnedDescriptor] = []
    attempted: list[int] = []

    def close_fault(fd: int) -> None:
        """Fail only first private FD and close the other normally."""
        attempted.append(fd)
        if fd == descriptors[0].fd:
            raise OSError("close fault")
        real_close(fd)

    try:
        with (
            patch.object(os, "close", side_effect=close_fault),
            pytest.raises(RetainedResourceError) as failure,
        ):
            with owner.supervisor_resources() as directory:
                for name in ("first", "second"):
                    path = directory / name
                    owner.safety.contained(path=path)
                    path.write_bytes(b"private")
                    descriptors.append(OwnedDescriptor.capture(fd=os.open(path, os.O_RDONLY)))
                assert owner.retained is not None
                owner.retained.descriptors = descriptors
                raise original
        assert len(attempted) == 2
        assert descriptors[1].fd is None
        assert owner.retained is failure.value.resource
    finally:
        for descriptor in descriptors:
            if descriptor.fd is not None:
                real_close(descriptor.fd)
        owner.drain_supervisor(timeout=1)
    assert failure.value.first_error is original


def test_handshake_close_fault_retains_actual_child(tmp_path: Path) -> None:
    """A parent close fault still joins its actual finite dummy supervisor."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("pass\n")
    real_close = os.close
    original = OSError("handshake close")
    failed_fd: int | None = None

    def close_fault(fd: int) -> None:
        """Fault only an allocated handshake FD after the actual spawn returns."""
        nonlocal failed_fd
        if owner._process is not None and failed_fd is None:
            failed_fd = fd
            raise original
        real_close(fd)

    try:
        with patch.object(os, "close", side_effect=close_fault):
            with pytest.raises(RetainedResourceError) as failure:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=1)
        assert failure.value.first_error is original
        assert owner.retained is failure.value.resource
        assert owner.retained.process is not None
        assert owner.retained.process.wait(timeout=10) == 0
        with pytest.raises(ChildProcessError):
            os.waitpid(owner.retained.process.pid, os.WNOHANG)
    finally:
        if failed_fd is not None:
            try:
                real_close(failed_fd)
            except OSError:
                pass
        owner.drain_supervisor(timeout=10)


@pytest.mark.parametrize("fault", ["stdout_open", "stderr_open", "read", "close"])
def test_capture_fault_owns_files_and_actual_child(tmp_path: Path, fault: str) -> None:
    """Capture faults retain exact capabilities or close all files after actual join."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("print('dummy')\n")
    original = OSError(fault)
    opened: list[int] = []
    real_open, real_close = os.open, os.close
    failed_fd: int | None = None

    def capture_open(path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """Inject only capture opens; delegate other fixture-owned operations."""
        if Path(path).name in ("stdout", "stderr"):
            if fault == f"{Path(path).name}_open":
                raise original
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
            opened.append(fd)
            return fd
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def capture_close(fd: int) -> None:
        """Keep first capture FD unresolved, not any unrelated descriptor."""
        nonlocal failed_fd
        if fault == "close" and fd in opened and failed_fd is None:
            failed_fd = fd
            raise original
        real_close(fd)

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, "open", side_effect=capture_open))
            stack.enter_context(patch.object(os, "close", side_effect=capture_close))
            if fault == "read":
                stack.enter_context(patch.object(owner, "read_capture", side_effect=original))
            expected = RetainedResourceError if fault == "close" else OSError
            with pytest.raises(expected) as failure:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=2)
        if fault == "close":
            assert isinstance(failure.value, RetainedResourceError)
            assert failure.value.first_error is original
            assert failure.value.resource is owner.retained
            assert owner.retained is not None and owner.retained.directory.exists()
        else:
            assert failure.value is original
            assert owner.retained is None
        if fault in ("read", "close"):
            assert owner._process is not None and owner._process.returncode == 0
            with pytest.raises(ChildProcessError):
                os.waitpid(owner._process.pid, os.WNOHANG)
        else:
            assert owner._process is None
        for fd in opened:
            if fd != failed_fd:
                with pytest.raises(OSError):
                    os.fstat(fd)
    finally:
        if failed_fd is not None:
            real_close(failed_fd)
        owner.drain_supervisor(timeout=10)


def test_supervisor_capture_admission_preserves_active_identity(tmp_path: Path) -> None:
    """Concurrent entry cannot replace or remove the first context's captures."""
    from concurrent.futures import ThreadPoolExecutor
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)

    def enter_again() -> None:
        """Try a second context without creating any child or sending any signal."""
        with owner.supervisor_resources():
            pytest.fail("concurrent capture admission succeeded")

    with owner.supervisor_resources() as directory:
        resource = owner.retained
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                with pytest.raises(RuntimeError, match="capture owner busy"):
                    executor.submit(enter_again).result(timeout=2)
        finally:
            # Independent RED cleanup restores the exact first owner, not a guessed path.
            owner.retained = resource
        assert owner.retained is resource
        assert directory.exists()
    assert owner.retained is None
    assert not directory.exists()


@pytest.mark.parametrize("ending", [b":123\n", b"", None])
def test_partial_ready_requires_complete_frame(tmp_path: Path, ending: bytes | None) -> None:
    """Injected read boundaries model fragmentation, EOF and timeout without live signals."""
    import select
    import subprocess
    from unittest.mock import Mock
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    process = Mock(pid=123)
    selections: list[tuple[list[int], list[int], list[int]]] = [
        ([7], [], []),
        ([], [], []) if ending is None else ([7], [], []),
    ]
    with (
        patch.object(select, "select", side_effect=selections),
        patch.object(os, "read", side_effect=[b"READY", ending]),
        patch.object(os, "killpg") as kill,
    ):
        if ending == b":123\n":
            owner.await_supervisor_ready(process=process, fd=7, timeout=1)
            assert owner._supervisor_ready
        else:
            with pytest.raises(subprocess.TimeoutExpired if ending is None else RuntimeError):
                owner.await_supervisor_ready(process=process, fd=7, timeout=1)
            assert not owner._supervisor_ready
    kill.assert_not_called()


@pytest.mark.parametrize("allocation", ["pipe_read", "pipe_write", "stdout", "stderr"])
def test_allocated_fd_survives_identity_failure(tmp_path: Path, allocation: str) -> None:
    """Fail identity capture on an actual new FD; independent cleanup makes RED safe."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("pass\n")
    allocated: dict[str, int] = {}
    real_pipe, real_open, real_stat, real_close = os.pipe, os.open, os.fstat, os.close
    original = OSError("identity capture")
    failed = False

    def pipe() -> tuple[int, int]:
        """Record only newly allocated private handshake ends."""
        pair = real_pipe()
        allocated.update(pipe_read=pair[0], pipe_write=pair[1])
        return pair

    def opened(path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """Record capture allocations, delegating fixture directory operations."""
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name in ("stdout", "stderr"):
            allocated[Path(path).name] = fd
        return fd

    def inspected(fd: int) -> os.stat_result:
        """Inject once, precisely after the selected allocation."""
        nonlocal failed
        if not failed and fd == allocated.get(allocation):
            failed = True
            raise original
        return real_stat(fd)

    try:
        with (
            patch.object(os, "pipe", new=pipe),
            patch.object(os, "open", new=opened),
            patch.object(os, "fstat", new=inspected),
        ):
            with pytest.raises(OSError) as caught:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=1)
        assert caught.value is original and failed
        assert owner._process is None and owner.retained is None
        for fd in allocated.values():
            with pytest.raises(OSError):
                real_stat(fd)
    finally:
        for fd in allocated.values():
            try:
                real_close(fd)
            except OSError:
                pass
        owner.drain_supervisor(timeout=2)


def test_unjoined_child_and_close_failure_keep_one_capability(tmp_path: Path) -> None:
    """Keep actual child and FD reachable through GC, preserving the ultimate primary."""
    import gc
    import subprocess
    import sys
    import weakref
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("import time\ntime.sleep(.3)\n")
    original = KeyboardInterrupt("first interruption")
    real_wait, real_close = subprocess.Popen.wait, os.close
    held_fd: int | None = None

    def wait(process: subprocess.Popen[str], timeout: float | None = None) -> int:
        """Interrupt only the actual registered child join, including its cleanup join."""
        assert process is owner._process
        raise original

    def close(fd: int) -> None:
        """Fail one parent capture close; all other disposal remains real."""
        nonlocal held_fd
        if (
            owner.retained is not None
            and any(d.fd == fd for d in owner.retained.descriptors[2:])
            and held_fd is None
        ):
            held_fd = fd
            raise OSError("capture disposal")
        real_close(fd)

    try:
        with patch.object(subprocess.Popen, "wait", new=wait), patch.object(os, "close", new=close):
            with pytest.raises(RetainedResourceError) as caught:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=2)
        error = caught.value
        resource = error.resource
        assert resource.process is not None and resource.process.returncode is None
        reference = weakref.ref(resource.process)
        gc.collect()
        assert reference() is resource.process and resource.directory.exists()
        assert held_fd is not None and os.fstat(held_fd)
        assert error.owner is owner and owner.retained is resource
        assert error.first_error is original
        assert not isinstance(error.first_error, RetainedResourceError)
    finally:
        if owner._process is not None:
            real_wait(owner._process, timeout=10)
        if held_fd is not None:
            real_close(held_fd)
        owner.drain_supervisor(timeout=2)
    assert resource.process is not None
    assert resource.process.returncode is not None and not resource.directory.exists()
    with pytest.raises(ChildProcessError):
        os.waitpid(resource.process.pid, os.WNOHANG)


@pytest.mark.parametrize("fault", ["handler", "write", "close", "spawn", "stop"])
def test_child_partial_startup_disposes_ready_fd(tmp_path: Path, fault: str) -> None:
    """An isolated dummy checks inherited FD disposal before its interpreter exits."""
    import subprocess
    import sys

    safety = ProcessSafety(root=tmp_path)
    wrapper, workload = tmp_path / "wrapper.py", tmp_path / "workload.py"
    for path in (wrapper, workload):
        safety.contained(path=path)
    workload.write_text("pass\n")
    wrapper.write_text(
        "import os,sys,signal\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor,RetainedResourceError\n"
        f"owner=OwnedSupervisor(root=Path({str(tmp_path)!r}))\nr,w=os.pipe()\n"
        "real_close=os.close\noriginal=OSError('startup')\n"
        "def close(fd):\n real_close(fd)\n raise original\n"
        "def stop(*args):\n owner.request_stop(15,None)\n"
        "try:\n"
        + {
            "handler": " with patch.object(signal,'signal',side_effect=original):\n",
            "write": " with patch.object(os,'write',side_effect=original):\n",
            "close": " with patch.object(os,'close',side_effect=close):\n",
            "spawn": " with patch('subprocess.Popen',side_effect=original):\n",
            "stop": " with patch.object(signal,'signal',side_effect=stop), patch('subprocess.Popen',side_effect=AssertionError('spawn after stop')):\n",
        }[fault]
        + "  try:\n"
        + f"   result=owner.invoke(args=[sys.executable,'-I','-B',{str(workload)!r}],timeout=1,ready_fd=w)\n"
        + ("   assert result==124\n" if fault == "stop" else "   raise AssertionError('fault not raised')\n")
        + "  except RetainedResourceError as error:\n   assert error.first_error is original\n"
        "  except OSError as error:\n   assert error is original\n"
        " try: os.fstat(w)\n except OSError: pass\n else: raise AssertionError('READY FD leaked')\n"
        "finally:\n real_close(r)\n"
        " try: real_close(w)\n except OSError: pass\n"
    )
    result = subprocess.run(
        args=[sys.executable, "-I", "-B", str(wrapper)],
        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_capture_read_uses_existing_owned_fd(tmp_path: Path) -> None:
    """No transient Python read stream/finalizer can introduce another close fault."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("print('captured')\n")
    with patch.object(Path, "read_text", side_effect=OSError("unsafe read handle close")):
        result = owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=2)
    assert result.stdout == "captured\n" and result.stderr == ""
    assert owner.retained is None


def test_retained_entry_survives_repeated_interrupts(tmp_path: Path) -> None:
    """Real disposable wrapper retains its child across sleep/release and loop-gap SIGINT."""
    import subprocess
    import sys

    safety = ProcessSafety(root=tmp_path)
    wrapper, workload = tmp_path / "wrapper.py", tmp_path / "workload.py"
    for path in (wrapper, workload):
        safety.contained(path=path)
    workload.write_text("import time\ntime.sleep(.1)\n")
    wrapper.write_text(
        "import os,sys,time,signal\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor,RetainedSupervisor,RetainedResourceError\n"
        f"owner=OwnedSupervisor(root=Path({str(tmp_path)!r}))\n"
        "import subprocess\n"
        f"child=subprocess.Popen([sys.executable,'-I','-B',{str(workload)!r}],start_new_session=True)\n"
        "resource=RetainedSupervisor(directory=owner.root,process=child)\nowner.retained=resource\n"
        "primary=ValueError('primary')\ncap=RetainedResourceError(first_error=primary,owner=owner,resource=resource)\n"
        "sleeps=0\nreleases=0\nreal_sleep=time.sleep\nreal_release=cap.release\n"
        "def sleep(delay):\n global sleeps\n sleeps+=1\n"
        " if sleeps<=2: raise KeyboardInterrupt('sleep')\n real_sleep(delay)\n"
        "def release(*,timeout):\n global releases\n releases+=1\n"
        " assert cap.first_error is primary and owner.retained is resource\n"
        " if releases<=2: raise KeyboardInterrupt('release')\n real_release(timeout=timeout)\n"
        "def trace(frame,event,arg):\n"
        " if frame.f_code.co_name=='run_entry' and event=='line' and sleeps and owner.retained is not None:\n"
        "  os.kill(os.getpid(),signal.SIGINT)\n return trace\n"
        "try:\n"
        " with patch.object(owner,'invoke',side_effect=cap),patch.object(time,'sleep',side_effect=sleep),patch.object(cap,'release',side_effect=release):\n"
        "  sys.settrace(trace)\n"
        "  try: result=owner.run_entry(args=[],timeout=1)\n"
        "  finally: sys.settrace(None)\n"
        " assert result==125 and sleeps>=5 and releases>=3\n"
        " assert owner.retained is None and child.returncode==0\n"
        " try: os.waitpid(child.pid,os.WNOHANG)\n"
        " except ChildProcessError: pass\n else: raise AssertionError('unreaped')\n"
        "finally:\n sys.settrace(None)\n child.wait(timeout=3)\n"
    )
    result = subprocess.run(
        args=[sys.executable, "-I", "-B", str(wrapper)],
        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("join_fails", [False, True])
def test_parent_stop_interrupt_still_joins(tmp_path: Path, join_fails: bool) -> None:
    """A second interrupt cannot skip the actual child's cleanup wait or FD disposal."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("import time\ntime.sleep(.1)\n")
    primary = KeyboardInterrupt("primary")
    real_wait = subprocess.Popen.wait
    calls = 0

    def wait(process: subprocess.Popen[str], timeout: float | None = None) -> int:
        """Interrupt initial wait; optionally interrupt the later cleanup wait too."""
        nonlocal calls
        assert process is owner._process
        calls += 1
        if calls == 1 or join_fails:
            raise primary
        return real_wait(process, timeout=timeout)

    try:
        with (
            patch.object(subprocess.Popen, "wait", new=wait),
            patch.object(owner, "request_supervisor_stop", side_effect=KeyboardInterrupt("second")),
        ):
            with pytest.raises(BaseException) as caught:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=2)
        assert calls == 2
        assert owner._process is not None
        if join_fails:
            assert isinstance(caught.value, RetainedResourceError)
            assert caught.value.first_error is primary
            assert caught.value.resource is owner.retained
            assert owner.retained is not None and owner.retained.process is owner._process
            assert all(d.fd is None for d in owner.retained.descriptors)
            assert owner._process.returncode is None
        else:
            assert caught.value is primary and owner.retained is None
            assert owner._process.returncode == 0
    finally:
        if owner._process is not None:
            real_wait(owner._process, timeout=10)
        owner.drain_supervisor(timeout=2)
    with pytest.raises(ChildProcessError):
        os.waitpid(owner._process.pid, os.WNOHANG)


def test_concurrent_drains_preserve_exact_owner(tmp_path: Path) -> None:
    """A real child wait barrier excludes a second drain until closure is published."""
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedSupervisor

    owner = OwnedProcessRun(root=tmp_path)
    directory, script = tmp_path / "captures", tmp_path / "dummy.py"
    for path in (directory, script):
        owner.safety.contained(path=path)
    directory.mkdir()
    script.write_text("pass\n")
    process = subprocess.Popen(args=[sys.executable, "-I", "-B", str(script)], env={}, text=True)
    resource = RetainedSupervisor(directory=directory, process=process)
    owner.retained = resource
    target = directory / "capture"
    owner.safety.contained(path=target)
    target.write_bytes(b"retained")
    fd = os.open(target, os.O_RDONLY)
    resource.adopt_descriptors(fds=(fd,))
    entered, proceed = Event(), Event()
    real_wait = process.wait

    def wait(timeout: float | None = None) -> int:
        """Hold only the first drain, with an independently released bounded barrier."""
        entered.set()
        assert proceed.wait(timeout=3)
        return real_wait(timeout=timeout)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor, patch.object(process, "wait", side_effect=wait):
            first = executor.submit(owner.drain_supervisor, timeout=2)
            try:
                assert entered.wait(timeout=2)
                with pytest.raises(RuntimeError, match="capture owner busy"):
                    owner.drain_supervisor(timeout=1)
                assert owner.retained is resource and directory.exists() and os.fstat(fd)
            finally:
                proceed.set()
            first.result(timeout=3)
        assert owner.retained is None and not directory.exists() and process.returncode == 0
        with pytest.raises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)
    finally:
        proceed.set()
        real_wait(timeout=3)
        owner.drain_supervisor(timeout=2)


@pytest.mark.parametrize("handler_fails", [False, True])
@pytest.mark.parametrize("close_first", [False, True])
def test_child_ready_combined_retention(tmp_path: Path, handler_fails: bool, close_first: bool) -> None:
    """Child READY ambiguous close and persistent inspection preserve primary and identity."""
    import subprocess
    import sys

    safety = ProcessSafety(root=tmp_path)
    wrapper, workload, other = tmp_path / "wrapper.py", tmp_path / "workload.py", tmp_path / "other"
    for path in (wrapper, workload, other):
        safety.contained(path=path)
    workload.write_text("raise AssertionError('must not spawn')\n")
    other.write_bytes(b"unrelated")
    wrapper.write_text(
        "import os,sys,signal,errno\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor,RetainedResourceError\n"
        f"owner=OwnedSupervisor(root=Path({str(tmp_path)!r}))\nr,w=os.pipe()\n"
        "real_close,real_stat=os.close,os.fstat\nprimary=ValueError('handler')\nclose_error=OSError('close')\n"
        "def close(fd):\n assert fd==w\n"
        + (" real_close(fd)\n" if close_first else "")
        + " raise close_error\n"
        "def inspect(fd):\n raise OSError(errno.EIO,'persistent inspection')\n"
        "try:\n"
        " with patch.object(os,'close',side_effect=close),patch.object(signal,'signal'"
        + (",side_effect=primary" if handler_fails else ",wraps=signal.signal")
        + "):\n  try:\n"
        + f"   owner.invoke(args=[sys.executable,'-I','-B',{str(workload)!r}],timeout=1,ready_fd=w)\n"
        "  except RetainedResourceError as error: cap=error\n"
        "  else: raise AssertionError('missing retention')\n"
        + f" assert cap.first_error is {'primary' if handler_fails else 'close_error'}\n"
        " resource=cap.resource\n assert owner.retained is resource and resource.process is None\n"
        " with patch.object(os,'fstat',side_effect=inspect):\n"
        "  for attempt in range(2):\n"
        "   try: cap.release(timeout=.1)\n"
        "   except OSError as error: assert error.errno==errno.EIO\n"
        "   else: raise AssertionError('inspection lost retention')\n"
        "   assert owner.retained is resource and resource.descriptors[0].fd==w\n"
        + (
            ""
            if close_first
            else " try: cap.release(timeout=.1)\n except RuntimeError: pass\n else: raise AssertionError('retried ambiguous close')\n real_close(w)\n"
        )
        + f" replacement=os.open({str(other)!r},os.O_RDONLY)\n assert replacement==w\n"
        " cap.release(timeout=.1)\n assert owner.retained is None\n"
        f" assert real_stat(replacement).st_ino==Path({str(other)!r}).stat().st_ino\n"
        "finally:\n real_close(r)\n"
        " try: real_close(w)\n except OSError: pass\n"
    )
    result = subprocess.run(
        args=[sys.executable, "-I", "-B", str(wrapper)],
        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_unsupervised_path_is_removed() -> None:
    """The test-only harness must expose no alternate unsafe process lifetime."""
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    assert not hasattr(OwnedProcessRun, "run")
    assert not hasattr(OwnedProcessRun, "cleanup")


def test_full_run_refuses_concurrent_drain(tmp_path: Path) -> None:
    """A barrier at capture reading holds a real joined run's still-active resources."""
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("print('owned')\n")
    entered, proceed = Event(), Event()
    real_read = owner.read_capture

    def read(*, fd: int) -> bytes:
        """Wait only on test-owned events, with independent finally release."""
        entered.set()
        assert proceed.wait(timeout=5)
        return real_read(fd=fd)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with patch.object(owner, "read_capture", side_effect=read):
            future = executor.submit(
                owner.run_supervised, args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=2
            )
            try:
                assert entered.wait(timeout=5)
                resource = owner.retained
                with pytest.raises(RuntimeError, match="capture owner busy"):
                    owner.drain_supervisor(timeout=1)
                assert owner.retained is resource
            finally:
                proceed.set()
            assert future.result(timeout=5).stdout == "owned\n"
    assert owner.retained is None


def test_failed_drain_still_attempts_every_fd(tmp_path: Path) -> None:
    """Repeated join interruption must not skip remaining independent FD disposal."""
    import subprocess
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    script = tmp_path / "dummy.py"
    owner.safety.contained(path=script)
    script.write_text("import time\ntime.sleep(.2)\n")
    real_wait = subprocess.Popen.wait
    original = KeyboardInterrupt("join interrupted")
    try:
        with pytest.raises(RetainedResourceError) as caught:
            with owner.supervisor_resources() as directory:
                with owner.capture_descriptors(out=directory / "stdout", err=directory / "stderr"):
                    assert owner.retained is not None
                    process = subprocess.Popen(
                        args=[sys.executable, "-I", "-B", str(script)],
                        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
                        start_new_session=True,
                        text=True,
                    )
                    owner.retained.process = process
                    # Transfer without context finalization closing these FDs yet.
                    with patch.object(owner.retained, "close_descriptors", side_effect=OSError("defer")):
                        raise RetainedResourceError(
                            first_error=original, owner=owner, resource=owner.retained
                        )
        resource = caught.value.resource
        # Allocate another real FD into the retained resource after the transfer.
        target = resource.directory / "late"
        owner.safety.contained(path=target)
        target.write_bytes(b"owned")
        resource.adopt_descriptors(fds=(os.open(target, os.O_RDONLY),))
        with patch.object(process, "wait", side_effect=original):
            with pytest.raises(BaseException) as interrupted:
                caught.value.release(timeout=1)
        assert all(d.fd is None for d in resource.descriptors)
        assert owner.retained is resource and resource.directory.exists()
        assert interrupted.value is original
    finally:
        if owner.retained is not None and owner.retained.process is not None:
            real_wait(owner.retained.process, timeout=5)
        owner.drain_supervisor(timeout=2)


@pytest.mark.parametrize("boundary", ["waitid", "killpg", "drain"])
def test_child_interrupt_still_reaps_owned_workload(tmp_path: Path, boundary: str) -> None:
    """Repeated BaseException faults run only in a disposable adopter with a finite child."""
    import subprocess
    import sys

    safety = ProcessSafety(root=tmp_path)
    wrapper, workload = tmp_path / "wrapper.py", tmp_path / "workload.py"
    for path in (wrapper, workload):
        safety.contained(path=path)
    workload.write_text("import time\ntime.sleep(.1)\n")
    wrapper.write_text(
        "import os,sys,time\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor,RetainedResourceError\n"
        f"owner=OwnedSupervisor(root=Path({str(tmp_path)!r}))\noriginal=KeyboardInterrupt('first')\n"
        "try:\n"
        + (
            " with patch.object(owner,'drain_supervisor',side_effect=original):\n"
            if boundary == "drain"
            else f" with patch.object(os,{boundary!r},side_effect=original):\n"
        )
        + "  try:\n"
        + f"   owner.invoke(args=[sys.executable,'-I','-B',{str(workload)!r}],timeout=.2)\n"
        "  except RetainedResourceError as error:\n   assert error.first_error is original\n"
        "  except KeyboardInterrupt as error:\n   assert error is original\n   assert owner.retained is None, 'interrupt bypassed cleanup'\n"
        "  else: raise AssertionError('lost interruption')\n"
        "finally:\n owner.drain_supervisor(timeout=3)\n"
        "try: os.waitpid(-1,os.WNOHANG)\nexcept ChildProcessError: pass\nelse: raise AssertionError('unjoined child')\n"
    )
    result = subprocess.run(
        args=[sys.executable, "-I", "-B", str(wrapper)],
        env={"SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_capture_close_reuse_preserves_unrelated_fd(tmp_path: Path) -> None:
    """Compose close-after-error/reuse with actual run and retained-resource release."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun, RetainedResourceError

    owner = OwnedProcessRun(root=tmp_path)
    script, unrelated = tmp_path / "dummy.py", tmp_path / "unrelated"
    for path in (script, unrelated):
        owner.safety.contained(path=path)
    script.write_text("pass\n")
    unrelated.write_bytes(b"unchanged")
    real_close = os.close
    replacement: int | None = None

    def close(fd: int) -> None:
        """Reuse only one known capture slot with another temp-owned regular file."""
        nonlocal replacement
        if (
            replacement is None
            and owner._process is not None
            and owner.retained is not None
            and any(d.fd == fd for d in owner.retained.descriptors[2:])
        ):
            real_close(fd)
            replacement = os.open(unrelated, os.O_RDONLY)
            assert replacement == fd
            raise OSError("after close")
        real_close(fd)

    try:
        with patch.object(os, "close", side_effect=close):
            with pytest.raises(RetainedResourceError) as caught:
                owner.run_supervised(args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=2)
        assert owner._process is not None and owner._process.returncode == 0
        caught.value.release(timeout=2)
        assert replacement is not None and os.fstat(replacement).st_ino == unrelated.stat().st_ino
        assert unrelated.read_bytes() == b"unchanged" and owner.retained is None
    finally:
        if replacement is not None:
            real_close(replacement)
        owner.drain_supervisor(timeout=2)


@pytest.mark.parametrize("field,value", [(0, 0o010600), (3, 2)])
def test_opened_descriptor_metadata_refused_before_write(tmp_path: Path, field: int, value: int) -> None:
    """Opened special or multiply-linked metadata cannot borrow a regular pathname."""
    safety = ProcessSafety(root=tmp_path)
    target = tmp_path / "capture"
    safety.contained(path=target)
    target.write_bytes(b"unchanged")
    fd = os.open(path=target, flags=os.O_WRONLY)
    original = os.fstat(fd)
    fields = list(original)
    fields[field] = value
    try:
        with patch.object(os, "fstat", return_value=os.stat_result(fields)):
            with patched_descriptors(safety=safety):
                with pytest.raises(PermissionError):
                    os.write(fd, b"bad")
        assert target.read_bytes() == b"unchanged"
    finally:
        os.close(fd)


def test_actual_atomic_writer_and_lease_under_child_guard(tmp_path: Path) -> None:
    """Run real atomic persistence and lock cleanup beneath the installed child guard."""
    import sys
    from tests.integration.herdr_restore_process_bootstrap import OwnedProcessRun

    safety = ProcessSafety(root=tmp_path)
    script = tmp_path / "persistence.py"
    safety.contained(path=script)
    script.write_text(
        "import sys,os\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
        "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
        f"root=Path({str(tmp_path)!r})\n"
        "ProcessSafety(root=root,stdio=(1,2)).install()\n"
        "from src.agents.slo_agent.history.atomic_io import AtomicFileWriter\n"
        "from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease\n"
        "from unittest.mock import patch\n"
        "target=root/'private'/'record'\n"
        "AtomicFileWriter.write_text(path=target,text='committed')\n"
        "assert target.read_text()=='committed'\n"
        "assert target.stat().st_mode & 0o777 == 0o600\n"
        "with patch.object(os,'replace',side_effect=OSError('injected')):\n"
        " try: AtomicFileWriter.write_text(path=target,text='uncommitted')\n"
        " except OSError: pass\n"
        " else: raise AssertionError('missing failure')\n"
        "assert target.read_text()=='committed'\n"
        "assert list(target.parent.iterdir())==[target]\n"
        "lease=HerdrFileLease()\n"
        "lease.acquire(path=target.parent/'lease',create=True)\n"
        "lease.require_held(path=target.parent/'lease')\n"
        "lease.close()\n"
        "print('PERSISTENCE_OK')\n",
        encoding="utf-8",
    )
    owner = OwnedProcessRun(root=tmp_path)
    result = owner.run_supervised(
        args=[sys.executable, "-I", "-B", str(script)], env={}, timeout=5, startup_allowance=5
    )
    assert result.returncode == 0 and result.stdout == "PERSISTENCE_OK\n", result.stderr


def test_owned_dirfd_admitted(tmp_path: Path) -> None:
    """A valid directory capability resolves a relative name under the owned root."""
    fd = os.open(path=tmp_path, flags=os.O_RDONLY | os.O_DIRECTORY)
    try:
        ProcessSafety(root=tmp_path).audit(event="os.mkdir", arguments=("new", 0o700, fd))
    finally:
        os.close(fd)
