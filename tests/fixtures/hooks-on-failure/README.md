# Command policy gate

This plugin checks each Bash command against a local script and a policy
service before it runs. If either check fails to run, the command is blocked
instead of going ahead. Edits are recorded after they happen; a failed
recording never blocks the edit.

`onFailure` requires Claude Code 2.1.295 or later.
