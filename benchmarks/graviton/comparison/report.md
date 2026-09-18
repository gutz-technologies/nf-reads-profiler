# Graviton benchmark: runtime and cost per sample

G4 and G5 profiling complete: all ten profiling tasks succeeded in each run. G5 downstream merging/conversion is still pending at this update. Five read caps from the same source sample, one run per generation. These observations are not replicated estimates of variability.

## Profiling runtime

Execution time uses exact Nextflow `realtime` milliseconds from the G4 HTML report and saved G5 `.command.trace` files, excluding queue waits. Positive time saved means G5 is faster; speedup is G4/G5.

| Process | Reads | G4 runtime | G5 runtime | Time saved | G5 speedup |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| profile_taxa | 100k | 2m 02.5s | 1m 46.6s | +15.9s | 1.149× |
| profile_taxa | 300k | 2m 07.7s | 1m 51.4s | +16.3s | 1.147× |
| profile_taxa | 1m | 2m 26.9s | 1m 58.4s | +28.5s | 1.241× |
| profile_taxa | 3m | 2m 58.9s | 2m 30.0s | +28.9s | 1.193× |
| profile_taxa | 10m | 4m 51.5s | 4m 12.0s | +39.4s | 1.157× |
| profile_function | 100k | 2m 45.2s | 2m 22.6s | +22.6s | 1.158× |
| profile_function | 300k | 3m 35.8s | 3m 05.4s | +30.4s | 1.164× |
| profile_function | 1m | 5m 15.1s | 4m 27.4s | +47.7s | 1.178× |
| profile_function | 3m | 10m 05.7s | 8m 43.7s | +82.0s | 1.157× |
| profile_function | 10m | 27m 21.2s | 23m 00.3s | +261.0s | 1.189× |

## Runtime-based cost estimate

Use actual worker type, AZ, and the Spot price effective during each task. Integrate price changes over Batch `startedAt` → `stoppedAt`, then multiply by requested vCPUs / worker vCPUs. This interval includes container work beyond the timed command. Include every attempt for cost, including failures; speed uses successful execution.

This CPU-share allocation is an estimate, not an AWS per-job bill or a fully packed-host forecast. It excludes unused capacity, host startup/shutdown, image pulls before RUNNING, EBS, S3 and other services. Memory can limit packing: MetaPhlAn requests 36 GiB for 16 CPUs, so CPU-only allocation can understate its capacity cost on compute-optimized hosts. Show actual fleet cost separately.

Verified G4 HUMAnN worker: `i-035550f957f0d940c`, `m8g.metal-24xl`, 96 vCPUs / 384 GiB, `us-east-2c`, Spot **$0.4308/hour** throughout the task interval. All five tasks used this worker. G4 MetaPhlAn used separate instance `i-0d6f195921644a5d1`, also m8g.metal-24xl, 96 vCPUs / 384 GiB, us-east-2c, $0.4308/hour. Recovered through CE Auto Scaling launch/termination history and its Spot request; it was the only worker in that CE during all five jobs (16:17:52–16:23:01 UTC).

Verified G5 workers: HUMAnN `i-00c747c665b5f5996`, c9g.24xlarge, 96 vCPU / 192 GiB, us-east-2c, $0.6594/h; MetaPhlAn `i-06683e5607459a50f`, c9g.48xlarge, 192 vCPU / 384 GiB, us-east-2a, $1.3922/h. Prices were constant during profiling. All five tasks per profiler used its listed worker; no G5 profiling retries.

| Reads | G4 HUMAnN | G5 HUMAnN | HUMAnN cost change | G4 MetaPhlAn | G5 MetaPhlAn | MetaPhlAn cost change | G4 both | G5 both |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 100k | $0.00346 | $0.00458 | +32.6% | $0.00320 | $0.00456 | +42.6% | $0.00666 | $0.00915 |
| 300k | $0.00443 | $0.00583 | +31.5% | $0.00310 | $0.00504 | +62.7% | $0.00753 | $0.01087 |
| 1m | $0.00644 | $0.00836 | +29.8% | $0.00405 | $0.00559 | +37.9% | $0.01049 | $0.01395 |
| 3m | $0.01223 | $0.01619 | +32.3% | $0.00450 | $0.00565 | +25.6% | $0.01673 | $0.02184 |
| 10m | $0.03293 | $0.04240 | +28.8% | $0.00616 | $0.00865 | +40.4% | $0.03909 | $0.05105 |

Cost change = G5 − G4 dollars; percent change = 100 × (G5/G4 − 1). Cost savings = G4 − G5. Both-profiler cost is the sum of their estimates. Do not sum parallel profiler runtimes and call it elapsed sample turnaround.

## End-to-end timing and billed cost

- G4 successful launch: 2026-09-18 16:06:49 UTC; finish: 17:00:37 UTC; full pipeline elapsed: **53m48s**. Last profiling task completed around 16:47 UTC; merging/reporting continued afterward.
- G5 launch: 17:02:23 UTC; completion and elapsed time pending.
- Add per-sample profiling-ready turnaround (both profilers complete) and queue delay alongside execution speed. Pipeline elapsed includes counting, cleaning, waiting, profiling, merging, and reporting.
- Billing-dashboard reconciliation: pending. CloudWatch operational metrics typically arrive within a few minutes; Cost Explorer/billing usage generally refreshes at least daily and can lag beyond 24 hours. Inspect the reported refresh/coverage window; first visible cost is not necessarily complete.
- Reconcile EC2/EBS cost for actual worker IDs and their full lifetime, with shared-host usage allocated explicitly. Separate the earlier failed G4 attempt. Avoid attributing unrelated account/queue spend to this benchmark. Per-sample billing allocation is a model even after the fleet bill is known.
- G4 cleaning requested 16 GiB initially / 32 GiB retries; G5 uses 8/16 GiB. Accuracy is level 3 in both. This changes whole-pipeline cost comparability; profiling CPU and memory requests are unchanged.

## Remaining reconciliation

G4 MetaPhlAn placement and allocated cost are now recovered; all profiling cost estimates are populated. G5 profiling finished at 17:36:10 UTC (last Batch stop), 33m47s after launch; this is not full-pipeline completion. Full elapsed time and billing reconciliation remain pending. Regenerate after the final G5 HTML report becomes available.

Evidence and exact numerical results are stored alongside this report in `evidence/` and `task-results.csv`.

Normalized per-VM results for all five input caps and pricing scenarios for every current profiler-pool VM: [per-million.md](per-million.md).
