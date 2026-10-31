+++
id = "host-roles"
part = "dispatch"
kind = "feature"
needs = ["foreman-tick", "run-place", "accounting"]
files = ["fab/hosts.py", "fab/dispatch.py", "fab/run.py", "fab/report.py", "fab/landing_report.py", "fab/code_report.py", "fab/flow.py", "fab/tests/test_package.py", "fab/tests/test_dispatch.py", "fab/tests/test_run.py", "fab/tests/test_report.py", "fab/tests/test_flow.py"]
effort = "medium"
minutes = 30
+++
# Hosts by role in one place

Which machine is the gate is one rule: the first host with role `gate`,
sorted by name. Every reader of the queue must agree on it, or the tick
imports one queue's record and untries on another. It is written out four
ways today:

- `fab.dispatch._import_queue` and `fab.dispatch._ready`:
  `sorted(name for name, host in hosts.items() if "gate" in host.roles)`,
  then `hosts[gate_hosts[0]]`;
- `fab.run._rejection`: `sorted((host for host in hosts.load().values()
  if "gate" in host.roles), key=lambda host: host.name)`, in a local named
  `gates`;
- `fab.report.gather`: `next((host for host in ordered if "gate" in
  host.roles), None)` over hosts sorted by name.

The builders are filtered the same way in `fab.dispatch.places`, `decide`'s
capacity, `fab.code_report.figures`, `fab.flow.measure` and
`fab.landing_report.figures` (for the gate). And `fab.flow.calm` parses
heavy's lines with its own `json.loads` loop, which is what
`fab.log.records` does since `tick-split`. Design: `docs/design/fab.md`,
sections 7 and 13.2.

## What changes

- `fab/hosts.py` gains `with_role(hosts: Mapping[str, Host], role: str) ->
  list[Host]`: the hosts holding role, sorted by name, with a docstring
  saying so. ValueError for a role not in ROLES.
- Every place above uses it. The gate is `with_role(hosts, "gate")[0]`;
  each caller keeps its own message and behaviour when there is none
  (`_import_queue` skips the import, `_ready` and `_rejection` raise their
  ValueError, `gather` adds `queue: no gate host`).
- `fab.run._rejection`'s local `gates` goes with the comprehension.
- `fab.flow.calm` takes its records from `log.records("\n".join(lines[2:]))`.
  It still never raises.
- No function grows. `fab.code_report.figures` is over 60 lines and must
  not grow (the size gate's ratchet): its one line changes in place.

## Acceptance

- `grep -n '"gate" in host.roles\|"builder" in host.roles' fab/*.py` finds
  only `fab/hosts.py`.
- `fab/tests/test_package.py`'s `HostsTest`: `with_role` orders by name,
  gives [] for a role no host has, and refuses an unknown role.
- `test_dispatch.py`, `test_run.py`, `test_report.py`, `test_flow.py` and
  the report tests pass unchanged. A test may be added, none weakened.
- `bin/fab test` passes, with no change in behaviour.

## Options, settled up front

- `with_role` returns Hosts, not names: every caller wants `.ssh` or
  `.name` from it.
- `fab.hosts.problems` and `fab.hosts.main` keep their own `"builder" in
  host.roles`: they judge one host, not a set.
