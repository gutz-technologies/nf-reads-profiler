# Enable G5 live queue counts in the benchmark dashboard

## Task

Extend the existing queue-depth monitoring Lambda to include the three G5 benchmark queues. Preserve monitoring of every currently configured queue. Implement and verify on AWS; do not launch jobs or alter Batch queues, compute environments, instance pools, or the active benchmark.

- Account: `730883236839`
- Region: `us-east-2`
- Lambda: `nf-reads-profiler-batch-queue-depth`
- Environment variable: `QUEUE_ARNS` (comma-separated full queue ARNs)
- Schedule: `nf-reads-profiler-batch-queue-depth-schedule`, expected `rate(1 minute)`
- Dashboard: `nf-reads-profiler-graviton-benchmark-20260918`
- Repository: `/home/ubuntu/github/nf-reads-profiler`
- Monitoring source: `infra/batch-dashboard.yaml`, resource `BatchQueueDepthFunction`

Add these exact values, without duplicates:

```text
arn:aws:batch:us-east-2:730883236839:job-queue/spot-short-g5
arn:aws:batch:us-east-2:730883236839:job-queue/spot-metaphlan-g5
arn:aws:batch:us-east-2:730883236839:job-queue/spot-humann-g5
```

## Evidence and uncertainty

The repository template configures only the four original queues (spot-queue, spot-metaphlan, spot-humann, spot-medi). It polls all five live statuses with pagination and publishes even zero counts. Its execution role already permits `batch:ListJobs` on `*` and `cloudwatch:PutMetricData` in `AWS/Batch`.

The previous agent could not inspect the deployed Lambda or EventBridge rules because the head-node role returned AccessDenied. Therefore verify the deployed configuration, code, role and schedule before editing; the missing G5 list is inferred from the template, not confirmed from live Lambda configuration. A VM using the same role will need an authorized AWS identity with the relevant permissions; changing machines alone does not resolve AccessDenied.

## Implementation

1. Verify caller account and region. Read the live Lambda configuration, code and schedule/target. Verify all three queues exist; they may be disabled and empty, which is fine.
2. Save a private backup of the current configuration and environment. Do not commit arbitrary environment values or credentials.
3. Merge the three ARNs into the current `QUEUE_ARNS`, retaining all existing entries and every other environment variable. Lambda environment updates replace the entire variables map: do not send only `QUEUE_ARNS` if other keys exist.
4. Apply a targeted `update-function-configuration` using a JSON input file and the read `RevisionId` to protect against concurrent edits. If the revision changed, reread and merge. If the queues are already present, skip the write and diagnose telemetry instead.
5. Wait for `LastUpdateStatus=Successful`. Keep the one-minute schedule and existing timeout unless observed failures justify a separate fix. Seven queues produce 35 metrics and at least 35 ListJobs requests per invocation; pagination can add requests. Check duration and throttling rather than increasing polling frequency.
6. Make the configuration durable in `infra/batch-dashboard.yaml`: retain the four imported queue ARNs and add an optional parameter for additional queue ARNs (default empty), composing the environment value without dropping existing entries. Record the three G5 ARNs as the intended parameter value for this deployment. Validate the template. A direct Lambda update creates CloudFormation drift until reconciled; document this explicitly. Do not deploy `infra/batch-stack.yaml`. If deploying the observability stack to reconcile, inspect its change set first and preserve its current parameters and unrelated resources.
7. After telemetry is verified, edit only the warning text in the live benchmark dashboard to indicate G5 telemetry is connected. Fetch the current dashboard first so any user layout edits survive. Update the local dashboard JSON and README warning too.

## Verification / acceptance

- Live `QUEUE_ARNS` contains the previous set plus the three G5 queues, with no duplicates; other environment variables are unchanged.
- Scheduled invocation succeeds for at least two successive one-minute intervals, with no Lambda errors, timeouts, throttling or access-denied messages. Use scheduled invocations; at most one manual invocation if needed, not a retry loop.
- CloudWatch contains fresh datapoints for each of the three G5 queue ARNs for:
  - `SubmittedJobCount`
  - `PendingJobCount`
  - `RunnableJobCount`
  - `StartingJobCount`
  - `RunningJobCount`
- Namespace is exactly `AWS/Batch`; dimension is exactly `JobQueue=<full queue ARN>`; unit is Count. Query datapoints with `get-metric-data` or `get-metric-statistics`, allowing several minutes for ingestion. Do not rely solely on metric discovery, which can lag.
- Zero-valued datapoints for empty/disabled queues count as success; missing datapoints do not. Do not enable G5 or submit a job merely to test telemetry.
- Compare live counts against paginated `batch list-jobs` for corresponding queue/status near the sample time; small differences are expected if jobs change state between calls.
- Confirm fresh datapoints still arrive for the previously monitored queues, and G5 dashboard live-count series render. The dashboard displays four of the five live statuses; Submitted is published but not currently plotted.
- Preserve Maximum for depth gauges and Sum for success/failure counters. Success/failure counters come from the separate event-driven `nf-reads-profiler-batch-metrics` Lambda; the template covers all queues automatically. Do not invent completion datapoints for idle queues.

## Rollback and handoff

If the update causes polling failures, restore only the previous `QUEUE_ARNS` value while preserving any concurrent changes to other environment keys, using a fresh RevisionId. Revert any associated source changes as appropriate. Do not modify Batch compute resources.

Report the UTC update time, before/after queue lists, verification datapoint timestamps and values, Lambda duration/errors, source changes, and whether CloudFormation drift remains. Include the dashboard link:

https://us-east-2.console.aws.amazon.com/cloudwatch/home?region=us-east-2#dashboards:name=nf-reads-profiler-graviton-benchmark-20260918
