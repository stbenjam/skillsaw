# harbour-plugins

The internal Grok Build marketplace for the harbour survey team.

## Add it

```
grok plugin marketplace add harbour-example/harbour-plugins
grok plugin install tide-charts --trust
```

`plugin-index.json` is generated in CI by `scripts/generate-plugin-index.py`
and is what the marketplace browser reads before anything is installed.
