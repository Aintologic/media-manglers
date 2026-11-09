Media Manglers Benchmark Guide
==============================

Purpose
-------
The benchmark framework turns repeatable motorsport/sim-racing benchmark runs
into compareable CSV, JSON, and Markdown outputs. It is separate from the smoke
and validator scripts.

Key docs
--------
- BENCHMARK_PROGRAM.md
- BENCHMARK_RESULTS_SCHEMA.md

Tracked suite manifests
-----------------------
- tools\benchmarks\manifests\canonical-short.json
- tools\benchmarks\manifests\canonical-long.json
- tools\benchmarks\manifests\technical-terminology-shadow.json
- tools\benchmarks\manifests\benchmark-lanes-v1.json

Tracked benchmark tools
-----------------------
- tools\benchmarks\Run-BenchmarkSuite.ps1
- tools\benchmarks\benchmark_report.py

Normal workflow
---------------
1. Pick a suite manifest and the lanes you want to run.
2. Run the benchmark suite into a dedicated output root.
3. Keep the raw package outputs, lane-meta.json files, and logs.
4. Use the generated benchmark-summary.csv / benchmark-results.json /
   benchmark-summary.md to compare lanes over time.

Bounded benchmark rules
-----------------------
- Use only approved single-video sources for bounded short passes.
- Do not use playlists for bounded short benchmark passes.
- Do not use revoked short sources.

Important caveats
-----------------
- Accuracy outranks runtime.
- Benchmark summaries do not replace raw artifacts.
- Raw benchmark packages and lane-meta.json files live in the local output
  root used for the pass; they are not tracked in Git.
- The technical terminology shadow set exists because racing-history clips alone
  will not catch SimHub / Crew Chief / UI vocabulary regressions.
