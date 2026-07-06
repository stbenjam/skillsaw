---
paths:
  - "app/frontend/**"
---

# Frontend Rules

- Components live in `app/frontend/components/`, one component per file.
- Use the shared fetch wrapper in `app/frontend/api.ts` for every request;
  never call `fetch` directly.
- Styles come from the design-system tokens; no hard-coded colors.
