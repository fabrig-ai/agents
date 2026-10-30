"""fabrig's slow tiers: one tree's tier with its prerequisites (docs/design/fab.md, 11).

Ported from fabrig's tools/tiers/run. A pair is a nextest profile `<tier>-<tree>` of the
checkout's `.config/nextest.toml`; the package map names the packages that hold its tests and
the native binaries its tests execute. Every build goes through `heavy`, which waits for disk
itself. Runs from a fabrig checkout on a builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fab.gate import Step
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
    raise NotImplementedError


def pair(pairs: dict[str, Pair], tree: str, tier: str) -> Pair:
    """The pair for tree and tier; TierError naming the configured profiles when there is none."""
    raise NotImplementedError


def bundle(target: Pair) -> Bundle | None:
    """The browser bundle a pair's tests load: BUNDLES[tree] for tier "browser" with a tree in
    BUNDLES, and for the profile "qa-temper"; None otherwise."""
    raise NotImplementedError


def target_directory(repo: Path, *, sh: Runner = run) -> Path:
    """cargo's target directory for the checkout: `cargo metadata --format-version 1 --no-deps`
    (directly, not through heavy: it builds nothing) run in repo, its `target_directory`
    resolved. TierError when the command fails or its output lacks the key."""
    raise NotImplementedError


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
    raise NotImplementedError


def run_pair(repo: Path, target_pair: Pair, extra: list[str], log: Path, *, sh: Runner = run) -> int:
    """Run a pair in the checkout at repo: target_directory when the pair has a bundle or a
    binary with env, then steps through fab.gate.run_steps into log (which stops at the first
    red). Return the nextest step's exit code when every earlier step passed; REFUSED when a
    prerequisite failed, or when target_directory failed (its error appended to log)."""
    raise NotImplementedError


def listed(output: str) -> set[tuple[str, str, str]]:
    """(package, binary id, test) of every test a `cargo nextest list --message-format json`
    output selects: the last stdout line that parses as a JSON object with "rust-suites"; per
    suite its "package-name" and "binary-id", per testcase name whose
    "filter-match"."status" is "matches". ValueError when no line holds a listing."""
    raise NotImplementedError


def verify(repo: Path, target_pair: Pair, *, sh: Runner = run) -> tuple[set, set]:
    """Whether the map's packages select what the whole workspace selects for the pair:
    `heavy cargo nextest list --workspace --profile <profile> --message-format json`, then the
    same with `-p <package>` per package instead of --workspace, both in repo; return
    (missed: in the workspace's listing only, added: in the packages' only). TierError naming
    the listing when a command fails or its output holds no listing."""
    raise NotImplementedError


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
    raise NotImplementedError
