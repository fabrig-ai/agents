#!/usr/bin/env -S python3 -I -B
"""Offline upper bound for run-hung episodes from records run lifecycle events.

Run events contain no events.jsonl mtime. Assuming no output since start gives
an upper bound, not proof of a hang. No producer commands or mail are invoked.
"""
import argparse
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import runpy
import tomllib

WATCH = runpy.run_path(str(Path(__file__).with_name('watch')))


def replay(records, config, days):
    starts, ends = {}, {}
    for path in sorted((records / 'events/runs').glob('*/*.jsonl')):
        for line in path.read_text().splitlines():
            event = json.loads(line)
            key = (event['host'], event['run'])
            if event['kind'] == 'run-start':
                starts[key] = event
            elif event['kind'] == 'run-end':
                ends[key] = event
    rows = {}
    for host, run in sorted(starts.keys() | ends.keys()):
        start, end = starts.get((host, run)), ends.get((host, run))
        # Some retained run-end rows predate the first available run-start.
        started = WATCH['stamp'](start['time']) if start else WATCH['stamp'](end['time']) - end['minutes'] * 60
        row = dict(run=run, owner='replay', effort=(start or end)['effort'],
                   started=started, changed=started, ended=False)
        if end:
            row['end'] = WATCH['stamp'](end['time'])
        rows.setdefault(host, []).append(row)
    rules = copy.deepcopy(config)
    for name, rule in rules.items():
        rule['enabled'] = name == 'run hung'
    state = {}
    result = []
    for day in sorted(set(days)):
        observed = [json.loads(line) for line in
                    (records / f'events/watch/hel8/{day}.jsonl').read_text().splitlines()]
        times = [WATCH['stamp'](event['time']) for event in observed]
        day_start = WATCH['stamp'](day + 'T00:00:00Z')
        day_end = WATCH['stamp']((date.fromisoformat(day) + timedelta(days=1)).isoformat() + 'T00:00:00Z')
        first, last = max(day_start, min(times)), min(day_end, max(times))
        # Heartbeats omit quiet polls. Rebuild the configured two-minute cadence
        # and include recorded times as well; completions become visible only
        # at their recorded event time, never using future median samples.
        ticks = sorted(set(times) | {first + offset for offset in range(0, int(last-first)+1, 120)})
        opened = []
        for now in ticks:
            data = dict(names={'replay': dict(always_watched=True, supervisor='')}, owned={})
            for host, runs in rows.items():
                data['runs/' + host] = [dict(row, ended=row.get('end', float('inf')) <= now)
                                        for row in runs if row['started'] <= now]
                for row in data['runs/' + host]:
                    if not row['ended']:
                        row.pop('end', None)
            candidates = WATCH['evaluate'](data, state, rules, now)
            events = WATCH['reconcile'](state, candidates, {}, rules, now, lambda *args: 0)
            opened.extend(dict(time=event['time'], subject=event['subject'])
                          for event in events if event['kind'] == 'alert-open')
        result.append(dict(day=day, first=WATCH['iso'](first), last=WATCH['iso'](last),
                           recorded_run_hung_openings=sum(event.get('rule') == 'run hung' and
                               event['kind'] == 'alert-open' for event in observed),
                           run_hung_openings_upper_bound=len(opened), openings=opened))
    return dict(mtime_assumption='unchanged since run start; upper bound only', days=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', type=Path)
    parser.add_argument('--day', action='append', required=True)
    args = parser.parse_args()
    with Path(__file__).with_name('watch.toml').open('rb') as stream:
        config = tomllib.load(stream)['rules']
    print(json.dumps(replay(args.records, config, args.day), indent=2))


if __name__ == '__main__':
    main()
