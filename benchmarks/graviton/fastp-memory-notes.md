# fastp memory sizing

Checked upstream fastp v1.1.0 source on 2026-09-18 (our container tag is 1.1.0).

- `--dedup` defaults to `--dup_calc_accuracy 3` in src/main.cpp.
- src/duplicate.cpp allocates and zeroes fixed Bloom-filter buffers at startup.
  Accuracy levels 1–6 allocate 1, 2, 4, 8, 16, 32 GiB respectively, plus
  other process memory. These buffer sizes do not depend on input bytes or
  reads_to_process. The README's higher-level table has stale/inconsistent
  numbers; use the versioned implementation.
- Level 3 therefore cannot fit a 4-GiB task. An 8-GiB initial allocation is
  a reasonable candidate, with 16/32-GiB retries, but needs measured validation.
- Total peak RSS also includes read queues, worker state, compression and
  reporting. Fixed filter allocation does not mean exactly fixed total RSS.
- Input-size scaling is a poor primary sizing rule here, especially compressed
  FASTQ: all five benchmark caps read the same input files and allocate the
  same filter. Changing accuracy changes collision behavior, so don't lower
  it silently as a memory retry strategy.
- Fixed hash construction is not a guarantee of byte-identical output:
  Bloom-filter false positives are documented; worker threads call checkPair
  against shared atomic filter buffers, so which duplicate record survives
  can depend on processing order. This is a source-based caveat, not a
  repeatability measurement of our container.

For a future Nextflow configuration, keep accuracy explicit in the fastp
command (`--dup_calc_accuracy 3`) and use a memory ladder independently:

```groovy
withName: 'clean_reads' {
    memory = { task.attempt == 1 ? 8.GB : (task.attempt == 2 ? 16.GB : 32.GB) }
}
```

Retain the benchmark's existing retry/error policy. Nextflow also supports
`task.previousTrace.memory * 2` on retries (since 24.10); this is previous
requested memory, not a reliable measurement of uncensored OOM peak RSS.
The explicit ladder makes the upper allocation obvious.

The active G4 run and matching G5 config remain at 16/32 GiB for comparison.
Use successful peak_rss measurements to evaluate an 8-GiB starting request
after this benchmark. No active run or command semantics changed for this note.

Sources:
- https://github.com/OpenGene/fastp/blob/v1.1.0/src/main.cpp#L200-L210
- https://github.com/OpenGene/fastp/blob/v1.1.0/src/duplicate.cpp#L9-L57
- https://github.com/OpenGene/fastp/blob/v1.1.0/src/peprocessor.cpp#L386-L405
- https://github.com/OpenGene/fastp/blob/v1.1.0/README.md#duplication-rate-and-deduplication
- https://www.nextflow.io/docs/latest/process.html#dynamic-task-resources
- https://www.nextflow.io/docs/latest/process.html#dynamic-task-resources-with-previous-execution-trace

Historical audit supersedes the initial 8-GiB uncertainty: 3,457 successful
accuracy-3 tasks peaked below 4.28 GiB; see history/report.md. User approved
8 GiB initially, 16 GiB on every retry. Applied in common.config; the active
G4 process retains its already-loaded 16/32-GiB setting.
