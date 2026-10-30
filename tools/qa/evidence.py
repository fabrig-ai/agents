"""Walk evidence snapshots. No login files, services, or legacy imports."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

CAP = 2048 * 1024
MAX_ENTRIES = 4096
MAX_DEPTH = 32
MAX_SECONDS = 5
SECRET = re.compile(
    r'-----BEGIN [^\n-]*PRIVATE KEY-----|'
    r'(?<![\w-])(?:gh[pousr]_[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_-]{20,}|'
    r'sk-[A-Za-z0-9_-]{20,})|sk-ant-|xox[abpr]-|AKIA[A-Z0-9]{16}|'
    r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
KEYS = r'password|passwd|secret|token|api_key|client_secret|access_token|refresh_token|private_key'
VALUE = r'''(?:"[^"\n]*"|'[^'\n]*'|\$\{\{.*?\}\}|\$\{[^}\n]*\}|<[^>\n]*>|(?:\\.|[^\s,;}&])+)+'''
ASSIGN = re.compile(rf'''(?i)(?<![\w-])["']?(?:{KEYS})["']?\s*[:=]\s*({VALUE})''')
PARAM = re.compile(r'(?i)[?&#](?:code|token|secret|key|password|access_token|refresh_token|id_token|client_secret|signature)=([^&#\s]*)')
HEADER = re.compile(r'''(?i)\b(?P<name>(?:Proxy-)?Authorization|(?:Set-)?Cookie)["']?[ \t]*:[ \t]*(?:"(?P<double>[^"\r\n]*)"|'(?P<single>[^'\r\n]*)'|(?P<plain>[^\r\n]+))''')
FORBIDDEN = re.compile(r'(?i)(?:^|[-_.])(cookies?|password|passwd|secret|token|credentials?|netrc)(?:$|[-_.])')


class Refusal(Exception):
    def __init__(self, path, rule, digest='', line=None):
        self.rule = rule
        self.digest = digest or hashlib.sha256((path + rule).encode()).hexdigest()
        super().__init__(f'{path}' + (f':{line}' if line else '') + f': {rule}')


def placeholder(value):
    value = value.strip()
    # Remove only a matching whole quote pair and harmless trailing punctuation.
    value = value.rstrip(',;.') if value not in ('...', '…') else value
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        value = value[1:-1].strip()
    return (not value or value.lower() in ('null', 'true', 'false', '[masked]')
            or re.fullmatch(r'[A-Z][A-Z0-9_]*|<[^<>]*>|\.{3,}|…|\*+|@[A-Za-z0-9_./-]+', value)
            or re.fullmatch(r'\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$\{\{[^\n]*\}\}', value))


def scan(text):
    """Return a rule only; never include the matched value in a diagnostic."""
    if SECRET.search(text):
        return 'key/jwt'
    if re.search(r'(?i)(?:^|\n)#\s*Netscape.*Cookie', text):
        return 'header/cookie-jar'
    for line in text.splitlines():
        if re.match(r'[^\t]+\t(?:TRUE|FALSE)\t[^\t]*\t(?:TRUE|FALSE)\t-?\d+\t[^\t]+\t.+', line):
            return 'header/cookie-jar'
        for match in HEADER.finditer(line):
            value = next(match[group] for group in ('double', 'single', 'plain') if match[group] is not None)
            if match['name'].lower().endswith('authorization'):
                fields = value.split(None, 1)
                if len(fields) == 2 and not placeholder(fields[1]):
                    return 'header/cookie-jar'
            else:
                for number, pair in enumerate(value.split(';')):
                    key, equals, part = pair.partition('=')
                    if (number and match['name'].lower() == 'set-cookie' and key.strip().lower()
                            in ('path', 'domain', 'expires', 'max-age', 'samesite')):
                        continue
                    if equals and not placeholder(part):
                        return 'header/cookie-jar'
    for match in re.finditer(r'(?i)https?://([^/@\s]+)@', text):
        if not placeholder(match[1].partition(':')[2] or match[1]):
            return 'link'
    for match in PARAM.finditer(text):
        if not placeholder(match[1]):
            return 'link'
    for match in ASSIGN.finditer(text):
        if not placeholder(match[1]):
            return 'assigned/user'
    for match in re.finditer(rf'''(?:^|\s)(?:-u\s*|--user(?:=|\s+))({VALUE})''', text):
        value = match[1].strip("\"'")
        if ':' in value and not placeholder(value.partition(':')[2]):
            return 'assigned/user'
    return None


def path_rule(path):
    """A prefix must not hide a shape recognized at the start of a component."""
    return next((rule for part in (path, *path.split('/')) if (rule := scan(part))), None)


class Traversal:
    def __init__(self):
        self.deadline = time.monotonic() + MAX_SECONDS
        self.entries = 0

    def check(self, depth=0):
        if depth > MAX_DEPTH or time.monotonic() >= self.deadline:
            raise Refusal('source', 'enumeration bound')

    def take(self, depth=0):
        self.check(depth)
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            raise Refusal('source', 'enumeration bound')

    def names(self, parent, depth):
        self.check(depth)
        names = []
        # Bound memory and time before sorting; listdir would materialize everything.
        with os.scandir(parent) as entries:
            for entry in entries:
                self.take(depth)
                names.append(entry.name)
        self.check(depth)
        return sorted(names)


def forbidden(path):
    return any(FORBIDDEN.search(part) or part.lower() in ('auth.json', 'id_rsa', 'id_ed25519')
               or re.fullmatch(r'(?i)login(?:\..*)?', part)
               or part.lower().endswith(('.header', '.headers', '.pem', '.key', '.env'))
               for part in path.split('/'))


def checked(info, path, directory=False):
    if (info.st_uid != os.getuid() or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or not directory and info.st_nlink != 1):
        raise Refusal(path, 'kind/binary')


@contextmanager
def opened_directory(path):
    """Walk every component with openat; a renamed ancestor cannot redirect us."""
    parts = Path(path).absolute().parts
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        checked(os.fstat(descriptor), 'source', directory=True)
        yield descriptor
    finally:
        os.close(descriptor)


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def snapshot(directory, metadata, cap=CAP):
    """Snapshot the allowlist once, then scan and return those exact bytes."""
    digest = hashlib.sha256()
    traversal = Traversal()
    entries, omissions, files = [], [], {}
    try:
        with opened_directory(directory) as root:
            def collect(parent, prefix='', group='documents', depth=0):
                for number, name in enumerate(traversal.names(parent, depth), 1):
                    path = prefix + name
                    # Unsafe names never appear in diagnostics or an index.
                    if any(ord(c) < 32 or 127 <= ord(c) < 160 or c in '\u2028\u2029' for c in name):
                        raise Refusal(f'{prefix or "source/"}entry {number}', 'kind/binary')
                    if path_rule(path):
                        raise Refusal(f'{prefix or "source/"}entry {number}', 'path secret-shape')
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if not prefix and name not in ('brief.md', 'plan.md', 'notes.md', 'report.md', 'scripts', 'evidence') \
                            and not re.fullmatch(r'report-[1-9][0-9]*\.md', name):
                        omissions.append(dict(entry=number, reason='outside allowlist'))
                        continue
                    digest.update(path.encode('utf-8', errors='surrogateescape'))
                    digest.update(repr(signature(info)).encode())
                    if forbidden(path):
                        raise Refusal(path, 'name')
                    is_dir = stat.S_ISDIR(info.st_mode)
                    checked(info, path, directory=is_dir)
                    if is_dir:
                        if not prefix and name not in ('scripts', 'evidence'):
                            raise Refusal(path, 'kind/binary')
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        try:
                            checked(os.fstat(child), path, directory=True)
                            collect(child, path + '/', group if prefix else name, depth + 1)
                        finally:
                            os.close(child)
                    else:
                        if not prefix and name in ('scripts', 'evidence'):
                            raise Refusal(path, 'kind/binary')
                        entries.append((path, group, info))
            collect(root)
            kept = list(entries)
            for group in ('evidence', 'scripts'):
                if sum(info.st_size for _, _, info in kept) <= cap:
                    break
                removed = [e for e in kept if e[1] == group]
                kept = [e for e in kept if e[1] != group]
                if removed:
                    omissions.append(dict(group=group, files=len(removed), bytes=sum(e[2].st_size for e in removed), reason='size'))
            if sum(info.st_size for _, _, info in kept) > cap:
                raise Refusal('documents', 'size')
            for path, group, info in kept:
                traversal.check()
                parent = os.dup(root)
                try:
                    parts = path.split('/')
                    for part in parts[:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        os.close(parent)
                        parent = child
                        checked(os.fstat(parent), path, directory=True)
                    fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    with os.fdopen(fd, 'rb') as source:
                        before = os.fstat(source.fileno())
                        checked(before, path)
                        if signature(before) != signature(info):
                            raise Refusal(path, 'changed during snapshot')
                        data = source.read(cap + 1)
                        if len(data) > cap or signature(os.fstat(source.fileno())) != signature(before):
                            raise Refusal(path, 'changed during snapshot')
                    digest.update(data)
                    try:
                        text = data.decode('utf-8')
                    except UnicodeError:
                        raise Refusal(path, 'kind/binary') from None
                    if '\0' in text:
                        raise Refusal(path, 'kind/binary')
                    rule = scan(text)
                    if rule:
                        line = next((i for i, line in enumerate(text.splitlines(), 1) if scan(line)), 1)
                        raise Refusal(path, rule, line=line)
                    files[path] = data
                finally:
                    os.close(parent)
        for group in ('evidence', 'scripts', None):
            index = dict(metadata, entries=sorted(files), files=len(files), bytes=sum(map(len, files.values())), omissions=omissions)
            data = (json.dumps(index, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()
            if sum(map(len, files.values())) + len(data) <= cap:
                break
            if group is None:
                raise Refusal('documents and index', 'size')
            removed = [name for name in files if name.startswith(group + '/')]
            if removed:
                omissions.append(dict(group=group, files=len(removed), bytes=sum(len(files[n]) for n in removed), reason='size'))
                for name in removed:
                    del files[name]
        traversal.check()
        for number, name in enumerate(index['entries'], 1):
            if path_rule(name):
                raise Refusal(f'index entry {number}', 'path secret-shape')
        rule = scan(data.decode())
        traversal.check()
        if rule:
            raise Refusal('index.json', rule)
        files['index.json'] = data
        return files, index
    except Refusal as error:
        error.digest = hashlib.sha256(digest.digest() + str(error).encode()).hexdigest()
        raise
    except (OSError, UnicodeError, RecursionError):
        raise Refusal('source', 'kind/binary', digest.hexdigest()) from None


def read_snapshot(directory):
    """Recheck a frozen archive without following any path component."""
    traversal = Traversal()
    try:
        with opened_directory(directory) as root:
            def read(path, number=0):
                traversal.take(len(path.split('/')) - 1)
                if path_rule(path):
                    raise Refusal(f'snapshot entry {number}', 'path secret-shape')
                if forbidden(path):
                    raise Refusal(f'snapshot entry {number}', 'name')
                parent = os.dup(root)
                try:
                    parts = path.split('/')
                    for part in parts[:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        os.close(parent)
                        parent = child
                        checked(os.fstat(parent), path, directory=True)
                    descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    with os.fdopen(descriptor, 'rb') as source:
                        before = os.fstat(source.fileno())
                        checked(before, path)
                        if before.st_size > CAP:
                            raise Refusal(path, 'size')
                        data = source.read(CAP + 1)
                        if signature(os.fstat(source.fileno())) != signature(before):
                            raise Refusal(path, 'changed during snapshot')
                    text = data.decode('utf-8')
                    if '\0' in text:
                        raise Refusal(path, 'kind/binary')
                    rule = scan(text)
                    if rule:
                        raise Refusal(path, rule)
                    return data
                finally:
                    os.close(parent)
            index_bytes = read('index.json')
            index = json.loads(index_bytes)
            names = index['entries']
            if isinstance(names, list) and len(names) + 1 > MAX_ENTRIES:
                raise Refusal('index.json', 'enumeration bound')
            if (not isinstance(names, list) or not all(isinstance(n, str) and re.fullmatch(
                    r'(?:brief|plan|notes|report)\.md|report-[1-9][0-9]*\.md|(?:scripts|evidence)/[^\x00-\x1f]+', n)
                    and all(p not in ('', '.', '..') for p in n.split('/')) for n in names)
                    or len(set(names)) != len(names)):
                raise Refusal('index.json', 'invalid snapshot index')
            for number, name in enumerate(names, 1):
                traversal.check()
                if path_rule(name):
                    raise Refusal(f'index entry {number}', 'path secret-shape')
            files = {name: read(name, number) for number, name in enumerate(names, 1)}
            if index['files'] != len(files) or index['bytes'] != sum(map(len, files.values())):
                raise Refusal('index.json', 'invalid snapshot index')
            files['index.json'] = index_bytes
            if sum(map(len, files.values())) > CAP:
                raise Refusal('snapshot', 'size')
            traversal.check()
            return files
    except Refusal:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RecursionError):
        raise Refusal('snapshot', 'kind/binary') from None


def tree_digest(files):
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode() + b'\0' + str(len(data)).encode() + b'\0' + data)
    return digest.hexdigest()


def directory_bytes(directory):
    """Metadata only, never follow links or open file contents for admission."""
    traversal = Traversal()
    def size(parent, depth=0):
        total = 0
        for name in traversal.names(parent, depth):
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            total += info.st_size
            if stat.S_ISDIR(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    total += size(fd, depth + 1)
                finally:
                    os.close(fd)
        return total
    try:
        with opened_directory(directory) as root:
            return os.fstat(root).st_size + size(root)
    except FileNotFoundError:
        if not Path(directory).exists():
            return 0
        raise
