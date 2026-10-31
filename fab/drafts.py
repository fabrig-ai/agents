"""Several plans in one tick: what each draft owns, and what the plans share
(docs/design/fab.md, 13.4).

The tick takes every listed plan in turn. Each plan's draft owns its tasks' runs, its
calls (their subject is the draft or under it) and those calls' review runs; it collects,
counts and limits only those. Builders' places and the one calm extra place per builder
are shared: the plans decide in order on the log as the plans before them left it.
A plan's design calls run in parallel up to its flow target (13.2). Every function here
is pure: it reads only its arguments.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from fab import flow
from fab.plan import Plan

DESIGN_ROLES = ("skeleton", "contract")  # the calls that design a part, sharing one limit


def under(draft: str, name: object) -> bool:
    """Whether name is the draft's: equal to draft, or starting with `<draft>/`. A name that
    is not a string (a record missing the field) is no draft's: False."""
    raise NotImplementedError


def owned(draft: str, flight: Iterable[dict], events: Iterable[dict]) -> list[dict]:
    """The run.started records of flight that are the draft's, in flight's order.

    flight is fab.dispatch.in_flight(events). A run is the draft's when its task is
    under(draft, ...) (the draft's tasks' runs and their foreman runs, `<draft>/<task>/foreman`),
    or when its kind is review and its task, the root call's id, names a call.started of
    events whose subject is under(draft, ...). A record whose task is not a string is no
    draft's. Never raises on a record missing a field."""
    raise NotImplementedError


def strays(drafts: Iterable[str], flight: Iterable[dict], events: Iterable[dict]) -> list[dict]:
    """The run.started records of flight that no draft of drafts owns (owned), in flight's
    order: runs of retired or unlisted plans and of calls with no draft. The tick collects
    them after every plan has ticked, so a run is never left uncollected. events is read
    once whatever the number of drafts."""
    raise NotImplementedError


def design_calls(plan: Plan, fresh: Sequence[str], events: Iterable[dict]) -> list[tuple[str, str]]:
    """The design calls to start now for plan, as (part id, role), in fresh's order.

    fresh is fab.dispatch.call_actions' list: parts of the design action not designed,
    not parked and with no open chain. The draft's design calls in flight are the
    call.started records of events whose role is in DESIGN_ROLES, whose subject is
    under(plan.draft, ...), and with no call.ended for the same call. The limit is
    fab.flow.target(plan.draft, events). While the calls in flight plus those chosen so far
    are below it, each part of fresh is chosen unless it is not in plan.parts or its
    subject `<draft>/<part>` has a design call in flight; its role is contract when
    plan.parts[part].contract, else skeleton. Empty when the calls in flight already reach
    the limit. Pure."""
    raise NotImplementedError


def spend(calm: Mapping[str, bool] | None, hosts: Iterable[str]) -> dict[str, bool]:
    """calm (fab.flow.measure's) after a plan started runs on hosts: a copy in which every
    builder named in hosts is False, the others as they were. None gives {}. A builder
    takes its calm extra place once per tick whichever plan uses it: in one decide a
    builder uses either its free places or its one extra (fab.dispatch.places), never both,
    so a builder a plan started on gives the later plans its free places only."""
    raise NotImplementedError


def unit(role: str, key: str) -> str:
    """The user unit a call runs in: `fab-call-<role>-<key>`, key being the call's subject
    (for skeleton and contract `<draft>/<part>`, for answer the draft, for review and
    retire `<draft>/review` and `<draft>/retire`) or, for amend, its root call's id; every
    character of key outside ASCII letters, digits and `-` is written `_`. systemd refuses
    a second unit of a name while the first runs, so one subject never has two calls
    running, even when the log does not show the first yet; two keys written alike only
    wait for each other. ValueError when role or key is empty."""
    raise NotImplementedError
