#!/usr/bin/env nextflow

/*
  StrainPhlAn subworkflow — strain-level profiling downstream of profile_taxa SAMs.

  Follows the StrainPhlAn 4.1 tutorial:
    https://github.com/biobakery/MetaPhlAn/wiki/StrainPhlAn-4.1

  Steps:
    1. sample2markers  (per sample)  SAM.bz2 -> <id>.json.bz2 consensus markers
    2. print_clades    (per run)     all sample markers -> clades detectable across samples
    3. extract_markers (per run/clade) pull the chosen clade's markers from the MetaPhlAn DB
    4. strainphlan     (per run/clade) markers -> multiple-seq alignment + RAxML tree (.tre)

    Steps 3-4 only run for clades listed in params.strainphlan_clades. With that
    param empty (default) the subworkflow stops after print_clades, so a first run
    tells you which clades are available before you commit to a tree.

  Channel key throughout is `run` (the study grouping), matching the rest of the pipeline.
*/

// STEP 1 — per-sample consensus markers from the MetaPhlAn SAM.
process sample2markers {

    tag "$name"
    container params.docker_container_metaphlan
    // Single-threaded when run on single samples post alignment. cpus lives here, memory in config.
    cpus 1
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/consensus_markers" }, mode: 'copy', pattern: "*.json.bz2"

    input:
    tuple val(meta), path(sam)

    output:
    tuple val(meta), path("*.json.bz2"), emit: markers

    script:
    name = task.ext.name ?: "${meta.id}"
    run  = task.ext.run  ?: "${meta.run}"
    """
    sample2markers.py \\
        -i ${sam} \\
        -o . \\
        -d ${params.direct_metaphlan_db}/${params.direct_metaphlan_id}.pkl \\
        --input_format bz2
    """
}

// STEP 2 — clades detectable across all samples in a run.
process print_clades {

    tag "$run"
    container params.docker_container_metaphlan
    cpus 1
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan" }, mode: 'copy', pattern: "print_clades_only.tsv"

    input:
    tuple val(run), path(markers)

    output:
    // StrainPhlAn --print_clades_only writes the clade table to print_clades_only.tsv
    // in the output dir (not stdout).
    tuple val(run), path("print_clades_only.tsv"), emit: clades

    script:
    """
    strainphlan \\
        -s ${markers} \\
        --print_clades_only \\
        --database ${params.direct_metaphlan_db}/${params.direct_metaphlan_id}.pkl \\
        -o .
    """
}

// STEP 3 — clade-specific marker FASTA from the MetaPhlAn DB.
process extract_markers {

    tag "$clade"
    container params.docker_container_metaphlan
    cpus 1

    input:
    val clade

    output:
    tuple val(clade), path("${clade}.fna"), emit: markers

    script:
    """
    extract_markers.py \\
        -c ${clade} \\
        -d ${params.direct_metaphlan_db}/${params.direct_metaphlan_id}.pkl \\
        -o .
    """
}

// STEP 4 — multiple-sequence alignment + RAxML tree for one clade in one run.
process strainphlan {

    tag "${run}:${clade}"
    container params.docker_container_metaphlan
    cpus 1
    // The (run x clade) cross-product includes combos where a clade isn't present
    // in a run: StrainPhlAn prints "Less than 4 samples remained after filtering"
    // and exits 1 (verified in trace, Jun-15 run). That's expected, not fatal — skip
    // those and keep the trees that do build. Any OTHER exit status (OOM 137, missing
    // DB, container 125-127, signals) is a real failure and must terminate the run.
    // Residual risk: a genuine internal crash that also exits 1 would be ignored, but
    // that is strictly safer than the old blanket 'ignore'.
    errorStrategy { task.exitStatus == 1 ? 'ignore' : 'terminate' }
    // Per-suffix for everything in trees/:
    //   RAxML_*                  RAxML tree + info/log files
    //   *.aln                    concatenated multiple-sequence alignment
    //   *.info / *.polymorphic   marker stats, polymorphic-site stats
    //   *.mutation / *_mutation_rates  mutation-rate summary + per-marker tables
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/trees" }, mode: 'copy', pattern: "RAxML_*"
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/trees" }, mode: 'copy', pattern: "*.aln"
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/trees" }, mode: 'copy', pattern: "*.info"
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/trees" }, mode: 'copy', pattern: "*.polymorphic"
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/trees" }, mode: 'copy', pattern: "*.mutation"
    publishDir { "${params.outdir}/${params.project}/${run}/strainphlan/trees" }, mode: 'copy', pattern: "*_mutation_rates"

    input:
    tuple val(run), path(markers), val(clade), path(clade_markers)

    // publishDir only publishes files captured by an output declaration, so every
    // artifact we want in trees/ must be declared here (the patterns above just
    // filter this set).
    output:
    tuple val(run), val(clade), path("RAxML_bestTree.*.tre"), emit: tree, optional: true
    tuple val(run), val(clade), path("RAxML_*"),          emit: raxml,          optional: true
    tuple val(run), val(clade), path("*.aln"),            emit: alignment,      optional: true
    tuple val(run), val(clade), path("*.info"),           emit: info,           optional: true
    tuple val(run), val(clade), path("*.polymorphic"),    emit: polymorphic,    optional: true
    tuple val(run), val(clade), path("*.mutation"),       emit: mutation,       optional: true
    tuple val(run), val(clade), path("*_mutation_rates"), emit: mutation_rates, optional: true

    script:
    """
    strainphlan \\
        -s ${markers} \\
        -m ${clade_markers} \\
        -c ${clade} \\
        --database ${params.direct_metaphlan_db}/${params.direct_metaphlan_id}.pkl \\
        --mutation_rates \\
        -o .
    """
}


workflow STRAINPHLAN {
    take:
        sams   // channel of [meta, sam.bz2] from profile_taxa.out.sam

    main:
        // STEP 1: per-sample markers
        sample2markers(sams)

        // Group every sample's markers by run.
        markers_by_run = sample2markers.out.markers
            .map { meta, markers -> [ meta.run, markers ] }
            .groupTuple()

        // STEP 2: which clades are shared across the run's samples
        print_clades(markers_by_run)

        // STEPS 3-4: only for explicitly requested clades.
        clades = channel.fromList(
            (params.strainphlan_clades ?: '')
                .tokenize(',')
                .collect { clade -> clade.trim() }
                .findAll { clade -> clade }
        )

        // markers from the DB for each requested clade (clade-keyed, run-independent)
        extract_markers(clades)

        // Cross every run's marker bundle with every clade's DB markers, then build trees.
        tree_input = markers_by_run.combine(extract_markers.out.markers)
            .map { run, markers, clade, clade_markers ->
                [ run, markers, clade, clade_markers ]
            }

        strainphlan(tree_input)

    emit:
        clades = print_clades.out.clades
        trees  = strainphlan.out.tree
}
