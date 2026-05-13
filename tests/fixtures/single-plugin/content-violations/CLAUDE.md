# Project Guidelines

Move fast and ship features daily.

<!-- skillsaw-assert content-redundant-with-tooling -->
Use 2 spaces for indentation in all files.
Use single quotes for JavaScript strings.
Set the maximum line length to 80 characters.
Format all files with prettier before saving.
Run eslint on every JavaScript file.
Check for unused variables in all functions.
Remove dead code from every module.
Place test fixtures in the test directory.
Sort imports alphabetically in every file.
Add type annotations to all function parameters.
Use const for all variables that are not reassigned.
Prefer arrow functions over function expressions.
Destructure objects when accessing multiple properties.
Use template literals instead of string concatenation.
Add semicolons at the end of every statement.
Use strict equality checks in all comparisons.
Avoid nested ternary expressions in all code.
Handle all promise rejections with catch blocks.
Validate all function arguments at entry points.
Log errors to the centralized logging service.
Use meaningful variable names throughout the code.
Document all exported functions with JSDoc comments.
Pin dependency versions in package.json exactly.
Run unit tests before every commit.
Check test coverage after every change.
Lint all markdown files before committing.
Validate YAML files with yamllint.
Run security scans weekly on all dependencies.
Update changelogs after every release.
Tag releases with semantic version numbers.
Create feature branches for every new feature.
Squash commits before merging to main.

<!-- skillsaw-assert content-critical-position -->
CRITICAL: Never deploy directly to production without approval.

Review all pull requests within 24 hours.
Assign at least two reviewers to every PR.
Run integration tests in CI for every branch.
Deploy to staging before every production release.
Monitor error rates after every deployment.
Roll back if error rates exceed the baseline.
Set up alerts for latency spikes in production.
Check dashboard metrics every morning.
Rotate API keys every 90 days.
Encrypt all sensitive data at rest.
Use HTTPS for all external API calls.
Sanitize all user inputs before processing.
Validate email addresses with regex patterns.
Normalize phone numbers to E.164 format.
Parse dates using the ISO 8601 standard.
Store timestamps in UTC in the database.
Add database indexes on frequently queried columns.
Use connection pooling for all database access.
Set query timeouts for all database operations.
Cache frequently accessed data in Redis.
Invalidate caches after every write operation.
Use pagination for all list API endpoints.
Rate limit all public API endpoints.
Compress API responses with gzip encoding.
Add CORS headers to all API responses.
Return proper HTTP status codes from all endpoints.
Document all API endpoints with OpenAPI specs.
Version all API endpoints with URL prefixes.
<!-- skillsaw-assert content-tautological -->
Write comprehensive tests for every new feature.
Test edge cases for all input validation.
Mock external services in unit tests.
Use fixtures for database test data.
Clean up test data after every test run.
Measure code coverage for all modules.
Enforce minimum 80 percent test coverage.
Run load tests before major releases.
Profile memory usage in long-running processes.
Optimize database queries that exceed 100ms.
Batch write operations for bulk data imports.
Use streaming for large file downloads.
Implement retry logic with exponential backoff.
Set circuit breakers for all external dependencies.
Log request and response bodies for debugging.
Redact sensitive fields in all log entries.
Track request latency with distributed tracing.
Archive old logs after 30 days.
Back up the database daily to offsite storage.
Test disaster recovery procedures quarterly.
Document the on-call runbook for every service.
Notify the team channel when deployments start.
Post deployment summaries after every release.
<!-- skillsaw-assert content-hook-candidate -->
Always run lint before committing every change.
Use meaningful commit messages for every change.
Follow the branch naming convention for all branches.
Add integration tests for every new endpoint.
Validate all configuration files on startup.
Handle timeout errors with retry logic.
Log all authentication failures to the audit trail.
Use environment variables for all secrets.
Configure the CI pipeline to run on every push.
Deploy feature flags through the control panel.
Build Docker images with multi-stage builds.
Test rollback procedures before every major release.
Review database migrations before applying them.
Set connection timeouts on all HTTP clients.
Verify SSL certificates in all environments.
Update the changelog for every user-facing change.
Remove unused imports from every module.
Format all SQL queries with parameterized inputs.
Check for memory leaks in long-running services.
Define error codes for all API error responses.
Implement health check endpoints for every service.
Export metrics from all background workers.
Validate webhook payloads with HMAC signatures.
Configure log rotation for all services.
Use structured logging in all new services.
Test all error handling paths in critical flows.
Handle graceful shutdown in all worker processes.
Verify backup integrity after every backup job.
Set resource limits on all container deployments.
Ensure all API responses include request IDs.
Follow semantic versioning for all library releases.
Push tags after every version bump.
Merge feature branches within one sprint.
Install security patches within 48 hours.
Rebase feature branches on main daily.

Never use var in JavaScript code.

<!-- skillsaw-assert content-banned-references -->
Use claude-3-opus for better code review results.

<!-- skillsaw-assert content-placeholder-text -->
TODO: add more configuration examples for the deployment pipeline.

<!-- skillsaw-assert content-broken-internal-reference -->
See [deployment docs](docs/missing-deployment-guide.md) for more details.

<!-- skillsaw-assert content-unlinked-internal-reference -->
See ./docs/architecture-overview.md for the system design.
