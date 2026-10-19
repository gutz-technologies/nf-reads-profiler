#!/bin/bash
# COMPLETED profile_taxa + profile_function + MEDI_QUANT:kraken + StrainPhlAn
# (sample2markers/print_clades/extract_markers/strainphlan) stats,
# summarized by process then date.
set -euo pipefail

# Trace files now land on S3 at <outdir>/<project>/reports/<ts>_trace.txt (was
# ../results_local_logs before reports moved to S3). The runs bucket is FUSE-mounted
# on the runner VM, so point at that mount. Pass a different results root as $1.
# The <project>/reports/<trace> layout is unchanged, so the project-from-path logic below still holds.
SCRIPT_DIR="${1:-/home/ubuntu/gutz-nf-reads-profilers-runs/results}"
[ -d "$SCRIPT_DIR" ] || { echo "results dir not found: $SCRIPT_DIR (pass one as \$1)" >&2; exit 1; }

RAW=$(mktemp --suffix=.tsv)
CUT=$(mktemp --suffix=.tsv)
NUM=$(mktemp --suffix=.tsv)
SUMMARY=$(mktemp --suffix=.tsv)
trap "rm -f $RAW $CUT $NUM $SUMMARY" EXIT

# Build raw table: project + trace_file prepended + all NF trace columns
printf "project\ttrace_file\t" > "$RAW"
find "$SCRIPT_DIR" -name "*_trace.txt" -type f | sort | head -1 | xargs head -1 >> "$RAW"

find "$SCRIPT_DIR" -name "*_trace.txt" -type f | sort | while read -r f; do
    project=$(basename "$(dirname "$(dirname "$f")")")
    grep -E "profile_taxa|profile_function|kraken|sample2markers|print_clades|extract_markers|strainphlan" "$f" \
        | grep -v "kraken_report" \
        | grep "COMPLETED" \
        | sed "s|^|${project}\t$(basename "$f")\t|" || true
done >> "$RAW"

# Keep only the columns we need
csvtk -t cut -f project,trace_file,name,realtime,'%cpu',peak_rss "$RAW" > "$CUT"

# Convert human-readable units to plain numbers: realtime→minutes, strip % and GB
awk -F'\t' 'BEGIN { OFS="\t" }
function parse_time(t,    val) {
    val = 0
    if (match(t, /[0-9]+h/)) val += substr(t, RSTART, RLENGTH-1) * 3600
    if (match(t, /[0-9]+m/)) val += substr(t, RSTART, RLENGTH-1) * 60
    if (match(t, /[0-9]+s/)) val += substr(t, RSTART, RLENGTH-1)
    return val / 60
}
NR==1 { print "project", "process", "sample", "realtime_min", "cpu_pct", "rss_gb"; next }
$6 == "-" { next }
{
    proc = $3; sub(/ \(.*\)/, "", proc)
    cpu = $5; gsub(/%/, "", cpu)
    rss = $6; gsub(/ GB/, "", rss)
    printf "%s\t%s\t%s\t%.2f\t%.1f\t%.2f\n",
        $1, proc, $3, parse_time($4), cpu+0, rss+0
}' "$CUT" > "$NUM"

# Summarize by process + project
csvtk -t summary -g process,project \
    -f sample:count,realtime_min:mean,realtime_min:max,cpu_pct:mean,cpu_pct:min,rss_gb:mean,rss_gb:max \
    "$NUM" > "$SUMMARY"

# Print each process as its own section
csvtk -t cut -f process "$SUMMARY" | tail -n +2 | sort -u | while read -r proc; do
    printf "\n=== %s ===\n" "$proc"
    csvtk -t grep -f process -p "$proc" "$SUMMARY" \
        | csvtk -t cut -f project,'sample:count','realtime_min:mean','realtime_min:max','cpu_pct:mean','cpu_pct:min','rss_gb:mean','rss_gb:max' \
        | csvtk -t pretty
done
