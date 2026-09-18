"""Extract unique historical fastp task attempts from Nextflow HTML reports."""
import csv, json, re, statistics
from pathlib import Path
root = Path('/home/ubuntu/gutz-nf-reads-profilers-runs/results')
rows = {}
files = sorted(root.glob('*/reports/*report.html'))
for f in files:
    text = f.read_text()
    match = re.search(r'\bdata\s*=\s*(\{\s*"trace"\s*:)', text)
    if not match:
        continue
    payload = text[match.start(1):].replace("\\'", "'")
    data, _ = json.JSONDecoder().raw_decode(payload)
    for r in (data['trace'] or []):
        if not r.get('name', '').startswith('clean_reads '):
            continue
        key = r.get('native_id')
        if not key or key == '-':
            key = r.get('workdir', '') + ':' + r.get('submit', '')
        if key in rows and rows[key]['status'] != 'CACHED':
            continue
        script = r.get('script', '')
        accuracy = re.search(r'--dup_calc_accuracy\s+(\d+)', script)
        accuracy = accuracy[1] if accuracy else ('3 (default)' if '--dedup' in script else 'unknown')
        def gib(field):
            try: return float(r[field]) / 2**30
            except (ValueError, KeyError): return None
        rows[key] = dict(native_id=key, name=r['name'], cohort=f.parts[-3],
                         status=r['status'], exit=r.get('exit'), accuracy=accuracy,
                         peak_gib=gib('peak_rss'), requested_gib=gib('memory'),
                         cpus=r.get('cpus'), container=r.get('container'),
                         source=str(f), workdir=r.get('workdir'))
output=Path(__file__).parent
with (output/'fastp-task-memory.csv').open('w') as h:
    writer=csv.DictWriter(h,fieldnames=list(next(iter(rows.values()))));writer.writeheader();writer.writerows(rows.values())
summaries=[]
for cohort,accuracy in sorted({(r['cohort'],r['accuracy']) for r in rows.values()}):
    group=[r for r in rows.values() if r['cohort']==cohort and r['accuracy']==accuracy]
    good=[r for r in group if r['status'] in ('COMPLETED','CACHED') and r['peak_gib'] is not None]
    values=sorted(r['peak_gib'] for r in good)
    if not values:continue
    item=dict(cohort=cohort,accuracy=accuracy,tasks=len(good),samples=len({r['name'] for r in good}),
              min=values[0],median=statistics.median(values),p95=values[int(.95*(len(values)-1))],max=values[-1],
              requested_gib=sorted({r['requested_gib'] for r in good if r['requested_gib'] is not None}))
    summaries.append(item)
(output/'summary.json').write_text(json.dumps(dict(reports_scanned=len(files),unique_attempts=len(rows),groups=summaries),indent=2)+'\n')
print(json.dumps(summaries,indent=2))
