#!/usr/bin/env bash
# Run shellcheck and the tools' isolated, offline self-tests, side by side.
set -eu
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
names=() pids=()
cleanup() {
    wait
    # Whatever a fixture left read-only must still go.
    chmod -R u+w "$scratch"
    rm -rf "$scratch"
}
trap cleanup EXIT
# A stopped gate stops its suites before their scratch goes.
stop() {
    local pid
    for pid in "${pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || true
    done
    exit "$1"
}
trap 'stop 130' INT
trap 'stop 143' TERM

# Each suite runs as a job of its own into its own log. The logs print
# whole, in this order, each followed by its `gate-step NAME SECONDS EXIT`
# line on stderr (landing-flow.md, 10).
suite() {
    local name=$1
    shift
    names+=("$name")
    (
        start=$(date +%s%N)
        status=0
        "$@" >"$scratch/$name.log" 2>&1 </dev/null || status=$?
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
suite test-post scripts/devel/test-post
suite test-land-set scripts/devel/test-land-set
suite test-landings scripts/devel/test-landings
suite test-codex-run scripts/devel/test-codex-run
suite test-record scripts/devel/test-record
suite test-receipt-inputs scripts/devel/test-receipt-inputs
suite test-repin scripts/devel/test-repin --evidence "$scratch/repin"
suite test-kache-setup env DEV_TMP="$scratch" scripts/infra/test-kache-setup
suite test-gate-policy scripts/devel/test-gate-policy
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
    cat "$scratch/$name.log"
    ms=$(cat "$scratch/$name.ms" 2>/dev/null) || ms=0
    printf 'gate-step %s %d.%03d %d\n' "$name" $((ms / 1000)) $((ms % 1000)) "$status" >&2
    ((status == 0)) || failed+=("$name")
done
if ((${#failed[@]})); then
    echo "check.sh: failed: ${failed[*]}" >&2
    exit 1
fi
