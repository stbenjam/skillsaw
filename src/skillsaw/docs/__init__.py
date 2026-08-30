"""Deprecated documentation generation, retained for compatibility.

The ``skillsaw docs`` CLI was deprecated in 0.20.0 and will be removed in an
upcoming release. Importing this package does not emit a runtime warning.
"""

from skillsaw.docs.extractor import extract_docs
from skillsaw.docs.html_renderer import render_html
from skillsaw.docs.markdown_renderer import render_markdown

__all__ = ["extract_docs", "render_html", "render_markdown"]
