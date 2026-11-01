"""Precheck: the queue's checks on a branch merged with a trunk, in its implementer's slot (docs/design/landing.md, 2)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from fab import atomic, gate, log
from fab.sh import Runner, run


def precheck(slot: Path, tip: str, *, onto: str = "origin/main", full: bool = False,
             home: Path | None = None, sh: Runner = run,
             load: Callable[[Path], dict] | None = None, without: Sequence[str] = ()) -> dict:
    """Check tip as the queue would and return the receipt.

    In slot: remember where HEAD is; fetch origin; detach at onto and merge tip (--no-ff;
    a conflict aborts it: outcome "conflict"); select with fab.gate.select (load: the metadata
    loader); run the ratchet steps without --write and the build-lane checks, logging to
    FAB_HOME/precheck/<tip>.log. Always restore the slot to where HEAD was, clean.
    With full, select "full" and ratchet every tree with scripts/old_forms.py.
    The receipt {tip, main (onto's sha), selection ("full", "docs" or sorted names), steps
    (as "name:code:seconds"), outcome ("green", "red" or "conflict"), log, at (fab.log.now())} is
    written to FAB_HOME/precheck/<tip>.json and returned.
    """
    slot = slot.resolve()

    def git(*args: str, check: bool = True):
        return sh(["git", *args], cwd=str(slot), check=check)

    original = git("rev-parse", "HEAD").out.strip()
    branch = git("symbolic-ref", "--quiet", "HEAD", check=False).out.strip()
    git("fetch", "origin")
    main_tip = git("rev-parse", "--verify", f"{onto}^{{commit}}").out.strip()
    tip = git("rev-parse", "--verify", "--end-of-options", f"{tip}^{{commit}}").out.strip()
    directory = (home if home is not None else log.home()) / "precheck"
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"{tip}.log"
    atomic.write(log_path, "")
    receipt = {"tip": tip, "main": main_tip, "selection": "docs", "steps": [],
               "outcome": "conflict", "log": str(log_path)}
    load_metadata = gate.loader(load, sh=sh)

    try:
        git("checkout", "--detach", "--force", main_tip)
        merged = git("-c", "user.name=fab", "-c", "user.email=fab@localhost",
                     "merge", "--no-ff", "--no-edit", tip, check=False)
        atomic.write(log_path, merged.out + merged.err)
        if not merged.ok:
            git("merge", "--abort")
        else:
            paths = gate.changed_paths(slot, base=main_tip, sh=sh)
            selected = ("full" if full else
                        gate.select(slot, paths, base=main_tip, sh=sh, load=load_metadata))
            receipt["selection"] = gate.shown(selected)
            ratchet_paths = ([tree for tree in gate.TREES
                              if (slot / tree / "scripts/old_forms.py").is_file()]
                             if full else paths)
            steps = gate.ratchet_steps(slot, ratchet_paths, write=False)
            meta = load_metadata(slot) if isinstance(selected, set) else None
            steps += gate.check_steps(slot, selected, paths, meta, lane="build")
            steps = [step for step in steps if step.name not in without]  # a check along the way
            results = gate.run_steps(steps, log_path, sh=sh)
            receipt["steps"] = gate.step_texts(results)
            receipt["outcome"] = "green" if all(step.green for step in results) else "red"
    finally:
        _restore(git, original, branch)
    receipt["at"] = log.now()
    atomic.write(directory / f"{tip}.json", json.dumps(receipt, indent=2) + "\n")
    return receipt


def _restore(git, original, branch):
    """Restore the slot's original HEAD and remove check output, without moving its branch."""
    # Reset while detached so the implementer's branch never moves to the merge.
    git("reset", "--hard", original)
    if branch:
        git("checkout", "--force", branch.removeprefix("refs/heads/"))
    else:
        git("checkout", "--detach", "--force", original)
    git("clean", "-fd")


def main(argv: list[str]) -> int:
    """`fab precheck SLOT TIP [--onto REF] [--full]`: print receipt path and outcome;
    exit 0 green, 1 otherwise."""
    parser = argparse.ArgumentParser(prog="fab precheck", description=__doc__)
    parser.add_argument("slot", type=Path)
    parser.add_argument("tip")
    parser.add_argument("--onto", default="origin/main")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    receipt = precheck(args.slot, args.tip, onto=args.onto, full=args.full)
    path = Path(receipt["log"]).with_suffix(".json")
    print(f"{path}: {receipt['outcome']}")
    return 0 if receipt["outcome"] == "green" else 1
