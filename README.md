## Acknowledgement

This pipeline is based on the original [YAMP](https://github.com/alesssia/YAMP) repo. Modifications have been made to make use of our infrastructure more readily. If you're here for a more customizable and flexible pipeline, please consider taking a look at the original repo.

# nf-reads-profiler

Nextflow DSL2 pipeline for metagenomic read profiling. Core tools: MetaPhlAn4,
HUMAnN4, fastp, MultiQC. Optional MEDI subworkflow (Kraken2/Bracken/Architeuthis)
for food microbiome quantification, and an optional StrainPhlAn subworkflow for
strain-level profiling. Runs on AWS Batch (primary) with local Docker for
development.

## Usage

### AWS Batch (production)

**Always launch inside `screen` — SSH disconnects and Claude Code client exits will
kill a foreground Nextflow process.**

```bash
# 1. Lock the MEDI Kraken2 hash into RAM — MEDI kraken runs in Docker on this
# head node; vmtouch warms the shared OS page cache so the container sees it instantly.
# -d daemonizes so it holds the lock while Nextflow runs.
vmtouch -dl /mnt/scratch/ssddbs/medi_db/hash.k2d

# 2. Start a named screen session and run the pipeline
screen -S nf-aws
nextflow run main.nf -profile aws \
  --input s3://gutz-nf-reads-profilers-runs/samplesheets/<name>.csv \
  --project <project_name> -resume

# 3. From another terminal: follow Nextflow's own log
tail -f .nextflow.log
grep "status: COMPLETED" .nextflow.log | grep -oP "name: \K\S+" | sort | uniq -c


# 4. After the pipeline finishes: release the MEDI hash lock
pkill vmtouch
```

To watch a Batch worker live (e.g. tail `/var/log/nf-userdata.log` for the boot-time
DB copy): `aws ssm start-session --target <instance-id> --region us-east-2` — no SSH
keys, but needs `ssm:StartSession` on your runner role (not granted by default).

Samplesheets live in `s3://gutz-nf-reads-profilers-runs/samplesheets/`. See
`samplesheets/slice.md` (also in that bucket) for how to build new slices.

### Local (Docker, dev/test)

```bash
# Basic test — small bundled data, no screen needed
nextflow run main.nf -profile test

# With MEDI food-microbiome quant (requires local SSD DBs at /mnt/scratch/ssddbs/)
screen -S nf-test
# Lock the Kraken2 hash into RAM before the first job (cold ~30 min; warm <1 min/sample).
# -d daemonizes so it holds the lock in the background while Nextflow runs.
vmtouch -dl /mnt/scratch/ssddbs/medi_db/hash.k2d
nextflow run main.nf -profile test_medi -resume
```

`screen` basics: detach with `Ctrl+A D`, reattach with `screen -r <name>`, list
with `screen -ls`.

**Cancelling a run cleanly:** send Ctrl-C into the screen session running
Nextflow (e.g. `screen -S <name> -X stuff $'\003'`) instead of killing the
process or the screen session. Nextflow's SIGINT handler does a graceful
abort: it terminates any in-flight AWS Batch jobs itself (no manual
`aws batch terminate-job` needed), flushes the execution report/trace, and
writes `Execution complete -- Goodbye` to `.nextflow.log` — the same clean
exit as a normal finish. Since `.nextflow.log` lives on S3 workDir for AWS
runs (no local tail -f), this is the only way to get a legible, complete log
instead of an abrupt cutoff. Verified 2026-08-17 on the gemma under8g run
(stuck on an unschedulable `combine_humann_tables` job): SIGINT → job
terminated → report saved → clean Goodbye, all within ~5s.

### Profiles

Profile-to-config mapping (`nextflow.config`):

- `aws` → `conf/aws_batch.config` (S3 workDir, `awsbatch` executor, Graviton spot queues)
- `azure` → `conf/azurebatch.config`
- `test` → `conf/test.config` (local Docker, tiny `nreads`/`minreads`)
- `test_medi` → `conf/test_medi.config` (extends `test`; enables MEDI, sets ssddbs paths, disables cleanup)

### Detecting when a run has ended

A finished run leaves no `nextflow run` process and no Docker containers, but
those alone are racy. Reliable signals, in order of preference:

- **`.nextflow.log`** — the definitive end marker is the final line
  `Execution complete -- Goodbye` (preceded by `Session await > all barriers
  passed`). Grep it: `grep -c 'Execution complete -- Goodbye' .nextflow.log`.
  This is written for both success and failure.
- **Console/tee output** — the pipeline prints `[SUCCESS] completed=N failed=M
  cached=K` (or a failure summary) as its last lines. Good for at-a-glance
  status, but only present if you teed stdout (e.g. `... | tee /tmp/run.out`).
- **`nextflow log` / `.nextflow/history`** — the run's status column flips to
  `OK`/`ERR` once it ends; `-` means still running or killed. Lags slightly
  behind the log's Goodbye line.

Don't rely on the `screen` session disappearing — if you launched with
`screen -dmS name bash -c "... | tee ..."`, the session ends the instant the
command returns, so its absence tells you nothing about success vs. failure.

## Output

All results land under `outdir/<project>/`. Three tiers: per-sample → per-study
combines → project-wide biom rollup. Layout below was verified against a real
2890-sample run (`diversigen-infant`).

```
outdir/<project>/<run>/
  ├── readcount/<id>_readcount.txt          # read count per sample
  ├── taxa/<id>_metaphlan.biom              # MetaPhlAn4 profile per sample
  ├── function/                             # HUMAnN4, per sample (only if --enable_humann, default true)
  │     ├── <id>_0.log
  │     ├── <id>_1_metaphlan_profile.tsv    # HUMAnN-internal MetaPhlAn
  │     ├── <id>_2_genefamilies.tsv
  │     ├── <id>_3_reactions.tsv
  │     └── <id>_4_pathabundance.tsv
  ├── combined_tables/                      # per-study combines, TSV only (HUMAnN)
  │     └── <run>_<type>_combined.tsv       # type = reactions | pathabundance | humann_taxonomy
  │                                         #   (genefamilies_combined.tsv NOT published — too big, ~24 GB;
  │                                         #    reconstructable from its stratified/unstratified biom)
  ├── medi/                                 # only if --enable_medi
  │     ├── bracken/<lev>/<lev>_<id>.b2     # per-sample Bracken counts (D/G/S); .b2 only
  │     ├── food_abundance.csv, food_content.csv
  │     ├── <lev>_counts.csv                # D/G/S lineage-annotated counts (medi/ root)
  │     ├── merged/<lev>_merged.csv         # D/G/S merged
  │     ├── multiqc_report.html
  │     └── architeuthis/<id>_mapping.csv, mappings.csv   # only if --mapping (off by default)
  ├── strainphlan/                          # only if --enable_strainphlan
  │     ├── consensus_markers/<id>.json.bz2 # per-sample consensus markers
  │     ├── print_clades_only.tsv           # clades detectable across the run's samples
  │     └── trees/RAxML_*, *.aln            # per clade in --strainphlan_clades (empty = stop after print_clades)
  └── log/                                  # nf-profile-reads-Report_multiqc_report.html + _data/

outdir/<project>/combined_bioms/            # project-wide biom rollup, one dir per type
                                            # — the single home for ALL biom (no per-run copy)
  ├── metaphlan/<run>_metaphlan_combined.biom
  ├── genefamilies/<run>_genefamilies_{stratified,unstratified}.biom
  ├── pathabundance/<run>_pathabundance_{stratified,unstratified}.biom
  ├── reactions/<run>_reactions_{stratified,unstratified}.biom
  ├── humann_taxonomy/<run>_humann_taxonomy.biom
  ├── regrouped/                            # only if --humann_regroup (off by default)
  └── medi/<run>_food_abundance.biom, _food_content_nutrients.biom, _food_content_compounds.biom

outdir/<project>/reports/                   # timeline, report, trace (timestamped via params.ts)
```

Kraken2 intermediates (`.k2`/`.tsv`) and the Bracken `*_bracken.tsv` side-file are
**not** published — they flow through channels only (publishDir commented out in
`subworkflows/quant.nf`).

StrainPhlAn runs only with `--enable_strainphlan` (default off), which switches
`profile_taxa` from `--no_map` to emitting a MetaPhlAn SAM per sample (the SAM
itself is **not** published). `--strainphlan_clades` is a comma-separated clade
list (e.g. `"t__SGB1877,t__SGB2318"`) to build trees for; empty (default) stops
after `print_clades`, which reports the available clades. `--enable_strainphlan`
is incompatible with `skipCompleted`: skipped samples would drop from the per-run
clade detection and tree build, so the run errors fast if both are set.

## MEDI downstream human read counts

`bin/collate_medi.sh` also produces `medi/human_read_counts.csv`, with one row
per sample found in the staged D/G/S Bracken files. It is retained with the other
local outputs under `--dry-run`, and uploaded alongside food reports otherwise.

`kraken_assigned_human_read_ends` takes `kraken_assigned_reads` for species taxid
9606 (Homo sapiens) from the species `.b2` file. It counts assignments surviving
Architeuthis filtering, before Bracken redistribution. It is distinct from
MEDI's existing `human_reads`, which uses Bracken estimates and repeats across
food rows. No original-library read count or host percentage is inferred.
MEDI receives HUMAnN4's `bowtie2_unaligned.fa`: reads without an accepted
nucleotide alignment to the sample-specific ChocoPhlAn pangenome, before the
DIAMOND protein search. Human is present in the MEDI database (GRCh38.p14).

`status=reported` means a human row was present. `human_taxon_not_reported`,
`empty_species_table`, and `missing_species_table` retain `NA` counts: Bracken's
reporting threshold means absence cannot establish zero human assignments.
Samples absent from every staged D/G/S file cannot be audited by this report.
`source_species_table` records the relative species-file path. For an existing
local or mounted Bracken directory, the report can also be generated alone:

```bash
python3 bin/medi_human_read_counts.py /path/to/medi/bracken human_read_counts.csv
```

## Standalone KneadData count collation

The root-level `collate_kneaddata.sh` reads an existing tab-delimited KneadData
summary with Python 3.9+ (standard library only). It writes a local TSV; it does
not run profiling or upload results. `--output` refuses to overwrite a file;
omit it to write to stdout. Diagnostics go to stderr.

```bash
mkdir -p results_kneaddata
./collate_kneaddata.sh \
  /home/ubuntu/github/globus_2026/globus-share/results/cosmosID_kneaddata_read_counts.txt \
  --cohort cosmosid-infant \
  --samplesheet /home/ubuntu/gutz-nf-reads-profilers-runs/samplesheets/cosmosid-infant-full.csv \
  --aliases collate_kneaddata_cosmosid_aliases.csv \
  --output results_kneaddata/cosmosid.tsv
./collate_kneaddata.sh \
  /home/ubuntu/github/globus_2026/globus-share/results/diversigen_kneaddata_read_counts.txt \
  --cohort diversigen-infant \
  --samplesheet /home/ubuntu/gutz-nf-reads-profilers-runs/samplesheets/diversigen-infant-published.csv \
  --output results_kneaddata/diversigen.tsv
```

Counts are **read ends**, not pairs: raw is `raw pair1 + raw pair2`; each later
stage sums both paired and both orphan columns. The measured loss is
`trimmed_read_ends - decontaminated_read_ends`, reported over both trimmed and
raw totals as fractions from 0 to 1. This avoids treating orphan creation as
host removal. It also excludes trimming loss from the numerator. Original stage
counts, source path, SHA-256, line number, reference label, and sample IDs are
retained for auditing.

**Host attribution is unresolved.** KneadData's
[read-count exporter](https://github.com/biobakery/kneaddata/blob/master/kneaddata/read_count_table.py)
extracts stage counts from logs. Its
[workflow](https://github.com/biobakery/kneaddata/blob/master/kneaddata/knead_data.py)
can run tandem-repeat filtering between the trimmed count and reference
decontamination. Its
[reference output counts](https://github.com/biobakery/kneaddata/blob/master/kneaddata/run.py)
are retained reads. The supplied summaries do not establish the version,
intervening filters, alignment settings, or paired-read removal policy. Therefore
the collator labels the difference as `trimmed_to_decontaminated_removed_*`
and leaves `host_reference_removed_fraction_*` as `NA`. Do not interpret the
retained complement as microbial fraction or taxonomic relative abundance.

Additional provider evidence is available in
`/home/ubuntu/github/globus_2026/globus-share/results/filtered_fastq_README.html`.
It documents KneadData v0.10.0 for both CosmosID and Diversigen, using
`kneaddata -i $R1 -i $R2 -o $outputdirectory -db $GRCh38_noalt_as -t 10 --trimmomatic $Trimmomatic-0.39/`.
That command omits `--bypass-trf`; the
[v0.10.0 source](https://github.com/biobakery/kneaddata/blob/0.10.0/kneaddata/knead_data.py)
enables TRF by default and uses strict paired-read decontamination by default.
This is cohort-level protocol evidence, not a per-sample execution log. It
supports treating the measured loss as potentially including tandem-repeat
removal, rather than assigning all of it to host-reference removal. No
per-sample KneadData logs were found in the checked local Globus results or
the two mounted cohort directories (through their final-output directories).
Additional execution logs or pre-reference counts can refine attribution later;
missing evidence does not exclude a sample from the count or coverage outputs.

`NA`/blank counts remain missing, not zero; incomplete stage totals and affected
fractions become `NA`. Zero denominators also yield `NA`. Counts must be finite,
nonnegative integers; duplicate IDs and malformed schemas abort before writing.
Unequal pair counts or increasing stage totals flag a row as `invalid_counts`
and suppress derived losses. All summary rows are retained. With `--samplesheet`,
an outer join adds samples lacking summaries and distinguishes `matched`,
`summary_only`, and `samplesheet_only`. No pipeline-output presence is inferred
from samplesheet membership.

Only the terminal `_R1_kneaddata` suffix is removed automatically. Other ID
changes require an explicit one-to-one alias CSV. The supplied CosmosID aliases
map 50 `_CP05949` IDs; each mapping was checked against
`globus_2026/globus-share/results/Cosmos_Infant_SampleID.csv`, including agreement
between `KneadData_concat_depth` and the summary's final paired-read total.

Local audit on 2026-10-19: CosmosID has 2,098 complete summary rows, all matching
the full samplesheet with these aliases. Diversigen has 2,944 summary rows:
2,932 complete and 12 incomplete. All 2,890 published samples match complete
rows; 54 summary rows are outside that samplesheet. The broader 2,948-row
by-visit sheet has 7 samples absent from the summary and leaves 3 summary rows
unmatched. Final and GRCh38 stage counts agree on complete rows in both cohorts.
Pipeline inputs use paired FASTQs; these upstream metrics also include orphans.
These two summaries provide no KneadData measurement for GEMMA or TEDDY.

Run focused checks with
`python3 -m unittest discover -s tests/scripts -p test_collate_kneaddata.py -v`.

## Databases

All profiles expect pre-staged databases; nothing is downloaded at runtime.

### Parameters and staging paths

| Param | Purpose |
|-------|---------|
| `direct_metaphlan_id` / `direct_metaphlan_db` | Standalone MetaPhlAn (newer DB, e.g. `mpa_vJan25_CHOCOPhlAnSGB_202503`) |
| `humann_metaphlan_index` / `humann_metaphlan_db` | MetaPhlAn DB matched to HUMAnN4 (e.g. `mpa_vOct22_CHOCOPhlAnSGB_202403`) |
| `humann_chocophlan` / `humann_uniref` / `humann_utilitymap` | HUMAnN4 nucleotide/protein/mapping DBs |
| `medi_db_path` / `medi_food_matches` / `medi_food_contents` | MEDI Kraken2+Bracken DB and food metadata |

Staging paths differ per profile:

- Local / `test_medi`: `/mnt/scratch/ssddbs/...` — synced from
  `s3://cjb-gutz-s3-demo` to the instance-store RAID at `/mnt/scratch/ssddbs/`.
  `docker.runOptions` in `nextflow.config` bind-mounts this into Docker. vJan25
  was installed via `metaphlan --install` and is now in both ssddbs and S3.
- AWS: `/mnt/dbs/...` — each per-database queue's workers sync their DB set from
  S3 to `/mnt/dbs/` at boot on the thin stock AMI (no baked DBs). The
  `spot-metaphlan` queue copies vJan25 from S3 (see
  `infra/multiqueue-design.md`).
