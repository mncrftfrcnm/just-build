"""Synthetic research fixtures: these are never live demand/market evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from idea_validation import digest, proposal_digest

TODAY = datetime.now(timezone.utc).date().isoformat()


def load_example(name):
    return json.loads((ROOT / 'examples' / name).read_text(encoding='utf-8'))


def seal(d):
    for role in ('primary', 'validation'):
        d[role]['shortlist_sha256'] = proposal_digest(d['candidates'], d['pool'])
    d['arbitration']['primary_sha256'] = digest(d['primary'])
    d['arbitration']['validation_sha256'] = digest(d['validation'])
    return d


def fixture():
    d = {'candidates': load_example('diverse-candidates.json'), 'pool': load_example('idea-pool.json'), 'as_of': TODAY}
    for role, origin in (('primary', 'observation-a'), ('validation', 'observation-b')):
        sources = [
            {'id': 'user', 'kind': 'user', 'locator': 'synthetic-test: stated wish for local tools', 'publisher': 'fixture-user', 'finding': 'Synthetic user explicitly wants a no-key local tool.', 'observed_on': TODAY},
            {'id': 'alternative-one', 'kind': 'local', 'locator': 'synthetic-test: alternative-one spec', 'publisher': 'fixture-alternative-one', 'finding': 'Synthetic existing tool requires manual re-entry.', 'observed_on': TODAY},
            {'id': 'alternative-two', 'kind': 'local', 'locator': 'synthetic-test: manual-workflow', 'publisher': 'fixture-alternative-two', 'finding': 'Synthetic manual workflow has no cross-session recovery.', 'observed_on': TODAY},
            {'id': 'need', 'kind': 'local', 'locator': 'synthetic-test: ' + origin, 'publisher': origin, 'finding': 'Synthetic independent observation supports a recoverable local journey.', 'observed_on': TODAY},
        ]
        report = {'version': 1, 'role': role, 'created_on': TODAY, 'fixture_only': True,
                  'reviewer': {'mode': 'single-agent', 'id': 'fixture-role-' + role}, 'sources': sources, 'assessments': []}
        if role == 'validation':
            report['blinded'] = True
        for i, candidate in enumerate(d['candidates']['candidates']):
            value = 4.5 if i == 0 else 3.5
            report['assessments'].append({
                'seed_id': candidate['seed_id'],
                'scores': {'user_fit': value, 'usefulness': value, 'feasibility': value, 'differentiation': value, 'trend': 0},
                'score_evidence': {'user_fit': ['user'], 'usefulness': ['need'], 'feasibility': ['need'], 'differentiation': ['alternative-one', 'alternative-two', 'need'], 'trend': []},
                'constraints': {key: {'status': 'pass', 'reason': 'Synthetic local no-key fixture meets this constraint.', 'evidence': ['user', 'need']} for key in ('resources', 'privacy_safety', 'first_slice')},
                'need': {'finding': 'Synthetic user loses task state between sessions.', 'evidence': ['need']},
                'disconfirming': {'finding': 'A simple manual list may already be sufficient; test before expanding.', 'evidence': ['alternative-two']},
                'differentiation': {
                    'alternatives': [{'name': 'Synthetic alternative one', 'evidence': ['alternative-one']}, {'name': 'Synthetic manual list', 'evidence': ['alternative-two']}],
                    'advantage': 'Recover a paused local journey without retyping state.',
                    'falsifier': 'The existing alternative resumes the same journey with equal effort.',
                    'test': 'Compare interrupted-session recovery using a fixed three-task fixture.',
                    'evidence': ['need', 'alternative-one', 'alternative-two']},
            })
        d[role] = report
    d['arbitration'] = {'version': 1, 'resolutions': [], 'decision': {'outcome': 'build', 'seed_id': d['candidates']['candidates'][0]['seed_id'], 'reason': 'Synthetic fixture: strongest conservative useful local journey.'}}
    return seal(d)


def decision(d, outcome, seed=None):
    d['arbitration']['decision'] = {'outcome': outcome, 'seed_id': seed, 'reason': 'Synthetic outcome follows recorded evidence and constraints.'}
    if outcome == 'experiment':
        d['arbitration']['experiment'] = {'hypothesis': 'A recovery workflow saves effort.', 'procedure': 'Compare two local mock journeys on the fixed fixture.', 'success': 'Recover all three tasks with fewer steps.', 'failure': 'No task recovery or equal/more effort.', 'max_minutes': 30, 'max_cost': 0}
    return seal(d)


def reject_others(d, keep=0):
    for role in ('primary', 'validation'):
        for i, row in enumerate(d[role]['assessments']):
            if i != keep:
                row['constraints']['resources']['status'] = 'fail'
    return seal(d)


def build_spec(d):
    spec = load_example('spec.json')
    seed_id = d['arbitration']['decision']['seed_id']
    selected = next(idea for idea in d['pool']['ideas'] if idea['id'] == seed_id)
    spec.update(selection_profile='corroborated-v1', selected_candidate=selected['name'],
                audience=selected['audience'], problem=selected['problem'], first_slice=selected['first_demo'])
    return spec
