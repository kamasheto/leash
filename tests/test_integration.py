"""Integration tests: leash's generated profiles against the real nono.

Run from the repo root:  python3 tests -k integration
(`python3 tests` runs these along with the unit tests.)

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
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import load_cli

cli = load_cli()

NONO = shutil.which("nono")
GIT = shutil.which("git")

# The built-in nono profile every install has; stands in for an agent's base.
BASE = "default"
AGENT_BASES = ("claude", "codex")

# Keep git inside the sandbox away from the user's ~/.gitconfig, which the
# `default` base profile can't read.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def nono(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NONO, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env={**os.environ, **GIT_ENV},
    )


def quiet_run_cmd(cmd: str, **kwargs) -> subprocess.CompletedProcess:
    """cli.run_cmd, but with nono's output captured instead of printed for
    every profile build. It's replayed to stderr if the command fails."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    result = real_run_cmd(cmd, **kwargs)
    if result.returncode != 0:
        sys.stderr.write((result.stdout or "") + (result.stderr or ""))
    return result


real_run_cmd = cli.run_cmd


def profile_exists(name: str) -> bool:
    return nono("profile", "show", "-s", name).returncode == 0


@unittest.skipUnless(NONO, "nono is not on PATH")
class NonoTestCase(unittest.TestCase):
    """A scratch git repo with a committed secret and a .leash denying it."""

    def setUp(self):
        patcher = mock.patch.object(cli, "run_cmd", quiet_run_cmd)
        patcher.start()
        self.addCleanup(patcher.stop)

        tmp = tempfile.TemporaryDirectory(prefix="leash-it-")
        self.addCleanup(tmp.cleanup)
        # resolve(): on macOS the temp dir lives behind the /var -> /private/var
        # symlink, and sandbox rules are matched against the real path.
        self.root = Path(tmp.name).resolve()

        self.write(".leash", "*.env\n")
        self.write("open.txt", "open\n")
        self.write("secret.env", "top secret\n")
        self.write("src/nested.env", "nested secret\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, *args: str) -> None:
        # Outside the sandbox: just setting up the fixture repo.
        subprocess.run([GIT, "-C", str(self.root), *args], check=True,
                       capture_output=True, env={**os.environ, **GIT_ENV})

    def build(self, tool: str = BASE, with_git: bool = False) -> Path:
        p = cli.Paths(tool=tool, project_root=self.root, with_git=with_git)
        cli.build_profile(p)  # also runs `nono profile validate`
        return p.profile_path

    def sandboxed(self, profile: Path, *cmd: str) -> subprocess.CompletedProcess:
        # The same `nono run` invocation main() makes (minus -v), with -s to
        # keep nono's own banner out of the captured output.
        return nono("run", "-s", "--allow-cwd", "--profile", str(profile),
                    "--workdir", str(self.root), "--", *cmd)

    def assertReadable(self, profile: Path, rel: str, content: str):
        result = self.sandboxed(profile, "cat", rel)
        self.assertEqual(result.returncode, 0, f"{rel}: {result.stderr}")
        self.assertEqual(result.stdout, content)

    def assertDenied(self, profile: Path, rel: str):
        result = self.sandboxed(profile, "cat", rel)
        self.assertNotEqual(result.returncode, 0, f"{rel} was readable: {result.stdout!r}")
        self.assertIn("not permitted", result.stderr)


class ValidateTest(NonoTestCase):
    def test_generated_profiles_validate(self):
        for with_git in (False, True):
            with self.subTest(with_git=with_git):
                profile = self.build(with_git=with_git)
                result = nono("profile", "validate", str(profile))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_profiles_validate_against_agent_bases(self):
        for tool in AGENT_BASES:
            with self.subTest(tool=tool):
                if not profile_exists(tool):
                    self.skipTest(f"nono profile '{tool}' is not installed")
                for with_git in (False, True):
                    self.build(tool=tool, with_git=with_git)

    def test_validate_rejects_a_broken_profile(self):
        # Guards the tests above: validation must actually be able to fail.
        broken = self.root / "broken.json"
        broken.write_text(json.dumps({
            "extends": BASE, "meta": {"name": "broken"},
            "filesystem": {"deny": "not-a-list"},
        }))
        self.assertNotEqual(nono("profile", "validate", "-s", str(broken)).returncode, 0)


class DefaultModeTest(NonoTestCase):
    def setUp(self):
        super().setUp()
        self.profile = self.build()

    def test_project_files_are_readable(self):
        self.assertReadable(self.profile, "open.txt", "open\n")

    def test_leash_patterns_are_denied(self):
        self.assertDenied(self.profile, "secret.env")
        self.assertDenied(self.profile, "src/nested.env")

    def test_leash_rules_are_denied(self):
        self.assertDenied(self.profile, ".leash")
        self.assertDenied(self.profile, ".leash-agents/default.profile.json")

    def test_git_dir_is_denied(self):
        self.assertDenied(self.profile, ".git/HEAD")

    def test_git_command_is_blocked(self):
        result = self.sandboxed(self.profile, "git", "show", "HEAD:secret.env")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("top secret", result.stdout)
        self.assertIn("leash: git is disabled", result.stderr)

    def test_git_by_absolute_path_is_blocked(self):
        result = self.sandboxed(self.profile, GIT, "show", "HEAD:secret.env")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("top secret", result.stdout)

    def test_extra_grant_reopens_a_leash_deny(self):
        extra = self.root / cli.STATE_DIR / "default.extra.json"
        extra.write_text(json.dumps({"read": ["$WORKDIR/secret.env"]}))
        profile = self.build()
        self.assertReadable(profile, "secret.env", "top secret\n")
        self.assertDenied(profile, "src/nested.env")

    def test_exit_code_passes_through(self):
        self.assertEqual(self.sandboxed(self.profile, "sh", "-c", "exit 7").returncode, 7)


class WithGitModeTest(NonoTestCase):
    def setUp(self):
        super().setUp()
        self.profile = self.build(with_git=True)

    def test_git_works(self):
        result = self.sandboxed(self.profile, "git", "log", "--format=%s")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "init\n")

    def test_git_dir_is_readable(self):
        result = self.sandboxed(self.profile, "cat", ".git/HEAD")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_leash_patterns_still_deny_direct_reads(self):
        self.assertDenied(self.profile, "secret.env")
        self.assertDenied(self.profile, ".leash")

    def test_committed_secret_leaks_through_history(self):
        # The documented trade-off of --with-git. If this starts failing,
        # nono (or leash) closed the gap and the docs should be updated.
        result = self.sandboxed(self.profile, "git", "show", "HEAD:secret.env")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "top secret\n")


if __name__ == "__main__":
    unittest.main()
