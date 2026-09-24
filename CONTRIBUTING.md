# Contributing

Keep the three benchmark steps independent. A change belongs in the earliest step
that owns the behavior:

- discovery and source-data requirements belong in `01-discovery`;
- deterministic validation, reconciliation, and consolidation belong in
  `02-evaluation`;
- product behavior and design requirements belong in `03-ui-benchmark`.

Do not commit real agent submissions, evaluation databases, generated reports, API
credentials, private development datasets, or downloaded POI media. Use synthetic
fixtures for regression tests.

Run the relevant offline tests before submitting a change. Network-dependent checks
must remain explicit and auditable.
