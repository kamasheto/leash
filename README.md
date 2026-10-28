![leash](https://sakr.me/post-heroes/leash.png)

# leash

Keep your agent on leash.

```sh
cd my-project
leash claude
```

leash runs `claude`, `codex` and friends inside a [nono](https://nono.sh) sandbox fenced to the project you're in. The agent gets the whole project to work with. It doesn't get your `.env`, your keys, your git history (by default), or anything else you list in `.leash`.

## Install

You'll need Python 3.11+ and git. Then:

```sh
curl -fsSL https://kamasheto.dev/install-leash | bash
```

The [installer](install.sh) asks before each change it makes:

1. Clones leash into `~/.local/share/leash`, or updates the clone if it's already there.
2. Installs nono (via brew) and its `claude`/`codex` profiles if they're missing.
3. Symlinks `~/.local/bin/leash`.
4. Adds `~/.local/bin` to your `PATH` if it isn't already there. It edits the startup file of your login shell, plus any other shell you've already set up: `~/.zshrc`, `~/.bashrc` (`~/.bash_profile` on macOS), or `~/.config/fish/conf.d/leash.fish`. Files that already mention `~/.local/bin` are left alone.

To update or remove it later (each also asks before every step):

```sh
leash update      # leash, nono (via brew) and nono's profiles
leash uninstall   # nono (via brew) and leash; the PATH line stays
```

### Manual install

If you'd rather not pipe a script into bash, do the same steps by hand:

```sh
git clone https://github.com/kamasheto/leash.git ~/.local/share/leash
~/.local/share/leash/cli install
```

Use `git clone` rather than copying the script on its own. leash relies on its own checkout (git engine) to match `.leash` patterns.

## Usage

Run it from your project root:

```sh
leash claude
leash codex
leash claude -p "fix the failing test"   # arguments go straight to the tool
leash --with-git claude                  # let the agent use git this session
leash --with-net claude                  # let the agent reach any host this session
```

leash's own flags go before the tool name. Everything after it is passed through to the tool untouched.

| Option | What it does |
| --- | --- |
| `--with-git` | Lets the agent run `git` and read `.git/` for this session. Off by default, see [below](#keeping-things-out-leash) for why. |
| `--with-net` | Lifts the network filter for this session, so the agent can reach any host. Off by default, see [below](#network-access). |
| `--verbose` | For `install`, `update` and `uninstall`: show the output of the commands they run. |
| `-h`, `--help` | Show usage |

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

## Network access

By default the agent can only reach the LLM APIs it needs to work (api.anthropic.com, api.openai.com and the like), through nono's filtering proxy with its built-in `minimal` network profile. Every other host is blocked, so the agent can't send your code anywhere else or fetch things from the internet. That includes package registries and GitHub, so `npm install`, `pip install` and the like fail inside the sandbox.

Pass `--with-net` to lift the filter for a session. The agent can then reach any host and send it anything it can read.

## nono's save prompt

When a session ends, nono may ask whether to remember access to paths the agent tried to use. nono normally saves those answers to its own global config, where they'd never apply to this project. leash moves them into the project instead: denials inside the project are appended to `.leash`, and everything else goes into `.leash-agents/<tool>.extra.json`.

To revoke something you granted, remove it from `extra.json`. It'll be blocked again on the next run.

Everything else under `.leash-agents/` is generated and safe to delete. leash adds the directory to your `.gitignore` for you.

## Configuration

`config.toml` contains configuration options. Changing anything there rebuilds each project's profile on its next run.

| Option | Default | What it does |
|---|---|---|
| `LOG_RETENTION` | `14` | How many days session logs in `.logs/` are kept. Older ones are deleted at the start of each session. `0` turns logging off and deletes every stored log. |
| `STATE_DIR` | `".leash-agents"` | Name of the per-project folder where leash keeps generated profiles and absorbed grants (`<tool>.extra.json`). It's added to the project's `.gitignore` and the agent can't read it. Renaming it doesn't move an existing folder. |
| `IGNORE_FILE` | `".leash"` | Name of the per-project file with deny rules (gitignore syntax). The agent can't read it. Renaming it doesn't rename existing files, so their rules stop applying. |
| `NET_PROFILE` | `"minimal"` | nono network profile used unless you pass `--with-net`. `minimal` lets the agent reach only the LLM APIs (api.anthropic.com, api.openai.com, ...) and blocks every other host. [Preset Network Profiles](https://nono.sh/docs/cli/features/networking#preset-network-profiles) |

## Contributing

Issues and PRs are welcome. leash is stdlib-only Python, `leash.py` plus its settings in `config.toml`, and I'd like to keep it that way: no third-party packages, and no external tools beyond nono and git.

Run the tests with [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest                        # everything
uv run pytest -m "not integration"   # skip the ones that need nono
```

CI doesn't have nono, so run the integration tests locally if your change affects what the sandbox allows. Anything that loosens the always-denied rules should be opt-in, like `--with-git` and `--with-net`.

See [AGENTS.md](AGENTS.md) for how the code is laid out.

## License

[MIT](LICENSE) © Mahmoud Sakr
