#!/usr/bin/env bash
# Run shellcheck and the tools' isolated, offline self-tests.
set -eu
cd "$(dirname "$0")/.."

if command -v shellcheck >/dev/null 2>&1; then
    bash_tools=(scripts/check.sh)
    for tool in scripts/devel/* scripts/infra/* scripts/devel/recovery-v1/*; do
        [[ -f $tool ]] || continue
        if [[ $(head -n1 "$tool") == *bash* ]]; then
            bash_tools+=("$tool")
        fi
    done
    shellcheck -x -P SCRIPTDIR "${bash_tools[@]}"
fi

# Stable release fixtures must be outside every Git checkout.
scratch=$(mktemp -d /tmp/agents-check.XXXXXX)
export TMPDIR=$scratch
# Retention requested by a caller must not escape this gate's scratch.
unset GATE_POLICY_FIXTURE_EVIDENCE
cleanup() {
    # Installed release fixtures deliberately make their files read-only.
    chmod -R u+w "$scratch"
    rm -rf "$scratch"
}
trap cleanup EXIT
mkdir -p "$scratch/workspace/tmp"

DEV_ROOT=$scratch/workspace scripts/devel/test-tools
scripts/devel/test-land-set
scripts/devel/test-landings
scripts/devel/test-repin --evidence "$scratch/repin"
DEV_TMP=$scratch scripts/infra/test-kache-setup
scripts/devel/recovery-v1/test-gate-policy
scripts/devel/recovery-v1/test-inert-install --evidence "$scratch/inert-install"
# The full heavy-recovery and land-turn suites install real systemd units.
# Only land-turn's five local pipe/protocol cases belong in this gate.
scripts/devel/recovery-v1/test-land-turn --evidence "$scratch/land-turn" \
    --case protocol --case construction --case release-visibility \
    --case heartbeat-lifetime --case installed-validation
