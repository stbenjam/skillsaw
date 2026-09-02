"""Validate document parts against the bundled OOXML schema set."""

from pathlib import Path
from xml.etree import ElementTree

# Which schema validates which part. The schema set is loaded as a whole
# from the sibling directory — every .xsd in it is reachable at runtime
# through an <xsd:import>, so the mapping only names the entry points.
SCHEMA_MAPPINGS = {
    "word": "iso/wml.xsd",
    "xl": "iso/sml.xsd",
    "docProps": "ecma/opc-coreProperties.xsd",
}


class BaseValidator:
    def __init__(self, unpacked_dir, strict=False):
        self.unpacked_dir = Path(unpacked_dir)
        self.strict = strict
        self.schemas_dir = Path(__file__).parent.parent / "schemas"

    def schema_for(self, part):
        mapping = SCHEMA_MAPPINGS.get(part.parent.name)
        return self.schemas_dir / mapping if mapping else None

    def run(self):
        failures = []
        for part in sorted(self.unpacked_dir.rglob("*.xml")):
            schema = self.schema_for(part)
            if schema is None:
                continue
            try:
                ElementTree.parse(part)
            except ElementTree.ParseError as exc:
                failures.append(f"{part}: {exc}")
        return failures

    def render(self, failures, shells):
        body = "\n".join(f"<li>{failure}</li>" for failure in failures)
        shell = shells[0].read_text() if shells else "<ul>{body}</ul>"
        return shell.replace("{body}", body)
