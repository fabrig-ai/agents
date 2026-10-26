"""Receipt publication faults shared by direct validator rows and fake heavy.

Only disposable fixture paths are passed here; this never queries a queue.
"""
import hashlib
import json
import os


def submission_header(token, lane, fault=""):
    lines = []
    header = f"heavy: queued task 1 in the {lane} lane token {token}"
    if fault == "legacy_header":
        header = "heavy: queued task 1 in the gate lane"
    if fault == "non_gate_header":
        header = f"heavy: queued task 1 in the build lane token {token}"
    if fault == "malformed_header_token":
        header = "heavy: queued task 1 in the gate lane token malformed"
    if fault != "missing_header":
        lines.append(header)
    if fault == "duplicate_header":
        lines.append(header)
    return "\n".join(lines) + ("\n" if lines else "")


def completion_output(state, token, args, tree, policy, head, output, code=0, fault=""):
    lines = []
    receipts = state / "receipts"
    logs = state / "logs with spaces"
    receipts.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / (token + ".log")
    log.write_bytes(output)
    receipt = dict(schema="heavy-receipt-v1", token=token, id="1", queue="isolated-fixture",
                   lane="gate", tree=tree, policy=policy, args=args,
                   outcome="completed", code=code, payload_started=True,
                   payload_ended=True, release_complete=True, cgroup_empty=True,
                   elapsed_s=0.25, log=str(log), log_sha256=hashlib.sha256(output).hexdigest(),
                   head=head,
                   inputs=tree)
    if fault == "old_build_same_id":
        # A queued cancellation finds an older build's successful numeric-ID row.
        old = state / "old-build.log"
        old.write_text("heavy: ran alone for 7s\n")
        (state / "heavy.tsv").write_text(f"1\tbuild\told\t0\t7\t0\t0\t.\t{old}\n")
        return f"heavy: task 1 (build) exit 0, waited 0s, ran 7s, log {old}\n".encode()
    changes = {
        "wrong_token": ("token", "f" * 32), "wrong_id": ("id", "2"), "numeric_id": ("id", 1),
        "wrong_lane": ("lane", "build"), "wrong_tree": ("tree", "f" * 40),
        "wrong_policy": ("policy", "sha256:" + "f" * 64), "wrong_args": ("args", ["true"]),
        "cancelled": ("outcome", "cancelled"), "failed_code": ("code", 1),
        "boolean_code": ("code", False), "payload_not_started": ("payload_started", False),
        "payload_not_ended": ("payload_ended", False), "release_incomplete": ("release_complete", False),
        "scope_not_empty": ("cgroup_empty", False), "duration_string": ("elapsed_s", "?"),
        "duration_bool": ("elapsed_s", True), "duration_negative": ("elapsed_s", -1),
        "duration_nan": ("elapsed_s", float("nan")), "duration_infinite": ("elapsed_s", float("inf")),
        "empty_queue": ("queue", ""), "non_string_queue": ("queue", 1),
        "wrong_schema": ("schema", "heavy-receipt-v0"), "wrong_log_name": ("log", str(logs / "other.log")),
        "relative_log": ("log", token + ".log"), "wrong_digest": ("log_sha256", "0" * 64),
        "malformed_head": ("head", "HEAD"), "non_string_inputs": ("inputs", 1),
    }
    if fault in changes:
        key, value = changes[fault]
        receipt[key] = value
    if fault == "missing_duration":
        del receipt["elapsed_s"]
    if fault == "no_inputs":
        del receipt["head"], receipt["inputs"]
    if fault == "extra_field":
        receipt["unknown"] = True
    path = receipts / (token + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt))
    temporary.replace(path)
    if fault == "malformed_json":
        path.write_text("{broken")
    if fault == "duplicate_field":
        path.write_text(path.read_text()[:-1] + ', "code": 0}')
    if fault == "non_object_json":
        path.write_text("[]")
    if fault == "receipt_symlink":
        target = path.with_suffix(".saved")
        path.rename(target)
        path.symlink_to(target)
    if fault == "receipt_directory":
        path.unlink()
        path.mkdir()
    if fault == "receipt_fifo":
        path.unlink()
        os.mkfifo(path)
    if fault == "missing_receipt_file":
        path.unlink()
    if fault == "unreadable_receipt":
        path.chmod(0)
    if fault == "mutated_log":
        log.write_bytes(b"mutated completed log\n")
    if fault == "missing_log":
        log.unlink()
    if fault == "unreadable_log":
        log.chmod(0)
    if fault == "log_symlink":
        target = log.with_suffix(".saved")
        log.rename(target)
        log.symlink_to(target)
    if fault == "log_directory":
        log.unlink()
        log.mkdir()
    if fault == "log_fifo":
        log.unlink()
        os.mkfifo(log)
    if fault == "wrong_filename":
        target = path.with_name("other.json")
        path.rename(target)
        path = target
    if fault == "stale_valid_receipt":
        path = next(candidate for candidate in receipts.glob("*.json") if candidate != path)
        token = path.stem
    lines.append(output)
    lines.append("heavy: task 1 (gate) exit 0, waited 0s, ran 0s\n")
    line_token = "f" * 32 if fault == "wrong_line_token" else token
    line = f"heavy: receipt {path} token {line_token}"
    if fault == "relative_receipt":
        line = f"heavy: receipt {path.name} token {line_token}"
    if fault == "malformed_receipt_line":
        line = f"heavy: receipt {path} token malformed"
    if fault != "missing_receipt_line":
        lines.append(line + "\n")
    if fault == "duplicate_receipt":
        lines.append(line + "\n")
    if fault == "output_after_receipt":
        lines.append("heavy: late output\n")
    return b"".join(line.encode() if isinstance(line, str) else line for line in lines)
