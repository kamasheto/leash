![leash](https://sakr.me/post-heroes/leash.png)

# leash

Run a coding agent (`claude`, `codex`, ...) sandboxed with [nono](https://nono.sh), scoped to the current project.

## Requirements

- [nono](https://nono.sh) installed, with a base profile matching your tool name (e.g. `nono profile list` should show `claude` and/or `codex`)
- `git`
- Python 3

## Installation

<details>
  <summary>Install nono.sh if not already installed (click to expand)</summary>
  <blockquote>
    <sub>Latest instructions from https://nono.sh</sub>

```sh
# Install nono.sh
brew install nono

# If needed: install claude plugin
nono pull nolabs-ai/claude

# If needed: install codex plugin
nono pull nolabs-ai/codex

```
  </blockquote>

</details>

```sh
# clone 
git clone git@github.com:kamasheto/leash.git

# create a symlink from the leash cli
./leash/cli install

```

This symlinks `~/.local/bin/leash` to `leash/cli`. Make sure `~/.local/bin` is on your `PATH`.

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

- **`.leash`** — deny the agent access to specific files or directories. `.gitignore` syntax, lives in your project root, and is meant to be committed. `leash` creates it automatically on first run if it doesn't exist:

  ```
  .env
  secrets/
  *.pem
  ```

  `.leash` itself is always denied too, so the agent can't read or edit its own rules.

- **`.leash-agents/<tool>.extra.json`** — revoke a grant the agent picked up from a [post-session save-profile prompt](#post-session-save-profile-prompts). Remove the path from the relevant array and it's back to denied on the next run. The arrays differ in what they grant:

  - `allow` — read **and** write access.
  - `read` — read-only access.
  - `write` — write-only access (for directories, this doesn't include deletion).

  All three win over a conflicting `.leash` deny for the same path — which array a given path landed in just depends on what nono's save-profile prompt (or you, editing this file by hand) put it in.

  ```jsonc
  {
    "deny": [],
    "allow": ["/some/path/the/agent/was/granted"],
    "read": [],
    "write": []
  }
  ```

Everything else under `.leash-agents/` is generated and disposable — `leash` rebuilds it as needed and adds `.leash-agents/` to your project's `.gitignore` automatically.

## How it works

* On each run, `leash` builds a per-project nono profile at `.leash-agents/<tool>.profile.json` — extending the `<tool>` base profile, with `.leash` compiled into `filesystem.deny` and `.leash-agents/<tool>.extra.json` merged in for anything else. 
* It then runs `<tool>` through `nono run` using that profile. 
* The profile is only rebuilt when `.leash` or `.leash-agents/<tool>.extra.json` changes.

### Post-session save-profile prompts

nono's own save-profile prompt (shown after a session, for paths the agent tried to access) writes its answers to nono's global config, not to this project's profile. `leash` pulls those choices back in after each run:

- Denied paths under the project are appended to `.leash`.
- Everything else (allow/read/write grants, or paths outside the project) goes into `.leash-agents/<tool>.extra.json` instead, since `.leash` can only express denials scoped to the project.

Both are folded into `.leash-agents/<tool>.profile.json` on the next rebuild, so choices made at the prompt actually stick — and to walk one back later, edit `.leash-agents/<tool>.extra.json` as described above.
