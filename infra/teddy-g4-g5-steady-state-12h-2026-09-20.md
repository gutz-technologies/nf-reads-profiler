# TEDDY: measured 12-hour fleet throughput

September 19 (G4) versus September 20 (G5), 2026; 02:00–14:00 UTC.

| Profiler | G4 completions | G5 completions | G4 samples/h | G5 samples/h | Throughput change |
|---|---:|---:|---:|---:|---:|
| MetaPhlAn | 1730 | 2894 | 144.17 | 241.17 | +67.3% |
| HUMAnN4 | 2378 | 2654 | 198.17 | 221.17 | +11.6% |

Counts are unique successful sample completions in driver logs within
[02:00,14:00), excluding cached tasks. These measure fleet throughput, not
per-core performance; fleet capacity and sample mix differ.

Previously included modeled costs are withdrawn. Actual billed cost and
cost per sample for this exact window are unavailable in the collected evidence.
Daily Cost Explorer totals cannot isolate this window or profiler. Hourly
resource-level billing is needed; do not substitute Spot-price estimates.

## Billed Spot compute cost available 2026-09-22

Cost Explorer now reports unblended Spot EC2 compute cost by day and instance
type. Hourly Cost Explorer data is not enabled on the payer account, so the
exact 02:00-14:00 UTC windows still cannot be assigned billed cost without
estimating. The table below instead compares two observed operating days and
uses only instance types allowed by the corresponding profiler CEs. Counts are
successful profiler outputs recorded in the Nextflow logs; MetaPhlAn and
HUMAnN4 each count as one output per sample.

| Fleet/day | MetaPhlAn | HUMAnN4 | Profile outputs | Billed compute | Cost/output |
|---|---:|---:|---:|---:|---:|
| G4, Sep 19 | 2,517 | 3,385 | 5,902 | $165.475314 | $0.028037 |
| G5, Sep 20 | 5,509 | 5,156 | 10,665 | $217.118005 | $0.020358 |
| G5, Sep 21 | 4,448 | 4,447 | 8,895 | $192.167276 | $0.021604 |

On the clean Sep 19 versus Sep 20 day comparison, G5 produced 80.7% more
profile outputs and reduced billed compute cost per output by 27.4%, despite
31.2% higher total compute spend. The G5 profiler fleet billed $408.076974
across Sep 20-22 before the short-lived `r9g.24xlarge` allocation on Sep 21
was identified. Including it raises the current G5 profiler total to
$410.765941 (`c9g.24xlarge`, `r9g.24xlarge`, `c9g.48xlarge`, and
`m9gd.metal-48xl`). Sep 22 contributed only $1.480660 of that total.

MEDI is accounted separately. Its Sep 21-22 `r8gd.24xlarge` usage was
16.375555 instance-hours and $26.307124. In particular, the $17.776507
`r8gd.24xlarge` charge on Sep 21 is MEDI G4 cost and is excluded from all G5
profiler figures above. Cost Explorer still marks these recent days estimated,
meaning AWS may revise the billed values during finalization.

Profiler instance-type charges included above:

| Fleet/day | Instance type | Hours | Unblended cost |
|---|---|---:|---:|
| G4, Sep 19 | `c8g.12xlarge` | 152.379718 | $80.336964 |
| G4, Sep 19 | `c8g.metal-24xl` | 7.298056 | $8.570904 |
| G4, Sep 19 | `c8gn.48xlarge` | 33.407778 | $45.218388 |
| G4, Sep 19 | `m8g.metal-24xl` | 40.670279 | $18.573836 |
| G4, Sep 19 | `r8g.metal-24xl` | 17.641667 | $12.775223 |
| G5, Sep 20 | `c9g.24xlarge` | 138.893890 | $113.808407 |
| G5, Sep 20 | `c9g.48xlarge` | 23.796111 | $33.296617 |
| G5, Sep 20 | `m9gd.metal-48xl` | 47.593056 | $70.012982 |
| G5, Sep 21 | `c9g.24xlarge` | 123.669999 | $101.169996 |
| G5, Sep 21 | `r9g.24xlarge` | 2.180833 | $2.688967 |
| G5, Sep 21 | `c9g.48xlarge` | 20.791944 | $29.635560 |
| G5, Sep 21 | `m9gd.metal-48xl` | 39.070832 | $58.672753 |

### G5 queue allocation

Resource-level Cost Explorer access is unavailable. The following split
allocates the billed instance-type totals using measured instance lifetimes in
the two queue-specific Auto Scaling groups. Sep 20 has complete known instance
types. Sep 21's short-lived 96-vCPU replacements are allocated between queues
in proportion to their measured ASG instance-hours.

| Day | Queue | Outputs | Allocated billed compute | Cost/output |
|---|---|---:|---:|---:|
| Sep 20 | `spot-humann` | 5,156 | $159.608979 | $0.030956 |
| Sep 20 | `spot-metaphlan` | 5,509 | $57.509026 | $0.010439 |
| Sep 21 | `spot-humann` | 4,447 | $143.997358 | $0.032381 |
| Sep 21 | `spot-metaphlan` | 4,448 | $48.169918 | $0.010830 |

HUMAnN packed `c9g.24xlarge` nodes better: six 16-vCPU / 25-GiB jobs use
all 96 vCPUs, while MetaPhlAn's 36-GiB request allows five jobs and uses
80/96 vCPUs. Both queues fill all 192 vCPUs on `m9gd.metal-48xl` with 12 jobs.
HUMAnN still costs about three times as much per completed output because each
job runs substantially longer. A billed G4 split by queue is not recoverable:
resource IDs and cost-allocation tags were unavailable, and the old mixed G4
fleets used overlapping instance types. The combined Sep 19 G4 number remains
the directly billed value.

Small general/tiny-queue instances and non-profiler G4 types are excluded.
The source is AWS Cost Explorer queried 2026-09-22 with service
`Amazon Elastic Compute Cloud - Compute`, purchase type `Spot Instances`,
daily granularity, grouped by instance type.

## Trailing seven-day account EC2 cost

Window: Sep 16-22 UTC, with Sep 22 partial at query time. The user confirmed
the account activity in this window belongs to this work.

| Date | EC2 Compute | EC2-Other | Total |
|---|---:|---:|---:|
| Sep 16 | $14.634383 | $1,002.211191 | $1,016.845574 |
| Sep 17 | $22.030000 | $7.373671 | $29.403671 |
| Sep 18 | $47.634538 | $25.514576 | $73.149114 |
| Sep 19 | $189.345153 | $66.661110 | $256.006263 |
| Sep 20 | $232.392345 | $50.918776 | $283.311121 |
| Sep 21 | $225.916814 | $46.708567 | $272.625382 |
| Sep 22 partial | $12.758906 | $1.201611 | $13.960517 |
| **Total** | **$744.712140** | **$1,200.589501** | **$1,945.301641** |

EC2 Compute consists of $636.725285 Spot and $107.986855 On-Demand. EC2-Other
is dominated by a $996.67 `CapacityBlockFee:p5.48xlarge`, which is not disk
overhead or Spot fleet compute. Disk charges total $201.663237:

| Disk charge | Cost |
|---|---:|
| gp3 capacity | $110.722146 |
| gp3 provisioned IOPS | $49.413986 |
| gp3 provisioned throughput | $41.045284 |
| EBS snapshots | $0.481821 |
| **Disk total** | **$201.663237** |

Regional/data transfer contributes about $2.256264. Spot compute plus all
account disk overhead is $838.388522 for the seven-day window. Because EBS
cost-allocation tags are not enabled, that disk number is an account-wide
upper bound for the Spot queues rather than a directly billed queue-level
allocation.
