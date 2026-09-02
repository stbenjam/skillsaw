# The critic

One Opus subagent, launched after `CHECKLIST.md` exists, with the reports
directory, the prior-fixes file, the development rules, and the maintainer's
recorded decisions from this session. It is told to attack, not approve.

Required work:

1. Reproduce every Tier 1 item on a fixture or corpus repository. An item
   that does not reproduce is demoted; an item that also fails on `main` or
   on the last release is a bug, not a regression, and ranks accordingly.
2. Attack every proposed fix: does it trade a false positive for a worse
   false negative, does it contradict a deliberate earlier decision, is it
   really the size claimed, would deletion beat qualification?
3. Attack the prioritization by the three questions, weighing ecosystem
   size, but treating a 100% false-positive rate on a new ERROR rule as a
   bad first impression whatever the ecosystem.
4. Hunt for what the audit missed: read the commit log since the tag for
   user-visible changes with no checklist item, and lint five to ten corpus
   repositories with `-v --fail-on info` looking at the top-volume rules.
5. Judge the release call and name any behavior change that must appear in
   the release notes before the tag.

It returns an approved Tier 1 of at most ten, each with the exact fix it
endorses, the tests it needs, and the false-negative risk it accepts, plus an
ordered "next batch" list. Ship the approved list, in its order.

Expect the critic to rewrite fixes. In the 0.20.0 sweep it replaced two,
promoted three findings nobody had ranked, and set a release-notes gate on
the tag; a checklist that comes back unchanged was not attacked.
