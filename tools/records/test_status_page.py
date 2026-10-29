#!/usr/bin/env python3.13
"""Fixtures never touch real machines, records, accounts or the web root."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('status-page')
loader = importlib.machinery.SourceFileLoader('status_page', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
sp = importlib.util.module_from_spec(spec)
loader.exec_module(sp)
NOW = 1793275200  # fixed UTC clock
PRIVATE = ['lead/private-worker', 's/private-coordinator', 'coord-next',
           'private@example.net', 'sessionId', 'Secret mail subject',
           '/home/private/worktree', 'Private Person', 'secret-token-value']
POISON = ' '.join(PRIVATE)


class StatusPage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.fabrig = self.base/'records', self.base/'fabrig'
        self.root.mkdir()
        self.fabrig.mkdir()
        self.bin = self.base/'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin)+':/usr/bin:/bin', STATUS_NOW=str(NOW),
                        RECORDS_REPO=str(self.root), FABRIG_REPO=str(self.fabrig), DEV_TMP=str(self.base))
        self.fake('claim', "print('node 1 [lead/private-worker]: s/private-coordinator')\nprint('node 2 [pool]: free')")
        self.fake('record', "print('pulled')")
        self.fake('claude', """import sys, json
if sys.argv[1:3] == ['auth', 'status']:
 print(json.dumps({'loggedIn':True, 'subscriptionType':'max', 'orgId':'secret-token-value', 'email':'private@example.net', 'name':'Private Person'}))
else:
 print(json.dumps({'local_command':'usage', 'num_turns':0, 'total_cost_usd':0, 'result':'Current session: 25% used · resets 8pm (UTC)\\nCurrent week (all models): 40% used'}))
""")
        self.fake('codex', """import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 result = {} if r['method']=='initialize' else {'account':{'type':'chatgpt','email':'private@example.net','planType':'pro'}} if r['method']=='account/read' else {'accountId':'secret-token-value','rateLimits':{'limitId':'codex','primary':{'windowDurationMins':300,'usedPercent':50,'resetsAt':1793282400}}}
 print(json.dumps({'id':r['id'],'result':result}), flush=True)
""")
        self.capacity = dict(ips=['8.8.8.8', POISON], load=[1,2,3], cpus=8,
                             mem_available=8*1024**3, mem_total=16*1024**3,
                             disk_free=100*1024**3, disk_total=200*1024**3,
                             session=POISON)
        remote = dict(machine=self.capacity, errors={}, session=POISON,
                      claude_usage=dict(state='subscribed', plan='max', label='1234abcd',
                                        limits=[dict(name='session', used=25, resets=NOW+7200)]),
                      codex_usage=dict(state='signed-out', private=POISON))
        self.fake('ssh', 'print('+repr(json.dumps(remote))+')')
        self.machines = self.base/'machines'
        self.machines.write_text('node fixture-target\n# '+POISON+'\n')
        self.write('drafts/beta/draft.toml', 'source="beta.md"\npriority=1\nstate="paused"\ncoordinator="s/private-coordinator"\n')
        self.write('drafts/alpha/draft.toml', 'source="alpha.md"\npriority=2\nstate="active"\ncoordinator="s/private-coordinator"\n')
        (self.fabrig/'alpha.md').write_text('# Public alpha description\n'+POISON)
        (self.fabrig/'beta.md').write_text('Public beta description\n====\n'+POISON)
        self.write('director/priorities.toml', '[[draft]]\nname="alpha"\nreason="'+POISON+'"\n[[draft]]\nname="beta"\n')
        self.write('director/questions/0001.toml', 'asked="'+sp.utc(NOW-7200,'%Y-%m-%dT%H:%M:%SZ')+'"\nquestion="'+POISON+'"\n')
        self.write('director/questions/0002.toml', 'asked="2026-10-28T00:00:00Z"\nanswer="'+POISON+'"\n')
        self.event('queue', 'ready', -900, branch='private-branch')
        self.event('queue', 'land', -300, branch='private-branch', draft='alpha')
        self.event('queue', 'batch-start', -600, batch='private-batch')
        self.event('queue', 'batch-end', -60, batch='private-batch', outcome='rejected', step='clippy')
        self.event('runs', 'start', -400, run='private-run')
        self.event('runs', 'start', -600, run='ended-run')
        self.event('runs', 'end', -500, run='ended-run')
        self.event('claims', 'claim', -400)
        self.event('sessions', 'snapshot', -400, sessions=[dict(session='lead/private-worker',role='lead',state='idle'),dict(session='s/private-coordinator',role='coordinator',state='running')])

    def fake(self, name, content):
        path = self.bin/name
        path.write_text('#!/usr/bin/python3.13\n'+content+'\n')
        path.chmod(0o755)

    def write(self, relative, content):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def event(self, source, kind, offset, **extra):
        path = self.root/f'events/{source}/host/2026-10-29.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = path.read_text().splitlines() if path.exists() else []
        row = dict(id=str(len(rows)), source=source, host='host', kind=kind,
                   time=sp.utc(NOW+offset,'%Y-%m-%dT%H:%M:%SZ'), private=POISON, **extra)
        with path.open('a') as stream: stream.write(json.dumps(row)+'\n')

    def gather(self):
        with patch.dict(os.environ, self.env, clear=True):
            return sp.gather_page(self.root, self.fabrig, self.machines, False, SCRIPT.read_bytes())

    def test_sections_and_privacy(self):
        out = self.base/'index.html'
        (self.base/'v0.1.0.html').write_text(POISON)
        proc = subprocess.run([str(SCRIPT),'--no-pull','--machines',str(self.machines),'--out',str(out), '--samples',str(self.base/'samples')], env=self.env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        page = out.read_text()
        self.assertEqual(re.findall(r'<h2>(.*?)</h2>',page), ['Drafts','Landings and the queue','Work in flight','Waiting on the user','Machines and capacity','Subscriptions','Links'])
        for private in PRIVATE: self.assertNotIn(private, page)
        self.assertLess(page.index('Public alpha'),page.index('Public beta'))
        for wanted in ['1 open questions', '2 h 0 min ago', 'Slots held / total: 1 / 2', 'Runs running: 1', 'Leads live: 1', 'Coordinators live: 1', '9 min', 'clippy', '10 min median', 'href="v0.1.0.html"','100 GB', '25%']:
            self.assertIn(wanted,page)
        self.assertEqual(out.stat().st_mode & 0o777,0o644)
        self.assertEqual((self.base/'samples').stat().st_mode & 0o777,0o600)

    def test_real_cli_probes_with_fake_claude_and_codex(self):
        with patch.dict(os.environ,self.env,clear=True):
            data = sp.collect()
        self.assertEqual(data['errors'],{})
        self.assertIsInstance(data['machine']['load'],list)
        self.assertEqual(data['claude_usage']['limits'][0]['used'],25)
        self.assertEqual(data['codex_usage']['limits'][0]['used'],50)
        self.assertEqual(len(data['claude_usage']['label']),8)
        self.assertNotIn('private@example.net',json.dumps(data))

    def test_failing_source_is_unknown_and_others_survive(self):
        self.write('events/queue/host/2026-10-29.jsonl','{"oops":\n')
        data = self.gather()
        page = sp.render(data)
        self.assertIn('unknown · invalid data',page)
        self.assertIn('Public alpha',page)
        self.assertIn('Slots held / total: 1 / 2',page)
        self.fake('claim', "import sys\nprint('"+POISON+"',file=sys.stderr)\nsys.exit(1)")
        page = sp.render(self.gather())
        self.assertIn('Slots held / total: unknown · probe failed',page)
        for private in PRIVATE: self.assertNotIn(private,page)

    def test_empty_events_are_real_state(self):
        for path in (self.root/'events').glob('*/*/*.jsonl'): path.unlink()
        page = sp.render(self.gather())
        self.assertGreaterEqual(page.count('no events yet'),5)
        self.assertNotIn('unknown',page)

    def test_privacy_in_public_fields_and_probe_errors(self):
        (self.fabrig/'alpha.md').write_text('# '+POISON+'\n')
        data = self.gather()
        data['fleet']['node']['claude_usage']['plan'] = POISON
        data['fleet']['node']['claude_usage']['limits'][0]['name'] = POISON
        data['fleet']['node']['errors']['codex_usage'] = POISON
        data['fleet']['node'].pop('codex_usage')
        page = sp.render(data)
        for private in PRIVATE: self.assertNotIn(private,page)
        self.assertIn('unknown',page)

    def test_missing_records_and_bad_machines(self):
        self.machines.write_text(POISON)
        with patch.dict(os.environ,self.env,clear=True):
            data = sp.gather_page(self.base/'missing',self.fabrig,self.machines,False,b'')
        page = sp.render(data)
        self.assertIn('unknown · not found',page)
        for private in PRIVATE: self.assertNotIn(private,page)

    def test_atomic_write_and_failed_rename(self):
        target = self.base/'index.html'
        target.write_text('old')
        replace = os.replace
        def observe(source,dest):
            self.assertEqual(Path(source).parent,target.parent)
            self.assertEqual(target.read_text(),'old')
            self.assertEqual(Path(source).read_text(),'new')
            replace(source,dest)
        with patch.object(sp.os,'replace',side_effect=observe): sp.write(target,'new',0o644)
        self.assertEqual(target.read_text(),'new')
        with patch.object(sp.os,'replace',side_effect=OSError(POISON)):
            with self.assertRaises(OSError): sp.write(target,'incomplete',0o644)
        self.assertEqual(target.read_text(),'new')
        self.assertEqual(list(self.base.glob('.index.html.*')),[])

    def test_queue_buckets_dedup_wait_and_batch_duration(self):
        self.event('queue','land',-6*3600-1)
        self.event('queue','land',-6*3600+1)
        rows=sp.events(self.root,'queue')
        queue=sp.queue_data(rows,NOW+123)
        self.assertEqual(sum(n for _,_,n in queue['hours']),1)
        self.assertEqual(queue['waits'],[600])
        self.assertEqual(queue['batches'][0]['duration'],540)
        path=self.root/'events/queue/host/2026-10-29.jsonl'
        with path.open('a') as stream: stream.write(json.dumps(rows[0])+'\n')
        self.assertEqual(len(sp.events(self.root,'queue')),len(rows))

    def test_hour_boundary_and_batch_landing_not_counted_twice(self):
        rows = [dict(host='h', id='land', time=NOW, kind='land', batch='b'),
                dict(host='h', id='end', time=NOW, kind='batch-end', batch='b', outcome='landed')]
        queue = sp.queue_data(rows, NOW)
        self.assertEqual(len(queue['landings']), 1)
        self.assertEqual(sum(n for _, _, n in queue['hours']), 1)

    def test_pull_and_ssh_failure_do_not_stop_render(self):
        self.fake('record', 'import sys\nsys.exit(1)')
        self.fake('ssh', 'import sys\nprint('+repr(POISON)+', file=sys.stderr)\nsys.exit(255)')
        with patch.dict(os.environ, self.env, clear=True):
            data = sp.gather_page(self.root, self.fabrig, self.machines, True, b'')
        page = sp.render(data)
        self.assertIn('record pull exited 1', page)
        self.assertIn('Public alpha', page)
        self.assertIn('unknown', page)
        for private in PRIVATE: self.assertNotIn(private, page)

    def test_snapshot_transitions(self):
        rows=[dict(host='h',kind='snapshot',runs=[dict(run='r',state='running')]),dict(host='h',kind='end',run='r')]
        self.assertEqual(sp.live_count(rows,'runs')['runs'],0)

    def test_samples_keep_identity_private_and_measure_pace(self):
        fleet=sp.SimpleNamespace(now=NOW,usage=[('node','claude',dict(state='subscribed',plan='max',label='1234abcd',limits=[dict(name='session',used=60,resets=NOW+3600)]))])
        samples=sp.usage_samples(fleet)
        old=dict(samples[0],time=NOW-3600,used=30)
        self.assertIn('30.0%/h',sp.rate([old],fleet.usage[0][2]['limits'][0],'claude','1234abcd',NOW))
        self.assertIn('lasts',sp.pace([old],fleet.usage[0][2]['limits'][0],'claude','1234abcd',NOW))
        path=self.base/'samples'
        sp.write(path,json.dumps(old)+'\ninvalid\n',0o600)
        read,dropped=sp.read_samples(path)
        self.assertEqual(read,[old])
        self.assertEqual(dropped,1)


if __name__ == '__main__': unittest.main(verbosity=2)
