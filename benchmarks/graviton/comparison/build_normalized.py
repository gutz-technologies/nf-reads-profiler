#!/usr/bin/env python3
"""Normalize measured tasks; show explicitly hypothetical pool pricing scenarios."""
import csv
import json
from statistics import mean
from pathlib import Path
P = Path(__file__).resolve().parent
rows = list(csv.DictReader((P/'task-results.csv').open()))
tiers = {'100k': .1, '300k': .3, '1m': 1, '3m': 3, '10m': 10}
workers = {('g4','profile_taxa'): ('m8g.metal-24xl','i-0d6f195921644a5d1','us-east-2c'),
           ('g4','profile_function'): ('m8g.metal-24xl','i-035550f957f0d940c','us-east-2c'),
           ('g5','profile_function'): ('c9g.24xlarge','i-00c747c665b5f5996','us-east-2c'),
           ('g5','profile_taxa'): ('c9g.48xlarge','i-06683e5607459a50f','us-east-2a')}
out=[]
for r in rows:
    vm,i,az=workers.get((r['generation'],r['process']),('Unresolved','Unresolved','Unresolved'))
    n=tiers[r['tier']]
    out.append(dict(generation=r['generation'],process=r['process'],instance_type=vm,instance_id=i,az=az,read_cap=r['tier'],minutes_per_million=float(r['runtime_s'])/60/n,estimated_usd_per_million=float(r['cpu_share_estimated_usd'])/n if r['cpu_share_estimated_usd'] else ''))
with (P/'normalized-results.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
averages=[]
for g,proc in sorted({(r['generation'],r['process']) for r in out}):
    group=[r for r in out if r['generation']==g and r['process']==proc]
    assert len(group)==5 and {r['read_cap'] for r in group}==set(tiers)
    averages.append(dict(generation=g,process=proc,instance_type=group[0]['instance_type'],samples=5,
        minutes_per_million=mean(r['minutes_per_million'] for r in group),
        estimated_usd_per_million=mean(r['estimated_usd_per_million'] for r in group) if all(r['estimated_usd_per_million'] != '' for r in group) else ''))
with (P/'normalized-averages.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=list(averages[0])); w.writeheader(); w.writerows(averages)
lines=['# Minutes and dollars per million reads by VM','',
'Placement and Spot rates affect cost, but these two runs cannot isolate VM family, CPU generation, cache, and placement effects on speed. This is a comparison of the observed configurations, not proof that placement alone caused the difference.','',
'Normalization uses the configured input read cap (paired-input records/read pairs), not the number surviving cleaning. Minutes are elapsed profiler command minutes, not CPU-minutes. Dollars are the existing runtime-based CPU-share estimates, not the full instance bill. Every profiler requested 16 vCPUs. Small inputs have substantial fixed overhead; retain all five sizes instead of extrapolating a single linear rate.','',
'## Measured workers','', '| Generation / profiler | VM type | EC2 ID | AZ |','|---|---|---|---|']
for (g,p),(vm,i,az) in workers.items(): lines.append(f'| {g} / {p} | {vm} | {i} | {az} |')
lines += ['',
'## Sweep averages', '', 'Each of the five input sizes (100k, 300k, 1m, 3m, 10m) has equal weight: mean(task minutes / input millions), and mean(task allocated dollars / input millions). These are arithmetic means of the five normalized measurements, not total runtime divided by total reads.', '', '| Profiler | Generation / VM | Samples | Mean min / million | Mean estimated $ / million |', '|---|---|---:|---:|---:|']
for r in sorted(averages,key=lambda r:(r['process'],r['generation'])):
    cost=f"${r['estimated_usd_per_million']:.5f}" if r['estimated_usd_per_million'] != '' else 'Unavailable'
    lines.append(f"| {r['process']} | {r['generation']} / {r['instance_type']} | 5 | {r['minutes_per_million']:.3f} | {cost} |")
lines += ['', '## Measured normalization at every input size','', '| Profiler | Generation / VM | Input cap | min / million | estimated $ / million |','|---|---|---:|---:|---:|']
for r in sorted(out,key=lambda r:(r['process'],tiers[r['read_cap']],r['generation'])):
    cost=f"${r['estimated_usd_per_million']:.5f}" if r['estimated_usd_per_million'] != '' else 'Unavailable'
    lines.append(f"| {r['process']} | {r['generation']} / {r['instance_type']} | {r['read_cap']} | {r['minutes_per_million']:.3f} | {cost} |")
lines += ['', '## All current profiler-pool VM types: pricing scenario', '',
'These are projections, not measurements of every VM. For each generation and profiler, assume its measured sweep-average normalized runtime and Batch active duration apply unchanged to every VM in that generation. Apply the cheapest AZ quote from the saved 2026-09-18 pricing snapshots (latest quote per type/AZ). Placement and capacity are not guaranteed. This isolates the price effect under an explicit equal-speed-within-generation assumption. It does not measure family-specific performance. Generic/short-queue VMs do not run these profilers and are outside this table.', '',
'Projected dollars/million = mean(Batch active seconds / input millions) / 3600 × (16 / host vCPUs) × host Spot $/hour. All five sizes have equal weight. No idle-capacity or memory-packing adjustment; 36 GiB MetaPhlAn tasks can be memory-limited on c-series hosts.', '',
'| CE / profiler | VM | vCPUs | GiB | Cheapest AZ | Snapshot $/h | Assumed min/million | Projected $/million |','|---|---|---:|---:|---|---:|---:|---:|']
base=P.parents[2]/'infra/graviton5-capacity-2026-09-18'
types={}; prices={}
for group in ['humann','metaphlan']:
    folder=base/(group+'-costs')
    for t in json.loads((folder/'instance-types.json').read_text())['InstanceTypes']: types[t['InstanceType']]=t
    for q in json.loads((folder/'spot-prices.json').read_text())['SpotPriceHistory']:
        key=(q['InstanceType'],q['AvailabilityZone'])
        if key not in prices or q['Timestamp']>prices[key]['Timestamp']: prices[key]=q
for ce in json.loads((P/'evidence/current-profiler-pools.json').read_text())['computeEnvironments']:
    name=ce['computeEnvironmentName']; g='g5' if name.endswith('-g5') else 'g4'
    proc='profile_function' if 'humann' in name.lower() else 'profile_taxa'
    group=[r for r in rows if r['generation']==g and r['process']==proc]
    avg_minutes=mean(float(r['runtime_s'])/60/tiers[r['tier']] for r in group)
    avg_active=mean(float(r['batch_active_s'])/tiers[r['tier']] for r in group)
    for vm in sorted(ce['computeResources']['instanceTypes']):
        t=types[vm]; cpu=t['VCpuInfo']['DefaultVCpus']; mem=t['MemoryInfo']['SizeInMiB']/1024
        q=min((v for (typ,az),v in prices.items() if typ==vm),key=lambda v:float(v['SpotPrice']))
        rate=float(q['SpotPrice']); cost=avg_active/3600*16/cpu*rate
        lines.append(f"| {g} / {proc} | {vm} | {cpu} | {mem:g} | {q['AvailabilityZone']} | ${rate:.4f} | {avg_minutes:.3f} | ${cost:.5f} |")
lines += ['', 'Sources: `task-results.csv`, saved job→ECS mappings and Spot history in `evidence/`, current pool membership in `evidence/current-profiler-pools.json`, and historical pricing/type snapshots in `infra/graviton5-capacity-2026-09-18/{humann,metaphlan}-costs/`. All pool rows use snapshot pricing consistently; the measured table uses actual placement pricing.']
(P/'per-million.md').write_text('\n'.join(lines)+'\n')
