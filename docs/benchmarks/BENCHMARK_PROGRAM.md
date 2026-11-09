# Standardized Benchmark Program

## Purpose

Media Manglers needs a repeatable benchmark program that reflects the current repo and current approved sources, not one-off benchmark anecdotes or stale smoke links.

The benchmark program exists to measure:
- foreign-language speech-to-text accuracy
- foreign-language to English translation fidelity
- named-entity and domain-term preservation
- contamination, mojibake, omission, and repeated-fragment output failures
- runtime and real-time factor
- privacy and cost tradeoffs

Accuracy comes first. Runtime and cost matter, but they are tiebreakers after meaning preservation.

## Current benchmark source policy

- Use the approved motorsport / racing / sim-racing sources from the approved benchmark source set.
- Do not reuse the revoked short sources.
- Do not use playlists for bounded short benchmark passes.
- Keep smoke validation separate from benchmark reporting.

## Benchmark tiers

### Smoke

Use the tracked smoke scripts and validators for quick functional checks.
Smoke is not the benchmark program.

### Canonical short suite

Run this suite for:
- release candidates
- transcription or translation behavior changes
- model-routing changes
- protected-terms/profile changes
- reporting/schema changes that could affect language outputs

Current canonical short suite:
- English control: `1aA1WGON49E`
- German short A: `hNaUbuWL8MI`
- German short B: `7_u8Qj78cA0`
- French short: `XRka52Y3kyA`
- Japanese short: `WPm2N93SmTA`
- Spanish short: `5OspljwLkDQ`
- Italian short: `Xe6AgUkZmog`
- Chinese short: `fJ7V53jFrVc`

### Canonical long suite

Run this suite periodically for:
- milestone releases
- benchmark refresh passes
- major language/model architecture changes

Current canonical long suite:
- English long: `Pc-sv-w4yeA`
- German long: `GzcP3gciS6A`
- French long: `CYaZsZuc3AE`
- Italian long: `s_1I8ClUinQ`

### Technical terminology shadow set

Run this set when changes affect:
- protected-terms behavior
- named-entity protection
- UI/settings vocabulary
- SimHub / Crew Chief / tutorial ingestion paths

Current shadow-set direction:
- German Crew Chief basics
- one or two French SimHub tutorials
- optional English SimHub control

This shadow set exists because racing-history clips alone will not catch configuration/tutorial vocabulary regressions.

## Tracked manifests

Every benchmark source must be tracked in a machine-readable manifest. Each entry must include:
- title
- URL
- video ID
- expected language
- suite ID / tier
- source type
- topic class
- note about embedded English subtitles when known
- expected named entities or domain terms to preserve

The current tracked manifests live under `tools/benchmarks/manifests/`.

Benchmark manifests may also carry `expected_named_entities` hints for benchmark
sources. In benchmark-mode runs, those hints may be used in two narrow ways:

- in Hybrid runs, they may be passed into translation validation and repair so
  the benchmark can detect and reject avoidable proper-noun corruption such as
  `Brooklands -> Brooklyn`
- in Local/Hybrid transcription benchmark runs, they may be passed into Local
  Whisper as a narrow initial prompt so named-entity-sensitive benchmark lanes
  can measure whether exact proper-noun recall improves without post-correcting
  the raw transcript artifacts

Those hints are benchmark-scoped evidence, not a silent global protected-terms
profile. Generic product runs remain generic by default unless an operator
explicitly selects a protected-terms profile.

## Lane policy

Core benchmark lanes:
- `local-medium-cpu`
- `local-medium-gpu`
- `local-large-cpu`
- `local-large-gpu`
- `hybrid-public-medium-gpt-4o-mini`
- `hybrid-public-medium-gpt-4.1-mini`
- `hybrid-private-medium-gpt-5-mini`
- `hybrid-private-medium-gpt-4o-mini`
- `ai-private-whisper-1-gpt-5-mini`

Optional heavier lanes:
- `hybrid-private-large-gpt-5-mini`

Deferred future lanes:
- `ai-private-gpt-4o-mini-transcribe-gpt-5-mini`
- `ai-private-gpt-4o-transcribe-gpt-5-mini`

Those future lanes stay deferred until the repo cleanly supports approved non-`whisper-1` OpenAI transcription models.

## Device policy

The benchmark program must record both:
- requested Local Whisper device
- actual Local Whisper device used

That means CPU and GPU lanes must be explicit and comparable on a GPU-capable box. Auto-detected GPU use is not enough for benchmark reporting by itself.

## Scoring priorities

Benchmarks must reward meaning preservation, not just smooth prose.

Required metrics:
- app surface and version
- source label / URL / video ID
- suite and lane IDs
- source duration
- run duration
- real-time factor
- detected source language
- processing mode
- transcription provider/model
- translation provider/project
- requested model
- used model
- protected terms profile
- validation status
- estimated AI cost
- contamination count
- mojibake count
- omission/compression count
- repeated/fragmented output count
- named-entity preservation counts

## Named-entity and domain-term checks

The benchmark program must explicitly track whether important terms survive in:
- the source transcript
- the English translation

Current core checks include:
- Brooklands
- Hockenheimring
- Nürburgring
- Spa-Francorchamps
- Targa Florio
- SimHub
- Crew Chief
- iRacing

The benchmark scorer must flag `Brooklands -> Brooklyn` as a named-entity corruption.

The benchmark outputs must also separate:
- source-transcript substitution or omission
- translation-side corruption

That distinction matters because a raw/source transcript warning should not be
misread as a reopened translation defect after the earlier Hybrid translation fix.

## Protected terms policy inside benchmarks

- Generic mode is the default benchmark baseline.
- Do not silently apply the sim-racing profile to unrelated sources.
- If a profile-specific lane is intentionally benchmarked later, make that explicit in the lane metadata.
- French and non-German sources stay generic unless a future approved profile explicitly says otherwise.

## Evidence policy

Every benchmark run must preserve raw artifacts:
- package outputs
- source transcript text / json / srt when produced
- translated transcript text / json / srt when produced
- validation reports when produced
- `lane-meta.json`
- `script_run.log`
- `PROCESSING_SUMMARY.csv`
- benchmark summary csv/json/md outputs

Do not replace raw evidence with only a summary.

## README policy

When benchmark results are published, the repo README shows:
- current benchmark program entry point
- latest canonical short benchmark summary link
- latest canonical long benchmark status or placeholder
- best current local lane
- best current accuracy lane
- best current speed lane
- important caveats

## Related documents

- [Benchmark results schema](BENCHMARK_RESULTS_SCHEMA.md) - the fields every benchmark result records.
