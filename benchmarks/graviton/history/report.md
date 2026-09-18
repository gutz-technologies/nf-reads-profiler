# Historical fastp memory audit

Read local historical Nextflow HTML reports on 2026-09-18. Extracted exact
peak_rss bytes, saved commands, requested memory, and native Batch job IDs.
Deduplicated repeated/cached reports by job ID. Successful attempts only in
the table; repeated executions of a sample remain distinct tasks.

| Cohort | Accuracy | Tasks | Median GiB | P95 GiB | Max GiB | Requested GiB |
|---|---|---:|---:|---:|---:|---|
| cosmosid-infant | 3 (default) | 1898 | 4.167 | 4.197 | 4.205 | [8.0] |
| gemma | 3 | 1353 | 4.241 | 4.264 | 4.278 | [8.0, 16.0] |
| gemma-smoke | 3 | 6 | 4.239 | 4.246 | 4.251 | [8.0] |
| gemma-smoke | 6 | 3 | 32.221 | 32.221 | 32.243 | [40.0] |
| null | 3 (default) | 200 | 4.199 | 4.208 | 4.211 | [8.0] |

The 3,457 successful accuracy-3 task executions all peaked below 4.28 GiB.
The three accuracy-6 smoke tasks peaked around 32.22–32.24 GiB; saved scripts
explicitly confirm accuracy 6, so these are not accuracy-3 outliers.
The `null` group is the historical report directory name, not a named cohort.

8 GiB is supported by prior successful runs, not merely a proposed estimate.
Existing runs-repo conf/gemma.config lines 175–184 already use 8 GiB at
accuracy 3 and document this fixed-memory behavior. The active G4 benchmark
loaded 16/32 GiB. User subsequently selected 8/16 GiB for future launches;
record this cleaning allocation difference in comparisons with the active G4 run.
Do not interpret failed/OOM peaks as measurements of successful memory needs.
RSS is sampled, not the complete container memory-accounting peak.

Sources and exact per-task values: fastp-task-memory.csv. Reproduce with
`python3 benchmarks/graviton/history/audit_fastp.py`. Summary: summary.json.
Read-only source reports are under
/home/ubuntu/gutz-nf-reads-profilers-runs/results/*/reports/.
