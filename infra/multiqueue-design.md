# Design: per-database Batch queues (`multiqueue`)

Status: **in progress** — `spot-metaphlan` being implemented on the `multiqueue`
branch. `spot-humann` and `spot-medi` are designed here but **not yet built**.

## Problem

Today every Batch job runs on one queue (`spot-queue`) backed by a single
custom AMI that bakes **all** databases (~65 GiB) into the image. That AMI is
expensive to maintain (Packer rebuild on every DB bump) and, without Flexible
Snapshot Restore (FSR, billed per snapshot per AZ), its EBS snapshot lazy-loads
at ~6 MB/s — ~95 min before a worker is useful (issue I24). FSR fixes the boot
latency but costs money the whole time it's enabled.

Most jobs don't need most of the DBs. `profile_taxa`/StrainPhlAn need only
MetaPhlAn vJan25; `profile_function` needs the HUMAnN set; MEDI needs the
Kraken hash; everything else (count/clean/combine/multiqc) needs **no** DB.

## Principle: one queue per staged database

The queue boundary *is* the database boundary. Each special queue uses a **thin,
stock AMI** and copies only its own DB from S3 at boot (`aws s3 cp --recursive`).
No FSR, no Packer rebuilds, no lazy-load penalty — just a one-time copy per
instance, amortized across every job that lands on it.

| Workload | Processes routed | Database | Queue | Fallback |
|----------|-----------------|----------|-------|----------|
| Taxa / strain | `profile_taxa`, `STRAINPHLAN:*` | vJan25 (~44 GB) | `spot-metaphlan` | spot only |
| Function | `profile_function` | chocophlan + uniref + utilitymap + vOct22 | `spot-humann` *(future)* | spot only |
| Food | `MEDI_QUANT:*` | Kraken hash | `spot-medi` *(future)* | spot only |
| Everything else | count/clean/combines/multiqc | none | `spot-queue` (existing) | + on-demand |

`spot-queue` stays the **default** (`process.queue` in `conf/aws_batch.config`)
and keeps the on-demand fallback CE. It carries the light, DB-free glue. The
per-tool queues are spot-only — a strain/function/food job that loses its spot
instance just retries; none of them are latency-critical.

Naming is **by workload, not by DB version** (`spot-metaphlan`, not
`spot-vJan25`) so the name survives DB bumps.

## CloudFormation convention

Every per-DB queue is a copy-paste block keyed on one `<Workload>` token, so
adding the next one is mechanical:

```
Param:           MaxvCPUs<Workload>            # e.g. MaxvCPUsMetaphlan
LaunchTemplate:  <Workload>WorkerLaunchTemplate
ComputeEnv:      Spot<Workload>ComputeEnvironment   (Type: SPOT)
JobQueue:        <Workload>Queue               (JobQueueName: spot-<workload>)
```

Shared across all of them:

- **`ThinEcsAmiId`** — one param, the stock AL2023 ECS ARM64 image resolved from
  the AWS public SSM parameter
  `/aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended/image_id`.
  Nothing to rebuild; always current.
- The existing `EcsInstanceProfile`, `SpotFleetRole`, subnets, `BatchComputeSG`.
- `EcsInstanceRole` already has read on `DbSourceBucket` (`cjb-gutz-s3-demo`), so
  the boot-time `aws s3 cp` is already authorized.

Per-queue, only three things differ: which **S3 prefix** the UserData copies,
the **instance class**, and **MaxvCPUs**. spot-metaphlan uses `r8g.4xlarge`
(16 vCPU / 128 GB, primary — 2 jobs/VM) and `r8g.2xlarge` (8 / 64, pool depth —
1 job or any strainphlan step): `profile_taxa` is 8 vCPU / 36 GB = 4.5 GB/vCPU,
and r8g's 8 GB/vCPU ratio is what lets **two** jobs pack onto one 16-vCPU VM and
share that instance's single staged vJan25 copy. m8g/c8g (4 / 2 GB/vCPU) could
hold only one 36 GB job per box. `r8g.8xlarge` is intentionally excluded —
256 GB is memory-overprovisioned (see sizing table). `--nproc = task.cpus`
(no oversubscription) so 8 threads/job × 2 jobs exactly fills the 16 cores.

The boot-time copy **skips `*_SGB.fna` / `*_SGB.fna.bz2`** (~7.4 GB of index
*source* sequences not read at profiling time — the known-good `metaphlan
--install` set ships neither), trimming vJan25 from ~44 GB to ~37 GB.

### Spot-only — no on-demand fallback (by design)

spot-metaphlan is **spot-only**: its queue has a single spot CE, no on-demand CE
behind it (unlike `spot-queue`). profile_taxa/strainphlan jobs are not
latency-critical — a reclaimed job just retries — so we don't pay on-demand
rates for them.

The cost of spot-only is **no-capacity stalls**: if every spot pool the CE can
use goes dry, jobs sit RUNNABLE indefinitely (observed 2026-06-18 with only
`m8g.4xlarge` + `r8g.4xlarge` — both pools emptied, workers were reclaimed with
`instance-terminated-no-capacity` before the ~6-min boot+copy finished, so they
never registered with ECS → churn). Mitigations, in order:

1. **Many pools.** Capacity-optimized needs breadth. We list five 16-/32-vCPU
   r8g/m8g/c8g types (× 3 AZs = 15 pools). Larger sizes (8xlarge) often have
   deeper spot capacity than the popular 4xlarge.
2. **Bid = 100%** of on-demand. This only prevents *price* interruptions
   (`instance-terminated-by-price`); it does **not** help `no-capacity` (you
   can't bid for capacity that doesn't exist). It's cheap insurance, not a fix.
3. If stalls persist, the only real cure is adding an on-demand fallback CE —
   which we are **intentionally not doing** for this queue. Accept the stall risk.

### Instance sizing & memory — r8g.8xlarge is overkill

`profile_taxa` = 8 vCPU / 36 GB ⇒ 4.5 GB/vCPU. Sizing depends on how many jobs
share a VM and whether the index is memory-mapped:

| Scenario | Aggregate need | Best-fit Graviton VM | Memory waste |
|----------|----------------|----------------------|--------------|
| **No mm, 2 jobs/VM (current)** | 16 vCPU / 72 GB | `r8g.4xlarge` (16 / 128) | ~56 GB spare — cpu-exact, mem loose |
| No mm, 4 jobs/VM | 32 vCPU / 144 GB | `r8g.8xlarge` (32 / 256) | ~112 GB spare — **wasteful; why 8xlarge is a poor fit** |
| **mm, 1×32-thread job** | 32 vCPU / ~64 GB (index shared once) | `c8g.8xlarge` (32 / 64) ✓ exists | ~0 |
| mm, 2 jobs/VM | 32 vCPU / ~64 GB | `c8g.8xlarge` (32 / 64) or `m8g.8xlarge` (32 / 128) | minimal |

Takeaways:
- `r8g.8xlarge` (256 GB) is memory-overprovisioned — it only earns its RAM at
  4 jobs/VM, and even then wastes ~112 GB. Prefer **more `r8g.4xlarge`** for pool
  depth over one 8xlarge.
- The memory floor (36 GB/job for the ~34 GB bowtie2 index) is what forces r8g
  today. Memory-mapping removes that floor (shared index), which unlocks the
  compute-optimized **`c8g.8xlarge` (32 vCPU / 64 GB)** — the right shape for a
  32-thread, CPU-bound MetaPhlAn job. (32 vCPU / 64 GB VMs *do* exist: c8g.8xlarge.)
- So the path is: **now** r8g.4xlarge @ 8 cpu × 2 jobs → **after mm** c8g.8xlarge
  @ 32 cpu, dropping per-job memory once the shared-index footprint is measured.

### Future optimization: bowtie2 memory-mapping

With bowtie2 `--mm`, the two co-located jobs would mmap the *same* vJan25 index
files and share OS page-cache pages instead of each loading its own ~34 GB copy
— faster load and much lower real RAM (which would let us drop the per-job
`memory` directive and pack more jobs per VM). Deferred: MetaPhlAn 4.2.4's
passthrough for this needs verifying, and the per-job memory floor must be
re-measured before lowering it. Tracked here as a follow-up to the current
"stage once per VM" win.

### The `cliPath` / bind-mount constraint (important)

`aws.batch.cliPath = '/opt/conda-aws/bin/aws'` is **global** — it applies to
every job on every queue, and Nextflow bind-mounts the grandparent
(`/opt/conda-aws`) from the host into each container. The custom AMI bakes
awscli there. The thin AMI does **not** have it, so its UserData must
**reconstruct `/opt/conda-aws/bin/aws`** (install awscli v2 to that prefix)
before ECS registers, or every container on the thin queue fails to stage
inputs. The same binary is then used for the boot-time DB copy.

### Boot ordering

A **synchronous** (non-backgrounded) `aws s3 cp` in UserData naturally gates ECS
registration until the copy finishes — the instance accepts no Batch jobs until
the DB is present (this is the same blocking behavior documented in I24, used
here on purpose). ~3–5 min for vJan25, amortized over every job on the instance.

## Per-workload caveats

- **Sizes differ.** vJan25 ≈ 44 GB (~3–5 min). HUMAnN's set is larger; MEDI's
  hash is larger still — boot copy is minutes, not seconds, on those. Still far
  better than FSR-less lazy-load, but the "boot is cheap" claim is strongest for
  metaphlan.
- **MEDI is the real outlier.** Kraken wants the whole hash memory-resident
  (today: `vmtouch -dl`). `spot-medi` must use RAM-class instances sized to hold
  the hash and warm it after the copy — so it's "thin-AMI + s3 cp + RAM-sizing +
  warm," not just "thin-AMI + s3 cp." Design that block when we get to it.
- **MEDI is the biggest cost win (TODO).** Today every `MEDI_QUANT:*` process
  runs on the head node (`executor = 'local'` in `conf/aws_batch.config`), so the
  large RAM instance hosting the Kraken hash is pinned on-demand for the whole
  run regardless of how few MEDI jobs are in flight. Moving MEDI to a `spot-medi`
  queue is therefore the **largest projected savings** of the whole multiqueue
  effort — but it's last in rollout order because it's the hardest (RAM-sizing +
  hash warm). Until then, the head node stays the MEDI executor.

## Rollout order

1. **Now:** `spot-metaphlan` only — smallest DB, proves the thin-AMI + s3-cp
   pattern end to end, and it's exactly what the CosmosID StrainPhlAn test run
   exercises (`infra/playbook-CosmosID-queue.md`).
2. Clone the block for `spot-humann` once metaphlan is validated.
3. `spot-medi` last (needs the RAM-sizing + warm step).

## conf/aws_batch.config routing

Each routed process gets `queue = 'spot-metaphlan'` in its `withName` block;
unrouted processes fall through to `process.queue = 'spot-queue'`. Greppable and
reversible — deleting the `queue =` lines reverts to the single-queue behavior.

## How to validate `spot-metaphlan` cheaply

See `infra/playbook-CosmosID-queue.md` for the full run. The minimal smoke check
(a few minutes, well under \$10 of spot) is in the "Validating spot-metaphlan"
section of this repo's `infra/readme.md` workflow — in short: deploy the stack,
submit **one** sample through `profile_taxa` only, confirm the job lands on
`spot-metaphlan`, the worker booted on the thin AMI and copied vJan25, and the
`<id>_metaphlan.biom` appears in S3. One `m8g`/`c8g` spot instance for ~10–15
min is on the order of \$0.10–0.30.
