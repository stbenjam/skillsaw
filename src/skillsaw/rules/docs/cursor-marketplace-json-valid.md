## Why

Cursor discovers multi-plugin repositories through
`.cursor-plugin/marketplace.json`. This rule validates catalog metadata,
entry shapes, unique plugin names, and local sources. A local source must
resolve to a directory within its marketplace root, including when
`metadata.pluginRoot` prefixes the source. A source that already starts
with `pluginRoot`, with or without a leading `./`, is not prefixed twice,
and a root-relative source is accepted when only it names a directory.

String and object sources with a `path` are supported. Remote URLs are
validated as metadata without fetching or executing their contents. Entries
can supply component declarations without a separate plugin manifest.

## How to fix

Correct the field or local source named in the finding. Give each entry a
unique name and keep local source paths inside the marketplace. Entries
whose source names no directory are reported together, once per
marketplace. Findings are file-level and have no automatic fix.

See the [Cursor marketplace reference](https://cursor.com/docs/reference/plugins).
