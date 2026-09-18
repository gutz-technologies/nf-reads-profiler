# Graviton4 versus Graviton5: simple profiling benchmark

Updated 2026-09-18. Execution setup: [benchmark configs and commands](../benchmarks/graviton/README.md).

## Two runs, ten sample cases

Use one sufficiently deep CosmosID infant sample from
`/home/ubuntu/gutz-nf-reads-profilers-runs/playbooks/cosmosid-infant.md`.
Use the same source sample on both generations.

| fastp reads_to_process | Graviton4 | Graviton5 |
|---:|---|---|
| 100,000 | Run 1 | Run 2 |
| 300,000 | Run 1 | Run 2 |
| 1,000,000 | Run 1 | Run 2 |
| 3,000,000 | Run 1 | Run 2 |
| 10,000,000 | Run 1 | Run 2 |

**5 sizes × 2 generations = 10 sample cases. Two runs.** Use the existing
fastp `--reads_to_process` mechanism (`params.nreads`) for the size cap.
The labels describe that setting, not an exact post-filtering read count.
No custom subsampling workflow, extra replicates, warm-up matrix or smoke matrix.
The five cases are wired through the benchmark samplesheet and per-task
`ext.reads_to_process` override; ordinary runs retain `params.nreads`.

## Compute

Use two CEs per profiler comparison: the existing Graviton4 CE and its
Graviton5 counterpart. Allow all of us-east-2; do not pin an AZ.

| Profiler | Run 1: Graviton4 | Run 2: Graviton5 |
|---|---|---|
| profile_function | spot-humann | spot-humann-g5 |
| profile_taxa | spot-metaphlan | spot-metaphlan-g5 |

Each run covers both profilers for its five cases. Reuse the existing
process-specific CE pairs above; no additional CEs. Keep software, databases,
CPU/memory requests and options the same between runs. Disable MEDI and
StrainPhlAn. Use separate G4/G5 output paths, `skipCompleted=false`, and no
resume of measured tasks. G5 test CEs/queues currently exist but are disabled.

## Measure and report

- **Speed:** record profile_function and profile_taxa task runtimes for each
  size from the Nextflow trace. Speedup = G4 runtime / G5 runtime.
- **Cost:** read the G4 and G5 run costs from the billing dashboard, using
  distinct run labels/time windows so the two totals can be separated.
  Wait for billing data to populate. Cost saving = 1 − G5 cost / G4 cost.
- **Report both:** one five-row runtime comparison per profiler, plus the two
  run billing totals and percentage saving. Record actual instance types used.
  Do not invent per-size billed costs if the dashboard only exposes run totals.

Next: choose a sample with enough reads, wire the five caps into the two runs,
run G4 then G5, and record runtime speedup and dashboard cost savings.
