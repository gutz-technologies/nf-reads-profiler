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
| spot-medi | r8gd.metal-24xl, i8g.*, r8gd.*, m8gd.metal-48xl (all NVMe, 768GB-1.5TB) | | **none** | — | full gap. Kraken hash needs instance-store + mem-resident 414GB; not buildable on G5 today. Leave on G4 or skip MEDI in this test. |

## Rollout steps (not yet executed)

1. New branch: `graviton5-smoke` (this one).
2. New parallel CEs/queues, cloned from existing launch templates (same
   UserData/boot logic): `spot-queue-g5`, `spot-metaphlan-g5`,
   `spot-humann-g5`. No `spot-medi-g5` (no fit yet).
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
