# Validation checklist: spot-metaphlan queue (smoke test)

Run: 2 CosmosID samples, taxa + StrainPhlAn only, via
`conf/cosmosid-strainphlan-smoke.config` → project `cosmosid-strainphlan-smoke`.
Goal: prove the thin-AMI + S3-copy queue works end to end, and **measure boot
timing** since there is no FSR and no baked DB.

## A. Routing & correctness — does it work?

- [ ] Both `profile_taxa` jobs land on **`spot-metaphlan`** (not `spot-queue`).
- [ ] `count_reads` / `clean_reads` / MultiQC land on **`spot-queue`** (default).
- [ ] Worker booted on the **thin stock AMI** (`ThinEcsAmiId`), not the baked AMI.
- [ ] `/opt/conda-aws/bin/aws` was **reconstructed at boot** (awscli v2 install) —
      this is the new risk: if it's missing, every container fails to stage I/O.
- [ ] `/mnt/dbs/metaphlan_databases/vJan25/` present on the worker (12 objects,
      ~44 GB) and bind-mounted into the container (`volumes = ['/mnt/dbs:/mnt/dbs']`).
- [ ] MetaPhlAn ran with `--nproc 32` (2× the 16 requested cpus) — confirms the
      overprovisioning burst is in effect on the shared metal box.
- [ ] No `database does not exist` / missing-index errors.

## B. Boot & timing metrics (no FSR, no baked DB)

Measure on the worker via `/var/log/nf-userdata.log` (our UserData brackets each
phase with `=== ... at $(date) ===`). Grab it **before the spot worker scales to
zero** (SSH while RUNNING, or `sudo cat`/`cloud-init` after). Cross-check with
EC2 + ECS + Nextflow trace.

- [ ] **Instance load time without FSR** — spot request accepted → instance
      `running` → ECS-registered. The thin AMI is a stock public AMI (no custom
      snapshot), so this is plain EC2 boot, *not* the I24 95-min lazy-load.
      Source: EC2 console launch time; `nf-userdata.log` first `boot at` line;
      `cloud-init analyze blame` for per-unit boot cost.
- [ ] **S3 database copy time** — the `time aws s3 cp --recursive ... vJan25`
      block in `nf-userdata.log` (we wrapped it in `time`). Expectation ~3–5 min
      for ~44 GB; this is the figure that justifies "no FSR needed."
- [ ] **awscli install time** — the `Installing awscli v2` block (curl + unzip +
      install). Small, but counts toward boot-to-ready.
- [ ] **Docker / MetaPhlAn container boot** — ECR image pull (~4 GB metaphlan
      image) + container start, i.e. the job's **STARTING → RUNNING** gap.
      Source: Batch job timestamps (`createdAt`/`startedAt`) or the worker's
      `/var/log/ecs/ecs-agent.log` pull entries. First pull on a fresh instance
      is the slow one; a co-located 2nd job reuses the cached image.
- [ ] **Boot-to-first-job total** = instance request → first `profile_taxa`
      RUNNING. This is the real "cold worker" penalty the queue pays once per VM.
- [ ] **Per-job MetaPhlAn runtime** at `--nproc 8` (trace `duration`/`realtime`).

## C. DB-sharing / packing — the whole point of the queue

- [ ] Both `profile_taxa` jobs land on the **same instance** (one
      `r8g.metal-24xl`, 96 vCPU / up to 6 jobs at 16 cpus each). Source: Batch
      `describe-jobs` → `container.containerInstanceArn` matches for both; or both
      jobs' worker private IP identical in logs.
- [ ] The DB was copied **once** for that instance and **shared** by both jobs
      (single `nf-userdata.log` copy block, both containers read the same
      `/mnt/dbs`).
- [ ] Memory headroom OK: jobs at 36 GB each fit the 768 GB box, no OOM-kill
      (smoke = 2 jobs; a full run packs up to 6 × 36 GB = 216 GB).
- [ ] (If only 1 VM came up) Both jobs serialized/co-located rather than spawning
      a 2nd VM — acceptable either way for 2 samples; note which happened.

## D. Outputs

- [ ] `results/cosmosid-strainphlan-smoke/3month/taxa/<id>_metaphlan.biom` for
      both samples (>1 KB, plausible).
- [ ] `strainphlan/consensus_markers/<id>.json.bz2` per sample (sample2markers ran).
- [ ] `strainphlan/.../print_clades_only.tsv` for the `3month` run.
- [ ] **No tree** expected (2 samples < the 4-sample minimum) — `strainphlan`
      step exits 1 and is skipped, not a failure.
- [ ] SAM alignments **not** published (intentional).
- [ ] MultiQC report under `log/`.

## E. Cost & cleanup

- [ ] Total spend < a few dollars (1 r8g.metal-24xl spot ≈ \$2–3/hr, run ~15–30 min
      for the 2-sample smoke; only 2 of 6 job slots used).
- [ ] Worker scaled back to 0 after completion (CE MinvCpus=0).
- [ ] `.nextflow.log` ends with `Execution complete -- Goodbye`.

## Later rollout (after the 2-sample smoke passes)

1. ~~**Bump MetaPhlAn to 32 vCPU**~~ — superseded by the shipped config: instead
   of one 32-vCPU job per r8g.8xlarge, we ship `cpus = 16` with 2× burst
   (`--nproc 32`) packed **6 jobs per r8g.metal-24xl** (96 vCPU), all sharing one
   staged vJan25 copy. `resourceLimits.cpus = 16`. The metal box gives more
   per-sample throughput at lower $/vCPU than r8g.8xlarge.
2. **Scale up the sample count** using the full
   `cosmosid-infant-max20.csv` (20 samples) — exercises real per-run StrainPhlAn
   reduces (`3month` = 16, `1year` = 4) and the queue's parallelism.
3. (Separately tracked) bowtie2 `--mm` memory-mapping — see
   `infra/multiqueue-design.md`.

## Measured — run 1 (2026-06-18, project cosmosid-strainphlan-smoke, r8g.4xlarge)

> **Historical.** Run 1 used the *original* config: `r8g.4xlarge`, `cpus = 8`,
> `--nproc 8` (1:1), 2 jobs/VM. The shipped config has since changed to
> `r8g.metal-24xl` + `cpus = 16` + `--nproc 32` + 6 jobs/VM (see checklist above).
> Timings below are still valid for the thin-AMI + S3-copy *mechanism*, but a
> **run-2 on metal is needed** to re-confirm packing, nproc-32 contention, and
> per-sample runtime on the shipped config.

Cold worker, no FSR, stock AL2023 ECS AMI:

| Event | UTC | Δ from launch |
|-------|-----|---------------|
| Worker LaunchTime | 13:39:36 | — |
| Jobs STARTING (placed) | 13:46:13 | 6m37s — EC2 boot + awscli install + ~44 GB vJan25 copy + ECS register |
| Jobs RUNNING (startedAt) | 13:47:19 | 7m43s — +1m06s ECR image pull (~4 GB metaphlan) |

- **2-jobs-per-VM confirmed**: both `profile_taxa` placed on the *same*
  container instance (CE Desired auto-set to 16 vCPU = 2×8), sharing one staged
  vJan25 copy.
- **Synchronous-copy gating worked**: jobs sat RUNNABLE until the copy finished,
  then registered — exactly the intended behavior.
- Copy not isolated (head-node-role lacks `ssm:SendCommand`, so
  `/var/log/nf-userdata.log` unreadable live); boot+install+copy ≤ 6m37s.
- **vs FSR**: ~7.7 min one-time-per-VM cold penalty at \$0 standing cost, vs
  FSR's near-instant boot billed at \$2.25/hr/snapshot/AZ while enabled.

**Follow-up:** add `ssm:SendCommand` + `ssm:StartSession` to
`NextflowRunnerPolicy` so future runs can watch the copy live and isolate its
duration.

### Outcome — PASS

- `profile_taxa` ×2 + `sample2markers` ×2 all SUCCEEDED on spot-metaphlan,
  co-located on one r8g.4xlarge sharing one staged vJan25 copy.
- Outputs present: 2× `_metaphlan.biom`, 2× `consensus_markers/*.json.bz2`,
  `combined_bioms/metaphlan/3month_metaphlan_combined.biom`.
- `print_clades` failed exit 1 (`inputs + references are less than 4`) — expected
  for a 2-sample run, not an infra issue; real run (16× `3month`) clears it.
- Worker scaled to zero (terminated 14:19:04, CE Desired→0). $0 standing cost.
- **Per-sample `profile_taxa` ≈ 16–24 min** at `--nproc 8` (both concurrent on
  the shared 16-vCPU VM) → the headline motivation for the 32-vCPU + bowtie2
  `--mm` speedups.
- Confirmed via live `.command.sh`: `--nproc 8` (1:1, no oversubscription).

## Where each timing comes from (quick map)

| Metric | Source |
|--------|--------|
| Instance load (no FSR) | EC2 launch time → ECS register; `cloud-init analyze blame` |
| S3 DB copy | `time` block in `/var/log/nf-userdata.log` |
| awscli install | `Installing awscli v2` block in `nf-userdata.log` |
| Docker/MetaPhlAn boot | Batch job STARTING→RUNNING gap; `/var/log/ecs/ecs-agent.log` |
| Per-job runtime | Nextflow `reports/trace*` (`realtime`, `duration`) |
| 2-jobs/VM packing | `describe-jobs` → matching `containerInstanceArn` |
