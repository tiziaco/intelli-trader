# evals/results/ — frozen baseline + hotspot artifacts

This directory holds the durable performance-evals artifacts. It is intentionally
empty (a `.gitkeep` placeholder) after Step 1 of the `PERF-BASELINE` spike.

`PERF-BASELINE-RESULTS.md` — the frozen baseline (W1 wall-clock + peak memory),
the ranked hotspot map, and the W2 scaling curve — is written in **Step 2**
(`/gsd:spike`), which runs Scalene on top of this harness. Step 1 (this quick
task) builds the harness only; **no profiling / Scalene invocation is run here**.

See `.planning/spikes/PERF-BASELINE.md` §10 / §12 for the Step 2 output spec.
