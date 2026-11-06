# Pi 1.5.0 settings schema

`settings.schema.json` is copied byte-for-byte from tag
[`v1.5.0`](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/schemas/settings.schema.json)
(commit `f9a26365568127461c47a07a37dcb42c140a3ac5`) of the Pi repository.
Pi publishes the same schema at `https://pi.dev/schemas/settings.schema.json`.
The schema and source repository are licensed under MIT; the upstream
copyright and permission notice is bundled beside the schema as `LICENSE`.

Pi generates the schema from its settings types. The tagged copy is bundled
because it matches the 1.5.0 loader; on 2026-11-06 the pi.dev URL still served
the 1.4.0 build, which lacks `extensionChangelogVersions`. Linting never
downloads a schema.
