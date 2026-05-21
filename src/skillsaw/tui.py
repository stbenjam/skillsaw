"""TUI components for skillsaw — fix dashboard and tree explorer."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Input,
    Markdown,
    ProgressBar,
    RichLog,
    Static,
    Tree as TextualTree,
)

LOGO_BANNER = (
    "[bold rgb(255,80,0)]░█▀▀░█░█░▀█▀░█░░░█░░░█▀▀░█▀█░█░█[/]\n"
    "[bold rgb(255,140,0)]░▀▀█░█▀▄░░█░░█░░░█░░░▀▀█░█▀█░█▄█[/]\n"
    "[bold rgb(255,200,0)]░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀░▀[/]"
)

SLOGANS = [
    "Slicing through violations...",
    "Sharpening the codebase...",
    "Cutting clean code...",
    "Making the first cut...",
    "Sawing through tech debt...",
    "Precision cuts in progress...",
    "Measure twice, cut once...",
    "No blade left unturned...",
    "Trimming the rough edges...",
    "Power tools for clean code...",
    "Ripping through lint errors...",
    "Fine-tuning the finish...",
    "Safety glasses on...",
    "Dust collection engaged...",
    "Follow the cut line...",
]

FIX_CSS = """\
Screen {
    layout: vertical;
}

#header {
    height: 5;
    padding: 1 0 0 2;
}

#logo {
    width: auto;
    min-width: 36;
}

#header-right {
    width: 1fr;
    height: 3;
    content-align: right middle;
    text-align: right;
    padding-right: 1;
}

#slogan {
    text-style: italic;
    color: rgb(140,140,140);
}

#stats {
    height: 1;
}

#progress-row {
    height: 3;
    padding: 0 1;
    border-bottom: heavy rgb(80,80,80);
}

#progress-bar {
    width: 1fr;
}

#progress-label {
    width: auto;
    min-width: 30;
    content-align: right middle;
    text-align: right;
}

#main-panels {
    height: 1fr;
}

#log-panel {
    width: 1fr;
}

#log-panel-title {
    dock: top;
    height: 1;
    padding: 0 1;
    background: rgb(50,50,60);
    text-style: bold;
}

#diff-panel {
    width: 1fr;
    border-left: heavy rgb(80,80,80);
}

#diff-panel-title {
    dock: top;
    height: 1;
    padding: 0 1;
    background: rgb(50,50,60);
    text-style: bold;
}

#event-log {
    height: 1fr;
    scrollbar-size: 1 1;
}

#diff-log {
    height: 1fr;
    scrollbar-size: 1 1;
}

#status-bar {
    dock: bottom;
    height: 1;
    padding: 0 1;
    background: rgb(40,40,50);
    color: rgb(160,160,160);
}

#status-left {
    width: 1fr;
}

#status-right {
    width: auto;
    color: rgb(120,120,120);
}
"""

SUMMARY_CSS = """\
SummaryScreen {
    align: center middle;
}

#summary-box {
    width: 50;
    height: auto;
    max-height: 20;
    border: heavy rgb(255,140,0);
    background: rgb(30,30,40);
    padding: 1 2;
}

#summary-title {
    text-align: center;
    color: rgb(255,200,0);
    margin-bottom: 1;
}

#summary-body {
    height: auto;
}

#summary-hint {
    text-align: center;
    color: rgb(140,140,140);
    text-style: italic;
    margin-top: 1;
}
"""


class SummaryScreen(ModalScreen[None]):
    CSS = SUMMARY_CSS
    BINDINGS = [
        ("enter", "dismiss_screen", "Close"),
        ("escape", "dismiss_screen", "Close"),
        ("q", "dismiss_screen", "Close"),
    ]

    def __init__(self, result: Any, elapsed: float, **kwargs):
        super().__init__(**kwargs)
        self._result = result
        self._elapsed = elapsed

    def compose(self) -> ComposeResult:
        r = self._result
        with Vertical(id="summary-box"):
            yield Static(LOGO_BANNER, id="summary-title")
            body_lines = []
            body_lines.append(
                f"[green]✓ {r.violations_fixed}[/] fixed  "
                f"[dim]of {r.violations_before} violation(s)[/]"
            )
            if r.violations_after > 0:
                body_lines.append(f"[yellow]  {r.violations_after}[/] remaining")
            body_lines.append(f"[dim]  {len(r.files_modified)} file(s) modified[/]")
            tokens = r.total_usage.prompt_tokens + r.total_usage.completion_tokens
            if tokens:
                body_lines.append(f"[dim]  ~{tokens:,} tokens[/]")
            body_lines.append(f"[dim]  {_fmt_duration(self._elapsed)} elapsed[/]")
            yield Static("\n".join(body_lines), id="summary-body")
            yield Static("Press Enter to exit", id="summary-hint")

    def action_dismiss_screen(self) -> None:
        self.dismiss()


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    return f"{m}m{s:02d}s" if s else f"{m}m"


@dataclass
class FixParams:
    linter: Any
    provider: Any
    min_severity: Any
    max_workers: int
    dry_run: bool
    model_name: str = ""
    total_violations: int = 0


class FixApp(App):
    TITLE = "skillsaw fix"
    CSS = FIX_CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    slogan: reactive[str] = reactive("")
    violations_fixed: reactive[int] = reactive(0)
    violations_total: reactive[int] = reactive(0)
    progress_done: reactive[int] = reactive(0)
    progress_total: reactive[int] = reactive(0)
    elapsed: reactive[float] = reactive(0.0)
    active_files: reactive[str] = reactive("")

    class FixComplete(Message):
        def __init__(self, result: Any) -> None:
            super().__init__()
            self.result = result

    def __init__(self, params: FixParams, **kwargs):
        super().__init__(**kwargs)
        self._params = params
        self._start_time = time.monotonic()
        self._result = None
        self._active: dict[int, str] = {}
        self._slogan_timer: Timer | None = None
        self._cancelled = False
        self.violations_total = params.total_violations

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static(LOGO_BANNER, id="logo")
            with Vertical(id="header-right"):
                yield Static("", id="slogan")
                yield Static("", id="stats")
        with Horizontal(id="progress-row"):
            yield ProgressBar(total=100, show_percentage=False, show_eta=False, id="progress-bar")
            yield Static("", id="progress-label")
        with Horizontal(id="main-panels"):
            with Vertical(id="log-panel"):
                yield Static(" Event Log", id="log-panel-title")
                yield RichLog(markup=True, wrap=True, auto_scroll=True, id="event-log")
            with Vertical(id="diff-panel"):
                yield Static(" Live Diff", id="diff-panel-title")
                yield RichLog(markup=True, wrap=True, auto_scroll=True, id="diff-log")
        with Horizontal(id="status-bar"):
            yield Static("", id="status-left")
            yield Static("[dim]q/ctrl+c to quit[/]", id="status-right")

    def on_mount(self) -> None:
        self._rotate_slogan()
        self._slogan_timer = self.set_interval(5.0, self._rotate_slogan)
        self.set_interval(1.0, self._update_elapsed)
        self._refresh_stats()
        self.query_one("#event-log", RichLog).write("[dim]Starting LLM fix...[/]")
        self.query_one("#diff-log", RichLog).write("[dim]Waiting for changes...[/]")
        self._run_fix()

    def _rotate_slogan(self) -> None:
        self.slogan = random.choice(SLOGANS)

    def _update_elapsed(self) -> None:
        self.elapsed = time.monotonic() - self._start_time
        self._refresh_progress_label()
        self._refresh_status_bar()

    def watch_slogan(self, value: str) -> None:
        try:
            self.query_one("#slogan", Static).update(f"[italic dim]{value}[/]")
        except Exception:
            pass

    def watch_violations_fixed(self, value: int) -> None:
        self._refresh_stats()

    def watch_violations_total(self, value: int) -> None:
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        remaining = self.violations_total - self.violations_fixed
        try:
            self.query_one("#stats", Static).update(
                f"[green]{self.violations_fixed}[/] fixed  "
                f"[yellow]{remaining}[/] remaining  "
                f"[dim]of {self.violations_total} total[/]"
            )
        except Exception:
            pass

    def _refresh_progress_label(self) -> None:
        done = self.progress_done
        total = self.progress_total
        elapsed_str = _fmt_duration(self.elapsed)
        eta_str = ""
        if 0 < done < total:
            rate = self.elapsed / done
            remaining = rate * (total - done)
            eta_str = f"  ETA {_fmt_duration(remaining)}"
        pct = int(done / total * 100) if total else 0
        try:
            self.query_one("#progress-label", Static).update(
                f"[bold]{pct}%[/]  {elapsed_str}{eta_str}"
            )
            bar = self.query_one("#progress-bar", ProgressBar)
            bar.update(progress=pct)
        except Exception:
            pass

    def _refresh_status_bar(self) -> None:
        parts = []
        if self._active:
            names = [Path(n).name for n in self._active.values()]
            summary = ", ".join(names[:4])
            if len(names) > 4:
                summary += f" +{len(names) - 4}"
            parts.append(f"[bold]Active:[/] {summary}")
        model = self._params.model_name
        if model:
            parts.append(f"[dim]Model: {model}[/]")
        try:
            self.query_one("#status-left", Static).update("  ".join(parts) if parts else "")
        except Exception:
            pass

    def _on_fix_event(self, event_type: str, **kw) -> None:
        if self._cancelled or not self.is_running:
            raise KeyboardInterrupt
        try:
            self.call_from_thread(self._handle_event, event_type, **kw)
        except Exception:
            pass

    def _handle_event(self, event_type: str, **kw) -> None:
        if event_type == "progress":
            self.progress_done = kw["completed"]
            self.progress_total = kw["file_count"]
            self._refresh_progress_label()
            return

        if event_type == "file_start":
            self._active[kw.get("file_idx", 0)] = str(kw.get("rel_path", ""))
            self._refresh_status_bar()
            log = self.query_one("#event-log", RichLog)
            rel = kw["rel_path"]
            n = kw["num_violations"]
            rules = ", ".join(kw["rule_ids"])
            log.write(f"[bold]{rel}[/]  [dim]{n} violation(s): {rules}[/]")

        elif event_type == "iteration":
            log = self.query_one("#event-log", RichLog)
            rel = kw["rel_path"]
            log.write(f"  [dim]\\[{rel}] iteration {kw['iteration']}/{kw['max_iterations']}[/]")

        elif event_type == "tool_call":
            log = self.query_one("#event-log", RichLog)
            rel = kw["rel_path"]
            tool_args = kw.get("arguments", {})
            arg_summary = ""
            if "path" in tool_args:
                arg_summary = str(tool_args["path"])
            elif tool_args:
                first_key = next(iter(tool_args))
                val = str(tool_args[first_key])
                if len(val) > 40:
                    val = val[:37] + "..."
                arg_summary = val
            log.write(f"  [dim]\\[{rel}][/] {kw['name']}({arg_summary})")

        elif event_type == "tool_done":
            diff_text = kw.get("diff_text")
            if diff_text:
                diff_log = self.query_one("#diff-log", RichLog)
                diff_log.clear()
                rel = kw.get("rel_path", "")
                try:
                    self.query_one("#diff-panel-title", Static).update(f" Diff: {rel}")
                except Exception:
                    pass
                for line in diff_text.splitlines():
                    if line.startswith("+") and not line.startswith("+++"):
                        diff_log.write(f"[green]{_escape_markup(line)}[/]")
                    elif line.startswith("-") and not line.startswith("---"):
                        diff_log.write(f"[red]{_escape_markup(line)}[/]")
                    elif line.startswith("@@"):
                        diff_log.write(f"[cyan]{_escape_markup(line)}[/]")
                    else:
                        diff_log.write(_escape_markup(line))

        elif event_type == "retry":
            log = self.query_one("#event-log", RichLog)
            rel = kw["rel_path"]
            log.write(
                f"  [dim]\\[{rel}][/] [yellow]{kw['remaining']} violation(s)"
                f" remain, retrying...[/]"
            )

        elif event_type == "file_done":
            self._active.pop(kw.get("file_idx", 0), None)
            self._refresh_status_bar()
            log = self.query_one("#event-log", RichLog)
            rel = kw["rel_path"]
            remaining = kw.get("remaining", 0)
            changed = kw.get("changed", False)
            num = kw["num_violations"]
            if not changed:
                log.write(f"  [dim]\\[{rel}][/] [yellow]no changes[/]")
            elif remaining == 0:
                log.write(f"  [dim]\\[{rel}][/] [green]✓ all {num} violation(s) fixed[/]")
                self.violations_fixed += num
            else:
                fixed = num - remaining
                log.write(f"  [dim]\\[{rel}][/] [red]{fixed} fixed, {remaining} failed[/]")
                self.violations_fixed += fixed
            log.write("")

    @work(thread=True, exit_on_error=False)
    def _run_fix(self) -> None:
        p = self._params
        try:
            result = p.linter.llm_fix(
                p.provider,
                callback=self._on_fix_event,
                min_severity=p.min_severity,
                max_workers=p.max_workers,
                dry_run=p.dry_run,
            )
            self._result = result
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            try:
                self.call_from_thread(
                    self.query_one("#event-log", RichLog).write,
                    f"[red]Error: {_escape_markup(str(exc))}[/]",
                )
            except Exception:
                pass
        if self.is_running:
            self.call_from_thread(self._show_summary)

    def _show_summary(self) -> None:
        if self._result is not None:
            elapsed = time.monotonic() - self._start_time
            self.push_screen(SummaryScreen(self._result, elapsed), self._on_summary_dismissed)
        else:
            self.exit(None)

    def _on_summary_dismissed(self, _result: None) -> None:
        self.exit(self._result)

    def action_quit(self) -> None:
        self._cancelled = True
        self.workers.cancel_all()
        self.exit(self._result)


def _escape_markup(text: str) -> str:
    return text.replace("[", "\\[")


# ── Tree Explorer ──

_NODE_ICONS = {
    "MarketplaceNode": "🏪",
    "PluginNode": "🔌",
    "SkillNode": "⚡",
    "ApmNode": "📦",
    "ApmConfigNode": "⚙️",
    "CodeRabbitNode": "🐇",
    "PromptfooConfigNode": "🧪",
    "MarketplaceConfigNode": "⚙️",
}

TREE_CSS = """\
Screen {
    layout: vertical;
}

#tree-header {
    height: 5;
    padding: 1 0 0 2;
}

#tree-logo {
    width: auto;
    min-width: 36;
}

#tree-header-right {
    width: 1fr;
    height: 3;
    content-align: right middle;
    text-align: right;
    padding-right: 1;
}

#tree-panels {
    height: 1fr;
}

#tree-left {
    width: 1fr;
    min-width: 40;
}

#tree-left-title {
    dock: top;
    height: 1;
    padding: 0 1;
    background: rgb(50,50,60);
    text-style: bold;
}

#tree-right {
    width: 1fr;
    border-left: heavy rgb(80,80,80);
}

#tree-right-title {
    dock: top;
    height: 1;
    padding: 0 1;
    background: rgb(50,50,60);
    text-style: bold;
}

#lint-tree {
    height: 1fr;
    scrollbar-size: 1 1;
    overflow-x: auto;
}

#content-view {
    height: 1fr;
    scrollbar-size: 1 1;
}

#tree-status {
    dock: bottom;
    height: 1;
    padding: 0 1;
    background: rgb(40,40,50);
    color: rgb(160,160,160);
}

#tree-status-left {
    width: 1fr;
}

#tree-status-right {
    width: auto;
    color: rgb(120,120,120);
}

"""

SEARCH_CSS = """\
SearchScreen {
    align: center middle;
}

#search-box {
    width: 50;
    height: auto;
    border: heavy rgb(255,140,0);
    background: rgb(30,30,40);
    padding: 1 2;
}

#search-title {
    text-align: center;
    text-style: bold;
    color: rgb(255,200,0);
    margin-bottom: 1;
}

#search-input {
    width: 100%;
}
"""


class SearchScreen(ModalScreen[str]):
    CSS = SEARCH_CSS
    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Static("Search", id="search-title")
            yield Input(placeholder="Type to search...", id="search-input")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class TreeApp(App):
    TITLE = "skillsaw tree"
    CSS = TREE_CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("slash", "search", "Search"),
        ("escape", "clear_search", "Clear search"),
        ("e", "expand_all", "Expand all"),
        ("c", "collapse_all", "Collapse all"),
    ]

    def __init__(self, lint_tree: Any, root_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._lint_tree = lint_tree
        self._root_path = root_path
        self._filtered = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="tree-header"):
            yield Static(LOGO_BANNER, id="tree-logo")
            yield Static(
                f"[dim]{self._root_path}[/]",
                id="tree-header-right",
            )
        with Horizontal(id="tree-panels"):
            with Vertical(id="tree-left"):
                yield Static(" Tree", id="tree-left-title")
                yield TextualTree(self._lint_tree.tree_label(), id="lint-tree")
            with Vertical(id="tree-right"):
                yield Static(" Content", id="tree-right-title")
                yield Markdown("", id="content-view")
        with Horizontal(id="tree-status"):
            yield Static("", id="tree-status-left")
            yield Static(
                "[dim]/ search  Esc clear  e expand  c collapse  q quit[/]",
                id="tree-status-right",
            )

    def on_mount(self) -> None:
        tree = self.query_one("#lint-tree", TextualTree)
        tree.root.data = self._lint_tree
        self._populate_tree(tree.root, self._lint_tree)
        tree.root.expand_all()
        content = self.query_one("#content-view", Markdown)
        content.update("*Select a node to view its content.*")

    def _populate_tree(self, tree_node: Any, lint_node: Any) -> None:
        for child in lint_node.children:
            type_name = type(child).__name__
            icon = _NODE_ICONS.get(type_name, "")
            tokens = child.estimate_tokens()
            token_str = f" [dim]({tokens:,} tokens)[/]" if tokens else ""
            label = (
                f"{icon} {_escape_markup(child.tree_label())}{token_str}"
                if icon
                else f"{_escape_markup(child.tree_label())}{token_str}"
            )
            if child.children:
                branch = tree_node.add(label, data=child)
                self._populate_tree(branch, child)
            else:
                tree_node.add_leaf(label, data=child)

    def on_tree_node_highlighted(self, event: TextualTree.NodeHighlighted) -> None:
        self._show_node(event.node.data)

    def on_tree_node_selected(self, event: TextualTree.NodeSelected) -> None:
        self._show_node(event.node.data)

    def _show_node(self, node: Any) -> None:
        if node is None:
            return
        content = self.query_one("#content-view", Markdown)

        type_name = type(node).__name__
        path_str = str(node.path)
        try:
            rel = node.path.relative_to(self._root_path)
            path_str = str(rel)
        except ValueError:
            pass

        try:
            self.query_one("#tree-right-title", Static).update(f" {path_str}")
        except Exception:
            pass

        from .rules.builtin.content_analysis import ContentBlock, ParsedFrontmatterBlock

        tokens = node.estimate_tokens()
        status = f"[bold]{type_name}[/]  {path_str}  [dim]{tokens:,} tokens[/]"
        try:
            self.query_one("#tree-status-left", Static).update(status)
        except Exception:
            pass

        if isinstance(node, ParsedFrontmatterBlock):
            parts = []
            fm = node.frontmatter
            if fm:
                fm_lines = [f"| {k} | {v} |" for k, v in fm.items()]
                parts.append("| Field | Value |")
                parts.append("|---|---|")
                parts.extend(fm_lines)
                parts.append("")
            body = node.body_text
            if body:
                parts.append(body)
            content.update("\n".join(parts) if parts else "*No content.*")
        elif isinstance(node, ContentBlock):
            body = node.read_body(strip_code_blocks=False)
            if not body:
                content.update("*No content.*")
            elif node.path.suffix in (".json", ".yaml", ".yml"):
                lang = "json" if node.path.suffix == ".json" else "yaml"
                content.update(f"```{lang}\n{body}\n```")
            else:
                content.update(body)
        else:
            content.update(
                f"**{type_name}**\n\n"
                f"- **Path:** {path_str}\n"
                f"- **Children:** {len(node.children)}\n"
                f"- **Tokens:** {tokens:,}\n"
            )

    def action_search(self) -> None:
        self.push_screen(SearchScreen(), self._on_search_result)

    def _on_search_result(self, query: str) -> None:
        if not query:
            return
        matching_nodes: set[int] = set()
        self._collect_matches(self._lint_tree, query.lower(), matching_nodes)
        count = len(matching_nodes)
        if not count:
            try:
                self.query_one("#tree-status-left", Static).update(
                    f"[yellow]No matches for '{_escape_markup(query)}'[/]"
                )
            except Exception:
                pass
            return
        tree = self.query_one("#lint-tree", TextualTree)
        tree.clear()
        tree.root.data = self._lint_tree
        self._populate_tree_filtered(tree.root, self._lint_tree, matching_nodes)
        tree.root.expand_all()
        self._filtered = True
        try:
            self.query_one("#tree-status-left", Static).update(
                f"[bold]{count}[/] match(es) for '{_escape_markup(query)}'  [dim]Escape to clear[/]"
            )
        except Exception:
            pass

    def _collect_matches(self, lint_node: Any, query: str, matching: set[int]) -> bool:
        label = lint_node.tree_label().lower()
        is_match = query in label
        if is_match:
            self._add_subtree(lint_node, matching)
        child_match = False
        for child in lint_node.children:
            if self._collect_matches(child, query, matching):
                child_match = True
        if is_match or child_match:
            matching.add(id(lint_node))
            return True
        return False

    def _add_subtree(self, lint_node: Any, matching: set[int]) -> None:
        matching.add(id(lint_node))
        for child in lint_node.children:
            self._add_subtree(child, matching)

    def _populate_tree_filtered(self, tree_node: Any, lint_node: Any, matching: set[int]) -> None:
        for child in lint_node.children:
            if id(child) not in matching:
                continue
            type_name = type(child).__name__
            icon = _NODE_ICONS.get(type_name, "")
            tokens = child.estimate_tokens()
            token_str = f" [dim]({tokens:,} tokens)[/]" if tokens else ""
            label = (
                f"{icon} {_escape_markup(child.tree_label())}{token_str}"
                if icon
                else f"{_escape_markup(child.tree_label())}{token_str}"
            )
            children_in_match = [c for c in child.children if id(c) in matching]
            if children_in_match:
                branch = tree_node.add(label, data=child)
                self._populate_tree_filtered(branch, child, matching)
            else:
                tree_node.add_leaf(label, data=child)

    def action_clear_search(self) -> None:
        if not self._filtered:
            return
        tree = self.query_one("#lint-tree", TextualTree)
        tree.clear()
        tree.root.data = self._lint_tree
        self._populate_tree(tree.root, self._lint_tree)
        tree.root.expand_all()
        self._filtered = False
        try:
            self.query_one("#tree-status-left", Static).update("")
        except Exception:
            pass

    def action_expand_all(self) -> None:
        self.query_one("#lint-tree", TextualTree).root.expand_all()

    def action_collapse_all(self) -> None:
        tree = self.query_one("#lint-tree", TextualTree)
        tree.root.collapse_all()
        tree.root.expand()
