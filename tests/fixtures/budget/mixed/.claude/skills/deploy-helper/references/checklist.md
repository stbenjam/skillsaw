# Release Checklist

Complete every item before promoting a build to production.

- [ ] CI green on the release commit, including the nightly integration run.
- [ ] Database migrations applied to staging and verified reversible.
- [ ] Feature flags for unfinished work are off in production.
- [ ] On-call engineer is aware a deploy is going out.
- [ ] Error budget has headroom — check the SLO dashboard.
- [ ] Release notes drafted and linked in the deploy ticket.
