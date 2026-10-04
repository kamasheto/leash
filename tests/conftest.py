"""Fixtures shared by the unit and integration tests."""

import json
import subprocess
from pathlib import Path

import pytest

import leash


class Project:
    """A scratch project directory, plus shortcuts for building its profile."""

    def __init__(self, root: Path):
        self.root = root

    def write(self, rel: str, text: str = "") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def paths(self, tool: str = "claude", with_git: bool = False):
        return leash.Paths(tool=tool, project_root=self.root, with_git=with_git)

    def build(self, tool: str = "claude", with_git: bool = False):
        """Runs build_profile and returns the Paths it built for."""
        p = self.paths(tool=tool, with_git=with_git)
        leash.build_profile(p)
        return p

    def profile(self, tool: str = "claude", with_git: bool = False) -> dict:
        """Runs build_profile and returns the generated profile."""
        return json.loads(self.build(tool=tool, with_git=with_git).profile_path.read_text())


@pytest.fixture
def project(tmp_path) -> Project:
    # resolve(): on macOS the temp dir lives behind the /var -> /private/var
    # symlink, and sandbox rules are matched against the real path.
    root = (tmp_path / "project").resolve()
    root.mkdir()
    return Project(root)


@pytest.fixture
def nono_cfg(tmp_path, monkeypatch) -> Path:
    """Points nono's global config (XDG_CONFIG_HOME) at a temp dir."""
    cfg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    return cfg


class FakeNono:
    """Stands in for leash.run_cmd: records `nono ...` commands and pretends
    they succeeded, and passes everything else (git) through for real."""

    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls: list[str] = []
        self._real = leash.run_cmd

    def __call__(self, cmd: str, **kwargs):
        if not cmd.startswith("nono "):
            return self._real(cmd, **kwargs)
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr="")


@pytest.fixture
def fake_nono(monkeypatch) -> FakeNono:
    fake = FakeNono()
    monkeypatch.setattr(leash, "run_cmd", fake)
    return fake
