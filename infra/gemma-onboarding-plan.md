# GEMMA onboarding plan — preprocessing, then a normal pipeline run

Status: written 2026-08-14 as a plan; **stage 1 is complete and `under8g` is
essentially profiled** as of 2026-08-17. This document is a revision log — the
sections below record the reasoning as it developed, including branches that
were later abandoned. **Read the summary immediately below for what is actually
true now**, then use the rest for the measurements and the rejected
alternatives.

## Where the design landed (2026-08-17) — read this first

| question | answer | superseded |
|---|---|---|
| depth cap | **50M pairs, applied in stage 1** by proportional per-lane stride sampling | "no cap at all" (2026-08-14); "cap in fastp via `nreads`" (considered 2026-08-17, rejected) |
| stage 2 `nreads` | `0` — profiles whatever stage 1 emitted | — |
| batches | `under8g` / `over8g`, split on total sample bytes at 8×10⁹ | `under32m` / `over32m` |
| dedup | one `fastp --dedup` on the merged pair, accuracy 3, both batches | per-batch `--fastp_dedup_accuracy 6` |
| `GMA_353` | ordinary sample, capped to 50M pairs, runs inline | run alone afterwards at 24 h |
| runtime model | linear fit on the finished `under8g` run itself | cosmosid-infant slope, extrapolated 21× |

**Why the cap has to live in stage 1 and not in fastp** — this is the decision
that shaped everything else. `fastp --reads_to_process` stops reading after N
records: it is *head truncation*, not subsampling. On a merged multi-flowcell
file that keeps the first lanes and silently drops the rest. Measured on the 12
samples a 50M-pair cap actually binds on, **3 would lose a whole flowcell**
(`GMA_353` 3→2, `GMA_338` 2→1, `GMA_226` 3→1), and even a single-lane sample
would get a contiguous spatial slice of the flowcell rather than a sample of it.
Stage 1 instead gives each lane a proportional share of the cap and takes that
share by an even stride across the whole lane, so every flowcell and every
region of every flowcell is represented at the same rate.

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

## Revision 2026-08-14 — the cap is gone (SUPERSEDED by Revision 3)

**Superseded 2026-08-17: a 50M-pair cap is back, applied in stage 1. Skip to
*Revision 3* for the current design; this section explains why the original
32M cap was dropped, which is still the reason the batches are size classes.**

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
- **The run keys were then replaced outright** — see *Revision 2 — batches split
  on file size* below. `under32m`/`over32m` are retired.
- **Per-task resources had to be re-sized**, since `conf/aws_batch.config` was
  tuned against 32M pairs. `conf/gemma.config` overrides `count_reads`,
  `clean_reads`, `profile_taxa`, `profile_function` with per-attempt time
  ladders and raises `resourceLimits.time` to 24 h.
- **Runtime calibration**, `hours = slope × pairs/10M + fixed`:

  | source | method | HUMAnN | MetaPhlAn | humann cpus |
  |---|---|---:|---:|---:|
  | cosmosid-infant, 2098 samples | trace `realtime` | 0.563 | 0.067 | 16 |
  | cosmosid-infant, 50 samples | HUMAnN log TIMESTAMPs | 0.495 | 0.057 | 16 |
  | diversigen-infant, 87 samples | HUMAnN log TIMESTAMPs | 0.954 | 0.219 | 8 |

  The two cosmosid fits agree, which validates the log method; diversigen is
  ~2× slower because `profile_function` ran at `cpus = 8` there (raised to 16 in
  `25fbb00`, 2026-06-22, between the two runs). GEMMA uses the 16-cpu config, so
  the cosmosid slopes apply: ~2.2 h of HUMAnN at the over32m median (38.9M
  pairs), ~3.5 h at p90 (61M), **20–22 h for `GMA_353` (395.8M)**. Neither
  cohort exceeded 19.5M pairs, so the tail is a 21× extrapolation. `GMA_353` is
  best run alone afterwards (cpus 24, or on-demand) rather than sizing the whole
  cohort around it.
- **Dedup:** one post-merge `fastp --dedup` (unchanged), *not* per-lane — the
  duplicates that matter in GEMMA are cross-flowcell, because the extra
  flowcells are re-sequencing of the same library. Since fastp's dedup table is
  fixed size (1/2/4/8/16/32 GB for `--dup_calc_accuracy` 1–6, measured flat at
  4.20 GB RSS across 1898 cosmosid-infant tasks), uncapped depth raises the
  false-positive/over-dedup rate; the `over32m` run therefore adds
  `--fastp_dedup_accuracy 6`.

**Stage set** (the open decision above) is settled: taxa + HUMAnN + MEDI,
StrainPhlAn off.

## Revision 2 (2026-08-14) — batches split on file size

The `under32m`/`over32m` labels are retired. **No read count was ever measured
for this cohort**: `est_reads` in the manifests is `bytes ÷ constant`, with the
constant assumed to be 141 B/read (V350) and 75.5 B/read (DL100). Since the
batch label was byte-derived all along, the honest split is on the quantity we
actually know — bytes.

**New batches: `under8g` / `over8g`, split on total sample gz bytes (R1 + R2,
all lanes) at 8×10⁹.**

| batch | samples | files | TB | est pairs | size median | size max |
|---|---:|---:|---:|---:|---:|---:|
| `under8g` | 1252 | 8930 | 4.93 | 19.53 G | 5.18 GB | 8.00 GB |
| `over8g` | 104 | 856 | 1.18 | 4.45 G | 9.38 GB | 111.62 GB |

56 samples change batch relative to the old labels. Manifests
`gemma_manifest_{under8g,over8g}.tsv` are pre-sorted — `under8g` smallest-first,
`over8g` largest-first, lanes contiguous per sample — and their `run` column
carries the batch label.

### The bytes→reads constant, measured

24 files streamed and counted exactly (`aws s3 cp - | zcat | wc -l`):

| platform | read | n | B/read median | spread |
|---|---|---:|---:|---:|
| V350 | R1 | 7 | 135.4 | 5.7% |
| V350 | R2 | 5 | 136.1 | 8.5% |
| DL100 | R1 | 6 | 72.1 | 17.6% |
| DL100 | R2 | 6 | 81.8 | 20.3% |

The old constants were ~4% high on R1 (median `est_reads` error −3.9%, range
−9.5% to +6.5%). So 32M pairs is **8.69 GB** of V350 FASTQ pair but **4.93 GB**
of DL100 — an 8 GB threshold is ~29M pairs on V350 and ~55M on DL100. The
batches are size classes, not depth classes.

**The 1.9× is quality-score entropy, not read length.** Both platforms are
150 bp (mode 150 in 85–96% of reads, mean 148–149 after INRAE trimming), ~333
raw bytes/read, 40 distinct Q symbols, identical gzip settings. But V350 quality
strings carry 3.7–3.9 bits/base with no symbol above 19%, while DL100's carry
0.5–0.9 bits with one symbol at 91–95%: the qual stream is half the raw bytes
and it nearly vanishes under gzip on DL100. DL100 read names also come in two
lengths (33 vs 55 B), which is part of why its per-file spread is 3× V350's.

## `under8g` production run — status and cost (2026-08-17)

Full pipeline (taxa + function + MEDI, StrainPhlAn off) launched on the 1252
`under8g` samples. Ran into a stuck `combine_humann_tables` task
(`spot-queue`'s CE tops out at `m8g/c8g.4xlarge`, ~64 GB — the job's own
memory ladder retries up to 90 GB, which can never schedule there:
`MISCONFIGURATION:JOB_RESOURCE_REQUIREMENT`). Same ceiling problem existed for
`convert_tables_to_biom` (scales to 180 GB). Fixed by routing both to
`spot-humann` (`conf/aws_batch.config`), whose CE has metal instances with
headroom; `CLAUDE.md`'s queue table updated to match.

Cancelled the stuck run cleanly with `Ctrl-C` into the `screen` session
(`screen -S nf-gemma-under8g -X stuff $'\003'`) rather than killing the
process — Nextflow's SIGINT handler terminates in-flight Batch jobs itself,
flushes the report/trace, and writes a normal `Execution complete -- Goodbye`
to `.nextflow.log`. Since AWS runs put `.nextflow.log` on S3 workDir (no local
`tail -f`), this is the only way to get a complete, readable log instead of an
abrupt cutoff. Documented in `README.md` under `screen` basics.

**Sample count** (from `.nextflow.log*`, `status: COMPLETED` events, before
the cancel): samplesheet has 1252 rows; `count_reads` completed for all 1252;
`profile_taxa` (taxonomic profiling) completed for 1245 — the other 7 are
`minreads`-floor drops or in-flight retries, not hard failures.

**Cost** (`infra/get_aws_batch_spend.py`, Cost Explorer, us-east-2): run
started 2026-08-15 06:32. CE data lags 8–14 h, so only 2026-08-15 and
2026-08-16 are settled as of this writing — 2026-08-17 (the day of the stuck
job / cancel / relaunch) isn't billed yet.

| Date | VM (spot+on-demand) | EBS/other | Pre-run baseline subtracted |
|---|---:|---:|---:|
| 2026-08-15 | $104.59 | $17.24 | VM −$14.54/day, EBS −$3.08/day |
| 2026-08-16 | $124.49 | $17.63 | (baseline = 2026-08-14, no run activity) |

Run-attributable compute (2 days only): $200.00 VM + $28.71 EBS = **$228.71**.

**$/sample so far: ~$0.183** ($228.71 ÷ 1245 completed taxa profiles) —
**partial**, missing a full day (2026-08-17) of compute. Re-run
`infra/get_aws_batch_spend.py` after 2026-08-18 to get the settled Aug-17
figure and a true final $/sample once the run completes. Checked again on
2026-08-17 (same day) — CE still only has 08-15/08-16 settled, unchanged
from above; CE settles a day's data 8–14 h after that day's own UTC
midnight, so today's own spend is never visible same-day no matter how long
you wait within it.

## Revision 3 (2026-08-17) — a 50M-pair cap, applied upstream

Approved: **50 million pairs per sample**, and it is enforced in **stage 1**,
not in fastp. `conf/gemma.config` keeps `nreads = 0`; `preprocess_gemma.nf` runs
with `--cap 50000000`.

### Why cap again at all

The uncapped plan carried `GMA_353` at 392M pairs — a predicted ~20 h of HUMAnN
in a single task, a 24 h `resourceLimits` ceiling, and a >6 h spot job that one
reclamation restarts from zero. 400M pairs is far more depth than the analysis
needs. At 50M the deepest possible task is a predicted 2.6 h of HUMAnN
(17.7 min MetaPhlAn), which fits one 6 h attempt with 2.3× headroom, and the
24 h ceiling is gone.

### Why not in fastp

`fastp --reads_to_process` is head truncation. See *Where the design landed* at
the top for the flowcell-loss measurement. The short version: capping in fastp
would trade a depth problem for a batch-effect problem on exactly the samples
that are most valuable.

### What the cap actually touches

| batch | samples | over 50M pairs | pairs before → after |
|---|---:|---:|---|
| `under8g` | 1252 | **0** (real max 45.1M) | 18.86 G → 18.86 G (no-op) |
| `over8g` | 104 | 12 (byte-estimated) | 4.31 G → 3.77 G (−12.6%) |

`under8g`'s max is a **real** readcount from the finished run (n=1252, median
20.3M, p99 33.3M, max 45.1M pairs), not a byte estimate — so the finished
`under8g` results are already cap-compliant and are not re-run.

The 12 samples the cap binds on, and the share of each that survives:

| sample | Mpairs | GB gz | flowcells | lanes | kept |
|---|---:|---:|---:|---:|---:|
| `GMA_353` | 395.8 | 111.6 | 3 | 6 | 12.6% |
| `sGMA_454` | 83.3 | 23.5 | 1 | 2 | 60.0% |
| `GMA_338` | 81.7 | 23.1 | 2 | 5 | 61.2% |
| `GMA_1426` | 79.0 | 11.9 | 3 | 4 | 63.3% |
| `GMA_1441` | 76.8 | 11.6 | 4 | 5 | 65.1% |
| `GMA_Sal_6_TST` | 73.5 | 20.7 | 1 | 1 | 68.1% |
| `GMA_226` | 65.5 | 18.5 | 3 | 5 | 76.3% |
| `GMA_913` | 61.0 | 17.2 | 1 | 4 | 81.9% |
| `GMA_1459` | 59.6 | 9.0 | 3 | 4 | 83.8% |
| `GMA_1470` | 56.4 | 8.5 | 4 | 5 | 88.7% |
| `GMA_1123` | 54.9 | 15.5 | 3 | 4 | 91.1% |
| `GMA_1127` | 54.4 | 15.3 | 3 | 4 | 91.9% |

286 GB of gz — **4.7% of the cohort** — has to be re-processed. Everything else
already on S3 stays exactly as it is.

### How stage 1 takes the sample

`preprocess_gemma.nf` already had the proportional path; it had never run in
production (every summary row from the 2026-08-15 full-cohort run says `cat`).
Two things changed:

1. **`bin/gemma_take_pairs.py` gained a systematic mode.** Given `--records k`
   and `--total n` for a lane, it emits record *i* when a Bresenham accumulator
   (`acc += k`, emit and `acc -= n` when `acc >= n`) crosses — an even stride
   over the entire lane instead of a prefix. Selection depends only on the
   record number, so R1 and R2 pick **identical record indices** and positional
   pairing survives. Head mode (no `--total`) is retained for the smoke slice.
   The cost is decompressing the whole lane, which is why this is worth doing
   only for the few samples over the cap.
2. **The skip check learned provenance.** `--skip_existing` used to compare only
   object size, which cannot distinguish "built under a different cap" from
   "built correctly" (`GMA_1127`'s uncapped object is just 9% larger than its
   capped one). The per-sample log now carries a `plan_mode` column, and the
   check reads the *published* log back: `cat`-mode output is byte-identical
   under any cap, so it needs only the size check (now two-sided); proportional
   output additionally has to match the previous run's plan. Effect: **re-running
   the whole cohort at the new cap redoes exactly the 12 samples and skips the
   other 1344.**

Verified offline against a fake-S3 shim (3 samples, 5 lanes, 2 flowcells):
exact cap hit, both flowcells represented at equal rate, R1/R2 selecting the
same reads, and the skip check behaving correctly across four cap transitions
(same cap → skip all; tighter cap → rebuild the bound samples; cap 0 → rebuild
as `cat`; back to the cap → rebuild proportional).

Throughput measured at ~1 M records/s for the sampler on top of gzip inflate,
so `GMA_353` (392M pairs × 2 reads) is a ~2 h task. `conf/aws_batch.config`
gained a `withName: 'GEMMA_MERGE_LANES'` block (cpus 4, 4 GB, `4.h × attempt`)
— the previous 1 h default would have killed it.

### Why dedup still is not done per lane

The question came up as "derep each lane, then sample each of those". No:
GEMMA's extra flowcells are **re-sequencing of the same library**, so the
duplicates that matter are cross-flowcell and a per-lane dedup cannot see them.
It would also force stage 1 to decompress and recompress all 5.55 TiB rather
than 4.7% of it. Dedup stays in `clean_reads`, on the merged pair, **after**
sampling. Cost of that ordering: the ~4% of the 50M that turns out to be
duplicate. Measured duplication on the finished `under8g` run is **3.8–6.1%**
(fastp, n=3 — the only samples in that run's MultiQC general-stats table, so
treat it as indicative rather than a cohort estimate), with 94–96% of reads
surviving fastp overall.

### Config consequences

`conf/gemma.config` keeps `nreads = 0` but was re-tuned for a world where
nothing exceeds 50M pairs:

- `profile_function` `time` → flat `6.h` (was `attempt==1 ? 6.h : 24.h`)
- `profile_taxa` `time` → `1.h × attempt` (was `3.h × attempt`)
- `resourceLimits.time` → `6.h` (was `24.h`); `cpus` stays 32
- `--fastp_dedup_accuracy 6` for `over8g` dropped — accuracy 3 for both batches,
  no per-batch command-line flags at all
- `count_reads` now measures capped depth, so `readcount/` and the profiled
  depth agree again (under the fastp-cap alternative they would not have)

`cpus` 16 → 32 on `profile_taxa`/`profile_function` is unchanged and unrelated
to the cap: both tools burst to 2× their requested cpus internally, so
requesting 16 let Batch's bin-packer believe 2 jobs fit a `c8g.12xlarge`
(48 vCPU) when real thread usage is 64. `resourceLimits.cpus` is 32 to match,
or the requests would be clamped back to `aws_batch.config`'s 24.

## `over8g` production plan — updated 2026-08-17



Full details and the finalized decisions are in the canonical playbook,
`s3://gutz-nf-reads-profilers-runs/playbooks/gemma.md` (`## Decisions
(2026-08-17)`, `### How long the deep samples take`) — summary:

- **Runtime model**: replaced the cosmosid-infant extrapolation (21× past its
  fitted range) with a linear regression fit directly on the completed
  `under8g` run's own readcount × trace data (R² 0.95/0.96, <7–9% mean abs
  error against actual `under8g` runtimes). Scripts:
  `bin/gemma_join_readcount_runtime.py`, `bin/gemma_runtime_vs_readcount.R`,
  `bin/gemma_predict_runtime.py`.
- **`GMA_353`** (396M pairs, 4.7× the next-largest sample in either cohort) is
  capped to 50M pairs by stage 1, so it predicts to 17.7 min `profile_taxa` /
  2.6 h `profile_function` and runs **inline** in the normal `over8g` batch.
  `bin/build_gemma_samplesheet.py` gained `--sort-by-readcount`;
  `gemma-over8g.csv` was regenerated with `GMA_353` sorted to row 1 so it
  starts immediately rather than becoming the tail straggler.
- **`cpus` 16 → 32** for `profile_taxa`/`profile_function` in
  `conf/gemma.config` — both tools burst to 2× their requested cpus
  internally (measured), so the old request of 16 let AWS Batch's
  bin-packer under-count real host thread usage (documented oversubscription
  on `c8g.12xlarge`: 2 jobs × 32 real threads = 64 > 48 vCPUs). Requesting
  the true 32 fixes Batch's own accounting.
- **`profile_function` time** is a flat `6.h` and `resourceLimits.time` is back
  to `6.h`: with stage 1 capping at 50M pairs, nothing needs the 24 h ceiling.
  `resourceLimits.cpus` raised 24 → 32 to match the per-process cpu request.
- All config changes synced to the FUSE/S3-backed `conf/gemma.config` and
  validated with `nextflow -C conf/gemma.config config` (exit 0, directives
  resolve as intended). **Blocker before launching `over8g`: stage 1 has to be
  re-run at `--cap 50000000`** so the 12 over-cap samples are resampled — see
  *Revision 3*. `over8g` has not been launched yet.
