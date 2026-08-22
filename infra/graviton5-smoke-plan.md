# Graviton5 (c9g/m9g) smoke-test plan

Goal: stand up a **new, isolated** set of Batch CEs/queues on Graviton5
instances and re-run the gemma-smoke slice against them, to compare against
the existing Graviton4 (c8g/m8g/...) fleet. Does not touch prod CEs/queues.

## Graviton5 availability — VALIDATED live against AWS (us-east-2), 2026-08-17

`describe-instance-types` + `describe-instance-type-offerings` +
`describe-spot-price-history` in `us-east-2`. All 10 vantage-listed types
confirmed to exist, offered in all 3 AZs (a/b/c):

| Type | vCPU | Mem GiB | Spot $/hr | Spot $/vCPU/hr |
|---|---:|---:|---:|---:|
| c9g.2xlarge | 8 | 16 | 0.093 | 0.0116 |
| c9g.4xlarge | 16 | 32 | 0.254 | 0.0159 |
| c9g.12xlarge | 48 | 96 | 0.559 | 0.0117 |
| c9g.24xlarge | 96 | 192 | 0.944 | 0.0098 |
| c9g.48xlarge | 192 | 384 | 2.358 (jitters 1.68-2.38) | 0.0123 |
| **c9g.metal-48xl** | 192 | 384 | **0.832 (flat)** | **0.0043 — cheapest/vCPU** |
| m9g.2xlarge | 8 | 32 | 0.127 | 0.0159 |
| m9g.4xlarge | 16 | 64 | 0.301 | 0.0188 |
| m9g.24xlarge | 96 | 384 | 1.251 | 0.0130 |
| m9g.metal-48xl | 192 | 768 | 0.939 (flat) | 0.0049 |

**Correction to earlier claim:** `m9g.metal-48xl` is NOT the cheapest
per-vCPU pool. `c9g.metal-48xl` is, at $0.0043/vCPU/hr vs m9g.metal-48xl's
$0.0049/vCPU/hr (~13% cheaper). Both metal-48xl types show unusually flat
spot pricing vs. the jittery sized variants — consistent with thin/new
supply, so treat as provisional until real Batch usage tests it.

**Correction to NVMe-variant assumption:** vantage.sh was wrong — live AWS
confirms `c9gd.24xlarge` (96 vCPU/192GiB + 3x1900GB local NVMe) and
`m9gd.metal-48xl` (192 vCPU/768GiB + 3x3800GB local NVMe) **do exist** in
us-east-2. `r9g`, `i9g`, `x9g`, `c9gn`, `m9gn` confirmed non-existent
(`InvalidInstanceType`) — those gaps stand. The NVMe finding reopens
possibilities for DB-staging queues (spot-medi still has no fit — no
high-mem 8-16GB/vCPU G5 family — but c9gd/m9gd NVMe could matter for
metaphlan/humann DB staging if ever revisited).

## spot-medi >500GB-RAM candidate — deep price/capacity check, 2026-08-17

Only two G5 types clear 500 GiB RAM: `m9g.metal-48xl` (768GiB, no NVMe) and
its NVMe sibling `m9gd.metal-48xl` (768GiB + local NVMe). 7-day
`describe-spot-price-history` pull (261 points, all 3 AZs), not just latest
tick:

| Type | AZ 2a | AZ 2b | AZ 2c |
|---|---|---|---|
| c9g.metal-48xl (384GiB, ref only — too small alone) | $0.8317 flat | $0.8317 flat | $0.8317 flat |
| **m9g.metal-48xl** (768GiB) | $1.13-$1.48 (med $1.31) | **$0.9393 flat** | **$0.9393 flat** |
| m9gd.metal-48xl (768GiB+NVMe) | $1.24-$1.55 (med $1.40) | $1.2067 flat | $1.75-$2.27 (med $2.00) |

vantage.sh's $1.0056/hr for m9g.metal-48xl looks like a stale/blended
figure — real AWS data shows it's under $1/hr **only in AZ 2b/2c**, pricier
and variable in 2a. m9gd (NVMe) is **never under $1/hr in any AZ** over this
window — the NVMe sibling doesn't hit the target.

Spot Placement Score (AWS's real queue-depth signal, 1-10, higher=better),
single-AZ scores are per-AZ (order not guaranteed a/b/c) and regional spreads
across all 3:

| Type | tc=1 | tc=2 | tc=4 | tc=8 | Regional tc=1/2/4/8 |
|---|---|---|---|---|---|
| m9g.metal-48xl | 3,3,2 | 2,1,3 | 1,1,3 | 2,1,1 | 3,3,3,2 |
| m9gd.metal-48xl | 2,3,2 | 1,2,1 | 1,1,1 | 1,1,1 | 3,3,2,1 |

Both cap at 3/10 — genuinely thin spot capacity, not an artifact. Degrades
further as target capacity rises, especially m9gd (drops to 1 by tc=4 even
regionally).

**Verdict:** `m9g.metal-48xl` is the real spot-medi G5 candidate — sub-$1/hr
and flat in AZ 2b/2c, regional placement score holds at 3 through tc=4.
`m9gd.metal-48xl` is worse on both axes (never <$1/hr, placement score drops
to 1 at tc>=4) — its NVMe doesn't buy availability, and MEDI's page-cache
warm-up doesn't strictly need instance-store (EBS-staged + warm-into-RAM
works, just a slower initial copy). Neither pool is deep (capped at 3/10) —
plan for interruption/retry at more than a couple concurrent nodes, and pin
the CE's AZ preference toward 2b/2c to actually realize the ~$0.94/hr price
(Batch doesn't let you exclude a single AZ directly, but subnet selection in
`SubnetIds` can be scoped to 2b/2c-only subnets for this CE).

**AMI check:** SSM param
`/aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended/image_id`
resolves fine (`ami-01072f6f8844e1659`, modified 2026-08-07). No AWS docs
found confirming Graviton5 boot support explicitly. Same ARM64/Neoverse
architecture family as Graviton3/4, so likely boots, but **unverifiable
read-only — must smoke-test with a real launch**, not assume.

## Instance map: Graviton4 (current) -> Graviton5 (new test CEs)

| Queue | G4 type | vCPU/Mem | G5 replacement | vCPU/Mem | Note |
|---|---|---|---|---|---|
| spot-queue (glue) | m8g.2xlarge | 8/32GB | m9g.2xlarge | 8/32GB | same 4GB/vCPU |
| spot-queue | m8g.4xlarge | 16/64GB | m9g.4xlarge | 16/64GB | |
| spot-queue | c8g.2xlarge | 8/16GB | c9g.2xlarge | 8/16GB | same 2GB/vCPU |
| spot-queue | c8g.4xlarge | 16/32GB | c9g.4xlarge | 16/32GB | |
| spot-metaphlan | c8g.12xlarge | 48/96GB | c9g.12xlarge | 48/96GB | assumed, unverified |
| spot-metaphlan | c8g.metal-24xl | 96/192GB | c9g.24xlarge / metal-24xl | 96/192GB | c9g.24xlarge verified |
| spot-metaphlan | c8gd.24xlarge | 96/192GB+NVMe | none | — | gap: no NVMe G5 |
| spot-metaphlan | m8g.metal-24xl | 96/384GB | m9g.24xlarge | 96/384GB | verified |
| spot-metaphlan | c8g.48xlarge / metal-48xl | 192/384GB | c9g.48xlarge / metal-48xl | 192/384GB | verified both |
| spot-metaphlan | c8gd/c8gn.48xlarge | 192/384GB+NVMe | none | — | gap |
| spot-metaphlan | m8gd.metal-48xl | 192/768GB+NVMe | m9g.metal-48xl (no NVMe) | 192/768GB | mem tier matches, NVMe lost |
| spot-metaphlan | r8g.metal-48xl | 192/1.5TB | none | — | gap, no 8GB/vCPU G5 tier |
| spot-metaphlan | x8g.8xl / 12xl (16GB/vCPU) | 32/512, 48/768 | none | — | gap, no high-mem G5 family; StrainPhlAn sample2markers under-provisioned in G5 CE |
| spot-metaphlan | r8g.metal-24xl | 96/768GB | no clean fit | — | m9g.metal-48xl is 2x vCPU for same mem/vCPU ratio |
| spot-humann | same c8g/m8g pools as above | | c9g/m9g equivalents | | same NVMe/mem-tier gaps |
| spot-medi | r8gd.metal-24xl, i8g.*, r8gd.*, m8gd.metal-48xl (all NVMe, 768GB-1.5TB) | | **m9g.metal-48xl** | 192/768GB, no NVMe | fit found (see dedicated section above) — sub-$1/hr in AZ 2b/2c, placement score 3/10 through tc=4. No 1.5TB-tier equivalent, so the r8g.metal-48xl-class headroom is still a gap; m9g.metal-48xl's 768GB must be enough for the 414GB hash + working memory. |

## Field evidence from the G4 spot-humann CE (2026-08-18, gemma over8g run)

Measured live during the GEMMA over8g stage-2 run, on the existing G4
`spot-humann` CE (`SPOT_PRICE_CAPACITY_OPTIMIZED`, `MaxvCPUsHumann=960`).
Two findings that should shape the G5 `InstanceTypes` lists.

**1. Only `m8g.metal-24xl` had both a >=4 GiB/vCPU ratio and real spot depth.**
The CE stalled at 480 of 960 `desiredvCpus` and placed nothing but
`m8g.metal-24xl` (5 instances, spread 2a/2b/2c). Spot placement score at
target capacity 480 vCPU, single-AZ:

| instance | GiB/vCPU | use2-az1 | use2-az2 | use2-az3 |
|---|---:|---:|---:|---:|
| `m8g.metal-24xl` | 4 | 1 | 3 | 3 |
| `m8gd.metal-48xl` | 4 | 1 | 1 | 1 |
| `r8g.metal-48xl` | 8 | 1 | 1 | 1 |
| `c8g.metal-48xl` | 2 | 1 | 3 | 1 |

`m8gd.metal-48xl` is score 1 everywhere *and* 2.05x the $/vCPU of
`m8g.metal-24xl` ($0.00922 vs $0.00449, cheapest-AZ spot), so
price-capacity-optimized correctly skipped it — it was not a viable second
pool. On the G5 side the same shape is likely: a list that leans on one
`m9g` type for the 4 GiB/vCPU tier has a single point of capacity failure.
Give each G5 queue at least two viable pools at the *actual* ratio it needs,
and check placement scores at the CE's real target capacity, not at tc=1.

**2. The 4 GiB/vCPU requirement is probably wrong — CPU is the binding
constraint, not memory.** ECS `describe-container-instances` on every humann
node: 3 running tasks, **CPU remaining 0**, memory remaining 263,132 of
386,012 MiB registered. Per task that is 32 vCPU and 40,960 MiB = **1.25
GiB/vCPU**. (`conf/aws_batch.config` declares `cpus = 16` / `memory = 25.GB`
attempt-1, 40.GB on retry, and the job def lands at 32 vCPU — the "x2
internally" note on that block.) So ~2/3 of each node's RAM sat idle while
the pool was CPU-starved.

At 1.25 GiB/vCPU the cheap 2 GiB/vCPU `c8g.*` pools clear the requirement
with room to spare — `c8g.metal-48xl` is both cheaper per vCPU ($0.00397 vs
$0.00449) and has depth (score 3 in use2-az3), and fits 6 x 32-vCPU tasks in
240 of its 384 GB. The G5 analogue `c9g.metal-48xl` is already flagged above
as best $/vCPU (0.0043). **Verify the real per-task ratio before writing the
G5 `InstanceTypes` lists** — sizing the humann CE off the declared memory
ladder rather than observed usage is what narrowed it to one pool.

Caveat: this is one run's snapshot. The 40 GB observed matches the *retry*
rung, so some of those tasks may be attempt 2; re-measure on a clean run
before treating 1.25 GiB/vCPU as the design number.

Changing `InstanceTypes` on an existing CE **replaces it and kills in-flight
jobs** (see CLAUDE.md) — so any correction here lands on the new G5 CEs at
creation, or on the G4 CEs only between runs.

## Rollout steps (not yet executed)

1. New branch: `graviton5-smoke` (this one).
2. New parallel CEs/queues, cloned from existing launch templates (same
   UserData/boot logic): `spot-queue-g5`, `spot-metaphlan-g5`,
   `spot-humann-g5`, `spot-medi-g5` (single type `m9g.metal-48xl`, no NVMe —
   MEDI's boot script must EBS-stage the Kraken DB instead of instance-store,
   then warm hash into page cache same as today; subnets scoped to AZ
   2b/2c to realize the ~$0.94/hr price).
3. `InstanceTypes` per new CE — all 10 base types confirmed live, plus
   `c9gd.24xlarge` and `m9gd.metal-48xl` (NVMe, confirmed live, vantage was
   wrong about these not existing). Lead with `c9g.metal-48xl` for
   best $/vCPU (0.0043), not m9g.metal-48xl. `r9g`/`i9g`/`x9g`/`c9gn`/`m9gn`
   confirmed genuinely non-existent — no fit for spot-medi or the
   16GB/vCPU StrainPhlAn tier still stands.
4. **Blocking validation — DONE 2026-08-17** (live AWS API, us-east-2):
   all 10 base types + c9gd.24xlarge + m9gd.metal-48xl exist, all 3 AZs.
   ECS ARM64 AMI param resolves; boot support on G5 unconfirmed by docs,
   residual risk flagged for real-launch smoke test (step 6).
5. `cfn-lint infra/*.yaml` after any CFN edits.
6. Baseline: reuse the existing gemma-smoke slice (7 under8g + 3 over8g,
   same samplesheet, same `conf/gemma.config` mem ladder), routed via a new
   `-profile aws_g5` / `conf/aws_batch_g5.config` overlay that only swaps
   queue names. Compare against the recorded G4 smoke result (7/9 under8g,
   3/3 over8g, `40GB attempt-1 / 60GB attempt-2` ladder — see
   `project_gemma_pipeline_status` memory).
7. Compare: wall time/sample, cost, OOM rate, spot interruption rate.

No CFN/config files written yet — plan only, per request.
