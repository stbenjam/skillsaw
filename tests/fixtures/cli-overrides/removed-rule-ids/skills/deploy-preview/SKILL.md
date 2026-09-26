---
name: deploy-preview
description: Deploy the current branch to a preview environment and report its URL. Use when a reviewer asks to see a pull request running before it merges.
---

# Deploy preview

1. Run `make build` and stop if the build fails.
2. Run `./scripts/deploy-preview.sh` with the current branch name.
3. Read the preview URL from the last line of the script output.
4. Post the URL as a comment on the pull request.

The preview environment is deleted automatically seven days after the last deploy.
