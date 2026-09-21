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
