# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`leash` is a single Python script (`leash`, no extension, `#!/usr/bin/env python3` shebang) that runs a coding agent (`claude`, `codex`, ...) sandboxed with [nono](https://nono.sh), scoped to the current git repository. There is no build step, no package manager, no test suite — the entire project is `./leash` plus generated state under `.leash/`. JSON is handled with the standard library's `json` module, so `jq` is not a dependency.

## Development

- Edit `leash` directly; it's the only source file.
- Sanity-check changes by running it against a scratch git repo: `./leash claude` (or any tool present on PATH with a matching nono profile).
- Syntax-check with `python3 -m py_compile leash`.
- `leash install` symlinks the script to `~/.local/bin/leash` — test install changes by running `./leash install` and confirming the symlink target with `readlink ~/.local/bin/leash`.

## Architecture

Everything happens in one linear script (`leash`):

1. **Arg dispatch** (`main`) — first arg is the tool name (`claude`, `codex`, ...) or the special `install` subcommand. `install` symlinks the script itself into `~/.local/bin` and exits early, before any of the git/nono checks below run.
2. **Preconditions** — requires `nono`, `git`, and the target tool to be on PATH (`require_cmd`); requires being run from the root of a git repository (not a subdirectory) since `.leash_deny` resolution depends on repo-relative paths.
3. **Profile generation** (`build_profile`) — turns `.leash_deny` (gitignore syntax) into a per-project, per-tool nono profile at `.leash/<tool>.profile.json`, which `extends` the tool's base nono profile. It merges two inputs: `.leash_deny` → `filesystem.deny`, and `.leash/<tool>.extra.json` (see step 5) → `filesystem.deny/allow/read/write`. `allow`/`read`/`write` entries win over a conflicting `.leash_deny` deny for the same path (set subtraction), so a path explicitly allowed via the save-profile flow isn't left denied. `.leash_deny` itself and the `.leash/` state dir are always denied so the sandboxed agent can't read or edit its own rules. `build_profile` also appends `.leash/` to the project's `.gitignore` (creating it if needed, via `ensure_gitignore_has_state_dir`) — this state dir is never meant to be committed.
   - `compute_deny_paths` shells out to `git ls-files --ignored --exclude-from=.leash_deny --directory` to get git's own gitignore-pattern matching (negation, `**`, anchoring) instead of reimplementing it.
   - Profile rebuild is skipped unless the combined sha256 of `.leash_deny` and `.leash/<tool>.extra.json` (cached in `.leash/<tool>.ignore.sha256`) has changed (`needs_rebuild`), so unrelated runs stay cheap.
4. **Execution** — `nono run --allow-cwd --profile <generated profile> --workdir <repo root> -- <tool> <args...>`, run in the foreground (via `subprocess.run`, not `exec`'d) so the script regains control afterward; the exit status is captured and re-raised at the very end, after step 5 runs.
5. **Absorbing nono's save-profile prompt** (`absorb_session_grants`) — nono's own post-session prompt (paths the agent tried to access) writes its answers to nono's *global* config keyed by a profile name — either a not-yet-applied draft (`~/.config/nono/profile-drafts/<name>.json`) or, once confirmed, a promoted user profile (`~/.config/nono/profiles/<name>.json`) — never back into this project's generated profile, so left alone those choices are silently discarded every run. `<name>` is **not reliably** the leash-generated profile name (`p.profile_name` / `leash-<tool>-<project slug>`): nono attributes a given deny rule's save-prompt to whichever profile in the extends chain actually owns that rule, so a denial coming from `<tool>`'s own base/pack profile (its default deny groups, e.g. credentials) gets saved under the plain tool name instead. `absorb_session_grants` therefore checks both names, in both locations, after each session (`absorb_from`), and folds matches back in: `$WORKDIR`-relative denies become `.leash_deny` lines; everything else (allow/read/write, or paths outside the project) goes to `.leash/<tool>.extra.json` via `append_extra`, since `.leash_deny` can only express project-scoped denials. It then strips any `.leash_deny` lines now covered by an allow/read/write grant (`strip_ignore_lines_covered_by_extra`), **deletes** the consumed draft or promoted file (its content now lives in the project, so leaving the global copy around would just get it silently re-absorbed every run), and calls `build_profile` immediately so the change takes effect without waiting for the next invocation.

All shell-outs (`git`, `nono`) go through `run_cmd(cmd: str, **kwargs)`, which takes a normal-looking bash command string and splits it with `shlex.split` before handing the argv to `subprocess.run` — no shell is ever invoked. Any variable dropped into one of these command strings (a path, the tool name, a user-supplied arg) is wrapped in `q()` (`shlex.quote`) first, so values containing spaces or shell metacharacters round-trip correctly.

Key invariant: `.leash/<tool>.profile.json` (and the schema/hash files alongside it) are local, disposable state (`.leash/` is auto-gitignored, see step 3) — never hand-edit them or treat them as source of truth; they're regenerated from `.leash_deny` and `.leash/<tool>.extra.json`. `.leash_deny` is the human-owned source of truth; `.leash/<tool>.extra.json` is leash-owned generated state (written only by `append_extra`) for grants `.leash_deny` can't express — it's still meant to be hand-edited when revoking a previously-absorbed grant (remove the path from its array), just not treated as authoritative the way `.leash_deny` is.
