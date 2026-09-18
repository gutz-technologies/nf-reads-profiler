#!/usr/bin/env python3
"""One-shot VM watcher. Exit on failure; never automatically relaunch G5."""
import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/ubuntu/github/nf-reads-profiler')
os.chdir(ROOT)
STATE = ROOT / 'benchmarks/graviton/execution/watcher'
STATE.mkdir(parents=True, exist_ok=True)
lock = (STATE / 'lock').open('w')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Watcher already running')

def status(message):
    line = datetime.datetime.now(datetime.timezone.utc).isoformat() + ' ' + message
    print(line, flush=True)
    (STATE / 'status.txt').write_text(line + '\n')

def aws(*args):
    result = subprocess.run(['aws', *args, '--region', 'us-east-2', '--output', 'json'],
                            check=True, capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout)

pools = ['spot-short-g5', 'spot-metaphlan-g5', 'spot-humann-g5']
g4 = ROOT / 'benchmarks/graviton/execution/g4'
g5 = ROOT / 'benchmarks/graviton/execution/g5'
try:
    if (STATE / 'launch-claimed.txt').exists() or (g5 / 'started.txt').exists():
        raise RuntimeError('G5 already started or launch claimed; manual inspection required')
    status('WAITING: G4 successful exit; polling every 60 seconds')
    deadline = time.monotonic() + 24 * 3600
    while not (g4 / 'finished.txt').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('G4 did not finish within 24 hours')
        time.sleep(60)
    if (g4 / 'exit-code.txt').read_text().strip() != '0':
        raise RuntimeError('G4 failed; G5 will not launch')
    # Claim before any AWS changes; restarts require explicit inspection.
    with (STATE / 'launch-claimed.txt').open('x') as claim:
        claim.write(datetime.datetime.now(datetime.timezone.utc).isoformat() + '\n')
    if (g5 / 'started.txt').exists():
        raise RuntimeError('G5 was started independently')
    status('PREPARING: G4 succeeded; enabling three G5 compute environments')
    for pool in pools:
        aws('batch', 'update-compute-environment', '--compute-environment', pool, '--state', 'ENABLED')
    for kind, key, arg in [('compute-environments','computeEnvironments','--compute-environments'),
                           ('job-queues','jobQueues','--job-queues')]:
        if kind == 'job-queues':
            for pool in pools:
                aws('batch','update-job-queue','--job-queue',pool,'--state','ENABLED')
        until = time.monotonic() + 900
        while True:
            items = aws('batch', 'describe-' + kind, arg, *pools)[key]
            if any(x['status'] == 'INVALID' for x in items):
                raise RuntimeError('Invalid AWS resource: ' + json.dumps(items))
            if len(items) == 3 and all(x['status'] == 'VALID' and x['state'] == 'ENABLED' for x in items):
                break
            if time.monotonic() > until:
                raise RuntimeError('Timed out waiting for enabled/valid ' + kind)
            time.sleep(30)
    resolved = subprocess.run(['nextflow','-c','benchmarks/graviton/g5.config','config','-flat'],
                              check=True, capture_output=True, text=True, timeout=120)
    (STATE / 'g5-launched.config').write_text(resolved.stdout)
    status('STARTING: G5 benchmark; see execution/g5/console.log')
    with (STATE / 'g5-launcher.log').open('a') as output:
        result = subprocess.run(['bash','benchmarks/graviton/run-g5.sh'], stdout=output, stderr=subprocess.STDOUT)
    status('G5 FINISHED: launcher exit ' + str(result.returncode))
    raise SystemExit(result.returncode)
except Exception as exc:
    status('BLOCKED: ' + str(exc))
    raise
