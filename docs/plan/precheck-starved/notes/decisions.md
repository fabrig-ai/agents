# precheck-starved: the cut's decisions

What the request and its design left to the cut, each settled with its
reason. The spec binds them.

1. **One direct part, one task** (`precheck-collector`), as the request
   says: one concept, no contract another part reads.
2. **The collector's lane is a keyword.** `fab.queue_cpu.run_steps` builds
   its wrapper with `lane="gate"` (`heavy --gate cc`); precheck runs in the
   build lane (landing.md 2). It gains `lane: str = "gate"`, passed to
   `cpu.build_wrapper`; the queue's call is unchanged. A parameter added to
   a public function makes the task `kind = "interface"` (gates.md 2).
3. **Precheck passes `record = {"selection": receipt["selection"]}`** so
   the collector's `full` reads as the queue's does; the record's
   `cpu_trees` stay in the log the collector writes, not the receipt.
4. **The receipt's starved count is `starved`, an int**, always present
   (0 for docs, conflict, or no test step): the number of starved cases in
   the derived `gate-junit.xml` reports `run_steps` returns (failure type
   `test timeout`), summed over default and fuzzy. `outcome` stays
   `green`/`red`/`conflict` from the steps' `green`, so receipt reuse
   (landing.md 3) and `fab/receipts.py` `parse` (which keeps other keys)
   are unchanged.
5. **The log names the starved tests** from those same reports, after the
   collector's own lines: one line per case,
   `<profile>: starved <binary> <test>`. Count and names come from one
   source, the reconciled cases the queue's red classification reads.
6. **A repeated precheck of one tip** replaces its collector directory:
   `run_steps` makes `log.with_suffix("")` (`FAB_HOME/precheck/<tip>/`)
   with `exist_ok=False`, so precheck removes it before the steps (it
   already empties the log). Without this the second check of a tip
   raises.
7. **Critical path:** the single task, 60 implementer-minutes.
