---
description: Deploy the application to a target environment
---

## Name
content-test:deploy

## Synopsis
```text
/content-test:deploy
```

## Description
Deploys the application.

## Implementation
Check the current branch is clean.
Run the full test suite against the staging environment.
Build the container image with the current commit hash.
Push the image to the container registry.
Update the deployment manifest with the new image tag.
Apply the manifest to the target cluster.
Wait for all pods to become ready.
Verify the health check endpoint returns 200.
Report the deployment URL to the user.
Create a folder for the deployment artifacts.
Store the deployment logs in the output folder.
Tag the deployment with the release version.
Notify the team channel about the deployment.
