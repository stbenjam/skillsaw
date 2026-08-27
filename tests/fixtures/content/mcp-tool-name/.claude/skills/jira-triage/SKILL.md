---
name: jira-triage
description: Triage incoming Jira tickets for the acme-platform board — classify, label, and assign. Use when the sprint backlog has unclassified issues.
---

# Jira Triage

Triage every unclassified ticket on the acme-platform board in one pass.

## Steps

<!-- skillsaw-assert content-mcp-tool-name -->
1. List the untriaged tickets with mcp__plugin_jira_atlassian__searchJiraIssuesUsingJql
   using the JQL `project = ACME AND labels IS EMPTY ORDER BY created ASC`.
<!-- skillsaw-assert content-mcp-tool-name -->
2. For each ticket, read the full body with `mcp__plugin_jira_atlassian__getJiraIssue`
   and decide whether it is a bug, a feature, or a support question.
3. Apply the matching label with `editJiraIssue`. Bugs get `kind/bug`,
   features get `kind/feature`, and support questions get `kind/question`.
4. Assign bugs to the on-call engineer named in the sprint rotation and leave
   everything else unassigned.

## Stop conditions

Stop when the JQL query returns no rows. Report the count of tickets you
labelled, broken down by label, and list any ticket you could not classify.
