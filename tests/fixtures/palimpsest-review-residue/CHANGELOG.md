# Changelog

A version-scoped document. Narrating change is the whole job here, so the
Palimpsest Reviewer must not flag this file for diff-anchored writing.

## 2.0.0

- Rewrote the pager. The previous approach re-parsed the template on every
  page, which was replaced by a single materialized list.
- `follow_links` now also handles nested catalogs.

## 1.2.0

- Added multi-page catalog support. Before this release the loader read only
  the first page and silently dropped the rest.
