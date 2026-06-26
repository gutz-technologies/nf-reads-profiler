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

### Infrastructure scripts

| Script | Purpose |
|--------|---------|
| `infra/smoke-test.sh` | 2-sample end-to-end smoke test on AWS Batch |
| `infra/max005_test.sh` | 5-sample scaling baseline (I16); must run under screen |
| `infra/medi_test.sh` | Full MEDI end-to-end test; must run under screen |

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
- AWS: `/mnt/dbs/...` — pre-baked custom AMI (Packer, see
  `issues/I14-custom-ami-worker.md`). The `spot-metaphlan` queue instead copies
  vJan25 from S3 at boot (see `infra/multiqueue-design.md`).
