#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/github/nf-reads-profiler
run_dir=benchmarks/graviton/execution/g4
mkdir -p "$run_dir"
date -u +%FT%TZ > "$run_dir/started.txt"
set +e
nextflow -log "$run_dir/nextflow.log" run main.nf -c benchmarks/graviton/g4.config -name graviton_bench_g4_20260918_retry2 -ansi-log false > "$run_dir/console.log" 2>&1
run_status=$?
set -e
printf '%s\n' "$run_status" > "$run_dir/exit-code.txt"
date -u +%FT%TZ > "$run_dir/finished.txt"
# Archive driver logs on success or failure; preserve Nextflow's exit status.
archive_uri=s3://gutz-nf-reads-profilers-runs/results/graviton-benchmark-g4-20260918/execution/g4/
if ! aws s3 cp "$run_dir/" "$archive_uri" --recursive --region us-east-2 --only-show-errors; then
    echo "Log upload failed; local logs retained at $run_dir" >&2
    if [[ "$run_status" -eq 0 ]]; then run_status=1; fi
fi
exit "$run_status"
