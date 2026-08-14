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
 * Two batches, ONE code path:
 *   under32m  total est pairs <= cap  -> plain concatenation of every lane
 *   over32m   total est pairs >  cap  -> each lane contributes round(p_i*cap/P)
 * Proportional sampling is a no-op below the cap, so a misclassified borderline
 * sample still gets the right answer.
 *
 * Why not cat everything and let fastp cap it: `fastp --reads_to_process` is head
 * truncation, not subsampling -- on a concatenated multi-flowcell file it would
 * take lane 1 and drop the other flowcells, baking the flowcell batch effect into
 * the reads. Two-thirds of GEMMA samples span multiple flowcells.
 *
 * Why still emit a real R1/R2 PAIR: one pre-concatenated file flips
 * meta.single_end true, which reinterprets --reads_to_process as reads instead of
 * pairs (half the intended depth cohort-wide) and loses pair-aware --dedup.
 *
 * Nothing touches local disk: each lane is streamed S3 -> stdout -> S3 multipart
 * upload. In the `cat` path no byte is decompressed (gzip members concatenate
 * natively); only the proportional path pays decompress/recompress.
 *
 * Usage (from the repo root, in screen):
 *   nextflow run preprocess_gemma.nf \
 *     -c conf/aws_batch.config \
 *     --project gemma \
 *     --manifest /home/ubuntu/github/globus_2026/s3-to-s3/gemma_manifest_under32m.tsv
 *
 * Add `--dry_run` to plan without transferring, or
 * `--samples GMA_015,sGMA_378` to run a smoke slice.
 */

nextflow.enable.dsl = 2

params.manifest      = null
params.outprefix     = 's3://gutz-nf-reads-profilers-workdir/preprocessed/gemma'
params.logdir        = 's3://gutz-nf-reads-profilers-runs/results/gemma/preprocess'
params.cap           = 32000000   // PAIRS, matching params.nreads in nextflow.config.
                                  // 0 = NO CAP: every lane is cat'd whole, both batches.
                                  // Keep in sync with params.nreads of the stage-2 run.
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
 * lifecycle) a resume will NOT notice. Re-run with --skip_existing true, which
 * checks S3 directly and skips only what is really there.
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

    # plan.tsv adds k = pairs to take from this lane (all of them below the cap)
    awk -F'\\t' -v cap="\$CAP" -v tot="\$TOTAL" 'BEGIN{OFS="\\t"}
        { k = (cap <= 0 || tot <= cap) ? \$4 : int(\$4 * cap / tot + 0.5); print \$0, k }' \\
        lanes.tsv > plan.tsv

    # Expected upload sizes drive the multipart chunk size: without them the CLI
    # assumes a small object, caps at 10000 parts of 8 MB and dies at 80 GB.
    # GMA_353 alone is 104 GiB.
    EXP1=\$(awk -F'\\t' '{s += \$5 * \$7 / (\$4 ? \$4 : 1)} END{printf "%d", s+1}' plan.tsv)
    EXP2=\$(awk -F'\\t' '{s += \$6 * \$7 / (\$4 ? \$4 : 1)} END{printf "%d", s+1}' plan.tsv)

    if [ "${params.skip_existing}" = "true" ] \\
       && aws s3 ls "${out1}" > /dev/null 2>&1 \\
       && aws s3 ls "${out2}" > /dev/null 2>&1; then
        MODE=skipped
    fi
    if [ "${params.dry_run}" = "true" ] && [ "\$MODE" != "skipped" ]; then
        MODE=dry_run
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
                aws s3 cp --only-show-errors "\$uri" - \\
                  | gemma_take_pairs.py --records "\$k" --stats "lane_\${which}_\${key}.stats"
            fi
        done < plan.tsv
    }

    if [ "\$MODE" = "cat" ] || [ "\$MODE" = "proportional" ]; then
        stream_read 1 | aws s3 cp --only-show-errors --expected-size "\$EXP1" - "${out1}"
        stream_read 2 | aws s3 cp --only-show-errors --expected-size "\$EXP2" - "${out2}"
    fi

    {
        echo -e "sample\\trun\\tmode\\tn_lanes\\tcap_pairs\\test_total_pairs\\tplanned_pairs"
        PLANNED=\$(awk -F'\\t' '{s+=\$7} END{print s+0}' plan.tsv)
        echo -e "${meta.id}\\t${meta.run}\\t\$MODE\\t\$NLANES\\t\$CAP\\t\$TOTAL\\t\$PLANNED"
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

    GEMMA_MERGE_LANES.out.log
        .map { meta, log -> log.text.readLines()[1] + '\n' }
        .collectFile(name: 'preprocess_summary.tsv', storeDir: params.logdir, sort: true,
                     seed: "sample\trun\tmode\tn_lanes\tcap_pairs\test_total_pairs\tplanned_pairs\n")
}
