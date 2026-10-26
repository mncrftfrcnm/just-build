#!/usr/bin/env python3
"""Dependency-free repository checks; does not run the agent workflow."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ('codex', 'claude-code')
ROOT_FILES = ('.gitignore', '.gitattributes', '.editorconfig', 'VERSION', 'LICENSE',
              'README.md', 'INSTALL.md', 'CONTRIBUTING.md', 'SECURITY.md', 'SUPPORT.md',
              'CODE_OF_CONDUCT.md', 'CHANGELOG.md', 'requirements-dev.txt')
SOURCE_DIRS = ('codex', 'claude-code', '.github', 'docs', 'tools', 'examples')
HOST_SPECIFIC = {'SKILL.md', 'references/host.md', 'agents/openai.yaml'}


def linked(path):
    return (path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
            or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400))


def source_files(root=ROOT):
    """Explicit distribution roots omit local reports, credentials and build output."""
    root = Path(root).resolve()
    result = []

    def visit(path):
        if linked(path):
            raise ValueError(f'Linked distribution path: {path.relative_to(root)}')
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.name != '__pycache__':
                    visit(child)
        elif path.is_file():
            if path.suffix != '.pyc':
                result.append(path)
        else:
            raise ValueError(f'Non-regular distribution path: {path.relative_to(root)}')

    for name in (*ROOT_FILES, *SOURCE_DIRS):
        visit(root / name)
    return sorted(result, key=lambda path: path.relative_to(root).as_posix())


def check(root=ROOT):
    root = Path(root).resolve()
    files = source_files(root)
    packages = [root / host / 'just-build' for host in HOSTS]
    tables = [{p.relative_to(package).as_posix(): p.read_bytes() for p in files if p.is_relative_to(package)}
              for package in packages]
    shared = (set(tables[0]) | set(tables[1])) - HOST_SPECIFIC
    for name in sorted(shared):
        if name not in tables[0] or name not in tables[1] or tables[0][name] != tables[1][name]:
            raise ValueError(f'Host package drift: {name}')
    license_bytes = (root / 'LICENSE').read_bytes()
    if any(table.get('LICENSE') != license_bytes for table in tables):
        raise ValueError('Root and host licenses differ')
    for host, table in zip(HOSTS, tables):
        entry = table.get('SKILL.md', b'').decode('utf-8')
        if not re.match(r'\A---\r?\nname: just-build\r?\ndescription: .+\r?\n', entry):
            raise ValueError(f'Invalid skill entry point: {host}')
    if 'allow_implicit_invocation: false' not in tables[0].get('agents/openai.yaml', b'').decode():
        raise ValueError('Codex invocation policy changed')
    if 'disable-model-invocation: true' not in tables[1]['SKILL.md'].decode():
        raise ValueError('Claude invocation policy changed')

    python_count = json_count = yaml_count = 0
    for file in files:
        rel = file.relative_to(root).as_posix()
        name = file.name.casefold()
        if name == '.env' or (name.startswith('.env.') and name != '.env.example') or file.suffix.casefold() in ('.pem', '.key'):
            raise ValueError(f'Private configuration in distribution: {rel}')
        text = file.read_text(encoding='utf-8')
        if re.search(r'(?:[A-Za-z]:[\\/]+Users[\\/]+|/Users/|/home/)[A-Za-z0-9_.-]+', text):
            raise ValueError(f'Personal absolute path in distribution: {rel}')
        if re.search(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----', text):
            raise ValueError(f'Private key material in distribution: {rel}')
        if file.suffix == '.py':
            ast.parse(text, filename=rel, feature_version=(3, 11))
            python_count += 1
        elif file.suffix == '.json':
            json.loads(text)
            json_count += 1
        elif file.suffix in ('.yml', '.yaml'):
            from check_workflows import load_workflow
            load_workflow(file)  # Safe YAML syntax/duplicate checks, not GitHub's complete schema.
            yaml_count += 1
        elif file.suffix == '.md':
            for link in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                parsed = urlsplit(link.strip('<>'))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = (file.parent / unquote(parsed.path)).resolve()
                if not target.is_relative_to(root) or not target.exists():
                    raise ValueError(f'Broken local Markdown link in {rel}: {link}')
            skill = next((package for package in packages if file.is_relative_to(package)), None)
            if skill:
                for ref in re.findall(r'(?:references|examples|scripts|benchmarks)/[\w./-]+\.(?:md|json|py|yaml)', text):
                    if not (skill / ref).is_file():
                        raise ValueError(f'Broken skill reference in {rel}: {ref}')

    from check_workflows import check as check_workflow_policy
    workflows = check_workflow_policy(root)
    from check_community import check as check_community_policy
    community = check_community_policy(root)
    return {'passed': True, 'source_files': len(files),
            'python_files_parsed': python_count, 'json_files_parsed': json_count, 'yaml_files_parsed': yaml_count,
            'shared_host_files': len(shared), 'workflow_policy': workflows, 'community_policy': community,
            'scope': 'Structural and repository workflow policy checks, not a comprehensive security scan or live-host evaluation'}


if __name__ == '__main__':
    try:
        print(json.dumps(check(), indent=2))
    except (OSError, ValueError, SyntaxError) as exc:
        raise SystemExit(f'Repository check failed: {exc}')
