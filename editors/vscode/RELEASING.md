# Release skillsaw for VS Code

The extension version is independent of the skillsaw CLI version. Publishing
uses GitHub Actions OIDC through Marketplace Trusted Publishing; no PAT is
stored in the repository.

## One-time setup

1. Create the `stbenjam` publisher in the
   [Marketplace dashboard](https://marketplace.visualstudio.com/manage).
2. Under that publisher's **Trusted Publishing**, create this policy:

   | Field | Value |
   | --- | --- |
   | Policy name | skillsaw VS Code releases |
   | Repository owner | stbenjam |
   | Repository | skillsaw |
   | Workflow | release-vscode.yml |
   | Environment | marketplace |

3. Configure the `marketplace` GitHub environment's protection rules as desired.
   Only the publish job receives `id-token: write`.

See Microsoft's [Trusted Publishing documentation](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#publish-with-github-actions-and-trusted-publishing).

## Release

1. Update `version` in `package.json` and the package-lock root entries, then
   describe the release in `CHANGELOG.md`. Use a stable `major.minor.patch`
   version. Update the README when behavior changes.
2. Follow the repository's pre-push checklist and run the extension checks:

   ```sh
   npm ci --ignore-scripts
   npm run lint
   npm test
   npm run test:host
   npm run package
   ```

   Run these in `editors/vscode` after installing the checkout's CLI with
   `make venv` at the repository root. Linux without a display needs
   `xvfb-run -a npm run test:host`.
3. Merge the reviewed changes to `main`.
4. Run **Release VS Code extension** manually on `main`, or push a tag matching
   the package version, such as `vscode-v0.1.0`. The workflow rejects tagged
   commits outside `main` and version mismatches. It runs tests, packages the
   extension and publishes that exact VSIX artifact.
5. Check the workflow and the
   [Marketplace listing](https://marketplace.visualstudio.com/items?itemName=stbenjam.skillsaw).
   Install the published version into a fresh VS Code profile and confirm the
   missing-CLI instructions and saved-file diagnostics.

Choose one trigger per version; Marketplace versions cannot be overwritten.
Do not create a GitHub Release for an extension tag: the repository's separate
Python release workflow publishes to PyPI on GitHub Release events.

For manual recovery, download `skillsaw-vscode-release` from the workflow and
upload its VSIX through the Marketplace dashboard. Keep the release artifact
unchanged so it matches the tested build.
