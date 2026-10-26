import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_community import ROOT, check, validate_form, validate_dependabot, validate_release
from check_workflows import load_workflow


class CommunityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.form = load_workflow(ROOT / '.github/ISSUE_TEMPLATE/evaluation_report.yml')
        self.dependencies = load_workflow(ROOT / '.github/dependabot.yml')
        self.release = load_workflow(ROOT / '.github/release.yml')

    def test_current_configuration_has_all_forms_and_both_ecosystems(self):
        result = check()
        self.assertTrue(result['passed'])
        self.assertEqual(3, len(result['forms']))
        self.assertEqual({'pip', 'github-actions'}, set(result['dependabot_ecosystems']))

    def test_duplicate_invalid_ids_and_labels_are_rejected(self):
        for field, value in (('id', 'environment'), ('id', '../bad'), ('id', [])):
            with self.subTest(field=field, value=value):
                doc = copy.deepcopy(self.form)
                doc['body'][2][field] = value
                with self.assertRaisesRegex(ValueError, 'IDs'):
                    validate_form(doc)
        doc = copy.deepcopy(self.form)
        doc['body'][2]['attributes']['label'] = doc['body'][1]['attributes']['label']
        with self.assertRaisesRegex(ValueError, 'labels must be unique'):
            validate_form(doc)

    def test_nonboolean_required_and_unusable_dropdowns_are_rejected(self):
        for mutation in ('required', 'duplicate-options', 'nontext-options', 'default', 'multiple'):
            with self.subTest(mutation=mutation):
                doc = copy.deepcopy(self.form)
                item = doc['body'][2]
                if mutation == 'required':
                    item['validations']['required'] = 'true'
                elif mutation == 'duplicate-options':
                    item['attributes']['options'] = ['same', 'same']
                elif mutation == 'nontext-options':
                    item['attributes']['options'] = [123]
                elif mutation == 'default':
                    item['attributes']['default'] = 99
                else:
                    item['attributes']['multiple'] = 'false'
                with self.assertRaises(ValueError):
                    validate_form(doc)

    def test_empty_forms_and_unreviewed_fields_cannot_silently_pass(self):
        for mutation in ('required', 'type', 'markdown', 'top'):
            with self.subTest(mutation=mutation):
                doc = copy.deepcopy(self.form)
                if mutation == 'required':
                    for item in doc['body']:
                        item.pop('validations', None)
                elif mutation == 'type':
                    doc['body'][1]['type'] = 'unsupported'
                elif mutation == 'markdown':
                    doc['body'][0]['id'] = 'invalid-markdown-id'
                else:
                    doc['assignees'] = ['invented-owner']
                with self.assertRaises(ValueError):
                    validate_form(doc)

    def test_dependabot_cannot_drop_ecosystems_or_enable_unreviewed_access(self):
        mutations = [lambda d: d['updates'].pop(),
                     lambda d: d['updates'][0].update({'directory': '/elsewhere'}),
                     lambda d: d['updates'][1].update({'package-ecosystem': 'github-actions'}),
                     lambda d: d['updates'][0].update({'open-pull-requests-limit': True}),
                     lambda d: d.update({'registries': {'private': {}}}),
                     lambda d: d['updates'][0].update({'insecure-external-code-execution': 'allow'})]
        for mutate in mutations:
            doc = copy.deepcopy(self.dependencies)
            mutate(doc)
            with self.assertRaises(ValueError):
                validate_dependabot(doc)

    def test_release_categories_cannot_lose_or_shadow_fallback(self):
        for mutation in ('missing', 'early', 'duplicate-label', 'duplicate-title'):
            with self.subTest(mutation=mutation):
                doc = copy.deepcopy(self.release)
                categories = doc['changelog']['categories']
                if mutation == 'missing':
                    categories.pop()
                elif mutation == 'early':
                    categories.insert(0, categories.pop())
                elif mutation == 'duplicate-label':
                    categories[1]['labels'] = categories[0]['labels']
                else:
                    categories[1]['title'] = categories[0]['title']
                with self.assertRaises(ValueError):
                    validate_release(doc)

    def test_actual_files_reject_duplicate_form_names_blank_issue_bypass_and_empty_pr(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT / '.github', root / '.github')
            path = root / '.github/ISSUE_TEMPLATE/config.yml'
            path.write_text('blank_issues_enabled: true\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Blank issues'):
                check(root)
            path.write_text('blank_issues_enabled: false\n', encoding='utf-8')
            pr = root / '.github/pull_request_template.md'
            saved = pr.read_text(encoding='utf-8')
            pr.write_text('', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Pull request'):
                check(root)
            pr.write_text(saved, encoding='utf-8')
            path = root / '.github/ISSUE_TEMPLATE/feature_request.yml'
            doc = load_workflow(path)
            doc['name'] = self.form['name']
            path.write_text(yaml.safe_dump(doc), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'names must be unique'):
                check(root)


if __name__ == '__main__':
    unittest.main()
