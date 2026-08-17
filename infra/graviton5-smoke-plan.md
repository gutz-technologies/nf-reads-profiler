# Graviton5 (c9g/m9g) smoke-test plan

Goal: stand up a **new, isolated** set of Batch CEs/queues on Graviton5
instances and re-run the gemma-smoke slice against them, to compare against
the existing Graviton4 (c8g/m8g/...) fleet. Does not touch prod CEs/queues.

## Graviton5 availability (as of 2026-08, vantage.sh)

Only `c9g` and `m9g` families exist so far (launched June 2026). No `r9g`,
`i9g`, `x9g`, and no NVMe/local-storage variants (`*d`, `*n`, `*gd`) yet.

Confirmed specs (us-east-2 pricing per vantage.sh, unverified against live AWS
API — see validation task below):

| Type | vCPU | Mem | On-demand $/hr | Spot $/hr |
|---|---:|---:|---:|---:|
| c9g.24xlarge | 96 | 192 GiB | 4.173 | 1.542 |
| c9g.48xlarge | 192 | 384 GiB | 8.346 | 3.415 |
| c9g.metal-48xl | 192 | 384 GiB | 8.346 | 2.620 |
| m9g.24xlarge | 96 | 384 GiB | 4.70 | 2.16 |
| m9g.metal-48xl | 192 | 768 GiB | 9.39 | 2.55 |

`m9g.metal-48xl` spot ($2.55/hr for 192 vCPU / 768 GiB = ~$0.0133/vCPU/hr) is
the cheapest per-vCPU pool seen — cheaper than c9g.metal-48xl spot
(~$0.0136/vCPU/hr) despite 2x the memory. Worth leading with it in the new
metaphlan/humann CEs' `InstanceTypes` list once existence + capacity are
confirmed live (SPOT_PRICE_CAPACITY_OPTIMIZED will still spread across the
listed pools; order mainly documents intent).

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
3. `InstanceTypes` per new CE limited to verified-existing pools only:
   `c9g.2xlarge/4xlarge/12xlarge/24xlarge/48xlarge/metal-48xl`,
   `m9g.2xlarge/4xlarge/24xlarge/metal-48xl`. Drop all `*d`/`*n`/`*gd` and the
   1.5TB / 16GB-per-vCPU tiers.
4. **Blocking validation before any deploy** (delegated to subagent, see
   below):
   - Do `c9g`/`m9g` (all sizes above, esp. `m9g.metal-48xl`) actually exist
     and have capacity in `us-east-2`? Verify via
     `aws ec2 describe-instance-type-offerings` /
     `describe-instance-types`, not just vantage.sh.
   - Current on-demand + spot pricing in `us-east-2` specifically (vantage
     numbers above may be a different region's default).
   - Does the ECS-optimized ARM64 AMI (or whatever AMI the thin-AMI boot
     path resolves) support booting on Graviton5? Brand-new silicon
     (June 2026) — Batch/ECS support unconfirmed.
5. `cfn-lint infra/*.yaml` after any CFN edits.
6. Baseline: reuse the existing gemma-smoke slice (7 under8g + 3 over8g,
   same samplesheet, same `conf/gemma.config` mem ladder), routed via a new
   `-profile aws_g5` / `conf/aws_batch_g5.config` overlay that only swaps
   queue names. Compare against the recorded G4 smoke result (7/9 under8g,
   3/3 over8g, `40GB attempt-1 / 60GB attempt-2` ladder — see
   `project_gemma_pipeline_status` memory).
7. Compare: wall time/sample, cost, OOM rate, spot interruption rate.

No CFN/config files written yet — plan only, per request.
