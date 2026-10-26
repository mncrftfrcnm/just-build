"""Real public-entry checks for typed JSON and preserved caller input."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from support import ROOT, load_example
import api_contract
import behavior_contract
from contract_assertions import json_equal, json_expectation, strict_json


CLI_APP = '''import json, os, sys
from pathlib import Path
action = sys.argv[1]
target = Path('input.bin')
if action == 'init':
    target.write_bytes(b'private-fixture-content')
    print('created')
elif action == 'directory':
    target.mkdir()
    print('created')
elif action == 'oversized':
    target.write_bytes(b'x' * (1024 * 1024 + 1))
    print('created')
elif action == 'inspect':
    print(json.dumps({'ok': True, 'count': 1, 'ratio': 1.0, 'items': [None]}))
elif action == 'mutate':
    target.write_bytes(b'changed')
    print(json.dumps({'ok': True, 'count': 1, 'ratio': 1.0, 'items': [None]}))
elif action == 'delete':
    target.unlink()
    print(json.dumps({'ok': True, 'count': 1, 'ratio': 1.0, 'items': [None]}))
elif action == 'hardlink':
    Path('alias.bin').write_bytes(target.read_bytes())
    target.unlink()
    os.link('alias.bin', target)
    print(json.dumps({'ok': True, 'count': 1, 'ratio': 1.0, 'items': [None]}))
elif action == 'raw':
    sys.stdout.buffer.write(bytes.fromhex(sys.argv[2]))
elif action == 'would-create':
    Path(__file__).with_name('must-not-execute').write_text('ran')
    target.write_bytes(b'created too late')
    print('created')
else:
    print('invalid request', file=sys.stderr)
    sys.exit(2)
'''

EXPECTED = {'ok': True, 'count': 1, 'ratio': 1.0, 'items': [None]}


def cli_contract():
    def step(action, **checks):
        return {'argv': ['{python}', '{project}/app.py', action],
                'exit_code': 0, **checks}
    return {'name': 'JSON and input preservation fixture', 'scenarios': [
        {'id': 'read-without-mutation', 'steps': [
            step('init', file_exists=['input.bin']),
            step('inspect', stdout_json_equals=copy.deepcopy(EXPECTED), file_unchanged=['input.bin']),
            step('inspect', stdout_json_equals=copy.deepcopy(EXPECTED))]},
        {'id': 'bad-input', 'steps': [
            {'argv': ['{python}', '{project}/app.py', 'invalid'], 'exit_code': 2,
             'stderr_contains': ['invalid request'], 'file_absent': ['not-created.bin']}]}]}


def api_json_contract():
    contract = load_example('security/local-api-contract.json')
    for scenario in contract['scenarios']:
        for step in scenario['steps']:
            step.pop('body_contains')
            step['body_json_equals'] = ({'items': []} if step['status'] == 200 else
                                       {'error': 'invalid request'} if step['status'] == 400 else
                                       {'error': 'rate limit exceeded'})
    return contract


class StrictJSONTests(unittest.TestCase):
    def test_whole_value_matching_preserves_types_and_nested_structure(self):
        value = {'nothing': None, 'values': [True, 1, 1.0, 'one'], 'empty': {}}
        self.assertTrue(json_equal(strict_json(json.dumps(value).encode()), value))
        for actual, expected in ((True, 1), (1, 1.0), ([False], [0]),
                                 ({'x': 1, 'extra': 2}, {'x': 1}), ('1', 1)):
            with self.subTest(actual=actual, expected=expected):
                self.assertFalse(json_equal(actual, expected))
        self.assertIsNone(strict_json(b'null'))

    def test_output_rejects_permissive_invalid_or_unbounded_json(self):
        for raw in (b'{"x":1,"x":1}', b'NaN', b'Infinity', b'-Infinity', b'1e999',
                    b'{} trailing', b'{} {}', b'"\xff"', b'"\\ud800"',
                    b'[' * 21 + b'0' + b']' * 21, b'"' + b'x' * 4095 + b'"',
                    b'[' + b','.join([b'0'] * 256) + b']'):
            with self.subTest(raw=raw[:45]), self.assertRaises(ValueError):
                strict_json(raw)

    def test_expectation_rejects_non_json_cycles_nonfinite_and_limits(self):
        cycle = []; cycle.append(cycle)
        for value in ((1, 2), {1: 'bad key'}, {'bad': {1, 2}}, float('nan'),
                      float('inf'), 'x' * 4097, [0] * 256, cycle, '\ud800'):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                json_expectation(value)

    def test_legacy_normalized_contract_hashes_are_unchanged(self):
        cases = [(behavior_contract, 'cli-behavior-contract.json',
                  '098127218507f82f79bd2c613ff0163d6013199c5587a9e6dacd8ca948ebc621'),
                 (api_contract, 'security/local-api-contract.json',
                  '8561895bdf1cf27f312df7d76e7b663c18fcf6a2a7f47f4bdb98d8d9c8133b3f')]
        for module, name, expected in cases:
            with self.subTest(name=name):
                normalized = module.validate(load_example(name))
                actual = hashlib.sha256(json.dumps(normalized, sort_keys=True,
                    separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(actual, expected)


class CLIAssertionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'app.py').write_text(CLI_APP, encoding='utf-8')

    def test_actual_json_and_unchanged_bytes_pass_without_persisting_raw_input(self):
        report = behavior_contract.run(self.root, cli_contract())
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['steps_passed'], 4)
        self.assertNotIn('private-fixture-content', json.dumps(report))

    def test_actual_mutation_or_deletion_fails_freshly_normalized_contract(self):
        for action in ('mutate', 'delete'):
            with self.subTest(action=action):
                manifest = cli_contract()
                manifest['scenarios'][0]['steps'][1]['argv'][-1] = action
                # Revalidating/resealing a manifest cannot make changed input pass.
                normalized = behavior_contract.validate(manifest)
                report = behavior_contract.run(self.root, normalized)
                self.assertFalse(report['passed'])
                self.assertTrue(any('file_unchanged:' in failure
                    for failure in report['outcomes'][-1]['failures']), report)

    def test_missing_input_fails_before_command_can_create_it(self):
        manifest = cli_contract()
        first = manifest['scenarios'][0]['steps'][0]
        first['argv'][-1] = 'would-create'
        first['file_unchanged'] = ['input.bin']
        report = behavior_contract.run(self.root, manifest)
        self.assertFalse(report['passed'])
        self.assertIn('precondition', report['outcomes'][0]['failures'][0])
        self.assertFalse((self.root / 'must-not-execute').exists())

    def test_directory_and_oversized_input_fail_before_observed_step(self):
        for action in ('directory', 'oversized'):
            with self.subTest(action=action):
                manifest = cli_contract()
                manifest['scenarios'][0]['steps'][0]['argv'][-1] = action
                report = behavior_contract.run(self.root, manifest)
                self.assertFalse(report['passed'])
                self.assertEqual(report['steps_passed'], 1)
                self.assertIn('precondition', report['outcomes'][-1]['failures'][0])

    def test_same_bytes_replaced_by_hardlink_fail_closed(self):
        manifest = cli_contract()
        manifest['scenarios'][0]['steps'][1]['argv'][-1] = 'hardlink'
        report = behavior_contract.run(self.root, manifest)
        self.assertFalse(report['passed'])
        self.assertTrue(any('file_unchanged:' in failure
                            for failure in report['outcomes'][-1]['failures']), report)

    def test_actual_wrong_typed_json_fails_despite_matching_snippet(self):
        manifest = cli_contract()
        step = manifest['scenarios'][0]['steps'][1]
        step['stdout_contains'] = ['true']
        step['stdout_json_equals']['ok'] = 1
        report = behavior_contract.run(self.root, behavior_contract.validate(manifest))
        self.assertFalse(report['passed'])
        self.assertIn('stdout_json_equals: whole JSON value/type differs',
                      report['outcomes'][-1]['failures'])

    def test_actual_duplicate_nonfinite_and_invalid_utf8_outputs_fail(self):
        for raw, expected in ((b'{"ok":true,"ok":true}', {'ok': True}),
                              (b'NaN', None), (b'"\xff"', '\ufffd')):
            with self.subTest(raw=raw):
                manifest = cli_contract()
                step = manifest['scenarios'][0]['steps'][1]
                step['argv'] = ['{python}', '{project}/app.py', 'raw', raw.hex()]
                step['stdout_json_equals'] = expected
                report = behavior_contract.run(self.root, manifest)
                self.assertFalse(report['passed'])
                self.assertTrue(any('strict UTF-8 JSON' in failure
                    for failure in report['outcomes'][-1]['failures']), report)

    def test_json_scalar_and_null_assertions_are_real_observations(self):
        manifest = cli_contract()
        step = manifest['scenarios'][0]['steps'][2]
        step['argv'] = ['{python}', '{project}/app.py', 'raw', b'null'.hex()]
        step['stdout_json_equals'] = None
        self.assertTrue(behavior_contract.run(self.root, manifest)['passed'])

    def test_unchanged_validation_rejects_aliases_absence_traversal_and_unknowns(self):
        for value in ([], ['input.bin', 'INPUT.bin'], ['../input.bin'],
                      ['C:/input.bin'], ['input.bin'] * 6):
            with self.subTest(value=value), self.assertRaises(behavior_contract.ContractError):
                manifest = cli_contract()
                manifest['scenarios'][0]['steps'][1]['file_unchanged'] = value
                behavior_contract.validate(manifest)
        manifest = cli_contract()
        manifest['scenarios'][0]['steps'][1]['file_absent'] = ['INPUT.bin']
        with self.assertRaisesRegex(behavior_contract.ContractError, 'conflicts'):
            behavior_contract.validate(manifest)
        manifest = cli_contract()
        manifest['scenarios'][0]['steps'][1]['stdout_json_shape'] = {'anything': True}
        with self.assertRaises(behavior_contract.ContractError):
            behavior_contract.validate(manifest)


class APIAssertionTests(unittest.TestCase):
    def test_actual_loopback_json_contract_keeps_error_throttle_and_recovery(self):
        report = api_contract.run(ROOT / 'examples/security/sample-api', api_json_contract())
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['steps_passed'], 6)
        self.assertEqual(report['target'], 'loopback-only')

    def test_actual_wrong_json_type_fails_with_matching_response_snippet(self):
        manifest = api_json_contract()
        first = manifest['scenarios'][0]['steps'][0]
        first['body_contains'] = ['items']
        first['body_json_equals'] = {'items': False}
        report = api_contract.run(ROOT / 'examples/security/sample-api', api_contract.validate(manifest))
        self.assertFalse(report['passed'])
        self.assertIn('body_json_equals: whole JSON value/type differs',
                      report['outcomes'][0]['failures'])

    def test_actual_duplicate_key_response_fails_instead_of_last_value_winning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = (ROOT / 'examples/security/sample-api/server.py').read_text(encoding='utf-8')
            source = source.replace("body = json.dumps(obj).encode('utf-8')",
                                    "body = b'{\"items\":[],\"items\":[]}'")
            (root / 'server.py').write_text(source, encoding='utf-8')
            report = api_contract.run(root, api_json_contract())
            self.assertFalse(report['passed'])
            self.assertTrue(any('strict UTF-8 JSON' in failure
                for failure in report['outcomes'][0]['failures']), report)

    def test_json_only_still_requires_nonempty_observation_and_rate_recovery(self):
        manifest = api_json_contract()
        first = manifest['scenarios'][0]['steps'][0]
        first['body_json_equals'] = None
        self.assertIsNone(api_contract.validate(manifest)['scenarios'][0]['steps'][0]['body_json_equals'])
        first.pop('body_json_equals')
        with self.assertRaisesRegex(api_contract.APIContractError, 'Each step needs'):
            api_contract.validate(manifest)
        manifest = api_json_contract()
        manifest['scenarios'][1]['steps'][-1]['wait_seconds'] = 0
        with self.assertRaisesRegex(api_contract.APIContractError, 'post-wait recovery'):
            api_contract.validate(manifest)

    def test_both_contracts_reject_invalid_expectations(self):
        for invalid in ({'x': float('nan')}, {'x': (1, 2)}, 'x' * 4097):
            with self.subTest(kind=type(invalid).__name__):
                cli = cli_contract()
                cli['scenarios'][0]['steps'][1]['stdout_json_equals'] = invalid
                with self.assertRaises(behavior_contract.ContractError):
                    behavior_contract.validate(cli)
                api = api_json_contract()
                api['scenarios'][0]['steps'][0]['body_json_equals'] = invalid
                with self.assertRaises(api_contract.APIContractError):
                    api_contract.validate(api)


if __name__ == '__main__':
    unittest.main()
