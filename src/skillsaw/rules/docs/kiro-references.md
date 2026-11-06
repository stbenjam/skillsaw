# kiro-references

Check literal relative file references in repository-authored Kiro configuration.
This rule is opt-in and reports missing targets as warnings.

## How to fix

Resolve a JSON agent's `file://` prompt from the directory containing its config.
Resolve `file://` resources and steering file/folder references from the workspace
root containing `.kiro`. This resource check assumes execution at that root.

Correct the path or add the missing file. Exclude intentionally unavailable
resources through the rule's normal file exclusions. Absolute/global paths,
interpolation, resource globs, knowledge bases, and `skill://` are left unresolved.
Steering line-range suffixes do not change the file existence check.

Markdown links use `content-broken-internal-reference`. See the
[Kiro support boundaries](../kiro.md) for version and runtime limits.
