# Step 2 — POI Evaluator

`poi-evaluator` is a city-independent SQLite pipeline for comparing POI datasets
submitted by multiple agents. It preserves the original JSON, extracts searchable
records, validates URLs without allowing requests into private networks, proposes
cross-submission identity matches, and exports a review queue and summary report.

Version 0.1 deliberately keeps qualitative LLM review outside the deterministic
pipeline. The adapter boundary, prompt, and JSON contracts are included so a later
review worker can consume explicit queue items without becoming a source of truth
for imports, HTTP checks, or matching.

The next design phase is specified separately in [Step 3](../03-ui-benchmark/README.md).
It gives every UI agent the same consolidated Step 2 dataset for development. The
application is a universal travel-planning UX over user-loaded POI data; Rome is only
its playful empty-state fallback. Imported records stay read-only while additional
files may be merged or used as replacements. The design phase is UX-led and its
scoring rubric is intentionally deferred.

## What is implemented

- Lossless storage of the complete submitted JSON text plus a raw JSON object for
  every imported POI.
- Flexible import of a root array, `pois[]`, `pointsOfInterest[]`, or GeoJSON Point
  features. Common camelCase and snake_case fields are normalized without changing
  the source record.
- SQLite tables for submissions, POI records, external identifiers, tags, links,
  images, ratings, evidence, URL checks, canonical POIs, matches, conflicts, review
  queue items, and evaluation runs.
- Deterministic matching across different submissions using exact external IDs,
  normalized names, geographic distance, and fuzzy name similarity.
- Explicit identity relations: `same_place`, `part_of`, `contains`, `related`,
  `different_place`, and `uncertain`.
- Automatic canonical groups for high-confidence `same_place` matches. Conflicting
  category, subcategory, and coordinate values become review items rather than being
  silently overwritten.
- HTTP `HEAD` validation with bounded `GET` fallback, redirect history, timeouts,
  MIME checks, structured status values, and review-queue integration.
- JSON, JSONL, and CSV review exports plus a deterministic JSON summary report.
- LLM review request/result contracts and a versioned content-review prompt.
- A versioned canonical export contract for safe and detailed POI datasets, including
  provider-neutral rating scales and explicit media-rights states. The exporter that
  resolves reviewed records into this contract remains the next implementation step.

## Requirements and setup

Python 3.9 or newer is the only runtime requirement. The core has no third-party
dependencies.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
poi-evaluator --help
```

All commands accept `--db` and optional `--config` before the subcommand:

```bash
poi-evaluator --db work/evaluation.sqlite --config config.example.json init-db
```

## Typical pipeline

Import any number of independent submissions. Agent labels should be stable and must
not expose model identity to later blind qualitative reviewers.

```bash
poi-evaluator --db work/evaluation.sqlite import data/agent-a.json --agent submission-a
poi-evaluator --db work/evaluation.sqlite import data/agent-b.json --agent submission-b
poi-evaluator --db work/evaluation.sqlite match
poi-evaluator --db work/evaluation.sqlite validate-urls
poi-evaluator --db work/evaluation.sqlite export-review outputs/review-queue.jsonl
poi-evaluator --db work/evaluation.sqlite report outputs/report.json
poi-evaluator --db work/evaluation.sqlite agent-report outputs/agent-evaluation.json \
  --markdown outputs/agent-evaluation.md
poi-evaluator --db work/evaluation.sqlite export-canonical \
  --safe-output outputs/canonical-poi-v1.safe.json \
  --detailed-output outputs/canonical-poi-v1.detailed.json \
  --audit-output outputs/canonical-export-audit.json \
  --dataset-version rome-canonical-v1
```

The canonical export deliberately omits entities involved in unresolved identity
matches or open high-severity conflicts. The safe profile contains only media with
complete permissive-license attribution and ratings whose source URL passed the URL
validator. The detailed profile retains media and ratings with explicit rights and
verification states. Both outputs preserve record-level provenance, while the audit
file records every exclusion and aggregate count.

URL validation resumes by default, deduplicates equal URLs, and uses bounded
concurrency. The limits can be adjusted without changing the stored contract:

```bash
poi-evaluator --db work/evaluation.sqlite validate-urls --workers 16 --per-host 4
```

The same deterministic sequence is available as one command:

```bash
poi-evaluator --db work/evaluation.sqlite pipeline \
  --submission submission-a=data/agent-a.json \
  --submission submission-b=data/agent-b.json \
  --validate-urls \
  --report outputs/report.json \
  --review outputs/review-queue.jsonl
```

Run the included offline example without network checks:

```bash
poi-evaluator --db work/demo.sqlite pipeline \
  --submission agent-a=examples/agent-a.json \
  --submission agent-b=examples/agent-b.json
```

Reviewers can resolve an identity candidate without editing SQL directly:

```bash
poi-evaluator --db work/evaluation.sqlite resolve-match 42 part_of --reviewer reviewer-1
```

Every matching and URL-validation invocation creates an `evaluation_runs` row with
its effective configuration, completion state, and summary. This makes repeated
runs auditable.

The agent report compares each submission by field coverage, description diagnostics,
URL outcomes, cross-agent corroboration, and shared conflicts. Its provisional score
is deliberately limited to deterministic signals: 50% structural completeness, 30%
URL success among conclusive checks, and 20% conclusive URL coverage. Rate limiting,
timeouts, and network failures are reported as inconclusive. Factual accuracy,
writing quality, image identity, licensing validity, and relevance remain outside
that score until the evidence-backed review phase is run.

## Import behavior

The import transaction fails as a unit when a record has no usable name, coordinates
fall outside WGS84 bounds, or IDs repeat inside one submission. A missing POI ID is
assigned a stable positional ID such as `row-12` for that immutable source file.

The database keeps two representations:

- `submissions.raw_document_json` is the exact UTF-8 text that was read from disk.
- `poi_records.raw_json` is the complete submitted POI object serialized as JSON;
  `normalized_json` and searchable columns hold derived values.

Original files are never edited. The source path and SHA-256 digest are recorded.
The pair `(agent_name, source_sha256)` prevents accidental duplicate imports.

## Matching rules

Matching only compares records from different submissions.

1. A shared external ID and namespace produces an auto-accepted `same_place` match.
2. An identical normalized name within the configured exact distance produces an
   auto-accepted `same_place` match.
3. An identical name without compatible coordinates remains `uncertain`.
4. A sufficiently similar name within the fuzzy distance becomes an `uncertain`
   candidate for review.

Nearby coordinates alone never create a match. This protects relationships such as
a museum inside a palace or a crypt inside a church. A reviewer can explicitly set
`part_of`, `contains`, `related`, `different_place`, or `uncertain`.

The defaults live in [config.example.json](config.example.json). Distances are in
metres and can be changed for any city or region.

## URL validation and SSRF protection

Each hop is parsed and DNS-resolved before a request. The validator rejects:

- schemes other than HTTP and HTTPS;
- URLs containing credentials;
- localhost names;
- every loopback, private, link-local, multicast, reserved, or otherwise non-global
  IP address returned by DNS;
- redirects to any blocked destination.

The transport connects to the already approved IP and keeps the original hostname
for the HTTP `Host` header and TLS certificate/SNI verification. This prevents a
second DNS lookup from bypassing the address check. Response bodies are bounded and
only a small prefix is read for `GET` checks.

Statuses are `reachable`, `redirected`, `not_found`, `blocked`, `rate_limited`,
`timeout`, `invalid_url`, `mime_mismatch`, `network_error`, or `unverified`. A 403 or
429 is kept distinct from a broken link. Direct image URLs must return an image MIME
type; page-like URLs accept normal text, JSON, PDF, or generic binary content.

Equal URLs with the same MIME expectation are requested once and the result is
written to every corresponding target. Existing results are reused when a run is
resumed or when another page-like target references a URL checked earlier. Validation
uses bounded worker and per-host limits, commits progress every 100 unique checks,
and processes completed requests without allowing one slow server to block database
writes. `--no-resume` explicitly requests a fresh check. Automatic retry policy is
left for a later iteration because `403` and `429` responses need separate handling
from transient network failures.

## Database and contracts

The complete migration is [schema/001_initial.sql](schema/001_initial.sql). It uses
foreign keys, constraints, and indexes while retaining JSON payloads for fields that
may evolve.

Qualitative review integration consists of:

- [src/poi_evaluator/review_contract.py](src/poi_evaluator/review_contract.py) — the
  provider interface;
- [contracts/llm-review-request.schema.json](contracts/llm-review-request.schema.json)
  and [contracts/llm-review-result.schema.json](contracts/llm-review-result.schema.json)
  — machine-readable input/output contracts;
- [prompts/content-review.md](prompts/content-review.md) — a blind-review prompt that
  requires evidence and keeps all six identity relations.

The planned canonical handoff is documented in [CANONICAL_EXPORT.md](CANONICAL_EXPORT.md)
and validated by [contracts/canonical-poi-v1.schema.json](contracts/canonical-poi-v1.schema.json).
Current media-license counts and their limitations are recorded in
[MEDIA_LICENSE_AUDIT.md](MEDIA_LICENSE_AUDIT.md).

## Tests

The test suite uses only the standard library and performs no network requests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

It covers normalization, raw-data preservation, child-table extraction, canonical
matching, review resolution, report export, HEAD-to-GET fallback, redirect tracking,
MIME mismatch, and blocking of direct or redirected private-network targets.

## Current scope

This iteration does not claim that reachable content belongs to the POI, that a
description is factually correct, or that an image depicts the place. Those checks
belong to the later evidence-backed qualitative review. Matching thresholds are
candidates for calibration on real benchmark submissions; external-ID matches are
still auditable rather than treated as unquestionable truth.
