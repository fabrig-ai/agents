#!/usr/bin/env bash
# Run shellcheck and the tools' isolated, offline self-tests.
set -eu
cd "$(dirname "$0")/.."

if command -v shellcheck >/dev/null 2>&1; then
    bash_tools=(scripts/check.sh)
    for tool in scripts/devel/* scripts/infra/*; do
        [[ -f $tool ]] || continue
        if [[ $(head -n1 "$tool") == *bash* ]]; then
            bash_tools+=("$tool")
        fi
    done
    shellcheck -x -P SCRIPTDIR "${bash_tools[@]}"
fi

# The fixtures run below /tmp, outside every Git checkout and its Cargo
# configuration.
scratch=$(mktemp -d /tmp/agents-check.XXXXXX)
export TMPDIR=$scratch
# Retention requested by a caller must not escape this gate's scratch.
unset GATE_POLICY_FIXTURE_EVIDENCE
cleanup() {
    # Whatever a fixture left read-only must still go.
    chmod -R u+w "$scratch"
    rm -rf "$scratch"
}
trap cleanup EXIT

scripts/devel/test-post
scripts/devel/test-land-set
scripts/devel/test-landings
scripts/devel/test-codex-run
scripts/devel/test-record
scripts/devel/test-receipt-inputs
scripts/devel/test-repin --evidence "$scratch/repin"
DEV_TMP=$scratch scripts/infra/test-kache-setup
scripts/devel/test-gate-policy
# The full heavy-recovery and land-turn suites install real systemd units.
# Only land-turn's five local pipe/protocol cases belong in this gate.
scripts/devel/test-land-turn --evidence "$scratch/land-turn" \
    --case protocol --case construction --case release-visibility \
    --case heartbeat-lifetime --case holder-validation
