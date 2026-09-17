"""Offline Nextflow integration tests; no real credentials or network downloads.

Run: python -m unittest discover -s tests -p test_sra_ngc.py -v
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import gzip
from pathlib import Path
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
if '--version' in args:
    print('aws-cli/2.0.0' if tool == 'aws' else '3.2.1')
    sys.exit(0)
if tool in ('prefetch', 'fasterq-dump') and '--ngc' in args:
    assert Path(args[args.index('--ngc') + 1]).read_text() == 'fake-test-key'
if tool == 'prefetch':
    assert '--ngc' in args
    run = args[-1]
    Path(run).mkdir()
    name = run + ('_dbgap_123.sra' if run == 'SRR1' else '.sra')
    (Path(run) / name).write_text('protected')
    (Path(run) / 'companion').write_text('keep me')
elif tool == 'aws':
    assert '--no-sign-request' in args
    Path(args[-2]).write_text('public')
elif tool == 'fasterq-dump':
    archive = Path(args[-1])
    if archive.read_text() == 'protected':
        assert '--ngc' in args
        assert archive.name == archive.parent.name + '.sra'
        assert (archive.parent / 'companion').exists()
    else:
        assert '--ngc' not in args
    for mate in (1, 2):
        Path(f'{archive.stem}_{mate}.fastq').write_text('@read\nACGT\n+\nIIII\n')
elif tool == 'pigz':
    for name in args:
        path = Path(name)
        with gzip.open(str(path) + '.gz', 'wb') as out:
            out.write(path.read_bytes())
        path.unlink()
else:
    raise AssertionError(tool)
'''


@unittest.skipUnless(shutil.which('nextflow'), 'Nextflow required')
class SraNgcTests(unittest.TestCase):
    def run_workflow(self, authenticated):
        with tempfile.TemporaryDirectory(prefix='sra-ngc-test-') as tmp:
            root = Path(tmp)
            binaries = root / 'bin'
            binaries.mkdir()
            for name in ('aws', 'prefetch', 'fasterq-dump', 'pigz'):
                executable = binaries / name
                executable.write_text(MOCK)
                executable.chmod(0o755)
            # A filename containing spaces exercises key staging, not shell interpolation.
            key = root / 'test repository key.ngc'
            key.write_text('fake-test-key')
            config = root / 'nextflow.config'
            config.write_text('''
params.docker_container_sra = 'unused'
params.docker_container_aws = 'unused'
params.aws_region = 'us-east-1'
process.executor = 'local'
process.shell = ['/bin/bash', '-euo', 'pipefail']
docker.enabled = false
conda.enabled = false
''')
            script = root / 'main.nf'
            setup = (
                f"key = channel.value(file('{key}', checkIfExists: true))\n"
                'SRA_PREFETCH(ids, key)\narchives = SRA_PREFETCH.out.sra_file'
                if authenticated else
                'key = channel.value([])\nAWS_DOWNLOAD(ids)\narchives = AWS_DOWNLOAD.out.sra_file'
            )
            script.write_text(f'''
include {{ AWS_DOWNLOAD; SRA_PREFETCH; FASTERQ_DUMP }} from '{ROOT}/modules/data_handling'
workflow {{
    ids = channel.of([[id: 'one'], 'SRR1'], [[id: 'two'], 'SRR2'])
    {setup}
    FASTERQ_DUMP(archives, key)
    FASTERQ_DUMP.out.reads.map {{ meta, reads ->
        assert reads.size() == 2
        assert reads.every {{ it.size() > 0 }}
        "VERIFIED_PAIR:${{meta.id}}"
    }}.view()
}}
''')
            env = dict(os.environ, PATH=f'{binaries}:{os.environ["PATH"]}',
                       NXF_OFFLINE='true', NXF_DISABLE_CHECK_LATEST='true')
            result = subprocess.run(
                ['nextflow', '-C', str(config), 'run', str(script), '-ansi-log', 'false'],
                cwd=root, env=env, capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertIn('VERIFIED_PAIR:one', output)
            self.assertIn('VERIFIED_PAIR:two', output)

    def test_ngc_staging_and_protected_and_standard_archive_names(self):
        self.run_workflow(authenticated=True)

    def test_public_download_without_key(self):
        self.run_workflow(authenticated=False)


if __name__ == '__main__':
    unittest.main()
