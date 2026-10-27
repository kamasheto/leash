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


# --- install: ensure_nono ----------------------------------------------------

class FakeInstall:
    """Stands in for leash.run_cmd during install: `nono profile show <name>`
    succeeds only for profiles in `profiles`; `brew install` / `nono pull`
    succeed unless listed in `failing`. Every call is recorded."""

    def __init__(self, profiles=(), failing=()):
        self.profiles = set(profiles)
        self.failing = set(failing)
        self.calls: list[str] = []

    def __call__(self, cmd: str, **kwargs):
        self.calls.append(cmd)
        if cmd.startswith("nono profile show "):
            ok = cmd.split()[-1] in self.profiles
        else:
            ok = cmd not in self.failing
        return leash.subprocess.CompletedProcess(cmd, 0 if ok else 1)


@pytest.fixture
def install_env(monkeypatch):
    """Returns setup(answers, nono_on_path, profiles, failing) -> FakeInstall,
    with input() answering from `answers` in order (EOF once exhausted)."""
    def setup(answers=(), nono_on_path=True, profiles=(), failing=()):
        fake = FakeInstall(profiles, failing)
        monkeypatch.setattr(leash, "run_cmd", fake)
        on_path = {"brew", "nono"} if nono_on_path else {"brew"}
        monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}" if name in on_path else None)
        queue = list(answers)

        def fake_input(prompt):  # like input() without a terminal: no echo
            sys.stdout.write(prompt)
            if not queue:
                raise EOFError
            return queue.pop(0)
        monkeypatch.setattr("builtins.input", fake_input)
        return fake
    return setup


def test_ensure_nono_declined_stops(install_env):
    fake = install_env(answers=["n"], nono_on_path=False)
    with pytest.raises(SystemExit):
        leash.ensure_nono()
    assert fake.calls == []


def test_ensure_nono_installs_nono_then_profiles(install_env):
    fake = install_env(answers=["y", "y", "n"], nono_on_path=False)
    leash.ensure_nono()
    assert "brew install nono" in fake.calls
    assert "nono pull nolabs-ai/claude" in fake.calls
    assert "nono pull nolabs-ai/codex" not in fake.calls


def test_ensure_nono_brew_failure_stops(install_env):
    install_env(answers=["y"], nono_on_path=False, failing={"brew install nono"})
    with pytest.raises(SystemExit):
        leash.ensure_nono()


def test_ensure_nono_existing_profiles_skip_prompts(install_env):
    fake = install_env(profiles={"claude", "codex"})  # input() would EOF -> no
    leash.ensure_nono()
    assert not any(c.startswith("nono pull") or c.startswith("brew") for c in fake.calls)


@pytest.mark.parametrize("answers, failing", [
    pytest.param(["n", "n"], (), id="both-declined"),
    pytest.param(["y", "y"], {"nono pull nolabs-ai/claude", "nono pull nolabs-ai/codex"},
                 id="both-pulls-fail"),
])
def test_ensure_nono_no_profile_stops(install_env, answers, failing):
    install_env(answers=answers, failing=failing)
    with pytest.raises(SystemExit):
        leash.ensure_nono()


def test_ensure_nono_one_profile_is_enough(install_env):
    fake = install_env(answers=["n", "y"])
    leash.ensure_nono()
    assert "nono pull nolabs-ai/codex" in fake.calls


def test_install_stops_before_symlink_when_nono_declined(install_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    install_env(answers=["n"], nono_on_path=False)
    with pytest.raises(SystemExit):
        leash.run_install()
    assert not (tmp_path / ".local" / "bin" / "leash").exists()


# --- update ------------------------------------------------------------------

UPDATE_CMDS = ("git -C", "brew upgrade nono", "nono update")


@pytest.mark.parametrize("answers, expected", [
    pytest.param(["y", "y", "y"], UPDATE_CMDS, id="all"),
    pytest.param([], (), id="eof-means-no"),
    pytest.param(["n", "y", "n"], ("brew upgrade nono",), id="only-brew"),
])
def test_update_runs_only_confirmed_steps(install_env, answers, expected):
    fake = install_env(answers=answers)
    leash.run_update()
    assert len(fake.calls) == len(expected)
    assert all(c.startswith(prefix) for c, prefix in zip(fake.calls, expected))


def test_update_pulls_leash_checkout(install_env):
    fake = install_env(answers=["y"])
    leash.run_update()
    root = Path(leash.__file__).resolve().parent
    assert fake.calls == [f"git -C {leash.quote(str(root))} pull --ff-only"]


def test_update_failure_continues(install_env, capsys):
    fake = install_env(answers=["n", "y", "y"], failing={"brew upgrade nono"})
    leash.run_update()
    assert fake.calls == ["brew upgrade nono", "nono update"]
    assert capsys.readouterr().out.splitlines() == [
        "🦮 Update leash in "
        f"{Path(leash.__file__).resolve().parent} with `git pull --ff-only`? (Y/n) n 🛑",
        "🦮 Upgrade nono with `brew upgrade nono`? (Y/n) Y ❌",
        "🦮 Update the installed nono packs with `nono update`? (Y/n) Y ✅",
    ]


# --- step / run_step / --verbose ---------------------------------------------

@pytest.mark.parametrize("typed, yes, shown", [
    pytest.param("", True, "Y", id="enter-means-yes"),
    pytest.param("y", True, "Y", id="y"),
    pytest.param("YES", True, "Y", id="yes"),
    pytest.param("n", False, "n 🛑\n", id="n"),
    pytest.param("whatever", False, "n 🛑\n", id="other"),
    pytest.param(None, False, "n 🛑\n", id="eof-means-no"),
])
def test_confirm(install_env, capsys, typed, yes, shown):
    install_env(answers=[] if typed is None else [typed])
    assert leash.confirm("Go?") is yes
    assert capsys.readouterr().out == f"🦮 Go? (Y/n) {shown}"


@pytest.fixture
def real_run_cmd(monkeypatch):
    monkeypatch.setattr(leash, "run_cmd",
                        lambda cmd, **kw: leash.subprocess.run(leash.shlex.split(cmd), **kw))


@pytest.mark.parametrize("cmd, ok, mark", [
    pytest.param("echo hi", True, "✅", id="success"),
    pytest.param("sh -c 'echo hi; exit 1'", False, "❌", id="failure"),
    pytest.param("no-such-command-xyz", False, "❌", id="missing"),
])
def test_run_step_silent_shows_output_only_on_failure(real_run_cmd, capfd, cmd, ok, mark):
    # run_step carries on a line confirm() already printed, so only the
    # dots and the mark are new.
    assert leash.run_step("🦮 Go? (Y/n) Y", cmd, verbose=False) is ok
    out, err = capfd.readouterr()
    assert out.startswith(" ") and out.endswith(f"{mark}\n")
    assert "\n" not in out[:-1] and "hi" not in out
    assert bool(err) is not ok


def test_run_step_verbose_streams_output_above_progress(real_run_cmd, capfd):
    assert leash.run_step("🦮 Go? (Y/n) Y", "echo hi", verbose=True)
    # Without a terminal the progress line can't be redrawn below the output,
    # so it's repeated when the step ends.
    assert capfd.readouterr().out == " \nhi\n🦮 Go? (Y/n) Y ✅\n"


def test_run_step_callable_failure(capfd):
    def fail():
        raise PermissionError("nope")
    assert not leash.run_step("🦮 Go? (Y/n) Y", fail, verbose=False)
    out, err = capfd.readouterr()
    assert out == " ❌\n" and "nope" in err


def test_step_declined_skips_action(install_env, capsys):
    install_env(answers=["n"])
    ran = []
    assert not leash.step("Go?", lambda: ran.append(1))
    assert ran == [] and capsys.readouterr().out == "🦮 Go? (Y/n) n 🛑\n"


@pytest.mark.parametrize("argv, verbose", [
    pytest.param(["update"], False, id="default"),
    pytest.param(["--verbose", "update"], True, id="verbose"),
])
def test_verbose_flag_reaches_subcommand(run_main, monkeypatch, argv, verbose):
    seen = []
    monkeypatch.setattr(leash, "run_update", seen.append)
    code, out, _ = run_main(*argv)
    assert code == 0 and seen == [verbose]
    assert ("`leash --verbose update`" in out) is not verbose


def test_silent_notice_skipped_after_install_sh(run_main, monkeypatch):
    monkeypatch.setattr(leash, "run_install", lambda verbose: None)
    monkeypatch.setenv("LEASH_NOTICE_SHOWN", "1")
    assert "silent mode" not in run_main("install")[1]


@pytest.mark.parametrize("argv, text", [
    pytest.param(["--verbose", "claude"], "--verbose only applies", id="with-tool"),
    pytest.param(["update", "--verbose"], "'update' takes no arguments", id="after-name"),
])
def test_verbose_flag_errors(run_main, argv, text):
    code, _, err = run_main(*argv)
    assert code == 1 and text in err


# --- uninstall ---------------------------------------------------------------

@pytest.fixture
def fake_checkout(tmp_path, monkeypatch):
    """A scratch leash checkout that leash.__file__ points into, plus a HOME
    whose ~/.local/bin/leash links to its `cli`."""
    root = tmp_path / "share" / "leash"
    root.mkdir(parents=True)
    (root / "leash.py").write_text("")
    (root / "cli").symlink_to("leash.py")
    monkeypatch.setattr(leash, "__file__", str(root / "leash.py"))
    home = tmp_path / "home"
    link = home / ".local" / "bin" / "leash"
    link.parent.mkdir(parents=True)
    link.symlink_to(root.resolve() / "cli")
    monkeypatch.setenv("HOME", str(home))
    return root, link


def test_uninstall_declined_keeps_everything(install_env, fake_checkout):
    root, link = fake_checkout
    fake = install_env()  # input() EOFs -> no
    leash.run_uninstall()
    assert fake.calls == []
    assert root.exists() and link.is_symlink()


def test_uninstall_all_steps(install_env, fake_checkout):
    root, link = fake_checkout
    fake = install_env(answers=["y", "y"])
    leash.run_uninstall()
    assert fake.calls == ["brew uninstall nono"]
    assert not root.exists() and not link.is_symlink()


def test_uninstall_leaves_foreign_symlink(install_env, fake_checkout, tmp_path):
    root, link = fake_checkout
    link.unlink()
    link.symlink_to(tmp_path / "elsewhere")
    install_env(answers=["n", "y"])
    leash.run_uninstall()
    assert not root.exists() and link.is_symlink()


def test_uninstall_brew_failure_continues(install_env, fake_checkout, capsys):
    root, _ = fake_checkout
    install_env(answers=["y", "y"], failing={"brew uninstall nono"})
    leash.run_uninstall()
    assert not root.exists()
    out = capsys.readouterr().out
    assert "🦮 Uninstall nono with `brew uninstall nono`? (Y/n) Y ❌\n" in out
    assert out.endswith("(Y/n) Y ✅\n")


# --- install: PATH setup -----------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    """A scratch $HOME with no ZDOTDIR and a Linux-style bash setup, where
    every confirm() is answered yes (override with `answer`)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.setattr(leash.sys, "platform", "linux")
    monkeypatch.setattr(leash, "confirm", lambda question: True)
    return tmp_path


def answer(monkeypatch, yes):
    """Answers every confirm() with `yes`, recording the questions asked."""
    questions = []

    def fake_confirm(question):
        questions.append(question)
        return yes
    monkeypatch.setattr(leash, "confirm", fake_confirm)
    return questions


@pytest.mark.parametrize("shell, rc", [
    ("/bin/zsh", ".zshrc"),
    ("/bin/bash", ".bashrc"),
    ("/usr/bin/fish", ".config/fish/conf.d/leash.fish"),
])
def test_path_added_for_login_shell(home, monkeypatch, shell, rc):
    monkeypatch.setenv("SHELL", shell)
    leash.add_bin_dir_to_path()
    assert leash.PATH_MARKER in (home / rc).read_text()
    assert [f.name for f in home.iterdir() if f.is_file()] == ([rc] if "/" not in rc else [])


def test_path_added_for_other_set_up_shells(home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    (home / ".bashrc").write_text("alias ll='ls -l'")  # no trailing newline
    leash.add_bin_dir_to_path()
    assert (home / ".bashrc").read_text() == (
        f"alias ll='ls -l'\n\n{leash.PATH_MARKER}\n{leash.POSIX_PATH_LINE}\n")
    assert leash.PATH_MARKER in (home / ".zshrc").read_text()


def test_path_bash_on_macos_uses_bash_profile(home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(leash.sys, "platform", "darwin")
    leash.add_bin_dir_to_path()
    assert leash.PATH_MARKER in (home / ".bash_profile").read_text()
    assert not (home / ".bashrc").exists()


def test_path_zsh_honors_zdotdir(home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("ZDOTDIR", str(home / "zsh"))
    leash.add_bin_dir_to_path()
    assert leash.PATH_MARKER in (home / "zsh" / ".zshrc").read_text()


def test_path_not_added_twice(home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    (home / ".zshrc").write_text('export PATH="$HOME/.local/bin:$PATH"\n')
    questions = answer(monkeypatch, True)
    leash.add_bin_dir_to_path()
    leash.add_bin_dir_to_path()
    assert (home / ".zshrc").read_text() == 'export PATH="$HOME/.local/bin:$PATH"\n'
    assert questions == []


def test_path_declined_leaves_files_alone(home, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    (home / ".bashrc").write_text("alias ll='ls -l'\n")
    questions = answer(monkeypatch, False)
    leash.add_bin_dir_to_path()
    assert len(questions) == 1 and ".zshrc" in questions[0] and ".bashrc" in questions[0]
    assert not (home / ".zshrc").exists()
    assert (home / ".bashrc").read_text() == "alias ll='ls -l'\n"
    assert "export PATH=" in capsys.readouterr().out


def test_path_unknown_shell_only_warns(home, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/usr/bin/nu")
    leash.add_bin_dir_to_path()
    assert list(home.iterdir()) == []
    assert "doesn't know your shell" in capsys.readouterr().out


@pytest.mark.parametrize("line", [leash.POSIX_PATH_LINE])
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_posix_path_line_is_idempotent(shell, line, home):
    from shutil import which
    if which(shell) is None:
        pytest.skip(f"{shell} not installed")
    out = leash.subprocess.run(
        [shell, "-c", f'PATH=/usr/bin:/bin; {line}; {line}; echo "$PATH"'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == f"{home}/.local/bin:/usr/bin:/bin"


# --- install: symlink --------------------------------------------------------

@pytest.fixture
def install_home(home, monkeypatch):
    """`home`, with nono already set up and ~/.local/bin off PATH."""
    monkeypatch.setattr(leash, "ensure_nono", lambda verbose=False: None)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    return home


def cli_path():
    return Path(leash.__file__).resolve().parent / "cli"


def test_install_creates_symlink_and_path(install_home):
    leash.run_install()
    assert (install_home / ".local" / "bin" / "leash").readlink() == cli_path()
    assert leash.PATH_MARKER in (install_home / ".zshrc").read_text()


def test_install_declined_changes_nothing(install_home, monkeypatch):
    questions = answer(monkeypatch, False)
    leash.run_install()
    assert len(questions) == 1  # the symlink; PATH isn't offered without it
    assert not (install_home / ".local").exists()
    assert not (install_home / ".zshrc").exists()


def test_install_replaces_other_symlink_only_if_confirmed(install_home, monkeypatch):
    target = install_home / ".local" / "bin" / "leash"
    target.parent.mkdir(parents=True)
    target.symlink_to("/somewhere/else")
    questions = answer(monkeypatch, False)
    leash.run_install()
    assert questions[0].startswith("Replace ")
    assert target.readlink() == Path("/somewhere/else")


def test_install_existing_symlink_needs_no_prompt(install_home, monkeypatch):
    target = install_home / ".local" / "bin" / "leash"
    target.parent.mkdir(parents=True)
    target.symlink_to(cli_path())
    monkeypatch.setenv("PATH", f"{target.parent}:/usr/bin")
    questions = answer(monkeypatch, True)
    leash.run_install()
    assert questions == []
