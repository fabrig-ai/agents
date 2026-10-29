# agents

fabrig's factory: the fleet's declarations and its deployment (`fleet/`, `tools/`), and in time the roles, prompts and tools that run the pipeline. Private. It does not go through fabrig's merge queue.

`old/` is the legacy kit as it was at tag `legacy-2026-10-28`. Machines still run some of its tools from their frozen `~/src/rust/agents` checkouts until each tool is ported or retired. Never fast-forward those checkouts: this tree moved, and their links would break.
