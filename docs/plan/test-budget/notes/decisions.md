# test-budget: the cut's decisions

What the request and its design left to the cut, each settled with its
reason. The spec binds them.

1. **One direct part, one task** (`cpu-budget`), as the request says: one
   concept, no contract another part reads.
2. **Readers of the summary line: none parse it.** Searched `fab/`,
   `fab/roles/*.md`, `bin/`, `scripts/` and `docs/design/`, 11-01: no test
   imports `fab.testrun` or matches the line. `fab/land.py` passes the
   output's last 20 lines on as free text, `fab/dispatch.py` reads only the
   exit, and `fab/roles/implementer.md` says "prints its time", still true.
   So the request's check changes no reader.
3. **The over-budget line stays as it is.** It names no unit, and the
   summary above it prints both.
4. **`fab/cli.py`'s help says CPU.** `run every test; fail past the 30 s CPU
   budget`: the only other place in the code that states the budget, and
   no test pins it. `AGENTS.md` and the older plans keep "30 s": the design
   still says under 30 s.
5. **The CPU start is taken where the wall start is**, before discovery, so
   both figures cover the same work. `os.times()` counts only children that
   were waited for, which the suite's commands are.
6. **`kind = "feature"`:** `main(argv)` keeps its signature and only a
   private helper is added.
7. **The suite has room.** On hel8 at load 1.5 on 11-01 it took 23.0 s of
   CPU (`user` 18.2 + `sys` 4.9) and 23.8 s of wall, so main stays under
   the budget with the change.
8. **Critical path:** the single task, 30 implementer-minutes.
