## Issue Triage Verdict

**Recommendation:** {{RECOMMENDATION}}

<!--
RECOMMENDATION — pick exactly one, keep the emoji:
  🛠️ FIX — REPRODUCED       a real defect you reproduced/confirmed; skillsaw should fix it
                            (a genuinely wrong or missing doc counts as FIX too)
  ✨ IMPLEMENT — GOOD IDEA   an in-scope feature worth building into skillsaw core
  🔌 PLUGIN                  in skillsaw's domain but niche/single-vendor — belongs in a
                            rule plugin, not core (link https://skillsaw.org/plugins/)
  ⛔ REJECT                  out of scope, not reproduced, works-as-intended, invalid,
                            duplicate, or answered
-->

> {{VERDICT_LINE}}
<!-- One sentence a maintainer can act on at a glance: the call + the single most
     important reason. Must stand on its own. -->

---

### Summary

{{SUMMARY}}
<!-- 3–4 plain-language sentences: what the issue asks, whether its claims hold up against
     the code, and why this recommendation. Save the evidence for the details below. -->

---

<details>
<summary><b>What I checked & enriched details</b></summary>

<br>

**What I checked**

{{EVIDENCE}}
<!-- Commands run, `file:line` references, repro attempts, related-issue searches. -->

**Enriched details**

{{ENRICHMENT}}
<!--
As applicable:
- Minimal reproduction (config + input + command + observed vs expected)
- Locus: rule ID + `file:line` (or "n/a" with why)
- Verified against: <version/commit>; reproduces on main: yes/no
- Related: #N (duplicate), PR #M (in progress)
-->

**Suggested labels:** {{LABELS}}
<!-- Recommend only; do not apply. e.g. bug, enhancement, documentation, duplicate, needs-info, wontfix. -->

</details>

---

<sub>🤖 Advisory triage by [skillsaw-issue-triage](https://github.com/stbenjam/skillsaw/tree/main/.apm/skills/skillsaw-issue-triage) — a recommendation for a maintainer, not a decision. Labels and closes are suggestions only.</sub>
