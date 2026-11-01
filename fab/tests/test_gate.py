"""Selection rules and command seams (docs/design/landing.md, 2; fab.md, 4)."""

import json
import unittest
from pathlib import Path

from fab import gate
from fab.sh import Failed, Result, run
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


def metadata(root=Path('/workspace')):
    names = ('core', 'normal', 'build', 'dev', 'transitive', 'unrelated', 'always', 'nested')
    packages = [{'id': name, 'name': name, 'version': '1.0.0',
                 'manifest_path': str(root / name / 'Cargo.toml')} for name in names]
    packages[-1]['manifest_path'] = str(root / 'core/examples/nested/Cargo.toml')
    edges = {'normal': ['core'], 'build': ['core'], 'dev': ['core'], 'transitive': ['dev']}
    return {'workspace_root': str(root), 'workspace_members': list(names), 'packages': packages,
            'resolve': {'nodes': [{'id': name, 'dependencies': edges.get(name, [])} for name in names]}}


def resolved_metadata(root=Path('/workspace')):
    data = metadata(root)
    data['packages'] += [
        {'id': 'external', 'name': 'external', 'version': '2.0.0', 'source': 'registry+fixture'},
        {'id': 'middle', 'name': 'middle', 'version': '1.0.0', 'source': 'registry+fixture'}]
    data['resolve']['nodes'][0]['dependencies'] = ['middle']
    data['resolve']['nodes'] += [{'id': 'middle', 'dependencies': ['external']},
                                 {'id': 'external', 'dependencies': []}]
    return data


def lockfile(packages):
    return 'version = 4\n' + ''.join(
        '\n[[package]]\n' + '\n'.join(f'{key} = {json.dumps(value)}' for key, value in package.items()) + '\n'
        for package in packages)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + '.new')
    sibling.write_text(text)
    sibling.replace(path)


class RecordsTest(unittest.TestCase):
    def test_loader_passes_repo_once_and_returns_the_same_dict(self):
        repo = Path('/workspace')
        loaded = []
        meta = {}

        def load(path):
            loaded.append(path)
            return meta

        once = gate.loader(load)
        self.assertEqual(loaded, [])
        self.assertIs(once(repo), meta)
        self.assertIs(once(repo), meta)
        self.assertEqual(loaded, [repo])

    def test_shown_preserves_modes_and_sorts_package_names(self):
        for selected in ('full', 'docs'):
            self.assertEqual(gate.shown(selected), selected)
        packages = {'normal', 'core'}
        self.assertEqual(gate.shown(packages), ['core', 'normal'])
        self.assertEqual(packages, {'normal', 'core'})
        self.assertEqual(gate.shown(set()), [])

    def test_step_texts_preserves_order_names_codes_and_three_decimals(self):
        results = [gate.StepResult('ratchet:jig', ('ratchet',), 0, True, 1.2346),
                   gate.StepResult('clippy', ('check',), 7, False, 0)]
        self.assertEqual(gate.step_texts(results), ['ratchet:jig:0:1.235', 'clippy:7:0.000'])
        self.assertEqual(gate.step_texts(()), [])


class SelectionTest(unittest.TestCase):
    closure = {'core', 'normal', 'build', 'dev', 'transitive', 'always'}

    def select(self, paths, **kwargs):
        return gate.selection(paths, metadata(), always=['always'],
                              read_by_tests=['docs/contract/**'], **kwargs)

    def test_full_inputs(self):
        for path in ('Cargo.toml', '.config/nextest.toml', 'nested/.config/gate/x', 'rust-toolchain',
                     'core/rust-toolchain.toml', 'rustfmt.toml', 'core/src/rustfmt.toml', 'core/clippy.toml'):
            with self.subTest(path=path):
                self.assertTrue(gate.full_inputs(iter([path])))
                self.assertEqual(self.select([path]), 'full')
        self.assertFalse(gate.full_inputs(['core/Cargo.toml', 'my.config/x', 'tools/check.py']))

    def test_source_manifest_and_reverse_closure_all_edge_kinds(self):
        for path in ('core/src/lib.rs', 'core/Cargo.toml'):
            with self.subTest(path=path):
                self.assertEqual(self.select([path]), self.closure)

    def test_inputs_select_owner(self):
        for path in ('tests/check.rs', 'benches/speed.rs', 'examples/demo.rs', 'build.rs'):
            with self.subTest(path=path):
                self.assertEqual(self.select(['unrelated/' + path]), {'unrelated', 'always'})

    def test_nested_owner_and_root_package(self):
        owners = gate.package_owners(metadata())
        self.assertEqual(owners[0], ('core/examples/nested', 'nested'))
        self.assertEqual(self.select(['core/examples/nested/src/lib.rs']), {'nested', 'always'})
        self.assertEqual(self.select(['core-other/src/lib.rs']), 'full')
        data = resolved_metadata()
        data['packages'][0]['manifest_path'] = '/workspace/Cargo.toml'
        self.assertIn(('.', 'core'), gate.package_owners(data))
        self.assertIn('core', gate.selection(['src/lib.rs'], data, always=[], read_by_tests=[]))

    def test_unowned_and_non_source_non_markdown_are_full(self):
        for path in ('outside/source.rs', 'core/scripts/check.py', 'core/fixtures/input'):
            with self.subTest(path=path):
                self.assertEqual(self.select([path]), 'full')

    def test_docs_and_tools_add_no_packages(self):
        docs = ['README.md', 'docs/guide.md', 'core/README.md', 'agents/x.md', 'tools/y.py']
        self.assertEqual(self.select(docs), 'docs')
        self.assertEqual(self.select([]), 'docs')
        self.assertEqual(self.select(['core/src/lib.rs', *docs]), self.closure)
        self.assertEqual(self.select(['toolsmith/source.rs']), 'full')

    def test_markdown_in_source_directories(self):
        for directory in ('src', 'tests', 'benches', 'examples'):
            with self.subTest(directory=directory):
                self.assertEqual(self.select([f'unrelated/{directory}/input.md']), {'unrelated', 'always'})
        self.assertEqual(self.select(['core/examples/nested/src/input.md']), {'nested', 'always'})

    def test_read_by_tests_globs_take_precedence(self):
        for paths in (['docs/contract/store.md'], ['core/src/lib.rs', 'docs/contract/deep/store.md']):
            self.assertEqual(self.select(paths), 'full')
        self.assertEqual(gate.selection(['tools/input.md'], {}, always=[],
                                        read_by_tests=['tools/*.md']), 'full')

    def test_lock_requires_comparison_and_keeps_always_when_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'base and HEAD'):
            self.select(['Cargo.lock'])
        self.assertEqual(self.select(['Cargo.lock'], locked=set()), {'always'})
        self.assertEqual(self.select(['Cargo.lock'], locked={'core'}), self.closure)
        self.assertEqual(gate.selection(['Cargo.lock'], metadata(), locked=set(),
                                        always=[], read_by_tests=[]), set())

    def test_missing_always_and_resolve_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'missing workspace packages: absent, missing'):
            gate.selection(['core/src/lib.rs'], metadata(), always=['missing', 'absent'], read_by_tests=[])
        data = metadata()
        data['resolve'] = None
        with self.assertRaisesRegex(ValueError, 'resolve graph'):
            gate.selection(['core/src/lib.rs'], data, always=[], read_by_tests=[])

    def test_external_lock_change_reverse_closure(self):
        before = lockfile([{'name': 'external', 'version': '1.0.0', 'source': 'registry+fixture'}])
        after = lockfile([{'name': 'external', 'version': '2.0.0', 'source': 'registry+fixture'}])
        data = resolved_metadata()
        locked = gate.lock_changes(before, after, data)
        self.assertEqual(locked, {'external'})
        self.assertEqual(gate.selection(['Cargo.lock'], data, locked=locked,
                                        always=['always'], read_by_tests=[]), self.closure)

    def test_lock_fields_checksum_and_dependency_order(self):
        entry = {'name': 'external', 'version': '2.0.0', 'source': 'registry+fixture',
                 'dependencies': ['one', 'two'], 'checksum': 'before'}
        for updates, expected in (({'version': '1.0.0'}, {'external'}),
                                  ({'source': 'git+fixture'}, {'external'}),
                                  ({'name': 'other'}, {'external'}),
                                  ({'dependencies': ['one']}, {'external'}),
                                  ({'checksum': 'after', 'dependencies': ['two', 'one']}, set())):
            with self.subTest(updates=updates):
                self.assertEqual(gate.lock_changes(lockfile([{**entry, **updates}]), lockfile([entry]),
                                                   resolved_metadata()), expected)

    def test_removed_dependencies_and_added_entries(self):
        before = [{'name': 'core', 'version': '1.0.0', 'dependencies': ['removed']},
                  {'name': 'removed', 'version': '1.0.0'}]
        after = [{'name': 'core', 'version': '1.0.0'}]
        self.assertEqual(gate.lock_changes(lockfile(before), lockfile(after), metadata()), {'core'})
        self.assertEqual(gate.lock_changes(lockfile([]), lockfile([{'name': 'unrelated', 'version': '1.0.0'}]),
                                           metadata()), {'unrelated'})

    def test_lock_duplicate_versions_and_sources(self):
        data = resolved_metadata()
        data['packages'] += [{'id': 'other-version', 'name': 'external', 'version': '1.0.0',
                              'source': 'registry+fixture'},
                             {'id': 'other-source', 'name': 'external', 'version': '2.0.0',
                              'source': 'git+fixture'}]
        entry = {'name': 'external', 'version': '2.0.0', 'source': 'registry+fixture'}
        self.assertEqual(gate.lock_changes(lockfile([]), lockfile([entry]), data), {'external'})
        self.assertEqual(gate.lock_changes(lockfile([entry]), lockfile([]), data), {'external'})


class FilesTest(unittest.TestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.repo = self.home / 'checkout'
        self.repo.mkdir()

    def test_config_cutover_and_comments(self):
        write(self.repo / 'tools/queue/always.txt', '# old\n always # explanation\n\n')
        write(self.repo / 'tools/queue/read-by-tests.txt', ' docs/old/** \n')
        self.assertEqual(gate.config(self.repo), (['always'], ['docs/old/**']))
        write(self.repo / '.config/gate/always.txt', 'core\n # comment\nnormal\n')
        write(self.repo / '.config/gate/read-by-tests.txt', 'docs/new/** # input\n')
        self.assertEqual(gate.config(self.repo), (['core', 'normal'], ['docs/new/**']))

    def test_config_missing_lists_do_not_fall_back(self):
        self.assertEqual(gate.config(self.repo), ([], []))
        write(self.repo / 'tools/queue/always.txt', 'old\n')
        (self.repo / '.config/gate').mkdir(parents=True)
        self.assertEqual(gate.config(self.repo), ([], []))

    def test_metadata_uses_two_locked_commands_and_separate_diagnostics(self):
        workspace = {'workspace_root': str(self.repo), 'workspace_members': ['core'],
                     'packages': [], 'resolve': None}
        resolved = {'workspace_root': 'ignored', 'workspace_members': ['ignored'],
                    'packages': [{'id': 'core'}, {'id': 'external'}], 'resolve': {'nodes': []}}
        fake = FakeRunner().on(['cargo', 'metadata', '--no-deps'],
                               Result(0, json.dumps(workspace), 'diagnostic\n')).on(
                                   ['cargo', 'metadata'], Result(0, json.dumps(resolved), 'warning\n'))
        self.assertEqual(gate.metadata(self.repo, sh=fake), {**workspace, 'packages': resolved['packages'],
                                                           'resolve': resolved['resolve']})
        self.assertEqual(fake.argvs(), [
            ['cargo', 'metadata', '--no-deps', '--format-version', '1', '--locked'],
            ['cargo', 'metadata', '--format-version', '1', '--locked']])
        self.assertTrue(all(call.cwd == str(self.repo) for call in fake.calls))
        with self.assertRaises(Failed):
            gate.metadata(self.repo, sh=FakeRunner().on(['cargo'], Result(1, err='bad manifest')))

    def test_loader_defaults_to_metadata_with_injected_runner(self):
        meta = metadata(self.repo)
        fake = FakeRunner().on(['cargo', 'metadata'], Result(0, json.dumps(meta)))
        once = gate.loader(sh=fake)
        self.assertEqual(fake.calls, [])
        loaded = once(self.repo)
        self.assertEqual(loaded, meta)
        self.assertIs(once(self.repo), loaded)
        self.assertEqual(fake.argvs(), [
            ['cargo', 'metadata', '--no-deps', '--format-version', '1', '--locked'],
            ['cargo', 'metadata', '--format-version', '1', '--locked']])
        self.assertTrue(all(call.cwd == str(self.repo) for call in fake.calls))

    def test_select_full_docs_and_tools_without_metadata_or_git(self):
        def no_load(repo):
            self.fail('metadata should not be loaded')

        fake = FakeRunner()
        write(self.repo / '.config/gate/read-by-tests.txt', 'docs/contract/**\n')
        for paths, expected in ((['Cargo.toml'], 'full'), (['tools/check.py'], 'docs'),
                                (['README.md', 'core/README.md'], 'docs'),
                                (['docs/contract/store.md'], 'full'), ([], 'docs')):
            with self.subTest(paths=paths):
                self.assertEqual(gate.select(self.repo, paths, sh=fake, load=no_load), expected)
        self.assertEqual(fake.calls, [])

    def test_select_default_loader_uses_injected_runner(self):
        data = metadata(self.repo)
        fake = FakeRunner().on(['git', 'rev-parse'], Result(0, 'tip\ntip\n')).on(
            ['cargo', 'metadata'], Result(0, json.dumps(data)))
        self.assertEqual(gate.select(self.repo, ['unrelated/src/lib.rs'], sh=fake), {'unrelated'})
        self.assertEqual(sum(call.argv[:2] == ['cargo', 'metadata'] for call in fake.calls), 2)

    def test_run_steps_stops_after_red_and_appends_command_output(self):
        log = self.home / 'checks.log'
        write(log, 'prior log\n')
        steps = [gate.Step(name, ('checker', name, 'two words'), str(self.repo))
                 for name in ('fmt', 'clippy', 'build')]
        fake = FakeRunner().on(['checker', 'fmt'], Result(0, 'formatted\n', 'fmt diagnostic\n')).on(
            ['checker', 'clippy'], Result(9, 'lint output\n', 'lint error\n'))
        times = iter([0, 2, 10, 18])
        outcomes = gate.run_steps(steps, log, sh=fake, clock=lambda: next(times))
        self.assertEqual(outcomes, [gate.StepResult('fmt', steps[0].argv, 0, True, 2),
                                    gate.StepResult('clippy', steps[1].argv, 9, False, 8)])
        self.assertEqual(fake.argvs(), [list(step.argv) for step in steps[:2]])
        text = log.read_text()
        self.assertTrue(text.startswith('prior log\n'))
        for fragment in ("[fmt] checker fmt 'two words'", 'formatted\nfmt diagnostic\n',
                         '[clippy]', 'lint output\nlint error\n', f'(cwd {self.repo})'):
            self.assertIn(fragment, text)
        self.assertNotIn('[build]', text)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_no_tests_is_green_only_for_nextest_steps(self):
        for name in ('build', 'default', 'fuzzy', 'fmt', 'clippy', 'ratchet:jig', 'other'):
            with self.subTest(name=name):
                step = gate.Step(name, ('checker', name), str(self.repo))
                fake = FakeRunner().on(['checker'], Result(gate.NO_TESTS, 'empty\n'))
                outcomes = gate.run_steps([step], self.home / 'checks.log', sh=fake)
                self.assertEqual(outcomes[0].green, name in ('build', 'default', 'fuzzy'))
                self.assertEqual(outcomes[0].code, gate.NO_TESTS)

    def test_run_steps_timeout_launch_error_and_empty(self):
        step = gate.Step('build', ('checker',), str(self.repo))
        log = self.home / 'checks.log'
        fake = FakeRunner().on(['checker'], Result(124, 'partial\n', 'timed out\n'))
        options = []

        def runner(argv, **kwargs):
            options.append(kwargs)
            return fake(argv, **kwargs)

        result = gate.run_steps([step, step], log, sh=runner, timeout=7)[0]
        self.assertEqual(result.code, 124)
        self.assertFalse(result.green)
        self.assertEqual(options, [{'cwd': str(self.repo), 'timeout': 7}])
        self.assertIn('partial\ntimed out', log.read_text())

        def missing(argv, **kwargs):
            raise FileNotFoundError('missing checker')

        self.assertEqual(gate.run_steps([step], log, sh=missing)[0].code, 127)
        self.assertIn('missing checker', log.read_text())
        text = log.read_text()
        self.assertEqual(gate.run_steps([], log, sh=fake), [])
        self.assertEqual(log.read_text(), text)


class StepsTest(unittest.TestCase):
    repo = Path('/workspace')

    def test_full_both_lanes_and_docs(self):
        for lane, prefix in (('gate', ('heavy', '--gate')), ('build', ('heavy',))):
            with self.subTest(lane=lane):
                steps = gate.check_steps(self.repo, 'full', [], None, lane=lane)
                self.assertEqual(steps[0], gate.Step('fmt', ('cargo', 'fmt', '--all', '--check'), str(self.repo)))
                self.assertEqual([step.name for step in steps], ['fmt', 'clippy', 'build', 'default', 'fuzzy'])
                for step in steps[1:]:
                    self.assertEqual(step.argv[:len(prefix)], prefix)
                    self.assertIn('--workspace', step.argv)
                    self.assertNotIn('-p', step.argv)
                    self.assertEqual(step.cwd, str(self.repo))
                self.assertEqual(gate.check_steps(self.repo, 'docs', ['jig/README.md'], None, lane=lane), [])

    def test_package_scope_and_nextest_arguments(self):
        for lane, heavy in (('gate', ('heavy', '--gate')), ('build', ('heavy',))):
            with self.subTest(lane=lane):
                steps = gate.check_steps(self.repo, {'normal', 'core'}, ['core/src/lib.rs'], metadata(), lane=lane)
                scope = ('-p', 'core', '-p', 'normal')
                self.assertEqual([step.argv for step in steps], [
                    ('cargo', 'fmt', '--check', '-p', 'core'),
                    (*heavy, 'cargo', 'clippy', *scope, '--all-targets', '--', '-D', 'warnings'),
                    (*heavy, 'cargo', 'nextest', 'run', *scope, '--no-run'),
                    (*heavy, 'cargo', 'nextest', 'run', *scope, '--no-fail-fast'),
                    (*heavy, 'cargo', 'nextest', 'run', *scope, '--no-fail-fast', '--profile', 'fuzzy')])

    def test_fmt_owners_are_deepest_sorted_and_unique(self):
        paths = ['unrelated/src/lib.rs', 'core/src/lib.rs', 'core/tests/check.rs',
                 'core/examples/nested/src/lib.rs', 'outside.rs']
        steps = gate.check_steps(self.repo, {'core', 'normal', 'nested', 'unrelated', 'always'},
                                 paths, metadata(), lane='gate')
        self.assertEqual(steps[0].argv, ('cargo', 'fmt', '--check', '-p', 'core', '-p', 'nested', '-p', 'unrelated'))

    def test_no_rust_skips_fmt_and_metadata_empty_selection_skips_checks(self):
        for paths in (['Cargo.lock'], ['core/Cargo.toml'], ['core/tests/data.json']):
            with self.subTest(paths=paths):
                steps = gate.check_steps(self.repo, {'core'}, paths, None, lane='build')
                self.assertEqual([step.name for step in steps], ['clippy', 'build', 'default', 'fuzzy'])
        self.assertEqual(gate.check_steps(self.repo, set(), ['Cargo.lock'], None, lane='gate'), [])
        with self.assertRaisesRegex(ValueError, 'ownership metadata'):
            gate.check_steps(self.repo, {'core'}, ['core/src/lib.rs'], None, lane='gate')

    def test_ratchets_deduplicated_sorted_in_both_modes(self):
        paths = ['temper/src/lib.rs', 'jig/README.md', 'jig/src/lib.rs', 'skein/docs/x.md',
                 'smith/scripts/check.py', 'core/src/lib.rs', 'jiggy/README.md', 'tools/queue/mq']
        for write_mode in (True, False):
            with self.subTest(write=write_mode):
                self.assertEqual(gate.ratchet_steps(self.repo, paths, write=write_mode), [
                    gate.Step('ratchet:' + tree,
                              ('python3', '-I', '-B', f'/workspace/{tree}/scripts/old_forms.py',
                               *(('--write',) if write_mode else ())), f'/workspace/{tree}')
                    for tree in ('jig', 'skein', 'smith', 'temper')])
        self.assertEqual(gate.ratchet_steps(self.repo, ['tools/x.py'], write=True), [])


class GitTest(unittest.TestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        _, self.repo = git_pair(self.home)

    def commit(self):
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Fixture change')
        return git(self.repo, 'rev-parse', 'HEAD')

    def runner(self, argv, **kwargs):
        return run(argv, env=GIT_ENV, **kwargs)

    def test_changed_paths_renames_both_sides_and_preserves_unusual_names(self):
        self.assertEqual(gate.changed_paths(self.repo, sh=self.runner), [])
        write(self.repo / 'core/src/original.rs', 'fixture\n')
        write(self.repo / 'delete me', 'delete\n')
        base = self.commit()
        git(self.repo, 'mv', 'core/src/original.rs', 'renamed\nfile.rs')
        git(self.repo, 'rm', '-q', 'delete me')
        write(self.repo / 'added\tfile', 'added\n')
        candidate = self.commit()
        write(self.repo / 'uncommitted', 'ignored\n')
        self.assertEqual(gate.changed_paths(self.repo, candidate, base, sh=self.runner),
                         ['added\tfile', 'core/src/original.rs', 'delete me', 'renamed\nfile.rs'])
        self.assertEqual(gate.changed_paths(self.repo, base, base, sh=self.runner), [])
        self.assertEqual(gate.changed_paths(self.repo, candidate, sh=self.runner),
                         ['added\tfile', 'renamed\nfile.rs'])

    def test_select_candidate_source_docs_and_wrong_checkout(self):
        write(self.repo / 'tools/queue/always.txt', 'always\n')
        write(self.repo / 'core/src/input.md', 'input\n')
        write(self.repo / 'tools/y.py', 'ignored\n')
        candidate = self.commit()
        loaded = []

        def load(repo):
            loaded.append((repo, git(repo, 'rev-parse', 'HEAD')))
            return metadata(repo)

        paths = gate.changed_paths(self.repo, sh=self.runner)
        self.assertEqual(gate.select(self.repo, paths, candidate=candidate, sh=self.runner, load=load),
                         SelectionTest.closure)
        self.assertEqual(loaded, [(self.repo, candidate)])
        with self.assertRaisesRegex(ValueError, 'candidate checkout'):
            gate.select(self.repo, paths, candidate='origin/main', sh=self.runner, load=load)
        self.assertEqual(len(loaded), 1)

    def test_select_lock_compares_explicit_base_candidate_blobs(self):
        write(self.repo / 'tools/queue/always.txt', 'always\n')
        before = lockfile([{'name': 'external', 'version': '1.0.0', 'source': 'registry+fixture'}])
        after = lockfile([{'name': 'external', 'version': '2.0.0', 'source': 'registry+fixture'}])
        write(self.repo / 'Cargo.lock', before)
        base = self.commit()
        write(self.repo / 'Cargo.lock', after)
        candidate = self.commit()
        write(self.repo / 'Cargo.lock', 'invalid uncommitted lock text')
        paths = gate.changed_paths(self.repo, candidate, base, sh=self.runner)
        self.assertEqual(paths, ['Cargo.lock'])
        self.assertEqual(gate.select(self.repo, paths, base=base, candidate=candidate,
                                     sh=self.runner, load=resolved_metadata), SelectionTest.closure)
        self.assertEqual(gate.select(self.repo, paths, base=candidate, candidate=candidate,
                                     sh=self.runner, load=resolved_metadata), {'always'})


if __name__ == '__main__':
    unittest.main()
