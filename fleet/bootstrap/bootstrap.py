#!/usr/bin/env python3
"""Minimal root/user bootstrap; --dry-run works without root or a live HOME."""

import argparse
import json
import os
from pathlib import Path
import pwd
import runpy
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
POOL = runpy.run_path(str(ROOT / "fleet/pool.py"))


def host_declaration(name):
    return (POOL["declaration"](ROOT, name) or
            tomllib.loads((ROOT / "fleet/hosts.toml").read_text())["hosts"].get(name))


class Bootstrap:
    def __init__(self, args):
        self.args = args

    def run(self, *argv, capture=False):
        print("$ " + shlex.join(map(str, argv)), flush=True)
        if self.args.dry_run:
            return ""
        return subprocess.run(list(map(str, argv)), check=True, text=True,
                              stdout=subprocess.PIPE if capture else None).stdout or ""

    def write(self, path, content, mode=0o644, owner=None):
        print(f"file {path} mode={mode:04o}")
        if self.args.dry_run:
            return
        path = Path(path)
        # Follow no configuration/destination symlinks, including parents.
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError(f"refusing symlink: {parent}")
        if path.exists() and not path.is_file():
            raise ValueError(f"not a regular file: {path}")
        data = content.encode() if isinstance(content, str) else content
        if path.exists() and path.read_bytes() == data:
            os.chmod(path, mode)
            if owner:
                os.chown(path, *owner)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), mode)
                if owner:
                    os.fchown(stream.fileno(), *owner)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def root(self):
        if not self.args.dry_run and os.geteuid() != 0:
            raise ValueError("root.sh must run as root")
        packages = [line.partition("#")[0].strip() for line in
                    (ROOT / "fleet/bootstrap/packages.txt").read_text().splitlines()]
        packages = [p for p in packages if p]
        self.run("apt-get", "update")
        self.run("env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", *packages)
        try:
            user = pwd.getpwnam("free") if not self.args.dry_run else None
        except KeyError:
            user = None
        if user is None:
            self.run("useradd", "--create-home", "--shell", "/bin/bash", "--user-group", "free")
        if not self.args.dry_run:
            user = pwd.getpwnam("free")
            if user.pw_dir != "/home/free":
                raise ValueError("free must have HOME /home/free")
        self.run("hostnamectl", "set-hostname", host_declaration(self.args.host)["hostname"])
        self.run("usermod", "--append", "--groups", "sudo", "free")
        sudoers = "free ALL=(ALL) NOPASSWD: ALL\n"
        if not self.args.dry_run:
            # Validate before promotion so an interrupted run cannot break sudo.
            fd, temporary = tempfile.mkstemp(prefix=".bootstrap-sudo-", dir="/etc/sudoers.d")
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(sudoers)
                self.run("visudo", "-cf", temporary)
            finally:
                Path(temporary).unlink(missing_ok=True)
        self.write("/etc/sudoers.d/free", sudoers, 0o440)
        # Authorized public keys are the only SSH material bootstrap reads.
        # Private keys and sshd configuration are never read or changed.
        if self.args.dry_run:
            print("copy root authorized PUBLIC keys to free if missing; preserve existing keys")
        else:
            destination = Path("/home/free/.ssh/authorized_keys")
            if not destination.exists():
                source = Path("/root/.ssh/authorized_keys")
                if source.is_symlink() or not source.is_file():
                    raise ValueError("USER: install public authorized key in /root/.ssh/authorized_keys first")
                sshdir = destination.parent
                if sshdir.is_symlink():
                    raise ValueError("refusing symlink .ssh")
                sshdir.mkdir(mode=0o700, exist_ok=True)
                sshdir.chmod(0o700)
                os.chown(sshdir, user.pw_uid, user.pw_gid)
                self.write(destination, source.read_bytes(), 0o600, (user.pw_uid, user.pw_gid))
            elif destination.is_symlink() or not stat.S_ISREG(destination.stat().st_mode):
                raise ValueError("refusing unsafe authorized_keys")
        self.pool_public_keys(user)
        self.run("loginctl", "enable-linger", "free")
        self.write("/etc/apt/apt.conf.d/20auto-upgrades", 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n')
        self.write("/etc/apt/apt.conf.d/99-fleet-no-reboot", 'Unattended-Upgrade::Automatic-Reboot "false";\n')
        # These are the only limits found on both hosts (Debian defaults).
        self.write("/etc/security/limits.d/10-coredump-debian.conf",
                   "* soft core 0\nroot soft core 0\n* hard core infinity\nroot hard core infinity\n")
        self.run("systemctl", "enable", "--now", "unattended-upgrades", "apt-daily.timer", "apt-daily-upgrade.timer")
        # Cap the system journal (hel8 reached 620 MB, 10-30); journald reads drop-ins at restart.
        self.write("/etc/systemd/journald.conf.d/90-fabrig.conf", "[Journal]\nSystemMaxUse=200M\n")
        self.run("systemctl", "restart", "systemd-journald")
        print("No swap or custom sysctl settings were found; Debian/image defaults apply.")

    def pool_public_keys(self, user):
        if POOL["declaration"](ROOT, self.args.host):
            if self.args.dry_run:
                print("install fleet-scale PUBLIC key for root and free")
            else:
                public = (ROOT / "fleet/bootstrap/fleet-scale.pub").read_text().strip()
                if not public.startswith("ssh-ed25519 ") or "\n" in public:
                    raise ValueError("invalid fleet-scale public key")
                for account, owner in (("/root", (0, 0)), ("/home/free", (user.pw_uid, user.pw_gid))):
                    directory = Path(account) / ".ssh"
                    if directory.is_symlink():
                        raise ValueError("unsafe .ssh directory")
                    directory.mkdir(mode=0o700, exist_ok=True)
                    directory.chmod(0o700)
                    os.chown(directory, *owner)
                    destination = directory / "authorized_keys"
                    if destination.is_symlink():
                        raise ValueError("unsafe authorized_keys")
                    previous = destination.read_text() if destination.exists() else ""
                    if public not in previous.splitlines():
                        self.write(destination, previous + ("\n" if previous and not previous.endswith("\n") else "") + public + "\n", 0o600, owner)

    def user(self):
        if not self.args.dry_run and (os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "free"):
            raise ValueError("user.sh must run as free, without sudo")
        home = Path.home()
        versions = tomllib.loads((ROOT / "fleet/versions.toml").read_text())
        rust = versions["rustc"]["install"]
        options = ["--profile", rust["profile"]]
        for component in rust["components"]:
            options += ["--component", component]
        for target in rust["targets"]:
            options += ["--target", target]
        self.run("rustup", "toolchain", "install", rust["toolchain"], *options, "--no-self-update")
        self.run("rustup", "default", rust["toolchain"])
        for extra in rust["extra_toolchains"]:
            self.run("rustup", "toolchain", "install", extra, "--profile", rust["profile"], "--no-self-update")
        agents = home / "src/fabrig/agents"
        origin = (POOL["repositories"](ROOT) if POOL["declaration"](ROOT, self.args.host) else
                  tomllib.loads((ROOT / "fleet/repositories.toml").read_text()))["agents"]
        if self.args.dry_run:
            print(f"clone {origin} to {agents} if missing; validate existing origin and clean checkout")
        else:
            for parent in (agents, *agents.parents):
                if parent.is_symlink():
                    raise ValueError(f"refusing symlink: {parent}")
            if not agents.exists():
                agents.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".agents-bootstrap-", dir=agents.parent) as temporary:
                    clone = Path(temporary) / "clone"
                    self.run("git", "clone", "--", origin, clone)
                    clone.rename(agents)
            if self.run("git", "-C", agents, "rev-parse", "--show-toplevel", capture=True).strip() != str(agents):
                raise ValueError("agents is not a dedicated checkout")
            if self.run("git", "-C", agents, "remote", "get-url", "origin", capture=True).strip() != origin:
                raise ValueError("agents has a foreign origin")
            if self.run("git", "-C", agents, "status", "--porcelain", "--untracked-files=all", capture=True).strip():
                raise ValueError("agents checkout is dirty")
        # Empty operational directories only. No locks, queues, claims, sessions,
        # login files, spool messages or heavy ledger are synthesized or reset.
        for relative in ("src/rust/tmp/post", "src/rust/tmp/kache", "src/rust/tmp/logs",
                         "src/fabrig/tasks", "src/fabrig/notes", "src/fabrig/ops"):
            directory = home / relative
            print(f"mkdir -p {directory}")
            if not self.args.dry_run:
                for parent in (directory, *directory.parents):
                    if parent.is_symlink():
                        raise ValueError(f"refusing symlink: {parent}")
                directory.mkdir(parents=True, exist_ok=True)
        runner = agents / "tools/fleet-sync"
        self.run(sys.executable, "-I", "-B", runner, "--provision", "--host", self.args.host)
        self.run(sys.executable, "-I", "-B", home / "src/fabrig/current/tools/fleet-sync", "--host", self.args.host)
        print("USER: complete Claude/Codex logins and verification; keep the host drained until acceptance.")

    def member(self):
        if not POOL["declaration"](ROOT, self.args.host):
            raise ValueError("member settings require a pool host")
        self.write(Path.home() / "src/fabrig/fleet/member.json", json.dumps({
            "name": self.args.host, "local_only_kache": self.args.local_only_kache}) + "\n", 0o600)

    def kache(self):
        host = POOL["declaration"](ROOT, self.args.host, None if self.args.dry_run else Path.home())
        if not host or host["machine_env"].get("KACHE_LOCAL_ONLY"):
            raise ValueError("shared kache setup requires a shared-store pool member")
        # fleet-scale calls this only on its newly provisioned, drained member.
        # Credentials are inspected by metadata only, never read here.
        pool = tomllib.loads((ROOT / "fleet/pool.toml").read_text())
        destination = pool["kache_destination"]
        if not destination.startswith("~/") or ".." in Path(destination[2:]).parts:
            raise ValueError("unsafe kache destination")
        if not self.args.dry_run:
            path = Path.home() / destination[2:]
            for component in (path, *path.parents):
                if component.is_symlink():
                    raise ValueError("unsafe kache credential path")
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ValueError("kache credential must be a regular 0600 file")
        values = host["machine_env"]
        cap, floor = values["KACHE_MAX_GB"], values["PLAN_MIN_DISK_GB"]
        config = (ROOT / "fleet/kache/config.toml").read_text()
        config = config.replace("@CAP@", str(cap)).replace("@LOCAL_ONLY@", "false")
        config = config.replace("@RECOVERY@", str((floor + max(cap, 1)) * 1024**3))
        config += (ROOT / "fleet/kache/remote.toml").read_text()
        self.write(Path.home() / ".config/kache/config.toml", config, 0o600)
        dropin = (ROOT / "fleet/kache/20-shared-store.conf").read_text()
        dropin = dropin.replace("%h/.config/kache/store.env", "%h/" + destination[2:])
        self.write(Path.home() / ".config/systemd/user/kache.service.d/20-shared-store.conf", dropin, 0o600)
        self.run("systemctl", "--user", "daemon-reload")
        self.run("systemctl", "--user", "restart", "kache.service")

    def seed(self):
        if not POOL["declaration"](ROOT, self.args.host) or not self.args.seed:
            raise ValueError("seed mode requires a pool host and --seed")
        if self.args.dry_run:
            print(f"verify and install pinned seed {self.args.seed} for {self.args.host}")
            return
        module = runpy.run_path(str(ROOT / "tools/fleet-sync"), run_name="fleet_seed")
        pin = tomllib.loads((ROOT / "fleet/versions.toml").read_text())[self.args.seed]
        install = pin["install"]
        if install.get("seed") != "peer":
            raise ValueError("seed mode accepts only pinned peer artifacts")
        module["validate_install"](self.args.seed, install, pin["version"])
        entries = module["seed_entries"](ROOT, install)
        destination = Path.home() / install.get("release", install.get("destination", ""))
        for parent in (destination, *destination.parents):
            if parent.is_symlink():
                raise ValueError("unsafe seed destination")
        if destination.exists():
            raise ValueError("pool preseed requires an absent destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".pool-seed-") as temporary:
            work = Path(temporary)
            with (work / "archive").open("xb") as stream:
                shutil.copyfileobj(sys.stdin.buffer, stream)
            module["Runner"].unpack_seed(None, work / "archive", work / "verified", entries)
            source = work / "verified" if install["kind"] != "binary" else work / "verified/payload"
            source.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("root", "user", "seed", "member", "kache"))
    parser.add_argument("--seed")
    parser.add_argument("--local-only-kache", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print only; no reads from machine configuration, no writes or subprocesses")
    parser.add_argument("--host", default="hetzner2")
    args = parser.parse_args()
    if not host_declaration(args.host):
        parser.error("unknown fleet host")
    bootstrap = Bootstrap(args)
    getattr(bootstrap, args.mode)()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"bootstrap: {error}")
