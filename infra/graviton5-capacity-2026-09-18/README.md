# Graviton5 Spot assessment — 2026-09-18

Live AWS CLI snapshot, account 730883236839, region us-east-2. Scope: profile_function and profile_taxa only. MEDI and production resources remain unchanged.

## Placement scores

Scores are 1–10, higher is better; estimates do not guarantee capacity. VM targets use `units`, not vCPUs. Scores apply to the complete mixed pool, not each member. AZ ordering below is fixed using this account’s subnet mapping.

| Pool | VMs | Region | us-east-2a | us-east-2b | us-east-2c |
|---|---:|---:|---:|---:|---:|
| humann | 1 | 9 | 9 | 9 | 9 |
| humann | 2 | 9 | 9 | 9 | 9 |
| humann | 4 | 9 | 9 | 8 | 9 |
| humann | 8 | 9 | 7 | 5 | 8 |
| humann | 16 | 9 | 3 | 2 | 4 |
| metaphlan | 1 | 9 | 9 | 9 | 9 |
| metaphlan | 2 | 9 | 9 | 9 | 9 |
| metaphlan | 4 | 9 | 9 | 9 | 9 |
| metaphlan | 8 | 9 | 7 | 6 | 8 |
| metaphlan | 16 | 9 | 3 | 3 | 4 |

MetaPhlAn at its current 200-vCPU limit scores 9 regionally and in every AZ. AWS rejected HUMAnN’s 960-vCPU target with `TargetCapacityLimitExceeded`; its full CE limit is therefore unassessed. VM-count scenarios can exceed the configured CE maximums and are capacity estimates, not runnable configurations.

AWS also returned `MaxConfigLimitExceeded` after the initial matrix: new placement configurations must wait for the 24-hour restriction to expire. The four user-suggested MEDI choices could not be scored. See [placement-score query discipline](metaphlan-costs/report.md#placement-score-query-discipline) before requesting more scores. Service Quotas listing was denied to the runner role; account Spot vCPU quota remains unverified.

AWS API documentation warns that one or two types, or variations of one type, always return low placement scores. The August report’s single-type 3/10 scores do not establish thin supply by themselves. Scores also do not account for our workload fit or prove boot success.

## Created isolated resources

Two CEs and two dedicated queues: `spot-humann-g5` and `spot-metaphlan-g5`. Final state: disabled; CE minimum and desired capacity zero. AWS required ENABLED at creation; each CE was created without a queue and disabled immediately after becoming VALID. No benchmark jobs submitted.

Cloned live roles, subnets, security groups, SPOT_PRICE_CAPACITY_OPTIMIZED, 50% bid setting, AMI, and boot configuration. Launch templates pinned to existing version 6. Maximums preserved: HUMAnN 960 vCPU; MetaPhlAn 200 vCPU. Resources were created with the Batch API, outside the production CloudFormation stack. The temporary creation payloads and raw API snapshots were removed after their findings were summarized here.

Instance mapping: 8g → 9g where offered; metal-24xl → 24xlarge where no matching metal size exists. Unsupported c8gn and x8g equivalents omitted. This is a profiling test pool, not an equivalent replacement for all high-memory StrainPhlAn workloads.

- humann: `c9g.12xlarge`, `c9g.24xlarge`, `c9g.48xlarge`, `c9g.metal-48xl`, `c9gd.48xlarge`, `m9g.24xlarge`, `m9gd.metal-48xl`, `r9g.24xlarge`, `r9g.metal-48xl`
- metaphlan: `c9g.12xlarge`, `c9g.24xlarge`, `c9g.48xlarge`, `c9g.metal-48xl`, `c9gd.24xlarge`, `c9gd.48xlarge`, `m9g.24xlarge`, `m9gd.metal-48xl`, `r9g.24xlarge`, `r9g.metal-48xl`

## Spot price snapshot

USD per instance-hour, Linux/UNIX. Latest returned sample per type/AZ. Prices alone do not establish cost per completed sample. EBS and data transfer excluded.

| Type | vCPU | GiB | 2a | 2b | 2c |
|---|---:|---:|---:|---:|---:|
| c9g.12xlarge | 48 | 96 | 0.792100 | 0.624200 | 0.490700 |
| c9g.24xlarge | 96 | 192 | 0.796000 | 0.994200 | 0.659400 |
| c9g.48xlarge | 192 | 384 | 1.392200 | 1.813500 | 1.310300 |
| c9g.metal-48xl | 192 | 384 | 1.384300 | 1.481700 | 1.500400 |
| c9gd.24xlarge | 96 | 192 | 0.759700 | 1.049100 | 0.740700 |
| c9gd.48xlarge | 192 | 384 | 1.530200 | 2.764500 | 1.697800 |
| m9g.24xlarge | 96 | 384 | 0.999400 | 1.295000 | 1.042600 |
| m9gd.metal-48xl | 192 | 768 | 1.835700 | 1.578200 | 1.327400 |
| r9g.24xlarge | 96 | 768 | 1.135100 | 1.728500 | 0.793100 |
| r9g.metal-48xl | 192 | 1536 | 1.528500 | 3.979800 | 1.543900 |

## Benchmark routing and remaining validation

The agreed 100k–10m CosmosID infant comparison is documented in the
[Graviton4 versus Graviton5 benchmark plan](../graviton4-vs-graviton5-benchmark-plan.md).

The temporary `conf/aws_batch_g5.config` routing overlay was removed after the
benchmark. Production queue routing now belongs in `infra/batch-stack.yaml` and
the normal AWS configuration.

Use five reads_to_process settings (100k, 300k, 1m, 3m, 10m) on the same source sample: one G4 run and one G5 run, ten sample cases total. Keep software and task resources the same. Report profiler runtime speedup and cost savings from the billing dashboard. The linked simplified plan supersedes the earlier replicate/cold-warm design. No speedup or cost saving has yet been measured.

## Existing MEDI

Current CE allows r8gd.metal-24xl, i8g.24xlarge, r8gd.24xlarge, m8gd.metal-48xl, r8gd.metal-48xl and i8g.48xlarge; all provide local NVMe and at least 768 GiB RAM. Desired capacity was zero and ECS returned no registered workers. No MEDI changes made.
