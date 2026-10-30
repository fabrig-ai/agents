`lifetime.py` is an unchanged test fixture from fabrig
`9a05948376f7bfebea0406abf00d92796f35a52c:tools/slots/lifetime.py`.
The bash suite copies it into its temporary HOME's fabrig installation.
It keeps the tests self-contained while slots is awaiting its separate move.
Production uses sibling `tools/slots` when present, otherwise the existing
`~/src/fabrig/main/tools/slots` installation.
