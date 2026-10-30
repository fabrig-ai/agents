import json
import tomllib
import unittest
from pathlib import Path

from fab.nextest import Case, ERROR_LINE, exact_filter, junit, overlay, union
from fab.tests.support import tmp_home


class NextestTest(unittest.TestCase):
    def test_nextest_case_key(self):
        case = Case('qa', 'crate::binary', 'test"\\é', 'pass', '')
        self.assertEqual(json.loads(case.key), [case.profile, case.binary, case.test])
        self.assertEqual(case.key, json.dumps([case.profile, case.binary, case.test],
                                             separators=(',', ':')))

    def test_nextest_junit_cases_in_order(self):
        long_error = 'x' * (ERROR_LINE + 20)
        xml = f'''<testsuites tests="7">
          <testsuite name="crate::one">
            <testcase name="passes"/>
            <testcase name="failure-text"><failure message="ignored">

  first line
second line</failure></testcase>
            <testcase name="failure-message"><failure message="message failure"/></testcase>
            <testcase name="skips"><skipped/></testcase>
          </testsuite>
          <testsuite name="crate::two">
            <testcase name="error-text"><error>\n{long_error}\nlater</error></testcase>
            <testcase name="error-message"><error message="message error"/></testcase>
            <testcase name="passes"/>
          </testsuite>
        </testsuites>'''
        with tmp_home() as home:
            path = home / 'junit.xml'
            sibling = path.with_suffix('.tmp')
            sibling.write_text(xml)
            sibling.replace(path)
            cases = junit(path, 'qa')
        self.assertEqual(cases, [
            Case('qa', 'crate::one', 'passes', 'pass', ''),
            Case('qa', 'crate::one', 'failure-text', 'fail', '  first line'),
            Case('qa', 'crate::one', 'failure-message', 'fail', 'message failure'),
            Case('qa', 'crate::one', 'skips', 'skipped', ''),
            Case('qa', 'crate::two', 'error-text', 'fail', 'x' * ERROR_LINE),
            Case('qa', 'crate::two', 'error-message', 'fail', 'message error'),
            Case('qa', 'crate::two', 'passes', 'pass', ''),
        ])

    def test_nextest_junit_invalid_reports(self):
        invalid = (
            '<testsuite/>',
            '<testsuites>',
            '<testsuites><testsuite/></testsuites>',
            '<testsuites><testsuite name="b"><testcase/></testsuite></testsuites>',
            '<testsuites><testsuite name="b"><testcase name="t"/></testsuite>'
            '<testsuite name="b"><testcase name="t"/></testsuite></testsuites>',
            '<testsuites tests="2"><testsuite name="b"><testcase name="t"/>'
            '</testsuite></testsuites>',
            '<testsuites tests="bad"/>',
        )
        with tmp_home() as home:
            path = home / 'junit.xml'
            with self.assertRaises(ValueError):
                junit(path, 'qa')
            for xml in invalid:
                with self.subTest(xml=xml):
                    sibling = path.with_suffix('.tmp')
                    sibling.write_text(xml)
                    sibling.replace(path)
                    with self.assertRaises(ValueError):
                        junit(path, 'qa')

    def test_nextest_junit_empty_and_child_precedence(self):
        with tmp_home() as home:
            path = home / 'junit.xml'
            for xml, expected in (
                ('<testsuites tests="0"/>', []),
                ('<testsuites><testsuite name="b"><testcase name="t">'
                 '<error message="error"/><skipped/><failure message="failure"/>'
                 '</testcase></testsuite></testsuites>',
                 [Case('qa', 'b', 't', 'fail', 'failure')]),
            ):
                sibling = path.with_suffix('.tmp')
                sibling.write_text(xml)
                sibling.replace(path)
                self.assertEqual(junit(path, 'qa'), expected)

    def test_nextest_exact_filter(self):
        self.assertEqual(exact_filter('crate-name::bin.1', 'crate::module::test_name'),
                         'binary_id(=crate-name::bin.1) & test(=crate::module::test_name)')
        for bad in ('a b', 'a"b', 'a(b)', '', 'a\nb', 'é'):
            for binary, test in ((bad, 'test'), ('binary', bad)):
                with self.subTest(binary=binary, test=test), self.assertRaises(ValueError):
                    exact_filter(binary, test)

    def test_nextest_union(self):
        filters = [exact_filter('b', test) for test in ('a', 'b', 'c')]
        self.assertEqual(union(filters[:1]), filters[0])
        self.assertEqual(union(filters), f'({filters[0]}) | ({filters[1]}) | ({filters[2]})')
        with self.assertRaises(ValueError):
            union([])

    def test_nextest_overlay_preserves_config(self):
        config = '''
"clé" = "café 東京"
count = 4
ratio = 1.25
small = 1e-20
negative-zero = -0.0
[profile.x]
retries = 2
fail-fast = false
[[profile.x.overrides]]
filter = 'test(=crate::module::test_name)'
threads-required = 2
[profile.x.overrides.slow-timeout]
period = '10s'
terminate-after = 3
[profile.other]
retries = 0
'''
        expected = tomllib.loads(config)
        path = Path('/tmp/résultats/junit.xml')
        expected['profile']['x']['junit'] = {
            'path': str(path), 'store-success-output': False, 'store-failure-output': True,
        }
        result = overlay(config, 'x', path)
        self.assertEqual(tomllib.loads(result), expected)
        self.assertIn('café 東京', result)
        self.assertEqual([line.split(' = ', 1)[0] for line in result.splitlines()],
                         [json.dumps(key, ensure_ascii=False) for key in expected])
        self.assertIn('"negative-zero" = -0.0', result)

    def test_nextest_overlay_replaces_junit(self):
        config = '''[profile.x.junit]
path = "old.xml"
store-success-output = true
extra = "discard"
'''
        self.assertEqual(tomllib.loads(overlay(config, 'x', Path('new.xml'))), {
            'profile': {'x': {'junit': {'path': 'new.xml', 'store-success-output': False,
                                      'store-failure-output': True}}},
        })

    def test_nextest_overlay_unknown_profile(self):
        for config in ('', '[profile.x]\nretries = 1'):
            with self.subTest(config=config), self.assertRaises(ValueError):
                overlay(config, 'unknown', Path('junit.xml'))

    def test_nextest_overlay_unsupported_values(self):
        for value in ('inf', '-inf', 'nan', '1e999', '2026-10-30',
                      '2026-10-30T12:30:00Z', '12:30:00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                overlay(f'[profile.x]\nvalue = [{value}]', 'x', Path('junit.xml'))
