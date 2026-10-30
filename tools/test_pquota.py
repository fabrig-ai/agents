"""Quota boot proposal: temporary root, HOME and fake services; no sudo/host state."""

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


FAKE = r'''#!/usr/bin/python3
import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ['PQUOTA_FIXTURE'])
control = json.loads((root / 'control.json').read_text())
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with (root / 'calls.jsonl').open('a') as out: out.write(json.dumps([name, *args]) + '\n')
if name in control.get('fail', []): sys.exit(9)
if name == 'runuser':
    assert args[:5] == ['-u', 'free', '--', 'env', '-i']
    args = args[5:]
    while '=' in args[0]: args = args[1:]
    command = pathlib.Path(args.pop(0)).name
    if command == 'python3': print((root / 'heavy.json').read_text()); sys.exit(0)
    sys.exit(subprocess.call([str(root / 'bin' / command), *args]))
elif name == 'ssh':
    assert args[-1] == 'claim list'
    sys.exit(subprocess.call([str(root / 'bin/claim'), 'list']))
elif name == 'claim': print((root / 'claims.txt').read_text(), end='')
elif name == 'heavy':
    assert args == ['--installed']
    sys.exit(control.get('installed', 0))
elif name == 'findmnt': print(json.dumps({'filesystems': [control['mount']]}))
elif name == 'xfs_quota': print(control['quota'])
elif name == 'grub-editenv': print(control.get('grubenv', ''))
elif name == 'systemctl':
    if args == ['--user', 'is-active', 'fleet-sync.timer']: print(control.get('timer', 'active'))
    else: assert args == ['reboot']
elif name == 'update-grub':
    enabled = (root / 'etc/default/grub.d/90-fabrig-pquota.cfg').exists()
    flags = ' rootflags=pquota' if enabled and not control.get('bad_generated') else ''
    text = 'set default="0"\nmenuentry "Debian" {\n linux /vmlinuz root=/dev/sda1 ro' + flags + '\n}\n'
    text += 'menuentry "Recovery" {\n linux /vmlinuz rootflags=pquota\n}\n'
    (root / 'boot/grub/grub.cfg').write_text(text)
else: raise RuntimeError(name)
'''


class PquotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pquota-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.mod = load('pquota_fixture', ROOT / 'fleet/bootstrap/pquota')
        self.marker_uid = 0
        real_stat = os.stat
        def fake_stat(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if str(path) == str(self.root / 'var/lib/fabrig-pquota/fence'):
                fields = list(info)
                fields[4] = self.marker_uid
                return os.stat_result(fields)
            return info
        self.patch(self.mod.os, 'stat', side_effect=fake_stat)
        self.patch(self.mod.socket, 'gethostname', return_value='debian-16gb-hel1-7')
        self.patch(self.mod.pwd, 'getpwnam', return_value=argparse.Namespace(pw_uid=1234))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('runuser', 'ssh', 'claim', 'heavy', 'findmnt', 'xfs_quota', 'systemctl', 'update-grub', 'grub-editenv'):
            self.put('bin/' + name, FAKE, 0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin', HOME=str(self.home),
                        PQUOTA_FIXTURE=str(self.root), PYTHONDONTWRITEBYTECODE='1')
        self.tool = self.mod.Pquota('hetzner7', root=self.root, env=self.env)
        self.control = dict(mount=dict(target='/', source='/dev/sda1', fstype='xfs', options='rw,noquota'),
                            quota='Project quota state on / (/dev/sda1)\n  Accounting: OFF\n  Enforcement: OFF\n')
        self.controls()
        self.put('proc/cmdline', 'BOOT_IMAGE=/vmlinuz root=/dev/sda1 ro\n')
        self.put('proc/sys/kernel/random/boot_id', 'boot-before\n')
        self.put('etc/default/grub', 'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX=""\n')
        self.put('var/lib/fabrig-pquota/fence', 'hetzner7 ops: all producers stopped; drained REF\n', 0o600)
        self.put('claims.txt', 'hetzner7 1 [pool]: free\nhetzner3 1 [pool]: free\n')
        self.put('heavy.json', json.dumps(dict(version=1, installation=dict(boot='boot-before'), tasks={})))
        self.put('boot/grub/grub.cfg', 'set default="0"\nmenuentry "Debian" {\n linux /vmlinuz ro\n}\n'
                 'menuentry "Other" {\n linux /vmlinuz rootflags=pquota\n}\n')

    def patch(self, obj, name, **kwargs):
        mock = patch.object(obj, name, **kwargs)
        result = mock.start()
        self.addCleanup(mock.stop)
        return result

    def put(self, path, content, mode=0o644):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(mode)
        return path

    def controls(self, **changes):
        self.control.update(changes)
        self.put('control.json', json.dumps(self.control))

    def output(self, function):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = function()
        return result, stream.getvalue()

    def calls(self):
        path = self.root / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode, p.stat().st_ino)
                for p in self.root.rglob('*') if p.is_file() and p.name != 'calls.jsonl'}

    def prepare(self):
        self.output(self.tool.prepare)

    def test_plan_default_read_only_exact_proposal_and_fence_values(self):
        before = self.snapshot()
        _, output = self.output(self.tool.plan)
        self.assertIn(self.mod.CONTENT, output)
        self.assertIn('would run: update-grub', output)
        self.assertIn('noquota', output)
        self.assertIn('Accounting: OFF', output)
        self.assertIn('PASS fence central claims: []', output)
        self.assertIn('PASS fence heavy idle', output)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(c[0] == 'update-grub' or c == ['systemctl', 'reboot'] for c in self.calls()))
        with patch.object(self.mod.sys, 'argv', ['pquota', '--host', 'hetzner7']), \
                patch.object(self.mod.os, 'geteuid', return_value=0), \
                patch.object(self.mod, 'Pquota', return_value=self.tool):
            self.assertEqual(self.output(self.mod.main)[0], 0)

    def test_plan_unavailable_observations_are_not_idle(self):
        self.controls(fail=['findmnt', 'xfs_quota', 'ssh', 'heavy'])
        _, output = self.output(self.tool.plan)
        self.assertIn('UNAVAILABLE mount', output)
        self.assertIn('FAIL fence central claims', output)
        self.assertIn('FAIL fence heavy idle', output)

    def assert_refuses(self):
        before = self.snapshot()
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            self.tool.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(c[0] == 'update-grub' for c in self.calls()))

    def test_fence_refuses_host_mismatch(self):
        with patch.object(self.mod.socket, 'gethostname', return_value='hetzner6'):
            self.assert_refuses()

    def test_fence_refuses_non_xfs_and_failed_mount(self):
        for row in (dict(target='/', fstype='ext4', options='rw'), dict(target='/home', fstype='xfs', options='rw')):
            self.controls(mount=row)
            self.assert_refuses()
        self.controls(fail=['findmnt'])
        self.assert_refuses()

    def test_fence_refuses_missing_wrong_host_empty_reason_unsafe_owner_and_mode(self):
        marker = self.root / 'var/lib/fabrig-pquota/fence'
        marker.unlink()
        self.assert_refuses()
        for content in ('hetzner6 drained', 'hetzner7', '  '):
            self.put('var/lib/fabrig-pquota/fence', content, 0o600)
            self.assert_refuses()
        self.put('var/lib/fabrig-pquota/fence', 'hetzner7 drained', 0o666)
        self.assert_refuses()
        marker.chmod(0o600)
        self.marker_uid = 1000
        self.assert_refuses()

    def test_fence_refuses_claim_ssh_failure_empty_malformed_and_duplicate(self):
        self.controls(fail=['ssh'])
        self.assert_refuses()
        self.controls(fail=[])
        for text in ('', 'garbage\n', 'hetzner7 1 [pool]: strange\n',
                     'hetzner7 1 [pool]: free\nhetzner7 1 [pool]: free\n'):
            self.put('claims.txt', text)
            self.assert_refuses()

    def test_fence_refuses_host_claim_but_filters_other_hosts_exactly(self):
        held = 's/ops: build (since 2026-10-30T12:00:00+00:00); held 0d 00:01:00'
        self.put('claims.txt', f'hetzner7 1 [pool]: {held}\n')
        self.assert_refuses()
        self.put('claims.txt', f'hetzner70 1 [pool]: {held}\nhetzner3 1 [pool]: free\n')
        self.assertEqual(self.tool.claims(), [])

    def test_fence_refuses_every_unfinished_or_unknown_heavy_state(self):
        for state in ('queued', 'waiting', 'launching', 'active', 'disk-retry', 'finishing', 'closing', 'unknown'):
            self.put('heavy.json', json.dumps(dict(version=1, installation=dict(boot='b'), tasks={'x': {'state': state}})))
            self.assert_refuses()

    def test_fence_refuses_missing_broken_unsupported_heavy(self):
        for value in ('invalid', '{}', '{"version": 2}', '{"version":1,"tasks":{},"installation":null}',
                      '{"version":1,"tasks":{"x":{}},"installation":{"boot":"b"}}'):
            self.put('heavy.json', value)
            self.assert_refuses()
        self.controls(installed=1)
        self.assert_refuses()
        self.controls(fail=['runuser'])
        self.assert_refuses()

    def test_prepare_atomic_idempotent_records_original_and_never_reboots(self):
        original = self.tool.digest()
        self.prepare()
        path = self.root / self.mod.DROPIN.lstrip('/')
        state = self.tool.state()
        self.assertEqual(state['grub_before'], original)
        self.assertNotEqual(state['grub_after'], original)
        self.assertEqual(state['before_mount']['options'], 'rw,noquota')
        self.assertEqual(state['boot_id'], 'boot-before')
        self.assertEqual(path.read_text(), self.mod.CONTENT)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.root / self.mod.STATE.lstrip('/')).stat().st_mode & 0o777, 0o600)
        before = self.snapshot()
        calls = len([c for c in self.calls() if c[0] == 'update-grub'])
        self.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(calls, len([c for c in self.calls() if c[0] == 'update-grub']))
        self.assertNotIn(['systemctl', 'reboot'], self.calls())
        self.assertEqual(list(path.parent.glob('.90-fabrig*')), [])
        inode = path.stat().st_ino
        with patch.object(self.mod.os, 'replace', wraps=os.replace) as replace:
            self.tool.write(self.mod.DROPIN, self.mod.CONTENT + '# new\n', 0o644)
            self.assertEqual(replace.call_count, 1)
        self.assertNotEqual(inode, path.stat().st_ino)

    def test_prepare_failure_leaves_intent_and_refuses_reboot_then_rollback(self):
        for fail in (['update-grub'], []):
            self.controls(fail=fail, bad_generated=not fail)
            if self.tool.path(self.mod.STATE).exists():
                self.tool.path(self.mod.STATE).unlink()
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                self.tool.prepare()
            self.assertEqual(self.tool.state()['phase'], 'preparing')
            with self.assertRaises(ValueError): self.tool.reboot()
        self.controls(fail=[], bad_generated=False)
        self.output(self.tool.rollback)
        self.assertEqual(self.tool.state()['phase'], 'rolled-back')

    def test_foreign_dropin_and_symlink_are_refused(self):
        path = self.put(self.mod.DROPIN.lstrip('/'), '# foreign\n')
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()): self.tool.prepare()
        path.unlink()
        target = self.put('foreign', 'preserve')
        path.symlink_to(target)
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()): self.tool.prepare()
        self.assertEqual(target.read_text(), 'preserve')
        path.unlink()
        parent = path.parent
        parent.rmdir()
        outside = self.root / 'other-directory'
        outside.mkdir()
        parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()): self.tool.prepare()
        self.assertEqual(list(outside.iterdir()), [])

    def test_default_entry_not_stray_occurrence_and_unusual_defaults_refuse(self):
        with self.assertRaises(ValueError): self.tool.check_entry(True)
        self.tool.check_entry(False)
        for default in ('saved', '1>0', 'unknown'):
            self.put('etc/default/grub', f'GRUB_DEFAULT="{default}"\n')
            with self.assertRaises(ValueError): self.tool.default_entry()
        self.put('etc/default/grub', 'GRUB_DEFAULT=0\n')
        self.controls(grubenv='next_entry=1\n')
        with self.assertRaises(ValueError): self.tool.default_entry()
        self.controls(grubenv='')
        self.put('etc/default/grub.d/other.cfg', 'GRUB_DEFAULT=1\n')
        with self.assertRaises(ValueError): self.tool.default_entry()

    def test_rollback_removes_only_owned_dropin_records_and_is_idempotent(self):
        self.prepare()
        self.output(self.tool.rollback)
        self.assertFalse(self.tool.path(self.mod.DROPIN).exists())
        state = self.tool.state()
        self.assertEqual(state['phase'], 'rolled-back')
        self.assertEqual(state['boot_id'], 'boot-before')
        self.tool.check_entry(False)
        self.output(self.tool.rollback)
        self.assertNotIn(['systemctl', 'reboot'], self.calls())
        self.output(self.tool.reboot)
        self.assertIn(['systemctl', 'reboot'], self.calls())

    def test_rollback_fresh_bootstrap_without_state_or_available_fence(self):
        self.put(self.mod.DROPIN.lstrip('/'), self.mod.CONTENT)
        self.tool.path('/var/lib/fabrig-pquota/fence').unlink()
        self.controls(fail=['ssh', 'heavy'])
        self.output(self.tool.rollback)
        self.assertEqual(self.tool.state()['origin'], 'rollback-without-prepare')
        self.assertEqual(self.tool.state()['phase'], 'rolled-back')
        self.tool.check_entry(False)
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            self.tool.reboot()
        self.assertNotIn(['systemctl', 'reboot'], self.calls())

    def test_rollback_foreign_dropin_refuses(self):
        self.prepare()
        self.put(self.mod.DROPIN.lstrip('/'), '# foreign\n')
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()): self.tool.rollback()
        self.assertEqual(self.tool.path(self.mod.DROPIN).read_text(), '# foreign\n')

    def test_reboot_requires_yes_successful_preparation_unchanged_boot_and_grub(self):
        for command in ('prepare', 'rollback', 'reboot'):
            with patch.object(sys, 'argv', ['pquota', command, '--host', 'hetzner7']), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.mod.main()
            self.assertEqual(error.exception.code, 2)
        with self.assertRaises(FileNotFoundError): self.tool.reboot()
        self.prepare()
        self.put('proc/sys/kernel/random/boot_id', 'boot-after')
        with self.assertRaises(ValueError): self.tool.reboot()
        self.put('proc/sys/kernel/random/boot_id', 'boot-before')
        self.put('boot/grub/grub.cfg', '# changed')
        with self.assertRaises(ValueError): self.tool.reboot()
        self.assertNotIn(['systemctl', 'reboot'], self.calls())

    def test_reboot_immediately_rechecks_intact_fence(self):
        self.prepare()
        self.controls(fail=['ssh'])
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()): self.tool.reboot()
        self.assertNotIn(['systemctl', 'reboot'], self.calls())
        self.controls(fail=[])
        self.output(self.tool.reboot)
        calls = self.calls()
        self.assertEqual(calls[-1], ['systemctl', 'reboot'])
        self.assertTrue(any(c[0] == 'claim' for c in calls[-8:]))

    def healthy_boot(self):
        self.prepare()
        self.put('proc/sys/kernel/random/boot_id', 'boot-after\n')
        self.put('proc/cmdline', 'root=/dev/sda1 ro rootflags=pquota\n')
        self.control['mount']['options'] = 'rw,relatime,prjquota'
        self.controls(quota='User quota state on / (/dev/sda1)\n  Accounting: OFF\n  Enforcement: OFF\n'
                      'Project quota state on / (/dev/sda1)\n  Accounting: ON\n  Enforcement: ON\n  Inode: #131\n')

    def test_verify_boot_checks_pass_but_history_honestly_unproven_read_only(self):
        self.healthy_boot()
        before = self.snapshot()
        ok, output = self.output(self.tool.verify)
        self.assertFalse(ok)
        self.assertEqual(sum(line.startswith('PASS ') for line in output.splitlines()), 7, output)
        self.assertIn('FAIL no claims appeared during downtime: UNPROVEN', output)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(all(line.startswith(('PASS ', 'FAIL ')) for line in output.splitlines()))

    def test_verify_each_failed_boot_service_quota_claim_observation(self):
        self.healthy_boot()
        self.put('proc/cmdline', 'root=/dev/sda1 ro')
        self.put('proc/sys/kernel/random/boot_id', 'boot-before')
        self.controls(timer='inactive', quota='Project quota state on / (/dev/sda1)\n Accounting: OFF\n Enforcement: ON\n')
        self.control['mount']['options'] = 'rw,noquota'
        self.controls(installed=2)
        held = 's/qa: new work (since 2026-10-30T15:00:00+00:00); held 0d 00:00:00'
        self.put('claims.txt', f'hetzner7 1 [pool]: {held}\n')
        ok, output = self.output(self.tool.verify)
        self.assertFalse(ok)
        self.assertTrue(all(line.startswith('FAIL ') for line in output.splitlines()), output)
        self.assertIn('new work', output)

    def test_verify_project_section_cannot_borrow_user_enforcement(self):
        self.healthy_boot()
        self.controls(quota='User quota state on / (/dev/sda1)\n Accounting: ON\n Enforcement: ON\n'
                      'Project quota state on / (/dev/sda1)\n Accounting: ON\n Enforcement: OFF\n')
        _, output = self.output(self.tool.verify)
        self.assertIn('FAIL project accounting/enforcement ON', output)

    def test_bootstrap_flag_on_off_invalid_and_root_wrapper_share_bytes(self):
        module = load('bootstrap_pquota_fixture', ROOT / 'fleet/bootstrap/bootstrap.py')
        tool = module.Bootstrap(argparse.Namespace(dry_run=False, host='hetzner7'))
        writes, commands = [], []
        with patch.object(tool, 'write', side_effect=lambda *a: writes.append(a)), \
                patch.object(tool, 'run', side_effect=lambda *a: commands.append(a)), \
                contextlib.redirect_stdout(io.StringIO()):
            tool.pquota({})
            tool.pquota({'pquota': False})
            self.assertEqual((writes, commands), ([], []))
            tool.pquota({'pquota': True})
            self.assertEqual(writes, [(self.mod.DROPIN, self.mod.CONTENT)])
            self.assertEqual(commands, [('update-grub',)])
            with self.assertRaises(ValueError): tool.pquota({'pquota': 'true'})
        wrapper = (ROOT / 'fleet/bootstrap/root.sh').read_text()
        self.assertIn('bootstrap.py" root', wrapper)
        self.assertIn('self.pquota(host)', (ROOT / 'fleet/bootstrap/bootstrap.py').read_text())

    def test_root_bootstrap_wrapper_flag_on_off_dry_run_in_temporary_tree(self):
        source = self.root / 'source'
        shutil.copytree(ROOT / 'fleet/bootstrap', source / 'fleet/bootstrap')
        for flag in ('', 'pquota = false', 'pquota = true'):
            hosts = source / 'fleet/hosts.toml'
            hosts.write_text('[hosts.fixture]\nhostname = "fixture"\n' + flag + '\n')
            before = self.snapshot()
            result = subprocess.run(['/bin/bash', str(source / 'fleet/bootstrap/root.sh'),
                                     '--dry-run', '--host', 'fixture'],
                                    env=dict(self.env, PATH='/usr/bin:/bin'), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.mod.DROPIN in result.stdout, flag == 'pquota = true')
            self.assertEqual('$ update-grub' in result.stdout, flag == 'pquota = true')
            self.assertEqual(before, self.snapshot())

    def test_fleet_parser_accepts_boolean_flag_and_rejects_non_boolean(self):
        source = self.root / 'source'
        shutil.copytree(ROOT / 'fleet', source / 'fleet')
        shutil.copytree(ROOT / 'tools', source / 'tools')
        module = load('fleet_pquota_fixture', ROOT / 'tools/fleet-sync')
        module.SYSTEM_TOOL_DIRS = (self.root / 'fixture-system-bin',)
        hosts = source / 'fleet/hosts.toml'
        original = hosts.read_text()
        for flag in ('true', 'false', '"true"', '1'):
            hosts.write_text(original.replace('[hosts.hetzner7]', '[hosts.hetzner7]\npquota = ' + flag))
            if flag in ('true', 'false'):
                module.Declarations(source, self.home)
            else:
                with self.assertRaisesRegex(ValueError, 'pquota flag'):
                    module.Declarations(source, self.home)

    def test_quota_asset_requires_compatibility_parser_then_timer_promotes(self):
        fixture = load('fleet_quota_stage_fixture', ROOT / 'tools/test_fleet_sync.py')
        f = fixture.FleetTest(methodName='runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        asset = f.source / 'fleet/bootstrap/pquota'
        content = asset.read_bytes()
        asset.unlink()
        # The immediate predecessor lacks only this proposal's parser support.
        # Demonstrate that publishing the asset without compatibility refuses.
        parser = f.source / 'tools/fleet-sync'
        compatible = parser.read_text()
        predecessor = compatible.replace(', "bootstrap/pquota"', '')
        fixture.put(parser, predecessor, True)
        f.publish()
        f.sync('--host', 'hetzner7')
        previous = f.current()
        fixture.put(asset, content.decode(), True)
        fixture.put(parser, compatible, True)
        f.publish()
        failed = f.sync('--host', 'hetzner7', '--timer', script=previous / 'tools/fleet-sync', expected=1)
        self.assertEqual(f.current(), previous)
        self.assertTrue(failed['consecutive_failures'])
        # Publish code only and clear the fixture's backoff through its retry
        # control, then publish the asset with no parser change.
        asset.unlink()
        f.publish()
        fixture.put(f.home / '.config/fleet-sync/retry', 'fixture retry')
        f.sync('--host', 'hetzner7', '--timer', script=previous / 'tools/fleet-sync')
        compatible_release = f.current()
        fixture.put(asset, content.decode(), True)
        target = f.publish()
        result = f.sync('--host', 'hetzner7', '--timer', script=compatible_release / 'tools/fleet-sync')
        self.assertEqual(result['agents_sha'], target)
        self.assertEqual(result['consecutive_failures'], 0)


if __name__ == '__main__':
    unittest.main()
