# profile_function / HUMAnN compute environment prices

Snapshot: 2026-09-18T15:16:56Z. Region us-east-2; Linux/UNIX Spot USD/hour.

## SpotHumannComputeEnviron-oxqAp0dDXiodwz5e

State: ENABLED; desired vCPUs: 0; max vCPUs: 960; allocation strategy: SPOT_PRICE_CAPACITY_OPTIMIZED.

No registered ECS workers and no EC2 instance IDs belonging to this CE. A regional EC2 cross-check found only three nonterminated instances, none of an allowed HUMAnN type or tagged for HUMAnN.

| Allowed EC2 instance type ID | vCPUs | RAM GiB | us-east-2a | us-east-2b | us-east-2c | Spot USD/vCPU-hour range |
|---|---:|---:|---:|---:|---:|---:|
| c8g.12xlarge | 48 | 96 | 0.6174 | 0.6440 | 0.4325 | 0.009010–0.013417 |
| c8g.48xlarge | 192 | 384 | 1.7607 | 1.6890 | 1.7697 | 0.008797–0.009217 |
| c8gd.48xlarge | 192 | 384 | 1.3460 | 1.3094 | 1.3486 | 0.006820–0.007024 |
| c8g.metal-24xl | 96 | 192 | 1.0259 | 0.8687 | 1.1492 | 0.009049–0.011971 |
| c8g.metal-48xl | 192 | 384 | 1.0944 | 0.7630 | 1.5193 | 0.003974–0.007913 |
| c8gn.48xlarge | 192 | 384 | 1.4343 | 1.4662 | 1.4152 | 0.007371–0.007636 |
| m8g.metal-24xl | 96 | 384 | 0.6991 | 0.6961 | 0.4308 | 0.004488–0.007282 |
| m8gd.metal-48xl | 192 | 768 | 1.2909 | 1.4534 | 1.3396 | 0.006723–0.007570 |
| r8g.metal-24xl | 96 | 768 | 0.8237 | 1.6098 | 0.7130 | 0.007427–0.016769 |
| r8g.metal-48xl | 192 | 1536 | 1.1311 | 1.8008 | 1.7874 | 0.005891–0.009379 |

## spot-humann-g5

State: DISABLED; desired vCPUs: 0; max vCPUs: 960; allocation strategy: SPOT_PRICE_CAPACITY_OPTIMIZED.

No registered ECS workers and no EC2 instance IDs belonging to this CE. A regional EC2 cross-check found only three nonterminated instances, none of an allowed HUMAnN type or tagged for HUMAnN.

| Allowed EC2 instance type ID | vCPUs | RAM GiB | us-east-2a | us-east-2b | us-east-2c | Spot USD/vCPU-hour range |
|---|---:|---:|---:|---:|---:|---:|
| c9g.12xlarge | 48 | 96 | 0.7921 | 0.6242 | 0.4907 | 0.010223–0.016502 |
| c9g.24xlarge | 96 | 192 | 0.7960 | 0.9942 | 0.6594 | 0.006869–0.010356 |
| c9g.48xlarge | 192 | 384 | 1.3922 | 1.8135 | 1.3103 | 0.006824–0.009445 |
| c9g.metal-48xl | 192 | 384 | 1.3843 | 1.4817 | 1.5004 | 0.007210–0.007815 |
| c9gd.48xlarge | 192 | 384 | 1.5302 | 2.7645 | 1.6978 | 0.007970–0.014398 |
| m9g.24xlarge | 96 | 384 | 0.9994 | 1.2950 | 1.0426 | 0.010410–0.013490 |
| m9gd.metal-48xl | 192 | 768 | 1.8357 | 1.5782 | 1.3274 | 0.006914–0.009561 |
| r9g.24xlarge | 96 | 768 | 1.1351 | 1.7285 | 0.7931 | 0.008261–0.018005 |
| r9g.metal-48xl | 192 | 1536 | 1.5285 | 3.9798 | 1.5439 | 0.007961–0.020728 |

## Equal-vCPU comparison

| G4 / G5 pair | vCPUs each | us-east-2a savings | us-east-2b savings | us-east-2c savings |
|---|---:|---:|---:|---:|
| c8g.12xlarge / c9g.12xlarge | 48 | -28.3% | 3.1% | -13.5% |
| c8g.metal-24xl / c9g.24xlarge | 96 | 22.4% | -14.4% | 42.6% |
| c8g.48xlarge / c9g.48xlarge | 192 | 20.9% | -7.4% | 26.0% |
| c8g.metal-48xl / c9g.metal-48xl | 192 | -26.5% | -94.2% | 1.2% |
| c8gd.48xlarge / c9gd.48xlarge | 192 | -13.7% | -111.1% | -25.9% |
| m8g.metal-24xl / m9g.24xlarge | 96 | -43.0% | -86.0% | -142.0% |
| m8gd.metal-48xl / m9gd.metal-48xl | 192 | -42.2% | -8.6% | 0.9% |
| r8g.metal-24xl / r9g.24xlarge | 96 | -37.8% | -7.4% | -11.2% |
| r8g.metal-48xl / r9g.metal-48xl | 192 | -35.1% | -121.0% | 13.6% |

Positive savings = Graviton5 cheaper; negative = more expensive. Formula: 1 − (G5 hourly price / G4 hourly price), for equal vCPUs and assumed equal CPU speed. These pairs have matching RAM as well; some pair G4 metal with G5 virtualized shapes. c8gn.48xlarge has no direct G5 equivalent in this CE.

AWS Batch queues have no fixed hourly price. The actual bill depends on the EC2 type, selected AZ, occupied time, and changing Spot price. SPOT_PRICE_CAPACITY_OPTIMIZED may select a pool other than the cheapest quoted pool. Prices do not prove capacity availability. The configured bidPercentage is 50; it is a ceiling relative to On-Demand, not a flat 50% discount. These comparisons exclude startup/idle time, interruption overhead, packing, RAM limits, EBS, and transfer charges. No AWS resources changed.
