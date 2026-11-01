"""Precheck receipts carried to and reused at the gate (docs/design/landing.md, 3)."""

import unittest
from unittest.mock import patch

from fab import atomic, log, receipts
from fab.hosts import Host
from fab.run import remote_home
from fab.sh import Result, ssh
from fab.tests.landing_checks import MAIN, TIP, kept, receipt, receipt_hosts, receipt_text
from fab.tests.support import FakeRunner, run_started, tmp_home


class ReceiptTest(unittest.TestCase):
    def test_parse_keeps_every_key_and_accepts_precheck_selections(self):
        for selection in ('full', 'docs', ['pkg'], []):
            value = receipt(selection=selection)
            self.assertEqual(receipts.parse(receipt_text(value), TIP), value)
        value = receipt(tip='a' * 64, main='b' * 64, outcome='conflict') | {'steps': ['unsplit']}
        self.assertEqual(receipts.parse(receipt_text(value), value['tip']), value)

    def test_parse_refuses_each_invalid_field(self):
        failures = {'tip': (MAIN, 'short', None, 'A' * 40),
                    'main': ('short', 1, None),
                    'outcome': ('unknown', None, []),
                    'selection': (1, None, 'pkg', [1]),
                    'steps': (1, None, 'fmt:0:1', [1])}
        for field, values in failures.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                    receipts.parse(receipt_text(receipt() | {field: value}), TIP)
            value = receipt()
            del value[field]
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, field):
                receipts.parse(receipt_text(value), TIP)

    def test_parse_requires_json_object(self):
        for text in ('{torn', '[]', 'null', '1', '"text"'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                receipts.parse(text, TIP)

    def test_reusable_requires_green_and_both_commits(self):
        self.assertTrue(receipts.reusable(receipt(), TIP, MAIN))
        for value in (None, receipt(outcome='red'), receipt(outcome='conflict'),
                      receipt(main=TIP), receipt(tip=MAIN)):
            with self.subTest(receipt=value):
                self.assertFalse(receipts.reusable(value, TIP, MAIN))

    def test_covers_step_and_binary_package(self):
        for binary in ('pkg', 'pkg::wire'):
            self.assertTrue(receipts.covers(receipt(), 'default', binary))
        self.assertTrue(receipts.covers(receipt(selection='full'), 'fuzzy', 'other::wire'))
        for value, step, binary in ((receipt(), 'default', 'other'),
                                    (receipt(), 'missing', 'pkg'),
                                    (receipt(selection='docs'), 'default', 'pkg'),
                                    (receipt(outcome='red'), 'default', 'pkg'),
                                    (None, 'default', 'pkg'),
                                    (receipt() | {'steps': ['malformed']}, 'malformed', 'pkg')):
            with self.subTest(receipt=value, step=step, binary=binary):
                self.assertFalse(receipts.covers(value, step, binary))
        self.assertTrue(receipts.covers(receipt(steps=['ratchet:pkg']), 'ratchet:pkg', 'pkg'))

    def test_builder_uses_latest_eligible_run_in_event_order(self):
        hosts = receipt_hosts() | {'new': Host('new', 'fab@new', ('builder',))}
        for kind in ('implement', 'repair', 'rebase'):
            events = [run_started('draft/task'), run_started('draft/task', 2, kind=kind, host='new'),
                      run_started('draft/other', host='builder'),
                      run_started('draft/task', 3, kind='review', host='builder'),
                      run_started('draft/task', 4, kind='foreman', host='builder'),
                      run_started('draft/task/foreman', host='builder')]
            self.assertEqual(receipts.builder('draft/task', iter(events), hosts), hosts['new'])

    def test_builder_does_not_fall_back_from_missing_or_non_builder_host(self):
        hosts = receipt_hosts()
        for host in ('missing', 'a-gate'):
            events = [run_started('draft/task'), run_started('draft/task', 2, host=host)]
            self.assertIsNone(receipts.builder('draft/task', events, hosts))
        self.assertIsNone(receipts.builder('draft/task', [], hosts))
        self.assertIsNone(receipts.builder('draft/task', [run_started('draft/task', kind='review')], hosts))


class StorageTest(unittest.TestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__() / 'fab'
        self.addCleanup(context.__exit__, None, None, None)

    def test_path_is_confined_to_receipts_and_accepts_full_sha_lengths(self):
        for tip in (TIP, 'a' * 64):
            self.assertEqual(receipts.path(self.home, tip), self.home / 'receipts' / f'{tip}.json')
        for tip in ('short', 'A' * 40, '../x'):
            with self.subTest(tip=tip), self.assertRaises(ValueError):
                receipts.path(self.home, tip)

    def test_store_keeps_text_and_replaces_previous_receipt(self):
        text = receipt_text(receipt())
        destination = receipts.store(self.home, TIP, text)
        self.assertEqual(destination, receipts.path(self.home, TIP))
        self.assertEqual(destination.read_text(), text)
        self.assertEqual(receipts.load(self.home, TIP), receipt())
        value = receipt(selection='full')
        self.assertEqual(receipts.store(self.home, TIP, receipt_text(value)), destination)
        self.assertEqual(receipts.load(self.home, TIP), value)
        self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_refused_store_writes_nothing_and_preserves_existing_receipt(self):
        with self.assertRaisesRegex(ValueError, 'tip'):
            receipts.store(self.home, TIP, receipt_text(receipt(tip=MAIN)))
        self.assertFalse(self.home.exists())
        destination = kept(self.home, receipt())
        before = destination.read_text()
        with self.assertRaises(ValueError):
            receipts.store(self.home, TIP, '{torn')
        self.assertEqual(destination.read_text(), before)

    def test_load_ignores_missing_unreadable_and_invalid_receipts(self):
        self.assertIsNone(receipts.load(self.home, TIP))
        self.assertIsNone(receipts.load(self.home, '../x'))
        destination = kept(self.home, receipt())
        for text in ('{torn', receipt_text(receipt(tip=MAIN))):
            atomic.write(destination, text)
            self.assertIsNone(receipts.load(self.home, TIP))
        for error in (OSError('unreadable'), UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid')):
            with patch('pathlib.Path.read_text', side_effect=error):
                self.assertIsNone(receipts.load(self.home, TIP))


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__() / 'fab'
        self.addCleanup(context.__exit__, None, None, None)
        self.log_path = self.home / 'events.jsonl'
        self.hosts = receipt_hosts()
        self.events = [run_started('draft/task')]
        self.text = receipt_text(receipt())
        host = self.hosts['builder']
        self.cat = ssh(host.ssh, ['cat', f'{remote_home(host)}/precheck/{TIP}.json'])
        self.accept = ssh(self.hosts['a-gate'].ssh, ['fab', 'queue', 'receipt', TIP])

    def test_deliver_reads_remote_home_then_sends_exact_text_to_first_gate(self):
        fake = FakeRunner().on(self.cat, Result(0, self.text))
        self.assertTrue(receipts.deliver('draft/task', TIP, self.events, self.hosts,
                                        sh=fake, log_path=self.log_path))
        self.assertEqual(fake.argvs(), [self.cat, self.accept])
        self.assertEqual([call.input for call in fake.calls], [None, self.text])
        self.assertEqual(log.read(self.log_path), [])

    def test_deliver_without_builder_runs_nothing(self):
        fake = FakeRunner()
        self.assertFalse(receipts.deliver('draft/task', TIP, [], self.hosts,
                                         sh=fake, log_path=self.log_path))
        self.assertEqual(fake.calls, [])
        self.assertEqual(log.read(self.log_path), [])

    def test_cat_failure_and_non_green_receipts_have_no_note(self):
        for result in (Result(1, err='missing'), Result(0, receipt_text(receipt(outcome='red'))),
                       Result(0, receipt_text(receipt(outcome='conflict')))):
            with self.subTest(result=result):
                fake = FakeRunner().on(self.cat, result)
                self.assertFalse(receipts.deliver('draft/task', TIP, self.events, self.hosts,
                                                 sh=fake, log_path=self.log_path))
                self.assertEqual(fake.argvs(), [self.cat])
                self.assertEqual(log.read(self.log_path), [])

    def test_deliver_notes_parse_error(self):
        fake = FakeRunner().on(self.cat, Result(0, receipt_text(receipt(main='short'))))
        self.assertFalse(receipts.deliver('draft/task', TIP, self.events, self.hosts,
                                         sh=fake, log_path=self.log_path))
        self.assertEqual(fake.argvs(), [self.cat])
        note, = log.read(self.log_path)
        self.assertEqual((note['ev'], note['text']),
                         ('note', 'receipt draft/task: main must be a full lowercase SHA'))

    def test_deliver_notes_missing_gate(self):
        fake = FakeRunner().on(self.cat, Result(0, self.text))
        self.assertFalse(receipts.deliver('draft/task', TIP, self.events,
                                         {'builder': self.hosts['builder']},
                                         sh=fake, log_path=self.log_path))
        self.assertEqual(fake.argvs(), [self.cat])
        self.assertEqual(log.read(self.log_path)[0]['text'], 'receipt draft/task: no gate host')

    def test_deliver_notes_refusing_gate_last_error_line_or_output(self):
        for result, last in ((Result(1, 'out', 'first\nlast error\n'), 'last error'),
                             (Result(1, 'first\nlast output\n'), 'last output'),
                             (Result(1), '')):
            with self.subTest(result=result):
                fake = FakeRunner().on(self.cat, Result(0, self.text)).on(self.accept, result)
                self.assertFalse(receipts.deliver('draft/task', TIP, self.events, self.hosts,
                                                 sh=fake, log_path=self.log_path))
                self.assertEqual(fake.argvs(), [self.cat, self.accept])
                self.assertEqual(log.read(self.log_path)[-1]['text'], f'receipt draft/task: gate: {last}')


if __name__ == '__main__':
    unittest.main()
