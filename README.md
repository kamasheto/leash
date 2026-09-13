![leash](https://sakr.me/post-heroes/leash.png)

# leash

Run a coding agent (`claude`, `codex`, ...) sandboxed with [nono](https://nono.sh), scoped to the current project.

## Requirements

- [nono](https://nono.sh) installed, with a base profile matching your tool name (e.g. `nono profile list` should show `claude` and/or `codex`)
- `git`
- Python 3 (standard library only — no extra packages to install)

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

## Configuring access

Day to day, there are only two files you should ever need to touch:

- **`.nono_ignore`** — deny the agent access to specific files or directories. `.gitignore` syntax, lives in your project root, and is meant to be committed. `leash` creates it automatically on first run if it doesn't exist:

  ```
  .env
  secrets/
  *.pem
  ```

  `.nono_ignore` itself is always denied too, so the agent can't read or edit its own rules.

- **`.nono/<tool>.extra.json`** — revoke a grant the agent picked up from a [post-session save-profile prompt](#post-session-save-profile-prompts). Remove the path from the relevant array and it's back to denied on the next run. The arrays differ in what they grant:

  - `allow` — read **and** write access.
  - `read` — read-only access.
  - `write` — write-only access (for directories, this doesn't include deletion).

  All three win over a conflicting `.nono_ignore` deny for the same path — which array a given path landed in just depends on what nono's save-profile prompt (or you, editing this file by hand) put it in.

  ```jsonc
  {
    "deny": [],
    "allow": ["/some/path/the/agent/was/granted"],
    "read": [],
    "write": []
  }
  ```

Everything else under `.nono/` is generated and disposable — `leash` rebuilds it as needed and adds `.nono/` to your project's `.gitignore` automatically.

## How it works

On each run, `leash` builds a per-project nono profile at `.nono/<tool>.profile.json` — extending the `<tool>` base profile, with `.nono_ignore` compiled into `filesystem.deny` and `.nono/<tool>.extra.json` merged in for anything else. It then runs `<tool>` through `nono run` using that profile. The profile is only rebuilt when `.nono_ignore` or `.nono/<tool>.extra.json` changes.

### Post-session save-profile prompts

nono's own save-profile prompt (shown after a session, for paths the agent tried to access) writes its answers to nono's global config, not to this project's profile. `leash` pulls those choices back in after each run:

- Denied paths under the project are appended to `.nono_ignore`.
- Everything else (allow/read/write grants, or paths outside the project) goes into `.nono/<tool>.extra.json` instead, since `.nono_ignore` can only express denials scoped to the project.

Both are folded into `.nono/<tool>.profile.json` on the next rebuild, so choices made at the prompt actually stick — and to walk one back later, edit `.nono/<tool>.extra.json` as described above.
