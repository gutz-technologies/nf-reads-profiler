# Minutes and dollars per million reads by VM

Placement and Spot rates affect cost, but these two runs cannot isolate VM family, CPU generation, cache, and placement effects on speed. This is a comparison of the observed configurations, not proof that placement alone caused the difference.

Normalization uses the configured input read cap (paired-input records/read pairs), not the number surviving cleaning. Minutes are elapsed profiler command minutes, not CPU-minutes. Dollars are the existing runtime-based CPU-share estimates, not the full instance bill. Every profiler requested 16 vCPUs. Small inputs have substantial fixed overhead; retain all five sizes instead of extrapolating a single linear rate.

## Measured workers

| Generation / profiler | VM type | EC2 ID | AZ |
|---|---|---|---|
| g4 / profile_taxa | m8g.metal-24xl | i-0d6f195921644a5d1 | us-east-2c |
| g4 / profile_function | m8g.metal-24xl | i-035550f957f0d940c | us-east-2c |
| g5 / profile_function | c9g.24xlarge | i-00c747c665b5f5996 | us-east-2c |
| g5 / profile_taxa | c9g.48xlarge | i-06683e5607459a50f | us-east-2a |

## Sweep averages

Each of the five input sizes (100k, 300k, 1m, 3m, 10m) has equal weight: mean(task minutes / input millions), and mean(task allocated dollars / input millions). These are arithmetic means of the five normalized measurements, not total runtime divided by total reads.

| Profiler | Generation / VM | Samples | Mean min / million | Mean estimated $ / million |
|---|---|---:|---:|---:|
| profile_function | g4 / m8g.metal-24xl | 5 | 10.174 | $0.01263 |
| profile_function | g5 / c9g.24xlarge | 5 | 8.747 | $0.01665 |
| profile_taxa | g4 / m8g.metal-24xl | 5 | 6.287 | $0.00970 |
| profile_taxa | g5 / c9g.48xlarge | 5 | 5.437 | $0.01415 |

## Measured normalization at every input size

| Profiler | Generation / VM | Input cap | min / million | estimated $ / million |
|---|---|---:|---:|---:|
| profile_function | g4 / m8g.metal-24xl | 100k | 27.534 | $0.03457 |
| profile_function | g5 / c9g.24xlarge | 100k | 23.771 | $0.04585 |
| profile_function | g4 / m8g.metal-24xl | 300k | 11.987 | $0.01478 |
| profile_function | g5 / c9g.24xlarge | 300k | 10.300 | $0.01943 |
| profile_function | g4 / m8g.metal-24xl | 1m | 5.251 | $0.00644 |
| profile_function | g5 / c9g.24xlarge | 1m | 4.456 | $0.00836 |
| profile_function | g4 / m8g.metal-24xl | 3m | 3.365 | $0.00408 |
| profile_function | g5 / c9g.24xlarge | 3m | 2.910 | $0.00540 |
| profile_function | g4 / m8g.metal-24xl | 10m | 2.735 | $0.00329 |
| profile_function | g5 / c9g.24xlarge | 10m | 2.300 | $0.00424 |
| profile_taxa | g4 / m8g.metal-24xl | 100k | 20.411 | $0.03199 |
| profile_taxa | g5 / c9g.48xlarge | 100k | 17.767 | $0.04562 |
| profile_taxa | g4 / m8g.metal-24xl | 300k | 7.097 | $0.01032 |
| profile_taxa | g5 / c9g.48xlarge | 300k | 6.190 | $0.01679 |
| profile_taxa | g4 / m8g.metal-24xl | 1m | 2.448 | $0.00405 |
| profile_taxa | g5 / c9g.48xlarge | 1m | 1.973 | $0.00559 |
| profile_taxa | g4 / m8g.metal-24xl | 3m | 0.994 | $0.00150 |
| profile_taxa | g5 / c9g.48xlarge | 3m | 0.833 | $0.00188 |
| profile_taxa | g4 / m8g.metal-24xl | 10m | 0.486 | $0.00062 |
| profile_taxa | g5 / c9g.48xlarge | 10m | 0.420 | $0.00086 |

## All current profiler-pool VM types: pricing scenario

These are projections, not measurements of every VM. For each generation and profiler, assume its measured sweep-average normalized runtime and Batch active duration apply unchanged to every VM in that generation. Apply the cheapest AZ quote from the saved 2026-09-18 pricing snapshots (latest quote per type/AZ). Placement and capacity are not guaranteed. This isolates the price effect under an explicit equal-speed-within-generation assumption. It does not measure family-specific performance. Generic/short-queue VMs do not run these profilers and are outside this table.

Projected dollars/million = mean(Batch active seconds / input millions) / 3600 × (16 / host vCPUs) × host Spot $/hour. All five sizes have equal weight. No idle-capacity or memory-packing adjustment; 36 GiB MetaPhlAn tasks can be memory-limited on c-series hosts.

| CE / profiler | VM | vCPUs | GiB | Cheapest AZ | Snapshot $/h | Assumed min/million | Projected $/million |
|---|---|---:|---:|---|---:|---:|---:|
| g5 / profile_taxa | c9g.24xlarge | 96 | 192 | us-east-2c | $0.6594 | 5.437 | $0.01340 |
| g5 / profile_taxa | c9g.48xlarge | 192 | 384 | us-east-2c | $1.3103 | 5.437 | $0.01332 |
| g5 / profile_taxa | m9gd.metal-48xl | 192 | 768 | us-east-2c | $1.3274 | 5.437 | $0.01349 |
| g4 / profile_function | c8g.12xlarge | 48 | 96 | us-east-2c | $0.4325 | 10.174 | $0.02537 |
| g4 / profile_function | c8g.48xlarge | 192 | 384 | us-east-2b | $1.6890 | 10.174 | $0.02477 |
| g4 / profile_function | c8g.metal-24xl | 96 | 192 | us-east-2b | $0.8687 | 10.174 | $0.02547 |
| g4 / profile_function | c8g.metal-48xl | 192 | 384 | us-east-2b | $0.7630 | 10.174 | $0.01119 |
| g4 / profile_function | c8gd.48xlarge | 192 | 384 | us-east-2b | $1.3094 | 10.174 | $0.01920 |
| g4 / profile_function | c8gn.48xlarge | 192 | 384 | us-east-2c | $1.4152 | 10.174 | $0.02075 |
| g4 / profile_function | m8g.metal-24xl | 96 | 384 | us-east-2c | $0.4308 | 10.174 | $0.01263 |
| g4 / profile_function | m8gd.metal-48xl | 192 | 768 | us-east-2a | $1.2909 | 10.174 | $0.01893 |
| g4 / profile_function | r8g.metal-24xl | 96 | 768 | us-east-2c | $0.7130 | 10.174 | $0.02091 |
| g4 / profile_function | r8g.metal-48xl | 192 | 1536 | us-east-2a | $1.1311 | 10.174 | $0.01658 |
| g5 / profile_function | c9g.24xlarge | 96 | 192 | us-east-2c | $0.6594 | 8.747 | $0.01665 |
| g5 / profile_function | c9g.48xlarge | 192 | 384 | us-east-2c | $1.3103 | 8.747 | $0.01655 |
| g4 / profile_taxa | c8g.12xlarge | 48 | 96 | us-east-2c | $0.4325 | 6.287 | $0.01947 |
| g4 / profile_taxa | c8g.48xlarge | 192 | 384 | us-east-2b | $1.6890 | 6.287 | $0.01901 |
| g4 / profile_taxa | c8g.metal-24xl | 96 | 192 | us-east-2b | $0.8687 | 6.287 | $0.01955 |
| g4 / profile_taxa | c8g.metal-48xl | 192 | 384 | us-east-2b | $0.7630 | 6.287 | $0.00859 |
| g4 / profile_taxa | c8gd.24xlarge | 96 | 192 | us-east-2a | $0.6796 | 6.287 | $0.01530 |
| g4 / profile_taxa | c8gd.48xlarge | 192 | 384 | us-east-2b | $1.3094 | 6.287 | $0.01474 |
| g4 / profile_taxa | c8gn.48xlarge | 192 | 384 | us-east-2c | $1.4152 | 6.287 | $0.01593 |
| g4 / profile_taxa | m8g.metal-24xl | 96 | 384 | us-east-2c | $0.4308 | 6.287 | $0.00970 |
| g4 / profile_taxa | m8gd.metal-48xl | 192 | 768 | us-east-2a | $1.2909 | 6.287 | $0.01453 |
| g4 / profile_taxa | r8g.metal-24xl | 96 | 768 | us-east-2c | $0.7130 | 6.287 | $0.01605 |
| g4 / profile_taxa | r8g.metal-48xl | 192 | 1536 | us-east-2a | $1.1311 | 6.287 | $0.01273 |
| g4 / profile_taxa | x8g.12xlarge | 48 | 768 | us-east-2c | $0.9941 | 6.287 | $0.04475 |
| g4 / profile_taxa | x8g.8xlarge | 32 | 512 | us-east-2a | $0.8108 | 6.287 | $0.05475 |

Sources: `task-results.csv`, saved job→ECS mappings and Spot history in `evidence/`, current pool membership in `evidence/current-profiler-pools.json`, and historical pricing/type snapshots in `infra/graviton5-capacity-2026-09-18/{humann,metaphlan}-costs/`. All pool rows use snapshot pricing consistently; the measured table uses actual placement pricing.
