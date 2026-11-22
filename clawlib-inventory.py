#!/usr/bin/env python3
"""Inventory local Git repositories as a JSON manifest (read-only).

Origin: February 2026 ClawLib repository inventory/update discussion.
Reconstructed: November 2026; original updater was Bash.
Usage: python clawlib-inventory.py ~/clawlib -o sources.json --include-dirty
Dependencies: standard library and git executable. Exit: 0 success, 2 invalid input.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

def git(repo, *args):
    result = subprocess.run(['git','-C',str(repo),*args], capture_output=True,
                            text=True, timeout=10, check=False)
    return result.stdout.strip() if result.returncode == 0 else ''

def inventory(root, include_dirty):
    entries = []
    for marker in sorted(root.rglob('.git')):
        if not (marker.is_dir() or marker.is_file()):
            continue
        repo = marker.parent
        commit = git(repo, 'rev-parse', 'HEAD')
        if not commit:
            continue
        item = {'path': str(repo.relative_to(root)),
                'branch': git(repo, 'branch', '--show-current') or '(detached)',
                'remote': git(repo, 'remote', 'get-url', 'origin'), 'commit': commit}
        if include_dirty:
            item['dirty'] = bool(git(repo, 'status', '--porcelain'))
        entries.append(item)
    return entries

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('-o','--output',type=Path,default=Path('sources.json'))
    p.add_argument('--include-dirty',action='store_true')
    a = p.parse_args()
    if not a.root.is_dir():
        p.error('root must be an existing directory')
    try:
        data = {'root':str(a.root.resolve()), 'repositories':inventory(a.root.resolve(),a.include_dirty)}
        a.output.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        print(f'Indexed {len(data["repositories"])} repositories in {a.output}')
        return 0
    except (OSError,subprocess.TimeoutExpired) as e:
        print(f'Error: {e}',file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
