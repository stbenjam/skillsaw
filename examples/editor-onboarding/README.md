# Publisher onboarding: edit → diagnostic → fix → CI

This small Agent Skills repository ships a release-notes skill, its reference
checklist, root lint configuration and a GitHub Actions workflow. It starts
with zero findings and uses the same skillsaw engine in the editor and CI.

1. [Install the VS Code pilot](https://github.com/stbenjam/skillsaw/tree/main/editors/vscode#install) and set
   `skillsaw.executable` to the installed CLI. Copy this entire directory,
   including its dotfiles, outside the skillsaw checkout and open the copy as
   a VS Code workspace. For example, from the skillsaw repository root:

   ```sh
   cp -R examples/editor-onboarding /tmp/skillsaw-publisher
   code /tmp/skillsaw-publisher
   ```

2. Trust the copy. Open [the skill](skills/release-notes/SKILL.md), change line 2
   from `name: release-notes` to `name: Release_Notes`, and save. The Problems
   panel reports `agentskill-name` at line 2 as an error. The CLI likewise
   exits 1. If the panel is empty, run **skillsaw: Lint Workspaces** and check
   **skillsaw: Show Output** for executable or configuration errors.

3. In a terminal with the same CLI on PATH, from the copy's root, preview and
   apply the safe name repair:

   ```sh
   skillsaw fix --dry-run .
   skillsaw fix .
   skillsaw lint --format json --verbose .
   ```

   Use the absolute `skillsaw.executable` path in place of `skillsaw` if it
   is not on PATH. Review the change: the name is `release-notes` again.
   Run **skillsaw: Lint Workspaces** to clear the editor finding. The JSON
   report has no violations and the CLI exits 0. The extension applies no
   automatic edits.

4. Commit the clean copy to a repository you publish on GitHub. Its
   [.github/workflows/lint.yml](.github/workflows/lint.yml) uses the existing
   skillsaw Action at a pinned source commit. That action installs skillsaw
   from its own checkout and runs it against the publisher repository root.
   No new action or service is needed. The root `fail-on: warning` policy
   applies in both places. Custom rules are disabled in this CI workflow;
   the fixture needs none. A future commit reintroducing the bad name fails
   this job.

The [root config](.skillsaw.yaml) also excludes `drafts/**` and includes
[publishing guidance](handbook/publishing.md) through `content-paths`.
Save that config to refresh diagnostics after changing a policy. These
choices demonstrate that the editor uses the CLI's repository configuration,
including content outside conventional agent directories.

The walkthrough is regression-tested by `tests/test_editor_onboarding.py`
and the pilot's real extension-host test. The checked-in fixture stays clean;
tests introduce the bad name only in temporary copies.
