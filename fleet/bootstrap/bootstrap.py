#!/usr/bin/env python3
"""Minimal root/user bootstrap; --dry-run works without root or a live HOME."""

import argparse
import os
from pathlib import Path
import pwd
import runpy
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]


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

    def pquota(self, host):
        enabled = host.get("pquota", False)
        if type(enabled) is not bool:
            raise ValueError("pquota flag must be boolean")
        if enabled:
            guard = None
            if not self.args.dry_run:
                guard = runpy.run_path(str(ROOT / "fleet/bootstrap/pquota"))["Pquota"](self.args.host)
                state = guard.bootstrap_begin()
            self.write("/etc/default/grub.d/90-fabrig-pquota.cfg",
                       'GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX rootflags=pquota"\n')
            self.run("update-grub")
            if guard:
                guard.finish_prepare(state)
            print("USER: pquota requires one drained reboot after root bootstrap; fleet-scale automation is pending.")

    def root(self):
        if not self.args.dry_run and os.geteuid() != 0:
            raise ValueError("root.sh must run as root")
        hosts = tomllib.loads((ROOT / "fleet/hosts.toml").read_text())["hosts"]
        host = hosts[self.args.host]
        if type(host.get("pquota", False)) is not bool:
            raise ValueError("pquota flag must be boolean")
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
        # Bind quota recovery to the final host identity before any boot write.
        self.run("hostnamectl", "set-hostname", hosts[self.args.host]["hostname"])
        self.pquota(host)
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
        origin = tomllib.loads((ROOT / "fleet/repositories.toml").read_text())["agents"]
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("root", "user"))
    parser.add_argument("--dry-run", action="store_true", help="print only; no reads from machine configuration, no writes or subprocesses")
    parser.add_argument("--host", default="hetzner2")
    args = parser.parse_args()
    hosts = tomllib.loads((ROOT / "fleet/hosts.toml").read_text())["hosts"]
    if args.host not in hosts:
        parser.error("unknown fleet host")
    bootstrap = Bootstrap(args)
    getattr(bootstrap, args.mode)()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"bootstrap: {error}")
