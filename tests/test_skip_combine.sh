#!/usr/bin/env bash
# Preview real workflow graphs without executing tasks or needing reference DBs.
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
cat > "$test_dir/preview.config" <<'CONFIG'
process.executor = 'local'
docker.enabled = false
report.enabled = false
timeline.enabled = false
trace.enabled = false
CONFIG
for mode in default skip medi taxa; do
    args=()
    case "$mode" in
        skip) args=(--skip_combine true) ;;
        medi) args=(--skip_combine true --enable_medi true) ;;
        taxa) args=(--skip_combine true --enable_humann false) ;;
    esac
    nextflow -log "$test_dir/$mode.log" run main.nf -preview \
        -c "$test_dir/preview.config" --project skip-combine-test \
        --input assets/samplesheet-test-local.csv --outdir "$test_dir/results" \
        --skipCompleted false -with-dag "$test_dir/$mode.dot" \
        "${args[@]}" > "$test_dir/$mode.out" 2>&1 || {
            cat "$test_dir/$mode.out"; exit 1;
        }
    grep -q 'label="profile_taxa"' "$test_dir/$mode.dot"
    if [[ "$mode" != taxa ]]; then
        grep -q 'label="profile_function"' "$test_dir/$mode.dot"
    fi
    if [[ "$mode" == default ]]; then
        for process in combine_metaphlan_tables combine_humann_tables combine_humann_taxonomy_tables split_stratified_tables convert_tables_to_biom; do
            grep -q "label=\"$process\"" "$test_dir/$mode.dot"
        done
    else
        if grep -Eq 'label="(combine_metaphlan_tables|combine_humann_tables|combine_humann_taxonomy_tables|split_stratified_tables|convert_tables_to_biom|regroup_genefamilies)"' "$test_dir/$mode.dot"; then
            echo "Unexpected aggregation in $mode"; exit 1
        fi
    fi
    if [[ "$mode" == medi ]]; then
        grep -Eq 'label="(MEDI_QUANT:)?quantify"' "$test_dir/$mode.dot"
        grep -Eq 'label="(MEDI_QUANT:)?merge_taxonomy"' "$test_dir/$mode.dot"
    fi
    echo "PASS: $mode workflow graph"
done
