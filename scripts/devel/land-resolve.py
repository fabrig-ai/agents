#!/usr/bin/env python3
"""Settle a stopped rebase's mechanical conflicts, or none of them.

  python3 -I -B land-resolve.py WORKTREE

Read the index's three stages, never conflict markers in the worktree.
Exit 0 after committing every resolution, 1 for conflicts left to a person,
2 when no rebase is stopped on conflicts or Git fails (landing-flow.md, 3).
"""
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


def resolve(worktree):
    def git(*args, data=None, env=None):
        result = subprocess.run(['git', '-C', str(worktree), *args], input=data,
                                capture_output=True, env=env)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace').strip())
        return result.stdout

    def value(*args):
        return git(*args).decode().strip()

    if not any(Path(value('rev-parse', '--path-format=absolute', '--git-path', state)).is_dir()
               for state in ('rebase-merge', 'rebase-apply')):
        raise RuntimeError('no rebase stopped on conflicts')
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
            if path not in RULES:
                raise Stop('no rule for it')
            modes = {mode for mode, _ in stages.values()}
            if set(stages) != {'1', '2', '3'} or len(modes) != 1 or not modes <= {'100644', '100755'}:
                raise Stop('not a content conflict')
            try:
                texts = [git('cat-file', 'blob', stages[str(n)][1]).decode() for n in (1, 2, 3)]
            except UnicodeError:
                raise Stop('not a UTF-8 table') from None
            text, how = RULES[path](*texts)
            results[path] = (text.encode(), how, stages['2'][0])
        except Stop as error:
            stops.append((path, str(error)))
    if stops:
        for path, reason in stops:
            print(f'stops {path}: {reason}')
        return 1
    # Preview in a private index, including callers' already-staged clean paths.
    with tempfile.TemporaryDirectory(prefix='land-resolve-index-') as directory:
        index = Path(directory) / 'index'
        shutil.copyfile(value('rev-parse', '--path-format=absolute', '--git-path', 'index'), index)
        env = dict(os.environ, GIT_INDEX_FILE=str(index))
        for path, (contents, _, mode) in results.items():
            oid = git('hash-object', '-w', '--stdin', data=contents).decode().strip()
            git('update-index', '--add', '--cacheinfo', mode, oid, path, env=env)
        if git('write-tree', env=env).strip() == git('rev-parse', 'HEAD^{tree}').strip():
            for path in results:
                print(f'stops {path}: the resolution leaves nothing to commit')
            return 1
    message = git('show', '-s', '--format=%B', stopped)
    trailers = [arg for path, (_, how, _) in results.items()
                for arg in ('--trailer', f'Rebase-Resolved: {path}: {how}')]
    message = git('interpret-trailers', '--where', 'end', '--if-exists', 'add', *trailers, data=message)
    author = git('show', '-s', '--format=%an%x00%ae%x00%aI', stopped).decode().strip().split('\0')
    for path, (contents, _, _) in results.items():
        (worktree / path).write_bytes(contents)
        git('add', '--', path)
    git('-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false', 'commit', '--quiet',
        '--cleanup=verbatim', '-F', '-', data=message,
        env=dict(os.environ, GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1], GIT_AUTHOR_DATE=author[2]))
    commit = value('rev-parse', '--short', 'HEAD')
    subject = value('show', '-s', '--format=%s', stopped)
    for path, (_, how, _) in results.items():
        print(f'resolved {path} in {commit} ({subject}): {how}')
    return 0


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise RuntimeError('usage: land-resolve.py WORKTREE')
        sys.exit(resolve(Path(sys.argv[1]).resolve()))
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f'land-resolve: {error}', file=sys.stderr)
        sys.exit(2)
