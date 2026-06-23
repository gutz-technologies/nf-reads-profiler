#!/usr/bin/env bash
# bin/scrape_last_local_log.sh

set -euo pipefail

LOG_FILE=".nextflow.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "Error: $LOG_FILE not found in the current directory." >&2
    exit 1
fi

echo "========================================="
echo "       Nextflow Run Status Summary       "
echo "========================================="

# 1. Run Metadata
RUN_NAME=$(sed -n 's/.*Run name: \([a-zA-Z0-9_-]*\).*/\1/p' "$LOG_FILE" | tail -n 1 || echo "Unknown")
SESSION_UUID=$(sed -n 's/.*Session UUID: \([a-f0-9-]*\).*/\1/p' "$LOG_FILE" | tail -n 1 || echo "Unknown")
START_TIME=$(head -n 1 "$LOG_FILE" | cut -d' ' -f1,2 || echo "Unknown")
COMMAND=$(sed -n 's/.* Launcher - $> \(.*\)/\1/p' "$LOG_FILE" | head -n 1 || echo "Unknown")

echo "Run Name:     $RUN_NAME"
echo "Session UUID: $SESSION_UUID"
echo "Start Time:   $START_TIME"
echo "Command:      $COMMAND"
echo "-----------------------------------------"

# 2. Status Assessment
IS_COMPLETE=false
IS_FAILED=false

if grep -q "Execution complete -- Goodbye" "$LOG_FILE"; then
    IS_COMPLETE=true
fi

if grep -q -E "ERROR nextflow|Workflow failed" "$LOG_FILE"; then
    IS_FAILED=true
fi

if [ "$IS_COMPLETE" = true ] && [ "$IS_FAILED" = false ]; then
    echo "Status:       COMPLETED SUCCESSFULLY"
elif [ "$IS_FAILED" = true ]; then
    echo "Status:       FAILED"
else
    echo "Status:       IN PROGRESS"
fi
echo "-----------------------------------------"

# 3. Process Task Counts (Succeeded, Cached, Failed, Active)
awk '
/Cached process >/ {
    match($0, /Cached process > .*/)
    name_raw = substr($0, RSTART + 17, RLENGTH - 17)
    split(name_raw, name_arr, " \\(")
    name_part = name_arr[1]
    sub(/ *$/, "", name_part)
    cached[name_part]++
    all_processes[name_part] = 1
}
/Submitted process >/ {
    match($0, /Submitted process > .*/)
    name_raw = substr($0, RSTART + 20, RLENGTH - 20)
    split(name_raw, name_arr, " \\(")
    name_part = name_arr[1]
    sub(/ *$/, "", name_part)
    submitted[name_part]++
    all_processes[name_part] = 1
}
/Task completed > TaskHandler/ {
    # Extract name
    match($0, /name: [^;]+/)
    name_raw = substr($0, RSTART + 6, RLENGTH - 6)
    split(name_raw, name_arr, " \\(")
    name_part = name_arr[1]
    sub(/ *$/, "", name_part)

    # Extract exit code
    match($0, /exit: [^;]+/)
    exit_part = substr($0, RSTART + 6, RLENGTH - 6)

    # Extract status
    match($0, /status: [^;]+/)
    status_part = substr($0, RSTART + 8, RLENGTH - 8)

    if (submitted[name_part] > 0) {
        submitted[name_part]--
    }

    if (exit_part == "0" && (status_part == "COMPLETED" || status_part == "SUCCESS")) {
        succeeded[name_part]++
    } else {
        failed[name_part]++
    }
    all_processes[name_part] = 1
}
END {
    # Sort and print process table
    printf "%-35s %-11s %-10s %-10s %-10s\n", "Process Name", "Succeeded", "Cached", "Failed", "Active"
    print "--------------------------------------------------------------------------------"
    PROCINFO["sorted_in"] = "@ind_str_asc"
    for (p in all_processes) {
        s = succeeded[p] ? succeeded[p] : 0
        c = cached[p] ? cached[p] : 0
        f = failed[p] ? failed[p] : 0
        act = submitted[p] ? submitted[p] : 0
        printf "%-35s %-11d %-10d %-10d %-10d\n", p, s, c, f, act
    }
}
' "$LOG_FILE"
echo "========================================="
