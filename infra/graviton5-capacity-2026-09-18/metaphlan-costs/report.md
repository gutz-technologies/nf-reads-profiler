# MetaPhlAn Graviton4 versus Graviton5: cheapest regional Spot prices

Fresh AWS CLI snapshot: 2026-09-18T15:25:00Z. Linux/UNIX Spot prices in us-east-2, USD. Each row is an allowed instance type, not a running VM.

Ten-VM placement scores were not obtained: the distinct-configuration limit was reached. Omitted from the tables; raw responses are retained alongside this report.

## Graviton4 — SpotMetaphlanComputeEnvi-fcBWFMwh79fzN3bX

CE state: ENABLED; desired vCPUs: 0; allocation: SPOT_PRICE_CAPACITY_OPTIMIZED.

| Instance type ID | vCPUs | RAM GiB | Cheapest AZ(s) | $/VM-hour | $/vCPU-hour |
|---|---:|---:|---|---:|---:|
| c8g.12xlarge | 48 | 96 | us-east-2c | 0.4325 | 0.009010 |
| c8g.metal-24xl | 96 | 192 | us-east-2b | 0.8687 | 0.009049 |
| c8gd.24xlarge | 96 | 192 | us-east-2a | 0.6796 | 0.007079 |
| m8g.metal-24xl | 96 | 384 | us-east-2c | 0.4308 | 0.004488 |
| c8g.48xlarge | 192 | 384 | us-east-2b | 1.6890 | 0.008797 |
| c8g.metal-48xl | 192 | 384 | us-east-2b | 0.7630 | 0.003974 |
| c8gd.48xlarge | 192 | 384 | us-east-2b | 1.3094 | 0.006820 |
| c8gn.48xlarge | 192 | 384 | us-east-2c | 1.4152 | 0.007371 |
| m8gd.metal-48xl | 192 | 768 | us-east-2a | 1.2909 | 0.006723 |
| r8g.metal-48xl | 192 | 1536 | us-east-2a | 1.1311 | 0.005891 |
| x8g.8xlarge | 32 | 512 | us-east-2a | 0.8108 | 0.025337 |
| x8g.12xlarge | 48 | 768 | us-east-2c | 0.9941 | 0.020710 |
| r8g.metal-24xl | 96 | 768 | us-east-2c | 0.7130 | 0.007427 |

## Graviton5 — spot-metaphlan-g5

CE state: DISABLED; desired vCPUs: 0; allocation: SPOT_PRICE_CAPACITY_OPTIMIZED.

| Instance type ID | vCPUs | RAM GiB | Cheapest AZ(s) | $/VM-hour | $/vCPU-hour |
|---|---:|---:|---|---:|---:|
| c9g.12xlarge | 48 | 96 | us-east-2c | 0.4907 | 0.010223 |
| c9g.24xlarge | 96 | 192 | us-east-2c | 0.6594 | 0.006869 |
| c9g.48xlarge | 192 | 384 | us-east-2c | 1.3103 | 0.006824 |
| c9g.metal-48xl | 192 | 384 | us-east-2a | 1.3843 | 0.007210 |
| c9gd.24xlarge | 96 | 192 | us-east-2c | 0.7407 | 0.007716 |
| c9gd.48xlarge | 192 | 384 | us-east-2a | 1.5302 | 0.007970 |
| m9g.24xlarge | 96 | 384 | us-east-2a | 0.9994 | 0.010410 |
| m9gd.metal-48xl | 192 | 768 | us-east-2c | 1.3274 | 0.006914 |
| r9g.24xlarge | 96 | 768 | us-east-2c | 0.7931 | 0.008261 |
| r9g.metal-48xl | 192 | 1536 | us-east-2a | 1.5285 | 0.007961 |

## Equal-speed cost estimate

Cheapest normalized Graviton4 option: `c8g.metal-48xl` in us-east-2b, **$0.003974/vCPU-hour** ($0.7630/VM-hour for 192 vCPUs).

Cheapest normalized Graviton5 option: `c9g.48xlarge` in us-east-2c, **$0.006824/vCPU-hour** ($1.3103/VM-hour for 192 vCPUs).

Assuming equal CPU speed and equally effective utilization, the cheapest G5 option costs **71.7% more per vCPU-hour** than the cheapest G4 option at this snapshot. These are independently selected cheapest pools, not guaranteed placements or fleet-average costs.

## Availability before price

Rechecked **2026-09-18 15:30:59 UTC** with one request for ten
`c8g.metal-48xl` instances in us-east-2. AWS again returned
`MaxConfigLimitExceeded`; stopped immediately without querying other types.
Exact request/error: [placement-recheck.json](placement-recheck.json).
No numeric scores are available to restore to the per-type tables.

The selection objective is **best value subject to sufficient availability**,
not simply the cheapest listed VM. However, AWS says single-type requests
always score low, so an individual-type score cutoff is not a reliable
availability filter. Do not treat a missing score as zero or attach a mixed-pool
score to each member of that pool.

After the allowance resets, score a small shortlist of actual candidate pools
at ten VMs across us-east-2, then compare value among pools meeting the chosen
threshold. No threshold has been selected yet. Per-type availability needs
observed launch/fulfillment evidence; no capacity-test launches were made.
The cheapest-AZ price in these tables is not guaranteed by a regional score.

## Placement-score query discipline

The earlier broad sweep exhausted the allowance; continuing with 23 new
per-type requests after the first limit error was unnecessary.

- Decide the few configurations needed before calling AWS. For this comparison,
  start with one regional request per CE's actual mixed pool, target **10 units**
  (VMs), rather than a type × size × AZ sweep. A mixed-pool score describes ten
  instances total, not ten of each type.
- Save the exact request, response and UTC timestamp; reuse recent results for
  identical configurations. Only query individual types when specifically needed,
  sequentially, and stop the whole batch at the first limit error.
- `MaxConfigLimitExceeded` is a **distinct-configuration allowance**, not ordinary
  request-rate throttling. AWS's returned message says existing configurations
  from the last 24 hours may be retried, or wait 24 hours before specifying new
  ones. Brief sleeps or parallel retries do not replenish that allowance.
- For ordinary throttling, use bounded AWS SDK/CLI retries with exponential
  backoff and jitter. Do not repeatedly retry configuration-limit errors.

AWS recommends at least three distinct types: one/two types or variations of
one type always score low. Scores are 1–10 estimates, not availability guarantees
or probabilities. A regional score does not guarantee the cheapest AZ price.

There is no fixed queue price. Batch uses SPOT_PRICE_CAPACITY_OPTIMIZED and may select another type/AZ. Prices change. Estimates exclude startup/idle time, interruptions, packing, memory limits, disks, network, and actual speed differences. No AWS resources were modified or launched.
