"""Disposable git remotes, central claims and fake SSH; no live services."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent


def put(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + '.new')
    sibling.write_text(text)
    sibling.chmod(0o755 if executable else 0o644)
    sibling.replace(path)


SSH = r'''#!/usr/bin/env python3
import json,os,shlex,subprocess,sys,time
from pathlib import Path
home=Path.home()
target,command=sys.argv[-2:]
args=shlex.split(command)
action=args[5] if args[:4]==['python3','-I','-B','-c'] else None
logged=['remote',action] if action else args
with (home/'ssh.log').open('a') as log: log.write(json.dumps([target,logged])+'\n')
if target=='central':
 state=home/'claim.json'
 if args[1]=='list':
  held=json.loads(state.read_text())[:2] if state.exists() else None
  print('\n'.join(' '.join(pair) for pair in [('hetzner7','4'),('hetzner3','1')] if list(pair)!=held))
 elif args[1]=='claim':
  if state.exists(): sys.exit(1)
  state.write_text(json.dumps(args[2:]))
  if os.environ.get('LOST_CLAIM_REPLY'): sys.exit(255)
 elif args[1]=='release':
  data=json.loads(state.read_text())
  assert data[:3]==args[2:5] and data[3]==args[6], (data,args)
  state.unlink()
  if os.environ.get('LOSE_RELEASE_REPLY'): sys.exit(255)
 else: sys.exit(2)
else:
 if action=='prepare' and os.environ.get('BAD_TEMP'):
  print(json.dumps(dict(remote_dir='/tmp/agents-gate.x/../outside')))
  sys.exit(0)
 if action=='cleanup' and os.environ.get('DROP_CLEANUP'): sys.exit(255)
 if action=='wait' and os.environ.get('DROP_WAIT'):
  deadline=time.monotonic()+5
  while not (home/'ready').exists() and time.monotonic()<deadline: time.sleep(.01)
  sys.exit(255)
 if action=='prepare':
  result=subprocess.check_output(args,text=True)
  (home/'remote').write_text(json.loads(result)['remote_dir'])
  print(result)
 else:
  result=subprocess.run(args,capture_output=True)
  sys.stdout.buffer.write(result.stdout)
  sys.stderr.buffer.write(result.stderr)
  sys.exit(result.returncode)
'''

CHECK = r'''#!/usr/bin/env python3
import json,os,subprocess,sys,time
from pathlib import Path
home=Path.home()
count=home/'gates'
n=int(count.read_text())+1 if count.exists() else 1
count.write_text(str(n))
if os.environ.get('WAIT_GATE'):
 (home/'ready').write_text(str(os.getpid()))
 while not (home/'end-gate').exists(): time.sleep(0.01)
if os.environ.get('RACE_PATH') and (n==1 or os.environ.get('SECOND_RACE')):
 other=home/'upstream'
 path=other/os.environ['RACE_PATH']
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(str(n))
 for args in (['add','.'],['commit','-qm','race'],['push','origin','main']):
  subprocess.run(['git','-C',str(other),*args],check=True)
if os.environ.get('BUG_HEAVY'):
 (home/'src/rust/tmp/heavy/state.json').write_text(json.dumps(dict(version=1,tasks={'fixture':dict(repo='/fixture-outside-gate',label=os.environ['HEAVY_LABEL'],state='queued')})))
report=Path(sys.argv[sys.argv.index('--json')+1])
report.write_text(json.dumps(dict(code=int(bool(os.environ.get('FAIL_GATE'))),files=[],starved=0)))
print('FILE OWNER CPU_s WALL_s BUDGET_s STATUS\nfixture lead/test 0.1 0.2 8 ok')
sys.exit(int(bool(os.environ.get('FAIL_GATE'))))
'''


class LandFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='land-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        put(self.home/'src/rust/tmp/heavy/state.json',json.dumps(dict(version=1,tasks={})))
        self.addCleanup(self.drain_fixture)
        self.env = {k: v for k,v in os.environ.items() if not k.startswith('AGENTS_GATE_')}
        self.env.update(HOME=str(self.home), PATH=str(self.bin)+':'+os.environ['PATH'],
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                        DEV_ROOT=str(self.home/'src/rust'), DEV_TMP=str(self.home/'src/rust/tmp'),
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        put(self.bin / 'ssh', SSH, True)
        for name in ('land', 'gate.py', 'land_remote.py'):
            put(self.source / 'tools' / name, (ROOT/'tools'/name).read_text(), True)
        put(self.source / 'tools/check.sh', CHECK, True)
        put(self.source / 'tools/gate.toml', '[budget]\nenforce = false\n[select]\n"a/**" = ["tools/a/test_a.py"]\n"b/**" = ["tools/b/test_b.py"]\n')
        for name in ('a','b'):
            put(self.source / f'tools/{name}/test_{name}.py', '')
        put(self.source / 'fleet/hosts.toml', '[hosts.hel8]\nssh="central"\nroles=["session"]\n[hosts.hetzner7]\nssh="builder"\nroles=["builder"]\n[hosts.hetzner3]\nssh="builder"\nroles=["builder"]\n')
        self.inventory = self.root / 'hosts'
        put(self.inventory, 'hetzner7 4=pool\nhetzner3 1=pool\n')
        self.git('init', '-b', 'main')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.origin = self.root / 'origin.git'
        self.command('git', 'clone', '--bare', self.source, self.origin)
        self.git('remote', 'add', 'origin', self.origin)
        self.command('git','clone',self.origin,self.home/'upstream')
        self.git('switch', '-c', 'feature')
        put(self.source / 'a/change', 'feature')
        self.git('add', '.')
        self.git('commit', '-qm', 'feature')
        self.original = self.tip()

    def drain_fixture(self):
        # Explicit --kill is permitted only for this fixture's recorded children.
        for path in (self.home/'.local/state/agents-gate/unreconciled').glob('*.json'):
            subprocess.run(['python3','-I','-B','tools/land','--reconcile',path.stem,'--kill'],
                           cwd=self.source,env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)

    def records(self):
        return list((self.home/'.local/state/agents-gate/unreconciled').glob('*.json'))

    def assert_kept(self):
        self.assertTrue((self.home/'claim.json').exists())
        self.assertEqual(len(self.records()),1)
        self.assertFalse(any(a[:2]==['claim','release'] for a in self.calls()))
        row=json.loads(self.records()[0].read_text())
        self.assertEqual(row['owner'],'s/deploy-gate')
        self.assertEqual(row['what'],json.loads((self.home/'claim.json').read_text())[3])
        return row

    def command(self, *args, expected=0):
        result = subprocess.run(list(map(str,args)), cwd=self.source, env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.last_result = result
        self.assertEqual(result.returncode, expected, result.stdout+result.stderr)
        return result.stdout.strip()

    def git(self, *args):
        return self.command('git', *args)

    def tip(self):
        return self.command('git','--git-dir',self.origin,'rev-parse','main')

    def land(self, *args, expected=0):
        return self.command('python3','-I','-B','tools/land','--inventory',self.inventory,
                            *args, expected=expected)

    def calls(self):
        return [json.loads(line)[1] for line in (self.home/'ssh.log').read_text().splitlines()]

    def assert_released(self):
        self.assertFalse((self.home/'claim.json').exists())
        claims=[args for args in self.calls() if args[:2]==['claim','claim']]
        releases=[args for args in self.calls() if args[:2]==['claim','release']]
        self.assertEqual(len(claims),1)
        self.assertEqual(len(releases),1)
        self.assertEqual(claims[0][2:5], releases[0][2:5])
        self.assertEqual(claims[0][5],releases[0][6])
        if (self.home/'remote').exists():
            self.assertFalse(Path((self.home/'remote').read_text()).exists())


class LandTests(LandFixture):
    def test_bundle_claim_release_and_push(self):
        self.git('push','origin','HEAD:feature')
        output=self.land('--host','hetzner7')
        self.assertEqual(self.git('ls-remote','--heads','origin','refs/heads/feature'),'')
        self.assertEqual(self.tip(),self.git('rev-parse','HEAD'))
        self.assertEqual(self.git('branch','--show-current'),'')
        self.assertNotIn('feature',self.git('branch','--format=%(refname:short)'))
        self.assertIn('shipped HEAD bundle',output)
        self.assertIn('merge wall',output)
        self.assert_released()
        self.assertTrue(any(a[:2]==['sh','-c'] and 'candidate.bundle' in a[2] for a in self.calls()))

    def test_dry_run_auto_builder(self):
        output=self.land('--dry-run')
        self.assertIn('claimed hetzner3 slot 1',output)
        self.assertIn('stopping before push',output)
        self.assertEqual(self.tip(),self.original)
        self.assert_released()

    def test_failure_releases_and_never_pushes(self):
        self.env['FAIL_GATE']='1'
        self.land('--host','hetzner7',expected=1)
        self.assertEqual(self.tip(),self.original)
        self.assert_released()

    def test_lost_claim_reply_keeps_exact_intent(self):
        self.env['LOST_CLAIM_REPLY']='1'
        self.land('--host','hetzner7',expected=1)
        self.assertEqual(self.tip(),self.original)
        self.assert_kept()

    def test_interrupt_keeps_unseen_remote_claim(self):
        self.env['WAIT_GATE']='1'
        child=subprocess.Popen(['python3','-I','-B','tools/land','--host','hetzner7',
                                '--inventory',str(self.inventory)],cwd=self.source,env=self.env,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+10
            while not ((self.home/'ready').exists() and self.records() and
                       json.loads(self.records()[0].read_text()).get('remote_pgid')):
                self.assertIsNone(child.poll())
                self.assertLess(time.monotonic(),deadline)
                time.sleep(.01)
            child.send_signal(signal.SIGINT)
            out,err=child.communicate(timeout=10)
            self.assertNotEqual(child.returncode,0,out+err)
            row=self.assert_kept()
            self.assertIsInstance(row['remote_pgid'],int)
            self.assertIn('--reconcile',err)
            self.env.pop('WAIT_GATE')
            self.land('--reconcile',row['id'],'--kill')
            self.assert_released()
            self.assertEqual(self.tip(),self.original)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()




    def test_dirty_main_and_detached_refuse_without_push(self):
        put(self.source/'dirt','dirt')
        self.land(expected=1)
        (self.source/'dirt').unlink()
        self.git('switch','main')
        self.land(expected=1)
        self.git('checkout','--detach')
        self.land(expected=1)
        self.assertEqual(self.tip(),self.original)
        self.assertFalse((self.home/'ssh.log').exists())

    def test_invalid_remote_temporary_path_is_never_removed(self):
        self.env['BAD_TEMP']='1'
        self.land('--host','hetzner7',expected=1)
        self.assert_kept()
        self.assertFalse(any(args[0]=='rm' for args in self.calls()))
        self.assertEqual(self.tip(),self.original)

    def test_local_rebases_before_one_check(self):
        put(self.home/'upstream/b/upstream','new')
        for args in [('add','.'),('commit','-qm','upstream'),('push','origin','main')]:
            self.command('git','-C',self.home/'upstream',*args)
        output=self.land('--local')
        self.assertIn('LOCAL FALLBACK',output)
        self.assertEqual((self.home/'gates').read_text(),'1')
        self.assertTrue((self.source/'b/upstream').exists())
        self.assertEqual(self.tip(),self.git('rev-parse','HEAD'))

    def test_no_force_push_command(self):
        text=(ROOT/'tools/land').read_text()
        self.assertNotIn('--force',text)
        self.assertNotIn('HEAD:+',text)


class PeriodicTests(unittest.TestCase):
    def test_units_only_render_for_flagged_builder(self):
        loader=importlib.machinery.SourceFileLoader('fleet_periodic_fixture',str(ROOT/'tools/fleet-sync'))
        module=importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name,loader))
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as home:
            declarations=module.Declarations(ROOT,Path(home))
            for host in declarations.hosts:
                wanted=declarations.host_units(host)
                self.assertEqual('agents-periodic.timer' in wanted,host=='hetzner3')
                self.assertEqual('agents-periodic.service' in wanted,host=='hetzner3')
            service=(ROOT/'fleet/units/agents-periodic.service').read_text()
            self.assertIn('AGENTS_PERIODIC',service)
            self.assertIn('Nice=19',service)
            self.assertIn('IOSchedulingClass=idle',service)

    def test_periodic_runs_both_tiers_and_routes_failure_and_missing_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            put(root/'tools/periodic',(ROOT/'tools/periodic').read_text(),True)
            put(root/'tools/check.sh',r'''#!/usr/bin/env python3
import json,sys
from pathlib import Path
tier=sys.argv[sys.argv.index('--tier')+1]
with (Path.home()/'tiers').open('a') as f: f.write(tier+'\n')
Path(sys.argv[sys.argv.index('--json')+1]).write_text(json.dumps(dict(files=[dict(failed=True,owner='s/qa'),dict(failed=True,owner='')],reasons=[])))
sys.exit(1)
''',True)
            put(root/'bin/post', '#!/bin/bash\nprintf "%s\\n" "$*" >> "$HOME/mail"\n',True)
            env=dict(os.environ,HOME=str(root),PATH=str(root/'bin')+':'+os.environ['PATH'])
            result=subprocess.run(['python3','-I','-B',str(root/'tools/periodic')],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((root/'tiers').exists())
            env['AGENTS_PERIODIC']='1'
            result=subprocess.run(['python3','-I','-B',str(root/'tools/periodic')],env=env,capture_output=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertEqual((root/'tiers').read_text(),'periodic\ngate\n')
            mail=(root/'mail').read_text()
            self.assertEqual(mail.count('s/qa@hel8'),2)
            self.assertEqual(mail.count('ops@hel8'),2)


if __name__=='__main__':
    unittest.main()
