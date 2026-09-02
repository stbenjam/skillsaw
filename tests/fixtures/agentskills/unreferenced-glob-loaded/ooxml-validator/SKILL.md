---
name: ooxml-validator
description: Validate the XML inside a .docx or .xlsx against the OOXML schemas, and render an HTML report of the failures. Use when a generated Office document opens with a repair prompt or fails to open at all.
---

# OOXML Validator

Unpack the document, then validate every part against the OOXML schemas:

```bash
unzip -q report.docx -d unpacked/
python scripts/validate.py unpacked/ --report validation.html
```

## Reading the output

Each failure names the part, the line, and the schema rule it violated.
Fix the part in `unpacked/`, re-zip, and re-run until the run is clean.

Pass `--strict` to fail on the warnings the Office applications tolerate,
such as an unknown attribute in a namespace the document declares but
never uses.

Legacy flat-file exports are out of scope: convert them to .docx first.
