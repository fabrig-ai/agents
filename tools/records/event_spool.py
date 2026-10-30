"""Host-local raw events, with atomic two-hour retention. Standard library only."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile

HOURS = 2
SOURCES = ('runs', 'queue', 'heavy', 'sessions', 'claims', 'leases', 'post', 'post-sent', 'watch')


def root():
    return Path.home() / 'src/fabrig/events'


def stamp(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.utcoffset() is None:
        raise ValueError('event time needs offset')
    return value.timestamp()


def validate(row, source):
    if (not isinstance(row, dict) or row.get('source') != source or
            any(not isinstance(row.get(k), str) or not row[k] for k in ('id', 'host', 'kind', 'time'))):
        raise ValueError('invalid spool event')
    return stamp(row['time'])


def read(directory, source, now):
    """Readers never mutate; absent sources are empty, malformed ones fail."""
    rows, seen = [], set()
    for path in sorted((directory / source).glob('????-??-??.jsonl')):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            at = validate(row, source)
            key = (row['host'], row['id'])
            if now - HOURS * 3600 <= at <= now and key not in seen:
                rows.append(row)
                seen.add(key)
    return sorted(rows, key=lambda r: stamp(r['time']))


def replace(path, rows):
    fd, sibling = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            for row in rows:
                out.write(json.dumps(row, sort_keys=True) + '\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(sibling, path)
    finally:
        if os.path.exists(sibling):
            os.unlink(sibling)


def append(source, rows, now, directory=None):
    """Caller retains its cursor/outbox until this succeeds; replay skips ids.

    The spool lock also serializes different callers, including a future watch
    collector. Each changed day is replaced as a whole; readers see complete files.
    """
    if source not in SOURCES:
        raise ValueError('invalid spool source')
    directory = root() if directory is None else directory
    target = directory / source
    for path in (directory.parent.parent, directory.parent, directory, target):
        if path.is_symlink():
            raise ValueError('spool symlink refused')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    lockpath = target / '.lock'
    if lockpath.is_symlink():
        raise ValueError('spool lock symlink refused')
    with lockpath.open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        days, seen = {}, set()
        paths = sorted(target.glob('????-??-??.jsonl'))
        existing = []
        for path in paths:
            if path.is_symlink():
                raise ValueError('spool day symlink refused')
            existing.extend(json.loads(line) for line in path.read_text().splitlines())
        for row in [*existing, *rows]:
            at = validate(row, source)
            # Drop historical context samples when replaying an old outbox.
            if at < now - HOURS * 3600 or (source == 'sessions' and row['kind'] == 'context'):
                continue
            key = (row['host'], row['id'])
            if key in seen:
                continue
            seen.add(key)
            day = datetime.fromtimestamp(at, timezone.utc).date().isoformat()
            days.setdefault(day, []).append(row)
        for day, kept in days.items():
            replace(target / (day + '.jsonl'), kept)
        for path in paths:
            if path.stem not in days:
                path.unlink()


def probe_source(path):
    """Ship this dependency with either self-contained SSH probe, not a host install."""
    dependency = Path(__file__).read_text()
    inline = 'import types\nevent_spool = types.ModuleType("event_spool")\nexec(' + repr(dependency) + ', event_spool.__dict__)'
    return Path(path).read_text().replace('import event_spool', inline)
