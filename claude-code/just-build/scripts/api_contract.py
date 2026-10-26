#!/usr/bin/env python3
"""Bounded loopback HTTP behavior checks for an authorized local project.

Not a sandbox, vulnerability scanner or authorization to probe other services.
The runner never accepts an external URL and never follows redirects.
"""
from __future__ import annotations
import argparse
import http.client
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
from host_safety import is_link, safe_relative, checked_path, bounded_json
from process_runner import ManagedProcess
from contract_assertions import json_expectation, strict_json, json_equal

class APIContractError(ValueError):
    pass

ID = re.compile(r'^[a-z][a-z0-9-]{0,39}$')
METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}
ALLOWED_HEADERS = {'Content-Type', 'Accept', 'X-Client-ID'}


def _path(s):
    if not isinstance(s, str) or not s.startswith('/') or s.startswith('//') or len(s) > 160 or any(ord(c) < 32 or ord(c) > 126 for c in s) or '\\' in s or '#' in s or '://' in s:
        raise APIContractError('HTTP path must be a bounded origin-relative path (no external URLs)')
    return s


def _argv(items):
    if not isinstance(items, list) or len(items) != 4 or any(not isinstance(s, str) or not s or len(s) > 180 for s in items):
        raise APIContractError('Launch argv must be a bounded argument list')
    if items[:1] != ['{python}'] or not items[1].startswith('{project}/') or not items[1].endswith('.py'):
        raise APIContractError('Launch must use {python} {project}/<entry>.py')
    entry = items[1][len('{project}/'):]
    try:
        safe_relative(entry)
    except ValueError as exc:
        raise APIContractError(str(exc)) from exc
    if not entry or '\\' in entry or any(c in ('', '.', '..') for c in entry.split('/')):
        raise APIContractError('Unsafe API entry path')
    if items[2:] != ['--port', '{port}']:
        raise APIContractError('Launch must use a single --port {port} loopback target; no extra bind/URL arguments')
    for x in items:
        for token in ('{python}', '{project}', '{port}'):
            x = x.replace(token, '')
        if '{' in x or '}' in x or '\x00' in x:
            raise APIContractError('Unsupported launch placeholder')
    return list(items)


def validate(doc):
    if not isinstance(doc, dict) or set(doc) != {'name', 'launch', 'scenarios'}:
        raise APIContractError('API contract requires name, launch, scenarios')
    name = doc['name']
    if not isinstance(name, str) or not 5 <= len(name) <= 100:
        raise APIContractError('Invalid API contract name')
    launch = doc['launch']
    if not isinstance(launch, dict) or set(launch) != {'argv', 'ready_path'}:
        raise APIContractError('Launch requires argv and ready_path')
    argv = _argv(launch['argv'])
    ready = _path(launch['ready_path'])
    scenarios = doc['scenarios']
    if not isinstance(scenarios, list) or not 2 <= len(scenarios) <= 4:
        raise APIContractError('API contract needs 2..4 scenarios')
    names, total, positive, negative, throttled, recovered = set(), 0, False, False, False, False
    cleaned = []
    for case in scenarios:
        if not isinstance(case, dict) or set(case) != {'id', 'steps'} or not isinstance(case['id'], str) or not ID.fullmatch(case['id']) or case['id'] in names:
            raise APIContractError('Invalid or duplicate scenario id')
        names.add(case['id'])
        steps = case['steps']
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise APIContractError('Each scenario needs 1..8 steps')
        normal = []
        limited_key = None
        successes = {}
        for step in steps:
            allowed = {'method', 'path', 'status', 'body', 'body_contains', 'headers', 'header_contains', 'wait_seconds', 'body_json_equals'}
            if not isinstance(step, dict) or set(step) - allowed or not {'method', 'path', 'status'}.issubset(step):
                raise APIContractError('Step needs method, path, status and no unknown keys')
            method = step['method']
            if not isinstance(method, str) or method not in METHODS:
                raise APIContractError('Unsupported HTTP method')
            path = _path(step['path'])
            status = step['status']
            if type(status) is not int or not 200 <= status <= 499:
                raise APIContractError('Expected status must be 200..499')
            body = step.get('body', '')
            if not isinstance(body, str) or len(body.encode('utf-8')) > 1024:
                raise APIContractError('Request body must be <=1024 bytes')
            headers = step.get('headers', {})
            if not isinstance(headers, dict) or len(headers) > 3 or any(k not in ALLOWED_HEADERS or not isinstance(v, str) or not 1 <= len(v) <= 64 or '\r' in v or '\n' in v for k,v in headers.items()):
                raise APIContractError('Request headers must be bounded and allowlisted')
            snippets = step.get('body_contains', [])
            if not isinstance(snippets, list) or not 0 <= len(snippets) <= 3 or any(not isinstance(s, str) or not s or len(s) > 120 for s in snippets):
                raise APIContractError('Response snippets must contain 0..3 bounded entries')
            extra = {}
            if 'body_json_equals' in step:
                try:
                    extra['body_json_equals'] = json_expectation(step['body_json_equals'])
                except (ValueError, TypeError) as exc:
                    raise APIContractError(f'Invalid body_json_equals: {exc}') from exc
            if not snippets and not extra:
                raise APIContractError('Each step needs response snippets or a whole JSON assertion')
            response_headers = step.get('header_contains', {})
            if not isinstance(response_headers, dict) or len(response_headers) > 3 or any(not isinstance(k, str) or k.lower() not in ('retry-after','content-type','x-ratelimit-remaining') or not isinstance(v, str) or not 1 <= len(v) <= 80 for k,v in response_headers.items()):
                raise APIContractError('Unsupported response header checks')
            wait = step.get('wait_seconds', 0)
            if type(wait) not in (int, float) or not 0 <= wait <= 2:
                raise APIContractError('wait_seconds must be 0..2')
            total += 1
            positive |= status < 300
            negative |= 400 <= status < 429
            actor_key = (method, path, headers.get('X-Client-ID', 'anonymous'))
            if status == 429:
                if 'retry-after' not in {k.lower() for k in response_headers}:
                    raise APIContractError('429 must check Retry-After')
                if successes.get(actor_key, 0) < 2 or limited_key is not None:
                    raise APIContractError('429 requires two prior successful requests to the same endpoint and client')
                throttled = True
                limited_key = actor_key
            elif limited_key == actor_key and 200 <= status < 300 and wait > 0:
                recovered = True
            elif status < 300 and limited_key is None:
                successes[actor_key] = successes.get(actor_key, 0) + 1
            normal.append({'method': method, 'path': path, 'status': status, 'body': body, 'headers': headers, 'body_contains': snippets, 'header_contains': response_headers, 'wait_seconds': wait, **extra})
        cleaned.append({'id': case['id'], 'steps': normal})
    if not 5 <= total <= 20 or not (positive and negative and throttled and recovered):
        raise APIContractError('Contract needs 5..20 requests, success, 4xx error, 429 and post-wait recovery')
    return {'name': name, 'launch': {'argv': argv, 'ready_path': ready}, 'scenarios': cleaned}


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _request(port, method, path, body='', headers=None, *, raw_body=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request(method, path, body=body.encode('utf-8'), headers=headers or {})
        response = connection.getresponse()
        raw = response.read(4097)
        if len(raw) > 4096:
            raise http.client.HTTPException('response exceeds the contract body limit')
        return response.status, {k.lower(): v for k,v in response.getheaders()}, raw if raw_body else raw.decode('utf-8', errors='replace')
    finally:
        connection.close()


def run(project, manifest):
    contract = validate(manifest)
    if is_link(project):
        raise APIContractError('linked project roots are forbidden')
    project = Path(project).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise APIContractError('project must be a directory')
    entry = project / contract['launch']['argv'][1][len('{project}/'):]
    try:
        checked_path(entry, project)
    except (OSError, ValueError) as exc:
        raise APIContractError('API entry must be unlinked and inside the project') from exc
    if not entry.is_file():
        raise APIContractError('API entry must be a regular project file')
    outcomes = []
    total = sum(len(c['steps']) for c in contract['scenarios'])
    with tempfile.TemporaryDirectory(prefix='just-build-api-') as scratch:
        port = _free_port()
        tokens = {'{python}': sys.executable, '{project}': str(project), '{port}': str(port)}
        argv = [a.replace('{python}', tokens['{python}']).replace('{project}', tokens['{project}']).replace('{port}', tokens['{port}']) for a in contract['launch']['argv']]
        with ManagedProcess(argv, scratch, timeout=120, extra_env={'JUST_BUILD_DATA_DIR': scratch}) as proc:
            try:
                deadline = time.monotonic() + 4
                ready = False
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    try:
                        code, _, _ = _request(port, 'GET', contract['launch']['ready_path'])
                        if 200 <= code < 300:
                            ready = True
                            break
                    except (OSError, http.client.HTTPException):
                        time.sleep(0.05)
                if not ready:
                    return {'name': contract['name'], 'passed': False, 'steps_passed': 0, 'steps_total': total, 'outcomes': [{'scenario': 'startup', 'step': 0, 'passed': False, 'failures': ['local service did not become ready']}], 'target': 'loopback-only'}
                for case in contract['scenarios']:
                    for index, step in enumerate(case['steps'], 1):
                        if step['wait_seconds']:
                            time.sleep(step['wait_seconds'])
                        failures = []
                        if proc.poll() is not None or proc.output_limited:
                            return {'name': contract['name'], 'passed': False, 'steps_passed': sum(x['passed'] for x in outcomes), 'steps_total': total, 'outcomes': outcomes + [{'scenario': case['id'], 'step': index, 'passed': False, 'failures': ['local service stopped or exceeded its resource budget']}], 'target': 'loopback-only'}
                        try:
                            code, headers, content = _request(port, step['method'], step['path'], step['body'], step['headers'], raw_body='body_json_equals' in step)
                            if code != step['status']:
                                failures.append(f'expected status {step["status"]}, got {code}')
                            if 'body_json_equals' in step:
                                try:
                                    if not json_equal(strict_json(content), step['body_json_equals']):
                                        failures.append('body_json_equals: whole JSON value/type differs')
                                except (ValueError, UnicodeError):
                                    failures.append('body_json_equals: response must be bounded strict UTF-8 JSON')
                                content = content.decode('utf-8', errors='replace')
                            for snippet in step['body_contains']:
                                if snippet not in content:
                                    failures.append('missing response content')
                            for key, text in step['header_contains'].items():
                                if text not in headers.get(key.lower(), ''):
                                    failures.append(f'missing/incorrect response header {key}')
                        except (OSError, http.client.HTTPException):
                            failures.append('loopback request failed')
                        outcomes.append({'scenario': case['id'], 'step': index, 'passed': not failures, 'failures': failures})
                        if failures:
                            return {'name': contract['name'], 'passed': False, 'steps_passed': sum(x['passed'] for x in outcomes), 'steps_total': total, 'outcomes': outcomes, 'target': 'loopback-only'}
                return {'name': contract['name'], 'passed': True, 'steps_passed': len(outcomes), 'steps_total': total, 'outcomes': outcomes, 'target': 'loopback-only'}
            finally:
                proc.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run a frozen API contract against a project started on loopback only')
    parser.add_argument('--project', required=True)
    parser.add_argument('--file', required=True)
    a = parser.parse_args(argv)
    try:
        result = run(a.project, bounded_json(a.file))
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 1
    except (APIContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'API contract: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
