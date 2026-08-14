# GEMMA onboarding plan — preprocessing, then a normal pipeline run

Status: **plan only, nothing deployed or run** (written 2026-08-14).

GEMMA is the first cohort delivered as **multiple FASTQ pairs per biological
sample** (flowcell × lane, sometimes across two sequencer generations). Every
prior cohort (Diversigen, CosmosID) arrived pre-merged, one pair per sample, so
the pipeline has never had to collapse lanes.

**Shape of the solution: add a preprocessing stage that produces one merged
FASTQ pair per sample, then run `nf-reads-profiler` normally.** No schema
change, no `main.nf` reorder, no change to `nreads`/`minreads` semantics. The
pipeline sees GEMMA exactly as it saw CosmosID.

## The data, as measured

Source: `s3://gutz-data-s3/gemma-fastq/inrae-fastq/<SAMPLE>/<flowcell>_<lane>_<index>_<read>.clean.rmHost.fastq.gz`

Transfer verified complete 2026-08-14: **9786/9786 objects, 5.55 TiB, 0 missing**.

| Fact | Value |
|---|---|
| Biological samples | 1356 (829 `GMA_*`, 527 `sGMA_*`) |
| FASTQ pairs (lane-level rows) | 4893 |
| Lane pairs per sample | 1–8 (median 3) |
| Platform | MGI DNBSEQ — **not** Illumina |
| Flowcells | 36 total: `V350*` (8570 files), `DL100*` (1216 files) |
| Read length | 150 bp both platforms, full-resolution Q scores |
| Provenance | `.clean.rmHost` — adapter-cleaned and host-depleted upstream by INRAE |
| Total depth | 23.17 G read pairs (46.35 G reads) |

Platform confirmed from read names, not filename inference:
`@V350291262L1C001R00100001925/1` is MGI DNB grammar (`L`ane/`C`olumn/`R`ow);
Illumina would be `@A00123:45:HXXXXX:1:1101:1000:1000 1:N:0:ATCG`. The newer
`DL100*` run additionally carries an inline dual index
(`#CGAGCCGATT+GGATCGCACG`).

There are **no dates anywhere in this dataset** — gzip MTIME is zeroed in all 36
flowcells, FASTQ headers carry none, and the S3 timestamps are the 2026-08-13
copy. Ordering below relies on MGI serial numbers increasing over time, which is
a reasonable proxy but is not verifiable from the data and cannot order `V350`
against `DL100` (different serial series).

### Sample-count reconciliation

Authority is EBRIS's `gemma_samples_transfer_20260808.txt` (1439 rows, 1358
unique `sample_id`, one blank → **1357 real**).

- `sGMA_CTNEG_1` — negative control, never sequenced, no FASTQ.
- `GMA_327` + `GMA_327_l3` — pre-fused by the provider into
  `GMA_327_GMA_327_l3_fused` (2 ids → 1 sample).

1357 − 1 control − 1 fusion = **1356**, matching the samplesheet.

### Re-sequencing pattern

Extra flowcells went to low-yield samples:

| Group | n | Median first-flowcell yield |
|---|---:|---:|
| Single-flowcell samples | 297 | 42.6M reads |
| Multi-flowcell samples | 1059 | **8.6M reads** (earliest run only) |

Target depth looks like ~40M reads (~20M pairs). Samples at 3/4/5 flowcells all
land at 41–46M total; the **2-flowcell group is the anomaly at 14.9M median** —
573 samples that got a second run and still fell short. Those are the cohort's
struggling libraries and are worth carrying as a depth covariate.

The later flowcell is usually a full re-sequence, not a trickle: median **47.3%**
of a sample's reads come from its highest-serial flowcell (p25 27%, p75 58%).
The exception is the cross-platform case, where the second platform contributes
a median of only 13.4%.

`DL100` appears almost exclusively alongside the newest `V350342xxx` era (90 of
101 occurrences; 10 with `V350330xxx`, 1 with `V350199xxx`), consistent with
`DL100` being the later instrument.

### Platform mixing

| Split | N samples |
|---|---:|
| V350 only | 1164 |
| DL100 only | 141 |
| **Both platforms in one sample** | **51** |

For those 51, the minor platform contributes min 0.0% / **median 13.4%** / max
39.6% of reads; **0 of 51** have both halves clearing the cap, and **8 of 51**
have a minor half below `minreads`. They are top-ups, not parallel runs — which
is why samples are never split by platform (see rejected options below).

## Units — `nreads` and `minreads` are in PAIRS

`fastp --reads_to_process` is documented as "how many reads/**pairs** to be
processed" and takes pairs for PE input. `count_reads` runs on raw `reads[0]`
(R1 only, pre-clean), so `READ_COUNT` is also a pair count. Therefore:

- `nreads = 32,000,000` → 32M **pairs** (64M reads)
- `minreads = 100,000` → 100k **pairs**

Comparing whole-read totals against these is wrong by 2×.

## How the pipeline handles paired ends (verified 2026-08-14)

`clean_reads` (`modules/house_keeping.nf:92-107`) runs fastp in PE mode and then
**concatenates the two output files into one**:

```
fastp -i ${reads[0]} -I ${reads[1]} -o out.R1.fq.gz -O out.R2.fq.gz \
  --reads_to_process ${params.nreads} --dedup ...

cat out.R1.fq.gz out.R2.fq.gz > ${name}_trimmed.fq.gz
```

So MetaPhlAn and HUMAnN see one flat file and pairing is discarded — **but only
after fastp**. That ordering is what the preprocessing contract depends on.

### Preprocessing must still emit a real R1/R2 pair

Handing the pipeline a single pre-concatenated file instead would break two
things:

1. **fastp PE mode needs two files** with matching record counts and positional
   order. One file makes `meta.single_end = !fastq_2` (`main.nf:167`) flip true
   and takes the single-end branch.
2. **`--reads_to_process` silently changes units.** PE: 32M *pairs*. SE on a
   concatenated file: 32M *reads* — **half the intended depth cohort-wide**, and
   the pairs-vs-reads section above inverts. It also loses pair-aware `--dedup`,
   which is the whole reason for merging before fastp.

### What it does simplify

Because pairing only has to survive as far as fastp, the merge is much dumber
than it looks:

- **Lane concatenation order is free.** Downstream is an unordered bag of reads.
  `cat` every lane's R1 in some order, then every lane's R2 in the *same* order.
  No sorting, no interleaving, no read-name matching — positional correspondence
  is all fastp needs.
- **Proportional sampling needs no read-name logic.** Take `head -n 4×k_i` from
  lane *i*'s R1 and the identical `k_i` from its R2.
- **gzip members concatenate natively.** `cat a.fastq.gz b.fastq.gz` is a valid
  gzip stream, so the merge is an I/O-bound copy with no decompress/recompress.
  That makes the 5.55 TiB pass far cheaper than its size suggests and keeps it
  comfortably on `spot-queue`.

Do **not** build a `seqtk`-style pairing-aware merger; it would buy nothing.

### `params.mergeReads` is dead code

Declared in `nextflow.config:50`, `conf/test.config:25`, and
`tests/nextflow.config:58`; referenced by **zero** processes. The R1+R2 `cat` in
`clean_reads` is unconditional and this flag does not control it. Candidate for
deletion — do not reach for it expecting it to change merge behavior.

## The two batches

These are also the two **run keys** — see "Two run keys" below.

| batch | samples | raw GB | raw GiB | TiB | files | lane pairs | multi-lane | est pairs (G) | pairs used | median depth |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `under32m` | 1276 | 5169.4 | 4814.4 | 4.70 | 9116 | 4558 | 1245 | 19.43 | 19.43 (all) | 19.7M |
| `over32m` | 80 | 936.8 | 872.5 | 0.85 | 670 | 335 | 79 | 3.74 | 2.56 | 38.9M |
| **total** | **1356** | **6106.2** | **5686.9** | **5.55** | **9786** | **4893** | **1324** | **23.17** | **21.99** | — |

`raw GB`/`raw GiB` are summed S3 object bytes (measured, not estimated); only
`est pairs` is byte-derived.

- **`under32m` (1276 samples): plain `cat`.** Total depth is at or below the cap,
  so no truncation happens and concatenating every lane is exact.
- **`over32m` (80 samples): proportional sampling.** Take each lane's *share* of
  the cap. Head-truncating a concatenated file would take lane 1 (and part of
  lane 2) and drop the other flowcells entirely — with two-thirds of samples
  spanning multiple flowcells, that would bake the flowcell batch effect into the
  reads themselves.

The cap discards only **1.18 G of 23.17 G pairs (5%)**, but *which* 5% is decided
entirely by this logic. **64 samples are flagged `borderline`** (41 in
`under32m`, 23 in `over32m`) — near the threshold on byte-derived estimates, so
exact classification only exists at runtime. See the safety property below.

Note `needs_proportional_sampling=yes` is **79**, not 80: one over-cap sample is
single-lane, so plain `cat` plus fastp's own cap is already exact for it.

Built manifests, all in `globus_2026/s3-to-s3/` (builder:
`scratchpad/split_by_cap.py`):

| file | rows | contents |
|---|---:|---|
| `gemma_runs_by_cap.tsv` | 1356 | batch label, `borderline`, `needs_proportional_sampling` |
| `gemma_manifest_{under32m,over32m}.tsv` | 9116 / 670 | lane-level, enriched manifest + `run` — preprocessing input |
| `gemma_summary_{under32m,over32m}.tsv` | 1276 / 80 | sample-level summary + `run`, `borderline`, `needs_proportional_sampling` |
| `gemma-{under32m,over32m}.csv` | 1276 / 80 | schema-valid samplesheets (point at not-yet-built preprocessed pairs) |

## Design decisions

### Preprocess outside the pipeline, then run normally

Preprocessing writes one merged FASTQ pair per sample to S3; the pipeline then
runs against plain samplesheets (1276 + 80 rows) with no code change.
Consequences:

- `count_reads` sees a merged R1 → `READ_COUNT` is the sample's pair count, and
  `minreads` keeps exactly the meaning it has for every other cohort.
- `fastp --dedup` runs **after** merging, so it catches cross-flowcell PCR
  duplicates — the same library re-sequenced on a second flowcell reproduces its
  duplicates, and with two-thirds of samples multi-flowcell that matters.
- Per-lane fastp QC is not produced. Capture per-lane stats in the preprocessing
  log instead if lane-level QC is wanted.

**Safety property:** proportional sampling is a no-op for under-cap samples
(take 100% of each lane = `cat`). One code path is therefore correct for both
batches, and a misclassified borderline sample still gets the right answer.
Preprocessing can proportion using estimated per-lane depths and let fastp's
existing `--reads_to_process` enforce the exact ceiling on an already-balanced
merged file.

### Two run keys: `under32m` and `over32m`

**Decided 2026-08-14: the cap batch is the run key.** `study_accession` is
`under32m` (1276) or `over32m` (80), giving two output trees and two sets of
combined tables. The batch split already had to exist for preprocessing, so this
reuses it rather than inventing a second axis.

`meta.run` (from `study_accession`) drives the output dir `<project>/<run>/` and
every `groupTuple` combine (`combine_humann_tables`,
`combine_humann_taxonomy_tables`, `combine_metaphlan_tables`, `MULTIQC`,
StrainPhlAn's `print_clades`). Alternatives considered and rejected:

| Option | Verdict |
|---|---|
| Cap batch (`under32m`/`over32m`) | **Chosen.** Reuses the split preprocessing needs anyway; platform rides as a metadata column. |
| Single `gemma` | Simplest, one combined table set — superseded by the decision above. |
| Split by platform (`V350`/`DL100`/`mixed`) | Defensible, no data loss, but splits combined tables three ways for a covariate 96% of samples don't straddle. |
| Split mixed samples across platform runs | **Rejected on data.** 8 of 51 minor halves fall below `minreads` and would be discarded outright; 0 of 51 are balanced enough to serve as platform replicates. |
| Split by `n_flowcells` (fc1–fc5) | **Rejected as unstable.** `fc5` is 100% DL100 and `fc4` half, so it partly aliases platform; and new data changes a sample's run → task hash → full re-run. |

Two consequences to hold onto, both accepted:

- **The split axis is sequencing depth**, which correlates with library quality —
  the 573 struggling two-flowcell libraries concentrate in `under32m`. The two
  runs' combined tables are therefore not depth-comparable to each other; treat
  them as two tables to be joined at analysis time, not as replicates.
- **64 borderline samples sit near the threshold on byte estimates.** Since
  `meta.run` is part of the task input tuple, a sample that gets reclassified
  when real read counts land changes its run → re-hashes its tasks → re-runs it
  and moves it between combined tables. **Freeze run assignment from
  `gemma_runs_by_cap.tsv` as built and never recompute it from measured counts.**
  The file, not the arithmetic, is the authority.

**`meta.run` is part of the task input tuple, so changing it later re-runs the
cohort from scratch.** Unlike `skip_combines` or a per-sample biom step, this is
not a cheap decision to revisit — hence settling it before the first run.

### Tracking V350 vs DL100 through the merge

Platform is computed **per sample** (`V350`/`DL100`/`mixed`, with the 51
straddlers marked `mixed`) and carried as a column in
`gemma_sample_summary.tsv`, joinable on `sample_id`. It does not appear in
output paths, so the cohort keeps one combined biom set while remaining
stratifiable at analysis time. Lane-level attributes (flowcell, lane, index)
survive in the preprocessing log and in the enriched manifest.

## Phases

### Phase 1 — unblock infra (no code)

1. `infra/batch-stack.yaml`: add `gutz-data-s3` read (`s3:GetObject`,
   `s3:ListBucket`, `s3:GetBucketLocation`) to the `S3Access` inline policy on
   `nf-reads-profiler-batch-job-role`. That policy today covers only the workdir
   bucket, the runs bucket, and `gutz-data-globus`, so **workers cannot read
   GEMMA inputs at all**. IAM-only change — not a compute-resource edit, so no CE
   replacement; safe to deploy while jobs run. Deploy with `/deploy-stack`.
   (The runner role already has `AmazonS3FullAccess`.)

### Phase 2 — preprocessing (the new stage)

2. Build the enriched manifest and per-sample rollup — **done**:
   `gemma_manifest_enriched.tsv` (9786 rows: sample, cohort, platform, flowcell,
   lane, index, read, bytes, est_reads, filename, s3_uri) and
   `gemma_sample_summary.tsv` (1356 rows, merged across lanes and instruments).
   Read counts are estimated from compressed bytes using per-platform ratios
   measured on 18 real files — **V350 ≈ 141 B/read** (n=11, 133–155),
   **DL100 ≈ 75.5 B/read** (n=7, 63–82). DL100 compresses ~2× denser; a single
   global ratio would inflate the 141 DL100-only samples by ~85%. Expect ±10%.
3. Write a small preprocessing workflow (its own `.nf`, reusing
   `conf/aws_batch.config` and `spot-queue`) that per sample:
   - reads its lane list from `gemma_manifest_<batch>.tsv`;
   - for `under32m`, `cat`s all lane R1s and all lane R2s (gzip streams
     concatenate natively — no decompress);
   - for `over32m`, takes each lane's proportional share of 32M pairs
     (`round(p_i × C / P)`) from R1 and R2 **identically**, by record count from
     the head of each file — positional correspondence is sufficient, see
     "How the pipeline handles paired ends";
   - writes `<sample>_R1.fastq.gz` / `<sample>_R2.fastq.gz`;
   - logs per-lane input pairs and output pairs for QC.
4. Output location:
   `s3://gutz-nf-reads-profilers-workdir/preprocessed/gemma/<batch>/`
   (per-batch subdir so the two runs can't collide). ~5.55 TiB. That bucket's
   30-day lifecycle auto-cleans it — **which means the pipeline run must complete
   within 30 days of preprocessing**, and a much later `-resume` will find inputs
   gone. Use a retained prefix instead if that window is uncomfortable.
5. Samplesheets — **built**: `gemma-under32m.csv` (1276 rows) and
   `gemma-over32m.csv` (80 rows), `sample,fastq_1,fastq_2,study_accession` with
   `study_accession` = the batch, pointing at the preprocessed pairs (which do
   not exist until step 3 runs). Validate against `assets/schema_input.json` and
   upload to `s3://gutz-nf-reads-profilers-runs/samplesheets/`.

### Phase 3 — optional pipeline improvements (not required for GEMMA)

Neither blocks the run; both are cheap to add later since they don't touch
`meta.run`.

6. `params.skip_combines` gate — skip the per-run combine/split/biom reduces
   when only per-sample outputs are wanted (~5 lines in `main.nf`).
7. Per-sample HUMAnN biom. Today per-sample function output is TSV only
   (`<run>/function/<id>_{2_genefamilies,3_reactions,4_pathabundance}.tsv`);
   only combined tables become biom. A light per-sample TSV→biom process would
   give collaborators who import per-sample files the same convenience they have
   for taxa (`<run>/taxa/<id>_metaphlan.biom`), without abusing the run key.

### Phase 4 — validate, then run

8. **Smoke slice (~10 samples), taxa only.** Choose deliberately: a 1-lane
   sample, the 8-lane `GMA_327_GMA_327_l3_fused`, a sub-`minreads` sample
   (`sGMA_378`), a DL100-only sample, one of the 51 mixed-platform samples, and
   one `over32m` sample to exercise proportional sampling. Draw from **both**
   batches so each run key is exercised end to end. Confirms merge, IAM, the
   `minreads` drop, and whether fastp accepts MGI read names without
   `--fix_mgi_id`.
9. **Full run** — two invocations, one per batch, per `playbooks/gemma.md`.

## Known landmines

- 7 samples fall below `minreads` (100k pairs) and will be dropped — logged, not
  fatal: `sGMA_824`, `sGMA_378`, `sGMA_799`, `sGMA_852`, `sGMA_1214`,
  `sGMA_794`, `sGMA_417`. All are in `under32m`.
- `GMA_353` is 104 GiB, 20× median and 5× the next largest — one oversized
  preprocessing task.
- `combine_humann_tables` now reduces over 1276 (`under32m`) and 80 (`over32m`)
  samples separately rather than 1356 at once, but the big reduce still needs the
  memory ladder already committed in `conf/aws_batch.config` (32→64→90 GB by
  attempt).
- **fastp `--fix_mgi_id` — exercise this in the smoke slice.** MGI read names end
  `/1` and `/2`, and fastp's PE name-consistency check runs on exactly the files
  preprocessing produces. Better to find out at 10 samples than at 1356. Not
  enabled today; add it to `clean_reads` only if the smoke slice trips it.
- 3 non-FASTQ objects sit in the source prefix (`Biografia.docx`, the transfer
  manifest, and one zero-length partial); the manifest ignores them.

## Revision 2026-08-14 — the cap is gone

The depth cap was dropped after this document was written: the run profiles
**every read of every sample** (`nreads = 0` in `conf/gemma.config`, stage 1 run
with `--cap 0`). Read the capping analysis above as the rationale for the
*batching*, which survives, not for a cap that is still applied.

What changes:

- **Stage 1 is one path.** With `--cap 0` both batches plain-`cat` every lane;
  the proportional-sampling code stays in `preprocess_gemma.nf` but is unused
  for this cohort. No decompress/recompress anywhere.
- **The 5% is kept.** 23.17 G pairs instead of 21.99 G. All of the difference is
  in the 80 `over32m` samples (3.74 G vs 2.56 G pairs, +46%); `under32m` is
  untouched, since every sample in it is ≤ 32M pairs already.
- **`under32m`/`over32m` still are the run keys**, frozen from
  `gemma_runs_by_cap.tsv` as described above. They now denote a depth split
  rather than a capping rule — re-labelling would re-hash every task.
- **Per-task resources had to be re-sized**, since `conf/aws_batch.config` was
  tuned against 32M pairs. `conf/gemma.config` overrides `count_reads`,
  `clean_reads`, `profile_taxa`, `profile_function` with per-attempt time
  ladders and raises `resourceLimits.time` to 12 h.
- **Dedup:** one post-merge `fastp --dedup` (unchanged), *not* per-lane — the
  duplicates that matter in GEMMA are cross-flowcell, because the extra
  flowcells are re-sequencing of the same library. Since fastp's dedup table is
  fixed size (1/2/4/8/16/32 GB for `--dup_calc_accuracy` 1–6, measured flat at
  4.20 GB RSS across 1898 cosmosid-infant tasks), uncapped depth raises the
  false-positive/over-dedup rate; the `over32m` run therefore adds
  `--fastp_dedup_accuracy 6`.

**Stage set** (the open decision above) is settled: taxa + HUMAnN + MEDI,
StrainPhlAn off.
