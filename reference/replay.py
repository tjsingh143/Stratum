#!/usr/bin/env python3
"""Replay pinned R references in isolation; preserve committed reference evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'reference'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--offline', action='store_true', help='verify cached source downloads only')
    args = ap.parse_args()
    subprocess.run(['python3', str(REF / 'fetch.py')] + (['--offline'] if args.offline else []), check=True)
    with tempfile.TemporaryDirectory(prefix='stratum-r-replay-') as tmp:
        stage = Path(tmp)
        for name in ('fetch.py', 'manifest.json'):
            shutil.copy2(REF / name, stage / name)
        shutil.copytree(REF / 'r', stage / 'r')
        # Copy only pinned inputs; never seed the computation with derived CSVs.
        manifest = json.loads((REF / 'manifest.json').read_text())
        for item in manifest['sources']:
            target = stage / '_fetched' / item['id']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REF / '_fetched' / item['id'], target)
        subprocess.run(['bash', str(stage / 'r/run_reference.sh')], check=True)
        expected = {p.name for p in (REF / 'r_outputs').iterdir() if p.is_file()}
        actual = {p.name for p in (stage / 'r_outputs').iterdir() if p.is_file()}
        if expected != actual:
            raise RuntimeError('R output file set differs: ' + repr(expected ^ actual))
        for name in sorted(expected):
            if (REF / 'r_outputs' / name).read_bytes() != (stage / 'r_outputs' / name).read_bytes():
                raise RuntimeError('R replay differs from frozen reference: ' + name)
        for path, sha in manifest['derived'].items():
            source = stage / '_fetched' / path
            if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
                raise RuntimeError('derived CSV checksum differs: ' + path)
        dest = REF / '_fetched/derived'
        dest.mkdir(parents=True, exist_ok=True)
        for p in (stage / '_fetched/derived').iterdir():
            shutil.copy2(p, dest / p.name)
    print('Pinned R replay matches every stored output; reference CSVs rebuilt from pinned sources.')


if __name__ == '__main__':
    main()
