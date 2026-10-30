# Taste

How code in this repository reads. Every implementer's brief carries this
file after the role text; the gates (`fab/gates.py`) enforce its banned names;
the structure review adds pairs as it finds them. A pair is short, from this
repository, and says in one line why the good side wins.

## Banned names

A new public name may not contain one of these words (split at underscores
and capitals). Each says nothing about what the thing does; name that instead.

- `util` — a drawer, not a name.
- `utils` — the same drawer.
- `helper` — every function helps; say how.
- `helpers` — the same.
- `misc` — what does not fit belongs somewhere else.
- `common` — shared is a place, not a purpose.
- `manager` — names a role, hides the work.
- `handler` — says it is called, not what it does.
- `handle` — the verb of the same.
- `impl` — the code is the implementation.
- `tmp` — names a lifetime; say what it holds.
- `temp` — the same.
- `stuff` — nothing.
- `thing` — nothing.
- `obj` — every value is one.
- `data` — every value is data; say which.
- `info` — the same.
- `do` — every function does.
- `perform` — the same.
- `wrapper` — says it calls something else, not why.

## Pairs

### Write to a sibling, then rename

Why: a crash mid-write leaves the old file whole, and readers never see half
of one.

Bad:

```python
path.write_text(json.dumps(state))
```

Good:

```python
_write(path, json.dumps(state))  # fab.run._write: a temporary sibling, then replace
```

### Commands go through the runner

Why: tests pass `FakeRunner` and check the argv; nothing real runs where it is
not the point.

Bad:

```python
def fetch(repo: Path) -> None:
    subprocess.run(["git", "fetch", "origin"], cwd=repo, check=True)
```

Good:

```python
def fetch(repo: Path, *, sh: Runner = run) -> None:
    sh(["git", "fetch", "origin"], cwd=str(repo), check=True)
```

### Decide over plain data, act in a thin shell

Why: the decision is tested directly, without ssh or a log on disk.

Bad:

```python
def tick(plan_dir):
    for event in log.read():
        if event["ev"] == "run.started" and run_status_over_ssh(event)["ended"]:
            ...
```

Good:

```python
actions = decide(plan, tasks, events, hosts)  # pure
for action in actions:
    take(action)  # the shell
```

### Use the primitive on main

Why: one format everywhere; the reports compare timestamps as strings.

Bad:

```python
stamp = datetime.now(timezone.utc).isoformat()
```

Good:

```python
stamp = log.now()
```

### A docstring states the contract

Why: it is what the implementer fills and the next reader trusts; restating
the name tells neither anything.

Bad:

```python
def collect(run_id, events, hosts):
    """Collect the run."""
```

Good:

```python
def collect(run_id, events, hosts):
    """Collect an ended run once: copy its report here, log run.ended. Returns the
    outcome; None while the run is still going or when it was already collected."""
```
