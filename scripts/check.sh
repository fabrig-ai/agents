#!/usr/bin/env bash
# Run shellcheck and the tools' isolated, offline self-tests, side by side.
set -eu
# Timing and its machine-readable decimals do not depend on the caller's locale.
export LC_ALL=C
# Job control gives each suite a process group of its own, to stop whole,
# and keeps SIGINT, which background jobs would otherwise ignore, for the
# fixtures that send it.
set -m
cd "$(dirname "$0")/.."

# The fixtures run below /tmp, outside every Git checkout and its Cargo
# configuration.
scratch=$(mktemp -d /tmp/agents-check.XXXXXX)
export TMPDIR=$scratch
# Retention requested by a caller must not escape this gate's scratch.
unset GATE_POLICY_FIXTURE_EVIDENCE
names=() pids=() stopped=0
cleanup() {
    local pid tries
    # No suite's process group outlives the gate, and the scratch goes only
    # once each has gone: a stopped suite may still be stopping its own
    # children, and a second signal would cut that short.
    for pid in "${pids[@]}"; do
        if ((!stopped)); then
            kill -TERM -- "-$pid" 2>/dev/null || continue
        fi
        for ((tries = 0; tries < 150; tries++)); do
            kill -0 -- "-$pid" 2>/dev/null || continue 2
            sleep 0.1
        done
        kill -KILL -- "-$pid" 2>/dev/null || true
    done
    wait
    # Whatever a fixture left read-only must still go.
    chmod -R u+w "$scratch" 2>/dev/null || true
    rm -rf "$scratch"
}
trap cleanup EXIT
# A stopped gate stops its suites before their scratch goes.
stop() {
    local pid
    stopped=1
    for pid in "${pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || true
    done
    exit "$1"
}
trap 'stop 130' INT
trap 'stop 143' TERM

# Each suite runs as a job of its own into its own log. The logs print
# whole, in this order, each followed by its `gate-step NAME SECONDS EXIT CPU`
# line on stderr (landing-flow.md, 10).
suite() {
    local name=$1
    shift
    names+=("$name")
    (
        start=$(date +%s%N)
        status=0
        # Bash's time includes the command (also a shell function) and its
        # waited-for children, while keeping their stderr in the suite log.
        TIMEFORMAT='%3U %3S'
        { time "$@" >"$scratch/$name.log" 2>&1 </dev/null; } 2>"$scratch/$name.time" || status=$?
        echo $((($(date +%s%N) - start) / 1000000)) >"$scratch/$name.ms"
        exit "$status"
    ) &
    pids+=("$!")
}

shellcheck_tools() {
    command -v shellcheck >/dev/null 2>&1 || return 0
    local bash_tools=(scripts/check.sh) tool
    for tool in scripts/devel/* scripts/infra/*; do
        [[ -f $tool ]] || continue
        if [[ $(head -n1 "$tool") == *bash* ]]; then
            bash_tools+=("$tool")
        fi
    done
    shellcheck -x -P SCRIPTDIR "${bash_tools[@]}"
}

suite shellcheck shellcheck_tools
suite test-fixture-waits scripts/devel/test-fixture-waits
suite test-gate-budget scripts/devel/test-gate-budget
suite test-post scripts/devel/test-post
suite test-land-set scripts/devel/test-land-set
suite test-land-resolve scripts/devel/test-land-resolve
suite test-landings scripts/devel/test-landings
suite test-after-landing scripts/devel/test-after-landing
suite test-codex-run scripts/devel/test-codex-run
suite test-record scripts/devel/test-record
suite test-qa scripts/devel/test-qa
suite test-logins scripts/devel/test-logins
suite test-issue scripts/devel/test-issue
suite test-tidy scripts/devel/test-tidy
suite test-receipt-inputs scripts/devel/test-receipt-inputs
suite test-heavy-plain scripts/devel/test-heavy-plain
suite test-repin scripts/devel/test-repin --evidence "$scratch/repin"
suite test-kache-setup env DEV_TMP="$scratch" scripts/infra/test-kache-setup
suite test-setup-checkouts scripts/infra/test-setup-checkouts
suite test-after-landing-units scripts/infra/test-after-landing-units
suite test-fleet-units scripts/infra/test-fleet-units
suite test-gate-policy scripts/devel/test-gate-policy
suite test-status-page scripts/devel/test-status-page
suite test-fleet scripts/devel/test-fleet
# The full heavy-recovery and land-turn suites install real systemd units.
# Only land-turn's five local pipe/protocol cases belong in this gate.
suite test-land-turn scripts/devel/test-land-turn --evidence "$scratch/land-turn" \
    --case protocol --case construction --case release-visibility \
    --case heartbeat-lifetime --case holder-validation

failed=()
for i in "${!names[@]}"; do
    name=${names[i]}
    status=0
    wait "${pids[i]}" || status=$?
    log=$scratch/$name.log
    cat "$log"
    # A log cut off mid-line must not swallow its gate-step line.
    [[ ! -s $log || -z $(tail -c1 "$log") ]] || echo
    ms=$(cat "$scratch/$name.ms" 2>/dev/null) || ms=0
    cpu=$(awk '{printf "%.3f", $1 + $2}' "$scratch/$name.time")
    printf '%s %s\n' "$name" "$cpu" >>"$scratch/cpu"
    printf 'gate-step %s %d.%03d %d %s\n' "$name" $((ms / 1000)) $((ms % 1000)) "$status" "$cpu" >&2
    ((status == 0)) || failed+=("$name")
done
share_failed=0
python3 -I -S -B scripts/devel/gate-shares.py scripts/gate-shares "$scratch/cpu" || share_failed=1
if ((${#failed[@]})); then
    # land shows the gate's last lines: they end with the failures' own.
    for name in "${failed[@]}"; do
        echo "== $name, its log's last lines:"
        tail -n 40 "$scratch/$name.log"
    done
    echo "check.sh: failed: ${failed[*]}" >&2
    exit 1
fi
if ((share_failed)); then
    echo "check.sh: failed: gate-shares" >&2
    exit 1
fi
