# {{MARKETPLACE_NAME}}

{{MARKETPLACE_SUBTITLE}}

## Installation

Add the marketplace to Claude Code:

```
/plugin marketplace add {{GITHUB_REPO}}
```

Install a specific plugin:

```
/plugin install <plugin-name>@{{MARKETPLACE_NAME}}
```

## Development

Run the linter to validate plugin structure:

```bash
make lint
```

Update documentation:

> **Deprecated in skillsaw 0.20.0:** `make docs` uses `skillsaw docs`, which
> will be removed in an upcoming release.

```bash
make docs
```

## Documentation

Visit the [documentation site](https://{{GITHUB_PAGES_URL}}) for more information.

## License

MIT
