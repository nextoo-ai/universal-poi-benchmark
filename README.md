# Universal POI Benchmark

An end-to-end benchmark for discovering, evaluating, consolidating, and presenting
points of interest. The repository separates the work into three independent steps
so that data research, verification, and product design can be tested without mixing
their responsibilities.

## Pipeline

```text
POI discovery agents
        ↓
01-discovery
independent POI JSON submissions
        ↓
02-evaluation
validation, URL checks, matching, conflicts, and canonical groups
        ↓
consolidated POI JSON handoff
        ↓
03-ui-benchmark
design and evaluation of travel-planning applications
```

## Repository structure

| Directory | Step | Purpose |
|---|---|---|
| [`01-discovery`](01-discovery/) | Discovery | Defines how an agent researches and exports a real POI dataset for a destination. |
| [`02-evaluation`](02-evaluation/) | Evaluation | Imports multiple submissions into SQLite, validates URLs, proposes cross-agent matches, records conflicts, and exports reports. |
| [`03-ui-benchmark`](03-ui-benchmark/) | UI and UX | Defines a design-led benchmark for a universal travel planner built over user-loaded POI data. |

Each directory is self-contained and has its own README, contracts, examples, and
tests where applicable.

## Step handoffs

### Discovery → Evaluation

Every discovery agent produces an independent UTF-8 JSON dataset. Step 2 preserves
the original document and normalizes searchable fields without modifying the source.
Do not combine agent submissions before evaluation.

### Evaluation → UI benchmark

Step 2 creates canonical groups and identifies unresolved conflicts. A reviewed,
consolidated JSON export is the intended input for Step 3. The current evaluator
implements grouping, verification, reports, and review queues; a final reviewed
`canonical-poi-v1.json` export command remains future work.

Step 3 accepts a portable JSON object with a `pois` array. Its minimum upload contract
is intentionally compatible with richer discovery records and allows additional
fields.

## Public repository boundary

This repository contains benchmark definitions and implementation code. It does not
contain:

- agent submissions with hundreds of real POIs;
- the private consolidated development dataset;
- SQLite evaluation databases;
- generated review queues or benchmark results;
- downloaded or redistributed POI photographs.

The included examples are empty, minimal, or synthetic. Map and source-provider
attribution remains the responsibility of each application submission.

## Current status

- Step 1 includes a schema, taxonomy, destination profile, task, validator, and tests.
- Step 2 includes a working SQLite CLI pipeline, deterministic matching, resumable
  SSRF-safe URL validation, reports, review contracts, and tests.
- Step 3 includes the product brief, immutable-record planning model, upload and
  submission contracts, and a synthetic image-free fixture.
- The Step 3 scoring method is intentionally deferred. Visual quality and UX will
  account for at least 60% of its eventual evaluation.

## Development

Run each step from its own directory. For example:

```bash
cd 01-discovery
python -m unittest discover -s tests -v

cd ../02-evaluation
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

See the README inside each step for its complete workflow.
