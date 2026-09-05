"""Path memo eviction must preserve cached values and explicit invalidation."""

from skillsaw.utils import FileCache


def test_many_aliases_stay_bounded_without_evicting_the_shared_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"enabled": true}\n')
    cache = FileCache(maxsize=3)
    reads = []

    @cache.cached
    def read_config(candidate):
        reads.append(candidate)
        return candidate.read_text()

    assert read_config(path) == '{"enabled": true}\n'
    aliases = []
    for name in ("one", "two", "three", "four", "five", "six"):
        directory = tmp_path / name
        directory.mkdir()
        alias = directory / ".." / path.name
        aliases.append(alias)
        assert read_config(alias) == '{"enabled": true}\n'
        assert len(cache._resolved) <= 3
    # Memo eviction re-resolves paths; it must not force repeated file reads.
    assert read_config(path) == '{"enabled": true}\n'
    assert reads == [path]

    path.write_text('{"enabled": false}\n')
    cache.invalidate(path)
    for alias in aliases:
        assert read_config(alias) == '{"enabled": false}\n'
    assert len(reads) == 2
    assert len(cache._resolved) <= 3
