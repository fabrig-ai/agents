"""Two timer promotions, using temporary HOME and fake services/origins only."""

import io
import json
import shutil
import subprocess
import tarfile
import tomllib
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


@fixture.lru_cache(maxsize=1)
def before_stage_b():
    """The tree just before stage B: the runner and declarations every host runs."""
    marker = subprocess.check_output(
        ["git", "-C", str(fixture.ROOT), "log", "-1", "--format=%H", "--fixed-strings",
         "--grep=Enable bootstrap declarations after the compatibility rollout"], text=True).strip()
    return marker + "^" if marker else "HEAD"


# Stage A (d3712a2) and its predecessors are on every host already; what must
# promote stage B now is the runner deployed fleet-wide, just before it.
DEPLOYED = before_stage_b()
STAGE_A = DEPLOYED
HAS_BOOTSTRAP = (fixture.ROOT / "fleet/bootstrap/bootstrap.py").exists()
MUTATIONS = {"enable", "disable", "start", "stop", "restart", "daemon-reload"}


class BootstrapStagesTest(unittest.TestCase):
    def setUp(self):
        self.f = fixture.FleetTest(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        # Verify the historical rollout, independently of later runner changes.
        self.rollout = DEPLOYED.removesuffix('^') if DEPLOYED != 'HEAD' else 'HEAD'
        self.code = self.script(self.rollout)
        self.hosts_toml = (self.f.source / "fleet/hosts.toml").read_text()
        self.hosts = tuple(tomllib.loads(self.hosts_toml)["hosts"])

    def legacy_fleet(self):
        # The declarations live before stage B: main's own fleet tree, so units
        # that main already declares (after-landing) are not stage B's changes.
        base = before_stage_b()
        archive = fixture.historical_archive(base, "fleet")
        stage = self.f.directory / "fleet-stage"
        stage.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(stage, filter="data")
        # Declarations stage B did not touch come from main, so later changes to
        # them (Claude settings, say) are on both sides and are not promotions.
        marker = base.removesuffix("^")
        touched = set(subprocess.check_output(
            ["git", "-C", str(fixture.ROOT), "diff", "--name-only", base, marker, "--", "fleet"],
            text=True).split()) if marker != base else set()
        for path in (self.f.source / "fleet").rglob("*"):
            name = path.relative_to(self.f.source).as_posix()
            if path.is_file() and name not in touched:
                (stage / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, stage / name)
        # Units added after stage B must have their current role declarations
        # on both sides, without backporting stage B's new kache ownership.
        roles = 'fleet/units/roles.toml'
        before_roles = tomllib.loads(subprocess.check_output(
            ['git', '-C', str(fixture.ROOT), 'show', base + ':' + roles], text=True))['units']
        rollout_roles = tomllib.loads(subprocess.check_output(
            ['git', '-C', str(fixture.ROOT), 'show', marker + ':' + roles], text=True))['units']
        current_roles = tomllib.loads((self.f.source / roles).read_text())['units']
        added = rollout_roles.keys() - before_roles.keys()
        fixture.put(stage / roles, '[units]\n' + ''.join(
            json.dumps(unit) + ' = ' + json.dumps(assigned) + '\n'
            for unit, assigned in current_roles.items() if unit not in added))
        retired = self.f.directory / "retired-fleet"
        (self.f.source / "fleet").rename(retired)
        (stage / "fleet").rename(self.f.source / "fleet")
        stage.rmdir()
        shutil.rmtree(retired)
        # Keep the test's declared roster on both sides of the promotion, even
        # when a host was added or retired after this historical runner landed.
        # Seed flags belong to stage B, not the historical version-only inputs.
        fixture.put(self.f.source / "fleet/hosts.toml", "\n".join(
            line for line in self.hosts_toml.splitlines()
            if line.partition("=")[0].strip() != "seed") + "\n")
        fixture.put(self.f.source / "fleet/repositories.toml",
                    f'agents = {json.dumps(str(self.f.origin))}\nfabrig = {json.dumps(self.f.fabrig_origin)}\n')

    def script(self, revision):
        script = fixture.historical_source(revision)
        return script.replace('SYSTEM_TOOL_DIRS = (Path("/usr/bin"), Path("/bin"))',
                              f'SYSTEM_TOOL_DIRS = tuple(map(Path, {json.dumps([str(p) for p in self.f.system_bins])}))')

    def snapshot(self):
        return {name: row for name, row in self.f.snapshot(exclude_mirror=True).items()
                if not any(name == prefix or name.startswith(prefix + "/") for prefix in
                           ("src/fabrig", ".local/state/fleet-sync")) and name != "systemctl.log"}

    def simulate(self, host, before_code, after_fleet):
        self.legacy_fleet()
        fixture.put(self.f.source / "tools/fleet-sync", before_code, True)
        # Existing ops installation is never adopted, even as declarations arrive.
        for path, content in {
            ".config/kache/config.toml": "# ops-owned config\n",
            ".config/kache/store.env": "PRIVATE FIXTURE; never opened by fleet-sync",
            ".cache/kache/store/retain": "ops-owned data",
            ".config/systemd/user/kache.service": "# ops-owned unit\n",
        }.items():
            fixture.put(self.f.home / path, content)
        self.f.publish()
        self.f.sync("--host", host)
        self.f.sync("--host", host)
        previous = self.f.current()
        before = self.snapshot()
        managed = {key: self.f.state()[key] for key in ("managed_files", "managed_links", "managed_units")}
        calls = len(self.f.calls())
        fixture.put(self.f.source / "tools/fleet-sync", self.code, True)
        if after_fleet:
            shutil.rmtree(self.f.source / "fleet")
            shutil.copytree(fixture.ROOT / "fleet", self.f.source / "fleet")
            fixture.put(self.f.source / "fleet/repositories.toml",
                        f'agents = {json.dumps(str(self.f.origin))}\nfabrig = {json.dumps(self.f.fabrig_origin)}\n')
        else:
            # Same fleet, a different runner: promotion must not need new declarations.
            fixture.put(self.f.source / "tools/stage-a-fixture", "# code-only release marker\n")
        target = self.f.publish()
        state = self.f.sync("--host", host, "--timer", script=previous / "tools/fleet-sync")
        self.assertEqual(state["agents_sha"], target)
        self.assertEqual(self.f.current().name, "agents-" + target)
        self.assertTrue(state["last_timer_end"])
        self.assertEqual(state["consecutive_failures"], 0)
        self.assertIsNone(state["backoff_until"])
        self.assertEqual([i["item"] for i in state["items"] if i["result"] == "changed"], ["agents"])
        self.assertEqual({key: state[key] for key in managed}, managed)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(MUTATIONS & set(row) for row in self.f.calls()[calls:]))
        self.assertFalse(any("kache.service" in row for row in self.f.calls()[calls:]))
        self.assertNotIn("kache.service", state["managed_units"])
        return state

    def test_stage_b_changes_no_runner_code(self):
        # Stage B brought declarations alone. Compare that historical rollout,
        # allowing later runner changes after stage B has landed.
        stage_b = DEPLOYED.removesuffix("^")
        candidate = (self.f.process("git", "-C", fixture.ROOT, "show",
                                    stage_b + ":tools/fleet-sync").stdout
                     if stage_b != DEPLOYED else (fixture.ROOT / "tools/fleet-sync").read_text())
        self.assertEqual(self.f.process("git", "-C", fixture.ROOT, "show",
                                        DEPLOYED + ":tools/fleet-sync").stdout, candidate)


    def test_stage_a_accepts_future_assets_seeds_provision_pins_and_readonly_units(self):
        self.legacy_fleet()
        hosts = self.f.source / "fleet/hosts.toml"
        fixture.put(hosts, hosts.read_text().replace("[hosts.hetzner3]", "[hosts.hetzner3]\nseed = true"))
        versions = self.f.source / "fleet/versions.toml"
        fixture.put(versions, versions.read_text() + """
[kache.install]
kind = "kache-source"
repository = "https://example.invalid/kache"
rev = "0000000000000000000000000000000000000000"
patches = ["git-checkout-rev.patch", "upload-bound.patch"]
destination = ".local/bin/kache"
musl_url = "https://example.invalid/musl.tar.gz"
musl_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
[chromium]
version = "147.0.7727.101"
version_only_hosts = ["hel8"]
command = ["chromium", "--version"]
[chromium.install]
kind = "opt-tar"
seed = "peer"
source = ".local/opt/chromium-147.0.7727.101"
release = ".local/opt/chromium-147.0.7727.101"
entrypoint = "usr/lib/chromium/chromium"
manifest = "seeds/chromium.sha256"
seed_hosts = ["hetzner3"]
""")
        for name in ("bootstrap/README.md", "bootstrap/bootstrap.py", "kache/config.toml", "kache/build"):
            fixture.put(self.f.source / "fleet" / name, "not a declaration: fixture asset\n")
        fixture.put(self.f.source / "fleet/seeds/chromium.sha256", "directory 0755  .\n")
        fixture.put(self.f.source / "fleet/units/kache.service", "[Unit]\nDescription=fixture\n[Service]\nExecStart=/bin/true\n")
        roles = self.f.source / "fleet/units/roles.toml"
        fixture.put(roles, roles.read_text() + '\n"kache.service" = ["*"]\n')
        policy = self.f.source / "fleet/policy.toml"
        fixture.put(policy, policy.read_text() + '\n".config/kache/config.toml" = "check"\n".config/systemd/user/kache.service" = "check"\n')
        with patch.dict("os.environ", self.f.env, clear=True):
            module, runner = self.f.runner()
            self.assertTrue(runner.kache_declared())
            self.assertEqual(runner.d.versions["chromium"]["install"]["seed_hosts"], ["hetzner3"])
            runner.units()
            self.assertNotIn("kache.service", runner.unit_owned)
            self.assertFalse((self.f.home / ".config/systemd/user/kache.service").exists())
            self.assertTrue(any(i["result"] == "warn" and i["item"].endswith("kache.service") for i in runner.state["items"]))
            # New forms are validated, not merely ignored by a permissive parser.
            fixture.put(hosts, hosts.read_text().replace("seed = true", 'seed = "yes"'))
            with self.assertRaisesRegex(ValueError, "seed flag"):
                module.Declarations(self.f.source, self.f.home)


if __name__ == "__main__":
    unittest.main()
