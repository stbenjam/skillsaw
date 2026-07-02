---
name: incident-investigator
description: Investigate a production incident from start to finish. Use when the user reports an outage, a spike in error rates, or asks for an incident investigation. Collects the recent deploy history, correlates it with the alert timeline, and pulls the relevant service logs for the affected window. Summarizes the most likely root causes with supporting evidence and links to the dashboards used. Prepares a draft incident report with an impact assessment, a timeline of events, and the follow-up actions the team agreed on. Posts the report to the incident channel and files tracking issues for each follow-up action so nothing is lost after the incident is closed. Keeps a record of every command it ran so the investigation can be audited or replayed later. Escalates to the on-call engineer when the evidence points at an ongoing problem rather than a resolved one. Works across the API, worker, and frontend services and understands the standard deployment topology. Never restarts services or rolls back deploys on its own; it always proposes the action and waits for confirmation. Understands maintenance windows and will not page anyone for alerts that fired inside one. Falls back to read-only analysis when it lacks credentials for a service. Reports partial findings rather than failing outright when a data source is unavailable.
---

# Incident Investigator

Investigate a production incident from start to finish.

## Steps

1. Collect the recent deploy history and the alert timeline.
2. Pull the relevant service logs for the affected window.
3. Summarize likely root causes with supporting evidence.
4. Draft the incident report and file follow-up issues.
