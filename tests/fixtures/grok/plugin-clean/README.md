# tide-charts

Turn NOAA tide predictions into shoreline survey windows, without leaving
the session.

## Install

```
grok plugin install tide-charts --trust
```

## What it adds

| Surface | Name | Purpose |
|---|---|---|
| Skill | `tide-window` | Find low-tide windows long enough to survey |
| MCP server | `tides` | NOAA predictions for one station and date range |

The MCP server is read-only and needs no credentials. Station ids come from
the NOAA CO-OPS station list.
