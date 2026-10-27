"""Integration tests: leash's generated profiles against the real nono.

Run from the repo root:  uv run pytest -m integration
(`uv run pytest` runs these along with the unit tests.)

Skipped unless `nono` is on PATH. Profiles extend nono's built-in `default`
profile, so no agent package (claude, codex) is needed; agent base profiles
are checked too when they're installed. Commands run inside the sandbox are
plain `cat` / `git`, never an agent.

These tests never call main() or absorb_session_grants(), so they don't
read or write nono's global config (~/.config/nono).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import leash

NONO = shutil.which("nono")
GIT = shutil.which("git")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not NONO, reason="nono is not on PATH"),
]

# The built-in nono profile every install has; stands in for an agent's base.
BASE = "default"
AGENT_BASES = ("claude", "codex")

# Keep git inside the sandbox away from the user's ~/.gitconfig, which the
# `default` base profile can't read.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

real_run_cmd = leash.run_cmd


def nono(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NONO, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env={**os.environ, **GIT_ENV},
    )


def quiet_run_cmd(cmd: str, **kwargs) -> subprocess.CompletedProcess:
    """leash.run_cmd, but with nono's output captured instead of printed for
    every profile build. It's replayed to stderr if the command fails."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    result = real_run_cmd(cmd, **kwargs)
    if result.returncode != 0:
        sys.stderr.write((result.stdout or "") + (result.stderr or ""))
    return result


def profile_exists(name: str) -> bool:
    return nono("profile", "show", "-s", name).returncode == 0


@pytest.fixture
def repo(project, monkeypatch):
    """A scratch git repo with a committed secret and a .leash denying it."""
    monkeypatch.setattr(leash, "run_cmd", quiet_run_cmd)

    def git(*args: str) -> None:
        # Outside the sandbox: just setting up the fixture repo.
        subprocess.run([GIT, "-C", str(project.root), *args], check=True,
                       capture_output=True, env={**os.environ, **GIT_ENV})

    project.write(".leash", "*.env\n")
    project.write("open.txt", "open\n")
    project.write("secret.env", "top secret\n")
    project.write("src/nested.env", "nested secret\n")
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return project


def build(repo, tool: str = BASE, with_git: bool = False, with_net: bool = False) -> Path:
    # build_profile also runs `nono profile validate`, and dies if it fails.
    return repo.build(tool=tool, with_git=with_git, with_net=with_net).profile_path


def sandboxed(repo, profile: Path, *cmd: str) -> subprocess.CompletedProcess:
    # The same `nono run` invocation main() makes (minus -v), with -s to
    # keep nono's own banner out of the captured output.
    return nono("run", "-s", "--allow-cwd", "--profile", str(profile),
                "--workdir", str(repo.root), "--", *cmd)


def assert_readable(repo, profile: Path, rel: str, content: str) -> None:
    result = sandboxed(repo, profile, "cat", rel)
    assert result.returncode == 0, f"{rel}: {result.stderr}"
    assert result.stdout == content


def assert_denied(repo, profile: Path, rel: str) -> None:
    result = sandboxed(repo, profile, "cat", rel)
    assert result.returncode != 0, f"{rel} was readable: {result.stdout!r}"
    assert "not permitted" in result.stderr


# --- validation --------------------------------------------------------------

MODES = pytest.mark.parametrize("with_git, with_net", [
    (False, False), (True, False), (False, True), (True, True),
], ids=["default", "with-git", "with-net", "with-git-and-net"])


@MODES
def test_generated_profile_validates(repo, with_git, with_net):
    result = nono("profile", "validate", str(build(repo, with_git=with_git, with_net=with_net)))
    assert result.returncode == 0, result.stdout + result.stderr


@MODES
@pytest.mark.parametrize("tool", AGENT_BASES)
def test_generated_profile_validates_against_agent_base(repo, tool, with_git, with_net):
    if not profile_exists(tool):
        pytest.skip(f"nono profile '{tool}' is not installed")
    build(repo, tool=tool, with_git=with_git, with_net=with_net)


def test_validate_rejects_a_broken_profile(project):
    # Guards the tests above: validation must actually be able to fail.
    broken = project.write("broken.json", json.dumps({
        "extends": BASE, "meta": {"name": "broken"},
        "filesystem": {"deny": "not-a-list"},
    }))
    assert nono("profile", "validate", "-s", str(broken)).returncode != 0


# --- default mode: no git ----------------------------------------------------

class TestDefaultMode:
    @pytest.fixture
    def profile(self, repo):
        return build(repo)

    def test_project_files_are_readable(self, repo, profile):
        assert_readable(repo, profile, "open.txt", "open\n")

    @pytest.mark.parametrize("rel", [
        pytest.param("secret.env", id="leash-pattern"),
        pytest.param("src/nested.env", id="leash-pattern-nested"),
        pytest.param(".leash", id="leash-rules"),
        pytest.param(".leash-agents/default.profile.json", id="leash-state"),
        pytest.param(".git/HEAD", id="git-dir"),
    ])
    def test_is_denied(self, repo, profile, rel):
        assert_denied(repo, profile, rel)

    def test_git_command_is_blocked(self, repo, profile):
        result = sandboxed(repo, profile, "git", "show", "HEAD:secret.env")
        assert result.returncode != 0
        assert "top secret" not in result.stdout
        assert "leash: git is disabled" in result.stderr

    def test_git_by_absolute_path_is_blocked(self, repo, profile):
        result = sandboxed(repo, profile, GIT, "show", "HEAD:secret.env")
        assert result.returncode != 0
        assert "top secret" not in result.stdout

    def test_extra_grant_reopens_a_leash_deny(self, repo):
        repo.write(f"{leash.STATE_DIR}/default.extra.json",
                   json.dumps({"read": ["$WORKDIR/secret.env"]}))
        profile = build(repo)
        assert_readable(repo, profile, "secret.env", "top secret\n")
        assert_denied(repo, profile, "src/nested.env")

    def test_exit_code_passes_through(self, repo, profile):
        assert sandboxed(repo, profile, "sh", "-c", "exit 7").returncode == 7


# --- --with-git mode ---------------------------------------------------------

class TestWithGitMode:
    @pytest.fixture
    def profile(self, repo):
        return build(repo, with_git=True)

    def test_git_works(self, repo, profile):
        result = sandboxed(repo, profile, "git", "log", "--format=%s")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "init\n"

    def test_git_dir_is_readable(self, repo, profile):
        result = sandboxed(repo, profile, "cat", ".git/HEAD")
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("rel", ["secret.env", ".leash"])
    def test_leash_denies_still_block_direct_reads(self, repo, profile, rel):
        assert_denied(repo, profile, rel)

    def test_committed_secret_leaks_through_history(self, repo, profile):
        # The documented trade-off of --with-git. If this starts failing,
        # nono (or leash) closed the gap and the docs should be updated.
        result = sandboxed(repo, profile, "git", "show", "HEAD:secret.env")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "top secret\n"


# --- network -----------------------------------------------------------------

def host_verdict(profile: Path, host: str) -> str:
    # Asks nono's policy engine; nothing actually connects anywhere.
    result = nono("why", "--profile", str(profile), "--host", host, "--port", "443")
    assert result.returncode == 0, result.stderr
    return result.stdout.split()[0]  # ALLOWED or DENIED


@pytest.mark.parametrize("host", ["api.anthropic.com", "api.openai.com"])
@pytest.mark.parametrize("with_net", [False, True], ids=["default", "with-net"])
def test_llm_apis_are_reachable(repo, host, with_net):
    assert host_verdict(build(repo, with_net=with_net), host) == "ALLOWED"


@pytest.mark.parametrize("host", ["example.com", "github.com"])
@pytest.mark.parametrize("with_net, verdict", [(False, "DENIED"), (True, "ALLOWED")],
                         ids=["default", "with-net"])
def test_other_hosts_only_with_net(repo, host, with_net, verdict):
    assert host_verdict(build(repo, with_net=with_net), host) == verdict
