"""fabrig's slow tiers: one tree's tier with its prerequisites (docs/design/fab.md, 11).

Ported from fabrig's tools/tiers/run. A pair is a nextest profile `<tier>-<tree>` of the
checkout's `.config/nextest.toml`; the package map names the packages that hold its tests and
the native binaries its tests execute. Every build goes through `heavy`, which waits for disk
itself. Runs from a fabrig checkout on a builder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fab import atomic
from fab import log as fab_log
from fab.gate import Step, run_steps
from fab.sh import Runner, run

NEXTEST_CONFIG = ".config/nextest.toml"
# The package map in the checkout; the first existing path wins.
PACKAGE_MAPS = (".config/tiers/packages.toml", "tools/tiers/packages.toml")
REFUSED = 2  # an unknown pair, a bad map or a failed prerequisite: nothing later ran
TEST_FAILED = 100  # nextest: some test failed
WASM = "wasm32-unknown-unknown"
NAME = r"[A-Za-z0-9_-]+"  # a package or binary name in the map
ENV = r"[A-Z][A-Z0-9_]*_TEST_[A-Z0-9_]+"  # a binary's test environment variable


class TierError(ValueError):
    """A pair or package map that cannot run; the message names the file and the pair."""


@dataclass(frozen=True)
class Binary:
    package: str
    bin: str
    env: str | None = None  # set to the built binary's absolute path for the tests


@dataclass(frozen=True)
class Pair:
    profile: str  # "<tier>-<tree>"
    tier: str
    tree: str
    packages: tuple[str, ...]  # sorted, unique
    binaries: tuple[Binary, ...]  # sorted by (package, bin)


@dataclass(frozen=True)
class Bundle:
    package: str  # the wasm shell package
    out: str  # the bundle directory under cargo's target directory
    variable: str  # set to the bundle's absolute directory for the tests
    options: tuple[str, ...]  # skein-ui-bundle's asset options, paths relative to the checkout
    features: tuple[str, ...] = ()


BUNDLES = {
    "skein": Bundle(
        "skein-ui-example-shell-web", "ui-example-bundle", "SKEIN_UI_EXAMPLE_BUNDLE",
        ("--stylesheet", "skein/examples/ui/shell-web/notes.css",
         "--noscript", "Notes needs WebAssembly and scripts.")),
    "jig": Bundle(
        "jig-client-test-shell-web", "jig-test-bundle", "JIG_TEST_BUNDLE",
        ("--stylesheet", "jig/crates/jig-client-shell-web/jig.css",
         "--stylesheet", "jig/testing/jig-client-test-shell-web/jig_client_test_shell_web.css",
         "--pictures", "jig=jig/crates/jig-client-shell-web/pictures",
         "--pictures", "jig-test=jig/testing/jig-client-test-shell-web/pictures",
         "--files", "jig/testing/jig-client-test-shell-web/files",
         "--noscript", "jig needs WebAssembly and scripts.")),
    "temper": Bundle(
        "temper-client-shell-web", "temper-bundle", "TEMPER_TEST_BUNDLE",
        ("--stylesheet", "temper/crates/temper-client-shell-web/temper.css",
         "--stylesheet", "temper/crates/temper-client-shell-web/task-pages.css",
         "--files", "temper/crates/temper-client-shell-web/files",
         "--noscript", "temper needs WebAssembly and scripts."),
        ("--features", "loopback-navigation")),
}


def load(repo: Path) -> dict[str, Pair]:
    """Every pair of the checkout at repo, keyed by profile, sorted by profile.

    Pairs: the `[profile.*]` tables of NEXTEST_CONFIG whose names hold a hyphen, split at the
    last one into tier and tree. The map: the first of PACKAGE_MAPS that exists; per profile a
    list of package names, and a `[binaries]` table with per profile a list of {package, bin,
    env?} records. TierError when a file is missing or does not parse, `[binaries]` does not
    have exactly the pairs' profiles as keys, or for any pair: its package list is missing,
    empty, not sorted or not unique, or holds a name not matching NAME; a binary record has
    other keys, a package or bin not matching NAME, or an env not matching ENV; the records
    are not sorted and unique by (package, bin), two share a bin, or two share an env."""
    def read(path: Path) -> dict:
        try:
            with path.open("rb") as source:
                return tomllib.load(source)
        except (OSError, ValueError) as error:
            raise TierError(f"tiers: read {path}: {error}") from error

    config_path = repo / NEXTEST_CONFIG
    profiles = read(config_path).get("profile")
    if not isinstance(profiles, dict):
        raise TierError(f"tiers: {config_path}: missing profile tables")
    names = sorted(name for name in profiles if "-" in name)
    map_path = next((repo / name for name in PACKAGE_MAPS if (repo / name).exists()), None)
    if map_path is None:
        raise TierError(f"tiers: missing package map ({', '.join(str(repo / name) for name in PACKAGE_MAPS)}); "
                        f"configured profiles: {', '.join(names)}")
    package_map = read(map_path)
    binary_map = package_map.get("binaries")
    if not isinstance(binary_map, dict) or set(binary_map) != set(names):
        raise TierError(f"tiers: {map_path}: binaries needs exactly the configured profiles: "
                        f"{', '.join(names)}")

    def matches(pattern: str, value) -> bool:
        return isinstance(value, str) and re.fullmatch(pattern, value) is not None

    pairs = {}
    for profile in names:
        packages = package_map.get(profile)
        if (not isinstance(packages, list) or not packages
                or any(not matches(NAME, name) for name in packages)
                or packages != sorted(set(packages))):
            raise TierError(f"tiers: {map_path}: {profile}: need sorted, unique package names")
        records = binary_map[profile]
        if not isinstance(records, list):
            raise TierError(f"tiers: {map_path}: {profile}: need a binary list")
        binaries = []
        for record in records:
            if (not isinstance(record, dict) or not {"package", "bin"} <= record.keys()
                    or record.keys() - {"package", "bin", "env"}
                    or not matches(NAME, record["package"]) or not matches(NAME, record["bin"])
                    or ("env" in record and not matches(ENV, record["env"]))):
                raise TierError(f"tiers: {map_path}: {profile}: invalid binary record: {record!r}")
            binaries.append(Binary(**record))
        keys = [(binary.package, binary.bin) for binary in binaries]
        variables = [binary.env for binary in binaries if binary.env is not None]
        if (keys != sorted(set(keys)) or len({binary.bin for binary in binaries}) != len(binaries)
                or len(set(variables)) != len(variables)):
            raise TierError(f"tiers: {map_path}: {profile}: need sorted, unique package/bin records "
                            "with distinct bin and env names")
        tier, tree = profile.rsplit("-", 1)
        pairs[profile] = Pair(profile, tier, tree, tuple(packages), tuple(binaries))
    return pairs


def pair(pairs: dict[str, Pair], tree: str, tier: str) -> Pair:
    """The pair for tree and tier; TierError naming the configured profiles when there is none."""
    profile = f"{tier}-{tree}"
    target = pairs.get(profile)
    if target is None or (target.tree, target.tier) != (tree, tier):
        raise TierError(f"tiers: {NEXTEST_CONFIG}: unknown pair {tree} {tier}; "
                        f"configured profiles: {', '.join(sorted(pairs))}")
    return target


def bundle(target: Pair) -> Bundle | None:
    """The browser bundle a pair's tests load: BUNDLES[tree] for tier "browser" with a tree in
    BUNDLES, and for the profile "qa-temper"; None otherwise."""
    if target.tier == "browser" or target.profile == "qa-temper":
        return BUNDLES.get(target.tree)
    return None


def target_directory(repo: Path, *, sh: Runner = run) -> Path:
    """cargo's target directory for the checkout: `cargo metadata --format-version 1 --no-deps`
    (directly, not through heavy: it builds nothing) run in repo, its `target_directory`
    resolved. TierError when the command fails or its output lacks the key."""
    try:
        result = sh(["cargo", "metadata", "--format-version", "1", "--no-deps"], cwd=str(repo))
        if not result.ok:
            raise ValueError(f"exit {result.code}: {(result.err or result.out).strip()}")
        return Path(json.loads(result.out)["target_directory"]).resolve()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TierError(f"tiers: {repo}: cargo metadata target_directory: {error}") from error


def steps(repo: Path, target_pair: Pair, extra: list[str], target: Path | None) -> list[Step]:
    """The commands that run a pair, in order, each a fab.gate.Step run in repo.

    Every argv starts `env NEXTEST_DOUBLE_SPAWN=0`, then the bundle variable (when the pair
    has a bundle) and each binary's env, as VAR=<absolute path>, then the command. With a
    bundle: `wasm module` (heavy cargo build --target WASM <features> -p <package>), `bundle
    tool` (heavy cargo build -p skein-ui-bundle), `browser bundle` (<target>/debug/skein-ui-bundle
    --module <target>/WASM/debug/<package with - as _>.wasm --name <that name> --prefix /bundle/
    <options> --out <target>/<out>, directly). Then per binary in order `binary <package>/<bin>`
    (heavy cargo build -p <package> --bin <bin>). Last `nextest` (heavy cargo nextest run -p
    <package> per package --profile <profile> --no-fail-fast, then extra unchanged).
    The bundle variable is <target>/<out>; a binary's env is <target>/debug/<bin>.
    ValueError when target is None and the pair has a bundle or a binary with env."""
    browser = bundle(target_pair)
    if target is None and (browser is not None or any(binary.env for binary in target_pair.binaries)):
        raise ValueError(f"{target_pair.profile}: target directory required for bundle or binary env")
    prefix = ["env", "NEXTEST_DOUBLE_SPAWN=0"]
    if browser is not None:
        prefix.append(f"{browser.variable}={target / browser.out}")
    prefix.extend(f"{binary.env}={target / 'debug' / binary.bin}"
                  for binary in target_pair.binaries if binary.env is not None)
    commands = []

    def add(name: str, *argv: str):
        commands.append(Step(name, (*prefix, *argv), str(repo)))

    if browser is not None:
        add("wasm module", "heavy", "cargo", "build", "--target", WASM,
            *browser.features, "-p", browser.package)
        add("bundle tool", "heavy", "cargo", "build", "-p", "skein-ui-bundle")
        module = browser.package.replace("-", "_")
        add("browser bundle", str(target / "debug" / "skein-ui-bundle"),
            "--module", str(target / WASM / "debug" / f"{module}.wasm"),
            "--name", module, "--prefix", "/bundle/", *browser.options,
            "--out", str(target / browser.out))
    for binary in target_pair.binaries:
        add(f"binary {binary.package}/{binary.bin}", "heavy", "cargo", "build",
            "-p", binary.package, "--bin", binary.bin)
    packages = [arg for package in target_pair.packages for arg in ("-p", package)]
    add("nextest", "heavy", "cargo", "nextest", "run", *packages,
        "--profile", target_pair.profile, "--no-fail-fast", *extra)
    return commands


def run_pair(repo: Path, target_pair: Pair, extra: list[str], log: Path, *, sh: Runner = run) -> int:
    """Run a pair in the checkout at repo: target_directory when the pair has a bundle or a
    binary with env, then steps through fab.gate.run_steps into log (which stops at the first
    red). Return the nextest step's exit code when every earlier step passed; REFUSED when a
    prerequisite failed, or when target_directory failed (its error appended to log)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    target = None
    if bundle(target_pair) is not None or any(binary.env for binary in target_pair.binaries):
        try:
            target = target_directory(repo, sh=sh)
        except TierError as error:
            atomic.extend(log, f"{error}\n")
            return REFUSED
    outcomes = run_steps(steps(repo, target_pair, extra, target), log, sh=sh)
    return outcomes[-1].code if outcomes[-1].name == "nextest" else REFUSED


def listed(output: str) -> set[tuple[str, str, str]]:
    """(package, binary id, test) of every test a `cargo nextest list --message-format json`
    output selects: the last stdout line that parses as a JSON object with "rust-suites"; per
    suite its "package-name" and "binary-id", per testcase name whose
    "filter-match"."status" is "matches". ValueError when no line holds a listing."""
    listing = None
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "rust-suites" in value:
            listing = value
    if listing is None:
        raise ValueError("missing nextest JSON listing")
    return {(suite["package-name"], suite["binary-id"], name)
            for suite in listing["rust-suites"].values()
            for name, testcase in suite.get("testcases", {}).items()
            if testcase["filter-match"]["status"] == "matches"}


def verify(repo: Path, target_pair: Pair, *, sh: Runner = run) -> tuple[set, set]:
    """Whether the map's packages select what the whole workspace selects for the pair:
    `heavy cargo nextest list --workspace --profile <profile> --message-format json`, then the
    same with `-p <package>` per package instead of --workspace, both in repo; return
    (missed: in the workspace's listing only, added: in the packages' only). TierError naming
    the listing when a command fails or its output holds no listing."""
    selections = (("workspace", ["--workspace"]),
                  ("packages", [arg for package in target_pair.packages for arg in ("-p", package)]))
    listings = []
    for name, selection in selections:
        try:
            result = sh(["heavy", "cargo", "nextest", "list", *selection,
                         "--profile", target_pair.profile, "--message-format", "json"], cwd=str(repo))
            if not result.ok:
                raise ValueError(f"exit {result.code}: {(result.err or result.out).strip()}")
            listings.append(listed(result.out))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise TierError(f"tiers: {target_pair.profile}: {name} listing: {error}") from error
    workspace, packages = listings
    return workspace - packages, packages - workspace


def main(argv: list[str]) -> int:
    """`fab tiers run TREE TIER [--repo PATH] [-- NEXTEST_ARGS...]` and
    `fab tiers verify [TREE TIER] [--repo PATH]`; repo defaults to the current directory.

    Every command runs with umask 077. run: load, pair, run_pair with the log
    FAB_HOME/tiers/<profile>-<YYYYMMDDTHHMMSSZ>.log; print `tiers: log <path>` first, then
    after the run the log's content, and return run_pair's code. verify: every pair, or the
    one named; per pair print `tiers: <profile>: <n> missed, <n> added` and then each
    difference as `tiers: <profile>: missed|added <package> <binary> <test>`, sorted; go on
    after a difference; exit 0 when none, 1 otherwise. A TierError: its message on stderr,
    exit REFUSED. Bad arguments (argparse): exit 2."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="fab tiers", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    verify_parser = commands.add_parser("verify")
    run_parser.add_argument("tree")
    run_parser.add_argument("tier")
    verify_parser.add_argument("tree", nargs="?")
    verify_parser.add_argument("tier", nargs="?")
    for command in (run_parser, verify_parser):
        command.add_argument("--repo", type=Path, default=Path.cwd())
    separator = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:separator])
    extra = argv[separator + 1:]
    if args.command == "verify":
        if separator < len(argv):
            parser.error("verify takes no nextest arguments")
        if (args.tree is None) != (args.tier is None):
            parser.error("verify needs both TREE and TIER, or neither")
    try:
        pairs = load(args.repo)
        chosen = [pair(pairs, args.tree, args.tier)] if args.tree is not None else list(pairs.values())
        if args.command == "run":
            target_pair = chosen[0]
            directory = fab_log.home() / "tiers"
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log = directory / f"{target_pair.profile}-{stamp}.log"
            print(f"tiers: log {log}", flush=True)
            code = run_pair(args.repo, target_pair, extra, log)
            print(log.read_text(), end="")
            return code
        different = False
        for target_pair in chosen:
            missed, added = verify(args.repo, target_pair)
            print(f"tiers: {target_pair.profile}: {len(missed)} missed, {len(added)} added")
            for label, tests in (("missed", missed), ("added", added)):
                for package, binary, test in sorted(tests):
                    print(f"tiers: {target_pair.profile}: {label} {package} {binary} {test}")
            different |= bool(missed or added)
        return int(different)
    except TierError as error:
        print(error, file=sys.stderr)
        return REFUSED
