"""Unit tests for leash.py.

Run from the repo root:  uv run pytest tests/test_leash.py

`nono` is stubbed out (see FakeNono in conftest.py), so it doesn't need to be
installed; `git` is real, since .leash pattern matching is delegated to it.
For tests against the real nono, see test_integration.py.
"""

import json
import sys
from pathlib import Path

import pytest

import leash

# Every unit test gets a fake nono and a throwaway nono config dir, so
# nothing here can touch the real ~/.config/nono.
pytestmark = pytest.mark.usefixtures("nono_cfg", "fake_nono")


# --- compute_deny_paths ------------------------------------------------------

def test_no_leash_file_denies_nothing(project):
    assert leash.compute_deny_paths(project.paths()) == []


@pytest.mark.parametrize("patterns, files, expected", [
    pytest.param("*.env\n", ["a.env", "main.py"], ["a.env"], id="glob"),
    # Parent dir not ignored: must still match.
    pytest.param("*.env\n", ["src/main.py", "src/b.env"], ["src/b.env"], id="glob-nested"),
    # git also lists `src/` itself here; the directory must not be denied.
    pytest.param("*.env\n", ["src/b.env"], ["src/b.env"], id="glob-nested-only-match"),
    pytest.param("/a.env\n", ["a.env", "src/a.env"], ["a.env"], id="anchored"),
    pytest.param("src/**/*.env\n", ["a.env", "src/x/y/b.env"], ["src/x/y/b.env"], id="double-star"),
    pytest.param("*.env\n!keep.env\n", ["a.env", "keep.env"], ["a.env"], id="negation"),
    pytest.param("secrets/\n", ["secrets/key.pem"], ["secrets"], id="dir-collapsed"),
    pytest.param("secrets/*\n", ["secrets/key.pem"], ["secrets/key.pem"], id="dir-contents"),
    # leash's checkout tracks `leash.py` and `README.md`; a same-named project
    # file must still be matched as untracked.
    pytest.param("README.md\n", ["README.md"], ["README.md"], id="leash-own-file-not-shadowed"),
    pytest.param(
        "*.env\nsecrets/\n!keep.env\n",
        ["a.env", "src/b.env", "keep.env", "secrets/key.pem", "src/main.py"],
        ["a.env", "secrets", "src/b.env"],
        id="combined",
    ),
])
def test_gitignore_semantics(project, patterns, files, expected):
    project.write(".leash", patterns)
    for rel in files:
        project.write(rel)
    assert sorted(leash.compute_deny_paths(project.paths())) == expected


def test_works_without_project_git_repo(project):
    assert not (project.root / ".git").exists()
    project.write(".leash", "*.env\n")
    project.write("x.env")
    assert leash.compute_deny_paths(project.paths()) == ["x.env"]


# --- build_profile -----------------------------------------------------------

@pytest.mark.parametrize("with_git", [False, True], ids=["default", "with-git"])
def test_protected_paths_are_denied(project, with_git):
    deny = project.profile(with_git=with_git)["filesystem"]["deny"]
    assert "$WORKDIR/.leash" in deny
    assert "$WORKDIR/.leash-agents" in deny
    assert ("$WORKDIR/.git" in deny) is not with_git


def test_git_command_policy_unless_with_git(project):
    assert project.profile()["command_policies"] == leash.GIT_COMMAND_POLICY
    assert "command_policies" not in project.profile(with_git=True)


def test_profile_metadata(project):
    profile = project.profile(tool="codex")
    assert profile["extends"] == "codex"
    assert profile["meta"]["name"] == f"leash-codex-{leash.slugify(project.root.name)}"


def test_leash_patterns_become_denies(project):
    project.write(".leash", "*.env\n")
    project.write("a.env")
    assert "$WORKDIR/a.env" in project.profile()["filesystem"]["deny"]


def test_creates_leash_file_when_missing(project):
    project.build()
    assert (project.root / ".leash").exists()


@pytest.mark.parametrize("kind", ["allow", "read", "write"])
def test_extra_grant_wins_over_leash_deny(project, kind):
    project.write(".leash", "*.env\n")
    project.write("a.env")
    project.write(".leash-agents/claude.extra.json", json.dumps({kind: ["$WORKDIR/a.env"]}))
    fs = project.profile()["filesystem"]
    assert "$WORKDIR/a.env" not in fs["deny"]
    assert fs[kind] == ["$WORKDIR/a.env"]


@pytest.mark.parametrize("kind", ["allow", "read", "write"])
@pytest.mark.parametrize("grant, with_git, kept", [
    ("$WORKDIR/.leash", False, False),
    ("$WORKDIR/.leash-agents/claude.profile.json", False, False),
    ("$WORKDIR/.git/hooks", False, False),
    ("$WORKDIR/.leash", True, False),
    ("$WORKDIR/.git/hooks", True, True),
])
def test_extra_cannot_reopen_protected_paths(project, kind, grant, with_git, kept):
    project.write(".leash-agents/claude.extra.json", json.dumps({kind: [grant, "$WORKDIR/ok"]}))
    fs = project.profile(with_git=with_git)["filesystem"]
    assert fs[kind] == sorted([grant, "$WORKDIR/ok"] if kept else ["$WORKDIR/ok"])


def test_gitignore_gets_state_dir_only_in_git_repos(project):
    project.build()
    assert not (project.root / ".gitignore").exists()
    (project.root / ".git").mkdir()
    project.build()
    project.build()  # idempotent: not appended twice
    assert (project.root / ".gitignore").read_text() == ".leash-agents/\n"


def test_validation_failure_dies(project, fake_nono):
    fake_nono.returncode = 1
    with pytest.raises(SystemExit):
        project.build()


# --- needs_rebuild -----------------------------------------------------------

def test_rebuild_lifecycle(project):
    p = project.paths()
    assert leash.needs_rebuild(p)
    leash.build_profile(p)
    assert not leash.needs_rebuild(p)
    project.write(".leash", "changed\n")
    assert leash.needs_rebuild(p)


def test_toggling_with_git_triggers_rebuild(project):
    project.build(with_git=False)
    assert leash.needs_rebuild(project.paths(with_git=True))
    project.build(with_git=True)
    assert not leash.needs_rebuild(project.paths(with_git=True))
    assert leash.needs_rebuild(project.paths(with_git=False))


# --- absorb_session_grants ---------------------------------------------------

@pytest.fixture
def built(project):
    # main() always builds the profile (creating .leash-agents/) before the
    # session runs, so absorb never sees a bare project.
    return project.build()


@pytest.fixture
def write_nono(nono_cfg):
    """Writes a nono save-profile file: kind is `profile-drafts` or `profiles`."""
    def write(kind: str, name: str, filesystem: dict) -> Path:
        path = nono_cfg / "nono" / kind / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"filesystem": filesystem}))
        return path
    return write


def test_nothing_to_absorb_is_a_noop(built, fake_nono):
    before = built.ignore_path.read_text()
    fake_nono.calls.clear()
    leash.absorb_session_grants(built)
    assert built.ignore_path.read_text() == before
    assert fake_nono.calls == []  # no rebuild


def test_draft_is_absorbed_and_deleted(built, write_nono):
    draft = write_nono("profile-drafts", built.profile_name, {
        "deny": ["$WORKDIR/secret.txt", "/etc/outside"],
        "read": ["/usr/share/thing"],
    })
    draft.with_suffix(".base").write_text("{}")
    leash.absorb_session_grants(built)
    assert "secret.txt" in built.ignore_path.read_text().splitlines()
    extra = leash.load_extra(built.extra_path)
    assert extra["deny"] == ["/etc/outside"]
    assert extra["read"] == ["/usr/share/thing"]
    assert not draft.exists()
    assert not draft.with_suffix(".base").exists()
    # Rebuilt immediately, so the new deny is already in the profile.
    profile = json.loads(built.profile_path.read_text())
    assert "/etc/outside" in profile["filesystem"]["deny"]


def test_promoted_profile_under_plain_tool_name(built, write_nono):
    promoted = write_nono("profiles", "claude", {"allow": ["/opt/tool"]})
    leash.absorb_session_grants(built)
    assert leash.load_extra(built.extra_path)["allow"] == ["/opt/tool"]
    assert not promoted.exists()


def test_grant_strips_matching_leash_line(project, built, write_nono):
    project.write(".leash", "a.env\nb.env\n")
    write_nono("profile-drafts", built.profile_name, {"allow": ["$WORKDIR/a.env"]})
    leash.absorb_session_grants(built)
    assert built.ignore_path.read_text().splitlines() == ["b.env"]


# --- main --------------------------------------------------------------------

@pytest.fixture
def run_main(project, monkeypatch, capsys):
    """Runs main() as `leash <argv...>` from the project dir and returns
    (exit code, stdout, stderr)."""
    monkeypatch.setattr(leash, "require_cmd", lambda *a, **k: None)
    monkeypatch.setattr(Path, "cwd", lambda: project.root)

    def run(*argv: str):
        monkeypatch.setattr(sys, "argv", ["leash", *argv])
        try:
            leash.main()
            code = 0
        except SystemExit as e:
            code = e.code
        out, err = capsys.readouterr()
        return code, out, err
    return run


@pytest.mark.parametrize("argv, code, stream, text", [
    pytest.param([], 0, "out", "usage: leash", id="no-args"),
    pytest.param(["--help"], 0, "out", "--with-git", id="help"),
    pytest.param(["--bogus", "claude"], 1, "err", "unknown option '--bogus'", id="unknown-flag"),
])
def test_arg_handling(run_main, argv, code, stream, text):
    got_code, out, err = run_main(*argv)
    assert got_code == code
    assert text in {"out": out, "err": err}[stream]


def test_runs_tool_through_nono_and_passes_args(project, run_main, fake_nono):
    code, _, _ = run_main("claude", "--with-git", "-p", "hi there")
    assert code == 0
    run = [c for c in fake_nono.calls if c.startswith("nono run ")]
    assert len(run) == 1
    # Flags after the tool name belong to the tool, not to leash.
    assert run[0].endswith("-- claude --with-git -p 'hi there'")
    profile = json.loads(project.paths().profile_path.read_text())
    assert "command_policies" in profile


def test_with_git_flag_before_tool(project, run_main):
    code, _, err = run_main("--with-git", "claude")
    assert code == 0
    assert "--with-git" in err  # warning printed
    profile = json.loads(project.paths().profile_path.read_text())
    assert "command_policies" not in profile


def test_tool_exit_code_is_propagated(project, run_main, fake_nono):
    # Build first: FakeNono's returncode applies to every nono call, and a
    # non-zero `nono profile validate` would die before the run.
    project.build()
    fake_nono.returncode = 3
    code, _, _ = run_main("claude")
    assert code == 3
