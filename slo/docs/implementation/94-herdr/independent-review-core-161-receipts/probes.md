# Independent core counterexamples

Run with approved Python3.11.7, `python -B -` from application root. Only new regular files beneath each resolved TemporaryDirectory are opened; injected close operates only on the lease descriptor and a new test-owned regular file. No subprocess or real Herdr is involved. This is deterministic fault injection, not a claim that the host syscall spontaneously failed.

```python
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease, HerdrSequenceStore

with tempfile.TemporaryDirectory(prefix="herdr-core161-") as directory:
    root = Path(directory).resolve()
    lease = HerdrFileLease()
    lease.acquire(path=root / "lock", create=True)
    original_fd = lease._fd
    real_close = os.close
    victim = []

    def ambiguous_close(fd):
        assert fd == original_fd
        real_close(fd)
        target = root / "unrelated-owned-file"
        assert target.resolve().parent == root and not target.exists()
        victim.append(os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
        raise OSError("synthetic ambiguous close")

    with patch("os.close", side_effect=ambiguous_close):
        try:
            lease.close()
        except OSError:
            pass
    assert original_fd == victim[0]
    assert lease._fd == victim[0]
    lease.close()
    try:
        os.fstat(victim[0])
    except OSError:
        print("R161-1 reproduced: retry closed unrelated reused descriptor")
    else:
        os.close(victim[0])
        raise AssertionError("defect not reproduced")

with tempfile.TemporaryDirectory(prefix="herdr-core161-") as directory:
    root = Path(directory).resolve()
    store = HerdrSequenceStore(state_root=root, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    path = next((root / "sequence-v1").glob("*.json"))
    valid = path.read_bytes()
    assert path.resolve().is_relative_to(root) and not path.is_symlink()
    path.write_bytes(valid + b"INVALID-TRAILING-BYTES")
    real_read = os.read

    def short_read(fd, count):
        return real_read(fd, min(count, len(valid)))

    with patch("os.read", side_effect=short_read):
        store.acquire()
        assert store._state.lifecycle_sequence == 1
        assert store.reserve(source="custom:slo") == 2
    assert b"INVALID" not in path.read_bytes()
    store.close()
    print("R161-2 reproduced: short read accepted and overwrote corrupt counter")
```

Initial observed output (exit0; post-probe coreutils silent):
```text
original_fd_equals_reused_fd True
lease_retains_reused_descriptor True
unrelated_file_still_open False
invalid_counter_accepted True
sequence_reserved_from_invalid_state 2
invalid_counter_overwritten True
```

The retained rerun executes the fenced block above unchanged. Desired regression tests must instead assert that unrelated descriptors remain open and corrupt sequence bytes remain unchanged with no sendable reservation. Existing tests cover close-before-error retention and restore-record short reads, but not these two sequence/lease cases.
