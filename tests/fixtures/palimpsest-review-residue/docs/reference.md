# Catalog loader reference

The counterpart to `overview.md`. Every construct here is one the Palimpsest
Reviewer must leave alone, including the ones that superficially resemble a
pattern on its list.

## Loading a catalog

`load_catalog()` reads `catalog.json` from the repo root and returns the
parsed entries. A missing file is not an error — an absent catalog and an
empty one mean the same thing to callers, so both return `{}`.

Domain vocabulary is used verbatim throughout: the loader walks the **lint
tree**, resolves each **repo type**, and reads **frontmatter** from every
block it finds. These are terms of art, not inflated diction.

House style for this project puts a bold lead-in on each bullet:

- **`root`**: Directory to search. Must exist before the call.
- **`follow_links`**: Whether to traverse nested catalogs. Off by default,
  because a symlink loop would otherwise recurse forever.

The single em dash in the paragraph above sets off an aside, which is what an
em dash is for. One of them is not a tell.

## Limits

A catalog larger than 10 entries per page is paginated by the registry. The
loader does not raise on the boundary; it follows the cursor until the
registry stops returning one.
