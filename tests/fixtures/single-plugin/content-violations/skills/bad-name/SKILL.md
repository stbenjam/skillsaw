---
name: bad-name
description: A skill for testing content section length violations
metadata:
  openclaw:
    os: "invalid"
    requires:
      bins: "not-a-list"
---

# Bad Name Skill

## Oversized Section

This section is intentionally very long to trigger the content-section-length rule.
The rule fires when a single markdown section exceeds 500 tokens, which is approximately
2000 characters. To reliably trigger this threshold, the section must contain enough prose
to push past the limit. Each sentence adds roughly 50-100 characters, so approximately
twenty to thirty sentences should be sufficient to reach the required length.

Start by gathering all available data from the configured data sources. Connect to each
database instance using the connection parameters stored in the environment variables.
Execute the data extraction queries against each table in the schema. Transform the raw
data into the normalized format expected by downstream consumers. Validate each record
against the schema definition before writing to the output buffer. Handle any schema
violations by logging the error and skipping the record. Aggregate the validation results
into a summary report for the user. Write the transformed data to the output directory in
the configured format. Compress the output files if the total size exceeds the threshold.
Upload the compressed archives to the configured cloud storage bucket. Update the metadata
catalog with the new data version and timestamp. Notify the downstream consumers that new
data is available for processing. Monitor the consumer acknowledgment within the timeout
period. Retry failed notifications up to three times with exponential backoff between
attempts. Log all retry attempts with the consumer identifier and failure reason.
Generate a final execution report with timing metrics for each step. Include the record
counts, error rates, and throughput measurements in the report. Store the execution
report alongside the data files in cloud storage. Clean up any temporary files created
during the extraction and transformation phases. Release all database connections back
to the connection pool. Send the execution summary to the monitoring dashboard. Archive
the log files for the current run in the designated log storage location. Verify the
archival was successful by reading back the first and last entries. Update the job
scheduler with the completion status and next scheduled run time. Record the total
elapsed time and peak memory usage in the metrics system. Mark the pipeline run as
complete in the orchestration database. Trigger any dependent pipelines that were
waiting on this data refresh. Validate that the triggered pipelines started within
their expected launch window. Report any pipeline launch failures to the operations
channel for manual investigation. End the execution by releasing the distributed lock
on the pipeline configuration. Confirm the lock release was successful to prevent
deadlocks in subsequent runs of this pipeline.
