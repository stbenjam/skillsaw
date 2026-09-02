# Building the test corpus

## Clone sample repositories

Shallow-clone a diverse set of real-world repositories into `~/tmp/skillsaw-audit/corpus/<owner>_<repo>/` using `git clone --depth 1`. Having a shared corpus ensures consistent and comparable testing across all reviewers.

## Gather target repositories

Include reference collections and popular repositories from each supported ecosystem, plus at least 10 repositories found via GitHub search for the specific file types being evaluated:

```bash
gh search code --extension md "agent.md" path:.github/agents
gh search code filename:server.json "io.modelcontextprotocol.registry"
gh search code filename:skills-lock.json
gh search code path:.devin/rules
```

Individual rule reviewers may clone additional relevant repositories as needed.

## Set up the previous release for comparison

To spot regressions or changes in behavior, install the previous release in a separate virtual environment:

```bash
uv venv ~/tmp/skillsaw-audit/venv-<last>
uv pip install --python ~/tmp/skillsaw-audit/venv-<last>/bin/python skillsaw==<last>
```

Name the executable on each side, or both scans run the development checkout:

```bash
~/tmp/skillsaw-audit/venv-<last>/bin/skillsaw lint <repo> --no-custom-rules --format json -v --fail-on info --no-baseline
.venv/bin/skillsaw lint <repo> --no-custom-rules --format json -v --fail-on info --no-baseline
```

Comparing results helps identify new false positives (findings on unchanged files that shouldn't be there) and verifies intended fixes.
