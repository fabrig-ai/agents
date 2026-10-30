"""Notification candidate filtering through the public CLI and private services."""

import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


fixture, kit = map(Path, sys.argv[1:3])
baseline = sys.argv[3:] == ["--baseline"]
root = fixture / "stale-history"
runs = root / "tmp/codex-run"
fake = root / "fake"
runs.mkdir(parents=True)
fake.mkdir()
bin_dir = fixture / "bin"
env = dict(os.environ, DEV_ROOT=str(root))
checks = 0
transcript = []
started = time.monotonic()


def cpu():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


initial_cpu = cpu()


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def snapshot(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        value = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
        result[str(path.relative_to(directory))] = (info.st_ino, info.st_mode, info.st_mtime_ns, value)
    return result


original_history = fixture / "workspace/tmp/codex-run"
original_snapshot = snapshot(original_history)


def run(name, *, ended=False, failed=None, age=180, meta=True):
    directory = runs / name
    directory.mkdir(mode=0o700)
    if meta:
        metadata(directory, age=age)
    if failed is not None:
        (directory / "post-failed").write_text(failed)
    if ended:
        (directory / "ended").touch(mode=0o600)
    return directory


def metadata(directory, *, age=180, omit="", timestamp="2026-10-29T00:00:00Z"):
    values = {"to": "o/stale", "report": str(root / "report.md"), "started": timestamp}
    (directory / "meta").write_text("".join(f"{key}={value}\n" for key, value in values.items() if key != omit))
    stamp = time.time() - age
    os.utime(directory / "meta", (stamp, stamp))


def call(label, *, post=False):
    result = subprocess.run([str(kit / "codex-run"), "stale", *(["--post"] if post else [])],
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    transcript.append({"label": label, "status": result.returncode,
                       "stdout": result.stdout.replace(str(fixture), "FIXTURE"),
                       "stderr": result.stderr.replace(str(fixture), "FIXTURE")})
    return result


def listing(result, expected, label):
    rows = [f"{name}\t{why}\t{runs / name}\to/stale\n" for name, why in sorted(expected.items())]
    check((result.returncode, result.stdout, result.stderr) == (0, "".join(rows), ""),
          (label, result.returncode, result.stdout, result.stderr))


# These temporary fakes inject only the named fault or exact unit state. The
# ordinary suite's tools and its PATH/startup audit remain in force.
stat_path = bin_dir / "stat"
stat_target = os.readlink(stat_path)
systemctl = bin_dir / "systemctl"
systemctl_bytes = systemctl.read_bytes()
systemctl_mode = systemctl.stat().st_mode
stat_path.unlink()
stat_path.write_text('''#!/usr/bin/env bash
set -euo pipefail
fault=$DEV_ROOT/fake/stat-fault
if [[ -f $fault ]]; then
    read -r name mode <"$fault"
    if [[ ${!#} == "$DEV_ROOT/tmp/codex-run/$name/meta" ]]; then
        case $mode in
            fail) echo 'fixture stat failed' >&2; exit 1 ;;
            end) : >"$DEV_ROOT/tmp/codex-run/$name/ended" ;;
            meta-race) mv "${!#}" "${!#}.before-race" ;;
        esac
    fi
fi
exec /usr/bin/stat "$@"
''')
stat_path.chmod(0o700)
systemctl.write_text('''#!/usr/bin/env bash
set -euo pipefail
[[ $# == 4 && $1 == --user && $2 == is-active && $3 == --quiet ]]
[[ -f $DEV_ROOT/fake/active-unit && $(<"$DEV_ROOT/fake/active-unit") == "$4" ]]
''')

try:
    for name, age in (("completed-fresh", 0), ("completed-old", 180), ("completed-day-old", 90000)):
        run(name, ended=True, age=age)
    unfinished = run("unfinished")
    active = run("active")
    (fake / "active-unit").write_text("codex-run-active")
    refused = run("refused-before-end", failed="refused\n")
    run("refused-ended", failed="refused\n", ended=True)
    for ended in (False, True):
        run(f"queued-{ended}", failed="queued, nobody will wake it: fixture\n", ended=ended)
    run("fresh-unfinished", age=0)
    run("day-old-unfinished", age=90000)
    run("missing-meta", ended=True, meta=False)
    history = snapshot(runs)
    expected = {"unfinished": "unit inactive without end", "refused-before-end": "post failed",
                "refused-ended": "post failed"}
    first = call("mixed history")
    listing(first, expected, "fresh/old/completed/active/refused/queued boundaries")
    second = call("repeated mixed history")
    check((first.returncode, first.stdout, first.stderr) ==
          (second.returncode, second.stdout, second.stderr), "repeated listing parity")
    check(snapshot(runs) == history, "listing preserves complete fixture history")

    # Completion publishes post-failed before ended. Exercise both intermediate
    # snapshots, including completion during stat, without inventing a late post.
    (active / "post-failed").write_text("refused\n")
    expected["active"] = "post failed"
    listing(call("refusal before end"), expected, "active refusal remains a candidate")
    (fake / "stat-fault").write_text("active end\n")
    listing(call("end during stat"), expected, "refused candidate survives ended transition")
    (fake / "stat-fault").unlink()
    check((active / "ended").is_file(), "finish race reached ended")
    (refused / "ended").touch()
    (unfinished / "ended").touch()
    del expected["unfinished"]
    listing(call("successful and refused completion"), expected, "successful completion omitted; refused retained")
    delivered = call("deliver refused completions", post=True)
    check(delivered.returncode == 0 and delivered.stderr == "" and
          set(delivered.stdout.splitlines()) == {f"{name} told: message-fixture waiting" for name in expected},
          "refused completions delivered")
    check(all((runs / name / "told").is_file() for name in expected), "delivery records told")
    listing(call("repeat after delivery", post=True), {}, "no repeated delivery")
    check(len((fake / "post.calls").read_text().splitlines()) == 3, "exactly three completion posts")

    (fake / "stat-fault").write_text("completed-old fail\n")
    result = call("completed noncandidate stat failure")
    check((result.returncode, result.stdout, result.stderr) ==
          ((1, "completed-old not told: meta age unavailable\n", "fixture stat failed\n") if baseline else (0, "", "")),
          "reviewed noncandidate age-stat diagnostic scope")
    candidate = run("stat-candidate")
    for mode in ("fail", "meta-race"):
        (fake / "stat-fault").write_text(f"stat-candidate {mode}\n")
        result = call(f"candidate {mode}")
        check(result.returncode != 0 and result.stderr and not (candidate / "told").exists(),
              ("candidate failure retains diagnostics and nonzero", mode, result))
        check(result.stdout == "stat-candidate not told: meta age unavailable\n", "candidate stat diagnostic")
        if mode == "meta-race":
            (candidate / "meta.before-race").rename(candidate / "meta")
    (candidate / "post-failed").write_text("refused\n")
    (candidate / "ended").touch()
    (fake / "stat-fault").write_text("stat-candidate fail\n")
    result = call("completed refused candidate stat failure")
    check((result.returncode, result.stdout, result.stderr) ==
          (1, "stat-candidate not told: meta age unavailable\n", "fixture stat failed\n"),
          "completed refused candidate retains age failure")
    (fake / "stat-fault").unlink()
    check(call("recovered refused candidate", post=True).returncode == 0 and
          (candidate / "told").is_file(), "candidate remains retryable after failures")

    for name, omit, timestamp in (("bad-to", "to", "2026-10-29T00:00:00Z"),
                                  ("bad-report", "report", "2026-10-29T00:00:00Z"),
                                  ("bad-started", "", "invalid-timestamp")):
        directory = run(name)
        metadata(directory, omit=omit, timestamp=timestamp)
    result = call("metadata and timestamp failures", post=True)
    check(result.returncode == 1 and "invalid-timestamp" in result.stderr and
          set(result.stdout.splitlines()) == {
              "bad-to not told: meta recipient unreadable or invalid",
              "bad-report not told: meta report unreadable or invalid",
              "bad-started not told: post body failed"}, "candidate metadata failures retain diagnostics")
    check(all(not (runs / name / "told").exists() for name in ("bad-to", "bad-report", "bad-started")),
          "failed metadata never records delivery")
    for name in ("bad-to", "bad-report", "bad-started"):
        metadata(runs / name)
    (fake / "post-exit").write_text("3\n")
    result = call("queued recovery", post=True)
    check(result.returncode == 0 and result.stderr == "" and len(result.stdout.splitlines()) == 3 and
          all((runs / name / "told").is_file() for name in ("bad-to", "bad-report", "bad-started")),
          "exit three delivers recovered unfinished candidates")
    listing(call("repeat queued recovery", post=True), {}, "queued recovery is not replayed")
    check(len((fake / "post.calls").read_text().splitlines()) == 7, "only seven intended notifications")
    check(set(path.name for path in runs.iterdir()) ==
          {key.split("/")[0] for key in history} | {"stat-candidate", "bad-to", "bad-report", "bad-started"},
          "all fixture run directories retained")
    check(all((runs / key).read_bytes() == value[3] for key, value in history.items()
              if value[3] is not None), "all original run evidence bytes retained")
    check(snapshot(original_history) == original_snapshot, "all preceding suite history retained unchanged")
finally:
    stat_path.unlink()
    stat_path.symlink_to(stat_target)
    systemctl.write_bytes(systemctl_bytes)
    systemctl.chmod(systemctl_mode)

if os.environ.get("CODEX_RUN_STALE_TRANSCRIPT"):
    Path(os.environ["CODEX_RUN_STALE_TRANSCRIPT"]).write_text(json.dumps(transcript, indent=2) + "\n")
print(f"stale candidates CPU={cpu() - initial_cpu:.3f}s wall={time.monotonic() - started:.3f}s; "
      f"{len(transcript)} public CLI calls; {len(list(runs.iterdir()))} run directories retained", file=sys.stderr)
print(checks)
