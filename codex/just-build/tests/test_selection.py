import copy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, TODAY, build_spec, decision, fixture, reject_others, seal
from idea_validation import canonical_url, digest, evaluate_dossier, require_current
from just_build import InvalidSpec, check_build, scaffold, verify_selection_binding
import run_tracker


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.d = fixture()
        self.seed = self.d['candidates']['candidates'][0]['seed_id']

    def evaluate(self):
        return evaluate_dossier(self.d)

    def test_valid_selection_is_explicitly_synthetic(self):
        result = self.evaluate()
        self.assertEqual(result['outcome'], 'build')
        self.assertTrue(result['fixture_only'])
        self.assertEqual(result['reviewer_mode'], 'single-agent-fallback')
        self.assertEqual(result['seed_id'], self.seed)

    def test_lower_score_wins_over_optimism(self):
        self.d['validation']['assessments'][0]['scores']['usefulness'] = 3
        seal(self.d)
        result = self.evaluate()
        self.assertEqual(result['ranked'][0]['scores']['usefulness'], 3)
        self.assertEqual(result['ranked'][0]['score'], 3.6)

    def test_failed_constraint_cannot_be_averaged_away(self):
        self.d['validation']['assessments'][0]['constraints']['privacy_safety']['status'] = 'fail'
        # Reject other than one clear runner-up, avoiding an artificial tie.
        for role in ('primary', 'validation'):
            for row in self.d[role]['assessments'][2:]:
                row['constraints']['resources']['status'] = 'fail'
        seed = self.d['primary']['assessments'][1]['seed_id']
        decision(self.d, 'build', seed)
        result = self.evaluate()
        self.assertEqual(result['seed_id'], seed)
        self.assertEqual(result['ranked'][0]['status'], 'reject')

    def test_unknown_constraint_requires_experiment(self):
        reject_others(self.d)
        self.d['validation']['assessments'][0]['constraints']['resources']['status'] = 'unknown'
        decision(self.d, 'experiment', self.seed)
        self.assertEqual(self.evaluate()['outcome'], 'experiment')

    def test_missing_user_history_yields_exploratory_experiment(self):
        reject_others(self.d)
        self.d['pool']['context_status'] = 'unavailable'
        self.d['pool']['context_basis'] = 'No past chats or personal projects are accessible in this synthetic test.'
        for idea in self.d['pool']['ideas']:
            if idea['origin'] in ('stated-interest', 'observed-work'):
                idea['origin'] = 'exploratory'
        for role in ('primary', 'validation'):
            for row in self.d[role]['assessments']:
                row['scores']['user_fit'] = 2
                row['score_evidence']['user_fit'] = ['need']
        decision(self.d, 'experiment', self.seed)
        self.assertEqual(self.evaluate()['outcome'], 'experiment')

    def test_all_rejected_means_no_build(self):
        reject_others(self.d, keep=-1)
        decision(self.d, 'no-build')
        result = self.evaluate()
        self.assertIsNone(result['winner'])
        self.assertTrue(all(x['status'] == 'reject' for x in result['ranked']))

    def test_insufficient_differentiation_rejects_candidate(self):
        reject_others(self.d)
        self.d['validation']['assessments'][0]['scores']['differentiation'] = 2.5
        decision(self.d, 'no-build')
        self.assertEqual(self.evaluate()['outcome'], 'no-build')

    def test_copied_evidence_is_not_corroboration(self):
        reject_others(self.d)
        self.d['validation']['sources'] = copy.deepcopy(self.d['primary']['sources'])
        decision(self.d, 'experiment', self.seed)
        self.assertEqual(self.evaluate()['ranked'][0]['additional_origins'], [])

    def test_irrelevant_new_citation_cannot_pass_corroboration(self):
        reject_others(self.d)
        report = self.d['validation']
        report['sources'][-1].update(locator=self.d['primary']['sources'][-1]['locator'], publisher='observation-a')
        report['sources'].append({'id': 'irrelevant', 'kind': 'local', 'locator': 'fixture: unrelated safety note', 'publisher': 'fresh-but-irrelevant', 'finding': 'Synthetic unrelated note', 'observed_on': TODAY})
        report['assessments'][0]['constraints']['privacy_safety']['evidence'].append('irrelevant')
        decision(self.d, 'experiment', self.seed)
        self.assertEqual(self.evaluate()['ranked'][0]['status'], 'experiment')

    def test_same_location_cannot_change_publisher(self):
        self.d['validation']['sources'][0]['publisher'] = 'renamed-to-look-independent'
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, 'conflicting'):
            self.evaluate()

    def test_unblinded_pass_requires_experiment(self):
        reject_others(self.d)
        self.d['validation']['blinded'] = False
        decision(self.d, 'experiment', self.seed)
        self.assertEqual(self.evaluate()['outcome'], 'experiment')

    def test_same_agent_cannot_claim_two_subagents(self):
        for role in ('primary', 'validation'):
            self.d[role]['reviewer'] = {'mode': 'subagent', 'id': 'same-agent'}
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, 'same reviewer'):
            self.evaluate()

    def test_near_tie_requires_experiment(self):
        for role in ('primary', 'validation'):
            self.d[role]['assessments'][1]['scores'] = dict(self.d[role]['assessments'][0]['scores'])
        # Slug order determines which candidate the deterministic comparison names.
        seed = min(self.seed, self.d['primary']['assessments'][1]['seed_id'])
        decision(self.d, 'experiment', seed)
        self.assertEqual(self.evaluate()['outcome'], 'experiment')

    def test_experiment_cannot_silently_authorize_spending(self):
        reject_others(self.d)
        self.d['validation']['blinded'] = False
        decision(self.d, 'experiment', self.seed)
        self.d['arbitration']['experiment']['max_cost'] = 1
        with self.assertRaisesRegex(InvalidSpec, 'zero-cost'):
            self.evaluate()

    def test_experiment_needs_observable_failure(self):
        reject_others(self.d)
        self.d['validation']['blinded'] = False
        decision(self.d, 'experiment', self.seed)
        del self.d['arbitration']['experiment']['failure']
        with self.assertRaises(InvalidSpec):
            self.evaluate()

    def test_material_score_disagreement_requires_resolution(self):
        reject_others(self.d)
        self.d['primary']['assessments'][0]['scores']['usefulness'] = 5
        self.d['validation']['assessments'][0]['scores']['usefulness'] = 3
        decision(self.d, 'experiment', self.seed)
        self.assertEqual(self.evaluate()['outcome'], 'experiment')
        self.d['arbitration']['resolutions'] = [{'seed_id': self.seed, 'dimension': 'usefulness', 'reason': 'Primary assumes repeated use; validation counts only the first session. Retain the lower score.', 'evidence': ['primary:need', 'validation:need']}]
        decision(self.d, 'build', self.seed)
        self.assertEqual(self.evaluate()['ranked'][0]['scores']['usefulness'], 3)

    def test_resolution_cannot_cite_unrelated_dimension(self):
        self.d['primary']['assessments'][0]['scores']['usefulness'] = 5
        self.d['validation']['assessments'][0]['scores']['usefulness'] = 3
        self.d['arbitration']['resolutions'] = [{'seed_id': self.seed, 'dimension': 'usefulness', 'reason': 'Synthetic comparison', 'evidence': ['primary:user', 'validation:user']}]
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, "dimension's evidence"):
            self.evaluate()

    def test_frozen_shortlist_changes_invalidate_reports(self):
        self.d['candidates']['candidates'][0]['reason'] += ' Edited after research.'
        with self.assertRaisesRegex(InvalidSpec, 'shortlist/pool digest'):
            self.evaluate()

    def test_changed_report_invalidates_arbiter(self):
        self.d['primary']['assessments'][0]['need']['finding'] += ' Changed.'
        with self.assertRaisesRegex(InvalidSpec, 'research report digest'):
            self.evaluate()

    def test_arbitrary_winner_is_rejected(self):
        self.d['arbitration']['decision']['seed_id'] = self.d['primary']['assessments'][1]['seed_id']
        with self.assertRaisesRegex(InvalidSpec, 'computed outcome'):
            self.evaluate()

    def test_future_and_stale_reports_are_rejected(self):
        for offset in (-8, 1):
            with self.subTest(offset=offset):
                self.d = fixture()
                self.d['primary']['created_on'] = (date.fromisoformat(TODAY) + timedelta(days=offset)).isoformat()
                seal(self.d)
                with self.assertRaisesRegex(InvalidSpec, 'seven days'):
                    self.evaluate()

    def test_source_access_cannot_follow_report(self):
        self.d['primary']['sources'][0]['observed_on'] = (date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, 'source access'):
            self.evaluate()

    def test_claims_need_known_sources(self):
        self.d['primary']['assessments'][0]['need']['evidence'] = ['invented']
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, 'known source'):
            self.evaluate()

    def test_high_user_fit_cannot_be_inferred_from_generic_topic(self):
        self.d['primary']['assessments'][0]['score_evidence']['user_fit'] = ['need']
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, 'user-stated'):
            self.evaluate()

    def test_novelty_needs_falsifiable_advantage_and_distinct_alternatives(self):
        for mutation in ('missing-test', 'same-alternative'):
            with self.subTest(mutation=mutation):
                self.d = fixture()
                gap = self.d['primary']['assessments'][0]['differentiation']
                if mutation == 'missing-test':
                    gap['falsifier'] = ''
                else:
                    gap['alternatives'][1]['name'] = gap['alternatives'][0]['name']
                seal(self.d)
                with self.assertRaises(InvalidSpec):
                    self.evaluate()

    def test_every_candidate_must_be_assessed_once(self):
        self.d['validation']['assessments'][1] = copy.deepcopy(self.d['validation']['assessments'][0])
        seal(self.d)
        with self.assertRaisesRegex(InvalidSpec, 'exactly one'):
            self.evaluate()

    def test_numeric_edge_cases_fail_closed(self):
        # Do not seal NaN/Inf: canonical serialization itself rejects them.
        for number in (float('nan'), float('inf'), True, -1, 5.1):
            with self.subTest(number=number):
                self.d = fixture()
                self.d['primary']['assessments'][0]['scores']['usefulness'] = number
                with self.assertRaises(InvalidSpec):
                    self.evaluate()

    def test_malformed_untrusted_json_shapes_fail_cleanly(self):
        cases = [
            (('primary',), []),
            (('validation', 'sources'), [None]),
            (('primary', 'reviewer'), 'not-an-object'),
            (('primary', 'assessments', 0, 'seed_id'), []),
            (('primary', 'assessments', 0, 'constraints'), []),
            (('primary', 'assessments', 0, 'need', 'evidence'), [['unhashable']]),
            (('primary', 'sources', 0, 'publisher'), {}),
            (('arbitration', 'version'), True),
            (('pool', 'version'), True),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                self.d = fixture()
                node = self.d
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                with self.assertRaises(InvalidSpec):
                    self.evaluate()

    def add_trend(self, published=None, two=True):
        for role in ('primary', 'validation'):
            report = self.d[role]
            for index in (1, 2):
                report['sources'].append({'id': f'trend-{index}', 'kind': 'web', 'url': f'https://trend{index}.example.org/releases', 'publisher': f'trend-origin-{index}', 'finding': 'Synthetic dated growth observation, not real research.', 'observed_on': TODAY, 'published_on': published or TODAY})
            report['assessments'][0]['scores']['trend'] = 4
            report['assessments'][0]['score_evidence']['trend'] = ['trend-1', 'trend-2'] if two else ['trend-1']
        seal(self.d)

    def test_current_trend_can_contribute_only_with_two_origins(self):
        self.add_trend()
        self.assertEqual(self.evaluate()['ranked'][0]['scores']['trend'], 4)

    def test_old_hype_cannot_contribute_trend_points(self):
        self.add_trend(published=(date.fromisoformat(TODAY) - timedelta(days=31)).isoformat())
        with self.assertRaisesRegex(InvalidSpec, 'current dated'):
            self.evaluate()

    def test_one_story_cannot_establish_momentum(self):
        self.add_trend(two=False)
        with self.assertRaisesRegex(InvalidSpec, 'two editorial'):
            self.evaluate()

    def test_url_variants_are_deduplicated(self):
        self.assertEqual(canonical_url('https://www.example.org/x?utm_source=a&id=1#top'), canonical_url('https://example.org/x?id=1&fbclid=b'))

    def test_private_and_credential_urls_are_rejected(self):
        for url in ('https://127.0.0.1/x', 'https://[::1]/x', 'https://10.0.0.4/x', 'https://u:p@example.org/x', 'file:///secrets', 'https://host.local/x', 'https://example.org:bad/x'):
            with self.subTest(url=url), self.assertRaises(InvalidSpec):
                canonical_url(url)

    def test_stale_selection_cannot_start_build(self):
        with self.assertRaisesRegex(InvalidSpec, 'selection date is stale'):
            require_current({'as_of': '2000-01-01'})

    def test_synthetic_example_cannot_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(InvalidSpec, 'fixture-only'):
                scaffold(build_spec(self.d), tmp, dossier=self.d)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_profile_cannot_omit_dossier(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(InvalidSpec):
            scaffold(build_spec(self.d), tmp)

    def authorize_synthetic_scaffold(self):
        # This toggle is isolated test setup, never evidence of live research.
        for role in ('primary', 'validation'):
            self.d[role]['fixture_only'] = False
        seal(self.d)

    def test_scaffold_freezes_selected_seed_and_preserves_presentation_changes(self):
        self.authorize_synthetic_scaffold()
        spec = build_spec(self.d)
        spec.update(name='A custom task workbench', summary='A refined presentation of the selected task board.')
        with tempfile.TemporaryDirectory() as tmp:
            project = scaffold(spec, tmp, dossier=self.d)
            recorded = json.loads((project / '.just-build' / 'decision.json').read_text())
            selected = next(idea for idea in self.d['pool']['ideas'] if idea['id'] == self.seed)
            self.assertEqual(recorded['selected_seed_id'], self.seed)
            self.assertEqual(recorded['selected_concept'], selected)
            self.assertEqual(recorded['name'], spec['name'])
            self.assertEqual(verify_selection_binding(recorded, self.d), selected)
            self.assertNotIn('selected_seed_id', spec)  # caller input is not mutated
            brief = (project / 'PROJECT_BRIEF.md').read_text()
            self.assertIn('**Seed ID:** ' + self.seed, brief)
            self.assertIn('**Mechanism:** ' + selected['mechanism'], brief)
            self.assertIn('**Hook:** ' + selected['hook'], brief)
            check_build(project)

    def test_selected_name_cannot_mask_replaced_core_concept(self):
        self.authorize_synthetic_scaffold()
        for field, replacement in (('audience', 'Marine research laboratories'),
                                   ('problem', 'Coastal sensors need calibration'),
                                   ('first_slice', 'Plot ocean temperature from a sensor feed')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                spec = build_spec(self.d)
                spec[field] = replacement
                with self.assertRaisesRegex(InvalidSpec, 'spec.' + field + ' must equal'):
                    scaffold(spec, tmp, dossier=self.d)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_supplied_selected_metadata_cannot_override_validated_pool(self):
        self.authorize_synthetic_scaffold()
        selected = next(idea for idea in self.d['pool']['ideas'] if idea['id'] == self.seed)
        for field, replacement in (('selected_seed_id', 'a-different-seed'),
                                   ('selected_concept', {**selected, 'mechanism': 'An unrelated sensor dashboard'})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                spec = build_spec(self.d)
                spec[field] = replacement
                with self.assertRaisesRegex(InvalidSpec, 'complete validated winner seed'):
                    scaffold(spec, tmp, dossier=self.d)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_check_rejects_changed_or_partial_record_binding(self):
        self.authorize_synthetic_scaffold()
        for mutation in ('audience', 'selected_seed_id', 'selected_concept', 'missing-id', 'missing-concept', 'full-binding'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                project = scaffold(build_spec(self.d), tmp, dossier=self.d)
                path = project / '.just-build' / 'decision.json'
                recorded = json.loads(path.read_text())
                if mutation == 'audience':
                    recorded['audience'] = 'An incompatible audience'
                elif mutation == 'selected_seed_id':
                    recorded['selected_seed_id'] = 'a-different-seed'
                elif mutation == 'selected_concept':
                    recorded['selected_concept']['mechanism'] = 'An incompatible mechanism'
                elif mutation.startswith('missing-'):
                    del recorded['selected_seed_id' if mutation == 'missing-id' else 'selected_concept']
                else:
                    other = self.d['pool']['ideas'][1]
                    recorded.update(selected_seed_id=other['id'], selected_candidate=other['name'], selected_concept=other,
                                    audience=other['audience'], problem=other['problem'], first_slice=other['first_demo'])
                path.write_text(json.dumps(recorded))
                with self.assertRaisesRegex(InvalidSpec, 'selected_concept|selected concept binding'):
                    check_build(project)

    def test_check_rejects_changed_or_duplicated_brief_binding(self):
        self.authorize_synthetic_scaffold()
        for mutation in ('core', 'frozen', 'duplicate'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                spec = build_spec(self.d)
                project = scaffold(spec, tmp, dossier=self.d)
                path = project / 'PROJECT_BRIEF.md'
                brief = path.read_text()
                if mutation == 'core':
                    brief = brief.replace('## Audience\n' + spec['audience'], '## Audience\nAn incompatible audience')
                elif mutation == 'frozen':
                    brief = brief.replace('**Seed ID:** ' + self.seed, '**Seed ID:** a-different-seed')
                else:
                    brief += '\n## Audience\nAn incompatible duplicate audience\n'
                path.write_text(brief)
                with self.assertRaisesRegex(InvalidSpec, 'PROJECT_BRIEF selected concept binding'):
                    check_build(project)

    def test_legacy_named_and_corroborated_records_remain_readable(self):
        self.authorize_synthetic_scaffold()
        with tempfile.TemporaryDirectory() as tmp:
            spec = build_spec(self.d)
            del spec['selection_profile']
            del spec['selected_candidate']
            project = scaffold(spec, tmp)
            check_build(project)
        with tempfile.TemporaryDirectory() as tmp:
            project = scaffold(build_spec(self.d), tmp, dossier=self.d)
            path = project / '.just-build' / 'decision.json'
            recorded = json.loads(path.read_text())
            del recorded['selected_seed_id']
            del recorded['selected_concept']
            path.write_text(json.dumps(recorded))
            check_build(project)

    def test_scaffold_and_tracker_preserve_selection_evidence(self):
        # Fixture labels are removed only inside this isolated unit test, never
        # from the shipped example or from a real research record.
        for role in ('primary', 'validation'):
            self.d[role]['fixture_only'] = False
        seal(self.d)
        with tempfile.TemporaryDirectory() as tmp:
            project = scaffold(build_spec(self.d), tmp, dossier=self.d)
            ledger = project / '.just-build'
            state = run_tracker.init(ledger, project, 'auto', 'new', 'Synthetic integration test')
            self.assertEqual(state['stages']['research']['status'], 'active')
            recorded = json.loads((ledger / 'decision.json').read_text())
            self.assertEqual(recorded['selection_dossier_sha256'], digest(self.d))

    def test_tampered_dossier_blocks_tracker_start(self):
        for role in ('primary', 'validation'):
            self.d[role]['fixture_only'] = False
        seal(self.d)
        with tempfile.TemporaryDirectory() as tmp:
            project = scaffold(build_spec(self.d), tmp, dossier=self.d)
            ledger = project / '.just-build'
            changed = copy.deepcopy(self.d)
            changed['primary']['assessments'][0]['need']['finding'] += ' Changed after selection.'
            (ledger / 'idea-validation.json').write_text(json.dumps(changed))
            with self.assertRaises(InvalidSpec):
                run_tracker.init(ledger, project, 'auto', 'new', 'Synthetic tamper test')

    def test_public_select_command_marks_fixture_with_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'dossier.json'
            path.write_text(json.dumps(self.d))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'just_build.py'), 'select', '--file', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertTrue(json.loads(result.stdout)['fixture_only'])


if __name__ == '__main__':
    unittest.main()
