"""Private HOME helpers for the records/lease contract tests."""
from io import BytesIO, TextIOWrapper
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch


def call_main(main, argv, env, data=b'', *, text=False):
    """Run a command's parser/entry point without another Python interpreter."""
    stdin = TextIOWrapper(BytesIO(data), encoding='utf-8')
    stdout = TextIOWrapper(BytesIO(), encoding='utf-8')
    stderr = TextIOWrapper(BytesIO(), encoding='utf-8')
    umask = os.umask(0o077)
    os.umask(umask)
    with stdin, stdout, stderr:
        with patch.dict(os.environ, env, clear=True), patch.object(sys, 'argv', argv), \
             patch.object(sys, 'stdin', stdin), patch.object(sys, 'stdout', stdout), \
             patch.object(sys, 'stderr', stderr):
            try:
                code = main()
            except SystemExit as error:
                code = error.code
            finally:
                os.umask(umask)
        stdout.flush()
        stderr.flush()
        out, err = stdout.buffer.getvalue(), stderr.buffer.getvalue()
    if text:
        out, err = out.decode(), err.decode()
    return subprocess.CompletedProcess(argv, code, out, err)


class RecordsSeed:
    """Build once per class; each test gets independent mutable Git copies."""
    seed_files = {'README.md': '# Records\n'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        temporary = tempfile.TemporaryDirectory(prefix='records-seed-')
        cls.addClassCleanup(temporary.cleanup)
        cls._records_seed = Path(temporary.name)
        cls._build_seed(cls._records_seed)

    @classmethod
    def _build_seed(cls, root):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'RECORDS_'))}
        env.update(HOME=str(root), XDG_CONFIG_HOME=str(root / '.config'),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        def git(*args):
            subprocess.run(['git', *args], env=env, check=True, capture_output=True)
        git('init', '--bare', '--initial-branch=main', str(root / 'origin.git'))
        git('clone', str(root / 'origin.git'), str(root / 'seed'))
        # A relative remote keeps each copied seed tied to its private origin.
        git('-C', str(root / 'seed'), 'config', 'remote.origin.url', '../origin.git')
        for name, content in cls.seed_files.items():
            path = root / 'seed' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git('-C', str(root / 'seed'), 'add', '.')
        git('-C', str(root / 'seed'), 'commit', '-m', 'initial records')
        git('-C', str(root / 'seed'), 'push', 'origin', 'main')

    def copy_records_seed(self):
        if not hasattr(self, '_records_seed'):
            # The status-page contract also constructs a fixture by hand.
            self._build_seed(self.home)
            return
        for name in ('origin.git', 'seed'):
            shutil.copytree(self._records_seed / name, self.home / name)
