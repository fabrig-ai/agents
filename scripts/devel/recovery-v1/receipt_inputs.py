"""Best-effort command inputs; never change the real Git index or refs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def capture(cwd):
    result = {}
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    # Always seed from the worktree's real index, even inside a Git caller.
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                'GIT_NAMESPACE', 'GIT_SHALLOW_FILE', 'GIT_PREFIX'):
        env.pop(key, None)
    def git(*args, data=None, raw=False):
        value = subprocess.check_output(['git', '-C', str(cwd), *args], env=env, input=data,
                                        stderr=subprocess.DEVNULL, timeout=10)
        return value if raw else value.decode().strip()
    try:
        root = git('rev-parse', '--show-toplevel')
        try:
            result['head'] = git('rev-parse', '--verify', 'HEAD')
        except subprocess.SubprocessError:
            pass  # An unborn worktree still has inputs.
        index = Path(git('rev-parse', '--path-format=absolute', '--git-path', 'index'))
        with tempfile.TemporaryDirectory(prefix='heavy-inputs-') as directory:
            temporary = Path(directory) / 'index'
            if index.exists():
                shutil.copyfile(index, temporary)
            env['GIT_INDEX_FILE'] = str(temporary)
            tracked = git('-C', root, 'ls-files', '-z', raw=True)
            git('-C', root, 'update-index', '--no-assume-unchanged', '-z', '--stdin', data=tracked)
            git('-C', root, 'update-index', '--no-skip-worktree', '-z', '--stdin', data=tracked)
            git('-C', root, 'add', '-A', '--', '.')
            result['inputs'] = git('write-tree')
    except (OSError, subprocess.SubprocessError, UnicodeError):
        pass
    return result


if __name__ == '__main__':
    print(json.dumps(capture(Path.cwd())))
