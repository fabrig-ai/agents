"""Pool declarations shared by bootstrap and the convergence runner."""
import re
import tomllib


def declaration(root, name):
    config = tomllib.loads((root / "fleet/pool.toml").read_text())
    if not re.fullmatch(re.escape(config["prefix"]) + r"-[1-9][0-9]*", name or ""):
        return None
    template = config["template"]
    return {key: template[key] for key in ("roles", "machine_env", "env")} | {
        "hostname": name, "ssh": f"free@{name}",
        **({"cargo_jobs": template["cargo_jobs"]} if "cargo_jobs" in template else {})}


def repositories(root):
    return {name: f"ssh://FABRIG_CENTRAL/~/src/fabrig/mirror/{name}.git"
            for name in ("agents", "fabrig")}
