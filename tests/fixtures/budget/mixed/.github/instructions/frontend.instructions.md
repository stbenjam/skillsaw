---
description: "Frontend guidelines for the storefront web UI"
applyTo: "web/**"
---

- Components live in `web/src/components/`, one component per file.
- Use the shared fetch wrapper in `web/src/api.ts` for every request; never
  call `fetch` directly.
- Styles come from the design-system tokens; no hard-coded colors or
  spacing values.
