"""Keep dependency downloads apart from private candidate validation."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))
from workflow_common_quality import candidate_inputs, subject
from workflow_control import ControlError, canonical, require

TOKEN = re.compile(r'\s+|\#[^\n]*|//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"|[a-z_]+|[{}\[\]=,]', re.S)
ADDRESS = re.compile(r'registry\.terraform\.io/[a-z0-9][a-z0-9-]{0,63}/[a-z0-9][a-z0-9-]{0,63}')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?')
HASH = re.compile(r'(?:zh:[0-9a-f]{64}|h1:[A-Za-z0-9+/]{43}=)')


def lock_data(path):
    """Accept the bounded literal dependency-lock grammar; discard all comments."""
    if not path.exists():
        return {}
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 131072,
            'terraform-lock-bound')
    raw = path.read_text()
    tokens, offset = [], 0
    for match in TOKEN.finditer(raw):
        require(match.start() == offset, 'terraform-lock-token')
        offset = match.end()
        value = match.group()
        if value.isspace() or value.startswith(('#', '//', '/*')):
            continue
        tokens.append(value)
    require(offset == len(raw) and len(tokens) <= 16384, 'terraform-lock-token-bound')
    position = 0
    def take(expected=None):
        nonlocal position
        require(position < len(tokens), 'terraform-lock-incomplete')
        value = tokens[position]; position += 1
        require(expected is None or value == expected, 'terraform-lock-grammar')
        return value
    def string():
        value = take()
        require(value.startswith('"'), 'terraform-lock-literal-required')
        result = json.loads(value)
        require(type(result) is str and len(result) <= 256, 'terraform-lock-string')
        return result
    providers = {}
    while position < len(tokens):
        take('provider'); address = string(); take('{')
        require(ADDRESS.fullmatch(address) and address not in providers and len(providers) < 32,
                'terraform-provider-address')
        fields = {}
        while tokens[position:position + 1] != ['}']:
            key = take()
            require(key in {'version', 'constraints', 'hashes'} and key not in fields,
                    'terraform-lock-field')
            take('=')
            if key == 'hashes':
                take('['); values = []
                while tokens[position:position + 1] != [']']:
                    values.append(string())
                    require(len(values) <= 64, 'terraform-lock-hash-count')
                    if tokens[position:position + 1] != [']']:
                        take(',')
                take(']'); fields[key] = values
            else:
                fields[key] = string()
        take('}')
        require(set(fields) >= {'version', 'hashes'} and VERSION.fullmatch(fields['version'])
                and fields['hashes'] and all(HASH.fullmatch(value) for value in fields['hashes']),
                'terraform-lock-version-or-hash')
        if 'constraints' in fields:
            require(re.fullmatch(r'[0-9A-Za-z.*<>=!~, +\-]+', fields['constraints']),
                    'terraform-lock-constraints')
        providers[address] = fields
    return providers


def engine(root):
    spec = importlib.util.spec_from_file_location('protected_terraform_quality', SOURCE / 'lit-repository-quality.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.ROOT = root
    return module


def prepare(record, base, output):
    configuration = subject(record)
    base = base.resolve()
    require(not os.environ.get('GH_TOKEN') and not os.environ.get('GITHUB_TOKEN'), 'terraform-no-credentials')
    actual = subprocess.check_output(['git', '-c', f'safe.directory={base}', '-C', str(base),
                                      'rev-parse', 'HEAD'], text=True).strip()
    require(actual == record['base'], 'terraform-protected-base-drift')
    previous = Path.cwd()
    try:
        os.chdir(base); candidate_inputs()
    finally:
        os.chdir(previous)
    module = engine(previous)
    roots = module.terraform_roots(configuration['repository_type'])
    require(0 < len(roots) <= 64, 'terraform-root-count')
    tasks = []
    output.mkdir(parents=True, exist_ok=False)
    for index, root in enumerate(roots):
        relative = root.relative_to(previous)
        approved = lock_data(base / relative / '.terraform.lock.hcl')
        proposed = lock_data(root / '.terraform.lock.hcl')
        require(set(proposed) <= set(approved), 'terraform-provider-not-approved-in-base')
        if not proposed:
            continue
        task = f'provider-{index:04d}'; tasks.append(task)
        directory = output / task; directory.mkdir()
        required = {f'p{i}': {'source': address, 'version': '= ' + fields['version']}
                    for i, (address, fields) in enumerate(sorted(proposed.items()))}
        (directory / 'main.tf.json').write_bytes(canonical({'terraform': {'required_providers': required}}))
        lines = []
        for address, fields in sorted(proposed.items()):
            lines += ['provider ' + json.dumps(address) + ' {', '  version = ' + json.dumps(fields['version']),
                      '  hashes = [' + ', '.join(json.dumps(value) for value in fields['hashes']) + ']', '}']
        (directory / '.terraform.lock.hcl').write_text('\n'.join(lines) + '\n')
    (output / 'requests.json').write_bytes(canonical({'version': 1, 'tasks': tasks}))
    (output / 'terraformrc').write_text('provider_installation {\n filesystem_mirror {\n  path = "/providers"\n }\n}\n')


def fetch(inputs, mirror):
    require(not os.environ.get('GH_TOKEN') and not os.environ.get('GITHUB_TOKEN'), 'terraform-no-credentials')
    value = json.loads((inputs / 'requests.json').read_bytes())
    require(type(value) is dict and set(value) == {'version', 'tasks'} and value['version'] == 1
            and type(value['tasks']) is list and len(value['tasks']) <= 64
            and len(set(value['tasks'])) == len(value['tasks'])
            and all(type(task) is str and re.fullmatch('provider-[0-9]{4}', task) for task in value['tasks']),
            'terraform-dependency-request-shape')
    for task in value['tasks']:
        subprocess.run(['terraform', f'-chdir={inputs / task}', 'providers', 'mirror', str(mirror)],
                       check=True, timeout=600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'fetch'))
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--mirror', type=Path)
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare(json.loads(args.policy.read_bytes()), args.base, args.directory)
    else:
        fetch(args.directory, args.mirror)


if __name__ == '__main__':
    try:
        main()
    except (ControlError, KeyError, ValueError, TypeError, OSError, AssertionError, subprocess.SubprocessError):
        raise SystemExit('Protected Terraform dependency supply blocked; no validation or approval granted.') from None
