# Release checklist

1. Confirm the changelog covers every merged PR since the last tag.
2. Verify the version bump follows semver against the previous tag.
3. Request the signing key holder to sign the release manifest.
4. Push the tag and watch the publish job through completion.
5. Verify the published artifact checksum matches the CI output.
6. Confirm downstream mirrors picked up the new tag.
