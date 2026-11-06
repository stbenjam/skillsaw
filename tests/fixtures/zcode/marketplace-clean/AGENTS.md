# Harbor Tools

This repository is a ZCode plugin marketplace. Each plugin lives in its own
directory under `plugins/` with a `.zcode-plugin/plugin.json` manifest.

## Conventions

- Keep plugin names lowercase and match each manifest `name` to its
  `marketplace.json` entry.
- Run `npm test` before opening a pull request.
