# Deploy

Deploy the current branch to the staging environment.

## Steps

1. Run the test suite and stop if anything fails.
2. Build the release artifact with `make build`.
3. Push the artifact to the staging bucket.
4. Announce the deploy in the team channel.
