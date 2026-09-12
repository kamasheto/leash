# leash

Run a coding agent (`claude`, `codex`, ...) sandboxed with [nono](https://nono.sh), scoped to the current project.

## Requirements

- [nono](https://nono.sh) installed, with a base profile matching your tool name (e.g. `nono profile list` should show `claude` and/or `codex`)
- `git`
- `jq`

## Installation

```sh
git clone git@github.com:kamasheto/leash.git
cd leash
./leash install
```

This symlinks `leash` into `~/.local/bin/leash`. Make sure `~/.local/bin` is on your `PATH`.

## Usage

```
leash <tool> [args...]
```

Run from the root of a git repository.

```sh
leash claude
leash codex
leash claude -p "fix the failing test"
```

Running `leash` with no arguments prints a short usage tip.

## .nono_ignore

Add a `.nono_ignore` file (`.gitignore` syntax) to your project root to deny the agent access to specific files or directories, e.g.:

```
.env
secrets/
*.pem
```

`leash` creates `.nono_ignore` automatically on first run if it doesn't exist. `.nono_ignore` itself is always denied, so the agent can't read or edit its own rules.

## How it works

On each run, `leash` builds a per-project nono profile at `.nono/<tool>.profile.json` (extending the `<tool>` base profile, with `.nono_ignore` compiled into `filesystem.deny`), then runs `<tool>` through `nono run` using that profile. The profile is only rebuilt when `.nono_ignore` changes.

Add `.nono/` to your project's `.gitignore` — it's local, generated state.
