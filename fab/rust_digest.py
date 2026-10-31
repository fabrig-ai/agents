"""Rust branch digests and crate inventories (docs/design/fab.md, 13.11).

Text scans are deliberately smaller than a Rust parser. Git and the old-forms
ratchet run only through the runner; build reads two already materialized trees.
"""

from __future__ import annotations

import difflib
import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fab import atomic
from fab.calls import Signature
from fab.digest import Change, Function, added_lines, outside
from fab.plan import Task
from fab.sh import Failed, Runner, run

SIZE_CAP = 60
DIGEST_LIMIT = 8_000
LIST_CAP = 30
LINE_CAP = 160
KINDS = ("production", "tests", "docs")
IDENTIFIER = r"(?:r#)?[A-Za-z_]\w*"
MODIFIERS = r"(?:(?:async|unsafe|const|default)\s+|extern\s+)*"
PUBLIC = re.compile(r"\bpub\s+" + MODIFIERS
                    + r"(?P<kind>fn|struct|enum|trait|type|const|mod)\s+(?P<name>" + IDENTIFIER + r")")
FN = re.compile(r"\bfn\s+(?P<name>" + IDENTIFIER + r")")
TOKEN = re.compile(
    r'//[^\n]*|/\*|(?:br|cr|r)(?P<hashes>#{0,255})"'
    r'|"(?:\\[\s\S]|[^"\\])*"'
    r"|'(?:[^'\\\n]|\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F_]+\}|[^\n]))'"
)
BLOCK = re.compile(r"/\*|\*/")
CFG_TEST = re.compile(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]")
COUNT = re.compile(r"^(\S+): count (\d+), baseline (\d+)(?:; lower with .*)?$")


@dataclass(frozen=True)
class Ratchet:
    """One form's actual counts in a touched top-level tree, missing sides zero. new: the
    base does not count the form (a new tree, or a form the branch adds to the ratchet),
    so its tip count is a baseline, not a rise."""

    tree: str
    form: str
    base: int
    tip: int
    new: bool = False


@dataclass(frozen=True)
class Digest:
    """A Rust branch's changes, public declarations, size flags and ratchet counts."""

    run: str
    task: str
    kind: str
    branch: str
    base: str
    tip: str
    changes: tuple[Change, ...]
    added: tuple[Signature, ...]
    removed: tuple[Signature, ...]
    outside: tuple[str, ...]
    long: tuple[Function, ...]
    ratchets: tuple[Ratchet, ...]


def _code(text: str) -> str:
    """Mask comments and literals, retaining offsets and newlines (including raw strings)."""
    pieces = []
    position = 0
    while token := TOKEN.search(text, position):
        pieces.append(text[position:token.start()])
        end = token.end()
        if token.group() == "/*":
            depth = 1
            while depth and (marker := BLOCK.search(text, end)):
                depth += 1 if marker.group() == "/*" else -1
                end = marker.end()
            if depth:
                end = len(text)
        elif token.group("hashes") is not None:
            closing = '"' + token.group("hashes")
            close = text.find(closing, end)
            end = len(text) if close == -1 else close + len(closing)
        pieces.append(re.sub(r"[^\n]", " ", text[token.start():end]))
        position = end
    pieces.append(text[position:])
    return "".join(pieces)


def _end(code: str, opening: int) -> int:
    """Offset just after the matching brace; an unclosed block cannot be measured."""
    depth = 0
    for position in range(opening, len(code)):
        if code[position] == "{":
            depth += 1
        elif code[position] == "}":
            depth -= 1
            if depth == 0:
                return position + 1
    raise ValueError("unclosed Rust block")


def _boundary(code: str, start: int) -> int | None:
    """The first body brace or declaration semicolon outside parameter/array brackets."""
    depth = 0
    for position in range(start, len(code)):
        char = code[position]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and char in ";{":
            return position
    return None


def classify(path: str) -> str:
    """Tests in a tests/ component or *_tests.rs; then .md docs; otherwise production."""
    path = PurePosixPath(path)
    if "tests" in path.parts or path.name.endswith("_tests.rs"):
        return "tests"
    return "docs" if path.suffix == ".md" else "production"


def test_lines(text: str) -> set[int]:
    """1-based lines of #[cfg(test)] modules, from the attribute through the closing brace.

    Other attributes may intervene. Comments and literals do not supply modules or braces.
    This covers rustfmt'd inline test modules, rather than arbitrary cfg expressions.
    """
    code = _code(text)
    lines = set()
    for attribute in CFG_TEST.finditer(code):
        rest = code[attribute.end():]
        module = re.match(r"\s*(?:#\[[^\]]*\]\s*)*(?:pub(?:\([^)]*\))?\s+)?mod\s+"
                          + IDENTIFIER + r"\s*\{", rest)
        if module:
            opening = attribute.end() + module.end() - 1
            start = code.count("\n", 0, attribute.start()) + 1
            end = code.count("\n", 0, _end(code, opening)) + 1
            lines.update(range(start, end + 1))
    return lines


def public_items(module: str, text: str) -> list[Signature]:
    """Unrestricted pub fn/struct/enum/trait/type/const/mod declarations in source order.

    Signature.text is the declaration's first line, without its body or trailing semicolon;
    doc is the nearest preceding /// or //! line. Restricted pub(crate) is not exported.
    Grep does not expand macros or evaluate cfg expressions.
    """
    code = _code(text)
    found = []
    for match in PUBLIC.finditer(code):
        end = text.find("\n", match.start())
        end = end if end != -1 else len(text)
        boundary = _boundary(code, match.end())
        declaration = text[match.start():min(end, boundary if boundary is not None else end)].strip()
        preceding = text[:match.start()].splitlines()
        doc = ""
        for previous in reversed(preceding):
            previous = previous.strip()
            if not previous or previous.startswith("#["):
                continue
            if previous.startswith(("///", "//!")):
                doc = previous[3:].strip()
            break
        found.append(Signature(module, match["name"], declaration, doc))
    return found


def inventory(root: Path, crates: Sequence[str]) -> list[Signature]:
    """Public items of repository-relative crate directories, in path then source order.

    Recursively scan .rs files, excluding tests/ and *_tests.rs and inline cfg(test) modules.
    Missing crates contribute nothing; overlapping crate directories do not duplicate items.
    """
    paths = sorted({path for crate in crates for path in (root / crate).rglob("*.rs")
                    if path.is_file() and classify(path.relative_to(root).as_posix()) == "production"})
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        tests = test_lines(text)
        text = "".join("\n" if number in tests else line
                       for number, line in enumerate(text.splitlines(keepends=True), 1))
        found.extend(public_items(path.relative_to(root).as_posix(), text))
    return found


def functions(module: str, text: str) -> list[Function]:
    """Functions with bodies, fn line through matching }, ignoring comments and literals.

    Qualify names by enclosing mod/trait/impl headers to distinguish methods. Trait signatures
    ending in ; have no body. This brace scan targets rustfmt'd code, not macro expansion.
    """
    code = _code(text)
    scopes = []
    for scope in re.finditer(r"\b(?:mod|trait|impl)\s+[^;{]+\{", code):
        opening = scope.end() - 1
        scopes.append((opening, _end(code, opening), " ".join(scope.group()[:-1].split())))
    found = []
    for match in FN.finditer(code):
        opening = _boundary(code, match.end())
        if opening is None or code[opening] == ";":
            continue
        end = _end(code, opening)
        start = code.count("\n", 0, match.start()) + 1
        parents = [name for first, last, name in scopes if first < match.start() < last]
        name = "::".join((*parents, match["name"]))
        found.append(Function(module, name, start, code.count("\n", 0, end) + 2 - start))
    return found


def long_functions(module: str, before: str, after: str, cap: int = SIZE_CAP) -> list[Function]:
    """Production functions over cap that are new or grew and contain added/replaced lines.

    Untouched, shortened and same-length old debt passes; inline cfg(test) functions are omitted.
    """
    was = {entry.name: entry.lines for entry in functions(module, before)}
    added = added_lines(before, after)
    tests = test_lines(after)
    return [entry for entry in functions(module, after)
            if entry.lines > cap and entry.lines > was.get(entry.name, 0)
            and entry.start not in tests
            and any(line in added for line in range(entry.start, entry.start + entry.lines))]


def line_changes(path: str, before: str, after: str) -> list[Change]:
    """Line insertions/deletions split by path kind and inline cfg(test) membership per side.

    SequenceMatcher uses autojunk=False. A path with no line changes still has one zero entry.
    """
    kind = classify(path)
    tests_before = test_lines(before) if kind == "production" and path.endswith(".rs") else set()
    tests_after = test_lines(after) if kind == "production" and path.endswith(".rs") else set()
    totals = {name: [0, 0] for name in KINDS}
    matcher = difflib.SequenceMatcher(None, before.splitlines(keepends=True),
                                      after.splitlines(keepends=True), autojunk=False)
    for tag, first, last, start, end in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            for number in range(first + 1, last + 1):
                totals["tests" if number in tests_before else kind][1] += 1
        if tag in ("replace", "insert"):
            for number in range(start + 1, end + 1):
                totals["tests" if number in tests_after else kind][0] += 1
    found = [Change(path, name, *totals[name]) for name in KINDS if any(totals[name])]
    return found or [Change(path, kind, 0, 0)]


def build(task: Task, run_id: str, branch: str, base_sha: str, tip_sha: str,
          changes: Sequence[Change], base: Path, tip: Path,
          ratchets: Sequence[Ratchet] = ()) -> Digest:
    """Read changed Rust texts from two trees; keep non-Rust numstat counts as supplied.

    Compare public declaration text (including signature changes as remove/add) only in changed
    .rs files. Split their line counts, flag grown production functions, and check task globs.
    Supplied per-tree ratchet counts are sorted by tree/form, like all path lists.
    """
    split, added, removed, long = [], [], [], []
    paths = sorted({entry.path for entry in changes})
    for change in sorted(changes, key=lambda entry: entry.path):
        if not change.path.endswith(".rs"):
            split.append(change)
            continue
        texts = [(root / change.path).read_text(encoding="utf-8")
                 if (root / change.path).is_file() else "" for root in (base, tip)]
        before, after = texts
        split.extend(line_changes(change.path, before, after))
        old, new = (public_items(change.path, text) for text in texts)
        old_keys = {(entry.name, entry.text) for entry in old}
        new_keys = {(entry.name, entry.text) for entry in new}
        added.extend(entry for entry in new if (entry.name, entry.text) not in old_keys)
        removed.extend(entry for entry in old if (entry.name, entry.text) not in new_keys)
        if classify(change.path) == "production":
            long.extend(long_functions(change.path, before, after))
    return Digest(run_id, task.id, task.kind, branch, base_sha, tip_sha, tuple(split),
                  tuple(added), tuple(removed), tuple(outside(paths, task.files)), tuple(long),
                  tuple(sorted(ratchets, key=lambda entry: (entry.tree, entry.form))))


def render(digest: Digest) -> str:
    """Deterministic Markdown, at most 8,000 characters including its final newline.

    Lists keep 30 entries of at most 160 characters, followed by an omitted-entry count.
    A final cut marker replaces whole lines beyond the total budget. Size is only a flag.
    """
    totals = ", ".join(
        f"{kind} +{sum(entry.added for entry in digest.changes if entry.kind == kind)}"
        f" -{sum(entry.removed for entry in digest.changes if entry.kind == kind)}" for kind in KINDS)
    lines = [f"# Rust digest: {digest.run}", "", f"- Task: {digest.task} ({digest.kind})",
             f"- Branch: `{digest.branch}`", f"- Base: `{digest.base[:12]}`; tip: `{digest.tip[:12]}`",
             f"- Lines: {totals}"]
    sections = [
        ("Changed paths", [f"- `{entry.path}` {entry.kind} +{entry.added} -{entry.removed}"
                           for entry in digest.changes]),
        ("Public items", [f"- {verb} `{entry.text}` ({entry.module})"
                          for verb, entries in (("added", digest.added), ("removed", digest.removed))
                          for entry in entries]),
        ("Outside the task's files", [f"- `{path}`" for path in digest.outside]),
        (f"Functions over {SIZE_CAP} lines (flag)",
         [f"- `{entry.module}:{entry.start}` {entry.name}: {entry.lines} lines" for entry in digest.long]),
        ("Old forms by tree", [f"- `{entry.tree}` `{entry.form}`: {entry.base} -> {entry.tip} "
                               f"({'new' if entry.new else f'{entry.tip - entry.base:+d}'})" for entry in digest.ratchets]),
    ]
    for title, entries in sections:
        lines.extend(["", f"## {title}"])
        lines.extend(entry[:LINE_CAP - 3] + "..." if len(entry) > LINE_CAP else entry
                     for entry in entries[:LIST_CAP])
        if not entries:
            lines.append("- none")
        if len(entries) > LIST_CAP:
            lines.append(f"- ... and {len(entries) - LIST_CAP} more")
    rendered = "\n".join(lines) + "\n"
    if len(rendered) <= DIGEST_LIMIT:
        return rendered
    cut = f"(cut at {DIGEST_LIMIT} characters)\n"
    kept = []
    remaining = DIGEST_LIMIT - len(cut)
    for line in rendered.splitlines(keepends=True):
        if len(line) > remaining:
            break
        kept.append(line)
        remaining -= len(line)
    return "".join(kept) + cut


def changes(repo: Path, base: str, tip: str, *, sh: Runner = run) -> list[Change]:
    """git diff --numstat -z --no-renames through the runner; binary counts are zero."""
    result = sh(["git", "diff", "--numstat", "-z", "--no-renames", base, tip, "--"],
                cwd=str(repo), check=True)
    found = []
    for record in result.out.split("\0"):
        if record:
            added, removed, path = record.split("\t", 2)
            found.append(Change(path, classify(path), 0 if added == "-" else int(added),
                                0 if removed == "-" else int(removed)))
    return found


def archive(repo: Path, rev: str, dest: Path, *, sh: Runner = run) -> Path:
    """Extract the whole revision into a new dest; remove the sibling tar even on failure."""
    dest.mkdir(parents=True)
    tar = Path(str(dest) + ".tar")
    try:
        sh(["git", "archive", "--format=tar", "-o", str(tar), rev], cwd=str(repo), check=True)
        with tarfile.open(tar) as tree:
            tree.extractall(dest, filter="data")
    finally:
        tar.unlink(missing_ok=True)
    return dest


def parse_counts(baseline: str, output: str) -> dict[str, int]:
    """Baseline counts, overridden by old_forms.py's sparse count/baseline diagnostics.

    Reject missing, duplicate, negative or malformed counts and diagnostic forms not in the
    baseline. Unmentioned forms equal their baseline; falls need not have been written back.
    """
    counts = {}
    for line in baseline.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        form, count = line.split()
        if form in counts or not count.isdecimal():
            raise ValueError(f"invalid old-forms baseline: {line}")
        counts[form] = int(count)
    if not counts:
        raise ValueError("empty old-forms baseline")
    seen = set()
    for line in output.splitlines():
        if match := COUNT.fullmatch(line):
            form = match[1]
            if form not in counts or form in seen or int(match[3]) != counts[form]:
                raise ValueError(f"invalid old-forms diagnostic: {line}")
            seen.add(form)
            counts[form] = int(match[2])
        elif ": count " in line:
            raise ValueError(f"invalid old-forms diagnostic: {line}")
    return counts


def _counts(root: Path, *, sh: Runner) -> dict[str, int]:
    """Count in a scratch archive with an isolated index and a restored zero baseline.

    old_forms.py omits falls when any form rises. A zero baseline makes every nonzero count
    a diagnostic, so mixed rises/falls remain exact even when baselines were not lowered.
    """
    path = root / "scripts/old-forms.txt"
    baseline = path.read_text(encoding="utf-8")
    zero = "".join(f"{form} 0\n" for form in parse_counts(baseline, ""))
    sh(["git", "init", "-q", str(root)], check=True)
    sh(["git", "add", "--all", "--force"], cwd=str(root), check=True)
    argv = ["python3", "-I", "-B", "scripts/old_forms.py"]
    try:
        atomic.write(path, zero)
        result = sh(argv, cwd=str(root))
        output = result.out + "\n" + result.err
        counts = parse_counts(zero, output)
        if not result.ok:
            rises = [match for line in output.splitlines() if (match := COUNT.fullmatch(line))
                     and int(match[2]) > int(match[3])]
            if result.code != 1 or not rises:
                raise Failed(argv, result)
        return counts
    finally:
        atomic.write(path, baseline)


def ratchets(base: Path, tip: Path, paths: Sequence[str], *, sh: Runner = run) -> list[Ratchet]:
    """Actual per-form counts for touched top-level trees with scripts/old_forms.py.

    Run each existing side from its tree root. Missing trees start at zero; deleting an
    existing tree's script fails closed. A present script requires a valid baseline.
    """
    found = []
    for tree in sorted({PurePosixPath(path).parts[0] for path in paths if len(PurePosixPath(path).parts) > 1}):
        roots = [root / tree for root in (base, tip)]
        scripts = [(root / "scripts/old_forms.py").is_file() for root in roots]
        if not any(scripts):
            continue
        if scripts[0] and roots[1].exists() and not scripts[1]:
            raise ValueError(f"{tree}: old_forms.py removed")
        before, after = [_counts(root, sh=sh) if exists else {} for root, exists in zip(roots, scripts)]
        found.extend(Ratchet(tree, form, before.get(form, 0), after.get(form, 0), form not in before)
                     for form in sorted(before.keys() | after.keys()))
    return found
