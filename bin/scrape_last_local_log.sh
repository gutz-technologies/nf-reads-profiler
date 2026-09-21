#!/usr/bin/env bash
# Summarize a Nextflow driver log; task work directories may be local or S3.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: scrape_last_local_log.sh [LOG_FILE | s3://BUCKET/KEY | -]

Without an argument, select the newest .nextflow.log or *.nextflow.log in
this directory. Use an explicit path for other custom `nextflow -log` names.
S3 input requires AWS CLI read access; - reads a finite driver log from stdin.
Reads a snapshot, not a live follow. Use the DEBUG driver log, not console/tee
output: console output does not contain task completion records.

Examples:
  bin/scrape_last_local_log.sh
  bin/scrape_last_local_log.sh teddy-srp154926.nextflow.log
  bin/scrape_last_local_log.sh /path/to/.nextflow.log
  aws s3 cp s3://bucket/run.nextflow.log - | bin/scrape_last_local_log.sh -
HELP
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    usage
    exit 0
fi
if (( $# > 1 )); then
    usage >&2
    exit 2
fi
SOURCE=${1:-}
if [[ -z $SOURCE ]]; then
    shopt -s nullglob
    for candidate in .nextflow.log *.nextflow.log; do
        if [[ -f $candidate && ( -z $SOURCE || $candidate -nt $SOURCE ) ]]; then
            SOURCE=$candidate
        fi
    done
    if [[ -z $SOURCE ]]; then
        echo 'Error: no .nextflow.log or *.nextflow.log found; pass a driver log path.' >&2
        exit 1
    fi
fi

LOG_FILE=$(mktemp)
trap 'rm -f -- "$LOG_FILE"' EXIT
case "$SOURCE" in
    -) cat > "$LOG_FILE" ;;
    s3://*) aws s3 cp "$SOURCE" "$LOG_FILE" --only-show-errors ;;
    *)
        if [[ ! -f $SOURCE || ! -r $SOURCE ]]; then
            echo "Error: cannot read driver log: $SOURCE" >&2
            exit 1
        fi
        cat -- "$SOURCE" > "$LOG_FILE"
        ;;
esac
if [[ ! -s $LOG_FILE ]]; then
    echo "Error: driver log is empty: $SOURCE" >&2
    exit 1
fi
if ! grep -Eq 'DEBUG .*nextflow|DEBUG n\.(processor|trace|c\.)' "$LOG_FILE"; then
    echo 'Error: no Nextflow DEBUG records found. Pass the driver log, not console/tee output.' >&2
    exit 1
fi

printf '=========================================\n'
printf '       Nextflow Run Status Summary\n'
printf '=========================================\n'
printf 'Log source:   %s\n' "$SOURCE"

awk '
function field(line, key, value) {
    value = line
    sub(".*" key ": ", "", value)
    sub(/;.*/, "", value)
    return value
}
function process_name(value) {
    sub(/ \(.*/, "", value)
    sub(/[[:space:]]+$/, "", value)
    return value
}
# A concatenated stream may contain multiple launches. Summarize only the last.
/DEBUG nextflow.cli.Launcher - \$>/ {
    delete succeeded; delete cached; delete failed; delete submitted
    delete all_processes; delete completed_ids
    run_name = uuid = workdir = ""
    ended = errors = aborted = 0
    start = $1 " " $2
    command = $0
    sub(/.*Launcher - \$> /, "", command)
}
NR == 1 { if (!start) start = $1 " " $2 }
/Run name: / { run_name = $0; sub(/.*Run name: /, "", run_name) }
/Session UUID: / { uuid = $0; sub(/.*Session UUID: /, "", uuid) }
/Work-dir: / { workdir = $0; sub(/.*Work-dir: /, "", workdir) }
/Execution complete -- Goodbye/ { ended = 1 }
/(^|[[:space:]])ERROR[[:space:]]+(nextflow|n\.)|Workflow failed/ { errors = 1 }
/Session aborted|Session abort|SIGINT|SIGTERM/ { aborted = 1 }
/Cached process > / {
    name = $0; sub(/.*Cached process > /, "", name)
    name = process_name(name)
    cached[name]++; all_processes[name] = 1
}
/(Submitted|Re-submitted) process > / {
    name = $0; sub(/.*(Submitted|Re-submitted) process > /, "", name)
    name = process_name(name)
    submitted[name]++; all_processes[name] = 1
}
/Task completed > TaskHandler/ {
    # IDs identify attempts; repeated completion lines must not double count.
    id = field($0, "id")
    if (completed_ids[id]++) next
    name = process_name(field($0, "name"))
    code = field($0, "exit")
    state = field($0, "status")
    submitted[name]--
    if (code == "0" && (state == "COMPLETED" || state == "SUCCESS"))
        succeeded[name]++
    else
        failed[name]++
    all_processes[name] = 1
}
END {
    printf "Run Name:     %s\n", run_name ? run_name : "Unknown"
    printf "Session UUID: %s\n", uuid ? uuid : "Unknown"
    printf "Start Time:   %s\n", start ? start : "Unknown"
    printf "Command:      %s\n", command ? command : "Unknown"
    printf "Work-dir:     %s\n", workdir ? workdir : "Unknown"
    print "-----------------------------------------"
    if (aborted) print "Status:       ABORT OBSERVED"
    else if (errors) print "Status:       ERROR OBSERVED (check driver log)"
    else if (ended) print "Status:       ENDED (no error/abort marker observed)"
    else print "Status:       NO END MARKER (may be running; liveness not checked)"
    print "-----------------------------------------"
    printf "%-35s %-11s %-10s %-10s %-10s\n", "Process Name", "Succeeded", "Cached", "Failed", "Pending"
    print "--------------------------------------------------------------------------------"
    # Sort portably; PROCINFO[sorted_in] only works with GNU awk.
    n = 0
    for (p in all_processes) {
        j = ++n
        while (j > 1 && names[j-1] > p) { names[j] = names[j-1]; j-- }
        names[j] = p
    }
    for (i = 1; i <= n; i++) {
        p = names[i]
        pending = submitted[p] > 0 ? submitted[p] : 0
        printf "%-35s %-11d %-10d %-10d %-10d\n", p, succeeded[p], cached[p], failed[p], pending
    }
    if (!n) print "No task events found in this snapshot."
    print "========================================="
    print "Counts cover logged attempts, including retries; not unique samples."
    print "Pending = submitted without logged completion (queued + starting + running)."
    print "Not live AWS counts. Truncated/rotated logs may omit task events."
}
' "$LOG_FILE"
