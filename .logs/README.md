## Audit logs

### Why?
Running nono with a net profiler prints out lots of information while it's actively blocking network connections. This output disturbs the agent experience (i.e. is printed during the agents session). Even though this does not interfer with the agents workflow, it is unpleasant and confusing to us (the user of the agent). I decided to traffic the consoled output to these log files to keep the agent flow clean. It also doubles nicely in keeping this information for future reference if needed.

### What is logged
This folder contains logs of your agents' sessions while working with `leash`, one file per session. This information contains
* the profile loaded and the command run
* the sandbox backend in use (e.g. macOS Seatbelt)
* paths nono added or relaxed (e.g. the project dir)
* every host the agent tried to reach, and whether it was allowed or denied (not with `--with-net`)
* the network proxy's start and shutdown
* warnings from nono

### What is not logged

* file access attempts, allowed or denied
* the contents of any file the agent read or wrote
* your conversation with the agent: prompts, replies, and anything shown in its terminal
* the contents of network requests and responses (only the host name is logged)
* any network activity at all in sessions run with `--with-net`

### Where these logs go
The logs stay on your machine, in this folder, so you can review a session after it ends. leash doesn't show them to the agent, doesn't send them anywhere, and doesn't use them for anything else.

At the start of each session, leash deletes logs older than `LOG_RETENTION` days (set in `config.toml`, 14 by default). Set it to `0` to turn logging off: leash then writes no log file and discards nono's log output.

