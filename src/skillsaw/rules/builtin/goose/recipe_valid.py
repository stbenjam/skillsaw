"""Validate the static authoring fields of Goose recipes."""

from skillsaw.blocks.goose import GooseRecipeBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.goose import EXTENSION_TYPES, INPUT_TYPES, REQUIREMENTS, recipe_string
from skillsaw.rule import Rule, Severity


class GooseRecipeValidRule(Rule):
    """Check metadata and declarations; template evaluation remains Goose's job."""

    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.GOOSE})

    @property
    def rule_id(self):
        return "goose-recipe-valid"

    @property
    def description(self):
        return "Goose recipe metadata, parameters and extensions must have valid shapes"

    def default_severity(self):
        return Severity.ERROR

    def check(self, context: RepositoryContext):
        violations = []
        for block in context.lint_tree.find(GooseRecipeBlock):
            if block.parse_error:
                violations.append(
                    self.violation(
                        "Cannot parse Goose recipe document",
                        file_path=block.path,
                        line=block.error_line,
                    )
                )
                continue
            data = block.raw_data
            if not isinstance(data, dict):
                violations.append(
                    self.violation("Goose recipe must be a mapping", file_path=block.path)
                )
                continue
            problems = []

            def problem(mapping, key, prefix, expected):
                problems.append((f"{prefix}{key}: {expected}", block.key_line(mapping, key)))

            def strings(mapping, keys, prefix="", required=False):
                for key in keys:
                    if required and key not in mapping:
                        problem(mapping, key, prefix, "required field is missing")
                        continue
                    if key not in mapping and not required:
                        continue
                    if mapping.get(key) is None:
                        continue
                    if recipe_string(mapping.get(key)) is None:
                        problem(mapping, key, prefix, "expected a string")

            def string_lists(mapping, keys, prefix=""):
                for key in keys:
                    values = mapping.get(key)
                    if values is not None and (
                        not isinstance(values, list)
                        or any(recipe_string(value) is None for value in values)
                    ):
                        problem(mapping, key, prefix, "expected an array of strings")

            strings(data, ("title", "description"), required=True)
            strings(data, ("version", "instructions", "prompt"))
            string_lists(data, ("activities",))
            if not any(
                (recipe_string(data.get(key)) or "").strip() for key in ("instructions", "prompt")
            ):
                problem(data, "instructions", "", "provide nonempty instructions or prompt")
            for key in ("settings", "author", "response", "retry"):
                if data.get(key) is not None and not isinstance(data[key], dict):
                    problem(data, key, "", "expected a mapping")
            for key in ("parameters", "extensions", "sub_recipes"):
                entries = data.get(key)
                if entries is None:
                    continue
                if not isinstance(entries, list):
                    problem(data, key, "", "expected an array")
                    continue
                for index, entry in enumerate(entries):
                    prefix = f"{key}[{index}]."
                    if not isinstance(entry, dict):
                        problem(data, key, "", f"item {index} must be a mapping")
                        continue
                    if key == "parameters":
                        strings(entry, ("key", "description"), prefix, required=True)
                        strings(entry, ("default",), prefix)
                        string_lists(entry, ("options",), prefix)
                        for field, allowed in (
                            ("input_type", INPUT_TYPES),
                            ("requirement", REQUIREMENTS),
                        ):
                            if not isinstance(entry.get(field), str) or entry[field] not in allowed:
                                problem(
                                    entry,
                                    field,
                                    prefix,
                                    f"expected one of {', '.join(sorted(allowed))}",
                                )
                        if entry.get("requirement") == "optional" and entry.get("default") is None:
                            problem(
                                entry, "default", prefix, "optional parameters require a default"
                            )
                        if entry.get("input_type") == "file" and entry.get("default") is not None:
                            problem(
                                entry, "default", prefix, "file parameters cannot have a default"
                            )
                    elif key == "sub_recipes":
                        strings(entry, ("name", "path"), prefix, required=True)
                        strings(entry, ("description",), prefix)
                        if entry.get("values") is not None and not isinstance(
                            entry["values"], dict
                        ):
                            problem(entry, "values", prefix, "expected a mapping")
                    else:
                        strings(entry, ("name",), prefix, required=True)
                        extension_type = entry.get("type")
                        if (
                            not isinstance(extension_type, str)
                            or extension_type not in EXTENSION_TYPES
                        ):
                            problem(
                                entry,
                                "type",
                                prefix,
                                f"expected one of {', '.join(sorted(EXTENSION_TYPES))}",
                            )
                        if extension_type == "stdio":
                            strings(entry, ("cmd",), prefix, required=True)
                            if not isinstance(entry.get("args"), list):
                                problem(entry, "args", prefix, "expected an array of strings")
                        elif extension_type == "streamable_http":
                            strings(entry, ("uri",), prefix, required=True)
                        strings(entry, ("description",), prefix)
                        string_lists(entry, ("available_tools",), prefix)
                        if extension_type == "stdio":
                            strings(entry, ("cwd",), prefix)
                            string_lists(entry, ("args", "env_keys"), prefix)
                        elif extension_type == "streamable_http":
                            strings(entry, ("socket", "client_id", "client_secret_key"), prefix)
                            string_lists(entry, ("env_keys", "scopes"), prefix)
                        elif extension_type in ("builtin", "platform"):
                            strings(entry, ("display_name",), prefix)
                        maps = (
                            ("envs", "headers")
                            if extension_type == "streamable_http"
                            else ("envs",) if extension_type == "stdio" else ()
                        )
                        for field in maps:
                            values = entry.get(field)
                            if values is not None and (
                                not isinstance(values, dict)
                                or any(recipe_string(value) is None for value in values.values())
                            ):
                                problem(entry, field, prefix, "expected a mapping of strings")
            if problems:
                detail = "; ".join(message for message, _ in problems[:5])
                if len(problems) > 5:
                    detail += f"; and {len(problems) - 5} more"
                violations.append(
                    self.violation(
                        f"Invalid Goose recipe: {detail}", file_path=block.path, line=problems[0][1]
                    )
                )
        return violations
