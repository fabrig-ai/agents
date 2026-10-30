"""Pool declarations shared by bootstrap and the convergence runner."""
import json
import os
from pathlib import Path
import re
import stat
import tomllib


def declaration(root, name, home=None):
    config = tomllib.loads((root / "fleet/pool.toml").read_text())
    if not re.fullmatch(re.escape(config["prefix"]) + r"-[1-9][0-9]*", name or ""):
        return None
    template = config["template"]
    host = {key: template[key].copy() for key in ("roles", "machine_env", "env")} | {
        "hostname": name, "ssh": f"free@{name}",
        **({"cargo_jobs": template["cargo_jobs"]} if "cargo_jobs" in template else {})}
    if home is not None:
        path = Path(home) / "src/fabrig/fleet/member.json"
        for component in (path, *path.parents):
            if component.is_symlink():
                raise ValueError("unsafe pool member settings path")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return host
        with os.fdopen(fd) as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ValueError("pool member settings must be a regular 0600 file")
            member = json.load(stream)
        if member.get("name") != name or type(member.get("local_only_kache")) is not bool:
            raise ValueError("invalid pool member settings")
        if member["local_only_kache"]:
            host["machine_env"]["KACHE_LOCAL_ONLY"] = 1
    return host


def repositories(root):
    return {name: f"ssh://FABRIG_CENTRAL/~/src/fabrig/mirror/{name}.git"
            for name in ("agents", "fabrig")}
