# Install skillsaw

Run `skillsaw --version`. If it works, retain that command prefix.

Otherwise choose the first available approach and retain its command prefix
for later steps:

1. Prefer zero-install execution with `uvx skillsaw`.
2. If uvx is unavailable, install with `pip install skillsaw` and use
   `skillsaw`.
3. Otherwise use the installed container runtime (`podman` or `docker`):

   ```console
   podman pull ghcr.io/stbenjam/skillsaw:latest
   podman run -v $(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw
   ```

   Mount the repository at `/workspace`; `:Z` provides the SELinux relabel.
   Append later subcommands after the image name.

Verify the chosen command with `--version`, then return to the router.
