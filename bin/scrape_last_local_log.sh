#!/usr/bin/env bash
# bin/scrape_last_local_log.sh
# Google Gemini 3.5 Flash with an example .nextflow.log file

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
    echo "Status:       IN PROGRESS (or interrupted)"
fi
echo "-----------------------------------------"

# 3. Stats Generation
STATS_LINE=$(grep "WorkflowStats\[" "$LOG_FILE" | tail -n 1 || true)

if [ -n "$STATS_LINE" ]; then
    # Parse final stats from completed run
    SUCCEEDED=$(echo "$STATS_LINE" | sed -n 's/.*succeededCount=\([0-9]*\).*/\1/p' || echo 0)
    FAILED=$(echo "$STATS_LINE" | sed -n 's/.*failedCount=\([0-9]*\).*/\1/p' || echo 0)
    CACHED=$(echo "$STATS_LINE" | sed -n 's/.*cachedCount=\([0-9]*\).*/\1/p' || echo 0)
    DURATION=$(echo "$STATS_LINE" | sed -n 's/.*succeedDuration=\([^;]*\).*/\1/p' || echo "Unknown")
    PEAK_CPUS=$(echo "$STATS_LINE" | sed -n 's/.*peakCpus=\([0-9]*\).*/\1/p' || echo "Unknown")
    PEAK_MEM=$(echo "$STATS_LINE" | sed -n 's/.*peakMemory=\([^;]*\).*/\1/p' || echo "Unknown")

    echo "Succeeded Tasks: $SUCCEEDED"
    echo "Cached Tasks:    $CACHED"
    echo "Failed Tasks:    $FAILED"
    echo "Total Duration:  $DURATION"
    echo "Peak CPUs:       $PEAK_CPUS"
    echo "Peak Memory:     $PEAK_MEM"
else
    # Parse live progress for active run
    CACHED=$(grep -c "Cached process >" "$LOG_FILE" || echo 0)
    SUBMITTED=$(grep -c "Submitted process >" "$LOG_FILE" || echo 0)
    COMPLETED=$(grep -c "Task completed >" "$LOG_FILE" || echo 0)
    FAILED=$(grep -c -E "Task failed >|exit: [1-9]" "$LOG_FILE" || echo 0)
    ACTIVE_TASKS=$(grep "tasks to be completed:" "$LOG_FILE" | tail -n 1 | sed -n 's/.*tasks to be completed: \([0-9]*\).*/\1/p' || echo 0)

    echo "Cached Tasks:    $CACHED"
    echo "Submitted Tasks: $SUBMITTED"
    echo "Completed Tasks: $COMPLETED"
    echo "Failed Tasks:    $FAILED"
    echo "Active Tasks (last check): $ACTIVE_TASKS"
fi

# 4. Recent Activity (Last 5 events)
echo "-----------------------------------------"
echo "Recent Actions:"
grep -E "Task completed >|Task failed >|Submitted process >|Cached process >" "$LOG_FILE" | tail -n 5 | \
    sed -E 's/.*(Task completed >|Task failed >|Submitted process >|Cached process > )/\1/' || \
    echo "No recent task events found."
echo "========================================="