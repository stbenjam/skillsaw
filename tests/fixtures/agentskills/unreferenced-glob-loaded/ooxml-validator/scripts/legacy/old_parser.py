"""Pre-2019 flat-file parser, kept while the last exports are migrated."""


def parse(lines):
    for line in lines:
        part, _, message = line.partition("\t")
        yield part.strip(), message.strip()
