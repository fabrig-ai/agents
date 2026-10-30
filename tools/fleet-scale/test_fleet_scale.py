"""No network beyond loopback: disposable HOME, fake API/SSH, real key utilities."""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import tempfile
import threading
import tomllib
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(SOURCE / 'tools/fleet-scale/fleet-scale'))
Fleet, Error = MODULE['Fleet'], MODULE['Error']
TOKEN = 'TEST-TOKEN-MUST-NEVER-LEAK-95b633'
ARTIFACT = b'#!/bin/sh\necho 2.1.312\n'

SSH = r'''#!/usr/bin/env python3
import hashlib, io, json, os, pathlib, sys, tarfile
home = pathlib.Path.home()
command = sys.argv[-1]
registry = home / 'src/fabrig/fleet/members.json'
members = json.loads(registry.read_text())['members'] if registry.exists() else {}
with (home / 'ssh.log').open('a') as log:
    log.write(json.dumps({'argv':sys.argv[1:], 'states':{k:v['state'] for k,v in members.items()}, 'steps':{k:v.get('step') for k,v in members.items()}})+'\n')
if os.environ.get('FAIL_SSH') and os.environ['FAIL_SSH'] in command:
    print('TEST-TOKEN-MUST-NEVER-LEAK-95b633', file=sys.stderr)
    sys.exit(7)
if "seed file" in command or 'os.fdopen(home' in command or 'tarfile.open' in command:
    data = b'#!/bin/sh\necho 2.1.312\n'
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as tar:
        item=tarfile.TarInfo('payload'); item.mode=0o755; item.size=len(data)
        tar.addfile(item, io.BytesIO(data))
elif 'fleet-member.pub' in command:
    print((home/'member.pub').read_text())
elif 'hashlib.file_digest' in command:
    data=sys.stdin.buffer.read()
    (home/'remote-credential').write_bytes(data)
    print('wrong' if os.environ.get('BAD_HASH') else hashlib.sha256(data).hexdigest())
elif 'bootstrap.py member' in command:
    import shlex
    arguments=shlex.split(command)
    name=arguments[arguments.index('--host')+1]
    path=home/'src/fabrig/fleet/member.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'name':name,'local_only_kache':'--local-only-kache' in arguments}))
    path.chmod(0o600)
elif 'fleet-sync --check' in command:
    print(json.dumps({'items':[{'item':'fixture','result':os.environ.get('CHECK_RESULT','ok')}]}))
elif 'fleet-scale-idle' in command:
    print(os.environ.get('HEAVY_STATUS', '{"idle":true}'))
elif '--version' in command:
    print('fixture 2.1.312')
elif 'is-active' in command:
    print(os.environ.get('TIMER_STATUS','active'))
else:
    sys.stdin.buffer.read()
'''

GIT = r'''#!/usr/bin/env python3
import io, sys, tarfile
if 'rev-parse' in sys.argv:
    print('a'*40)
elif 'archive' in sys.argv:
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|'):
        pass
else:
    sys.exit(9)
'''


def put(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    path.chmod(mode)



class FakeAPI(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle_request(self):
        f = self.server.fixture
        route = urlsplit(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else None
        f.requests.append((self.command, self.path, body))
        f.assertEqual(self.headers.get('Authorization'), 'Bearer ' + TOKEN)
        if f.api_failure and f.api_failure in self.command + ' ' + route.path:
            return self.respond(500, {'error': TOKEN})
        if route.path == '/v1/ssh_keys':
            if self.command == 'POST':
                f.keys.append(body | {'id': 11})
                return self.respond(201, {'ssh_key': f.keys[-1]})
            return self.respond(200, {'ssh_keys': f.keys})
        if route.path == '/v1/servers':
            if self.command == 'POST':
                number = f.next_id
                f.next_id += 1
                row = body | {'id': number, 'public_net': {'ipv4': {'ip': '192.0.2.' + str(number)}}}
                f.servers[number] = row
                if f.lost_create:
                    return self.respond(500, {'error': TOKEN})
                return self.respond(201, {'server':row, 'action':{'id':1}})
            selector = parse_qs(route.query)['label_selector'][0]
            member = selector.split('member=')[-1] if 'member=' in selector else None
            rows = [v for v in f.servers.values() if member is None or v['labels'].get('member') == member]
            return self.respond(200, {'servers':rows})
        if route.path.startswith('/v1/actions/'):
            return self.respond(200, {'action': {'status': f.action_status}})
        if route.path.startswith('/v1/servers/'):
            number = int(route.path.rsplit('/',1)[1])
            if number not in f.servers:
                return self.respond(404, {})
            if self.command == 'DELETE':
                del f.servers[number]
                return self.respond(200, {'action':{'id':2}})
            return self.respond(200, {'server':f.servers[number]})
        return self.respond(404, {})

    do_GET = do_POST = do_DELETE = handle_request

    def respond(self, code, payload):
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


class ScaleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.home = self.directory / 'home'
        self.home.mkdir()
        self.root = self.directory / 'repo'
        shutil.copytree(SOURCE / 'fleet', self.root / 'fleet')
        (self.root / 'tools').mkdir()
        shutil.copy(SOURCE / 'tools/fleet-sync', self.root / 'tools/fleet-sync')
        shutil.copytree(SOURCE / 'tools/fleet-scale', self.root / 'tools/fleet-scale')
        self.bin = self.directory / 'bin'
        put(self.bin / 'ssh', SSH, 0o755)
        put(self.bin / 'scp', '#!/bin/sh\nexit 99\n', 0o755)
        put(self.bin / 'git', GIT, 0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin)+':'+os.environ['PATH'])
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(self.home / 'member')], check=True)
        public = (self.home / 'member.pub').read_text()
        put(self.bin / 'ssh-keyscan', '#!/bin/sh\nprintf "%s %s\\n" "$5" '+shlex_quote(' '.join(public.split()[:2]))+'\n', 0o755)
        put(self.home / '.ssh/known_hosts', '204.168.210.29 '+public+'198.51.100.9 '+public)
        put(self.home / '.ssh/authorized_keys', '# retained comment\nssh-ed25519 AAAA other-user\n')
        self.original_auth = (self.home / '.ssh/authorized_keys').read_bytes()
        put(self.home / 'src/rust/tmp/hetzner/api-token', TOKEN)
        put(self.home / '.config/fleet-scale/kache-store.env', 'PRIVATE-KACHE-FIXTURE\n')
        self.requests, self.keys, self.servers = [], [], {}
        self.api_failure, self.lost_create = None, False
        self.action_status, self.next_id = 'success', 1
        server = ThreadingHTTPServer(('127.0.0.1',0), FakeAPI)
        server.fixture = self
        self.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = self.root / 'fleet/pool.toml'
        config.write_text(config.read_text().replace('https://api.hetzner.cloud/v1',f'http://127.0.0.1:{server.server_port}/v1'))
        (self.root / 'fleet/versions.toml').write_text('[claude]\nversion="2.1.312"\ncommand=["claude","--version"]\n[claude.install]\nkind="binary"\nseed="peer"\nsource=".local/share/claude/versions/2.1.312"\ndestination=".local/share/claude/versions/2.1.312"\nmode="0755"\nsha256="'+hashlib.sha256(ARTIFACT).hexdigest()+'"\n')
        self.fleet = Fleet(self.root, self.home)
        with contextlib.redirect_stdout(io.StringIO()):
            self.fleet.key()
        self.requests.clear()

    def invoke(self, *args, **environment):
        process = subprocess.run(['python3','-I','-B',str(self.root / 'tools/fleet-scale/fleet-scale'),*args],
                                 env=dict(self.env, **environment), capture_output=True, text=True)
        self.assertNotIn(TOKEN, process.stdout + process.stderr)
        return process

    def up(self):
        result = self.invoke('up')
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.fleet.registry.read()['members']['pool-1']

    def test_up_end_to_end_states_and_credentials(self):
        member = self.up()
        self.assertEqual(member['state'], 'ready')
        self.assertTrue(member['fingerprint'].startswith('SHA256:'))
        self.assertEqual(member['roles'], ['builder'])
        rows=[json.loads(line) for line in (self.home/'ssh.log').read_text().splitlines()]
        self.assertTrue(all('ForwardAgent=no' in row['argv'] for row in rows))
        states={value for row in rows for value in row['states'].values()}
        self.assertEqual(states, {'creating','bootstrapping'})
        steps={value for row in rows for value in row['steps'].values()}
        self.assertTrue({'root','member-key','seeds','member-settings','credential','user','kache','verify'} <= steps)
        ordered=[next(iter(row['steps'].values())) for row in rows]
        self.assertLess(ordered.index('member-settings'),ordered.index('user'))
        self.assertLess(ordered.index('user'),ordered.index('credential'))
        self.assertLess(ordered.index('credential'),ordered.index('kache'))
        self.assertLess(ordered.index('kache'),ordered.index('verify'))
        self.assertEqual((self.home/'remote-credential').read_bytes(), b'PRIVATE-KACHE-FIXTURE\n')
        self.assertNotIn(TOKEN, (self.home/'ssh.log').read_text())
        create = next(row[2] for row in self.requests if row[:2] == ('POST','/v1/servers'))
        self.assertEqual(create['ssh_keys'], ['fleet-scale'])
        self.assertEqual(create['server_type'], 'cpx42')
        self.assertEqual(create['labels'], {'fleet':'pool','member':'pool-1'})

    def test_key_idempotent_and_private_mode(self):
        before = (self.home/'.ssh/fleet-scale').read_bytes()
        for _ in range(2):
            result = self.invoke('key')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.keys), 1)
        self.assertEqual(before, (self.home/'.ssh/fleet-scale').read_bytes())
        self.assertEqual((self.home/'.ssh/fleet-scale').stat().st_mode & 0o777, 0o600)
        self.assertNotIn(before.decode(), result.stdout+result.stderr)

    def test_key_mismatch_refused(self):
        self.keys[0]['public_key'] = 'ssh-ed25519 OTHER'
        self.assertEqual(self.invoke('key').returncode, 1)
        self.assertEqual(len(self.keys), 1)

    def test_token_mode_refused(self):
        (self.home/'src/rust/tmp/hetzner/api-token').chmod(0o644)
        self.assertEqual(self.invoke('key').returncode, 1)
        self.assertEqual(self.requests, [])

    def test_api_body_is_not_logged(self):
        self.api_failure = 'POST /v1/servers'
        result = self.invoke('up')
        self.assertEqual(result.returncode, 1)
        self.assertIn('HTTP 500', result.stderr)
        self.assertEqual(self.fleet.registry.read()['members']['pool-1']['state'], 'creating')

    def test_lost_create_response_is_recovered_by_label(self):
        self.lost_create = True
        self.assertEqual(self.invoke('up').returncode, 1)
        self.assertEqual(len(self.servers), 1)
        self.assertEqual(self.invoke('down','pool-1').returncode, 0)
        self.assertEqual(self.servers, {})

    def test_authorization_exact_and_backup(self):
        self.up()
        path = self.home/'.ssh/authorized_keys'
        self.assertTrue(path.read_bytes().endswith(self.original_auth))
        grant=path.read_text().splitlines()[0]
        self.assertTrue(grant.startswith('restrict,command="git-shell -c \\"$SSH_ORIGINAL_COMMAND\\"" ssh-ed25519 '), grant)
        self.assertTrue(grant.endswith(' fleet-scale:pool-1'))
        self.assertEqual(path.with_name(path.name+'.fleet-scale.bak').read_bytes(), self.original_auth)
        self.assertEqual(self.invoke('down','pool-1').returncode, 0)
        self.assertEqual(path.read_bytes(), self.original_auth)
        self.assertEqual(self.invoke('down','pool-1').returncode, 0)

    def test_known_hosts_removes_only_member(self):
        before=(self.home/'.ssh/known_hosts').read_bytes()
        self.up()
        self.assertEqual(self.invoke('down','pool-1').returncode, 0)
        self.assertEqual((self.home/'.ssh/known_hosts').read_bytes(), before)

    def test_hosts_merge_ready_only(self):
        self.up()
        data=self.fleet.registry.read()
        data['members']['pool-2']={'name':'pool-2','state':'bootstrapping'}
        self.fleet.registry.write(data)
        result=self.invoke('hosts','--json')
        self.assertEqual(result.returncode,0,result.stderr)
        hosts=json.loads(result.stdout)['hosts']
        self.assertEqual(set(hosts), {'hel8','hetzner3','hetzner6','hetzner7','hetzner8','pool-1'})
        self.assertEqual(hosts['pool-1']['ssh'],'free@192.0.2.1')

    def test_limit_counts_failed_members(self):
        path=self.root/'fleet/pool.toml'
        path.write_text(path.read_text().replace('[limits]','[limits]\nmax_members=1'))
        self.up()
        self.assertEqual(self.invoke('up').returncode,1)
        self.assertEqual(len(self.servers),1)

    def test_dry_run_no_writes_or_api(self):
        before=self.snapshot()
        self.assertEqual(self.invoke('up','--dry-run').returncode,0)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.snapshot(),before)
        self.up()
        before=self.snapshot()
        self.requests.clear()
        self.assertEqual(self.invoke('down','pool-1','--dry-run').returncode,0)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.requests,[])

    def snapshot(self):
        return {str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}

    def test_registry_concurrency(self):
        code = '''import pathlib, runpy, sys
registry=runpy.run_path(sys.argv[1])['Registry'](pathlib.Path(sys.argv[2]))
for _ in range(15):
    with registry.locked():
        data=registry.read(); n=data['next']; data['next']+=1
        data['members'][str(n)]={'state':'creating'}; registry.write(data)
'''
        processes=[subprocess.Popen(['python3','-I','-B','-c',code,
                   str(SOURCE/'tools/fleet-scale/fleet-scale'),str(self.home)],env=self.env) for _ in range(5)]
        for process in processes:
            self.assertEqual(process.wait(timeout=15),0)
        data=self.fleet.registry.read()
        self.assertEqual(len(data['members']),75)
        self.assertEqual(data['next'],76)

    def test_force_skips_unreachable_drain(self):
        self.up()
        self.assertEqual(self.invoke('down','pool-1',FAIL_SSH='fleet-scale-idle').returncode,1)
        self.assertEqual(self.fleet.registry.read()['members']['pool-1']['state'],'draining')
        self.assertEqual(self.invoke('down','pool-1','--force',FAIL_SSH='fleet-scale-idle').returncode,0)

    def test_drain_busy_is_bounded_and_keeps_state(self):
        member=self.up()
        with patch.dict(os.environ,HEAVY_STATUS='{"idle":false}'):
            self.assertFalse(self.fleet.drain(member))
        with patch.object(self.fleet,'drain',return_value=False), patch('time.monotonic',side_effect=[0,301]):
            with self.assertRaises(Error): self.fleet.down('pool-1')
        self.assertEqual(self.fleet.registry.read()['members']['pool-1']['state'],'draining')
        self.assertEqual(len(self.servers),1)

    def test_delete_failure_retains_registry_and_key_for_retry(self):
        self.up()
        self.api_failure='DELETE /v1/servers'
        self.assertEqual(self.invoke('down','pool-1').returncode,1)
        self.assertEqual(self.fleet.registry.read()['members']['pool-1']['state'],'deleting')
        self.assertIn('fleet-scale:pool-1',(self.home/'.ssh/authorized_keys').read_text())
        self.api_failure=None
        self.assertEqual(self.invoke('down','pool-1').returncode,0)

    def test_labels_guard_fixed_servers(self):
        self.up()
        self.servers[1]['labels']={'fleet':'fixed'}
        result=self.invoke('down','pool-1','--force')
        self.assertEqual(result.returncode,1)
        self.assertIn('matching pool labels',result.stderr)
        self.assertEqual(len(self.servers),1)

    def test_template_bootstrap_and_convergence(self):
        helper=runpy.run_path(str(SOURCE/'fleet/bootstrap/bootstrap.py'))
        declaration=helper['host_declaration']('pool-1')
        fixed=tomllib.loads((SOURCE/'fleet/hosts.toml').read_text())['hosts']['hetzner3']
        self.assertEqual(declaration['machine_env'],{key:value for key,value in fixed['machine_env'].items() if key != 'KACHE_LOCAL_ONLY'})
        self.assertNotIn('KACHE_LOCAL_ONLY',declaration['machine_env'])
        self.assertNotIn('seed',declaration)
        for mode in ('root','user'):
            result=subprocess.run(['bash',str(SOURCE/f'fleet/bootstrap/{mode}.sh'),'--dry-run','--host','pool-1'],env=self.env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('pool-1',result.stdout)
            if mode=='root':
                self.assertIn('journald.conf.d/90-fabrig.conf',result.stdout)
                self.assertIn('PUBLIC key for root and free',result.stdout)
            else:
                self.assertIn('ssh://FABRIG_CENTRAL/~/src/fabrig/mirror/agents.git',result.stdout)
                self.assertNotIn('git@github.com',result.stdout)
        module=runpy.run_path(str(SOURCE/'tools/fleet-sync'),run_name='test_sync')
        declarations=module['Declarations'](SOURCE,self.home,'pool-1')
        self.assertEqual(declarations.host('pool-1'),'pool-1')
        self.assertEqual(declarations.fabrig_origin,'ssh://FABRIG_CENTRAL/~/src/fabrig/mirror/fabrig.git')
        self.assertNotIn('mirror.timer',declarations.host_units('pool-1'))
        self.assertIn('mirror.timer',declarations.host_units('hel8'))
        for name in ('hetzner3','hetzner6','hetzner7','hetzner8'):
            self.assertNotIn('mirror.service',declarations.host_units(name))

    def test_invalid_name_and_symlink_refused(self):
        self.assertEqual(self.invoke('down','hel8','--force').returncode,1)
        path=self.home/'.ssh/authorized_keys'
        path.unlink()
        target=self.home/'retain';put(target,'retained')
        path.symlink_to(target)
        with self.assertRaises(Error):self.fleet.authorization('pool-1','ssh-ed25519 AAAA')
        self.assertEqual(target.read_text(),'retained')

    def test_credential_mode_and_hash(self):
        member=self.up()
        path=self.home/'.config/fleet-scale/kache-store.env'
        path.chmod(0o644)
        with self.assertRaises(Error):self.fleet.credential(member)
        path.chmod(0o600)
        with patch.dict(os.environ,BAD_HASH='1'):
            with self.assertRaises(Error):self.fleet.credential(member)


    def test_action_failure_is_cleanable(self):
        self.action_status='error'
        self.assertEqual(self.invoke('up').returncode,1)
        self.assertEqual(self.fleet.registry.read()['members']['pool-1']['state'],'creating')
        self.action_status='success'
        self.assertEqual(self.invoke('down','pool-1').returncode,0)

    def test_get_failure_is_cleanable(self):
        self.api_failure='GET /v1/servers/1'
        self.assertEqual(self.invoke('up').returncode,1)
        self.api_failure=None
        self.assertEqual(self.invoke('down','pool-1').returncode,0)

    def test_trust_failure_is_cleanable(self):
        with patch.object(self.fleet,'trust',side_effect=Error('contact failed')):
            with self.assertRaises(Error):self.fleet.up()
        member=self.fleet.registry.read()['members']['pool-1']
        self.assertEqual(member['step'],'trust')
        self.assertEqual(member['ipv4'],'192.0.2.1')
        self.assertEqual(self.invoke('down','pool-1').returncode,0)

    def test_bad_verification_never_records_ready(self):
        for environment in ({'CHECK_RESULT':'drift'},{'TIMER_STATUS':'inactive'}):
            result=self.invoke('up',**environment)
            self.assertEqual(result.returncode,1)
            data=self.fleet.registry.read()
            name=next(iter(data['members']))
            self.assertEqual(data['members'][name]['state'],'bootstrapping')
            self.assertEqual(self.invoke('down',name,'--force').returncode,0)

    def test_release_archive_without_git_metadata(self):
        put(self.root/'.fleet-release.json',json.dumps({'sha':'b'*40}))
        put(self.bin/'git','#!/bin/sh\nexit 99\n',0o755)
        self.assertEqual(self.up()['template_revision'],'b'*40)

    def test_api_scheme_and_redirects_are_refused(self):
        for base in ('http://api.example.invalid/v1','https://user:password@example.invalid/v1'):
            with self.assertRaises(Error):MODULE['API'](base,self.home/'unused')
        self.assertIsNone(MODULE['NoRedirect']().redirect_request(None,None,None,None,None,None))

    def test_mirror_creation_refresh_and_read_only(self):
        # Real local git repositories prove the hook rejects pushes; no network.
        real_git=shutil.which('git',path=os.defpath)
        origins={}
        for name in ('agents','fabrig'):
            repo=self.directory/(name+'.git')
            subprocess.run([real_git,'init','--bare',str(repo)],check=True,capture_output=True)
            origins[name]=str(repo)
        (self.root/'fleet/repositories.toml').write_text(''.join(f'{name}="{url}"\n' for name,url in origins.items()))
        shutil.copy(SOURCE/'tools/fleet-scale/mirror',self.root/'tools/fleet-scale/mirror')
        env=dict(self.env,PATH=os.defpath)
        for _ in range(2):
            result=subprocess.run(['python3','-I','-B',str(self.root/'tools/fleet-scale/mirror')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        for name in origins:
            mirror=self.home/'src/fabrig/mirror'/(name+'.git')
            self.assertEqual(subprocess.check_output([real_git,'-C',str(mirror),'rev-parse','--is-bare-repository'],text=True).strip(),'true')
            hook=mirror/'hooks/pre-receive'
            self.assertEqual(subprocess.run([str(hook)]).returncode,1)
            working=self.directory/(name+'-working')
            subprocess.run([real_git,'clone',str(mirror),str(working)],check=True,capture_output=True)
            subprocess.run([real_git,'-C',str(working),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture'],check=True,capture_output=True)
            result=subprocess.run([real_git,'-C',str(working),'push','origin','HEAD:refs/heads/prohibited'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('pre-receive hook declined',result.stderr)


    def test_pool_public_key_bootstrap_preserves_existing_keys(self):
        import types
        module=runpy.run_path(str(SOURCE/'fleet/bootstrap/bootstrap.py'))
        klass=module['Bootstrap']
        sandbox=self.directory/'root-sandbox'
        for account in ('root','home/free'):
            put(sandbox/account/'.ssh/authorized_keys','ssh-ed25519 AAAA retain\n')
        public=(self.home/'member.pub').read_text().strip()
        put(self.root/'fleet/bootstrap/fleet-scale.pub',public+'\n')
        def mapped(value):
            value=Path(value)
            return sandbox/value.relative_to('/') if value.is_absolute() and not value.is_relative_to(self.directory) else value
        globals_=klass.pool_public_keys.__globals__
        with patch.dict(globals_,ROOT=self.root,Path=mapped), patch('os.chown'), patch('os.fchown'):
            bootstrap=klass(types.SimpleNamespace(host='pool-1',dry_run=False))
            user=types.SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
            bootstrap.pool_public_keys(user)
            bootstrap.pool_public_keys(user)
        for account in ('root','home/free'):
            target=sandbox/account/'.ssh/authorized_keys'
            self.assertEqual(target.read_text(),'ssh-ed25519 AAAA retain\n'+public+'\n')
            self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_seed_bootstrap_checks_content_before_installation(self):
        bootstrap=self.root/'fleet/bootstrap/bootstrap.py'
        def archive(data):
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w') as tar:
                item=tarfile.TarInfo('payload');item.mode=0o755;item.size=len(data)
                tar.addfile(item,io.BytesIO(data))
            return stream.getvalue()
        target=self.home/'.local/share/claude/versions/2.1.312'
        command=['python3','-I','-B',str(bootstrap),'seed','--host','pool-1','--seed','claude']
        bad=subprocess.run(command,input=archive(b'corrupt'),env=self.env,capture_output=True)
        self.assertNotEqual(bad.returncode,0)
        self.assertFalse(target.exists())
        good=subprocess.run(command,input=archive(ARTIFACT),env=self.env,capture_output=True)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(target.read_bytes(),ARTIFACT)
        self.assertEqual(target.stat().st_mode & 0o777,0o755)


    def test_authorization_preserves_missing_final_newline_and_other_markers(self):
        path=self.home/'.ssh/authorized_keys'
        original=b'# keep\nssh-ed25519 AAAA fleet-scale:pool-10\nssh-ed25519 BBBB final-without-newline'
        put(path,original)
        self.fleet.authorization('pool-1',(self.home/'member.pub').read_text())
        added=path.read_bytes()
        self.assertTrue(added.endswith(original))
        self.fleet.authorization('pool-1')
        self.assertEqual(path.read_bytes(),original)


    def test_heavy_probe_is_read_only_and_requires_released_tasks(self):
        import fcntl
        base=self.home/'src/rust/tmp/heavy'
        put(base/'host.lock','')
        snapshot={'version':1,'queue':hashlib.sha256(str(base).encode()).hexdigest(),
                  'installation':{'units':'fixture'},'tasks':{}}
        def probe():
            return subprocess.run(['python3','-I','-B','-c',MODULE['IDLE_PROBE']],env=self.env,capture_output=True,text=True)
        for phase,expected in ((None,True),('queued',False),('active',False),('finishing',False),('closing',False),('released',True)):
            snapshot['tasks']={} if phase is None else {'fixture':{'state':phase}}
            put(base/'state.json',json.dumps(snapshot))
            before=self.snapshot()
            result=probe()
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'idle':expected})
            self.assertEqual(self.snapshot(),before)
        with (base/'host.lock').open('rb') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            self.assertEqual(json.loads(probe().stdout),{'idle':False})
        snapshot['version']=2
        put(base/'state.json',json.dumps(snapshot))
        self.assertNotEqual(probe().returncode,0)
        (base/'state.json').unlink()
        self.assertNotEqual(probe().returncode,0)


    def test_missing_shared_source_refuses_without_fallback_or_allocation(self):
        source=self.home/'.config/fleet-scale/kache-store.env'
        source.unlink()
        # The old destination must never be used as a source fallback.
        put(self.home/'.config/kache/store.env','UNRELATED-PRIVATE-FIXTURE')
        result=self.invoke('up')
        self.assertEqual(result.returncode,1)
        self.assertIn('~/.config/fleet-scale/kache-store.env',result.stderr)
        self.assertIn('--local-only-kache',result.stderr)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.fleet.registry.read()['members'],{})
        self.assertFalse(self.fleet.registry.path.exists())

    def test_local_only_skips_delivery_and_persists_machine_env(self):
        (self.home/'.config/fleet-scale/kache-store.env').unlink()
        result=self.invoke('up','--local-only-kache')
        self.assertEqual(result.returncode,0,result.stderr)
        member=self.fleet.registry.read()['members']['pool-1']
        self.assertTrue(member['local_only_kache'])
        self.assertFalse((self.home/'remote-credential').exists())
        log=(self.home/'ssh.log').read_text()
        self.assertNotIn('hashlib.file_digest',log)
        self.assertNotIn('bootstrap.py kache',log)
        self.assertNotIn('PRIVATE-KACHE',result.stdout+result.stderr+log)
        module=runpy.run_path(str(SOURCE/'tools/fleet-sync'),run_name='local_only_sync')
        declarations=module['Declarations'](SOURCE,self.home,'pool-1')
        self.assertEqual(declarations.hosts['pool-1']['machine_env']['KACHE_LOCAL_ONLY'],1)
        self.assertNotIn('KACHE_LOCAL_ONLY',tomllib.loads((SOURCE/'fleet/pool.toml').read_text())['template']['machine_env'])
        # A fresh process/release still reads the member's non-secret choice.
        script='import pathlib,runpy; d=runpy.run_path('+repr(str(SOURCE/'tools/fleet-sync'))+')["Declarations"](pathlib.Path('+repr(str(SOURCE))+'),pathlib.Path.home(),"pool-1"); print(d.hosts["pool-1"]["machine_env"]["KACHE_LOCAL_ONLY"])'
        self.assertEqual(subprocess.check_output(['python3','-I','-B','-c',script],env=self.env,text=True).strip(),'1')

    def test_exact_distinct_paths_streaming_and_destination_permissions(self):
        import shlex
        source=self.home/'.config/fleet-scale/kache-store.env'
        destination_home=self.directory/'member-home'
        destination=destination_home/'.config/kache/store.env'
        destination.parent.mkdir(parents=True,mode=0o755)
        destination.parent.chmod(0o755)
        payload=b'PRIVATE-STREAMED-FIXTURE-'*50000
        put(source,payload)
        self.assertEqual(self.fleet.config['kache_source'],'~/.config/fleet-scale/kache-store.env')
        self.assertEqual(self.fleet.config['kache_destination'],'~/.config/kache/store.env')
        globals_=Fleet.credential.__globals__
        original=globals_['opened']
        requested=[]
        case=self
        class StreamingOnly:
            def __init__(self, stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def __getattr__(self,name):return getattr(self.stream,name)
            def read(self,*args):raise AssertionError('source must not be read into a variable')
            def readinto(self,buffer):
                case.assertLessEqual(len(buffer),262144)
                requested.append(len(buffer))
                return self.stream.readinto(buffer)
        def guarded(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return StreamingOnly(stream) if Path(path)==source else stream
        def remote(member,command,stdin=None,**kwargs):
            arguments=shlex.split(command)
            self.assertEqual(arguments[-1],'.config/kache/store.env')
            result=subprocess.run(arguments,stdin=stdin,env=dict(self.env,HOME=str(destination_home)),capture_output=True,check=True)
            return result.stdout
        with patch.dict(globals_,opened=guarded),patch.object(self.fleet,'ssh',side_effect=remote):
            self.fleet.credential({})
        self.assertTrue(requested)
        self.assertEqual(destination.read_bytes(),payload)
        self.assertEqual(destination.stat().st_mode & 0o777,0o600)
        self.assertEqual(destination.parent.stat().st_mode & 0o777,0o700)
        self.assertFalse((destination_home/'.config/fleet-scale/kache-store.env').exists())

    def test_shared_bootstrap_selectors_and_dropin_match_renderer(self):
        import types
        module=runpy.run_path(str(self.root/'fleet/bootstrap/bootstrap.py'))
        bootstrap=module['Bootstrap'](types.SimpleNamespace(host='pool-1',local_only_kache=False,dry_run=False))
        bootstrap.member()
        destination=self.home/'.config/kache/store.env'
        put(destination,'PRIVATE-FIXTURE-DO-NOT-READ')
        original=Path.read_text
        def forbid_credential(path,*args,**kwargs):
            self.assertNotEqual(path,destination)
            return original(path,*args,**kwargs)
        calls=[]
        with patch.object(Path,'read_text',forbid_credential),patch.object(bootstrap,'run',side_effect=lambda *args,**kwargs:calls.append(args)):
            bootstrap.kache()
        config=tomllib.loads((self.home/'.config/kache/config.toml').read_text())
        self.assertFalse(config['cache']['local_only'])
        self.assertEqual(config['cache']['local_max_size'],'40GiB')
        self.assertEqual(config['cache']['auto_recover_min_free_bytes'],80*1024**3)
        self.assertEqual(config['cache']['remote']['endpoint'],'http://10.80.0.13:3900')
        dropin=self.home/'.config/systemd/user/kache.service.d/20-shared-store.conf'
        self.assertIn('EnvironmentFile=%h/.config/kache/store.env',dropin.read_text())
        self.assertEqual(calls,[('systemctl','--user','daemon-reload'),('systemctl','--user','restart','kache.service')])
        sync=runpy.run_path(str(SOURCE/'tools/fleet-sync'),run_name='shared_sync')
        declarations=sync['Declarations'](SOURCE,self.home,'pool-1')
        self.assertNotIn('KACHE_LOCAL_ONLY',declarations.hosts['pool-1']['machine_env'])
        runner=sync['Runner'](types.SimpleNamespace(check=True,timer=False,resume_fd=None),declarations,'pool-1')
        with patch.object(Path,'read_text',forbid_credential):
            runner.kache_config()
        self.assertFalse(any(row['result'] in ('failed','drift') for row in runner.state['items']),runner.state['items'])


def shlex_quote(value):
    import shlex
    return shlex.quote(value)


def state_test(state):
    def test(self):
        member=self.up()
        data=self.fleet.registry.read()
        data['members']['pool-1']['state']=state
        self.fleet.registry.write(data)
        result=self.invoke('down','pool-1')
        self.assertEqual(result.returncode,0,result.stderr)
        data=self.fleet.registry.read()
        self.assertEqual(data['members'],{})
        self.assertEqual(len(data['retired']),1)
        self.assertEqual(self.servers,{})
    return test


for _state in MODULE['STATES']:
    setattr(ScaleTest,'test_down_from_'+_state,state_test(_state))


def failure_test(fragment, step):
    def test(self):
        result=self.invoke('up',FAIL_SSH=fragment)
        self.assertEqual(result.returncode,1,result.stderr)
        member=self.fleet.registry.read()['members']['pool-1']
        self.assertEqual(member['step'],step)
        listing=self.invoke('list')
        self.assertIn(step,listing.stdout)
        self.assertEqual(self.invoke('down','pool-1','--force').returncode,0)
        self.assertEqual(self.servers,{})
        self.assertNotIn('fleet-scale:pool-1',(self.home/'.ssh/authorized_keys').read_text())
    return test


for _label,_fragment,_step in (
        ('archive','tar -xf','root'),('root','root.sh','root'),('copy','cp -a','root'),
        ('member_key','fleet-member.pub','member-key'),('central_trust','mv "$tmp" ~/.ssh/known_hosts','member-key'),
        ('seed','bootstrap.py seed','seeds'),('credential','hashlib.file_digest','credential'),
        ('member_settings','bootstrap.py member','member-settings'),('kache','bootstrap.py kache','kache'),
        ('user','user.sh','user'),('heavy_install','--install-reconciler','user'),
        ('check','fleet-sync --check','verify'),('versions','--version','verify'),
        ('heavy','heavy --installed','verify'),('timer','is-active','verify')):
    setattr(ScaleTest,'test_failure_'+_label,failure_test(_fragment,_step))


if __name__=='__main__':
    unittest.main()
