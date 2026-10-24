![leash](https://sakr.me/post-heroes/leash.png)

# leash

leash runs a coding agent like `claude` or `codex` inside a [nono](https://nono.sh) sandbox that's scoped to the directory you're in.

```sh
cd my-project
leash claude
```

The agent can work on the project as usual, but it can't touch anything you've listed in `.leash`.

## Install

You'll need Python 3.11+ and git. Then:

```sh
git clone git@github.com:kamasheto/leash.git
./leash/cli install
```

This installs nono (via brew) and its `claude`/`codex` profiles if they're missing (it asks first), then symlinks `~/.local/bin/leash`. Make sure `~/.local/bin` is on your `PATH`.

Use `git clone` rather than copying the script on its own. leash relies on its own checkout to match `.leash` patterns.

## Usage

Run it from your project root:

```sh
leash claude
leash codex
leash claude -p "fix the failing test"   # arguments go straight to the tool
leash --with-git claude                  # let the agent use git this session
```

leash's own flags go before the tool name. Everything after it is passed through to the tool untouched.

## Keeping things out: `.leash`

`.leash` sits in your project root and uses `.gitignore` syntax. leash creates an empty one on first run.

```gitignore
.env
secrets/
*.pem
```

Commit it, so everyone working on the project gets the same rules.

A few things are always off limits, whatever `.leash` says:

- `.leash` and `.leash-agents/`, so the agent can't rewrite its own rules.
- `.git/` and the `git` command. Anything that was ever committed can be read back out of history (think `git show HEAD:.env`), and a writable `.git` lets the agent plant hooks that later run outside the sandbox.

So by default the agent has no git access. You do the commits yourself. If you'd rather let it run git for a session, pass `--with-git`, but know that it reopens both of those holes.

## nono's save prompt

When a session ends, nono may ask whether to remember access to paths the agent tried to use. nono normally saves those answers to its own global config, where they'd never apply to this project. leash moves them into the project instead: denials inside the project are appended to `.leash`, and everything else goes into `.leash-agents/<tool>.extra.json`.

To revoke something you granted, remove it from `extra.json`. It'll be blocked again on the next run.

Everything else under `.leash-agents/` is generated and safe to delete. leash adds the directory to your `.gitignore` for you.

## Contributing

Issues and PRs are welcome. The whole thing is one stdlib-only Python file, `leash.py`, and I'd like to keep it that way: no third-party packages, and no external tools beyond nono and git.

Run the tests with [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest                        # everything
uv run pytest -m "not integration"   # skip the ones that need nono
```

CI doesn't have nono, so run the integration tests locally if your change affects what the sandbox allows. Anything that loosens the always-denied rules should be opt-in, like `--with-git`.

See [AGENTS.md](AGENTS.md) for how the code is laid out.

## License

[MIT](LICENSE) © Mahmoud Sakr
