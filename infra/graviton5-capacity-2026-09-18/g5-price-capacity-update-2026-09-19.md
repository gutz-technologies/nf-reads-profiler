# G5 Spot price and queue-depth update — 2026-09-19

Read-only EC2 Spot-price snapshot for `us-east-2`, Linux/UNIX. The latest
returned price per type/AZ was used; the individual samples range from
2026-09-18T18:00Z through 2026-09-19T02:00Z. No Spot placement-score request
was made, so this update did not consume the daily distinct-configuration
allowance.

The configured CE ceilings are `spot-metaphlan-g5` = 200 vCPUs and
`spot-humann-g5` = 960 vCPUs. `Nodes at CE ceiling` is `floor(maxvCpus / node
vCPUs)`: it is the maximum whole-node depth within the stated ceiling, not a
capacity guarantee. `CE floor cost` is that node count multiplied by the
lowest current AZ price. It intentionally represents only the usable whole
nodes under the ceiling, not an estimate of the application bill.

| Type | vCPU / GiB | 2a $/h | 2b $/h | 2c $/h | Best $/vCPU-h | MetaPhlAn: nodes / vCPUs / floor $/h | HUMAnN: nodes / vCPUs / floor $/h |
|---|---:|---:|---:|---:|---:|---:|---:|
| c9g.12xlarge | 48 / 96 | 0.7973 | 0.6297 | 0.4877 | 0.010160 | 4 / 192 / 1.9508 | 20 / 960 / 9.7540 |
| c9g.24xlarge | 96 / 192 | 0.8019 | 1.0013 | 0.6443 | 0.006711 | 2 / 192 / 1.2886 | 10 / 960 / 6.4430 |
| c9g.48xlarge | 192 / 384 | 1.3966 | 1.7745 | 1.2956 | 0.006748 | 1 / 192 / 1.2956 | 5 / 960 / 6.4780 |
| c9g.metal-48xl | 192 / 384 | 1.3825 | 1.4553 | 1.5431 | 0.007201 | 1 / 192 / 1.3825 | 5 / 960 / 6.9125 |
| c9gd.24xlarge | 96 / 192 | 0.7585 | 1.0645 | 0.7665 | 0.007901 | 2 / 192 / 1.5170 | — (not in HUMAnN pool) |
| c9gd.48xlarge | 192 / 384 | 1.5611 | 2.7266 | 1.6813 | 0.008131 | 1 / 192 / 1.5611 | 5 / 960 / 7.8055 |
| m9g.24xlarge | 96 / 384 | 0.9884 | 1.3091 | 1.0659 | 0.010296 | 2 / 192 / 1.9768 | 10 / 960 / 9.8840 |
| m9gd.metal-48xl | 192 / 768 | 1.8056 | 1.5530 | 1.3387 | 0.006972 | 1 / 192 / 1.3387 | 5 / 960 / 6.6935 |
| r9g.24xlarge | 96 / 768 | 1.1387 | 1.7682 | 0.7788 | 0.008113 | 2 / 192 / 1.5576 | 10 / 960 / 7.7880 |
| r9g.metal-48xl | 192 / 1536 | 1.4949 | 3.9988 | 1.4977 | 0.007786 | 1 / 192 / 1.4949 | 5 / 960 / 7.4745 |

## Implications for the leading compute shapes

- `c9g.24xlarge` is currently the lowest normalized-price choice
  ($0.006711/vCPU-hour) and provides 10 nodes for HUMAnN and 2 whole nodes for
  MetaPhlAn. It is the depth-preserving choice among the three leading shapes.
- `c9g.48xlarge` is essentially tied on price ($0.006748/vCPU-hour, only
  0.55% above `c9g.24xlarge`) but reduces HUMAnN to 5 nodes and MetaPhlAn to a
  single 192-vCPU node within its 200-vCPU ceiling.
- `c9g.metal-48xl` costs 7.30% more per vCPU than `c9g.24xlarge` at this
  snapshot and has the same 5-node/1-node depth profile as `c9g.48xlarge`.

The MetaPhlAn ceiling cannot be exactly filled by any listed node size: its
largest whole-node allocation is 192 vCPUs. AWS Batch can in some situations
temporarily exceed a CE's maximum by one instance, but that behavior must not
be used as a capacity plan. In particular, two 192-vCPU nodes would be 384
vCPUs, almost twice the configured ceiling. `SPOT_PRICE_CAPACITY_OPTIMIZED`
may select a non-cheapest type/AZ, so these are price and depth references,
not guaranteed launch prices or hourly costs.
