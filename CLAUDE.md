# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

User- and operator-facing docs — running the pipeline, profiles, output layout,
databases, infra scripts — live in `README.md` and are imported below. This file
adds only the agent/code-internal guidance on top.

@README.md

## Samplesheet schema

Input is a CSV validated by `assets/schema_input.json` via the `nf-schema`
plugin. Each row has `fastq_1`, `fastq_2` (optional), and an SRA id column.
`main.nf` branches rows: rows with `fastq_1` set are treated as local files;
rows without local files but with an `[ESD]RR\d+` id go through `AWS_DOWNLOAD`
→ `FASTERQ_DUMP`. `single_end` is derived from whether `fastq_2` is present
(local) or the number of FASTQs produced (SRA).

## Code architecture

`main.nf` is the only top-level workflow. It wires three module files and two
subworkflows:

- `modules/data_handling.nf` — `AWS_DOWNLOAD`, `FASTERQ_DUMP` (SRA ingest from S3 → FASTQ).
- `modules/house_keeping.nf` — `count_reads`, `clean_reads` (fastp), `get_software_versions`, `MULTIQC`.
- `modules/community_characterisation.nf` — `profile_taxa` (MetaPhlAn4),
  `profile_function` (HUMAnN4), and HUMAnN table plumbing:
  `combine_humann_tables`, `combine_humann_taxonomy_tables`,
  `combine_metaphlan_tables`, `split_stratified_tables`, `convert_tables_to_biom`,
  `regroup_genefamilies`.
- `subworkflows/quant.nf` — `MEDI_QUANT` (Kraken2 → Architeuthis filter →
  Bracken → food-content quantification), gated on `params.enable_medi`.
- `subworkflows/strainphlan.nf` — `STRAINPHLAN` (sample2markers → print_clades →
  extract_markers → strainphlan tree), gated on `params.enable_strainphlan`.
  Consumes `profile_taxa.out.sam` — when `enable_strainphlan=true`, `profile_taxa`
  runs MetaPhlAn with `-s <id>.sam.bz2` instead of `--no_map`. `print_clades` and
  the per-clade RAxML tree are **per-run reduces** (`groupTuple` on `meta.run`);
  with `strainphlan_clades` empty (default) it stops after `print_clades`, which
  reports which clades are available before you commit to trees. Incompatible
  with `skipCompleted` (guarded in `main.nf`): a skipped sample never produces a
  SAM and SAM is not published, so it would silently drop from the per-run reduce.

Channel shape used throughout: `[ meta, reads_or_file ]`, where `meta` is a
map carrying at least `id` and `run` (study grouping key). Combines work by
dropping `id` from meta, tagging a `type` (`genefamilies`/`reactions`/
`pathabundance`/`metaphlan_profile`), then `groupTuple`-ing per study+type.
Stratification (`'stratified'`/`'unstratified'`) is stamped onto meta by the
main workflow *after* `split_stratified_tables` emits its two channels —
`main.nf` does these `.map` stamps inline, so splitter processes stay unaware
of stratification semantics.

Early-exit: `output_exists(meta)` in `main.nf` checks whether all three HUMAnN
TSVs already exist in `outdir/project/run/function/` — used to skip samples on
resume-style reruns.

The HUMAnN biom-conversion branch (`split_stratified_tables` →
`convert_tables_to_biom`) is **active** for every `enable_humann` run (enabled
in `57da5a3`, 2026-05-12, which removed the old `params.annotation` gate). It
runs after `combine_humann_tables`: splits each combined TSV into
stratified/unstratified, then converts every (type × stratification) to `.biom`
under `outdir/<project>/<run>/combined_tables/` and the per-type
`outdir/<project>/combined_bioms/`. `regroup_genefamilies` is a further branch
gated on `params.humann_regroup` (off by default).

## AWS Batch infra

Managed by two CloudFormation templates: `infra/batch-stack.yaml` (compute —
stack `nf-reads-profiler-batch`) and `infra/monitoring-stack.yaml`
(observability: SNS topic, alarms, EventBridge→Lambda metric publishers,
dashboard, budget — stack `nf-reads-profiler-monitoring`, split out at the
51 KB inline-template limit; imports the compute stack's queue-ARN exports, so
deploy compute first). Lint both with `cfn-lint infra/*.yaml` (no size limit,
unlike `validate-template`); `/deploy-stack` deploys both in order. Region
`us-east-2`, account `730883236839`.
All compute is **Graviton (ARM64)** — runner and workers both. Three job queues
(`spot-queue`, `spot-metaphlan`, `spot-humann`):

- `spot-queue` — default for all DB-free glue jobs (count/clean/combine/multiqc/
  SRA ingest). Two CEs: spot (primary) + on-demand (fallback). Now uses the thin
  stock AMI (awscli only, no DBs, no FSR) since no DB-bound jobs route here.
- `spot-metaphlan` — `profile_taxa` + `STRAINPHLAN:*` only (routed via
  `withName ... queue =` in `conf/aws_batch.config`). Spot-only, single CE,
  thin stock AMI that copies vJan25 from S3 at boot (~3–5 min/instance, no FSR,
  no Packer rebuild).
- `spot-humann` — `profile_function` only. Spot-only, single CE, thin AMI that
  syncs the HUMAnN DB set (~65 GiB) from S3 at boot. The per-database-queue
  pattern (and the planned `spot-medi`) is documented in
  `infra/multiqueue-design.md`. NOTE: with all three queues on thin AMIs, the
  baked-DB custom AMI (`EcsAmiId`) and its FSR/Packer pipeline are now orphaned
  — candidate for removal.

Two S3 buckets:

- `gutz-nf-reads-profilers-workdir` — Nextflow workDir, 30-day lifecycle, stack-managed.
- `gutz-nf-reads-profilers-runs` — samplesheets and results, `DeletionPolicy: Retain`.

Deploy, teardown, drift-recovery, and EFS setup steps are in `infra/readme.md`.
The `head-node-role` on the runner VM must have
`nf-reads-profiler-nextflow-runner-policy` attached; `conf/aws_batch.config`
references `nf-reads-profiler-batch-job-role` as `aws.batch.jobRole`.

Resource caps live in `conf/aws_batch.config` via `process.resourceLimits` —
retries won't blow past these (prevents runaway memory on retry storms).

### Deploying compute-resource changes REPLACES the CE (kills running jobs)

The CEs in `batch-stack.yaml` do not set `ReplaceComputeEnvironment`, so it
defaults to **`true`**: any change to a CE's *compute resources* (most commonly
`InstanceTypes`, but also subnets/SGs/allocation strategy) makes CloudFormation
**replace the entire CE** — create a new physical resource, then delete the old
one, terminating every instance on it and killing in-flight jobs. Verified
2026-06-23 via stack events: a deploy that only edited `SpotMetaphlan`'s
`InstanceTypes` emitted "Requested update requires the creation of a new
physical resource; hence creating one" and drained the CE. **Exception:** a
pure `maxVcpus` change updates *in place* (no replacement) — that's why the
`MaxvCPUsHumann` 600→960 bump didn't disturb running humann jobs, but the
later InstanceTypes edit did.

Rules of thumb:
- **Never deploy an `InstanceTypes` (or other compute-resource) change while a
  run is live** on the affected queue — it will kill the running jobs. Stage the
  YAML edit and deploy after the run, or accept the job loss (jobs retry under
  `maxSpotAttempts`/Nextflow, but it's a real interruption).
- YAML **comment-only** edits never trigger this — CloudFormation discards
  comments; replacement is always property-level.
- Observed but unconfirmed: in the 2026-06-23 deploy the *unchanged* humann CE
  was replaced alongside metaphlan. Leading hypothesis is the launch-template
  `Version: $Latest` ref making CFN re-evaluate/replace all CEs on any compute
  update (changeset auto-deleted, so not provable from artifacts). Treat "deploy
  any compute-resource change" as potentially churning **all** CEs until ruled
  out.
- To make such edits non-destructive, set `ReplaceComputeEnvironment: false`
  plus an `UpdatePolicy` (`TerminateJobsOnUpdate: false`, a
  `JobExecutionTimeoutMinutes`) so Batch updates in place and drains running
  jobs instead of terminating them. Not yet applied to this stack.

### `project` and execution-report paths (config gotcha)

`params.project` defaults to `"none"`; `main.nf` now fails fast if it's left
unset (so outputs don't silently land under `<outdir>/none/`). Always set a real
project.

The `timeline`/`report`/`dag`/`trace` file paths embed `${params.outdir}` and
`${params.project}`. Nextflow interpolates these GStrings **at config parse
time**, not at runtime, so they freeze to whatever `project`/`outdir` are when
the block is parsed. Consequences:

- A `project` passed on the **CLI** (`--project`) binds before any config parses,
  so it reaches the report paths — this is why playbook CLI runs land correctly.
- A `project` set in a **`-c` run config's `params{}` block** is merged *after*
  `nextflow.config`'s report blocks parse, so those blocks freeze to `none`.
  `conf/aws_batch.config` re-declares the report blocks (after its own S3
  `outdir`) to override that — but for `project` to resolve there, the run config
  **must set `params { project = ... }` BEFORE `includeConfig
  conf/aws_batch.config`**. Include-then-params freezes to `none` (verified with
  `nextflow config`). Outputs (publishDir, `main.nf`) read `params.project` at
  runtime and are always correct; only the four report files are affected.

## Key parameters

Defined in `nextflow.config`:

- `enable_humann` (default true) — run functional profiling and all HUMAnN combine/split steps.
- `singleEnd`, `mergeReads`, `nreads` (32,000,000 cap), `minreads` (100,000 floor; samples below this are logged and dropped, not failed).
- `process_humann_tables`, `humann_regroups` (e.g. `"uniref90_ko,uniref90_rxn"`), `split_size` — used by the currently-disabled regroup branch.
- `humann_params` — passthrough (test profile sets `--bypass-translated-search`).
- `enable_strainphlan` (default false) — emit MetaPhlAn SAM from `profile_taxa`
  and run the StrainPhlAn subworkflow. Incompatible with `skipCompleted`.
- `strainphlan_clades` — comma-separated clades (e.g. `"t__SGB1877,t__SGB2318"`)
  to build strain trees for. Empty (default) stops after `print_clades`.
- MEDI: `enable_medi`, `confidence`, `consistency`, `entropy`, `multiplicity`, `read_length`, `threshold`, `batchsize`, `mapping`, plus fastp knobs (`trim_front`, `min_length`, `quality_threshold`).

Error strategy is profile-dependent. Azure uses `errorStrategy = 'ignore'`
with retries on labelled processes; AWS defaults to `maxRetries = 0` plus
`resourceLimits`. Failed samples are logged and skipped, not fatal.

## Tests

`nf-test test` runs the nf-test suite (`tests/`, `nf-test.config`). There is
also a Python-side test harness under `tests/` for `bin/safe_cluster_process.py`
and friends — run with `python tests/run_integration_tests.py`. These cover
the (currently-disabled) HUMAnN split/regroup Python utilities, not the
Nextflow workflow itself.

## Scripts in `bin/`

Shipped on the Nextflow `PATH`. The table-processing scripts
(`safe_cluster_process.py`, `safe_regroup.py`, `process_humann_tables.sh`) are
only reached when the biom-conversion branch is re-enabled. The `scrape_*.sh`
helpers parse tool logs into MultiQC-custom-content TSVs; `medi_csv_to_biom.py`
converts MEDI CSV outputs.

## Custom agents and skills (`.claude/`)

**Agents** (spawn via `@agent-name` or the Agent tool):

- `batch-doctor` — read-only health check of the full Batch stack: CEs, queue,
  recent failures, launch template, S3 buckets, Nextflow logs. Produces a
  status table with WARN/FAIL callouts.
- `log-reader` — parses `.nextflow.log*` and fetches CloudWatch logs for
  failed Batch jobs. Produces a concise run report (succeeded/failed/aborted
  tasks, error messages, timing).

**Skills** (invoke via `/skill-name`):

- `deploy-stack` — validates the CloudFormation template, deploys, waits, and
  re-validates compute environments. Always shows the diff first.
- `preflight` — pre-flight checklist before a pipeline run: CEs valid, queue
  enabled, launch template UserData correct, S3 reachable, no stuck jobs.

## Debugging AWS Batch failures

When a pipeline run fails on AWS Batch, the diagnosis workflow is:

1. **Read the Nextflow log** — `grep 'ERROR\|FAIL' .nextflow.log` for the
   process name, exit code, and error summary.
2. **Get the Batch job log** — find the failed job's CloudWatch log stream in
   `/aws/batch/job` (log stream names follow
   `<job-def>/default/<job-id>`). The last few lines usually have the root
   cause.
3. **Check worker state** — if the error is a missing file/DB, the database
   may not be present. Currently this means the S3 sync didn't complete;
   after the custom AMI migration (see `issues/I14-custom-ami-worker.md`),
   it means the wrong AMI was used. Connect to the worker (if still running)
   and check `/var/log/nf-userdata.log` and `ls /mnt/dbs/`. No SSH/keys — use
   SSM: `aws ssm start-session --target <instance-id> --region us-east-2`
   from a human operator's own AWS CLI session (their IAM identity has
   `ssm:StartSession`). The runner's assumed role (`head-node-role`, what
   Claude Code's `aws` calls run as) does NOT have this permission by
   design — SSM is for human watchers, not the automation. If Claude needs
   worker-side visibility, use CloudWatch logs (`/aws/batch/job`) instead.
4. **Common failure modes**:
   - "database does not exist" → S3 sync race or wrong AMI (see
     `infra/readme.md` troubleshooting and `issues/I14-custom-ami-worker.md`).
   - "Essential container in task exited" → container OOM or command error;
     check CloudWatch logs for the specific error.
   - "Job killed by NF" → Nextflow aborted the run after a different task
     failed; find the original failure.
   - Jobs stuck in RUNNABLE → no capacity; check CE MaxvCpus and spot
     availability.

## Guardrails (`.claude/hooks/guardrails.sh`)

A PreToolUse hook that runs before every Bash, Write, and Edit call. Hard
blocks (exit 2) are non-negotiable; soft blocks prompt for confirmation.

**Hard blocks:**

| Category | What's blocked |
|----------|---------------|
| Docker destruction | `docker compose down -v`, `docker volume rm/prune`, `docker system prune` |
| Runaway EC2 | `aws ec2 run-instances`, `aws ec2 request-spot-instances` |
| Batch escalation | `update-compute-environment` with `maxvCpus` > 64 |
| CFN deletion | `aws cloudformation delete-stack` |
| Disk bombs | `dd if=`, `fallocate`, `mkfs` |
| Repo escape | `rm -r` outside the repo, Write/Edit to paths outside repo or `~/.claude/` |
| Git destruction | `git push --force` to main/master, `git reset --hard` on main/master |
| Secrets | Write to `.env`, `credentials`, `*.key`/`*_key.pem` files |

**Soft blocks (user confirmation prompt):**

| Category | What's prompted |
|----------|----------------|
| AWS pipeline launch | `nextflow run ... -profile aws` |

To override a hard block, the user must edit `guardrails.sh` directly.
