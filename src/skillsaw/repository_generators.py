"""Cached generator source discovery on the repository context."""

from skillsaw.discovery.generators import discover_projects


class RepositoryGeneratorsMixin:
    def generator_projects(self):
        key = tuple(self.exclude_patterns)
        cached = getattr(self, "_generator_projects_cache", None)
        if cached is None or cached[0] != key:
            scan = self._repository_scan()
            projects = discover_projects(
                self.root_path,
                (*scan.tool_dirs.get(".ruler", ()), *scan.tool_dirs.get(".rulesync", ())),
                scan.generator_config_files,
                resolve=self.resolve_path,
                is_excluded=self.is_path_excluded,
            )
            self._generator_projects_cache = (key, projects)
        return self._generator_projects_cache[1]
