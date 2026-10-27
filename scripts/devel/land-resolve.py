#!/usr/bin/env python3
"""Finish a stopped rebase whose every stop a rule settles (landing-flow.md, 3).

  python3 -I -B land-resolve.py [--cargo-lock] [--later] WORKTREE
  python3 -I -B land-resolve.py --regenerate WORKTREE TIP PATH...

Each settled stop is committed with Rebase-Resolved trailers before continuing.
Generated files take main's side, then scripts/regenerate.sh rewrites them through
heavy once the rebase finishes. --cargo-lock takes main's root lock for a repin;
--later prints `regenerate PATH` lines instead, for --regenerate after repinning.

Exit 0: done. 1: a stop no rule settles (left stopped), or regeneration refused.
After taking main's side of a generated file, either failure undoes the whole
rebase. --regenerate likewise restores TIP on refusal. Exit 2: no rebase stopped
on conflicts, or Git failed.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


class Stop(Exception):
    """Why a path's conflict stays for a person."""


def cells(line):
    line = line.rstrip('\r\n')
    if not line.startswith('|') or not line.endswith('|'):
        raise Stop('a line outside the table rows')
    # An even run of backslashes leaves the pipe unescaped.
    parts, start = [], 1
    for i in range(1, len(line)):
        if line[i] != '|':
            continue
        back = i - 1
        while back >= 0 and line[back] == '\\':
            back -= 1
        if (i - back - 1) % 2 == 0:
            parts.append(line[start:i].strip())
            start = i + 1
    if start != len(line):
        raise Stop('a malformed row')
    return parts


def delimiter(line):
    try:
        parts = cells(line)
        return bool(parts) and all(re.fullmatch(r':?-+:?', cell) for cell in parts)
    except Stop:
        return False


def rows(lines, width):
    result = {}
    for line in lines:
        parts = cells(line)
        if not parts or len(parts) != width or not parts[0] or delimiter(line):
            raise Stop('a malformed row')
        key = parts[0]
        if key in result:
            raise Stop(f'duplicate row {key}')
        result[key] = line
    return result


def ordered(base, main, branch):
    common = base.keys() & main.keys() & branch.keys()
    orders = [[key for key in side if key in common] for side in (base, main, branch)]
    if orders[0] != orders[1] or orders[0] != orders[2]:
        raise Stop('rows reordered')


def merge_rows(base, main, branch, width):
    sides = [rows(side, width) for side in (base, main, branch)]
    old, ours, theirs = sides
    ordered(*sides)
    chosen, changes = {}, [[], []]
    for key in dict.fromkeys([*old, *ours, *theirs]):
        before, left, right = (side.get(key) for side in sides)
        if left != before and right != before and left != right:
            raise Stop(f'the row {key} changed on both sides')
        chosen[key] = right if left == before else left
    for changed, side in zip(changes, (ours, theirs)):
        # Place deletions beside their surviving base neighbours in the report.
        order = list(side)
        keys = list(old)
        for i, key in enumerate(keys):
            if key not in side:
                following = next((key for key in keys[i + 1:] if key in order), None)
                order.insert(order.index(following) if following is not None else len(order), key)
        for key in order:
            if side.get(key) != old.get(key):
                verb = 'added' if key not in old else 'deleted' if key not in side else 'changed'
                changed.append((key, verb))
    order = list(ours)
    previous = None
    for key in theirs:
        if key not in ours and chosen[key] is not None:
            index = order.index(previous) + 1 if previous in order else 0
            while index < len(order) and order[index] not in old and order[index] not in theirs:
                index += 1
            order.insert(index, key)
        if key in order and chosen[key] is not None:
            previous = key
    return [chosen[key] for key in order if chosen[key] is not None], changes


def tables(lines):
    """Table headers and row spans; non-table Markdown stays opaque."""
    result = []
    for i in range(1, len(lines)):
        if not delimiter(lines[i]):
            continue
        try:
            width = len(cells(lines[i - 1]))
        except Stop:
            continue
        if width != len(cells(lines[i])):
            continue
        end = i + 1
        while end < len(lines) and lines[end].startswith('|'):
            end += 1
        result.append((i - 1, end, width))
    return result


def table_rows(base, main, branch):
    """Merge conflicts confined to different Markdown table rows: (text, how)."""
    texts = (base, main, branch)
    size = max(32, max((len(line) for text in texts for line in text.splitlines()), default=0) + 1)
    with tempfile.TemporaryDirectory(prefix='land-resolve-merge-') as directory:
        paths = [Path(directory) / name for name in ('base', 'main', 'branch')]
        for path, text in zip(paths, texts):
            path.write_bytes(text.encode())
        merged = subprocess.run(['git', 'merge-file', '-p', '--diff3', f'--marker-size={size}',
                                 str(paths[1]), str(paths[0]), str(paths[2])], capture_output=True)
    if merged.returncode < 0 or merged.returncode > 127:
        raise RuntimeError('git merge-file failed: ' + merged.stderr.decode(errors='replace').strip())
    lines = merged.stdout.decode().splitlines(keepends=True)
    starts = '<' * size
    ancestor, middle, end = '|' * size, '=' * size, '>' * size
    # Replace hunks with their merged rows; retain every cleanly merged byte.
    output, touched, changes = [], set(), [[], []]
    i = 0
    while i < len(lines):
        if not lines[i].startswith(starts):
            output.append(lines[i])
            i += 1
            continue
        current = tables(output)
        if not current or current[-1][1] != len(output):
            raise Stop('a line outside the table rows, or the header changed')
        table = len(current) - 1
        width = current[-1][2]
        sides = [[], [], []]
        side = 1
        i += 1
        while i < len(lines) and not lines[i].startswith(end):
            if lines[i].startswith(ancestor):
                side = 0
            elif lines[i].rstrip('\r\n') == middle:
                side = 2
            else:
                sides[side].append(lines[i])
            i += 1
        if i == len(lines):
            raise RuntimeError('git merge-file produced an incomplete conflict')
        settled, taken = merge_rows(*sides, width)
        output.extend(settled)
        touched.add(table)
        for target, source in zip(changes, taken):
            target.extend(source)
        i += 1
    if not touched:
        raise Stop('no table row conflict')
    # Check the complete affected tables too: a hunk can duplicate a clean row,
    # and a reorder can straddle two separate hunks.
    final_tables = tables(output)
    source_lines = [text.splitlines(keepends=True) for text in texts]
    source_tables = [tables(side) for side in source_lines]
    for number in sorted(touched):
        start, finish, width = final_tables[number]
        rows(output[start + 2:finish], width)
        sides = []
        for original, spans in zip(source_lines, source_tables):
            # A clean table insertion may shift its ordinal. Prefer its header.
            matches = [span for span in spans if original[span[0]:span[0] + 2] == output[start:start + 2]]
            if len(matches) == 1:
                first, last, count = matches[0]
            elif len(spans) == len(final_tables):
                first, last, count = spans[number]
            else:
                raise Stop('the table header changed')
            sides.append(rows(original[first + 2:last], count))
        ordered(*sides)
    how = []
    for label, taken in zip(('main', 'this commit'), changes):
        how.extend(f'{label} {verb} {key}' for key, verb in taken)
    return ''.join(output), 'table rows: ' + '; '.join(how)


RULES = {'docs/design/STATUS.md': table_rows}


class Repository:
    def __init__(self, worktree):
        self.worktree = worktree
        self.script = worktree / 'scripts/regenerate.sh'

    def git(self, *args, data=None, env=None):
        result = subprocess.run(['git', '-C', str(self.worktree), *args], input=data,
                                capture_output=True, env=env)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace').strip())
        return result.stdout

    def value(self, *args):
        return self.git(*args).decode().strip()

    def rebasing(self):
        return any(Path(self.value('rev-parse', '--path-format=absolute', '--git-path', state)).is_dir()
                   for state in ('rebase-merge', 'rebase-apply'))

    def owns(self, paths):
        if not self.script.is_file() or not os.access(self.script, os.X_OK):
            return False
        try:
            result = subprocess.run([str(self.script), '--owns', *paths], cwd=self.worktree,
                                    capture_output=True, check=False)
        except OSError as error:
            print(f'scripts/regenerate.sh --owns: {error}')
            return False
        # Keep the repository's explanation, even when --owns declines a rule.
        for line in (result.stdout + result.stderr).decode(errors='replace').splitlines():
            print(f'scripts/regenerate.sh --owns: {line}')
        return result.returncode == 0

    def undo(self, tip, paths):
        if self.rebasing():
            self.git('rebase', '--abort')
        else:
            # Remove before reset: TIP may track a path that main had deleted.
            untracked = self.git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
            for name in filter(None, untracked):
                path = self.worktree / os.fsdecode(name)
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
                parent = path.parent
                while parent != self.worktree and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            self.git('reset', '--hard', tip)
        print("undid the rebase: it had taken main's side of " + ', '.join(sorted(paths)))

    def regenerate(self, tip, paths):
        common = Path(self.value('rev-parse', '--path-format=absolute', '--git-common-dir'))
        name = common.parent.name if common.name == '.git' else common.name.removesuffix('.git')
        try:
            result = subprocess.run([str(Path(__file__).resolve().with_name('heavy')),
                '--tail', '60', 'scripts/regenerate.sh', *paths], cwd=self.worktree,
                capture_output=True, check=False,
                env=dict(os.environ, HEAVY_LABEL=f'land {name} regenerate'))
        except OSError as error:
            reason = str(error)
        else:
            stdout = result.stdout.decode(errors='replace').splitlines()
            stderr = result.stderr.decode(errors='replace').splitlines()
            if result.returncode:
                payload = [line for line in stdout if not line.startswith('heavy: ')]
                for line in payload:
                    print(f'scripts/regenerate.sh: {line}')
                if 'heavy: disk floor refused before payload start' in stderr:
                    reason = (f'heavy refused to run scripts/regenerate.sh (exit {result.returncode}): '
                              'disk floor refused before payload start')
                elif any(re.match(r'^heavy: task [0-9]+ ', line) for line in stdout):
                    verb = 'refused' if result.returncode == 3 else 'failed'
                    reason = f'scripts/regenerate.sh {verb} (exit {result.returncode})'
                    # A diagnostic starts at the last unindented line; build
                    # chatter before it must not bury the refusal.
                    start = next((i for i in range(len(payload) - 1, -1, -1)
                                  if payload[i] and not payload[i][0].isspace()), len(payload))
                    paragraph = [line.strip() for line in payload[start:] if line.strip()][:5]
                    if paragraph:
                        reason += ': ' + '; '.join(paragraph)
                else:
                    reason = f'heavy refused to run scripts/regenerate.sh (exit {result.returncode})'
                    if stderr:
                        reason += ': ' + stderr[-1].strip()
                log = next((match[1] for line in reversed(stdout)
                            if (match := re.match(r'^heavy: task [0-9]+ .* log (.+)$', line))), None)
                if log:
                    reason += f' (log {log})'
                for line in stdout:
                    if line.startswith('heavy: '):
                        print(line)
            else:
                reason = None
            for line in stderr:
                print(line)
        if reason:
            print(f'stops {", ".join(sorted(paths))}: {reason}')
            self.undo(tip, paths)
            return 1
        # NUL records retain spaces and quoted characters; disabling renames checks
        # both the removed and added path of a rename against the writer's contract.
        status = self.git('-c', 'status.renames=false', 'status', '--porcelain', '-z',
                          '--untracked-files=all')
        changed = sorted({os.fsdecode(entry[3:]) for entry in status.split(b'\0') if entry})
        if not changed:
            return 0
        if not self.owns(changed):
            for path in changed:
                print(f'stops {path}: scripts/regenerate.sh changed a path it does not own')
            self.undo(tip, paths)
            return 1
        before = self.value('rev-parse', '--short', 'HEAD')
        message = (f'regenerate.sh: rewrite {len(changed)} files after the rebase on {before}\n\n'
                   'Rebase-Resolved: scripts/regenerate.sh rewrote ' + ', '.join(changed) + '\n')
        self.git('add', '-A', '--', *changed)
        identity, timestamp, zone = self.value('var', 'GIT_COMMITTER_IDENT').rsplit(' ', 2)
        name, email = identity.rsplit(' <', 1)
        self.git('-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false',
                 'commit', '--quiet', '--cleanup=verbatim', '-F', '-', data=message.encode(),
                 env=dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email.removesuffix('>'),
                          GIT_AUTHOR_DATE=timestamp + ' ' + zone))
        print('regenerated ' + ', '.join(changed) + ' in ' + self.value('rev-parse', '--short', 'HEAD'))
        return 0


def settle(repo, cargo_lock):
    worktree, git, value = repo.worktree, repo.git, repo.value
    entries = {}
    for entry in git('ls-files', '-u', '-z').split(b'\0'):
        if entry:
            metadata, path = entry.split(b'\t', 1)
            mode, oid, stage = metadata.decode().split()
            entries.setdefault(os.fsdecode(path), {})[stage] = (mode, oid)
    if not entries:
        raise RuntimeError('no rebase stopped on conflicts')
    stopped = value('rev-parse', 'REBASE_HEAD')
    results, stops = {}, []
    for path, stages in entries.items():
        try:
            modes = {mode for mode, _ in stages.values()}
            if set(stages) != {'1', '2', '3'} or len(modes) != 1 or not modes <= {'100644', '100755'}:
                raise Stop('not a content conflict')
            if path == 'Cargo.lock' and cargo_lock:
                results[path] = (git('cat-file', 'blob', stages['2'][1]),
                                 "main's side, for the repin", stages['2'][0])
            elif path in RULES:
                try:
                    texts = [git('cat-file', 'blob', stages[str(n)][1]).decode() for n in (1, 2, 3)]
                except UnicodeError:
                    raise Stop('not a UTF-8 table') from None
                text, how = RULES[path](*texts)
                results[path] = (text.encode(), how, stages['2'][0])
            elif repo.owns([path]):
                results[path] = (git('cat-file', 'blob', stages['2'][1]),
                                 "main's side, for scripts/regenerate.sh", stages['2'][0])
            else:
                raise Stop('no rule for it')
        except Stop as error:
            stops.append((path, str(error)))
    if stops:
        for path, reason in stops:
            print(f'stops {path}: {reason}')
        return 1, []
    # Preview in a private index, including callers' already-staged clean paths.
    with tempfile.TemporaryDirectory(prefix='land-resolve-index-') as directory:
        index = Path(directory) / 'index'
        shutil.copyfile(value('rev-parse', '--path-format=absolute', '--git-path', 'index'), index)
        env = dict(os.environ, GIT_INDEX_FILE=str(index))
        for path, (contents, _, mode) in results.items():
            oid = git('hash-object', '-w', '--stdin', data=contents).decode().strip()
            git('update-index', '--add', '--cacheinfo', mode, oid, path, env=env)
        if (all(path in RULES for path in results)
                and git('write-tree', env=env).strip() == git('rev-parse', 'HEAD^{tree}').strip()):
            for path in results:
                print(f'stops {path}: the resolution leaves nothing to commit')
            return 1, []
    message = git('show', '-s', '--format=%B', stopped)
    trailers = [arg for path, (_, how, _) in results.items()
                for arg in ('--trailer', f'Rebase-Resolved: {path}: {how}')]
    message = git('interpret-trailers', '--where', 'end', '--if-exists', 'add', *trailers, data=message)
    author = git('show', '-s', '--format=%an%x00%ae%x00%aI', stopped).decode().strip().split('\0')
    for path, (contents, _, _) in results.items():
        (worktree / path).write_bytes(contents)
        git('add', '--', path)
    git('-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false', 'commit', '--quiet', '--allow-empty',
        '--cleanup=verbatim', '-F', '-', data=message,
        env=dict(os.environ, GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1], GIT_AUTHOR_DATE=author[2]))
    commit = value('rev-parse', '--short', 'HEAD')
    subject = value('show', '-s', '--format=%s', stopped)
    for path, (_, how, _) in results.items():
        print(f'resolved {path} in {commit} ({subject}): {how}')
    generated = [path for path, (_, how, _) in results.items()
                 if how == "main's side, for scripts/regenerate.sh"]
    return 0, generated


def resolve(worktree, cargo_lock=False, later=False):
    repo = Repository(worktree)
    if not repo.rebasing():
        raise RuntimeError('no rebase stopped on conflicts')
    original = Path(repo.value('rev-parse', '--path-format=absolute', '--git-path', 'rebase-merge/orig-head'))
    tip = original.read_text().strip() if original.is_file() else repo.value('rev-parse', 'ORIG_HEAD')
    generated = set()
    while repo.rebasing():
        code, paths = settle(repo, cargo_lock)
        if code:
            if generated:
                repo.undo(tip, generated)
            return code
        generated.update(paths)
        continued = subprocess.run(['git', '-C', str(worktree), '-c', 'core.hooksPath=/dev/null',
                                    'rebase', '--continue'], capture_output=True,
                                   env=dict(os.environ, GIT_EDITOR='true', GIT_SEQUENCE_EDITOR='true'))
        if continued.returncode and (not repo.rebasing() or not repo.git('ls-files', '-u')):
            raise RuntimeError(continued.stderr.decode(errors='replace').strip())
    paths = sorted(generated)
    if later:
        for path in paths:
            print(f'regenerate {path}')
        return 0
    return repo.regenerate(tip, paths) if paths else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo-lock', action='store_true')
    parser.add_argument('--later', action='store_true')
    parser.add_argument('--regenerate', action='store_true')
    parser.add_argument('worktree', type=Path)
    parser.add_argument('remaining', nargs='*')
    args = parser.parse_args()
    if ((args.regenerate and (args.cargo_lock or args.later or len(args.remaining) < 2))
            or (not args.regenerate and args.remaining)):
        parser.error('expected [--cargo-lock] [--later] WORKTREE or --regenerate WORKTREE TIP PATH...')
    try:
        worktree = args.worktree.resolve()
        if args.regenerate:
            sys.exit(Repository(worktree).regenerate(args.remaining[0], sorted(set(args.remaining[1:]))))
        sys.exit(resolve(worktree, args.cargo_lock, args.later))
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f'land-resolve: {error}', file=sys.stderr)
        sys.exit(2)
