"""Archive bootstrap and semantic routing checks, using only fixture services."""

from contextlib import redirect_stdout
import io
import json
import os
import tarfile
import tomllib
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


class FleetSync2bTest(fixture.FleetFixture):
    def archive(self):
        archive = self.directory / "agents.tar"
        sibling = archive.with_name(archive.name + ".new")
        self.process("git", "-C", self.source, "archive", "--output", sibling, "HEAD")
        sibling.replace(archive)
        directory = self.directory / "archive"
        directory.mkdir()
        with tarfile.open(archive) as stream:
            stream.extractall(directory, members=[m for m in stream.getmembers()
                              if m.name.split("/")[0] in ("fleet", "tools")], filter="data")
        self.assertFalse((directory / ".git").exists())
        self.assertFalse((directory / ".fleet-release.json").exists())
        return directory

    def routing(self):
        hosts = tomllib.loads((self.source / "fleet/hosts.toml").read_text())["hosts"]
        return {name: "local" if name == "hel8" else host["ssh"] for name, host in hosts.items()}

    def routing_text(self, mapping):
        return "".join(f"{name} {target}\n" for name, target in mapping.items())

    def routing_item(self, state):
        return next(i for i in state["items"] if i["item"] == "src/rust/tmp/post/machines")

    def test_declared_origin_and_archive_source_fallback(self):
        declared = tomllib.loads((fixture.ROOT / "fleet/repositories.toml").read_text())
        self.assertEqual(declared["agents"], "git@github.com:fabrig-ai/agents.git")
        archive = self.archive()
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            with patch.object(module, "ROOT", archive):
                self.assertEqual(runner.source(), (str(self.origin), "unknown"))
            with patch.object(runner, "git", side_effect=FileNotFoundError("fixture missing git")):
                self.assertEqual(runner.source(), (str(self.origin), "unknown"))

    def test_archive_normal_run_bootstraps_using_declared_origin(self):
        archive = self.archive()
        state = self.sync(script=archive / "tools/fleet-sync")
        self.assertEqual(state["agents_sha"], self.sha)
        self.assertEqual(self.git(self.home / "src/fabrig/agents", "remote", "get-url", "origin").strip(), str(self.origin))
        self.assertTrue(any(i["item"] == "version:codex" for i in state["items"]))

    def test_archive_check_and_preview_cover_all_items_without_real_writes(self):
        archive = self.archive()
        before = self.snapshot()
        state = self.sync("--check", script=archive / "tools/fleet-sync", expected=1)
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "agents"), "drift")
        for name in ("fabrig", ".cargo/config.toml", "src/rust/tmp/post/machines", "version:codex"):
            self.assertTrue(any(i["item"] == name for i in state["items"]), name)
        self.assertEqual(before, self.snapshot())
        output = self.directory / "preview"
        result = self.process("python3", "-I", "-B", archive / "tools/fleet-sync", "--host", "hel8", "--preview", output)
        self.assertTrue((output / "home/.cargo/config.toml").is_file())
        self.assertIn("New files:", result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_source_prefers_metadata_then_own_checkout_and_ignores_parent_checkout(self):
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            runner.d.agents_origin = "declared-fallback"
            self.assertEqual(runner.source(), (str(self.origin), self.sha))
            fixture.put(self.source / ".fleet-release.json", json.dumps({"origin": "release-origin", "sha": "b" * 40}))
            self.assertEqual(runner.source(), ("release-origin", "b" * 40))
            (self.source / ".fleet-release.json").unlink()
            nested = self.source / "nested-archive"
            nested.mkdir()
            with patch.object(module, "ROOT", nested):
                self.assertEqual(runner.source(), ("declared-fallback", "unknown"))

    def test_agents_failure_in_check_does_not_skip_other_checks(self):
        self.sync()
        fixture.put(self.home / "src/fabrig/agents/untracked", "dirty\n")
        before = self.snapshot(exclude_mirror=True)
        state = self.sync("--check", expected=1)
        self.assertEqual(state["items"][0]["item"], "agents")
        self.assertEqual(state["items"][0]["result"], "failed")
        for name in ("fabrig", ".cargo/config.toml", "src/rust/tmp/post/machines", "version:claude", "enabled:fleet-sync.timer"):
            self.assertTrue(any(i["item"] == name for i in state["items"]), name)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))

    def test_agents_failure_in_preview_does_not_skip_rendering_or_version_notice(self):
        before = self.snapshot()
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            runner.args.preview = str(self.directory / "preview")
            runner.item("agents", "failed", "fixture agents failure")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(runner.run(), 1)
        self.assertTrue((self.directory / "preview/home/.cargo/config.toml").exists())
        self.assertTrue(any(i["item"] == "versions" and i["result"] == "deferred" for i in runner.state["items"]))
        self.assertFalse(any(i["item"].startswith("version:") for i in runner.state["items"]))
        self.assertEqual(before, self.snapshot())

    def test_routing_equal_ignores_order_comments_and_current_username(self):
        path = self.home / "src/rust/tmp/post/machines"
        rows = [f"{name} {target.removeprefix('free@')}" for name, target in reversed(list(self.routing().items()))]
        fixture.put(path, "# operator order\n\n" + "\n\n".join(rows) + "\n# end\n")
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        for flags in ((), ("--check",)):
            state = self.sync(*flags, env={**self.env, "USER": "free"})
            self.assertEqual(self.routing_item(state)["result"], "ok")
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertFalse(path.with_name("machines.pre-fleet-sync").exists())

    def test_routing_difference_lists_exact_missing_extra_changed_names(self):
        path = self.home / "src/rust/tmp/post/machines"
        mapping = self.routing()
        mapping.pop("hetzner7")
        mapping["hetzner3"] = "someone-else@2.29.124.199"
        mapping["extra"] = "unexpected.example"
        fixture.put(path, self.routing_text(mapping))
        before = path.read_bytes()
        for flags in ((), ("--check",)):
            item = self.routing_item(self.sync(*flags, env={**self.env, "USER": "free"}))
            self.assertEqual(item["result"], "warn")
            self.assertEqual(item["reason"], "names differ: extra, hetzner3, hetzner7; check-only")
            self.assertEqual(path.read_bytes(), before)
        self.assertFalse(path.with_name("machines.pre-fleet-sync").exists())

    def test_routing_uses_user_and_rejects_ambiguous_or_malformed_names(self):
        path = self.home / "src/rust/tmp/post/machines"
        desired = self.routing_text(self.routing())
        cases = (("hel8 local\n", "hel8"), ("mystery\n", "mystery"),
                 ("hetzner7 wrong.example\n", "hetzner7"))
        for extra, name in cases:
            with self.subTest(extra=extra):
                # Identical duplicate entries are still a single mapping.
                fixture.put(path, desired + extra)
                item = self.routing_item(self.sync("--check", expected=1, env={**self.env, "USER": "free"}))
                self.assertEqual(item["result"], "ok" if name == "hel8" else "warn")
                if name != "hel8":
                    self.assertEqual(item["reason"], f"names differ: {name}; check-only")
        mapping = self.routing()
        mapping["hetzner7"] = mapping["hetzner7"].removeprefix("free@")
        fixture.put(path, self.routing_text(mapping))
        item = self.routing_item(self.sync("--check", expected=1, env={**self.env, "USER": "another-user"}))
        self.assertEqual(item["reason"], "names differ: hetzner7; check-only")

    def test_preview_reports_routing_meaning_without_writing_it(self):
        path = self.home / "src/rust/tmp/post/machines"
        fixture.put(path, self.routing_text(dict(reversed(list(self.routing().items())))))
        before = self.snapshot()
        output = self.directory / "preview-equal"
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--preview", output)
        self.assertNotIn("warn    src/rust/tmp/post/machines", result.stdout)
        self.assertEqual((output / "home/src/rust/tmp/post/machines").read_bytes(), path.read_bytes())
        self.assertEqual(before, self.snapshot())
        fixture.put(path, self.routing_text(self.routing()).replace("hel8 local", "hel8 wrong"))
        before = self.snapshot()
        output = self.directory / "preview-different"
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--preview", output)
        self.assertIn("names differ: hel8; check-only", result.stdout)
        self.assertEqual((output / "home/src/rust/tmp/post/machines").read_bytes(), path.read_bytes())
        self.assertEqual(before, self.snapshot())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(FleetSync2bTest(name) for name in FleetSync2bTest.__dict__ if name.startswith("test_"))
