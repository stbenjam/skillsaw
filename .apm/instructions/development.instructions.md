---
description: You must follow these instructions when developing skillsaw. 
---

Follow these rules when developing skillsaw, a configurable, rule-based linter for agentic contextual building blocks.

## Pre-push Checklist

<!-- skillsaw-disable-next-line content-hook-candidate -->
CRITICAL: You MUST always run these steps before pushing changes.

1. Ensure branch is up to date with UPSTREAM (stbenjam/skillsaw) — check git
   remotes then merge upstream's main.
2. Run `make test` — run the full test suite and ensure all tests pass. Never
   assume a problem is pre-existing; follow the boyscout rule and fix it anyway.
3. Run `make lint` — check formatting (or run `make format` to fix it).
4. Run `make update` — regenerate all generated files (must come after version bump).
5. Test against `openshift-eng/ai-helpers`: clone it, run `skillsaw`, and ensure exit 0.

## Pre-PR Checklist

Follow these checks before opening a PR:

- Check whether documentation is up to date for the changes on this branch.
    - Example: you add a new feature, flag, or lint type.
      Action: update `README.md` to include this.
    - Example: you encounter a problem during development you must keep for later.
      Action: update `.apm/instructions` and run `make update`.
- Verify test coverage on a new feature, flag, lint type or bug fix is complete.
    - Bug fixes must include regression protection.
    - New features, linters, and rules need integration test coverage WITH fixtures (see testing rules).

## Authoring Agentic Context

When you create or edit a skill, slash command, agent, hook, or instruction
file in this repo, load the `skillsaw-lint` skill and follow it: lint the
file with `.venv/bin/skillsaw lint <path>`, apply fixes, and re-lint until
clean before you finish. We ship the linter — our own context must pass it.

## Post-PR Checklist

After opening a PR, keep monitoring for feedback from CodeRabbit, Gemini,
and stbenjam. You may stop monitoring 20 minutes after you push a PR.
Review and handle valid feedback that comes in.

## Performance

Benchmark lint speed with the harness in `benchmarks/` (`make
benchmark`, `make profile`, `make benchmark-save` / `make benchmark-compare`
for regression checks — review `DEVELOPMENT.md`). When touching content rules,
the lint tree, or `utils.py` read paths, save a baseline on main and compare on your branch.

- **Avoid scanning every line against every regex pattern.**
  Run `patterns_matching_anywhere(body, patterns)` from `content_analysis`
  first to filter down to patterns that actually match the text, then scan
  line-by-line only with surviving patterns.
- **`lint_tree.find(NodeType)` is memoized per node** — keep it valid: anything
  that mutates tree structure outside a rebuild must call `invalidate_find_cache()`
  (see `FrontmatteredBlock.write_frontmatter_text`).
- **Read top-level frontmatter key lines from `frontmatter_key_line()`**,
  which uses a libyaml-backed line map with a ruamel fallback. Don't add
  per-key ruamel parses. Avoid ruamel round-trip parsing — it is ~30x slower and was the dominant cost of lint-tree construction.
- Keep per-blob work (whole-body `.lower()`, config-file stats) outside
  the per-block loop — run it once per `check()`.
- **Use fast string checks before running heavy regexes.** Simple checks
  like `str.isascii()`, `str.translate()`, or `"/" in text` quickly filter
  out clean text so regexes only run when necessary.
- **Use `paths.relative_to_str()` for repo-relative paths.**
  On Python 3.12+, `PurePath.relative_to` and `path.parents` allocate new
  `Path` objects for every ancestor, which adds significant overhead in large repos.
- **Load YAML with `yaml.load(..., Loader=_SAFE_LOADER)` from `utils.py`**
  instead of bare `yaml.safe_load` — `_SAFE_LOADER` uses the fast C-based
  LibYAML loader when available (~10x faster) while maintaining safe loading behavior.
- **`Linter.run()` / `fix()` pause Python's cyclic garbage collector**
  during rule execution to avoid expensive GC pauses across millions of
  objects. Rules should avoid circular references so temporary data is
  freed immediately via reference counting.

## Markdown: AST for reading, splice for writing

Read markdown structure (links, code spans, fences, HTML comments, headings)
from the markdown-it-py AST — read it via `block.markdown` (a
`skillsaw.markdown_doc.MarkdownDoc`). Never hand-roll per-line regexes for markdown structure.

- **Detection**: use the `MarkdownDoc` accessors — `links()`, `code_spans()`,
  `text_segments()`, `fences()`, `headings()`, `html_comments()`,
  `prose_lines()`. Scanning rules needing only prose read it automatically through `read_body(strip_code_blocks=True)`.
- **Fixes**: splice at the token spans the check matched using
  `markdown_doc.splice(content, edits)` — never re-locate fix targets with
  `line.find()` / `str.replace()` — avoid them; they corrupt substrings of other tokens.
- **Never render the AST back to markdown** — round-trip rendering reformats whole files and violates the scope-the-fix autofix rule.
- Use `markdown_doc.file_span()` to translate body-relative columns to file columns before splicing (YAML-embedded bodies are indented in the file);
  skip the edit — return early — when `file_span()` yields `None`.

## New Linter Rules

- **Make rules configurable when there are tuneable settings.**
- **Read declared options with `self.setting()`** so overrides, schema
  defaults, and explicit nulls follow one contract. Declare every literal
  config key the rule reads; `tests/test_rule_registry.py` enforces this for
  builtin rule class bodies.
- **Never break existing rules for users of skillsaw.**
- **Rules register themselves** — never hand-maintain import lists or config
  dicts. skillsaw auto-discovers any concrete `Rule` subclass under
  `src/skillsaw/rules/builtin/`. Keep defaults on the class: `default_enabled`
  and `default_severity()` define the single source of truth, and
  `LinterConfig.default()` is generated from them.
- **New rules default to `enabled: auto` or `enabled: false`**. Set
  `default_enabled = False` for opt-in; the base class default is `"auto"`.
  Never force-enable a new rule that could break existing users.
- **Use the lint tree for discovery** — call `context.lint_tree.find(NodeType)`.

### A rule earns its default

`enabled: auto` is a claim that the rule is useful on a typical repository of
its type. Prove it on real repositories before the rule ships, not on
fixtures. The 0.20.0 audit answered three questions for every rule; answer
them for yours:

1. **Does it affect common usage?** A finding the author will act on, on
   content a typical repository contains. A rule for a rare shape is opt-in
   (`default_enabled = False`). A rare false positive in prose can be
   silenced with a `skillsaw-disable` directive; JSON has no inline disable,
   so a false positive from a JSON rule costs the user a config change or a
   baseline — hold those rules to a higher bar.
2. **Is it correct?** Clone ten or more real repositories that carry the
   file type, run the rule, and read the findings. Verify every contested
   check against the tool the rule validates — its CLI, schema, or loader,
   not your memory of its docs. A check stricter than the tool is a
   false-positive generator. A default-enabled rule ships with a measured
   false-positive rate under about 10% on real content; an ERROR ships with
   none anyone can name. Every release-readiness pass has found the same
   thing: the rule was stricter than the tool.
3. **Is it annoying?** A rule that fires on most working repositories, or
   hundreds of times per repository, is noise whatever its precision. Measure
   first-run volume on the corpus; a rule that would land in the top five by
   count needs aggregation or a higher default threshold first.

Severity follows consequence. ERROR when the tool refuses the file or the
finding is a security or supply-chain risk. WARNING when the content works
but is measurably worse. INFO for advice. A validator whose green means "the
tool will not start" is worse than no validator. Never hardcode `severity=`
on the finding that is the rule's main contract: the configured severity
must apply, or `severity:` in `.skillsaw.yaml` and `skillsaw init` both lie.

One defect, one finding. A list holding the wrong values is one finding
naming them, not one finding per item. A directory full of the same problem
collapses to one finding per directory. Fixed-shape files that a tool
generates are documentation, not defects — `ghp_xxxx…`, `${VERSION}`,
`$version`, `__VERSION__`, the jwt.io example token — so learn the
placeholder spellings real repositories commit before shipping a detector.

The message names the consequence and the fix. It never asserts a reason the
rule did not verify (a prefix "depends on the reader's server name" when the
repository declares that server), and it points at the rule's own option
before anything suggests a disable. Prefer a configuration knob — exclusion,
threshold, allowlist, group — over `enabled: false`; config is the only
lever, and a knob keeps the rule's other findings.

A heuristic keyed on where a file lives rather than what it does — a script
under a dotfile directory, a filename mentioned in prose — detects a filing
convention, not a defect, and is evaded by anything that does not follow the
convention. Delete it rather than qualify it.

### Line numbers and the parse tree

- **Always report line numbers** on every violation traceable to a specific line, except whole-file violations.
- **Use `read_yaml_commented()`** (from `utils.py`) for YAML — never use
  `yaml.safe_load()` or `read_yaml()`. Keep line numbers via the ruamel.yaml
  objects `read_yaml_commented()` returns.
- **Use `commented_key_line(node, key)` / `commented_item_line(node, index)`** to extract 1-based line numbers from ruamel data structures.
- **Never fabricate line numbers** — if a field is missing, omit the line.
- **Declare `repo_types`** to control when `enabled: auto` fires.
- **Declare `config_schema`** when the rule accepts parameters.
- **Always keep EVERYTHING part of the parse tree.**
- **Keep the prose/config split in the block hierarchy** — `ContentBlock`
  subclasses are prose for an agent's context window and get every
  content-quality rule automatically. Make structured config files (settings,
  hooks, MCP JSON) subclass `JsonConfigBlock` instead; dedicated rules find
  them with `find(SettingsBlock)`. Never add a config file type under
  `ContentBlock` — content rules would then lint its JSON as instruction text.
- **Structured YAML config gets a direct `LintTarget` subclass, never
  `ContentBlock`** — `OpenAIMetadataBlock` is the pattern. It is deliberately
  neither `ContentBlock` (content rules would lint its YAML as instruction
  text) nor `JsonConfigBlock` (that hierarchy is JSON-specific and file-level;
  YAML keeps line numbers via `read_yaml_commented()`).

Never require line numbers for JSON files — the `json` module does not
preserve them. Keep JSON rules at file-level reporting.

## Autofix invariants

- **Avoid negative lookarounds around backtrackable quantifiers** in patterns
  that feed autofixes. A trailing `(?!\))` after `\.\w{1,10}` never rejects the
  match — the engine backtracks into a *truncated* match and the fix splices a
  corrupted span (issue #321). Match greedily, then check the characters
  adjacent to the full match in code and reject there.
- **Fixes that add a frontmatter field must guard against the key already
  existing** — `check()` may report "missing" for an empty/null value while
  the `key:` line is still present. Use `replace_frontmatter_field()` first
  and fall back to `prepend_frontmatter_fields()`, or the fix prepends a
  duplicate key on every run and never converges (issue #321).
- **Add new SAFE-autofix edge cases** to the `tests/fixtures/autofix/safe-idempotency`
  fixture so `TestSafeAutofixIdempotency` guards them; update `EXPECTED_SAFE_VIOLATIONS` when the fixture grows.
- **Autofix stands down entirely for plugins installed under `.codex/plugins/`**
  — vendor-managed content is diagnostic-only, so every rule's `fix()` silently
  no-ops there, by design. A new rule's fix needs no guard of its own for that
  case, and a "fix didn't apply" report from such a path is expected behavior,
  not a bug.

## Ecosystem provenance

"Which ecosystem owns this plugin directory" is decided in exactly one
place: `RepositoryContext.provenance()`, which returns a cached
`PluginProvenance` record per directory. It lives on
`RepositoryProvenanceMixin` in `repository_provenance.py`, alongside
`in_format_scope`, `is_codex_only_plugin`, and the containment helpers;
`RepositoryContext` mixes that in, so every caller still reaches it as
`RepositoryContext.provenance()`. Never answer an ownership
question with a fresh filesystem probe in a rule or in the tree builder —
two call sites probing independently is how a directory falls between
per-ecosystem attach paths and loses its content silently.

- **Discovery is state-free and lives in `src/skillsaw/discovery/`**
  (`claude.py`, `codex.py`, `agent_plugins.py`, `detect.py`, and
  `excludes.py`): functions take
  a root path and callbacks and return data, holding no caches and importing
  nothing from `context`.
  `RepositoryContext` is the stateful orchestrator — its methods wrap
  the discovery functions with the per-context caches and render the
  provenance verdicts over the evidence they gather.
- **Evidence is filesystem-first and `--type`-invariant.** An override
  changes what discovery walks, not what the author declared, so
  provenance reads markers, contained manifests, and catalog files
  directly (`_codex_catalog_files()`), never discovery output.
- **The lint tree builds plugins in ONE pass** over the union of claimed
  directories. Each directory gets one container; prose (`commands/`,
  `agents/`, `rules/`, README) attaches once with containment; config
  files attach per claiming ecosystem through the contained helpers.
  Never add a second per-ecosystem plugin loop.
- **Format rules gate on provenance declaratively, never with inline
  guards.** A rule that enforces one ecosystem's conventions declares
  `provenance_scope = "claude"` on its class and iterates targets
  through `self.scoped_find(context, NodeType)`; the filtering happens
  in exactly one place (`RepositoryContext.in_format_scope`, reading
  each node's `provenance_dir()`), so a Codex-only directory is exempt
  while dual-manifest and unclaimed directories keep every check.
  `TestProvenanceScopeMechanism` pins which rules declare the scope.
  The mechanism fails open by node type: `LintTarget.provenance_dir()`
  returns `None` unless the node type overrides it. Grep
  `def provenance_dir` for the current set — today `PluginNode`,
  `AgentPluginNode`, and `AgentPluginConfigNode` in `lint_target.py`,
  plus `CommandBlock` and `AgentBlock` in the frontmatter blocks
  module. A scope-declaring rule iterating a node type without the
  override silently gets no filtering, so add the override first.
- **`provenance_scope` is for rules iterating SHARED node types.** A
  rule reading `CommandBlock` or `PluginNode` — types every ecosystem
  populates — needs the declaration to stay out of another ecosystem's
  directories. A rule iterating an ecosystem-exclusive node type
  (`AgentPluginConfigNode`, `CodexPluginConfigNode`) is already scoped
  by its target, and declaring `provenance_scope` there is a bug: under
  a forced `--type` with no filesystem claim the scope filter skips the
  node, so the rule never reports a missing or malformed manifest. That
  is why `agent-plugin-json-valid` and `agent-plugin-mcp-valid` use
  plain `find(AgentPluginConfigNode)`.
- **Conditional strictness is not a skip.** The ecosystem-tightened
  checks (hooks/MCP shapes) stay `provenance_scope = None` and gate the
  tightened checks alone on `context.in_codex_only_plugin(path)` — the
  one spelling of "does a Codex-exclusive plugin own this file" — so
  dual-manifest plugins keep their established Claude results
  (`TestDualManifestBackwardCompat` pins this).

**Ecosystems and editor tools are different problems.** An *ecosystem*
packages and installs content (Claude plugins, Codex, Agent Plugins), so it
needs provenance: two of them can claim the same directory, and the format
rules must stay out of each other's trees. An *editor tool* (Cursor,
Copilot, Cline, Qwen) reads its own configuration locations, which no other
tool claims — nothing else installs into `.cursor/`, and `QWEN.md` belongs
to one reader — so it needs no provenance machinery at all. Pick
the recipe that matches; following the ecosystem one for an editor tool
builds machinery that design does not need.

**Adding an editor tool** (Cursor is the worked example): add its directory
name to `AGENT_TOOL_DIR_NAMES` in the `detect.py` discovery module if it reads a
directory rather than a single root file, so one walk finds it anywhere in
the tree; add its skill directory to `CONVENTIONAL_SKILL_DIRS` in the
`discovery` package; add its evidence to `_EDITOR_EVIDENCE` (or a
`marker()` check) in `instruction_formats()` — **detection must agree with
attachment**, or the lint tree grows blocks no format-gated rule ever looks
at; add block classes whose `category` encodes the budget role (`command`
for on-demand prompts, `instruction` for always-on prose, `agent` for
subagents); attach them in the editor-directory loop in `build_lint_tree`.
Structural rules for the tool declare `formats = frozenset({HAS_<TOOL>})`
and iterate their own block type — never `provenance_scope`, which is for
shared node types only. Prefer subclassing a shared block
(`VsCodeMcpBlock(McpBlock)`) over editing existing rule files, so the
security rules pick the tool up without a visit.

Four more, from OpenCode (`formats/opencode.py`, `rules/builtin/opencode/`):
check `APM_COMPILED_DIR_TARGETS` for a tool whose directory is also a
compile target (`.opencode` is, resolved on APM's evidence alone); set
`jsonc: ClassVar[bool] = True` on a JSONC host's block, never a
Claude-family one; keep configuration vocabulary — key sets, alias tables —
in `formats/<tool>.py`, not restated in rules; and when a dialect diverges
enough that a shared rule's every check misfires, subclassing isn't
enough — defer to the tool's own, as `mcp-valid-json` does for Agent
Plugins and OpenCode. Two inline branches is deliberate; at a third, hoist
the condition to a ClassVar.

**Adding an ecosystem** (Codex and Agent Plugins are the worked examples):
put its discovery leg — the
state-free plugin/manifest walks, catalog enumeration, local-source
resolution, and install-location helpers — in a new
`src/skillsaw/discovery/<ecosystem>.py` beside the existing discovery modules;
add its evidence probe to `provenance()` in
`repository_provenance.py` and its
context wrappers (caching, `--type` gating) in `context.py` beside
`_codex_catalog_files()` / `_agent_plugin_claim_set()`; add its config-file
cluster to the single
plugin pass in `build_lint_tree` (attached through a contained helper);
teach `in_format_scope` nothing — it already reads the
provenance claim set, so every `provenance_scope`-declaring rule honors
the new claim the moment the evidence probe lands; give the new ecosystem's
format rules `provenance_scope = "<ecosystem>"` only where they iterate a
shared node type — rules that iterate the ecosystem's own node type gate by
node type instead (see the scope rule above);
extend the union in `merge_plugin_dirs` callers if it discovers plugin
directories of its own. Prose needs no work — every claimed directory
already gets it — and existing rule files need no visits: scope is
declared per rule class, not guarded per call site.
