# Plan: `skillsaw docs` — Repository Documentation Generator

## Context

Users of skillsaw-linted repos (plugin marketplaces, single plugins, agentskills, .claude directories) currently have no way to generate a browsable overview of what's in their repo. The `docs` command will scan the repository, extract metadata from all plugins/skills/commands/agents/hooks/MCP servers, and produce beautiful multi-page HTML documentation (or markdown).

## CLI Design

Add `docs` as an argparse subparser with `required=False`, so bare `skillsaw` continues to behave identically to today (lint mode). No backward-compat breakage.

```
skillsaw docs [path] [--format {html,markdown}] [--output-dir DIR] [--title TITLE]
```

- `path` — positional, defaults to cwd
- `--format` — `html` (default) or `markdown`
- `--output-dir` — output directory (default: `skillsaw-docs/`). For single-page repos writing to stdout, the user must pass `--output-dir` to get files instead
- `--title` — custom title (defaults to marketplace/plugin name or "Documentation")

**Ambiguity handling:** argparse subparsers naturally resolve `skillsaw docs` as the subcommand vs. `skillsaw ./docs` as a path. Since `docs` is a known subcommand name, it takes priority. Users who have a directory literally named `docs` can use `./docs`.

## Output Structure

| Repo Type | HTML Output | Markdown Output |
|-----------|------------|-----------------|
| MARKETPLACE | Multi-page: `index.html` + `{plugin}.html` per plugin | Multi-file: `index.md` + `{plugin}.md` |
| SINGLE_PLUGIN | Single `index.html` | Single file |
| DOT_CLAUDE | Single `index.html` | Single file |
| AGENTSKILLS | Single `index.html` | Single file |

Cross-links: marketplace index cards link to `{plugin-name}.html`; each plugin page has breadcrumb back to index.

## Module Structure

New subpackage `src/skillsaw/docs/`:

```
src/skillsaw/docs/
    __init__.py           # Public API: generate_docs()
    models.py             # Dataclasses: DocsOutput, PluginDoc, CommandDoc, SkillDoc, etc.
    extractor.py          # Walks RepositoryContext, parses files, returns DocsOutput
    html_renderer.py      # Generates self-contained HTML (single + multi-page)
    markdown_renderer.py  # Generates markdown
```

## Data Models (`models.py`)

Dataclasses for structured content extraction:

- `CommandDoc` — name, file_path, description (frontmatter), full_name, synopsis, body
- `SkillDoc` — name, dir_path, description, license, compatibility, metadata, allowed_tools, body
- `AgentDoc` — name, file_path, description, body
- `HookDoc` — event_type, matchers with hook configs
- `McpServerDoc` — name, server_type (stdio/http/sse), config dict, source_file
- `RuleFileDoc` — name, file_path, description (from frontmatter), globs
- `PluginDoc` — name, path, description, version, author, commands[], skills[], agents[], hooks[], mcp_servers[], has_readme
- `MarketplaceDoc` — name, owner, plugins[]
- `DocsOutput` — repo_type, title, marketplace (optional), plugins[], skills[] (standalone)

## Content Extraction (`extractor.py`)

Main entry: `extract_docs(context: RepositoryContext, title: str = None) -> DocsOutput`

For each plugin discovered by `context.plugins`:
1. Read plugin.json / marketplace metadata via `context.get_plugin_metadata()`
2. Scan `commands/*.md` — parse YAML frontmatter + extract `## Name`, `## Synopsis`, `## Description` sections
3. Scan `skills/*/SKILL.md` — parse YAML frontmatter (name, description, license, compatibility, metadata, allowed-tools)
4. Scan `agents/*.md` — parse YAML frontmatter (name, description)
5. Read `hooks/hooks.json` — group by event type
6. Read `.mcp.json` and/or `plugin.json` → `mcpServers` — extract server configs
7. For DOT_CLAUDE: also scan `rules/*.md`

### Frontmatter parsing consolidation

Add `parse_frontmatter(content: str) -> Tuple[Optional[Dict], Optional[str], int]` to `src/skillsaw/rules/builtin/utils.py`, returning `(frontmatter_dict, body_after_frontmatter, end_line)`. This consolidates the repeated `re.match(r"^---\n(.*?)\n---", ...)` pattern used in command_format.py, skills.py, agents.py, rules_dir.py, and agentskills.py. Existing rules can be updated to use it incrementally.

Also add `extract_section(content: str, heading: str) -> Optional[str]` to extract content under a markdown heading.

## HTML Rendering (`html_renderer.py`)

Extend the design language from the existing `formatters/html.py`: same font stack, color palette, stat cards, rounded corners, shadows. New components:

- **Navigation bar** with breadcrumbs (marketplace → plugin)
- **Table of contents** with anchor links
- **Plugin card grid** on marketplace index (name, description, version, component counts)
- **Section cards** for commands, skills, agents, hooks, MCP servers
- **Code blocks** for command synopses and hook/MCP JSON configs
- **Type badges** (command, skill, agent, hook, MCP) with distinct colors
- **Responsive layout** — works on mobile

API:
- `render_html(docs: DocsOutput) -> Dict[str, str]` — returns `{filename: html_content}`, always at least `{"index.html": "..."}`, plus per-plugin pages for marketplaces

## Markdown Rendering (`markdown_renderer.py`)

Simpler output mirroring the HTML structure:
- H1 title, H2 per plugin, H3 per component type, H4 per item
- Tables for metadata (version, author, license)
- Fenced code blocks for synopses and JSON configs
- Internal anchor links for cross-references

API:
- `render_markdown(docs: DocsOutput) -> Dict[str, str]` — returns `{filename: content}`, single or multi-file

## CLI Wiring (`__main__.py`)

Add a `docs` subparser alongside the default (no-subcommand) lint path. The structure:

```python
subparsers = parser.add_subparsers(dest="command")
docs_parser = subparsers.add_parser("docs", help="Generate documentation")
docs_parser.add_argument("path", nargs="?", ...)
docs_parser.add_argument("--format", choices=["html", "markdown"], default="html")
docs_parser.add_argument("--output-dir", type=Path, default=None)
docs_parser.add_argument("--title", default=None)
```

When `args.command == "docs"`, call `run_docs(args)`. When `args.command is None`, run existing lint logic unchanged.

`run_docs()` creates RepositoryContext, calls `extract_docs()`, renders via chosen format, writes output files to `--output-dir` (defaulting to `skillsaw-docs/`).

## Key Files to Modify

| File | Change |
|------|--------|
| `src/skillsaw/__main__.py` | Add `docs` subparser, `run_docs()` function |
| `src/skillsaw/rules/builtin/utils.py` | Add `parse_frontmatter()`, `extract_section()` |
| `src/skillsaw/docs/__init__.py` | New — public API |
| `src/skillsaw/docs/models.py` | New — dataclasses |
| `src/skillsaw/docs/extractor.py` | New — metadata extraction |
| `src/skillsaw/docs/html_renderer.py` | New — HTML generation |
| `src/skillsaw/docs/markdown_renderer.py` | New — markdown generation |
| `tests/test_docs.py` | New — extractor + renderer + CLI tests |
| `tests/conftest.py` | Add DOT_CLAUDE fixture if missing |

## Implementation Order

1. `models.py` — pure dataclasses, no dependencies
2. `parse_frontmatter()` + `extract_section()` in `utils.py`
3. `extractor.py` — walks context, parses files, returns DocsOutput
4. `html_renderer.py` — single-page first, then multi-page with cross-links
5. `markdown_renderer.py`
6. `docs/__init__.py` — wire together
7. `__main__.py` — add subparser and `run_docs()`
8. Tests
9. `make update` to regenerate docs

## Verification

1. `make test` — all existing tests pass, new docs tests pass
2. `make lint` — formatting clean
3. Manual testing against real repos:
   - Run `skillsaw docs` on the skillsaw repo itself (DOT_CLAUDE type)
   - Clone `openshift-eng/ai-helpers` (marketplace), run `skillsaw docs`, verify multi-page HTML with cross-links
   - Open generated HTML in browser to verify visual quality
4. `make update` — regenerate all generated files
