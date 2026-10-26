#!/usr/bin/env python3
"""Validate the repository's reviewed GitHub community-file subset locally.

This is deliberately narrower than GitHub's full schema and does not create
labels, validate account settings, or establish server-side acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from check_workflows import load_workflow

ROOT = Path(__file__).resolve().parents[1]
FORMS = {'bug_report.yml', 'feature_request.yml', 'evaluation_report.yml'}


def keys(value, allowed, where):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'Unsupported {where} structure or keys')


def text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{where} must be nonempty text')


def strings(value, where):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f'{where} must contain nonempty strings')
    if len(value) != len(set(value)):
        raise ValueError(f'{where} contains duplicates')


def validate_form(doc):
    keys(doc, {'name', 'description', 'body'}, 'issue form')
    for field in ('name', 'description'):
        text(doc.get(field), 'Issue form ' + field)
    body = doc.get('body')
    if not isinstance(body, list) or not 2 <= len(body) <= 20:
        raise ValueError('Issue form requires 2..20 elements')
    identifiers, labels = set(), set()
    required = 0
    for item in body:
        keys(item, {'type', 'id', 'attributes', 'validations'}, 'form element')
        kind = item.get('type')
        attrs = item.get('attributes')
        if kind == 'markdown':
            if set(item) != {'type', 'attributes'}:
                raise ValueError('Markdown elements cannot declare input IDs or validations')
            keys(attrs, {'value'}, 'markdown attributes')
            text(attrs.get('value'), 'Markdown value')
            continue
        if kind not in ('input', 'textarea', 'dropdown'):
            raise ValueError('Unsupported issue input type')
        identifier = item.get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier) or identifier in identifiers:
            raise ValueError('Issue input IDs must be valid and unique')
        identifiers.add(identifier)
        allowed = {'label', 'description'} | ({'options', 'multiple', 'default'} if kind == 'dropdown' else {'placeholder', 'value'})
        keys(attrs, allowed, 'input attributes')
        text(attrs.get('label'), 'Input label')
        if attrs['label'] in labels:
            raise ValueError('Input labels must be unique')
        labels.add(attrs['label'])
        for field in ('description', 'placeholder', 'value'):
            if field in attrs:
                text(attrs[field], 'Input ' + field)
        validations = item.get('validations', {})
        keys(validations, {'required'}, 'input validations')
        if 'required' in validations and type(validations['required']) is not bool:
            raise ValueError('Required must be a boolean')
        required += validations.get('required', False)
        if kind == 'dropdown':
            options = attrs.get('options')
            strings(options, 'Dropdown options')
            if 'multiple' in attrs and type(attrs['multiple']) is not bool:
                raise ValueError('Dropdown multiple must be a boolean')
            if 'default' in attrs and (type(attrs['default']) is not int or not 0 <= attrs['default'] < len(options)):
                raise ValueError('Dropdown default must index its options')
    if not identifiers or not required:
        raise ValueError('Issue form must require at least one input')
    return {'name': doc['name'], 'inputs': len(identifiers), 'required_inputs': required}


def validate_dependabot(doc):
    keys(doc, {'version', 'updates'}, 'Dependabot')
    updates = doc.get('updates')
    if type(doc.get('version')) is not int or doc['version'] != 2 or not isinstance(updates, list) or len(updates) != 2:
        raise ValueError('Dependabot requires version 2 and both update ecosystems')
    ecosystems = set()
    for item in updates:
        keys(item, {'package-ecosystem', 'directory', 'schedule', 'open-pull-requests-limit'}, 'Dependabot update')
        ecosystem = item.get('package-ecosystem')
        if ecosystem not in ('pip', 'github-actions') or ecosystem in ecosystems or item.get('directory') != '/':
            raise ValueError('Dependabot must cover unique root pip and github-actions updates')
        ecosystems.add(ecosystem)
        if item.get('schedule') != {'interval': 'weekly'}:
            raise ValueError('Dependabot must retain reviewed weekly schedules')
        limit = item.get('open-pull-requests-limit')
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError('Dependabot PR limits must be 1..5')


def validate_release(doc):
    keys(doc, {'changelog'}, 'release notes')
    changelog = doc.get('changelog')
    keys(changelog, {'exclude', 'categories'}, 'changelog')
    if changelog.get('exclude') != {'labels': ['skip-changelog']}:
        raise ValueError('Release notes must retain the reviewed exclusion')
    categories = changelog.get('categories')
    if not isinstance(categories, list) or not 2 <= len(categories) <= 12:
        raise ValueError('Release notes require bounded categories')
    titles, labels = set(), set()
    for number, category in enumerate(categories):
        keys(category, {'title', 'labels'}, 'release category')
        title, assigned = category.get('title'), category.get('labels')
        text(title, 'Category title')
        strings(assigned, 'Category labels')
        if title in titles or labels.intersection(assigned):
            raise ValueError('Release category titles and labels must be unique')
        titles.add(title)
        labels.update(assigned)
        if '*' in assigned and (assigned != ['*'] or number != len(categories) - 1):
            raise ValueError('Release fallback must be alone in the last category')
    if '*' not in labels:
        raise ValueError('Release notes require a final fallback category')


def check(root=ROOT):
    root = Path(root)
    folder = root / '.github/ISSUE_TEMPLATE'
    if {p.name for p in folder.iterdir()} != FORMS | {'config.yml'}:
        raise ValueError('Issue template files differ from the reviewed forms')
    config = load_workflow(folder / 'config.yml')
    if config != {'blank_issues_enabled': False}:
        raise ValueError('Blank issues must stay disabled; contact destinations require explicit review')
    forms = [validate_form(load_workflow(folder / name)) for name in sorted(FORMS)]
    if len({form['name'] for form in forms}) != len(forms):
        raise ValueError('Issue form names must be unique')
    validate_dependabot(load_workflow(root / '.github/dependabot.yml'))
    validate_release(load_workflow(root / '.github/release.yml'))
    if not (root / '.github/pull_request_template.md').read_text(encoding='utf-8').strip():
        raise ValueError('Pull request template must not be empty')
    return {'passed': True, 'forms': forms, 'dependabot_ecosystems': ['pip', 'github-actions'],
            'scope': 'Reviewed community-file subset; not hosted rendering, account settings or full GitHub schema'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.root), indent=2))
    except (OSError, ValueError) as exc:
        raise SystemExit('Community checks failed: ' + str(exc))
