"""Extract the actual release once; a missing tag is an error, never a skip."""

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.compat.released_runner import RELEASED_TAG, REPOSITORY_ROOT


@pytest.fixture(scope="session")
def released_slo_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Extract frozen source for compatibility subprocesses before their first run.

    Args:
        tmp_path_factory (pytest.TempPathFactory): Owner of the extraction directory.

    Returns:
        Path: Released slo source, not the current checkout or installed package.
    """
    archive = subprocess.run(
        args=["git", "-C", str(REPOSITORY_ROOT), "archive", "--format=tar", RELEASED_TAG, "slo"],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if archive.returncode != 0:
        pytest.fail(
            f"Released Slo {RELEASED_TAG} could not be extracted from {REPOSITORY_ROOT}: "
            f"{archive.stderr.decode(errors='replace').strip()}. If the tag is missing, fetch tags."
        )
    target = tmp_path_factory.mktemp("released").resolve()
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
        for member in bundle.getmembers():
            assert (target / member.name).resolve().is_relative_to(target)
            assert member.isfile() or member.isdir(), "Release archive must not contain links or devices"
        bundle.extractall(path=target, filter="data")
    source = target / "slo"
    assert (source / "src/auth/credential_store.py").is_file()
    return source
