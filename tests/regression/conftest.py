"""Fixtures for review-fix regression tests."""

import os
import shutil
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRATCH_ROOT = REPO_ROOT / ".test-tmp" / "regression"


def _make_writable(path: Path) -> None:
    """Restore write permission on a tree so it can be deleted."""
    for root, dirs, files in os.walk(path):
        for name in dirs:
            try:
                os.chmod(Path(root) / name, 0o755)
            except OSError:
                pass
        for name in files:
            try:
                os.chmod(Path(root) / name, 0o644)
            except OSError:
                pass
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass


@pytest.fixture
def repo_tmp():
    """A scratch directory inside the repo (never bare /tmp)."""
    path = SCRATCH_ROOT / uuid.uuid4().hex[:12]
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        if path.exists():
            _make_writable(path)
            shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_xdg(repo_tmp, monkeypatch):
    """Keep config, DB and logs out of the real home directory."""
    xdg_data = repo_tmp / "xdg-data"
    xdg_state = repo_tmp / "xdg-state"
    home = repo_tmp / "home"
    for d in (xdg_data, xdg_state, home):
        d.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    monkeypatch.setenv("HOME", str(home))
    return {"data": xdg_data, "state": xdg_state, "home": home}
