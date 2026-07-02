---
name: deploy-staging
description: Deploy the application to the staging environment, including building artifacts, running the pre-deployment validation suite, uploading the artifacts to the staging bucket, rolling the staging cluster, verifying health checks, and posting a deployment summary to the team channel. Use when the user asks to deploy, ship, or release to staging.
---

# Deploy Staging

Deploy the application to the staging environment.

## Steps

1. Build the release artifacts with the standard build command.
2. Run the pre-deployment validation suite.
3. Upload the artifacts and roll the staging cluster.
4. Verify health checks and post a summary to the team channel.

<!-- The description above is 343 characters; integration tests assert on this length. -->
