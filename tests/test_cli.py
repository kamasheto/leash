"""Unit tests for leash's `cli` script.

Run from the repo root:  python3 tests

Uses only the standard library. `nono` is stubbed out (see FakeNono), so it
doesn't need to be installed; `git` is real, since .leash pattern matching
is delegated to it. For tests against the real nono, see test_integration.py.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import load_cli

cli = load_cli()


class FakeNono:
    """Stands in for cli.run_cmd: records `nono ...` commands and pretends
    they succeeded, and passes everything else (git) through for real."""

    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls: list[str] = []
        self._real = cli.run_cmd

    def __call__(self, cmd: str, **kwargs):
        if not cmd.startswith("nono "):
            return self._real(cmd, **kwargs)
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr="")


class ProjectTestCase(unittest.TestCase):
    """Each test gets a fresh scratch project dir and a fake nono config dir."""

    def patch(self, patcher):
        # Like TestCase.enterContext, which needs Python 3.11+.
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="leash-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "project"
        self.root.mkdir()
        self.nono_cfg = Path(tmp.name) / "xdg"
        self.patch(mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.nono_cfg)}))
        self.nono = FakeNono()
        self.patch(mock.patch.object(cli, "run_cmd", self.nono))

    def paths(self, tool: str = "claude", with_git: bool = False):
        return cli.Paths(tool=tool, project_root=self.root, with_git=with_git)

    def write(self, rel: str, text: str = "") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def build(self, **kwargs) -> dict:
        p = self.paths(**kwargs)
        cli.build_profile(p)
        return json.loads(p.profile_path.read_text())


class ComputeDenyPathsTest(ProjectTestCase):
    def test_no_leash_file_denies_nothing(self):
        self.assertEqual(cli.compute_deny_paths(self.paths()), [])

    def test_gitignore_semantics(self):
        self.write(".leash", "*.env\nsecrets/\n!keep.env\n")
        self.write("a.env")
        self.write("src/b.env")  # parent dir not ignored: must still match
        self.write("keep.env")
        self.write("secrets/key.pem")
        self.write("src/main.py")
        deny = cli.compute_deny_paths(self.paths())
        self.assertEqual(sorted(deny), ["a.env", "secrets", "src/b.env"])

    def test_works_without_project_git_repo(self):
        self.assertFalse((self.root / ".git").exists())
        self.write(".leash", "*.env\n")
        self.write("x.env")
        self.assertEqual(cli.compute_deny_paths(self.paths()), ["x.env"])

    def test_leash_own_tracked_files_dont_shadow_project_files(self):
        # leash's checkout tracks `cli` and `README.md`; a same-named project
        # file must still be matched as untracked.
        self.write(".leash", "README.md\n")
        self.write("README.md")
        self.assertEqual(cli.compute_deny_paths(self.paths()), ["README.md"])


class BuildProfileTest(ProjectTestCase):
    def test_default_denies_git(self):
        profile = self.build()
        self.assertIn("$WORKDIR/.git", profile["filesystem"]["deny"])
        self.assertIn("$WORKDIR/.leash", profile["filesystem"]["deny"])
        self.assertIn("$WORKDIR/.leash-agents", profile["filesystem"]["deny"])
        self.assertEqual(profile["command_policies"], cli.GIT_COMMAND_POLICY)

    def test_with_git_allows_git(self):
        profile = self.build(with_git=True)
        self.assertNotIn("$WORKDIR/.git", profile["filesystem"]["deny"])
        self.assertIn("$WORKDIR/.leash", profile["filesystem"]["deny"])
        self.assertNotIn("command_policies", profile)

    def test_profile_metadata(self):
        profile = self.build(tool="codex")
        self.assertEqual(profile["extends"], "codex")
        self.assertEqual(profile["meta"]["name"], f"leash-codex-{cli.slugify(self.root.name)}")

    def test_leash_patterns_become_denies(self):
        self.write(".leash", "*.env\n")
        self.write("a.env")
        self.assertIn("$WORKDIR/a.env", self.build()["filesystem"]["deny"])

    def test_creates_leash_file_when_missing(self):
        self.build()
        self.assertTrue((self.root / ".leash").exists())

    def test_extra_grant_wins_over_leash_deny(self):
        self.write(".leash", "*.env\n")
        self.write("a.env")
        self.write(".leash-agents/claude.extra.json", json.dumps({"read": ["$WORKDIR/a.env"]}))
        fs = self.build()["filesystem"]
        self.assertNotIn("$WORKDIR/a.env", fs["deny"])
        self.assertEqual(fs["read"], ["$WORKDIR/a.env"])

    def test_extra_cannot_reopen_protected_paths(self):
        self.write(".leash-agents/claude.extra.json", json.dumps({
            "allow": ["$WORKDIR/.leash", "$WORKDIR/.git/hooks", "$WORKDIR/ok"],
        }))
        fs = self.build()["filesystem"]
        self.assertEqual(fs["allow"], ["$WORKDIR/ok"])
        self.assertIn("$WORKDIR/.git", fs["deny"])

    def test_with_git_lets_extra_grant_git_paths(self):
        self.write(".leash-agents/claude.extra.json", json.dumps({"allow": ["$WORKDIR/.git/hooks"]}))
        self.assertEqual(self.build(with_git=True)["filesystem"]["allow"], ["$WORKDIR/.git/hooks"])

    def test_gitignore_gets_state_dir_only_in_git_repos(self):
        self.build()
        self.assertFalse((self.root / ".gitignore").exists())
        (self.root / ".git").mkdir()
        self.build()
        self.build()  # idempotent: not appended twice
        self.assertEqual((self.root / ".gitignore").read_text(), ".leash-agents/\n")

    def test_validation_failure_dies(self):
        self.nono.returncode = 1
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.build()


class NeedsRebuildTest(ProjectTestCase):
    def test_rebuild_lifecycle(self):
        p = self.paths()
        self.assertTrue(cli.needs_rebuild(p))
        cli.build_profile(p)
        self.assertFalse(cli.needs_rebuild(p))
        self.write(".leash", "changed\n")
        self.assertTrue(cli.needs_rebuild(p))

    def test_toggling_with_git_triggers_rebuild(self):
        cli.build_profile(self.paths(with_git=False))
        self.assertTrue(cli.needs_rebuild(self.paths(with_git=True)))
        cli.build_profile(self.paths(with_git=True))
        self.assertFalse(cli.needs_rebuild(self.paths(with_git=True)))
        self.assertTrue(cli.needs_rebuild(self.paths(with_git=False)))


class AbsorbSessionGrantsTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        # main() always builds the profile (creating .leash-agents/) before
        # the session runs, so absorb never sees a bare project.
        cli.build_profile(self.paths())

    def write_nono(self, kind: str, name: str, filesystem: dict) -> Path:
        path = self.nono_cfg / "nono" / kind / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"filesystem": filesystem}))
        return path

    def absorb(self, p):
        with contextlib.redirect_stderr(io.StringIO()):
            cli.absorb_session_grants(p)

    def test_nothing_to_absorb_is_a_noop(self):
        p = self.paths()
        before = p.ignore_path.read_text()
        self.nono.calls.clear()
        self.absorb(p)
        self.assertEqual(p.ignore_path.read_text(), before)
        self.assertEqual(self.nono.calls, [])  # no rebuild

    def test_draft_is_absorbed_and_deleted(self):
        p = self.paths()
        draft = self.write_nono("profile-drafts", p.profile_name, {
            "deny": ["$WORKDIR/secret.txt", "/etc/outside"],
            "read": ["/usr/share/thing"],
        })
        draft.with_suffix(".base").write_text("{}")
        self.absorb(p)
        self.assertIn("secret.txt", p.ignore_path.read_text().splitlines())
        extra = cli.load_extra(p.extra_path)
        self.assertEqual(extra["deny"], ["/etc/outside"])
        self.assertEqual(extra["read"], ["/usr/share/thing"])
        self.assertFalse(draft.exists())
        self.assertFalse(draft.with_suffix(".base").exists())
        # Rebuilt immediately, so the new deny is already in the profile.
        profile = json.loads(p.profile_path.read_text())
        self.assertIn("/etc/outside", profile["filesystem"]["deny"])

    def test_promoted_profile_under_plain_tool_name(self):
        p = self.paths()
        promoted = self.write_nono("profiles", "claude", {"allow": ["/opt/tool"]})
        self.absorb(p)
        self.assertEqual(cli.load_extra(p.extra_path)["allow"], ["/opt/tool"])
        self.assertFalse(promoted.exists())

    def test_grant_strips_matching_leash_line(self):
        p = self.paths()
        self.write(".leash", "a.env\nb.env\n")
        self.write_nono("profile-drafts", p.profile_name, {"allow": ["$WORKDIR/a.env"]})
        self.absorb(p)
        self.assertEqual(p.ignore_path.read_text().splitlines(), ["b.env"])


class MainTest(ProjectTestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["leash", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        super().setUp()
        self.patch(mock.patch.object(cli, "require_cmd"))
        self.patch(mock.patch.object(Path, "cwd", return_value=self.root))

    def test_no_args_prints_usage(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("usage: leash", out)

    def test_help_flag(self):
        code, out, _ = self.run_main("--help")
        self.assertEqual(code, 0)
        self.assertIn("--with-git", out)

    def test_unknown_flag_dies(self):
        code, _, err = self.run_main("--bogus", "claude")
        self.assertEqual(code, 1)
        self.assertIn("unknown option '--bogus'", err)

    def test_runs_tool_through_nono_and_passes_args(self):
        code, _, _ = self.run_main("claude", "--with-git", "-p", "hi there")
        self.assertEqual(code, 0)
        run = [c for c in self.nono.calls if c.startswith("nono run ")]
        self.assertEqual(len(run), 1)
        # Flags after the tool name belong to the tool, not to leash.
        self.assertTrue(run[0].endswith("-- claude --with-git -p 'hi there'"))
        profile = json.loads(self.paths().profile_path.read_text())
        self.assertIn("command_policies", profile)

    def test_with_git_flag_before_tool(self):
        code, _, err = self.run_main("--with-git", "claude")
        self.assertEqual(code, 0)
        self.assertIn("--with-git", err)  # warning printed
        profile = json.loads(self.paths().profile_path.read_text())
        self.assertNotIn("command_policies", profile)

    def test_tool_exit_code_is_propagated(self):
        # Build first: FakeNono's returncode applies to every nono call, and
        # a non-zero `nono profile validate` would die before the run.
        cli.build_profile(self.paths())
        self.nono.returncode = 3
        code, _, _ = self.run_main("claude")
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
