"""Render documentation as self-contained HTML pages."""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List

from skillsaw.context import RepositoryType
from skillsaw.docs.models import (
    AgentDoc,
    CommandDoc,
    DocsOutput,
    HookDoc,
    McpServerDoc,
    PluginDoc,
    RuleFileDoc,
    SkillDoc,
)

CSS = """\
:root {
    --primary: #6366f1;
    --primary-dark: #4f46e5;
    --secondary: #818cf8;
    --bg-dark: #0f0f0f;
    --bg-card: #1a1a1a;
    --bg-code: #2d2d2d;
    --text-primary: #f5f5f5;
    --text-secondary: #d4d4d4;
    --text-muted: #a3a3a3;
    --border: #3d3d3d;
    --success: #92cc6f;
    --accent: #ff9800;
    --radius: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 'Helvetica Neue', Arial, sans-serif;
    background: linear-gradient(135deg, #0f0f0f 0%, #1a1a1a 100%);
    color: var(--text-primary);
    line-height: 1.6;
    min-height: 100vh;
    padding-top: 60px;
}

a { color: var(--primary); text-decoration: none; }
a:hover { text-decoration: underline; }

.container { max-width: 1200px; margin: 0 auto; padding: 2rem; }

/* Navbar */
nav.navbar {
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    padding: 0.75rem 0;
    position: fixed; top: 0; left: 0; right: 0;
    z-index: 1000;
}
.navbar-content {
    max-width: 1200px; margin: 0 auto; padding: 0 2rem;
    display: flex; justify-content: space-between; align-items: center; gap: 2rem;
}
.navbar-brand { display: flex; align-items: center; gap: 1.5rem; }
.navbar-title { display: flex; flex-direction: column; gap: 0.125rem; }
.navbar-title h1 {
    font-size: 1.25rem; font-weight: 700;
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin: 0;
}
.subtitle { font-size: 0.75rem; color: var(--text-muted); margin: 0; }
.navbar-stats { display: flex; gap: 1rem; align-items: center; }
.stat {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.375rem 0.75rem; background: var(--bg-code);
    border-radius: 6px; border: 1px solid var(--border);
}
.stat-value { font-size: 1rem; font-weight: 700; color: var(--primary); }
.stat-label { color: var(--text-muted); font-size: 0.75rem; }

/* Search */
.search-box { margin-bottom: 2rem; position: relative; }
.search-input {
    width: 100%; padding: 1rem 1.5rem; font-size: 1rem; font-family: inherit;
    background: var(--bg-card); border: 2px solid var(--border);
    border-radius: var(--radius); color: var(--text-primary);
    transition: all 0.3s ease;
}
.search-input:focus {
    outline: none; border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}
.search-input::placeholder { color: var(--text-muted); }
.search-clear {
    position: absolute; right: 1rem; top: 50%; transform: translateY(-50%);
    background: none; border: none; color: var(--text-muted); font-size: 1.25rem;
    cursor: pointer; display: none; padding: 0.25rem;
}
.search-clear:hover { color: var(--text-primary); }

/* Plugin grid */
.plugins-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 1.5rem; margin-bottom: 3rem;
}
.plugin-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 1.5rem;
    transition: all 0.3s ease; cursor: pointer;
    height: 100%; display: flex; flex-direction: column;
}
.plugin-card:hover {
    transform: translateY(-2px); border-color: var(--primary);
    box-shadow: 0 8px 24px rgba(99, 102, 241, 0.15);
}
.plugin-header {
    display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;
}
.plugin-name { font-size: 1.5rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.25rem; }
.plugin-version {
    font-size: 0.75rem; color: var(--text-muted);
    background: var(--bg-code); padding: 0.25rem 0.5rem; border-radius: 4px;
}
.plugin-description { color: var(--text-secondary); margin-bottom: 1rem; font-size: 0.95rem; }
.item-counts {
    color: var(--text-muted); font-size: 0.875rem;
    display: flex; gap: 1rem; flex-wrap: wrap; margin-top: auto;
}
.item-count { display: flex; align-items: center; gap: 0.25rem; }
.item-count-badge {
    background: var(--bg-code); padding: 0.125rem 0.5rem;
    border-radius: 4px; font-weight: 600;
}

/* Section titles */
.section-title {
    font-size: 0.85rem; font-weight: 600; color: var(--text-primary);
    margin-bottom: 0.75rem; margin-top: 1.5rem;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.section-title:first-child { margin-top: 0; }

/* Search results */
.search-results-heading {
    font-size: 0.8rem; font-weight: 600; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em;
    margin: 1.5rem 0 0.75rem; padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}
.search-results-heading:first-child { margin-top: 0; }
.search-result-item {
    padding: 0.75rem 1rem; margin-bottom: 0.5rem;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; cursor: pointer; transition: all 0.2s ease;
    display: flex; align-items: center; gap: 0.75rem;
}
.search-result-item:hover {
    border-color: var(--primary); background: var(--bg-code);
}
.search-result-icon {
    flex-shrink: 0; width: 36px; height: 36px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.8rem; font-family: 'Monaco', 'Menlo', monospace;
}
.search-result-icon.cmd { background: rgba(146, 204, 111, 0.15); color: var(--success); }
.search-result-icon.skill { background: rgba(255, 152, 0, 0.15); color: var(--accent); }
.search-result-icon.agent { background: rgba(224, 192, 104, 0.15); color: #e0c068; }
.search-result-icon.hook { background: rgba(129, 140, 248, 0.15); color: var(--secondary); }
.search-result-icon.mcp { background: rgba(96, 165, 250, 0.15); color: #60a5fa; }
.search-result-icon.rule { background: rgba(163, 163, 163, 0.15); color: var(--text-muted); }
.search-result-icon.plugin { background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
.search-result-content { flex: 1; min-width: 0; }
.search-result-title { font-size: 0.95rem; color: var(--text-primary); font-weight: 600; }
.search-result-subtitle {
    font-size: 0.8rem; color: var(--text-muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.search-result-plugin {
    font-size: 0.75rem; color: var(--text-muted); background: var(--bg-code);
    padding: 0.125rem 0.5rem; border-radius: 4px; flex-shrink: 0;
}
.no-results {
    text-align: center; padding: 3rem; color: var(--text-muted); display: none;
}
.no-results.show { display: block; }
mark {
    background: rgba(99, 102, 241, 0.3); color: var(--text-primary);
    padding: 0 2px; border-radius: 2px;
}

/* Content items — shared across modal and single-plugin view */
.command-item {
    margin-bottom: 1rem; padding: 0.75rem;
    background: var(--bg-code); border-radius: 8px;
}
.command-name {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.9rem; color: var(--success); margin-bottom: 0.5rem; font-weight: 600;
}
.command-synopsis {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.5rem;
    padding: 0.5rem; background: var(--bg-dark); border-radius: 4px; overflow-x: auto;
}
.command-description { font-size: 0.875rem; color: var(--text-muted); }
.skill-item {
    margin-bottom: 1rem; padding: 0.75rem;
    background: var(--bg-code); border-radius: 8px; border-left: 3px solid var(--accent);
}
.skill-name { font-size: 0.95rem; color: var(--accent); margin-bottom: 0.5rem; font-weight: 600; }
.skill-description { font-size: 0.875rem; color: var(--text-muted); }
.skill-meta { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem; }
.agent-item {
    margin-bottom: 1rem; padding: 0.75rem;
    background: var(--bg-code); border-radius: 8px; border-left: 3px solid #e0c068;
}
.agent-name { font-size: 0.95rem; color: #e0c068; margin-bottom: 0.5rem; font-weight: 600; }
.agent-description { font-size: 0.875rem; color: var(--text-muted); }
.hook-item {
    margin-bottom: 1rem; padding: 0.75rem;
    background: var(--bg-code); border-radius: 8px; border-left: 3px solid var(--secondary);
}
.hook-name { font-size: 0.95rem; color: var(--secondary); margin-bottom: 0.5rem; font-weight: 600; }
.hook-type {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.5rem;
}
.mcp-item {
    margin-bottom: 1rem; padding: 0.75rem;
    background: var(--bg-code); border-radius: 8px; border-left: 3px solid #60a5fa;
}
.mcp-name { font-size: 0.95rem; color: #60a5fa; margin-bottom: 0.5rem; font-weight: 600; }
.mcp-type {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.5rem;
}
.rule-item {
    margin-bottom: 1rem; padding: 0.75rem;
    background: var(--bg-code); border-radius: 8px; border-left: 3px solid var(--text-muted);
}
.rule-name { font-size: 0.95rem; color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 600; }
.rule-description { font-size: 0.875rem; color: var(--text-muted); }
.rule-paths {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem;
}
.code-block {
    background: var(--bg-code); padding: 1rem; border-radius: 8px;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.9rem; color: var(--success); margin: 0.5rem 0;
    overflow-x: auto; white-space: pre;
}

/* Inline markdown */
.md-body code {
    background: var(--bg-code); padding: 1px 5px; border-radius: 3px;
    font-size: 0.9em; color: var(--text-secondary);
}
.md-body strong { color: var(--text-primary); }
.md-body a { color: var(--primary); }

/* Modal */
.modal {
    display: none; position: fixed; z-index: 1000;
    left: 0; top: 0; width: 100%; height: 100%;
    background-color: rgba(0, 0, 0, 0.8);
    align-items: center; justify-content: center;
}
.modal.show { display: flex; }
.modal-content {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); max-width: 700px; width: 90%;
    max-height: 85vh; position: relative;
    display: flex; flex-direction: column;
}
.modal-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 1.5rem 2rem 1rem 2rem; border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.modal-title-section { flex: 1; }
.modal-title { font-size: 1.35rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.5rem; }
.modal-meta { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
#modal-body { padding: 1.5rem 2rem 2rem 2rem; overflow-y: auto; flex: 1; }
.modal-filter {
    width: 100%; padding: 0.5rem 0.75rem; font-size: 0.875rem; font-family: inherit;
    background: var(--bg-code); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text-primary); margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.modal-filter:focus { outline: none; border-color: var(--primary); }
.modal-filter::placeholder { color: var(--text-muted); }
.modal-section-items[data-filtered="true"] .command-item,
.modal-section-items[data-filtered="true"] .skill-item,
.modal-section-items[data-filtered="true"] .agent-item,
.modal-section-items[data-filtered="true"] .hook-item,
.modal-section-items[data-filtered="true"] .mcp-item,
.modal-section-items[data-filtered="true"] .rule-item { display: none; }
.modal-section-items[data-filtered="true"] .modal-match { display: block; }
.close-button {
    background: none; border: none; color: var(--text-muted);
    font-size: 2rem; cursor: pointer; padding: 0;
    width: 2rem; height: 2rem;
    display: flex; align-items: center; justify-content: center;
    transition: color 0.3s ease;
}
.close-button:hover { color: var(--primary); }

footer { text-align: center; padding: 2rem; color: var(--text-muted); font-size: 0.875rem; }
footer a { color: var(--primary); }

/* Responsive */
@media (max-width: 968px) {
    .navbar-content { flex-direction: column; align-items: flex-start; gap: 1rem; }
    .navbar-brand { width: 100%; justify-content: space-between; }
    .navbar-stats { gap: 0.5rem; }
    .stat-label { display: none; }
    .plugins-grid { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
    .navbar-stats { flex-wrap: wrap; }
}
"""


def render_html(docs: DocsOutput) -> Dict[str, str]:
    """Render documentation as a single self-contained HTML page."""
    return {"index.html": _render_page(docs)}


def _render_page(docs: DocsOutput) -> str:
    is_marketplace = docs.repo_type == RepositoryType.MARKETPLACE and docs.marketplace is not None

    data = _build_data(docs)
    # Escape </ sequences to prevent </script> from breaking out of the script tag
    data_json = json.dumps(data, indent=None).replace("<", "\\u003c").replace(">", "\\u003e")

    mp = docs.marketplace
    title = (mp.name if mp and mp.name else docs.title) if is_marketplace else docs.title
    subtitle = _repo_type_label(docs.repo_type)

    return _wrap_page(
        title=title, subtitle=subtitle, data_json=data_json, is_marketplace=is_marketplace
    )


def _build_data(docs: DocsOutput) -> Dict[str, Any]:
    """Build the data structure for embedding as JSON."""
    plugins_data: List[Dict[str, Any]] = []

    sorted_plugins = sorted(docs.plugins, key=lambda p: p.name.lower())

    for plugin in sorted_plugins:
        p: Dict[str, Any] = {
            "name": plugin.name,
            "description": plugin.description or "",
            "version": plugin.version or "",
            "has_readme": plugin.has_readme,
            "commands": [],
            "skills": [],
            "agents": [],
            "hooks": [],
            "mcp_servers": [],
            "rules": [],
        }

        for cmd in plugin.commands:
            p["commands"].append(
                {
                    "name": cmd.name,
                    "full_name": cmd.full_name or "",
                    "description": cmd.description or "",
                    "description_html": _md(cmd.description),
                    "synopsis": cmd.synopsis or "",
                    "body_html": _md(cmd.body) if cmd.body else "",
                }
            )

        for skill in plugin.skills:
            meta_parts = []
            if skill.license:
                meta_parts.append(f"License: {_esc(skill.license)}")
            if skill.compatibility:
                meta_parts.append(f"Compatibility: {_esc(skill.compatibility)}")
            if skill.allowed_tools:
                meta_parts.append(f"Tools: {_esc(', '.join(skill.allowed_tools))}")
            p["skills"].append(
                {
                    "name": skill.name,
                    "description": skill.description or "",
                    "description_html": _md(skill.description),
                    "meta": " &middot; ".join(meta_parts),
                }
            )

        for agent in plugin.agents:
            p["agents"].append(
                {
                    "name": agent.name,
                    "description": agent.description or "",
                    "description_html": _md(agent.description),
                }
            )

        for hook in plugin.hooks:
            for entry in hook.entries:
                p["hooks"].append(
                    {
                        "event_type": hook.event_type,
                        "matcher": entry.matcher,
                        "hooks_json": json.dumps(entry.hooks, indent=2),
                    }
                )

        for srv in plugin.mcp_servers:
            endpoint = srv.config.get("command", srv.config.get("url", ""))
            p["mcp_servers"].append(
                {
                    "name": srv.name,
                    "type": srv.server_type,
                    "endpoint": str(endpoint),
                    "source": srv.source_file,
                }
            )

        for rule in plugin.rules:
            desc = rule.description or (rule.body[:200] if rule.body else "")
            p["rules"].append(
                {
                    "name": rule.name,
                    "description": desc,
                    "description_html": _md(desc),
                    "globs": rule.globs,
                }
            )

        plugins_data.append(p)

    standalone_skills = []
    for skill in docs.skills:
        standalone_skills.append(
            {
                "name": skill.name,
                "description": skill.description or "",
                "description_html": _md(skill.description),
            }
        )

    return {
        "plugins": plugins_data,
        "standalone_skills": standalone_skills,
    }


def _wrap_page(title: str, subtitle: str, data_json: str, is_marketplace: bool) -> str:
    search_placeholder = (
        "Search plugins, commands, skills..."
        if is_marketplace
        else "Search commands, skills, agents..."
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <nav class="navbar">
    <div class="navbar-content">
      <div class="navbar-brand">
        <div class="navbar-title">
          <h1>{_esc(title)}</h1>
          <p class="subtitle">{_esc(subtitle)}</p>
        </div>
        <div class="navbar-stats" id="navbar-stats"></div>
      </div>
    </div>
  </nav>

  <main class="container">
    <div class="search-box">
      <input type="text" id="search" class="search-input"
             placeholder="{_esc(search_placeholder)}" autocomplete="off">
      <button class="search-clear" id="search-clear" onclick="clearSearch()"
              aria-label="Clear search">&times;</button>
    </div>

    <section id="content"></section>

    <div class="no-results" id="no-results">
      No results found.
    </div>

    <footer>
      Generated by <a href="https://github.com/stbenjam/skillsaw">skillsaw</a>
    </footer>
  </main>

  <div id="modal" class="modal" onclick="closeModal(event)">
    <div class="modal-content" onclick="event.stopPropagation()">
      <div class="modal-header" id="modal-header"></div>
      <div id="modal-body"></div>
    </div>
  </div>

  <script>
  var DATA = {data_json};
  var IS_MARKETPLACE = {'true' if is_marketplace else 'false'};
  </script>
  <script>
{_get_js()}
  </script>
</body>
</html>
"""


def _get_js() -> str:
    return """\
(function() {
  var allPlugins = DATA.plugins;
  var standaloneSkills = DATA.standalone_skills || [];

  function init() {
    updateStats();
    renderDefault();
    handleHashChange();
    document.getElementById('search').addEventListener('input', onSearchInput);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') closeModal();
      if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        document.getElementById('search').focus();
      }
    });
  }

  function updateStats() {
    var stats = document.getElementById('navbar-stats');
    var items = [];
    if (IS_MARKETPLACE) items.push({label: 'Plugins', value: allPlugins.length});
    var tc = allPlugins.reduce(function(s,p){return s+p.commands.length;},0);
    var ts = allPlugins.reduce(function(s,p){return s+p.skills.length;},0) + standaloneSkills.length;
    var ta = allPlugins.reduce(function(s,p){return s+p.agents.length;},0);
    var th = allPlugins.reduce(function(s,p){return s+p.hooks.length;},0);
    var tm = allPlugins.reduce(function(s,p){return s+p.mcp_servers.length;},0);
    var tr = allPlugins.reduce(function(s,p){return s+p.rules.length;},0);
    if (tc > 0) items.push({label: 'Commands', value: tc});
    if (ts > 0) items.push({label: 'Skills', value: ts});
    if (ta > 0) items.push({label: 'Agents', value: ta});
    if (th > 0) items.push({label: 'Hooks', value: th});
    if (tm > 0) items.push({label: 'MCP Servers', value: tm});
    if (tr > 0) items.push({label: 'Rules', value: tr});
    stats.innerHTML = items.map(function(i) {
      return '<div class="stat"><div class="stat-value">'+i.value+'</div><div class="stat-label">'+i.label+'</div></div>';
    }).join('');
  }

  function renderDefault() {
    if (IS_MARKETPLACE) {
      renderPluginGrid(allPlugins);
    } else {
      renderSingleContent();
    }
  }

  // ---- Marketplace: plugin card grid ----
  function renderPluginGrid(plugins) {
    var el = document.getElementById('content');
    var nr = document.getElementById('no-results');
    if (plugins.length === 0) { el.innerHTML = ''; nr.classList.add('show'); return; }
    nr.classList.remove('show');
    el.innerHTML = '<div class="plugins-grid">' + plugins.map(function(p) {
      var counts = buildCountBadges(p);
      var ver = p.version ? '<span class="plugin-version">v'+esc(p.version)+'</span>' : '';
      return '<div class="plugin-card" onclick="showPluginModal(\\''+escAttr(p.name)+'\\')">' +
        '<div class="plugin-header"><div><div class="plugin-name">'+esc(p.name)+'</div>'+ver+'</div></div>' +
        '<div class="plugin-description">'+(p.description_html || esc(p.description) || '<em>No description</em>')+'</div>' +
        '<div class="item-counts">'+counts+'</div></div>';
    }).join('') + '</div>';
  }

  function buildCountBadges(p) {
    var b = [];
    if (p.commands.length) b.push(badge(p.commands.length, 'command'));
    if (p.skills.length) b.push(badge(p.skills.length, 'skill'));
    if (p.agents.length) b.push(badge(p.agents.length, 'agent'));
    if (p.hooks.length) b.push(badge(p.hooks.length, 'hook'));
    if (p.mcp_servers.length) b.push(badge(p.mcp_servers.length, 'mcp server'));
    if (p.rules.length) b.push(badge(p.rules.length, 'rule'));
    return b.join('');
  }

  function badge(n, label) {
    return '<div class="item-count"><span class="item-count-badge">'+n+'</span><span>'+label+(n!==1?'s':'')+'</span></div>';
  }

  // ---- Single-plugin: inline content ----
  function renderSingleContent() {
    var el = document.getElementById('content');
    var html = '';
    allPlugins.forEach(function(p) { html += renderPluginSections(p); });
    if (standaloneSkills.length > 0) {
      html += '<div class="section-title">Skills</div>';
      standaloneSkills.forEach(function(s) {
        html += '<div class="skill-item"><div class="skill-name">'+esc(s.name)+'</div>';
        if (s.description_html) html += '<div class="skill-description">'+s.description_html+'</div>';
        html += '</div>';
      });
    }
    el.innerHTML = html;
  }

  function renderPluginSections(p, forModal) {
    var h = '';
    var wrap = forModal ? function(cls, inner) { return '<div class="modal-section-items" data-filtered="false">' + inner + '</div>'; } : function(cls, inner) { return inner; };
    var dataAttr = forModal ? function(text) { return ' data-search="'+esc(text.toLowerCase())+'"'; } : function() { return ''; };
    if (p.commands.length) {
      h += '<div class="section-title">Commands</div>';
      var cmds = '';
      p.commands.forEach(function(c) {
        var searchText = (c.full_name||c.name) + ' ' + (c.description||'') + ' ' + (c.synopsis||'');
        cmds += '<div class="command-item"'+dataAttr(searchText)+'>';
        cmds += '<div class="command-name">/'+esc(c.full_name||c.name)+'</div>';
        if (c.synopsis) cmds += '<div class="command-synopsis">'+esc(c.synopsis)+'</div>';
        if (c.description_html) cmds += '<div class="command-description">'+c.description_html+'</div>';
        if (c.body_html) cmds += '<div class="command-description md-body" style="margin-top:0.5rem">'+c.body_html+'</div>';
        cmds += '</div>';
      });
      h += wrap('commands', cmds);
    }
    if (p.skills.length) {
      h += '<div class="section-title">Skills</div>';
      var skills = '';
      p.skills.forEach(function(s) {
        var searchText = s.name + ' ' + (s.description||'');
        skills += '<div class="skill-item"'+dataAttr(searchText)+'><div class="skill-name">'+esc(s.name)+'</div>';
        if (s.description_html) skills += '<div class="skill-description">'+s.description_html+'</div>';
        if (s.meta) skills += '<div class="skill-meta">'+s.meta+'</div>';
        skills += '</div>';
      });
      h += wrap('skills', skills);
    }
    if (p.agents.length) {
      h += '<div class="section-title">Agents</div>';
      var agents = '';
      p.agents.forEach(function(a) {
        var searchText = a.name + ' ' + (a.description||'');
        agents += '<div class="agent-item"'+dataAttr(searchText)+'><div class="agent-name">'+esc(a.name)+'</div>';
        if (a.description_html) agents += '<div class="agent-description">'+a.description_html+'</div>';
        agents += '</div>';
      });
      h += wrap('agents', agents);
    }
    if (p.hooks.length) {
      h += '<div class="section-title">Hooks</div>';
      var hooks = '';
      p.hooks.forEach(function(hk) {
        var searchText = hk.event_type + ' ' + hk.matcher;
        hooks += '<div class="hook-item"'+dataAttr(searchText)+'><div class="hook-name">'+esc(hk.event_type)+'</div>';
        hooks += '<div class="hook-type">Matcher: '+esc(hk.matcher)+'</div>';
        hooks += '<div class="code-block">'+esc(hk.hooks_json)+'</div></div>';
      });
      h += wrap('hooks', hooks);
    }
    if (p.mcp_servers.length) {
      h += '<div class="section-title">MCP Servers</div>';
      var mcps = '';
      p.mcp_servers.forEach(function(srv) {
        var searchText = srv.name + ' ' + srv.type + ' ' + srv.endpoint;
        mcps += '<div class="mcp-item"'+dataAttr(searchText)+'><div class="mcp-name">'+esc(srv.name)+'</div>';
        mcps += '<div class="mcp-type">'+esc(srv.type)+' &mdash; '+esc(srv.endpoint)+'</div></div>';
      });
      h += wrap('mcp', mcps);
    }
    if (p.rules.length) {
      h += '<div class="section-title">Rules</div>';
      var rules = '';
      p.rules.forEach(function(r) {
        var searchText = r.name + ' ' + (r.description||'');
        rules += '<div class="rule-item"'+dataAttr(searchText)+'><div class="rule-name">'+esc(r.name)+'</div>';
        if (r.description_html) rules += '<div class="rule-description">'+r.description_html+'</div>';
        if (r.globs && r.globs.length) rules += '<div class="rule-paths">Paths: '+r.globs.map(esc).join(', ')+'</div>';
        rules += '</div>';
      });
      h += wrap('rules', rules);
    }
    return h;
  }

  // ---- Search ----
  var searchDebounce = null;
  function onSearchInput(e) {
    var q = e.target.value;
    document.getElementById('search-clear').style.display = q ? 'block' : 'none';
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(function() { doSearch(q); }, 150);
  }

  window.clearSearch = function() {
    var input = document.getElementById('search');
    input.value = '';
    document.getElementById('search-clear').style.display = 'none';
    renderDefault();
    document.getElementById('no-results').classList.remove('show');
  };

  function doSearch(query) {
    var q = query.toLowerCase().trim();
    if (!q) { renderDefault(); document.getElementById('no-results').classList.remove('show'); return; }

    var results = { plugins: [], commands: [], skills: [], agents: [], hooks: [], rules: [] };

    allPlugins.forEach(function(p) {
      if (match(p.name, q) || match(p.description, q)) results.plugins.push(p);
      p.commands.forEach(function(c) {
        if (match(c.name, q) || match(c.full_name, q) || match(c.description, q) || match(c.synopsis, q))
          results.commands.push({plugin: p.name, item: c});
      });
      p.skills.forEach(function(s) {
        if (match(s.name, q) || match(s.description, q))
          results.skills.push({plugin: p.name, item: s});
      });
      p.agents.forEach(function(a) {
        if (match(a.name, q) || match(a.description, q))
          results.agents.push({plugin: p.name, item: a});
      });
      p.hooks.forEach(function(h) {
        if (match(h.event_type, q) || match(h.matcher, q))
          results.hooks.push({plugin: p.name, item: h});
      });
      p.rules.forEach(function(r) {
        if (match(r.name, q) || match(r.description, q))
          results.rules.push({plugin: p.name, item: r});
      });
    });

    standaloneSkills.forEach(function(s) {
      if (match(s.name, q) || match(s.description, q))
        results.skills.push({plugin: '', item: s});
    });

    renderSearchResults(results, q);
  }

  function match(str, q) { return str && str.toLowerCase().indexOf(q) !== -1; }

  function hi(text, q) {
    if (!text || !q) return esc(text || '');
    var safe = esc(text);
    var safeQ = esc(q);
    var re = new RegExp('(' + safeQ.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
    return safe.replace(re, '<mark>$1</mark>');
  }

  function renderSearchResults(results, q) {
    var el = document.getElementById('content');
    var nr = document.getElementById('no-results');
    var total = results.plugins.length + results.commands.length + results.skills.length +
                results.agents.length + results.hooks.length + results.rules.length;
    if (total === 0) { el.innerHTML = ''; nr.classList.add('show'); return; }
    nr.classList.remove('show');

    var html = '';

    if (results.plugins.length && IS_MARKETPLACE) {
      html += '<div class="search-results-heading">Plugins (' + results.plugins.length + ')</div>';
      results.plugins.forEach(function(p) {
        html += '<div class="search-result-item" onclick="showPluginModal(\\''+escAttr(p.name)+'\\')">';
        html += '<div class="search-result-icon plugin">'+esc(p.name.charAt(0).toUpperCase())+'</div>';
        html += '<div class="search-result-content"><div class="search-result-title">'+hi(p.name,q)+'</div>';
        html += '<div class="search-result-subtitle">'+hi(p.description,q)+'</div></div></div>';
      });
    }

    if (results.commands.length) {
      html += '<div class="search-results-heading">Commands (' + results.commands.length + ')</div>';
      results.commands.forEach(function(r) {
        var onclick = IS_MARKETPLACE ? ' onclick="showPluginModal(\\''+escAttr(r.plugin)+'\\')"' : '';
        html += '<div class="search-result-item"'+onclick+'>';
        html += '<div class="search-result-icon cmd">$</div>';
        html += '<div class="search-result-content"><div class="search-result-title">'+hi(r.item.full_name || r.item.name, q)+'</div>';
        html += '<div class="search-result-subtitle">'+hi(r.item.description,q)+'</div></div>';
        if (r.plugin) html += '<span class="search-result-plugin">'+esc(r.plugin)+'</span>';
        html += '</div>';
      });
    }

    if (results.skills.length) {
      html += '<div class="search-results-heading">Skills (' + results.skills.length + ')</div>';
      results.skills.forEach(function(r) {
        var onclick = IS_MARKETPLACE && r.plugin ? ' onclick="showPluginModal(\\''+escAttr(r.plugin)+'\\')"' : '';
        html += '<div class="search-result-item"'+onclick+'>';
        html += '<div class="search-result-icon skill">S</div>';
        html += '<div class="search-result-content"><div class="search-result-title">'+hi(r.item.name,q)+'</div>';
        html += '<div class="search-result-subtitle">'+hi(r.item.description,q)+'</div></div>';
        if (r.plugin) html += '<span class="search-result-plugin">'+esc(r.plugin)+'</span>';
        html += '</div>';
      });
    }

    if (results.agents.length) {
      html += '<div class="search-results-heading">Agents (' + results.agents.length + ')</div>';
      results.agents.forEach(function(r) {
        var onclick = IS_MARKETPLACE && r.plugin ? ' onclick="showPluginModal(\\''+escAttr(r.plugin)+'\\')"' : '';
        html += '<div class="search-result-item"'+onclick+'>';
        html += '<div class="search-result-icon agent">A</div>';
        html += '<div class="search-result-content"><div class="search-result-title">'+hi(r.item.name,q)+'</div>';
        html += '<div class="search-result-subtitle">'+hi(r.item.description,q)+'</div></div>';
        if (r.plugin) html += '<span class="search-result-plugin">'+esc(r.plugin)+'</span>';
        html += '</div>';
      });
    }

    if (results.hooks.length) {
      html += '<div class="search-results-heading">Hooks (' + results.hooks.length + ')</div>';
      results.hooks.forEach(function(r) {
        var onclick = IS_MARKETPLACE && r.plugin ? ' onclick="showPluginModal(\\''+escAttr(r.plugin)+'\\')"' : '';
        html += '<div class="search-result-item"'+onclick+'>';
        html += '<div class="search-result-icon hook">H</div>';
        html += '<div class="search-result-content"><div class="search-result-title">'+hi(r.item.event_type,q)+'</div>';
        html += '<div class="search-result-subtitle">Matcher: '+hi(r.item.matcher,q)+'</div></div>';
        if (r.plugin) html += '<span class="search-result-plugin">'+esc(r.plugin)+'</span>';
        html += '</div>';
      });
    }

    if (results.rules.length) {
      html += '<div class="search-results-heading">Rules (' + results.rules.length + ')</div>';
      results.rules.forEach(function(r) {
        var onclick = IS_MARKETPLACE && r.plugin ? ' onclick="showPluginModal(\\''+escAttr(r.plugin)+'\\')"' : '';
        html += '<div class="search-result-item"'+onclick+'>';
        html += '<div class="search-result-icon rule">R</div>';
        html += '<div class="search-result-content"><div class="search-result-title">'+hi(r.item.name,q)+'</div>';
        html += '<div class="search-result-subtitle">'+hi(r.item.description,q)+'</div></div>';
        if (r.plugin) html += '<span class="search-result-plugin">'+esc(r.plugin)+'</span>';
        html += '</div>';
      });
    }

    el.innerHTML = html;
  }

  // ---- Modal ----
  window.showPluginModal = function(name) {
    var p = allPlugins.find(function(x){return x.name===name;});
    if (!p) return;
    var counts = buildCountBadges(p);
    var ver = p.version ? '<span class="plugin-version">v'+esc(p.version)+'</span>' : '';
    var hdr = '<div class="modal-title-section"><div class="modal-title">'+esc(p.name)+'</div>' +
              '<div class="modal-meta">'+counts+'</div></div>' +
              '<div style="display:flex;flex-direction:column;gap:0.5rem;align-items:flex-end">' +
              '<div style="display:flex;gap:1rem;align-items:flex-start">'+ver+
              '<button class="close-button" onclick="closeModal()">&times;</button></div></div>';
    var totalItems = p.commands.length + p.skills.length + p.agents.length + p.hooks.length + p.mcp_servers.length + p.rules.length;
    var body = '<div class="plugin-description" style="margin-bottom:1rem">'+(p.description_html || esc(p.description) || '')+'</div>';
    if (totalItems >= 5) {
      body += '<input type="text" class="modal-filter" id="modal-filter" placeholder="Filter commands, skills..." autocomplete="off">';
    }
    body += '<div id="modal-sections">' + renderPluginSections(p, true) + '</div>';
    document.getElementById('modal-header').innerHTML = hdr;
    document.getElementById('modal-body').innerHTML = body;
    document.getElementById('modal').classList.add('show');
    window.location.hash = name;
    var filterInput = document.getElementById('modal-filter');
    if (filterInput) {
      filterInput.addEventListener('input', function(e) { filterModalItems(e.target.value); });
      filterInput.focus();
    }
  };

  window.closeModal = function(event) {
    if (!event || event.target.id === 'modal') {
      document.getElementById('modal').classList.remove('show');
      if (window.location.hash) history.pushState('','',window.location.pathname+window.location.search);
    }
  };

  function filterModalItems(query) {
    var q = query.toLowerCase().trim();
    var sections = document.querySelectorAll('#modal-sections .modal-section-items');
    sections.forEach(function(section) {
      if (!q) { section.setAttribute('data-filtered', 'false'); return; }
      section.setAttribute('data-filtered', 'true');
      var items = section.children;
      for (var i = 0; i < items.length; i++) {
        var searchText = items[i].getAttribute('data-search') || '';
        if (searchText.indexOf(q) !== -1) {
          items[i].classList.add('modal-match');
        } else {
          items[i].classList.remove('modal-match');
        }
      }
    });
    // Hide section titles with no visible items
    var titles = document.querySelectorAll('#modal-sections .section-title');
    titles.forEach(function(title) {
      var next = title.nextElementSibling;
      if (!next || !next.classList.contains('modal-section-items')) return;
      if (!q) { title.style.display = ''; return; }
      var hasVisible = next.querySelector('.modal-match');
      title.style.display = hasVisible ? '' : 'none';
    });
  }

  function handleHashChange() {
    var hash = window.location.hash.slice(1);
    if (hash && IS_MARKETPLACE) {
      var p = allPlugins.find(function(x){return x.name===hash;});
      if (p) showPluginModal(hash);
    }
  }
  window.addEventListener('hashchange', handleHashChange);

  function esc(str) {
    if (!str) return '';
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function escAttr(str) {
    return esc(str).replace(/'/g, '&#39;');
  }

  init();
})();
"""


# -- Utilities --


def _esc(text: str) -> str:
    return html.escape(str(text))


def _md(text: str) -> str:
    """Convert inline markdown to HTML with XSS protection."""
    if not text:
        return ""
    safe = html.escape(str(text))
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", safe)
    safe = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        safe,
    )
    paragraphs = re.split(r"\n{2,}", safe.strip())
    if len(paragraphs) <= 1:
        return safe.strip().replace("\n", "<br>")
    return "".join(f"<p>{p.strip().replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip())


def _repo_type_label(repo_type: RepositoryType) -> str:
    labels = {
        RepositoryType.SINGLE_PLUGIN: "Plugin",
        RepositoryType.MARKETPLACE: "Marketplace",
        RepositoryType.AGENTSKILLS: "agentskills.io",
        RepositoryType.DOT_CLAUDE: ".claude",
        RepositoryType.UNKNOWN: "Unknown",
    }
    return labels.get(repo_type, repo_type.value)
