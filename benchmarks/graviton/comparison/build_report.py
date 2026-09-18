#!/usr/bin/env python3
"""Build the paired benchmark report from saved Nextflow HTML and AWS evidence."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TIERS = ['100k', '300k', '1m', '3m', '10m']
PROCESSES = ['profile_taxa', 'profile_function']
records = {}
for generation in ['g4', 'g5']:
    path = ROOT / 'evidence' / f'{generation}-report.html'
    if path.exists():
        text = path.read_text()
        match = re.search(r'\bdata\s*=\s*(\{\s*"trace"\s*:)', text)
        data, _ = json.JSONDecoder().raw_decode(text[match.start(1):].replace("\\'", "'"))
    elif generation == 'g5':
        tasks = json.loads((ROOT/'evidence/g5-task-metadata.json').read_text())
        for task in tasks:
            raw = (ROOT/'evidence'/f"{task['native_id']}-command.trace").read_text()
            task.update(status='COMPLETED', cpus=16,
                        memory=(36 if task['name'].startswith('profile_taxa') else 25)*2**30,
                        realtime=int(re.search(r'realtime=(\d+)', raw)[1]))
        data = {'trace': tasks}
    else:
        continue
    jobs_file = ROOT / 'evidence' / f'{generation}-jobs.json'
    jobs = {j['jobId']: j for j in json.loads(jobs_file.read_text())['jobs']} if jobs_file.exists() else {}
    for task in data['trace']:
        process = task['name'].split(' ')[0]
        if process not in PROCESSES or task['status'] != 'COMPLETED':
            continue
        tier = task['name'].rsplit('_', 1)[1].rstrip(')')
        key = (generation, process, tier)
        if key in records:
            raise ValueError(f'Duplicate successful task: {key}')
        job = jobs.get(task['native_id'], {})
        row = dict(generation=generation, process=process, tier=tier,
                   job_id=task['native_id'], runtime_s=float(task['realtime']) / 1000,
                   cpus=int(task['cpus']), memory_gib=float(task['memory']) / 2**30,
                   batch_active_s=(job['stoppedAt']-job['startedAt'])/1000 if job.get('stoppedAt') else '',
                   cpu_share_estimated_usd='')
        # Both G4 workers verified: ECS for HUMAnN; ASG history + Spot request for MetaPhlAn.
        if generation == 'g4':
            assert len(job['attempts']) == 1
            row['cpu_share_estimated_usd'] = row['batch_active_s']/3600 * (row['cpus']/96) * 0.4308
        if generation == 'g5':
            assert job['status'] == 'SUCCEEDED' and len(job['attempts']) == 1
            # Saved ECS mappings and Spot histories verify constant prices during these jobs.
            hourly, worker_cpus = (0.6594, 96) if process == 'profile_function' else (1.3922, 192)
            row['cpu_share_estimated_usd'] = row['batch_active_s']/3600 * row['cpus']/worker_cpus * hourly
        records[key] = row
with (ROOT/'task-results.csv').open('w') as out:
    writer = csv.DictWriter(out, fieldnames=list(next(iter(records.values()))))
    writer.writeheader()
    writer.writerows(records.values())

def duration(s):
    return f'{int(s//60)}m {s%60:04.1f}s'

def value(row, field, formatter):
    return formatter(row[field]) if row and row[field] != '' else 'Pending'

lines = ['# Graviton benchmark: runtime and cost per sample', '',
         'G4 and G5 profiling complete: all ten profiling tasks succeeded in each run. G5 downstream merging/conversion is still pending at this update. Five read caps from the same source sample, one run per generation. These observations are not replicated estimates of variability.', '',
         '## Profiling runtime', '',
         'Execution time uses exact Nextflow `realtime` milliseconds from the G4 HTML report and saved G5 `.command.trace` files, excluding queue waits. Positive time saved means G5 is faster; speedup is G4/G5.', '',
         '| Process | Reads | G4 runtime | G5 runtime | Time saved | G5 speedup |',
         '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for process in PROCESSES:
    for tier in TIERS:
        a, b = (records.get((g,process,tier)) for g in ['g4','g5'])
        delta = f"{a['runtime_s']-b['runtime_s']:+.1f}s" if a and b else 'Pending'
        ratio = f"{a['runtime_s']/b['runtime_s']:.3f}×" if a and b else 'Pending'
        lines.append(f"| {process} | {tier} | {value(a,'runtime_s',duration)} | {value(b,'runtime_s',duration)} | {delta} | {ratio} |")
lines += ['', '## Runtime-based cost estimate', '',
          'Use actual worker type, AZ, and the Spot price effective during each task. Integrate price changes over Batch `startedAt` → `stoppedAt`, then multiply by requested vCPUs / worker vCPUs. This interval includes container work beyond the timed command. Include every attempt for cost, including failures; speed uses successful execution.', '',
          'This CPU-share allocation is an estimate, not an AWS per-job bill or a fully packed-host forecast. It excludes unused capacity, host startup/shutdown, image pulls before RUNNING, EBS, S3 and other services. Memory can limit packing: MetaPhlAn requests 36 GiB for 16 CPUs, so CPU-only allocation can understate its capacity cost on compute-optimized hosts. Show actual fleet cost separately.', '',
          'Verified G4 HUMAnN worker: `i-035550f957f0d940c`, `m8g.metal-24xl`, 96 vCPUs / 384 GiB, `us-east-2c`, Spot **$0.4308/hour** throughout the task interval. All five tasks used this worker. G4 MetaPhlAn used separate instance `i-0d6f195921644a5d1`, also m8g.metal-24xl, 96 vCPUs / 384 GiB, us-east-2c, $0.4308/hour. Recovered through CE Auto Scaling launch/termination history and its Spot request; it was the only worker in that CE during all five jobs (16:17:52–16:23:01 UTC).', '',
          'Verified G5 workers: HUMAnN `i-00c747c665b5f5996`, c9g.24xlarge, 96 vCPU / 192 GiB, us-east-2c, $0.6594/h; MetaPhlAn `i-06683e5607459a50f`, c9g.48xlarge, 192 vCPU / 384 GiB, us-east-2a, $1.3922/h. Prices were constant during profiling. All five tasks per profiler used its listed worker; no G5 profiling retries.', '',
          '| Reads | G4 HUMAnN | G5 HUMAnN | HUMAnN cost change | G4 MetaPhlAn | G5 MetaPhlAn | MetaPhlAn cost change | G4 both | G5 both |',
          '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for tier in TIERS:
    row=records.get(('g4','profile_function',tier))
    a=row['cpu_share_estimated_usd']
    b=records[('g5','profile_function',tier)]['cpu_share_estimated_usd']
    c=records[('g5','profile_taxa',tier)]['cpu_share_estimated_usd']
    d=records[('g4','profile_taxa',tier)]['cpu_share_estimated_usd']
    lines.append(f"| {tier} | ${a:.5f} | ${b:.5f} | {100*(b/a-1):+.1f}% | ${d:.5f} | ${c:.5f} | {100*(c/d-1):+.1f}% | ${a+d:.5f} | ${b+c:.5f} |")
lines += ['', 'Cost change = G5 − G4 dollars; percent change = 100 × (G5/G4 − 1). Cost savings = G4 − G5. Both-profiler cost is the sum of their estimates. Do not sum parallel profiler runtimes and call it elapsed sample turnaround.', '',
          '## End-to-end timing and billed cost', '',
          '- G4 successful launch: 2026-09-18 16:06:49 UTC; finish: 17:00:37 UTC; full pipeline elapsed: **53m48s**. Last profiling task completed around 16:47 UTC; merging/reporting continued afterward.',
          '- G5 launch: 17:02:23 UTC; completion and elapsed time pending.',
          '- Add per-sample profiling-ready turnaround (both profilers complete) and queue delay alongside execution speed. Pipeline elapsed includes counting, cleaning, waiting, profiling, merging, and reporting.',
          '- Billing-dashboard reconciliation: pending. CloudWatch operational metrics typically arrive within a few minutes; Cost Explorer/billing usage generally refreshes at least daily and can lag beyond 24 hours. Inspect the reported refresh/coverage window; first visible cost is not necessarily complete.',
          '- Reconcile EC2/EBS cost for actual worker IDs and their full lifetime, with shared-host usage allocated explicitly. Separate the earlier failed G4 attempt. Avoid attributing unrelated account/queue spend to this benchmark. Per-sample billing allocation is a model even after the fleet bill is known.',
          '- G4 cleaning requested 16 GiB initially / 32 GiB retries; G5 uses 8/16 GiB. Accuracy is level 3 in both. This changes whole-pipeline cost comparability; profiling CPU and memory requests are unchanged.', '',
          '## Remaining reconciliation', '',
          'G4 MetaPhlAn placement and allocated cost are now recovered; all profiling cost estimates are populated. G5 profiling finished at 17:36:10 UTC (last Batch stop), 33m47s after launch; this is not full-pipeline completion. Full elapsed time and billing reconciliation remain pending. Regenerate after the final G5 HTML report becomes available.', '',
          'Evidence and exact numerical results are stored alongside this report in `evidence/` and `task-results.csv`.']
lines += ['', 'Normalized per-VM results for all five input caps and pricing scenarios for every current profiler-pool VM: [per-million.md](per-million.md).']
(ROOT/'report.md').write_text('\n'.join(lines)+'\n')
