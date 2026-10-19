#!/usr/bin/env nextflow
/*
 * preprocess_gemma.nf -- stage 1 of the GEMMA cohort (see
 * s3://gutz-nf-reads-profilers-runs/playbooks/gemma.md and
 * infra/gemma-onboarding-plan.md).
 *
 * GEMMA arrives as multiple FASTQ pairs per biological sample (flowcell x lane,
 * 1-8 pairs each). This workflow merges each sample's lanes into ONE R1/R2 pair
 * in S3; main.nf then runs against plain samplesheets with no code change.
 *
 * THE DEPTH CAP LIVES HERE, not in fastp. Two batches (under8g/over8g, split on
 * total sample bytes), ONE code path, mode chosen per sample:
 *   total est pairs <= cap  -> `cat`: plain concatenation of every lane
 *   total est pairs >  cap  -> `proportional`: lane i contributes
 *                              round(p_i * cap / P) reads, taken by SYSTEMATIC
 *                              stride across the whole lane (gemma_take_pairs.py)
 * Proportional is a no-op below the cap, so a misclassified borderline sample
 * still gets the right answer.
 *
 * Why the cap cannot be left to fastp: `fastp --reads_to_process` is HEAD
 * TRUNCATION, not subsampling. On a concatenated multi-flowcell file it takes
 * the first lanes and drops the rest, baking the flowcell batch effect into the
 * reads -- two-thirds of GEMMA samples span multiple flowcells, and measured on
 * the 12 samples a 50M-pair cap actually binds on, 3 would lose a whole flowcell.
 * Even within one lane a prefix is a spatial slice of the flowcell, which is why
 * the per-lane share is taken by stride rather than as a prefix. The stage-2 run
 * therefore sets nreads = 0 (no cap) and profiles what this workflow produced.
 *
 * Why still emit a real R1/R2 PAIR: one pre-concatenated file flips
 * meta.single_end true, which reinterprets --reads_to_process as reads instead of
 * pairs (half the intended depth cohort-wide) and loses pair-aware --dedup.
 * R1 and R2 are cut at the same record COUNT and the same record INDICES --
 * selection depends only on record number, never on content -- so positional
 * correspondence survives.
 *
 * Why dedup is NOT done here, per lane, before sampling: GEMMA's extra flowcells
 * are RE-SEQUENCING of the same library, so the duplicates that matter are
 * cross-flowcell, which per-lane dedup cannot see. It stays where it is, in
 * clean_reads' `fastp --dedup` over the merged pair. Measured duplication on the
 * finished under8g run is 3.8-6.1%, so sampling first and deduping second costs
 * a few percent of the target depth, not a meaningful fraction.
 *
 * Nothing touches local disk: each lane is streamed S3 -> stdout -> S3 multipart
 * upload. In the `cat` path no byte is decompressed (gzip members concatenate
 * natively); the proportional path decompresses the WHOLE lane -- that is the
 * price of an unbiased sample, and it is paid by very few samples.
 *
 * Usage (from the repo root, in screen):
 *   nextflow run preprocess_gemma.nf \
 *     -c conf/aws_batch.config \
 *     --project gemma --cap 50000000 \
 *     --manifest /home/ubuntu/github/globus_2026/s3-to-s3/gemma_manifest_under8g.tsv
 *
 * Add `--dry_run` to plan without transferring, or
 * `--samples GMA_015,sGMA_378` to run a smoke slice.
 *
 * Re-running after a CAP CHANGE is safe with --skip_existing true: the skip
 * check compares the previously published plan (mode + planned pairs, read back
 * from the per-sample log) against the plan this run would execute, so samples
 * whose output would be byte-identical are skipped and only the ones the new cap
 * actually binds on are redone. See the skip logic inline below.
 */

nextflow.enable.dsl = 2

params.manifest      = null
params.outprefix     = 's3://gutz-nf-reads-profilers-workdir/preprocessed/gemma'
params.logdir        = 's3://gutz-nf-reads-profilers-runs/results/gemma/preprocess'
params.cap           = 50000000   // PAIRS. THE cohort depth cap -- stage 2 runs
                                  // uncapped (nreads = 0) against what this emits,
                                  // so this is the only place depth is limited.
                                  // 0 = NO CAP: every lane is cat'd whole.
params.samples       = ''         // comma-separated subset (smoke slice); empty = all
params.skip_existing = true       // skip samples whose R1+R2 are already in S3
params.dry_run       = false
params.docker_container_aws = '730883236839.dkr.ecr.us-east-2.amazonaws.com/aws-cli-bash:2'

/*
 * Merge one sample's lanes into a single R1/R2 pair in S3.
 *
 * The FASTQ pair is uploaded by the task itself rather than declared as a
 * Nextflow output: the cohort is 5.55 TiB and an output path would land a second
 * full copy in the S3 workDir before publishDir copied it again. The declared
 * output is the per-sample log. Consequence: `-resume` trusts the task cache, not
 * the objects -- if a published FASTQ is deleted (the workdir bucket has a 30-day
 * lifecycle, same gotcha CLAUDE.md documents for the main pipeline's workDir) a
 * resume will NOT notice: the cached task is reported complete even though its
 * output no longer exists in S3. This is inherent to the no-double-copy design
 * above, not fixable by adding an `output:` block without reintroducing that
 * second full copy -- so it is intentionally NOT routed through Nextflow's own
 * cache. Real recovery instead goes through --skip_existing (see its S3 existence
 * + integrity check inline below), which talks to S3 directly and is independent
 * of -resume/task-cache state entirely. If the 30-day window has already passed
 * on a `-resume` attempt, don't trust -resume for this workflow at all -- do a
 * fresh (non-resumed) run with --skip_existing true instead.
 */
process GEMMA_MERGE_LANES {
    tag "${meta.id}"
    container params.docker_container_aws

    publishDir { "${params.logdir}/${meta.run}" }, mode: 'copy', pattern: "*.preprocess.tsv"

    input:
    tuple val(meta), val(spec)

    output:
    tuple val(meta), path("${meta.id}.preprocess.tsv"), emit: log

    script:
    def out1 = "${params.outprefix}/${meta.run}/${meta.id}_R1.fastq.gz"
    def out2 = "${params.outprefix}/${meta.run}/${meta.id}_R2.fastq.gz"
    """
    set -euo pipefail

    # lanes.tsv: key  r1_uri  r2_uri  est_pairs  bytes_r1  bytes_r2
    cat > lanes.tsv <<'LANESPEC'
${spec}
LANESPEC

    CAP=${params.cap}
    TOTAL=\$(awk -F'\\t' '{s+=\$4} END{print s+0}' lanes.tsv)
    NLANES=\$(wc -l < lanes.tsv)

    # CAP=0 means no cap at all -- every sample takes the cat path.
    if [ "\$CAP" -le 0 ] || [ "\$TOTAL" -le "\$CAP" ]; then MODE=cat; else MODE=proportional; fi

    # PLAN_MODE is what the plan SAYS to do; MODE is what this task actually did
    # (it may become skipped/dry_run below). The published log carries both, so a
    # later run's skip check can tell "this object was built proportionally" from
    # "the task that last touched this sample decided to skip".
    PLAN_MODE=\$MODE

    # plan.tsv adds k = pairs to take from this lane (all of them below the cap)
    awk -F'\\t' -v cap="\$CAP" -v tot="\$TOTAL" 'BEGIN{OFS="\\t"}
        { k = (cap <= 0 || tot <= cap) ? \$4 : int(\$4 * cap / tot + 0.5); print \$0, k }' \\
        lanes.tsv > plan.tsv

    PLANNED_TOTAL=\$(awk -F'\\t' '{s+=\$7} END{print s+0}' plan.tsv)

    # Expected upload sizes drive the multipart chunk size: without them the CLI
    # assumes a small object, caps at 10000 parts of 8 MB and dies at 80 GB.
    # GMA_353 alone is 104 GiB.
    EXP1=\$(awk -F'\\t' '{s += \$5 * \$7 / (\$4 ? \$4 : 1)} END{printf "%d", s+1}' plan.tsv)
    EXP2=\$(awk -F'\\t' '{s += \$6 * \$7 / (\$4 ? \$4 : 1)} END{printf "%d", s+1}' plan.tsv)

    # EXP scales the SOURCE bytes by the kept fraction, which is exact for `cat`
    # but understates `proportional`: that path recompresses at gzip level 1,
    # looser than the source. Undershooting --expected-size is the dangerous
    # direction (too few, too small parts -> the 10000-part ceiling), so the
    # upload hint carries 30% slack. The skip check keeps using the unslacked
    # EXP as its lower bound.
    UP1=\$EXP1
    UP2=\$EXP2
    if [ "\$MODE" = "proportional" ]; then
        UP1=\$(( EXP1 * 13 / 10 ))
        UP2=\$(( EXP2 * 13 / 10 ))
    fi

    # skip_existing has to answer two different questions, and size alone can
    # only answer the first:
    #
    #  1. IS THE OBJECT COMPLETE? An interrupted `aws s3 cp - <key>` streaming
    #     upload still lands a truncated object at the key, and a bare
    #     `aws s3 ls` exit-0 check would then skip that sample forever. This is
    #     the ONLY integrity check we get -- see the -resume note above the
    #     process: Nextflow's own cache doesn't track these FASTQs. In `cat`
    #     mode the output is raw gzip-member concatenation, so EXP1/EXP2 are
    #     EXACT and a two-sided 5% band is a strong signal.
    #
    #  2. WAS IT BUILT TO THE SAME PLAN? Size cannot tell: a sample whose cap
    #     now binds at 92% (GMA_1127) would have an uncapped object only 9%
    #     larger than the capped one -- inside any tolerance wide enough to
    #     survive gzip-level differences. So provenance is read back from the
    #     PUBLISHED per-sample log instead, which records the mode and the
    #     planned pair count of the run that wrote the object. A cat-mode
    #     object is byte-identical no matter which cap produced it (cap 0 and
    #     cap 50M both cat a 20M-pair sample), so cat mode needs only check 1;
    #     proportional mode additionally requires the previous plan to match.
    #     Effect: re-running the whole cohort after a cap change redoes exactly
    #     the samples the new cap binds on.
    #
    # Every command here is guarded against `set -e`/pipefail: a missing object
    # or missing log is the normal case on a first run, not an error.
    MIN_OK_BYTES=1000
    SIZE1=\$(aws s3 ls "${out1}" 2>/dev/null | awk '{print \$3}' || true)
    SIZE2=\$(aws s3 ls "${out2}" 2>/dev/null | awk '{print \$3}' || true)
    SIZE1=\${SIZE1:-0}
    SIZE2=\${SIZE2:-0}

    PREV=\$(aws s3 cp "${params.logdir}/${meta.run}/${meta.id}.preprocess.tsv" - 2>/dev/null | sed -n '2p' || true)
    # Column 8 (plan_mode) is what the object was BUILT as; column 3 is what that
    # task did. Logs written before plan_mode existed have an empty column 8,
    # which reads as unknown -- safe, because unknown only ever forces a rebuild.
    PREV_PLAN_MODE=\$(printf '%s' "\$PREV" | cut -f8)
    PREV_PLANNED=\$(printf '%s' "\$PREV" | cut -f7)
    PREV_PLAN_MODE=\${PREV_PLAN_MODE:-unknown}
    PREV_PLANNED=\${PREV_PLANNED:-0}

    SIZE_OK=no
    if [ "\$SIZE1" -ge "\$MIN_OK_BYTES" ] && [ "\$SIZE2" -ge "\$MIN_OK_BYTES" ] \\
       && [ "\$SIZE1" -ge \$(( EXP1 * 95 / 100 )) ] && [ "\$SIZE2" -ge \$(( EXP2 * 95 / 100 )) ]; then
        SIZE_OK=yes
    fi
    # cat mode: EXP is exact, so also reject an object that is too BIG -- that is
    # what a leftover uncapped file looks like when the cap has since tightened.
    if [ "\$MODE" = "cat" ] && [ "\$SIZE_OK" = "yes" ]; then
        if [ "\$SIZE1" -gt \$(( EXP1 * 105 / 100 )) ] || [ "\$SIZE2" -gt \$(( EXP2 * 105 / 100 )) ]; then
            SIZE_OK=no
        fi
    fi

    PLAN_OK=no
    if [ "\$MODE" = "cat" ]; then
        PLAN_OK=yes
    elif [ "\$PREV_PLAN_MODE" = "proportional" ] && [ "\$PREV_PLANNED" = "\$PLANNED_TOTAL" ]; then
        PLAN_OK=yes
    fi

    if [ "${params.skip_existing}" = "true" ] && [ "\$SIZE_OK" = "yes" ] && [ "\$PLAN_OK" = "yes" ]; then
        MODE=skipped
    fi
    if [ "${params.dry_run}" = "true" ] && [ "\$MODE" != "skipped" ]; then
        MODE=dry_run
        # A dry run writes a log but no FASTQ, so it must not leave provenance a
        # later run could mistake for a real build.
        PLAN_MODE=dry_run
    fi

    # \$1 = 1 for R1, 2 for R2. Identical record counts, identical lane order:
    # positional correspondence is all fastp needs (no read-name matching).
    stream_read () {
        local which=\$1 key r1 r2 pairs b1 b2 k uri
        while IFS=\$'\\t' read -r key r1 r2 pairs b1 b2 k; do
            if [ "\$k" -le 0 ]; then continue; fi
            uri=\$r1
            if [ "\$which" = "2" ]; then uri=\$r2; fi
            if [ "\$MODE" = "cat" ]; then
                aws s3 cp --only-show-errors "\$uri" -
            else
                # --total makes the take SYSTEMATIC (even stride over the whole
                # lane) rather than a prefix; it is the lane's expected record
                # count, so R1 and R2 select identical record indices.
                aws s3 cp --only-show-errors "\$uri" - \\
                  | gemma_take_pairs.py --records "\$k" --total "\$pairs" \\
                        --stats "lane_\${which}_\${key}.stats"
            fi
        done < plan.tsv
    }

    if [ "\$MODE" = "cat" ] || [ "\$MODE" = "proportional" ]; then
        stream_read 1 | aws s3 cp --only-show-errors --expected-size "\$UP1" - "${out1}"
        stream_read 2 | aws s3 cp --only-show-errors --expected-size "\$UP2" - "${out2}"
    fi

    # The mode/planned_pairs on line 2 are what the NEXT run's skip check reads
    # back as provenance -- keep the column order stable.
    {
        echo -e "sample\\trun\\tmode\\tn_lanes\\tcap_pairs\\test_total_pairs\\tplanned_pairs\\tplan_mode"
        echo -e "${meta.id}\\t${meta.run}\\t\$MODE\\t\$NLANES\\t\$CAP\\t\$TOTAL\\t\$PLANNED_TOTAL\\t\$PLAN_MODE"
        echo
        echo -e "# per-lane\\nlane\\tr1_uri\\tr2_uri\\test_pairs\\tbytes_r1\\tbytes_r2\\tplanned_pairs\\tobserved_pairs_r1"
        while IFS=\$'\\t' read -r key r1 r2 pairs b1 b2 k; do
            obs=NA
            if [ -s "lane_1_\${key}.stats" ]; then obs=\$(cut -f1 "lane_1_\${key}.stats"); fi
            echo -e "\$key\\t\$r1\\t\$r2\\t\$pairs\\t\$b1\\t\$b2\\t\$k\\t\$obs"
        done < plan.tsv
    } > ${meta.id}.preprocess.tsv
    """
}

workflow {

    if (!params.manifest) {
        error "--manifest is required: the lane-level TSV for one batch, e.g. " +
              "globus_2026/s3-to-s3/gemma_manifest_under32m.tsv"
    }

    def keep = params.samples
        ? params.samples.tokenize(',')*.trim().findAll { it } as Set
        : null

    // One row per FASTQ object: sample_id run cohort platform flowcell lane index
    // read bytes est_reads filename s3_uri
    Channel
        .fromPath(params.manifest, checkIfExists: true)
        .splitCsv(sep: '\t', header: true)
        .filter { row -> keep == null || keep.contains(row.sample_id) }
        .map { row ->
            tuple(
                tuple(row.sample_id, row.run),
                [ lane_key : "${row.flowcell}_${row.lane}_${row.index}".toString(),
                  read     : row.read,
                  uri      : row.s3_uri,
                  pairs    : row.est_reads as Long,   // per-file read count == lane pair count
                  bytes    : row.bytes as Long ]
            )
        }
        .groupTuple()
        .map { key, recs ->
            def (sample, run) = key
            def meta = [ id: sample, run: run ]

            // Lane order is free -- downstream is an unordered bag of reads -- but
            // it must be the SAME for R1 and R2, so sort deterministically.
            def spec = recs
                .groupBy { it.lane_key }
                .sort { it.key }
                .collect { lane_key, files ->
                    def r1 = files.find { it.read == '1' }
                    def r2 = files.find { it.read == '2' }
                    if (!r1 || !r2) {
                        error "GEMMA ${sample}: lane ${lane_key} is not a complete pair " +
                              "(found reads ${files*.read}). Fix the manifest before running."
                    }
                    [ lane_key, r1.uri, r2.uri, r1.pairs, r1.bytes, r2.bytes ].join('\t')
                }
                .join('\n')

            tuple(meta, spec)
        }
        .set { samples }

    GEMMA_MERGE_LANES(samples)

    // Batch label for the summary filename: derived from --manifest itself (one
    // manifest == one batch per invocation, e.g. gemma_manifest_under8g.tsv), not
    // from meta.run pulled off the channel, so it's known synchronously at
    // workflow-definition time rather than depending on channel-emission timing.
    // Without this, two sequential invocations against the same --logdir (one per
    // batch, per this file's usage) silently overwrite each other's summary.
    def batchLabel = new File(params.manifest).name
        .replaceFirst(/^gemma_manifest_/, '')
        .replaceFirst(/\.tsv$/, '')

    GEMMA_MERGE_LANES.out.log
        .map { meta, log -> log.text.readLines()[1] + '\n' }
        .collectFile(name: "preprocess_summary_${batchLabel}.tsv", storeDir: params.logdir, sort: true,
                     seed: "sample\trun\tmode\tn_lanes\tcap_pairs\test_total_pairs\tplanned_pairs\tplan_mode\n")
}
