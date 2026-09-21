# TEDDY Graviton5 routing — 2026-09-20

Production queue names stay unchanged; no Nextflow G5 overlay needed.

| Queue | Compute environment | Max vCPUs | Bid cap |
|---|---|---:|---:|
| spot-humann | spot-humann-g5 | 960 | 50% |
| spot-metaphlan | spot-metaphlan-g5 | 300 | 50% |
| spot-queue | SpotComputeEnvironment-1dDk6WZcHIFWcOrb | 64 | 50% |

Both profiler CEs use `c9g.24xlarge`, `c9g.48xlarge`,
`m9gd.metal-48xl`, and `r9g.24xlarge`, with
`SPOT_PRICE_CAPACITY_OPTIMIZED`. Existing pinned launch-template version 6
retains benchmark-tested database staging. MEDI capacity and next-resume configuration are recorded below.

September 20 cheapest-AZ Spot quotes: respectively $0.6384, $1.2785, $1.3834,
and $0.7468 per VM-hour. These are price snapshots, not guaranteed placement
or measured speed for every type. The m/r types provide memory headroom:
MetaPhlAn requests 16 CPUs / 36 GiB, limiting c9g hosts to 5/10 tasks versus
6/12 CPU slots on the corresponding 96/192-vCPU memory-rich hosts.

Existing G4 CEs remain available but detached from the two production queues.
G5 CEs are API-managed, outside CloudFormation; existing dedicated G5 benchmark
queues also reference them, so concurrent benchmarks would share capacity.
`batch-stack.yaml` now references these existing G5 CE ARNs for production
routing and defaults short capacity to 64. No stack deployment performed.
Future deployments must retain `MaxvCPUsSpot=64` explicitly if the stack has an
older parameter value; changing the template default does not override it.

Regional Standard Spot quota checked: 1,200 vCPUs. Configured CE maxima total
1,624 including MEDI (1,324 with MEDI deferred); simultaneous full capacity remains quota-limited.
AWS Batch may exceed a CE max by up to one instance with this allocation
strategy; 64 is the configured short-pool maximum, not an absolute fleet cap.

Resume TEDDY with its existing config and
`-resume 75489d52-e5bc-45b5-bd46-1f68f41aea76` from the recorded checkout.
Do not apply `conf/aws_batch_g5.config`: it also changes short-job routing.
All reads retained; MEDI off for this pass, StrainPhlAn off. Later re-enable
MEDI and resume the same full cohort, preserving cache and S3 work.
No restart performed here.

## MetaPhlAn capacity increase — 2026-09-20

Raised live `spot-metaphlan-g5` max vCPUs from 200 to 300 while TEDDY runs.
Bid remains 50%. This scaling update does not require worker replacement or
Nextflow restart. Batch can add capacity as demand and Spot availability permit.

Deployment inputs match: `graviton5-capacity-2026-09-18/create-metaphlan-ce.json`
now specifies 300; `batch-stack.yaml` defaults `MaxvCPUsMetaphlan` to 300 for
its legacy CE. CloudFormation does not manage the production G5 CE. Reapply its
capacity independently when needed:

```bash
aws batch update-compute-environment --region us-east-2 \
  --compute-environment spot-metaphlan-g5 --compute-resources maxvCpus=300
```

## MEDI capacity — 2026-09-21

Updated live `spot-medi` CE `SpotMediComputeEnvironme-WW6oZWYdYGVBKXCV`:
max 300 vCPUs, min 0, bid unchanged at 50%. Final instance choices are
`r9gd.24xlarge` and `r8gd.24xlarge`, matching the user-edited template.
Both have 96 vCPUs / 768 GiB RAM and local NVMe. Kraken requests 8 CPUs /
8 GiB (16 GiB on retry): 12 jobs per node by CPU, leaving ample headroom
for the ~414 GiB shared hash. Three nodes provide 288 vCPUs / 36 slots.
Max 300 is not a three-node limit; Batch may overshoot by one instance.

MEDI is now enabled in the config for the next full-cohort resume, with
`skip_combine=true` to omit MetaPhlAn/HUMAnN cohort aggregation. MEDI's own
aggregation remains enabled. The running driver retains its original config.

AWS rejected both requested regional Spot limits (1,400 and 1,600) with
`ResourceAlreadyExistsException`: only one open request per quota. Existing
2,000-vCPU request remains open; current quota is 1,200.

Deployment: template default `MaxvCPUsMedi=300`; explicitly supply that
parameter on future stack updates (existing parameter values override defaults).
No full CloudFormation deployment performed.
