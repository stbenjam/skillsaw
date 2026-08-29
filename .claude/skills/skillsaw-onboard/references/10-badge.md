# Add a README badge

Run `skillsaw badge`. It writes `.skillsaw-badge.json` and prints two Markdown
variants. Add the endpoint badge to the README's existing badge group, or
directly below the top-level heading when no group exists. Keep its link to
`https://skillsaw.org/`.

If the command prints a URL placeholder because no GitHub remote was detected,
retain it for the user to fill once `.skillsaw-badge.json` is published.

When Makefile targets were added, make `lint` depend on badge regeneration:

```makefile
.PHONY: badge
badge:
	uvx skillsaw==$(SKILLSAW_VERSION) badge

lint: badge
	uvx skillsaw==$(SKILLSAW_VERSION) --strict
```

Use the selected container command instead when targets use a container.
Explain that the badge reflects the committed artifact, ignores baselines,
and must be regenerated after context changes. Record the changed files, then
return to the router.
