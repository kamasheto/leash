![leash](https://sakr.me/post-heroes/leash.png)

# leash

Run a coding agent (`claude`, `codex`, ...) sandboxed with [nono](https://nono.sh), scoped to the current project.

```sh
cd my-project
leash claude
```

The agent can work inside the project, but can't touch anything you list in `.leash`.

## Requirements

| Requirement | Notes |
| --- | --- |
| [nono](https://nono.sh) | Needs a base profile named after your tool. `nono profile list` should show `claude` and/or `codex`. |
| Python 3.9+ | No third-party packages needed. |
| git | Used to match `.leash` patterns. Your project doesn't need to be a git repository. |

## Installation

<details>
  <summary>Install nono first, if you don't have it (click to expand)</summary>
  <blockquote>
    <sub>Latest instructions at https://nono.sh</sub>

```sh
brew install nono

# if needed: base profile for claude
nono pull nolabs-ai/claude

# if needed: base profile for codex
nono pull nolabs-ai/codex
```
  </blockquote>
</details>

```sh
git clone git@github.com:kamasheto/leash.git
./leash/cli install
```

`install` symlinks `~/.local/bin/leash` to `leash/cli`. Make sure `~/.local/bin` is on your `PATH`.

> [!NOTE]
> Install with `git clone`, not by downloading the script on its own. leash uses its own checkout to match `.leash` patterns.

## Usage

```
leash [options] <tool> [args...]
```

Run it from your project's root directory. leash's options go **before** `<tool>`. Everything after `<tool>` is passed to the tool unchanged.

| Command | What it does |
| --- | --- |
| `leash claude` | Run Claude Code in the sandbox |
| `leash codex` | Run Codex in the sandbox |
| `leash claude -p "fix the failing test"` | Pass arguments through to the tool |
| `leash --with-git claude` | Run with git access for this session |
| `leash install` | Symlink leash into `~/.local/bin` |
| `leash [--help]`  | Show usage |

### Options

| Option | Effect |
| --- | --- |
| `--with-git` | Lets the agent use `git` and access `.git/` for this session. Both are denied by default; see [Always denied](#always-denied) for why. |

## Configuring access

Day to day, there are only two files you should ever need to touch:

| File | Purpose | Commit it? |
| --- | --- | --- |
| `.leash` | Files and directories the agent must not access | Yes |
| `.leash-agents/<tool>.extra.json` | Extra grants picked up from nono's save-profile prompt | No (auto-gitignored) |

### `.leash`

Uses `.gitignore` syntax and lives in your project root. leash creates it on the first run if it doesn't exist.

```gitignore
.env
secrets/
*.pem
```

### Always denied

Some paths are denied whatever `.leash` says. Nothing in `extra.json` can re-open them.

| Path | Why | Lift with |
| --- | --- | --- |
| `.leash`, `.leash-agents/` | So the agent can't read or edit its own rules | — |
| `.git/` and the `git` command | Any file that is or ever was committed could otherwise be read back from history (`git show HEAD:.env`, `git log -p`, or by decompressing `.git/objects`). The agent could also plant git hooks or config that later run **outside** the sandbox. | `--with-git` |

By default **the agent has no git access inside leash**. You can run commits, diffs and other git commands yourself, outside the sandbox. You can also pass `--with-git` for a session, but that brings back both risks above.

### `.leash-agents/<tool>.extra.json`

This file holds grants the agent picked up from a [post-session save-profile prompt](#post-session-save-profile-prompts). To revoke one, remove the path from its array. It's denied again on the next run.

```jsonc
{
  "deny": [],
  "allow": ["/some/path/the/agent/was/granted"],
  "read": [],
  "write": []
}
```

| Array | Grants |
| --- | --- |
| `allow` | Read **and** write access |
| `read` | Read-only access |
| `write` | Write-only access (for directories, not deletion) |
| `deny` | Denials that `.leash` can't express, such as paths outside the project |

If a path appears both here (in `allow`, `read` or `write`) and in `.leash`, this file wins.

Everything else under `.leash-agents/` is generated and disposable. leash rebuilds it as needed and adds `.leash-agents/` to your project's `.gitignore` (if the project is a git repository).

## How it works

1. **Build a profile.** leash writes a per-project nono profile to `.leash-agents/<tool>.profile.json`. It extends your `<tool>` base profile with:
   - the patterns in `.leash`,
   - the grants in `extra.json`,
   - the [always-denied](#always-denied) paths.

   The profile is only rebuilt when `.leash`, `extra.json`, leash itself, or the `--with-git` setting changes.
2. **Run the tool.** It runs `<tool>` through `nono run` with that profile.
3. **Absorb prompt answers.** After the session, it pulls your answers to nono's save-profile prompt back into the project (see below).

### Post-session save-profile prompts

After a session, nono may ask whether to save access to paths the agent tried to use. nono saves those answers to its own global config, not to this project. On its own, that means the answers would never apply to the next leash run. So after each run, leash pulls them back in:

| Answer | Where it goes |
| --- | --- |
| Deny a path inside the project | Appended to `.leash` |
| Anything else (allow/read/write, or paths outside the project) | `.leash-agents/<tool>.extra.json` |

leash then deletes nono's global copy and rebuilds the profile straight away, so your answers apply from the next run onwards.

## Contributing

Issues and pull requests are welcome.

- **Everything is in one file.** leash is the `cli` script, written for the Python 3 standard library. There's no build step and no dependencies to install.
- **No third-party packages.** Keep the external tools down to `nono` and `git` (unless there's a good reason otherwise.)
- **Shell commands** go through `run_cmd()`. Wrap every variable in `quote()`, and never use `shell=True`.
- **Don't weaken the defaults.** A change that relaxes the [always-denied](#always-denied) rules should be opt-in, like `--with-git`, and explain the trade-off.
- **Tests** live in `tests/` and use the standard library's `unittest`, so there's nothing to install. Run them all from the repo root:
  ```sh
  python3 tests                  # every test, listed with its result
  python3 tests -k integration   # only tests whose name matches
  ```

  | Suite | Needs | What it checks |
  | --- | --- | --- |
  | `test_cli.py` (unit) | Python, git | leash's logic. nono is stubbed out. Fast. |
  | `test_integration.py` | nono on `PATH` | Generated profiles pass `nono profile validate`, and the real sandbox enforces them (`cat` and `git` run inside nono). Skipped if nono isn't installed. |

  Add or update tests for any change in behavior. If your change affects what the sandbox allows or denies, add an integration test too. CI runs the unit tests on Linux and macOS, on the oldest and newest Python versions leash supports. It doesn't install nono, so run the integration tests locally.
- **Before opening a PR**, also run `./cli claude` (or another tool) in a scratch directory, both with and without `git init`. If your change affects the profile, check the generated `.leash-agents/<tool>.profile.json`.
- **Update the docs.** If you change behavior, update this README and `AGENTS.md` too.

By contributing, you agree that your contributions are licensed under the project's MIT license.

## License

[MIT](LICENSE) © 2026 Mahmoud Sakr
