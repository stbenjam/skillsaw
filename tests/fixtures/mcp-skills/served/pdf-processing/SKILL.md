---
name: pdf-processing
description: Extract, fill, and assemble PDF documents. Use when the user asks to fill a PDF form, merge PDFs, or produce an invoice or purchase order as a PDF.
---

# PDF processing

Choose the matching template from `templates/` before generating a document:

- [Invoice](templates/invoice.md) for billing a customer
- [Purchase order](templates/purchase-order.md) for ordering from a supplier

Fill every field in the template. If a value is unknown, ask the user rather
than guessing, then call the `render_pdf` tool with the completed template.
