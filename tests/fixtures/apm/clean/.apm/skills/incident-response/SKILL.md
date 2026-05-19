---
name: incident-response
description: Triage and respond to production incidents
compatibility: Requires kubectl, aws cli, and PagerDuty access
metadata:
  author: sre-team
  version: "1.2"
---

# Incident Response

Guide the on-call engineer through incident triage, investigation,
and resolution for production issues.

## When to Use This Skill

Use when a PagerDuty alert fires or a user reports a production issue
that needs immediate investigation.

## Implementation Steps

### Step 1: Gather Context

Collect information about the incident:
- Alert source and timestamp
- Affected service and environment
- Error rate and latency changes from monitoring

### Step 2: Investigate

Run diagnostic commands:
```bash
kubectl get pods -n production | grep -v Running
kubectl logs -f deployment/$SERVICE -n production --since=10m
aws cloudwatch get-metric-statistics --namespace Custom --metric-name ErrorRate
```

### Step 3: Identify Root Cause

Correlate findings with recent changes:
```bash
git log --oneline --since="2 hours ago"
kubectl rollout history deployment/$SERVICE -n production
```

### Step 4: Mitigate

If a recent deployment is the cause, roll back:
```bash
kubectl rollout undo deployment/$SERVICE -n production
```

### Step 5: Document

Create an incident report with:
- Timeline of events
- Root cause analysis
- Resolution steps taken
- Action items to prevent recurrence
