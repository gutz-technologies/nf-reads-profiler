# Graviton comparison

G4 round started **2026-09-18 15:38:48 UTC**, persistent screen session
`graviton-bench-g4-20260918`. Five count_reads jobs and get_software_versions
were submitted to Batch at 15:38:57 UTC. Logs: `execution/g4/`. G5 has not started.
G4 stopped at **2026-09-18 15:43:08 UTC**, exit 1: clean_reads (10m)
was killed for exceeding its 4 GiB memory allocation. Failed attempt logs are preserved locally and in S3 under execution/g4-failed-attempt1/.
Cleaning now requests 16 GiB initially and 32 GiB on retry for both generations.
G4 restarted **2026-09-18T16:06:49Z**, run graviton_bench_g4_20260918_retry2,
screen graviton-bench-g4-20260918-retry2, without resume. No completed round yet.
The earlier memory fix exists in commit 364b1a4 but was absent from this branch.

Five caps per run: 100k, 300k, 1m, 3m, 10m. Same paired source sample
`7-690764-1-4` for both generations. Its published cohort read count is
18,520,758 R1 reads (read on 2026-09-18); each run also executes count_reads.
The caps use fastp reads_to_process, not post-filtered read counts.

From the repository root, in screen/tmux, run G4 then G5:

```bash
bash benchmarks/graviton/run-g4.sh
bash benchmarks/graviton/run-g5.sh
```

Do not add `-resume`. Only start G5 after G4 finishes. Both runs execute
profile_taxa and profile_function, plus normal cleaning/reporting. MEDI and
StrainPhlAn are disabled. Each profiler retains its existing process-specific
CE pair. G5 small glue jobs (count_reads, get_software_versions, MULTIQC,
combine_metaphlan_tables, combine_humann_taxonomy_tables, split_stratified_tables)
use spot-short-g5. G5 cleaning also uses spot-short-g5; G4 cleaning uses spot-queue. Larger table
jobs retain spot-queue for both runs.

G5 test CEs/queues must be enabled before its run. On 2026-09-18 all four
profiling CEs were VALID, requested zero capacity, and the G5 pair was disabled.
No resources were enabled or benchmark jobs submitted during preparation.

Outputs and timestamped traces:
- `s3://gutz-nf-reads-profilers-runs/results/graviton-benchmark-g4-20260918/`
- `s3://gutz-nf-reads-profilers-runs/results/graviton-benchmark-g5-20260918/`

Work paths are also separate under the workdir bucket's `benchmarks/` prefix.
Trace includes native Batch job IDs, queue, runtime and requested resources.
Each profiler requests 16 vCPUs and internally uses 32 threads, identically
on both generations; existing memory settings and start gates are retained.

Report task runtime per tier for both profilers, then obtain the two run costs
from the billing dashboard after billing data populates. Record start/end UTC
and the actual worker instance IDs/types for billing attribution. Project names
in S3 do not by themselves create billing tags: verify the dashboard can isolate
the test workers/time windows and include shared spot-queue overhead consistently.
Avoid unrelated jobs during those windows; do not call a whole-account total the
benchmark cost. No custom billing-tag activation or dashboard change was made.

Selected pools (all us-east-2 AZs; existing G4 pools unchanged):
- HUMAnN G5: c9g.24xlarge, c9g.48xlarge.
- MetaPhlAn G5: c9g.24xlarge, c9g.48xlarge, m9gd.metal-48xl.
- Short G5: r9g.medium (1 vCPU / 8 GiB), m9g.large (2 / 8 GiB),
  r9g.large (2 / 16 GiB), m9g.2xlarge (8 / 32 GiB), r9g.2xlarge
  (8 / 64 GiB). The larger types accommodate cleaning at the current 16/32-GiB
  task allocation (including host overhead). Isolated CE/queue spot-short-g5; 32-vCPU ceiling,
  zero minimum/desired capacity, all three existing us-east-2 subnets,
  SPOT_PRICE_CAPACITY_OPTIMIZED, existing 50% bid setting, short-job launch
  template pinned to version 19. Created outside CloudFormation and disabled
  until launch. Current short tasks request 2 CPUs / 4 GiB unchanged, so
  r9g.medium is included but can only serve future 1-CPU jobs.

These three types have cheapest quoted rates below $0.007/vCPU-hour; this is a
selection criterion, not an enforced price cap in every AZ. Earlier placement
scores were for broader pools and do not apply to these narrowed pools.

Preflight: both configs resolved with Nextflow 26.04.2; a local fake-fastp
harness verified the emitted five cap arguments for both paired/single-end
inputs and the ordinary params.nreads fallback. This checks wiring, not real
fastp output or AWS execution. Both source S3 objects were readable and the G4
queues were ENABLED/VALID. Evidence is in preflight/.

## Live and archived logs

The launchers retain console.log and nextflow.log under execution/g4/ or
execution/g5/. Watch with `tail -F benchmarks/graviton/execution/g4/console.log`.
After Nextflow exits (success or failure), the launcher copies that directory
including timestamps and exit-code.txt to the run's S3 results prefix under
execution/g4/ or execution/g5/. Reports/traces already go to reports/ in S3.
An upload failure is printed and returns nonzero; local logs remain available.
Host loss or forced termination can prevent the final upload.

Historical fastp memory audit: [history/report.md](history/report.md).

Memory policy updated after historical audit: future launches use accuracy 3,
8 GiB initially / 16 GiB on retries. The already-running G4 retry2 loaded
16/32 GiB before this edit; its resolved config is preserved as
preflight/g4-retry2-launched.config. A subsequent G5 launch uses 8/16 GiB.
Record this cleaning-allocation difference in the cost comparison; profiler
resource requests remain identical. The current G4 process was not restarted.
