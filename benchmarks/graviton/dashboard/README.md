# Benchmark CloudWatch dashboard

Name: `nf-reads-profiler-graviton-benchmark-20260918`

Six queue panels: tiny / MetaPhlAn / HUMAnN, G4 then G5. Standalone dashboard; edit directly in AWS. Original dashboard unchanged.

Source: `dashboard.json`. Live depth uses Maximum; completion events use Sum, with 60-second periods. These are queue-wide, not run-filtered. No billing costs are inferred.

G5 live depth is **connected** as of 2026-09-18 16:37 UTC: `spot-short-g5`, `spot-metaphlan-g5` and `spot-humann-g5` were appended to the `nf-reads-profiler-batch-queue-depth` Lambda's `QUEUE_ARNS`, keeping the four original queues (7 total). Verified: fresh 60s datapoints in `AWS/Batch` for all five statuses on each G5 queue, zero-valued while the G5 queues are DISABLED. Lambda duration ~1.9-2.3 s against a 60 s timeout, no errors or throttling.

This was applied with a direct `update-function-configuration`, so the monitoring stack (`nf-reads-profiler-monitoring`) is **in CloudFormation drift** on `BatchQueueDepthFunction.Environment` until reconciled. `infra/batch-dashboard.yaml` now carries an optional `AdditionalQueueArns` parameter; deploying that template with

    AdditionalQueueArns=arn:aws:batch:us-east-2:730883236839:job-queue/spot-short-g5,arn:aws:batch:us-east-2:730883236839:job-queue/spot-metaphlan-g5,arn:aws:batch:us-east-2:730883236839:job-queue/spot-humann-g5

reproduces the live value and clears the drift. A deploy of the monitoring stack *without* that parameter would revert G5 telemetry to the four original queues.

Success/failure publisher is configured for all queues in the repository template. Blank data is not zero.
