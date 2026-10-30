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
import errno, hashlib, json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ['PQUOTA_FIXTURE'])
control = json.loads((root / 'control.json').read_text())
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with pathlib.Path(os.environ.get('PQUOTA_CALLS_FILE', root / 'calls.jsonl')).open('a') as out: out.write(json.dumps([name, *args]) + '\n')
if name in control.get('fail', []): sys.exit(9)
if name == 'runuser':
    assert args[:5] == ['-u', 'free', '--', 'env', '-i']
    args = args[5:]
    while '=' in args[0]: args = args[1:]
    command = pathlib.Path(args.pop(0)).name
    if command == 'python3':
        source = args[args.index('-c') + 1]
        if "src/rust/tmp/heavy/state.json" in source: print((root / 'heavy.json').read_text())
        elif 'fabrig_head=' in source:
            if control.get('source_error'): sys.exit(8)
            print(json.dumps(control['sources']))
        elif 'keys = set(json.loads' in source:
            if control.get('env_error'): sys.exit(8)
            print(json.dumps(control['machine']))
        elif 'pquota-heavy-submitters-v2' in source: print(json.dumps(control.get('submitters', [])))
        elif 'expected explicit regular .md' in source: print(pathlib.Path(args[-1]).read_text(), end='')
        else: raise RuntimeError(source)
        sys.exit(0)
    sys.exit(subprocess.call([str(root / 'bin' / command), *args]))
elif name == 'ssh':
    declaration = (root / 'inventory.txt').read_text()
    print(json.dumps(dict(path='/central/tools/slots/hosts', declaration=declaration,
        digest=hashlib.sha256(declaration.encode()).hexdigest(), listing=(root / 'claims.txt').read_text())))
elif name == 'heavy':
    assert args == ['--installed']
    sys.exit(control.get('installed', 0))
elif name == 'uname': print(control.get('kernel', 'fixture'))
elif name == 'blkid':
    if control.get('cache_probe') and not ('-c' in args and args[args.index('-c')+1] == '/dev/null' and '-p' in args):
        (root / 'run/blkid/blkid.tab').write_text('cache write')
    spec = args[-1]
    if '-U' in args:
        if spec != '11111111-1111-1111-1111-111111111111': sys.exit(2)
        print('/dev/sda1'); sys.exit(0)
    identities = control.get('identities', {'/dev/sda1': '11111111-1111-1111-1111-111111111111', '/dev/sdb1': '22222222-2222-2222-2222-222222222222', 'UUID=11111111-1111-1111-1111-111111111111': '11111111-1111-1111-1111-111111111111', '/dev/disk/by-uuid/11111111-1111-1111-1111-111111111111': '11111111-1111-1111-1111-111111111111'})
    if spec not in identities: sys.exit(2)
    print(identities[spec])
elif name == 'findmnt': print(json.dumps({'filesystems': [control['mount']]}))
elif name == 'xfs_quota':
    command = args[args.index('-c') + 1]
    if command == 'state': print(control['quota'])
    elif command == 'report -p -n -b': print('Project quota on / (/dev/sda1)\n Used Soft Hard\n#0 1 0 0')
    else:
        phase = 'setup' if command.startswith('project -s') else 'clear' if command.startswith('project -C') else 'uncap' if 'bhard=0 ' in command else 'cap'
        if control.get('probe_fail') == phase: sys.exit(8)
        if phase == 'setup': (root / 'project.json').write_text(json.dumps(int(command.split()[-1])))
elif name == 'python3':
    directory = pathlib.Path(args[-3])
    (directory / 'child').mkdir()
    (directory / 'child/payload').write_bytes(b'fixture')
    print(json.dumps(dict(errno=control.get('write_errno', errno.EDQUOT), bytes=control.get('written', 983040))))
elif name == 'grub-editenv': print(control.get('grubenv', ''))
elif name == 'systemctl':
    options, operands, terminated = [], [], False
    for arg in args:
        if arg == '--' and not terminated:
            terminated = True
        elif not terminated and arg.startswith('-'):
            if arg not in ('--user', '--all', '--no-pager', '--now') and not arg.startswith(('--output=', '--type=', '--property=')):
                print('systemctl: unrecognized option ' + arg, file=sys.stderr)
                sys.exit(2)
            options.append(arg)
        else:
            operands.append(arg)
    action, *units = operands
    if action == 'is-active':
        assert units == ['fleet-sync.timer']
        print(control.get('timer', 'active'))
    elif action == 'is-enabled':
        assert len(units) == 1
        value = control.get('enablement', {}).get(units[0], 'disabled')
        print(value); sys.exit(0 if value == 'enabled' else 1)
    elif action == 'list-unit-files':
        assert not units
        print(json.dumps(control.get('unit_files', [])))
    elif action == 'list-units':
        assert not units
        print(json.dumps(control.get('units', [])))
    elif action == 'show':
        assert len(units) == 1
        unit = units[0]
        graph_keys = ('WantedBy', 'RequiredBy', 'Requires', 'Wants', 'BindsTo', 'BoundBy', 'PartOf', 'ConsistsOf', 'Upholds', 'UpheldBy', 'Triggers', 'TriggeredBy', 'OnSuccess', 'OnFailure', 'OnSuccessOf', 'OnFailureOf')
        if unit == control.get('graph_error'): sys.exit(8)
        if unit in control.get('unit_properties', {}):
            output = control['unit_properties'][unit]
            values = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        else:
            state = control.get('unit_states', {}).get(unit, 'inactive')
            values = dict(LoadState='loaded', ActiveState=state, SubState='running' if state == 'active' else 'dead',
                          UnitFileState=control.get('enablement', {}).get(unit, 'disabled'))
        if unit != control.get('graph_incomplete'):
            for key in graph_keys: values.setdefault(key, '')
            values.setdefault('OnSuccessJobMode', 'replace')
            values.setdefault('OnFailureJobMode', 'replace')
        properties = [arg.partition('=')[2] for arg in options if arg.startswith('--property=')]
        requested = set(','.join(properties).split(',')) if properties else set(values)
        for key, value in values.items():
            if key in requested: print(key + '=' + value)
    else:
        assert action == 'reboot' and not units
elif name == 'update-grub':
    enabled = (root / 'etc/default/grub.d/90-fabrig-pquota.cfg').exists()
    flags = ' rootflags=pquota' if enabled and not control.get('bad_generated') else ''
    extra = ' bad=changed' if control.get('changed_options') else ''
    text = 'set default="0"\nmenuentry "Debian" {\n linux ' + control.get('generated_kernel', '/vmlinuz-fixture') + ' root=' + control.get('generated_root', '/dev/sda1') + ' ro console=ttyS0' + flags + extra + '\n}\n'
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
        self.patch(self.mod.pwd, 'getpwnam', return_value=argparse.Namespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('runuser', 'ssh', 'heavy', 'findmnt', 'xfs_quota', 'python3', 'systemctl', 'update-grub', 'grub-editenv', 'blkid', 'uname'):
            self.put('bin/' + name, FAKE, 0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin', HOME=str(self.home),
                        PQUOTA_FIXTURE=str(self.root), PYTHONDONTWRITEBYTECODE='1')
        self.control = dict(mount=dict(target='/', source='/dev/sda1', fstype='xfs', options='rw,noquota'),
            quota='Project quota state on / (/dev/sda1)\n  Accounting: OFF\n  Enforcement: OFF\n',
            sources=dict(fabrig_head='a' * 40, agents_current='/fixture/agents-release',
                heavy_path='/fixture/heavy', heavy_digests={str(n): 'b' * 64 for n in range(6)},
                start_once_units={'after-landing.service': 'd' * 64, 'qa-watch.service': 'e' * 64}),
            machine=dict(PLAN_MIN_DISK_GB='40', HEAVY_BUILD_SLOTS='3'),
            unit_states={'after-landing.service': 'inactive', 'qa-watch.service': 'active'})
        self.controls()
        self.put('proc/cmdline', 'root=/dev/sda1 ro console=ttyS0\n')
        self.put('proc/sys/kernel/random/boot_id', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\n')
        self.put('etc/default/grub', 'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX=""\nGRUB_CMDLINE_LINUX_DEFAULT="console=ttyS0"\n')
        self.put('etc/fstab', '/dev/sda1 / xfs defaults,noatime 0 1\n')
        self.put('boot/grub/grubenv', 'original environment\n')
        self.put('var/lib/fabrig-pquota/fence', 'hetzner7 ops: all producers stopped; drained REF\n', 0o600)
        self.put('inventory.txt', 'hetzner7 1=pool 4=pool\nhetzner3 1=pool\n')
        self.put('claims.txt', self.held('1') + self.held('4') + 'hetzner3 1 [pool]: free\n')
        self.put('heavy.json', json.dumps(dict(version=1, installation=dict(boot='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'), tasks={})))
        self.put('boot/grub/grub.cfg', 'set default="0"\nmenuentry "Debian" {\n linux /vmlinuz-fixture root=/dev/sda1 ro console=ttyS0\n}\n')
        self.policy = dict(inventory_digest=self.digest_inventory(), maintenance_owner='ops',
            maintenance_what='pquota maintenance REF', retained_claims=[], approval_files={}, retained_services={})
        self.tool = self.mod.Pquota('hetzner7', root=self.root, env=self.env, policy=self.policy)
        def attrs(path):
            project = json.loads((self.root / 'project.json').read_text())
            return dict(project=project, inherit=not self.control.get('bad_inherit', False))
        self.patch(self.tool, 'project_attrs', side_effect=attrs)

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

    def digest_inventory(self):
        return self.mod.hashlib.sha256((self.root / 'inventory.txt').read_bytes()).hexdigest()

    def held(self, slot, owner='ops', what='pquota maintenance REF', created='2026-10-30T12:00:00+00:00'):
        return f'hetzner7 {slot} [pool]: {owner}: {what} (since {created}); held 0d 00:01:00\n'

    def retained(self):
        self.put('claims.txt', self.held('1') + self.held('4', 'ops', 'after-landing 20261029T1846Z') + 'hetzner3 1 [pool]: free\n')
        post = self.put('approval.md', 'Id: POST-123\nFrom: s/dynamic-memory@hel8\nTo: ops@hel8\n\n'
            'slot: hetzner7:4\nwhat: after-landing 20261029T1846Z\n'
            'service: after-landing.service\nplan: preserve state and restart once by owner\n')
        self.policy['retained_claims'] = [dict(slot='4', owner='ops', approver='s/dynamic-memory', post='POST-123')]
        self.policy['approval_files'] = {'POST-123': str(post)}
        self.policy['retained_services'] = {'4': 'after-landing.service'}
        return post

    def prepare(self):
        self.output(self.tool.prepare)

    def assert_refuses(self, function=None):
        before = len([r for r in self.calls() if r[0] == 'update-grub' or r == ['systemctl', 'reboot', '--']])
        with self.assertRaises((ValueError, OSError)), contextlib.redirect_stdout(io.StringIO()):
            (function or self.tool.prepare)()
        self.assertEqual(before, len([r for r in self.calls() if r[0] == 'update-grub' or r == ['systemctl', 'reboot', '--']]))

    def handler_reboot_fixture(self, property):
        self.retained()
        self.prepare()
        self.controls(unit_files=[{'unit_file': 'boot-oneshot.service', 'state': 'enabled'}],
            enablement={'boot-oneshot.service': 'enabled'}, unit_properties={'boot-oneshot.service':
                'LoadState=loaded\nActiveState=inactive\nSubState=dead\nUnitFileState=enabled\n' + property + '=after-landing.service\n'})
        self.assert_refuses(self.tool.reboot)

    def healthy_boot(self):
        self.prepare()
        self.put('proc/sys/kernel/random/boot_id', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb\n')
        self.put('proc/cmdline', 'root=/dev/sda1 ro console=ttyS0 rootflags=pquota\n')
        self.control['mount']['options'] = 'rw,prjquota'
        self.controls(quota='Project quota state on / (/dev/sda1)\n Accounting: ON\n Enforcement: ON\n')

    def test_project_attrs_checks_kernel_project_and_inheritance_bits(self):
        directory = self.root / 'attrs'
        directory.mkdir()
        with patch.object(self.mod.fcntl, 'ioctl', return_value=self.mod.struct.pack('=5I8s',0x200,0,0,123,0,bytes(8))):
            self.assertEqual(self.mod.Pquota.project_attrs(self.tool,directory), dict(project=123, inherit=True))

    def test_submitter_status_reads_only_executable_and_action_never_payloads(self):
        prefixes = {
            '501': b'/usr/bin/python3\0-B\0/tool/heavy-recovery.py\0--task\0',
            '502': b'/usr/bin/python3\0/other/script.py\0',
            '503': b'/usr/bin/python3\0-c\0',
            '504': b'/usr/bin/python3\0-B\0/tool/heavy-recovery.py\0--reconcile\0',
        }
        class Guarded(io.BytesIO):
            def __init__(self, prefix):
                super().__init__(prefix + b'PRIVATE PAYLOAD MUST NEVER BE READ\0')
                self.boundary = len(prefix)
            def read(self, size=-1):
                if size != 1 or self.tell() >= self.boundary:
                    raise AssertionError('read crossed into private payload')
                return super().read(size)
        def open_metadata(path, *args, **kwargs):
            self.assertEqual(args, ('rb',))
            return Guarded(prefixes[path.parent.name])
        stream = io.StringIO()
        with patch.object(self.mod.subprocess, 'check_output', return_value='501 python3\n502 python3\n503 python3\n504 python3\n505 heavy\n'), \
                patch.object(Path, 'open', open_metadata), contextlib.redirect_stdout(stream):
            exec(self.mod.SUBMITTERS, {})
        self.assertEqual([row['pid'] for row in json.loads(stream.getvalue())], [501, 505])
        self.assertNotIn('PRIVATE', stream.getvalue())

    def test_environment_helper_only_returns_allowlisted_nonsecret_keys(self):
        path = self.home / 'src/rust/tmp/machine.env'
        path.parent.mkdir(parents=True)
        path.write_text('PLAN_MIN_DISK_GB=40\nPRIVATE_TOKEN=private fixture must never appear\n')
        result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c', self.mod.MACHINE_ENV,
                                 json.dumps(sorted(self.mod.MACHINE_KEYS))],
                                env=dict(self.env, HOME=str(self.home)), text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {'PLAN_MIN_DISK_GB': '40'})
        self.assertNotIn('private fixture', result.stdout + result.stderr)

    def test_bootstrap_flag_on_off_invalid_and_root_wrapper_share_bytes(self):
        module = load('bootstrap_pquota_fixture', ROOT / 'fleet/bootstrap/bootstrap.py')
        tool = module.Bootstrap(argparse.Namespace(dry_run=False, host='hetzner7'))
        writes, commands = [], []
        guard = unittest.mock.Mock()
        guard.bootstrap_begin.return_value = {'default_before': '/vmlinuz root=/dev/sda1 ro'}
        guard.check_entry.return_value = '/vmlinuz root=/dev/sda1 ro rootflags=pquota'
        with patch.object(module.runpy, 'run_path', return_value={'Pquota': lambda host: guard}), \
                patch.object(tool, 'write', side_effect=lambda *a: writes.append(a)), \
                patch.object(tool, 'run', side_effect=lambda *a: commands.append(a)), \
                contextlib.redirect_stdout(io.StringIO()):
            tool.pquota({})
            tool.pquota({'pquota': False})
            self.assertEqual((writes, commands), ([], []))
            tool.pquota({'pquota': True})
            self.assertEqual(writes, [(self.mod.DROPIN, self.mod.CONTENT)])
            self.assertEqual(commands, [('update-grub',)])
            with self.assertRaises(ValueError): tool.pquota({'pquota': 'true'})
            writes.clear()
            commands.clear()
            guard.bootstrap_begin.side_effect = ValueError('rootflags conflict')
            with self.assertRaises(ValueError): tool.pquota({'pquota': True})
            self.assertEqual((writes, commands), ([], []))
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
